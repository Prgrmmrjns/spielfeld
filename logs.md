## 2026-10-06
* **Update**: README is the idea and how to pass a model into `whatif`. Dataset rebuild steps are in `reproduction.md`.
* **Update**: Current tabbed demo deployed to production at https://spielfeld.vercel.app (`dpl_8JcvPHT5LsMsZqN8erfbkJxfjWia`).
* **Update**: Scripts live in `scripts/`, datasets in `datasets/` (heart failure CSV flattened out of `data/open/`).
* **Update**: `azt1d.py` downloads AZT1D and rebuilds the glucose table (README documents it); `scenarios.py` reads `data/azt1d/`. Repo cleaned: unused football code (history, influence, goals, optimizer, CSV outputs), caches, dead CSS and requirements removed.
* **Update**: Search sets every input on every trial (100 per side). LightGBM stand-in removed. Mortality, glucose and football recomputed with TabPFN-3.5.
* **Update**: Football squads now come from the current season only (18 clubs, players who appeared this season); the old pool also held last season's players. Football case regenerated.
* **Update**: Playground removed (routes, template, JS, API). The example tabs on the landing page carry the search explorer.
* **Update**: Examples and hero show the sampled designs; click a dot for the prediction, inputs and feasible ranges. Background redesigned with a confounding diagram; footer sticks to the bottom.
* **Update**: No cap on changed features (k=None means all); LightGBM stand-in (`SPIELFELD_MODEL=lgbm`) regenerates all three cases, search matches the grid; switch back to TabPFN after the quota resets.
* **Update**: Landing simplified: plain-language hero with patient example and live search plot, use-case cards (healthcare, football, diabetes), all math moved into Methodology.
* **Update**: Goal framing: highest or lowest class probability, or a target value or range for regression.
* **Update**: Search is Optuna (TPE) over feasible ranges, checked against grid brute force.
* **Update**: The search result is the design. The post-search attribution charts are gone.
* **Update**: Categorical factors (blood pressure, smoking, anaemia) use a two-way choice instead of a slider.
* **Update**: Football example is Freiburg vs Schalke (11 Oct). Examples are interactive: swap toggles on the lattice, sliders on the cached glucose and mortality profiles.
* **Update**: Conflict-aware search with one-change refinement and a brute-force check per case; clinical direction flags (mortality); smooth glucose CDF objective; landing rebuilt with envelope figure, animated coalition cube, KaTeX, range plots, checks and pipeline.
* **Update**: Landing redesign: domain-agnostic method, animated football stage (landing.js), Examples dropdown, no duplicate cards, relation section.
* **Update**: Play and landing pages lead with the reachable range; method and data notes sit in closed sections.
* **Update**: Play pages show both clubs (separate home and away search, both lineups, Elo/form/rest) and how each case is built, with an as-is / best / worst input table for glucose and mortality.

## 2026-10-05
* **Update**: Neutral TabPFN-blue UI and logo; actual vs optimal XI, dose-response charts; `/api/scenario/{domain}` serves cache or recomputes locally; removed matchday tips pages, refresh jobs and cron.
* **Update**: Built the `spielfeld` TabPFN extension (best/worst-case search), `scenarios.py`, domain-neutral landing and `/play/{domain}` for football, glucose, mortality; tips moved to `/football`.

## 2026-09-28
* **Update**: Held-out TabPFN ablation dropped age and recent shots (they raised log-loss); kept form, XI names, and home–away gaps. Domain ratios did not beat the raw table. Retrained tips and influence.
* **Update**: Model tab shows grouped feature influence (form and XI names lead) and a training-table preview.
* **Update**: TM backfill complete (2178 lineup pages); retrained on 2077 matches; full 2025 eval refreshed.
* **Update**: TabPFN 3.5 showcase — `data/matches.csv` (Elo/form/XI value/text), lineup lab + what-if API, benchmark page, football-data odds as benchmark only.
