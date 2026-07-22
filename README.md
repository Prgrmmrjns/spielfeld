# Spielfeld — Bundesliga Matchday Predictions

Predict the next Bundesliga Spieltag with engineered club features and a TabPFN (or calibrated gradient-boosting fallback) model. The web UI is a **FastAPI** app.

## Setup

```bash
git clone https://github.com/Prgrmmrjns/spielfeld.git
cd spielfeld
pip install -r requirements.txt          # FastAPI web
pip install -r requirements-ml.txt       # optional: run predict.py / SHAP
```

Put secrets in `.env`:

| Variable | Purpose |
|---|---|
| `TABPFN_API_KEY` / `TABPFN_TOKEN` | Prior Labs TabPFN (falls back to HistGradientBoosting) |
| `API_FOOTBALL_KEY` | [API-Football](https://www.api-football.com/) squads / starting XIs (league 78) |

## Web UI (FastAPI)

```bash
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

- `/` — matchday tips, XI sources, SHAP modal
- `/api/predictions` — baked predictions JSON
- `/api/lineups` — live API-Football XIs (confirmed, else last XI)
- `/api/refresh-lineups` — cron/manual refresh

```bash
# lineup-only refresh of baked JSON
python scripts/refresh_lineups.py
```

## Starting XIs (API-Football)

No scraping. Lineups come from API-Football:

1. **Confirmed** `/fixtures/lineups` when published
2. Else **last starting XI** from that club’s most recent finished match
3. Else a weak squad estimate (Python predict path)

Free plans often only expose seasons **2022–2024** and **10 req/min** — the client falls back automatically.

Refresh paths:

- **Vercel deploy** — `python scripts/refresh_lineups.py` in `buildCommand`
- **Hourly cron** — `GET /api/refresh-lineups`
- **Browser** — polls `/api/lineups` every 15 min
- **GitHub Action** — full `predict.py` rebuild (needs secrets)

## Vercel

FastAPI entrypoint: `app/main.py` (`app` instance). Static assets live in `public/` (CSS, SHAP plots, favicon).

Set project env `API_FOOTBALL_KEY` (and optionally `TABPFN_API_KEY` for Actions only).

## Predict next matchday

```bash
python predict.py
python predict.py --refresh            # re-download OpenLigaDB history
python predict.py --skip-shap
python predict.py --skip-lineups
```

Writes `predictions.json`, copies into `app/data/` + `public/data/`, and SHAP plots into `public/explanations/`.

## Features

| Feature | Description |
|---|---|
| `elo_diff` | ELO gap with home advantage |
| `form5_diff` / `form10_diff` | Points-per-game form gaps |
| `home_gf5` / `home_ga5` | Recent goals for / against |
| `h2h_*` | Head-to-head win/draw/goal-diff stats |
| `home_rest` / `away_rest` | Days since last match |
| `value_diff` | Approximate Transfermarkt squad-value gap |
| `home_xi_strength` / `away_xi_strength` / `xi_strength_diff` | API-Football XI strength |
| `home_xi_confirmed` / `away_xi_confirmed` | 1 if published lineup, else 0 |

Data: [OpenLigaDB](https://www.openligadb.de/) (`bl1`) + [API-Football](https://www.api-football.com/).
