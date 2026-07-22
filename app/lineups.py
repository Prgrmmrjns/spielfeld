"""Live / deploy-time lineup helpers (API-Football)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_football import ApiFootball, _accessible_season, _current_season

DATA_CANDIDATES = [
    ROOT / "app" / "data" / "predictions.json",
    ROOT / "public" / "data" / "predictions.json",
    ROOT / "predictions.json",
]


def load_predictions() -> dict:
    for path in DATA_CANDIDATES:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {
        "league": "Bundesliga",
        "season": "",
        "matchday": 0,
        "matchday_name": "Next Spieltag",
        "generated_at": "",
        "model": "unknown",
        "train_matches": 0,
        "predictions": [],
    }


def predictions_path() -> Path:
    for path in DATA_CANDIDATES:
        if path.exists():
            return path
    path = DATA_CANDIDATES[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_live_lineups(payload: dict | None = None) -> dict:
    payload = payload or load_predictions()
    preds = payload.get("predictions") or []
    key = os.getenv("API_FOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY") or os.getenv("API_SPORTS_KEY")
    if not key:
        return {
            "provider": None,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "note": "Set API_FOOTBALL_KEY for live lineups",
            "lineups": {
                str(p.get("match_id")): p.get("lineups")
                for p in preds
                if p.get("match_id") is not None
            },
        }

    af = ApiFootball()
    season = _accessible_season(af, _current_season())
    af.ensure_teams(season)
    af.ensure_fixtures(season)

    out: dict[str, dict] = {}
    for p in preds:
        mid = p.get("match_id")
        if mid is None:
            continue
        fx = None
        try:
            fx = af.find_fixture(p["home_team"], p["away_team"], p.get("date"), season=season)
        except Exception:
            fx = None
        hid = af.resolve_team_id(p["home_team"])
        aid = af.resolve_team_id(p["away_team"])
        try:
            packed = af.lineup_for_fixture(fx.get("id") if fx else None, hid, aid)
        except Exception:
            packed = {
                "home": {"source": "unknown", "formation": None, "players": []},
                "away": {"source": "unknown", "formation": None, "players": []},
                "fixture_id": None,
            }

        def side(block: dict) -> dict:
            players = block.get("players") or []
            # Prefer baked prediction lineup if API returned empty
            return {
                "source": block.get("source") or "unknown",
                "formation": block.get("formation"),
                "players": [
                    {
                        "id": pl.get("id"),
                        "name": pl.get("name"),
                        "number": pl.get("number"),
                        "pos": pl.get("pos"),
                    }
                    for pl in players
                ],
            }

        home = side(packed.get("home") or {})
        away = side(packed.get("away") or {})
        baked = p.get("lineups") or {}
        if not home["players"] and baked.get("home", {}).get("players"):
            home = {
                "source": baked["home"].get("source") or "last_xi",
                "formation": baked["home"].get("formation"),
                "players": baked["home"]["players"],
            }
        if not away["players"] and baked.get("away", {}).get("players"):
            away = {
                "source": baked["away"].get("source") or "last_xi",
                "formation": baked["away"].get("formation"),
                "players": baked["away"]["players"],
            }

        out[str(mid)] = {
            "api_fixture_id": packed.get("fixture_id") or (fx.get("id") if fx else None),
            "home": home,
            "away": away,
        }

    try:
        af.save()
    except Exception:
        pass

    return {
        "provider": "api-football",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "lineups": out,
    }


def persist_lineups_into_predictions(payload: dict | None = None) -> dict:
    """Update predictions JSON on disk with latest XIs (deploy / GH Action)."""
    payload = payload or load_predictions()
    live = build_live_lineups(payload)
    for p in payload.get("predictions") or []:
        mid = p.get("match_id")
        if mid is None:
            continue
        row = live.get("lineups", {}).get(str(mid))
        if row:
            # preserve strength if present
            baked = p.get("lineups") or {}
            if baked.get("home", {}).get("strength") is not None:
                row = {
                    **row,
                    "home": {**row["home"], "strength": baked["home"].get("strength")},
                    "away": {**row["away"], "strength": baked.get("away", {}).get("strength")},
                }
            p["lineups"] = row
    payload["lineups_provider"] = live.get("provider")
    payload["lineups_refreshed_at"] = live.get("refreshed_at")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for dest in (
        ROOT / "app" / "data" / "predictions.json",
        ROOT / "public" / "data" / "predictions.json",
        ROOT / "predictions.json",
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return payload
