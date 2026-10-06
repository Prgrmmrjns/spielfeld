# spielfeld

What-if modeling with TabPFN-3.5. You pick a goal: the highest or lowest probability of a class (`goal="max"` or `"min"`), or the chance that a regression lands on a target value or in a range (`models.near`, `models.in_range`). Given a feasible range per feature, it finds the input values that get closest, any number of them changed (cap with `k`). Example: the best input values for a patient to survive, according to the model.

```python
from spielfeld import Knob, whatif

model = fit_classifier(X_train, y_train)
to_frame = lambda states: pd.DataFrame(states)[X_train.columns]
objective = proba(model, to_frame, cls=0)          # e.g. P(survive)

knobs = [Knob("ejection_fraction", low=15, high=80, step=5, expect=1),
         Knob("smoking", choices=[0, 1], expect=-1)]
w = whatif(objective, patient_row, knobs)
w.best.actions, w.best.values[w.best.best_mask]   # the input changes, and P(survive) with them
```

Optuna's TPE sampler proposes designs and TabPFN scores each batch in one call. By default every input may change at once, within a trial budget (`budget`). With `k` set below the number of knobs, a screen of single changes seeds the search and a short polish tries one-step neighbours of the best design. `grid()` scores every allowed design at the same step sizes as a check. `expect` limits a knob to the direction prior knowledge allows, and flags single changes that contradict it. `Support` scores how far a configuration is from the training data.

do() sets the model's inputs and reads the prediction. That is a causal effect only when the model is causal.

Install: `pip install -e extension[client]` (or `[local]`). Python 3.12+. Tests: `pytest extension/tests`.
