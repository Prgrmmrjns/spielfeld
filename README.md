<p align="center">
  <img src="public/icon.svg" width="96" height="96" alt="Spielfeld" />
</p>

# Spielfeld

Bundesliga matchday tips with TabPFN, live XIs, an 11v11 pitch board, and ShapIQ explanations.

**Live:** [spielfeld.vercel.app](https://spielfeld.vercel.app)

## Setup

```bash
git clone https://github.com/Prgrmmrjns/spielfeld.git
cd spielfeld
pip install -r requirements.txt          # FastAPI web
pip install -r requirements-ml.txt       # predict.py + ShapIQ
```

Put secrets in `.env`:

| Variable | Purpose |
|---|---|
| `TABPFN_API_KEY` | Prior Labs TabPFN (required for `predict.py`) |
| `API_FOOTBALL_KEY` | Optional live squads / starting XIs (league 78) |

## Web UI

```bash
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

| Route | Purpose |
|---|---|
| `/` | Matchday tips, XI board, ShapIQ lab |
| `/about` | How the model and lab work |
| `/api/predictions` | Baked predictions JSON |
| `/api/lineups` | Live / estimated starting XIs |
| `/api/refresh-lineups` | Cron / manual lineup refresh |

```bash
python scripts/refresh_lineups.py   # refresh XIs in baked JSON
python predict.py                   # retrain TabPFN + ShapIQ + write predictions
```

## Starting XIs

1. **Confirmed** API-Football lineups when published  
2. Else **last starting XI** from the club’s most recent finished match  
3. Else squad estimate (Wikipedia / footballsquads)

Refresh paths: Vercel daily cron → `GET /api/refresh-lineups`, browser poll every 15 min, or GitHub Action running `predict.py`.

## Vercel

FastAPI entry: `app/main.py`. Static assets in `public/` (CSS, JS, icon, SHAP plots).

Set `API_FOOTBALL_KEY` in the Vercel project env. `TABPFN_API_KEY` is only needed for GitHub Actions / local `predict.py`.

## Features (model)

| Feature | Description |
|---|---|
| `elo_diff` | ELO gap with home advantage |
| `form5_diff` / `form10_diff` | Points-per-game form gaps |
| `home_gf5` / `home_ga5` | Recent goals for / against |
| `h2h_*` | Head-to-head win/draw/goal-diff stats |
| `home_rest` / `away_rest` | Days since last match |
| `value_diff` | Approximate squad-value gap |
| `*_xi_*` / line & star gaps | Starting-XI strength and player-derived units |

Data: [OpenLigaDB](https://www.openligadb.de/) (`bl1`) + [API-Football](https://www.api-football.com/) / squad lists.
