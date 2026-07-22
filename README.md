# Spielfeld — Bundesliga Matchday Predictions

Predict the next Bundesliga Spieltag with engineered club features and a TabPFN (or calibrated gradient-boosting fallback) model. Includes a Nuxt web app to browse the tips.

## Setup

```bash
git clone https://github.com/Prgrmmrjns/Spielfeld.git
cd Spielfeld
pip install -r requirements-ml.txt
```

Put secrets in `.env`:

| Variable | Purpose |
|---|---|
| `TABPFN_API_KEY` / `TABPFN_TOKEN` | Prior Labs TabPFN (falls back to HistGradientBoosting) |
| `API_FOOTBALL_KEY` | [API-Football](https://www.api-football.com/) squads / starting XIs (league 78) |

## Starting XIs (API-Football)

No scraping. Lineups come from API-Football:

1. **Confirmed** `/fixtures/lineups` when published
2. Else **last starting XI** from that club’s most recent finished match
3. Else a weak squad estimate (Python path only)

Refresh paths:

- **Every Vercel deploy** — `web/scripts/refresh-lineups.mjs` runs before `nuxt build` (needs `API_FOOTBALL_KEY` in Vercel env)
- **Hourly cron** — `GET /api/refresh-lineups` (live response; UI also polls `/api/lineups` every 15 min)
- **Full model + XI rebuild** — GitHub Action `.github/workflows/refresh-predictions.yml` (needs `TABPFN_API_KEY` + `API_FOOTBALL_KEY` secrets)

```bash
# local lineup-only refresh of baked JSON
npm --prefix web run refresh-lineups
```

## Vercel

The Nuxt app is in `web/`. Root `vercel.json` installs/builds with **npm** and runs the lineup refresh before build.

Set project env `API_FOOTBALL_KEY`. Preferred Root Directory can stay at repo root so `vercel.json` applies (cron + buildCommand).

## Predict next matchday

```bash
python predict.py
# or refresh history from OpenLigaDB:
python predict.py --refresh
python predict.py --skip-shap          # faster
python predict.py --skip-lineups       # no API-Football
```

This will:

1. Load Bundesliga results from OpenLigaDB (cached as `bundesliga_results.csv`)
2. Build leakage-safe features (ELO, form, H2H, rest days, squad value, XI strength)
3. Resolve starting XIs via API-Football (confirmed or last XI)
4. Fetch the upcoming Spieltag fixtures and write `predictions.csv` / `predictions.json`
5. Generate SHAP waterfall plots into `web/public/explanations/`

`predictions.json` is copied to `web/app|server|public/data/predictions.json`.

## Nuxt web app

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Predictions are embedded at build time; live XIs merge from `/api/lineups`.

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
