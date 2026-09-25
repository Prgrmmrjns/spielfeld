<p align="center">
  <img src="public/icon.svg" width="96" height="96" alt="Spielfeld" />
</p>

# Spielfeld

Bundesliga best-XI predictions with TabPFN 3.5, from each club’s last game.

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
python predict.py                   # append new matchday rows, refit TabPFN 3.5, write XIs
```

## Best XI

The model sees who started the last game and who was on the bench, plus the result, rest, and the next opponent. It predicts who starts next. The XI is the likeliest goalkeeper and the ten likeliest outfield players from that group.

Tables: `data/xi_matches.csv` (one row per team-match) and `data/xi_players.csv` (training rows).

GitHub Actions runs `predict.py` on matchday evenings and each morning. If OpenLigaDB has no newly finished matchday, it does not refit.

## Vercel

FastAPI entry: `app/main.py`. Static assets in `public/` (CSS, JS, icon, SHAP plots).

Set `API_FOOTBALL_KEY` in the Vercel project env. `TABPFN_API_KEY` is only needed for GitHub Actions / local `predict.py`.

## Training columns

| Column | Source |
|---|---|
| `team`, `opponent`, `is_home`, `matchday` | OpenLigaDB |
| `rest_days`, `last_points`, `last_gd` | previous OpenLigaDB result |
| `player_name`, `position`, `started_last`, `on_bench_last` | Transfermarkt last XI / bench |
| `y_started` | Transfermarkt XI of the match being predicted |

Data: [OpenLigaDB](https://www.openligadb.de/) (`bl1`) and Transfermarkt lineups. API-Football is optional and is not required for this table.
