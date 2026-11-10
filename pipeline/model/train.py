"""LightGBM 1X2 model with walk-forward validation, calibration, and bookmaker blend."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import TimeSeriesSplit

from pipeline.features.build import FEATURE_GROUPS, all_feature_columns, build_feature_matrix
from pipeline.paths import ARTIFACTS, MODELS, PROCESSED

LABELS = ["H", "D", "A"]
NON_ODDS_GROUPS = [g for g in FEATURE_GROUPS if g != "odds"]


def non_odds_features(cols: list[str] | None = None) -> list[str]:
    allowed = []
    for g in NON_ODDS_GROUPS:
        allowed.extend(FEATURE_GROUPS[g])
    if cols:
        return [c for c in cols if c in allowed]
    return allowed


def _brier_multiclass(y_true: np.ndarray, proba: np.ndarray) -> float:
    y_oh = np.eye(3)[y_true.astype(int)]
    return float(np.mean(np.sum((proba - y_oh) ** 2, axis=1)))


def _metrics(y_true: np.ndarray, proba: np.ndarray, name: str) -> dict:
    pred = proba.argmax(axis=1)
    return {
        "name": name,
        "n": int(len(y_true)),
        "log_loss": float(log_loss(y_true, proba, labels=[0, 1, 2])),
        "brier": _brier_multiclass(y_true, proba),
        "accuracy": float(accuracy_score(y_true, pred)),
    }


def bookmaker_baseline(df: pd.DataFrame) -> np.ndarray:
    p = np.array(df[["imp_home", "imp_draw", "imp_away"]].to_numpy(dtype=float), copy=True)
    mask = np.isnan(p).any(axis=1)
    p[mask] = np.array([1 / 3, 1 / 3, 1 / 3])
    p = p / p.sum(axis=1, keepdims=True)
    return p


def elo_only_baseline(df: pd.DataFrame, home_adv: float = 60.0) -> np.ndarray:
    eh = df["elo_home"].to_numpy(dtype=float)
    ea = df["elo_away"].to_numpy(dtype=float)
    exp_h = 1.0 / (1.0 + 10 ** ((ea - (eh + home_adv)) / 400.0))
    home = exp_h * (1 - 0.26)
    away = (1 - exp_h) * (1 - 0.26)
    draw = np.full_like(home, 0.26)
    p = np.vstack([home, draw, away]).T
    return p / p.sum(axis=1, keepdims=True)


def make_model(seed: int = 42) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        objective="multiclass",
        num_class=3,
        n_estimators=250,
        learning_rate=0.03,
        num_leaves=15,
        max_depth=4,
        subsample=0.85,
        colsample_bytree=0.7,
        min_child_samples=60,
        reg_alpha=0.5,
        reg_lambda=2.0,
        random_state=seed,
        verbosity=-1,
    )


def _align_proba(model, proba: np.ndarray) -> np.ndarray:
    ordered = np.zeros((proba.shape[0], 3))
    for j, c in enumerate(model.classes_):
        ordered[:, int(c)] = proba[:, j]
    return ordered


def _blend(p_model: np.ndarray, p_book: np.ndarray, w: float) -> np.ndarray:
    out = (1 - w) * p_model + w * p_book
    return out / out.sum(axis=1, keepdims=True)


def _learn_blend_weight(y: np.ndarray, p_model: np.ndarray, p_book: np.ndarray) -> float:
    best_w, best_ll = 0.5, 1e9
    for w in np.linspace(0.0, 1.0, 21):
        ll = log_loss(y, _blend(p_model, p_book, w), labels=[0, 1, 2])
        if ll < best_ll:
            best_ll, best_w = ll, float(w)
    return best_w


def walk_forward(df: pd.DataFrame, feature_cols: list[str] | None = None) -> dict:
    # Prefer non-odds engineered features; blend with market separately.
    feature_cols = non_odds_features(feature_cols or all_feature_columns())
    finished = df[df["y"].notna()].copy().sort_values("kickoff")
    for c in feature_cols:
        finished[c] = pd.to_numeric(finished[c], errors="coerce")

    seasons = sorted(finished["season_year"].unique())
    min_train_seasons = 3
    oof_rows = []
    fold_metrics = []
    blend_weights = []

    for i, test_season in enumerate(seasons):
        if i < min_train_seasons:
            continue
        train = finished[finished["season_year"] < test_season]
        test = finished[finished["season_year"] == test_season]
        if len(test) < 20 or len(train) < 200:
            continue

        # inner split for blend weight: last train season as val
        val_season = train["season_year"].max()
        fit = train[train["season_year"] < val_season]
        val = train[train["season_year"] == val_season]
        if len(fit) < 150:
            fit, val = train.iloc[: int(len(train) * 0.8)], train.iloc[int(len(train) * 0.8) :]

        model = make_model()
        model.fit(fit[feature_cols], fit["y"].astype(int))
        p_val = _align_proba(model, model.predict_proba(val[feature_cols]))
        w = _learn_blend_weight(val["y"].astype(int).to_numpy(), p_val, bookmaker_baseline(val))
        blend_weights.append(w)

        # refit on all train
        model.fit(train[feature_cols], train["y"].astype(int))
        p_model = _align_proba(model, model.predict_proba(test[feature_cols]))
        p_book = bookmaker_baseline(test)
        p_blend = _blend(p_model, p_book, w)
        y_test = test["y"].astype(int).to_numpy()

        fold_metrics.extend(
            [
                {**_metrics(y_test, p_blend, f"blend_{test_season}"), "season": int(test_season), "blend_w": w},
                {**_metrics(y_test, p_model, f"lgbm_{test_season}"), "season": int(test_season)},
                {**_metrics(y_test, p_book, f"book_{test_season}"), "season": int(test_season)},
                {**_metrics(y_test, elo_only_baseline(test), f"elo_{test_season}"), "season": int(test_season)},
            ]
        )

        for idx, (_, row) in enumerate(test.iterrows()):
            oof_rows.append(
                {
                    "match_uid": row["match_uid"],
                    "season_year": int(row["season_year"]),
                    "kickoff": str(row["kickoff"]),
                    "home_slug": row["home_slug"],
                    "away_slug": row["away_slug"],
                    "y": int(row["y"]),
                    "p_home": float(p_blend[idx, 0]),
                    "p_draw": float(p_blend[idx, 1]),
                    "p_away": float(p_blend[idx, 2]),
                    "model_home": float(p_model[idx, 0]),
                    "model_draw": float(p_model[idx, 1]),
                    "model_away": float(p_model[idx, 2]),
                    "book_home": float(p_book[idx, 0]),
                    "book_draw": float(p_book[idx, 1]),
                    "book_away": float(p_book[idx, 2]),
                    "elo_home_p": float(elo_only_baseline(test.iloc[[idx]])[0, 0]),
                    "elo_draw_p": float(elo_only_baseline(test.iloc[[idx]])[0, 1]),
                    "elo_away_p": float(elo_only_baseline(test.iloc[[idx]])[0, 2]),
                    "correct": int(p_blend[idx].argmax() == row["y"]),
                    "blend_w": w,
                }
            )

    oof = pd.DataFrame(oof_rows)
    overall = {}
    if len(oof):
        y = oof["y"].to_numpy()
        overall["model"] = _metrics(y, oof[["p_home", "p_draw", "p_away"]].to_numpy(), "blend_oof")
        overall["lgbm_only"] = _metrics(y, oof[["model_home", "model_draw", "model_away"]].to_numpy(), "lgbm_oof")
        overall["elo"] = _metrics(y, oof[["elo_home_p", "elo_draw_p", "elo_away_p"]].to_numpy(), "elo_oof")
        overall["bookmaker"] = _metrics(y, oof[["book_home", "book_draw", "book_away"]].to_numpy(), "book_oof")
        frac, mean = calibration_curve((y == 0).astype(int), oof["p_home"].to_numpy(), n_bins=8, strategy="quantile")
        overall["calibration_home"] = {
            "fraction_positives": frac.tolist(),
            "mean_predicted": mean.tolist(),
        }
        overall["mean_blend_weight"] = float(np.mean(blend_weights)) if blend_weights else None

    # Final model on all finished + blend weight from last fold / mean
    X_all = finished[feature_cols]
    y_all = finished["y"].astype(int)
    final = make_model()
    final.fit(X_all, y_all)
    # learn blend on last two seasons holdout style
    if len(seasons) >= 2:
        fit = finished[finished["season_year"] < seasons[-1]]
        val = finished[finished["season_year"] == seasons[-1]]
        tmp = make_model()
        tmp.fit(fit[feature_cols], fit["y"].astype(int))
        p_val = _align_proba(tmp, tmp.predict_proba(val[feature_cols]))
        blend_w = _learn_blend_weight(val["y"].astype(int).to_numpy(), p_val, bookmaker_baseline(val))
    else:
        blend_w = float(np.mean(blend_weights)) if blend_weights else 0.7

    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": final, "features": feature_cols, "blend_weight": blend_w},
        MODELS / "lgbm_1x2.joblib",
    )

    importance = pd.DataFrame(
        {"feature": feature_cols, "importance": final.feature_importances_}
    ).sort_values("importance", ascending=False)

    result = {
        "fold_metrics": fold_metrics,
        "overall": overall,
        "feature_importance": importance.to_dict(orient="records"),
        "feature_cols": feature_cols,
        "blend_weight": blend_w,
        "n_train": int(len(finished)),
        "notes": (
            "LightGBM trains on non-odds features only; final probabilities are a "
            "learned blend with bookmaker implied odds to preserve market calibration."
        ),
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "metrics.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    oof.to_csv(ARTIFACTS / "oof_predictions.csv", index=False)
    oof.to_json(ARTIFACTS / "oof_predictions.json", orient="records", date_format="iso")
    importance.to_csv(ARTIFACTS / "feature_importance.csv", index=False)
    return result


if __name__ == "__main__":
    path = PROCESSED / "features.csv"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["kickoff"])
    else:
        df = build_feature_matrix()
    res = walk_forward(df)
    print(json.dumps(res["overall"], indent=2, default=str))
