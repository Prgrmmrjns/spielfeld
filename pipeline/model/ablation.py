"""Feature-group ablation and optional SHAP summaries."""

from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

from pipeline.features.build import FEATURE_GROUPS, all_feature_columns
from pipeline.model.train import _brier_multiclass, make_model
from pipeline.paths import ARTIFACTS, PROCESSED


def _eval_cols(df: pd.DataFrame, cols: list[str], min_train_seasons: int = 3) -> dict:
    finished = df[df["y"].notna()].copy().sort_values("kickoff")
    for c in cols:
        finished[c] = pd.to_numeric(finished[c], errors="coerce")
    seasons = sorted(finished["season_year"].unique())
    ys, ps = [], []
    for i, test_season in enumerate(seasons):
        if i < min_train_seasons:
            continue
        train = finished[finished["season_year"] < test_season]
        test = finished[finished["season_year"] == test_season]
        if len(test) < 20:
            continue
        model = make_model()
        model.fit(train[cols].astype(float), train["y"].astype(int))
        proba = model.predict_proba(test[cols].astype(float))
        ordered = np.zeros((len(test), 3))
        for j, c in enumerate(model.classes_):
            ordered[:, int(c)] = proba[:, j]
        ys.append(test["y"].astype(int).to_numpy())
        ps.append(ordered)
    if not ys:
        return {"log_loss": None, "brier": None, "accuracy": None, "n": 0}
    y = np.concatenate(ys)
    p = np.vstack(ps)
    return {
        "log_loss": float(log_loss(y, p, labels=[0, 1, 2])),
        "brier": _brier_multiclass(y, p),
        "accuracy": float(accuracy_score(y, p.argmax(1))),
        "n": int(len(y)),
    }


def run_ablation(df: pd.DataFrame | None = None) -> dict:
    if df is None:
        df = pd.read_csv(PROCESSED / "features.csv", parse_dates=["kickoff"])
    full_cols = all_feature_columns()
    results = {"full": _eval_cols(df, full_cols), "leave_one_group_out": {}, "group_only": {}}

    for group, cols in FEATURE_GROUPS.items():
        without = [c for c in full_cols if c not in cols]
        results["leave_one_group_out"][group] = {
            **_eval_cols(df, without),
            "removed": cols,
        }
        results["group_only"][group] = {
            **_eval_cols(df, cols),
            "features": cols,
        }

    # Delta vs full: positive delta_log_loss means removing group hurts (group is useful)
    full_ll = results["full"]["log_loss"]
    findings = []
    for group, res in results["leave_one_group_out"].items():
        delta = None if full_ll is None or res["log_loss"] is None else res["log_loss"] - full_ll
        findings.append(
            {
                "group": group,
                "delta_log_loss_when_removed": delta,
                "useful": bool(delta is not None and delta > 0.001),
                "leave_one_out": res,
                "alone": results["group_only"][group],
            }
        )
    findings.sort(key=lambda x: (x["delta_log_loss_when_removed"] is None, -(x["delta_log_loss_when_removed"] or 0)))
    results["findings"] = findings

    # Tree model uses non-odds groups; odds enter via explicit blend in train.py
    keep_groups = [
        f["group"]
        for f in findings
        if f["group"] != "odds" and (f["useful"] or f["group"] in ("elo", "form", "table"))
    ]
    if not keep_groups:
        keep_groups = [g for g in FEATURE_GROUPS if g != "odds"]
    selected = []
    for g in keep_groups:
        selected.extend(FEATURE_GROUPS[g])
    results["selected_groups"] = keep_groups
    results["selected_features"] = selected
    results["odds_usage"] = "blended_post_hoc"

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "ablation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # findings log markdown
    lines = ["# Feature findings\n", f"Full model log loss: **{full_ll:.4f}**\n" if full_ll else ""]
    lines.append("| Group | Δ log loss if removed | Useful | Alone log loss |")
    lines.append("|---|---:|:---:|---:|")
    for f in findings:
        d = f["delta_log_loss_when_removed"]
        alone = f["alone"]["log_loss"]
        d_s = f"{d:.4f}" if d is not None else "n/a"
        a_s = f"{alone:.4f}" if alone else "n/a"
        lines.append(
            f"| {f['group']} | {d_s} | {'yes' if f['useful'] else 'no'} | {a_s} |"
        )
    (ARTIFACTS / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def run_shap(df: pd.DataFrame | None = None, max_rows: int = 400) -> dict:
    """TreeSHAP mean |value| per feature on a recent finished sample."""
    import shap

    if df is None:
        df = pd.read_csv(PROCESSED / "features.csv", parse_dates=["kickoff"])
    ablation = json.loads((ARTIFACTS / "ablation.json").read_text(encoding="utf-8"))
    cols = ablation.get("selected_features") or all_feature_columns()
    # SHAP on tree features only (exclude pure odds group if selected)
    cols = [c for c in cols if c not in FEATURE_GROUPS.get("odds", [])]
    finished = df[df["y"].notna()].sort_values("kickoff").copy()
    for c in cols:
        finished[c] = pd.to_numeric(finished[c], errors="coerce")
    seasons = sorted(finished["season_year"].unique())
    train = finished[finished["season_year"] < seasons[-1]]
    sample = finished[finished["season_year"] == seasons[-1]].tail(max_rows)
    X_train = train[cols].astype(float)
    X_sample = sample[cols].astype(float)
    model = make_model()
    model.fit(X_train, train["y"].astype(int))
    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(X_sample)
    if isinstance(sv, list):
        mean_abs = np.mean([np.abs(s).mean(axis=0) for s in sv], axis=0)
    elif getattr(sv, "ndim", 0) == 3:
        mean_abs = np.abs(sv).mean(axis=(0, 2))
    else:
        mean_abs = np.abs(sv).mean(axis=0)
    mean_abs = np.asarray(mean_abs).reshape(-1)
    ranking = (
        pd.DataFrame({"feature": cols, "mean_abs_shap": mean_abs})
        .sort_values("mean_abs_shap", ascending=False)
        .to_dict(orient="records")
    )
    out = {"features": ranking, "n_samples": int(len(sample))}
    (ARTIFACTS / "shap_importance.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    df = pd.read_csv(PROCESSED / "features.csv", parse_dates=["kickoff"])
    ab = run_ablation(df)
    print("selected", ab["selected_groups"])
    print(run_shap(df)["features"][:8])
