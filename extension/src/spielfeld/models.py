"""TabPFN backends and objectives. Prefers local `tabpfn`, falls back to `tabpfn_client`."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


def _backend():
    try:
        import tabpfn  # noqa: F401
        from tabpfn import TabPFNClassifier, TabPFNRegressor
    except ImportError:
        from tabpfn_client import TabPFNClassifier, TabPFNRegressor
    return TabPFNClassifier, TabPFNRegressor


def _make(cls):
    try:
        return cls.create_default_for_version("v3.5")
    except (AttributeError, TypeError, ValueError):
        return cls()


def fit_classifier(X: pd.DataFrame, y):
    clf = _make(_backend()[0])
    clf.fit(X, y)
    return clf


def fit_regressor(X: pd.DataFrame, y):
    reg = _make(_backend()[1])
    reg.fit(X, y)
    return reg


def proba(model, to_frame: Callable[[list], pd.DataFrame], cls) -> Callable[[list], np.ndarray]:
    """Objective: probability of class `cls`."""
    def predict(states: list) -> np.ndarray:
        p = model.predict_proba(to_frame(states))
        return np.asarray(p)[:, list(model.classes_).index(cls)]
    return predict


def near(model, to_frame: Callable[[list], pd.DataFrame], target: float, tol: float) -> Callable[[list], np.ndarray]:
    """Objective: P(|y - target| <= tol), the chance a regressor lands near a target value."""
    return in_range(model, to_frame, target - tol, target + tol)


def in_range(model, to_frame: Callable[[list], pd.DataFrame], lo: float, hi: float) -> Callable[[list], np.ndarray]:
    """Objective: P(lo <= y <= hi) from the predictive distribution of a regressor."""
    qs = [round(q, 3) for q in np.linspace(0.005, 0.995, 99)]

    levels = np.asarray(qs)

    def predict(states: list) -> np.ndarray:
        out = model.predict(to_frame(states), output_type="quantiles", quantiles=qs)
        q = np.stack([np.asarray(a) for a in out], axis=1) if isinstance(out, list) else np.asarray(out)
        if q.shape[1] != len(qs):
            q = q.T
        q = np.maximum.accumulate(q, axis=1)
        # continuous CDF by interpolating between quantiles, so the objective has no plateaus
        cdf = lambda row, t: np.interp(t, row, levels, left=0.0, right=1.0)
        return np.array([cdf(row, hi) - cdf(row, lo) for row in q])
    return predict
