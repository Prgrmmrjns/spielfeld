"""Generate upcoming matchday forecasts + track-record summary."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from pipeline.features.build import all_feature_columns
from pipeline.paths import ARTIFACTS, MODELS, PROCESSED
from pipeline.team_map import DISPLAY_NAMES


def _load_bundle():
    return joblib.load(MODELS / "lgbm_1x2.joblib")


def predict_upcoming(df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df is None:
        df = pd.read_csv(PROCESSED / "features.csv", parse_dates=["kickoff"])
    bundle = _load_bundle()
    model = bundle["model"]
    cols = bundle["features"]

    # Prefer selected features from ablation if present
    abl_path = ARTIFACTS / "ablation.json"
    if abl_path.exists():
        selected = json.loads(abl_path.read_text(encoding="utf-8")).get("selected_features")
        if selected:
            cols = [c for c in selected if c in df.columns]

    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    upcoming = df[df["y"].isna()].copy().sort_values("kickoff")
    if upcoming.empty:
        # also include not-yet-finished with null FTR
        upcoming = df[~df["finished"].fillna(False)].copy().sort_values("kickoff")

    # Current matchday = earliest upcoming matchday in current season
    if upcoming.empty:
        return upcoming

    cur_season = upcoming["season_year"].max()
    season_up = upcoming[upcoming["season_year"] == cur_season]
    matchday = int(season_up["matchday"].min()) if season_up["matchday"].notna().any() else None
    if matchday is not None:
        slate = season_up[season_up["matchday"] == matchday].copy()
    else:
        slate = season_up.head(9).copy()

    # Also keep next few matchdays for browsing
    future = season_up.copy()
    proba = model.predict_proba(future[cols].astype(float))
    ordered = np.zeros_like(proba)
    for j, c in enumerate(model.classes_):
        ordered[:, int(c)] = proba[:, j]

    # blend with bookmaker when available
    w = float(bundle.get("blend_weight", 0.6))
    book = np.array(future[["imp_home", "imp_draw", "imp_away"]].to_numpy(dtype=float), copy=True)
    mask = np.isnan(book).any(axis=1)
    book[mask] = ordered[mask]
    book = book / np.clip(book.sum(axis=1, keepdims=True), 1e-9, None)
    blended = (1 - w) * ordered + w * book
    blended = blended / blended.sum(axis=1, keepdims=True)

    future["p_home"] = blended[:, 0]
    future["p_draw"] = blended[:, 1]
    future["p_away"] = blended[:, 2]
    future["pick"] = future[["p_home", "p_draw", "p_away"]].idxmax(axis=1).map(
        {"p_home": "H", "p_draw": "D", "p_away": "A"}
    )
    future["home_display"] = future["home_slug"].map(DISPLAY_NAMES)
    future["away_display"] = future["away_slug"].map(DISPLAY_NAMES)

    # key drivers: largest |feature - train median| * importance for top features
    importance_path = ARTIFACTS / "feature_importance.csv"
    if importance_path.exists():
        imp = pd.read_csv(importance_path).set_index("feature")["importance"]
    else:
        imp = pd.Series(model.feature_importances_, index=bundle["features"])

    finished = df[df["y"].notna()]
    med = finished[cols].median()
    drivers = []
    for _, row in future.iterrows():
        deltas = []
        for c in cols:
            if c not in imp.index:
                continue
            val = row[c]
            if pd.isna(val):
                continue
            score = abs(float(val) - float(med.get(c, val))) * float(imp.get(c, 0))
            deltas.append({"feature": c, "value": float(val), "score": score})
        deltas.sort(key=lambda x: -x["score"])
        drivers.append(deltas[:8])
    future["drivers"] = drivers

    out = future[
        [
            "match_uid", "ol_match_id", "season_year", "season_label", "matchday",
            "kickoff", "home_slug", "away_slug", "home_display", "away_display",
            "home_icon", "away_icon", "p_home", "p_draw", "p_away", "pick",
            "imp_home", "imp_draw", "imp_away", "elo_home", "elo_away", "elo_diff",
            "drivers",
        ]
    ].copy()
    # serialize
    records = []
    for _, r in out.iterrows():
        records.append(
            {
                **{k: (None if pd.isna(v) else v) for k, v in r.items() if k != "drivers"},
                "kickoff": str(r["kickoff"]),
                "drivers": r["drivers"],
                "is_current_matchday": bool(matchday is not None and r["matchday"] == matchday),
            }
        )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season_year": int(cur_season),
        "current_matchday": matchday,
        "matches": records,
    }
    (ARTIFACTS / "forecasts.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def build_track_record() -> dict:
    oof_path = ARTIFACTS / "oof_predictions.json"
    if not oof_path.exists():
        return {"matches": [], "summary": {}}
    oof = pd.read_json(oof_path)
    oof["pick"] = oof[["p_home", "p_draw", "p_away"]].idxmax(axis=1).map(
        {"p_home": "H", "p_draw": "D", "p_away": "A"}
    )
    oof["actual"] = oof["y"].map({0: "H", 1: "D", 2: "A"})
    summary = {
        "n": int(len(oof)),
        "accuracy": float(oof["correct"].mean()) if len(oof) else None,
        "by_season": oof.groupby("season_year")["correct"].mean().astype(float).to_dict(),
    }
    # enrich names
    feat = pd.read_csv(PROCESSED / "features.csv", usecols=["match_uid", "home_slug", "away_slug", "home_name", "away_name", "FTHG", "FTAG", "matchday"])
    merged = oof.merge(feat, on="match_uid", how="left", suffixes=("", "_f"))
    records = []
    for _, r in merged.sort_values("kickoff", ascending=False).head(120).iterrows():
        records.append(
            {
                "match_uid": r["match_uid"],
                "kickoff": str(r["kickoff"]),
                "season_year": int(r["season_year"]),
                "home_slug": r["home_slug"],
                "away_slug": r["away_slug"],
                "home_name": DISPLAY_NAMES.get(r["home_slug"], r.get("home_name")),
                "away_name": DISPLAY_NAMES.get(r["away_slug"], r.get("away_name")),
                "p_home": float(r["p_home"]),
                "p_draw": float(r["p_draw"]),
                "p_away": float(r["p_away"]),
                "pick": r["pick"],
                "actual": r["actual"],
                "correct": bool(r["correct"]),
                "score": f"{int(r['FTHG'])}:{int(r['FTAG'])}" if pd.notna(r.get("FTHG")) else None,
            }
        )
    out = {"summary": summary, "matches": records}
    (ARTIFACTS / "track_record.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    predict_upcoming()
    print(build_track_record()["summary"])
