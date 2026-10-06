# Spielfeld

What-if modeling with TabPFN-3.5. You fit a model, name a goal, and give each input a feasible range. Spielfeld searches the combinations inside those ranges and keeps the one with the highest score: the highest chance of a class, or a target value or range for a regression.

Example: which clinical values, inside clinical ranges, give a heart-failure patient the highest predicted chance of survival.

**Live:** [spielfeld.vercel.app](https://spielfeld.vercel.app)

Prior Labs TabPFN 3.5 hackathon entry.

## Use it

```bash
pip install -e "extension[client]"
```

`TABPFN_API_KEY` in the environment (or a `.env` file). `fit_classifier` and `fit_regressor` build TabPFN-3.5. Any model with `predict_proba` or `predict` can be passed in the same way.

```python
import pandas as pd
from spielfeld import Knob, whatif
from spielfeld.models import fit_classifier, proba

model = fit_classifier(X_train, y_train)
to_frame = lambda states: pd.DataFrame(states)[list(X_train.columns)]
score = proba(model, to_frame, cls=0)          # the model goes in here

case = X_train.iloc[0].to_dict()
knobs = [
    Knob("ejection_fraction", low=15, high=80, step=5),
    Knob("smoking", choices=[0, 1]),
]
w = whatif(score, case, knobs)                  # goal="max"
w.best.actions                                  # which inputs change
w.best.values[w.best.best_mask]                 # the score of that design
```

`goal="min"` searches the lowest score. For a regression, fit with `fit_regressor` and pass `in_range(model, to_frame, 70, 180)` or `near(model, to_frame, target, tol)` as `score`, with `goal="max"`.

A `Knob` is one feature: a numeric range (`low`, `high`, `step`) or a list of `choices`. `expect=1` or `expect=-1` keeps that feature on the side prior knowledge allows. `k` caps how many features may change; the default lets every knob move. `Support` scores how far a design sits from the training rows.

`whatif` returns a `WhatIf`: `base` is the score of the case as it stands, `best` is the design the search kept.

`do()` sets the model's inputs and reads the prediction. That reading is a causal effect when the model is causal.

More on the search: [extension/README.md](extension/README.md).

## Run the site

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The page reads the cached results in `public/data/scenarios/`. How the three cases were built, and how to rebuild them: [reproduction.md](reproduction.md).
