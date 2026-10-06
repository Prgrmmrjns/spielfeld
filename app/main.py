"""Spielfeld — FastAPI app for the TabPFN what-if extension."""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="Spielfeld", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

public_dir = ROOT / "public"
if public_dir.is_dir():
    css_dir = public_dir / "css"
    if css_dir.is_dir():
        app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
    js_dir = public_dir / "js"
    if js_dir.is_dir():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
    data_dir = public_dir / "data"
    if data_dir.is_dir():
        app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")
    icon_svg = public_dir / "icon.svg"
    if icon_svg.exists():
        @app.get("/icon.svg", include_in_schema=False)
        async def icon_svg_route():
            from fastapi.responses import FileResponse
            return FileResponse(icon_svg, media_type="image/svg+xml")


DOMAINS = ("football", "glucose", "mortality")


def load_scenario(domain: str) -> dict | None:
    path = ROOT / "public" / "data" / "scenarios" / f"{domain}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def landing_context() -> dict:
    domains = []
    for name in DOMAINS:
        d = load_scenario(name) or {"domain": name, "title": name.title(), "instances": []}
        rows = []
        for it in d.get("instances") or []:
            s = next(iter(it["sides"].values())) if name == "football" else it
            best = s["best"]
            rows.append({
                "base": round(s["base"] * 100, 1), "best": round(best["value"] * 100, 1),
                "set": max(best["trials"], key=lambda t: t[1])[2].split(" + "),
            })
        domains.append({
            "domain": name, "title": d.get("title"), "question": d.get("question"),
            "model": (d.get("card") or {}).get("model"), "holdout": (d.get("card") or {}).get("holdout"),
            "rows": rows,
        })
    return {"domains": domains}


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", landing_context())


@app.get("/healthz")
async def healthz():
    return {"ok": True}
