# Reproducing the examples

The site shows three cached searches. This is how the datasets were built and how to run the search again.

```bash
pip install -r requirements.txt -r requirements-ml.txt
echo "TABPFN_API_KEY=..." > .env
python scripts/azt1d.py                 # diabetes table, once
python scripts/scenarios.py             # all three
# DOMAINS=glucose python scripts/scenarios.py
pytest extension/tests
```

`scripts/scenarios.py` writes `public/data/scenarios/{mortality,glucose,football}.json`.

## Background

| Case | Source | Where |
|---|---|---|
| Heart failure | UCI Heart Failure Clinical Records, 299 patients (Chicco & Jurman 2020, CC BY 4.0) | `datasets/heart_failure.csv`, in the repo |
| Diabetes | AZT1D, 25 people with type 1 diabetes on automated insulin delivery (Khamesian et al. 2025, CC BY 4.0) | `python scripts/azt1d.py` writes `datasets/azt1d/` (not in the repo, about 56 MB) |
| Football | Bundesliga results (OpenLigaDB, football-data.co.uk) and lineups (Transfermarkt) | `datasets/matches.csv`, `datasets/squads.json`, `datasets/lineups.json`, in the repo |

## Heart failure

`datasets/heart_failure.csv` is the UCI table, already in the repo. [UCI Heart Failure Clinical Records](https://archive.ics.uci.edu/dataset/519/heart+failure+clinical+records).

The target is survival, the complement of `DEATH_EVENT`. The 11 clinical columns are the inputs. Follow-up time is dropped because it leaks the outcome. Sixty patients are held out at random (seed 7); the rest train a TabPFN-3.5 classifier. The search may change ejection fraction (15–80% in steps of 5), sodium (125–145 mEq/L in steps of 2), creatinine (0.6–4.0 mg/dL in steps of 0.2), and blood pressure, smoking and anaemia (on or off). Age, sex, diabetes, platelets and CPK stay as they are for that patient.

## Diabetes (AZT1D)

`python scripts/azt1d.py` does both steps:

1. Downloads `AZT1D 2025.zip` (776 MB) from Mendeley Data, [doi.org/10.17632/gk9m674wcx.1](https://doi.org/10.17632/gk9m674wcx.1), and unpacks it to `datasets/azt1d/raw/`. If the link fails, download the zip from the dataset page and unpack it there, so that `datasets/azt1d/raw/**/CGM Records/Subject 1/Subject 1.csv` exists.
2. Writes `datasets/azt1d/azt1d_all_patients.parquet` (about 290,000 rows, 24 subjects). Subject 14 is skipped: its CGM and fingerstick readings share one column.

One row is one 5-minute step of one subject:

| Column | Meaning |
|---|---|
| `CGM_0` … `CGM_23` | glucose (mg/dL) over the last 2 hours, `CGM_23` newest |
| `Insulin_0` … `Insulin_23` | active bolus insulin per step: every logged dose (`TotalBolusInsulinDelivered`) weighted by an absorption curve (onset 15 min, peak 45 min) |
| `Carbs_0` … `Carbs_23` | active carbohydrate per step: every logged meal (`CarbSize`) weighted by an absorption curve (onset 10 min, peak 35 min) |
| `hour`, `time` | clock time of the step to predict |
| `target` | glucose 1 hour (12 steps) ahead minus glucose at that step |
| `subject_id` | 1 … 25 |

Missing CGM values are carried forward. Missing doses and meals count as 0.

`scripts/scenarios.py` then derives eight model inputs: glucose now, 15 minutes ago and 1 hour ago; insulin and carbohydrate over the last 30 minutes and the 30 minutes before that; hour of day. The target is glucose one hour ahead. Training uses 3,000 rows. Four subjects are held out entirely. The score is P(70 ≤ glucose ≤ 180 mg/dL), read from the regressor's quantile distribution. The search may change the insulin and carbohydrate windows. The CGM history and the hour stay fixed.

## Football

The match table, squad snapshot and lineups are already in the repo.

| File | Role |
|---|---|
| `datasets/matches.csv` | one row per Bundesliga match, 2019–2026, built from what is known before kickoff |
| `datasets/squads.json` | current-season squads |
| `datasets/lineups.json` | Transfermarkt lineups |
| `datasets/last_sides.json` | each club's latest XI |

Club strength on a row is Elo, points and goal difference over the last 5 games, days of rest, and the head-to-head record, each taken from that club's most recent match. The eleven names go in as text features. A swap rebuilds the name string. Elo, form and rest stay as they are. Each starter may stay or be replaced by a same-position squad player who is not already in the XI, and one player fills only one slot. The other club's XI is held fixed. Home and away are searched separately. The score is that side's win probability.

`python scripts/xi_model.py` refreshes the next matchday. It needs a network connection and `TABPFN_API_KEY`. `scripts/dataset.py` and `scripts/xi_table.py` build the match table and the latest XIs.
