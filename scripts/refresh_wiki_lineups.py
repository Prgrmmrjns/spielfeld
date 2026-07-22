#!/usr/bin/env python3
"""Refresh baked predictions with Wikipedia 2025–27 squads / estimated XIs + benches."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.lineups import persist_lineups_into_predictions


def main():
    payload = persist_lineups_into_predictions()
    preds = payload.get("predictions") or []
    print(f"provider={payload.get('lineups_provider')} wiki_seasons={payload.get('wiki_seasons')}")
    print(payload.get("lineups_note") or "")
    for p in preds[:3]:
        h = (p.get("lineups") or {}).get("home") or {}
        print(
            f"  {p.get('home_short')}: src={h.get('source')} season={h.get('wiki_season')} "
            f"xi={len(h.get('players') or [])} pool={len(h.get('pool') or [])} "
            f"names={[x.get('name') for x in (h.get('players') or [])[:4]]}"
        )
    print(f"refresh_wiki_lineups: {len(preds)} matches")


if __name__ == "__main__":
    main()
