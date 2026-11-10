#!/usr/bin/env python3
"""End-to-end weekly pipeline: ingest → features → train → ablation → forecast → DB sync."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

# Ensure repo root on path
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.export.db_sync import sync
from pipeline.features.build import build_feature_matrix
from pipeline.model.ablation import run_ablation, run_shap
from pipeline.model.forecast import build_track_record, predict_upcoming
from pipeline.model.player_impact import estimate_impacts
from pipeline.model.train import walk_forward
from pipeline.paths import ARTIFACTS


def main() -> int:
    t0 = time.time()
    print("==> Building feature matrix")
    df = build_feature_matrix()
    print(f"    rows={len(df)} finished={df['y'].notna().sum()}")

    print("==> Walk-forward training")
    metrics = walk_forward(df)
    print("    overall:", json.dumps(metrics.get("overall", {}), default=str)[:500])

    print("==> Feature-group ablation")
    ablation = run_ablation(df)
    print("    selected groups:", ablation.get("selected_groups"))

    print("==> Retrain final model on selected features")
    selected = ablation.get("selected_features")
    if selected:
        metrics = walk_forward(df, feature_cols=selected)

    print("==> SHAP importance")
    try:
        shap = run_shap(df)
        print("    top:", [f["feature"] for f in shap["features"][:5]])
    except Exception as e:
        print("    SHAP skipped:", e)

    print("==> Forecasts")
    predict_upcoming(df)
    build_track_record()

    print("==> Player impact")
    estimate_impacts(df)

    print("==> DB sync")
    db = sync()
    print("   ", db)

    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - t0, 1),
        "metrics": metrics.get("overall"),
        "selected_groups": ablation.get("selected_groups"),
        "findings": ablation.get("findings"),
        "db": db,
    }
    (ARTIFACTS / "pipeline_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print("==> Done in", summary["elapsed_sec"], "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
