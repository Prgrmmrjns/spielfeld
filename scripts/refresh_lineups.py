#!/usr/bin/env python3
"""Deploy-time / local lineup refresh (API-Football when keyed, else Wikipedia)."""
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
        print("refresh_lineups: no API_FOOTBALL_KEY — using Wikipedia squads")
    from app.lineups import persist_lineups_into_predictions

    payload = persist_lineups_into_predictions()
    for p in payload.get("predictions") or []:
        lu = p.get("lineups") or {}
        h, a = lu.get("home") or {}, lu.get("away") or {}
        print(
            f"XI {p.get('home_short')} vs {p.get('away_short')}: "
            f"{h.get('source')}/{a.get('source')} "
            f"pool {len(h.get('pool') or [])}/{len(a.get('pool') or [])} "
            f"wiki {h.get('wiki_season')}/{a.get('wiki_season')}"
        )
    print(
        f"refresh_lineups: provider={payload.get('lineups_provider')} "
        f"matches={len(payload.get('predictions') or [])} "
        f"wiki_seasons={payload.get('wiki_seasons')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
