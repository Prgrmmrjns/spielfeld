"""Spielfeld — FastAPI web UI for Bundesliga matchday tips."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.lineups import build_live_lineups, load_predictions, persist_lineups_into_predictions

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="Spielfeld", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

public_dir = ROOT / "public"
if public_dir.is_dir():
    # Mirror Vercel `public/` CDN paths for local `uvicorn`.
    css_dir = public_dir / "css"
    if css_dir.is_dir():
        app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
    js_dir = public_dir / "js"
    if js_dir.is_dir():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
    explanations = public_dir / "explanations"
    if explanations.is_dir():
        app.mount("/explanations", StaticFiles(directory=str(explanations)), name="explanations")
    data_dir = public_dir / "data"
    if data_dir.is_dir():
        app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")
    favicon = public_dir / "favicon.ico"
    if favicon.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon_route():
            from fastapi.responses import FileResponse
            return FileResponse(favicon)


def _pct(value: float) -> int:
    try:
        return int(round(float(value) * 100))
    except Exception:
        return 0


def _kickoff(date_str: str) -> str:
    from datetime import datetime, timezone
    try:
        raw = date_str if ("Z" in date_str or "+" in date_str) else f"{date_str}Z"
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # Europe/Berlin without zoneinfo dependency edge cases
        try:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo("Europe/Berlin"))
        except Exception:
            dt = dt.astimezone(timezone.utc)
        return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b, %H:%M')}"
    except Exception:
        return date_str


def _tip_label(match: dict) -> str:
    pred = match.get("predicted")
    if pred == "home_win":
        return match.get("home_short") or "Home"
    if pred == "away_win":
        return match.get("away_short") or "Away"
    return "Draw"


def _xi_label(match: dict) -> str | None:
    lineups = match.get("lineups") or {}
    h = (lineups.get("home") or {}).get("source")
    a = (lineups.get("away") or {}).get("source")
    if not h and not a:
        return None

    def lab(s: str | None) -> str:
        if s == "confirmed":
            return "confirmed"
        if s == "last_xi":
            return "last XI"
        if s == "squad_estimate":
            return "squad est."
        if s == "wiki_squad":
            return "wiki 25–27"
        if s == "squad_2026":
            return "squad 25–27"
        return "pending"

    return f"{lab(h)} · {lab(a)}"


templates.env.filters["pct"] = _pct
templates.env.filters["kickoff"] = _kickoff
templates.env.globals["tip_label"] = _tip_label
templates.env.globals["xi_label"] = _xi_label


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    payload = load_predictions()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "payload": payload,
            "payload_json": json.dumps(payload, ensure_ascii=False),
        },
    )


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    payload = load_predictions()
    return templates.TemplateResponse(
        request,
        "about.html",
        {"payload": payload},
    )


@app.get("/api/predictions")
async def api_predictions():
    return load_predictions()


@app.get("/api/lineups")
async def api_lineups():
    return build_live_lineups()


@app.get("/api/refresh-lineups")
async def api_refresh_lineups():
    """Cron + manual refresh. On writable FS, also persist into predictions JSON."""
    live = build_live_lineups()
    # Persist when not on a read-only serverless FS (local / Actions).
    if os.getenv("AF_PERSIST_LINEUPS", "0") == "1" or not os.getenv("VERCEL"):
        try:
            persist_lineups_into_predictions()
        except OSError:
            pass
    payload = load_predictions()
    matches = []
    for m in payload.get("predictions") or []:
        row = live.get("lineups", {}).get(str(m.get("match_id")))
        matches.append({
            "match_id": m.get("match_id"),
            "home_team": m.get("home_team"),
            "away_team": m.get("away_team"),
            "lineups": row or m.get("lineups"),
        })
    return {
        "ok": True,
        "provider": live.get("provider"),
        "refreshed_at": live.get("refreshed_at"),
        "season": live.get("season"),
        "note": live.get("note"),
        "match_count": len(matches),
        "matches": matches,
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True}
