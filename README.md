# Spielfeld — Bundesliga Matchday Predictions

Predict the next Bundesliga Spieltag with engineered club features and a TabPFN (or calibrated gradient-boosting fallback) model. Includes a Nuxt web app to browse the tips.

## Setup

```bash
git clone https://github.com/Prgrmmrjns/Spielfeld.git
cd Spielfeld
pip install -r requirements-ml.txt
```

Optional: put `TABPFN_API_KEY` or `TABPFN_TOKEN` in a `.env` file to use the Prior Labs TabPFN client. Without it, the script falls back to a calibrated `HistGradientBoostingClassifier`.

## Vercel

The Nuxt app is in `web/`. Root `vercel.json` installs/builds with **npm** (avoids corepack/pnpm issues on Vercel) and skips Python ML deps.

Preferred: set Vercel **Root Directory** to `web`. If it stays at repo root, `vercel.json` still builds Nuxt and moves Nitro’s `.vercel` output into place.

## Predict next matchday

```bash
python predict.py
# or refresh history from OpenLigaDB:
python predict.py --refresh
```

This will:

1. Load Bundesliga results from OpenLigaDB (cached as `bundesliga_results.csv`)
2. Build leakage-safe features (ELO, form, H2H, rest days, squad value)
3. Fetch the upcoming Spieltag fixtures
4. Write `predictions.csv` and `predictions.json`
5. Generate SHAP waterfall plots per fixture into `web/public/explanations/` ([Prior Labs interpretability](https://docs.priorlabs.ai/capabilities/interpretability))

`predictions.json` is also copied to `web/public/data/predictions.json` automatically.

Skip SHAP with `python predict.py --skip-shap`.

## Nuxt web app

```bash
cd web
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). The `/api/predictions` route serves `public/data/predictions.json`.

## Features

| Feature | Description |
|---|---|
| `elo_diff` | ELO gap with home advantage |
| `form5_diff` / `form10_diff` | Points-per-game form gaps |
| `home_gf5` / `home_ga5` | Recent goals for / against |
| `h2h_*` | Head-to-head win/draw/goal-diff stats |
| `home_rest` / `away_rest` | Days since last match |
| `value_diff` | Approximate Transfermarkt squad-value gap |

Data source: [OpenLigaDB](https://www.openligadb.de/) (`bl1`).
