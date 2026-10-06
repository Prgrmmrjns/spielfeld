"""Plausibility: how far is a configuration from the training data?"""
from __future__ import annotations

import numpy as np


class Support:
    """k-NN distance percentile against the training set (0 = typical, 1 = outlier)."""

    def __init__(self, train: np.ndarray, k: int = 5):
        train = np.asarray(train, dtype=float)
        self.mu = train.mean(axis=0)
        self.sd = train.std(axis=0) + 1e-9
        self.z = (train - self.mu) / self.sd
        self.k = k
        ref = self._dist(self.z[: min(len(self.z), 400)], skip_self=True)
        self.ref = np.sort(ref)

    def _dist(self, z: np.ndarray, skip_self: bool = False) -> np.ndarray:
        d = np.linalg.norm(z[:, None, :] - self.z[None, :, :], axis=2)
        d.sort(axis=1)
        s = 1 if skip_self else 0
        return d[:, s : s + self.k].mean(axis=1)

    def score(self, x: np.ndarray) -> np.ndarray:
        z = (np.asarray(x, dtype=float) - self.mu) / self.sd
        d = self._dist(z)
        return np.searchsorted(self.ref, d) / len(self.ref)
