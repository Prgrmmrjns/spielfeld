"""Sub-design lattice of a what-if design."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np


@dataclass
class Action:
    """One change of a design, e.g. do(ejection_fraction = 45)."""

    slot: str | tuple
    name: str
    apply: Callable[[Any], Any]
    expect: int | None = None  # expected sign of the effect on the objective (+1/-1)
    meta: dict = field(default_factory=dict)


@dataclass
class Side:
    """Best (or worst) design: its changes, and the value of every subset of them."""

    actions: list[Action]
    values: np.ndarray  # index = bitmask over `actions`
    best_mask: int
    support: float | None = None
    trials: list = field(default_factory=list)  # [n_changes, value, label] per scored design, in search order
    rows: int = 0
    space: dict = field(default_factory=dict)
    phases: list = field(default_factory=list)  # trial counts after the screen and after the warm start


def _apply(state, actions: Sequence[Action]):
    for a in actions:
        state = a.apply(state)
    return state


def _lattice(predict, state, actions: list[Action]) -> np.ndarray:
    m = len(actions)
    states = [
        _apply(state, [actions[i] for i in range(m) if mask >> i & 1])
        for mask in range(1 << m)
    ]
    return np.asarray(predict(states), dtype=float)


def _pick(mask_values: np.ndarray, k: int, sign: int) -> int:
    best, best_v = 0, sign * mask_values[0]
    for mask in range(1, len(mask_values)):
        if bin(mask).count("1") <= k and sign * mask_values[mask] > best_v:
            best, best_v = mask, sign * mask_values[mask]
    return best


def side_json(side: Side) -> dict:
    return {
        "actions": [{"slot": a.slot, "name": a.name, **a.meta} for a in side.actions],
        "values": [round(float(v), 5) for v in side.values],
        "mask": side.best_mask,
        "value": round(float(side.values[side.best_mask]), 5),
        "support": side.support,
        "trials": side.trials,
        "rows": side.rows,
        "space": side.space,
        "phases": side.phases,
    }
