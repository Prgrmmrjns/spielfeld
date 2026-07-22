#!/usr/bin/env python3
"""Deploy-time / local lineup refresh via API-Football."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    key = os.getenv("API_FOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY") or os.getenv("API_SPORTS_KEY")
    if not key:
        print("refresh_lineups: no API_FOOTBALL_KEY — skipping")
        return 0
    from app.lineups import persist_lineups_into_predictions

    payload = persist_lineups_into_predictions()
    for p in payload.get("predictions") or []:
        lu = p.get("lineups") or {}
        h = (lu.get("home") or {}).get("source", "unknown")
        a = (lu.get("away") or {}).get("source", "unknown")
        print(f"XI {p.get('home_short')} vs {p.get('away_short')}: {h}/{a}")
    print(f"refresh_lineups: updated predictions ({len(payload.get('predictions') or [])} matches)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
