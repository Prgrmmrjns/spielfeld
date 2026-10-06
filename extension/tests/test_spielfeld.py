import numpy as np
import pytest

from spielfeld import Knob, Support, grid, whatif


def predict(states):
    # a and b work together, c hurts, a has an interior optimum
    return [s["a"] + s["b"] + 0.5 * s["a"] * s["b"] - s["c"] - 0.3 * (s["a"] - 3) ** 2 for s in states]


KNOBS = [Knob("a", low=0, high=5, step=1), Knob("b", low=0, high=4, step=1), Knob("c", low=0, high=2, step=1)]


@pytest.mark.client_compatible
@pytest.mark.local_compatible
def test_whatif_matches_grid():
    x = {"a": 0.0, "b": 0.0, "c": 1.0}
    w = whatif(predict, x, KNOBS, k=2, budget=60, batch=8, goal="both")
    ref = grid(predict, x, KNOBS, k=2)
    assert w.best.values[w.best.best_mask] == pytest.approx(ref["best"])
    assert w.worst.values[w.worst.best_mask] == pytest.approx(ref["worst"])
    names = [a.slot for a in w.best.actions]
    assert names == ["a", "b"]
    assert w.best.values[w.best.best_mask] > w.best.values[1] + w.best.values[2] - w.best.values[0]


def test_direction_flag():
    # lowering a should help (expect=-1), but the model says it hurts
    x = {"a": 2.0}
    w = whatif(lambda ss: [s["a"] for s in ss], x, [Knob("a", low=0, high=4, step=1, expect=-1)], budget=10, goal="both")
    assert w.flagged and not w.best.actions
    assert all(v > 2 for n, v, *_ in w.worst.trials if n)  # the worst side may only raise a


def test_conflicts():
    # two slots may not bring in the same player
    worth = {"a": 0, "b": 0, "x": 2, "y": 1}
    f = lambda ss: [sum(worth[v] for v in s.values()) for s in ss]
    knobs = [Knob("s1", choices=["x", "y"]), Knob("s2", choices=["x", "y"])]
    clash = lambda d: len(d) - len(set(d.values()))
    w = whatif(f, {"s1": "a", "s2": "b"}, knobs, k=2, budget=20, batch=4, conflicts=clash)
    assert w.best.values[w.best.best_mask] == pytest.approx(3)
    assert grid(f, {"s1": "a", "s2": "b"}, knobs, k=2, conflicts=clash)["best"] == pytest.approx(3)


def test_support():
    rng = np.random.default_rng(0)
    s = Support(rng.normal(size=(200, 3)))
    assert s.score(np.array([[0, 0, 0], [9, 9, 9]]))[1] > 0.9


def test_single_goal():
    x = {"a": 0.0, "b": 0.0, "c": 1.0}
    lo = whatif(predict, x, KNOBS, k=2, budget=40, batch=8, goal="min")
    hi = whatif(predict, x, KNOBS, k=2, budget=40, batch=8)
    assert hi.worst.actions == [] and lo.best.actions == []
    assert hi.best.values[hi.best.best_mask] > lo.worst.values[lo.worst.best_mask]
