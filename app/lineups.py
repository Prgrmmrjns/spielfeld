"""Live / deploy-time lineup helpers (API-Football + Wikipedia squads)."""
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
from wiki_squads import WikiSquads, enrich_side_with_wiki

DATA_CANDIDATES = [
    ROOT / "app" / "data" / "predictions.json",
    ROOT / "public" / "data" / "predictions.json",
    ROOT / "predictions.json",
]


def load_predictions() -> dict:
    from app.shap_iq import enrich_payload

    for path in DATA_CANDIDATES:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return enrich_payload(payload)
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


def _stale_api_season(season: int | None) -> bool:
    """Free API-Football plans often stop at 2024 — treat that as stale for 2026 UI."""
    if season is None:
        return True
    return int(season) < 2025


def _apply_wiki(home: dict, away: dict, match: dict, wiki: WikiSquads, replace: bool) -> tuple[dict, dict]:
    home = enrich_side_with_wiki(home, match["home_team"], wiki=wiki, replace_players=replace)
    away = enrich_side_with_wiki(away, match["away_team"], wiki=wiki, replace_players=replace)
    return home, away


def build_live_lineups(payload: dict | None = None) -> dict:
    payload = payload or load_predictions()
    preds = payload.get("predictions") or []
    key = os.getenv("API_FOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY") or os.getenv("API_SPORTS_KEY")
    wiki = WikiSquads(cache_path=ROOT / "wiki_squads_cache.json")
    out: dict[str, dict] = {}
    provider = None
    season = None
    note = None

    if key:
        af = ApiFootball()
        season = _accessible_season(af, _current_season())
        stale = _stale_api_season(season)
        try:
            af.ensure_teams(season)
            af.ensure_fixtures(season)
        except Exception as exc:
            note = f"API-Football prep failed: {exc}"
            stale = True
        provider = "api-football"
        if stale:
            note = (note + "; " if note else "") + (
                f"API season {season} is older than 2025 — using Wikipedia 2025–27 squads for XI/bench"
            )

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

            home = af.serialize_side(packed.get("home") or {}, season)
            away = af.serialize_side(packed.get("away") or {}, season)
            baked = p.get("lineups") or {}
            if not home.get("players") and baked.get("home", {}).get("players"):
                home = {**baked["home"]}
            if not away.get("players") and baked.get("away", {}).get("players"):
                away = {**baked["away"]}

            # Replace XI when API data is from an old season; always attach wiki bench pool
            home, away = _apply_wiki(home, away, p, wiki, replace=stale)
            out[str(mid)] = {
                "api_fixture_id": packed.get("fixture_id") or (fx.get("id") if fx else None),
                "home": home,
                "away": away,
            }
        try:
            af.save()
        except Exception:
            pass
    else:
        provider = "footballsquads"
        note = "No API_FOOTBALL_KEY — footballsquads.co.uk (+ Wikipedia fallback) 2025–27 for XI + bench"
        for p in preds:
            mid = p.get("match_id")
            if mid is None:
                continue
            baked = p.get("lineups") or {}
            home = dict(baked.get("home") or {})
            away = dict(baked.get("away") or {})
            # Always refresh from wiki so we drop stale 2024 last_xi baked into JSON
            home, away = _apply_wiki(home, away, p, wiki, replace=True)
            out[str(mid)] = {
                "api_fixture_id": baked.get("api_fixture_id"),
                "home": home,
                "away": away,
            }

    wiki_seasons = sorted({
        (side.get("wiki_season") or "")
        for row in out.values()
        for side in (row.get("home") or {}, row.get("away") or {})
        if side.get("wiki_season")
    })

    return {
        "provider": provider,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "wiki_seasons": wiki_seasons,
        "note": note,
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
            p["lineups"] = row
    payload["lineups_provider"] = live.get("provider")
    payload["lineups_refreshed_at"] = live.get("refreshed_at")
    payload["lineups_note"] = live.get("note")
    payload["wiki_seasons"] = live.get("wiki_seasons")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for dest in (
        ROOT / "app" / "data" / "predictions.json",
        ROOT / "public" / "data" / "predictions.json",
        ROOT / "predictions.json",
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return payload
