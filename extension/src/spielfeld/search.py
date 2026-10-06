"""What-if search: Optuna proposes joint interventions do(X_S = v), TabPFN scores them in batches."""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from itertools import combinations, product
from math import prod
from typing import Any, Callable, Sequence

import numpy as np

from .core import Action, Side, _lattice, _pick, side_json


def _num(v):
    return float(v) if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) else v


def _fmt(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


@dataclass
class Knob:
    """A feature the search may set: a range (`low`, `high`, `step`) or a list of `choices`.

    `expect` (+1/-1) is the direction in which raising the feature should move the objective.
    The best side then only moves it that way, the worst side only the other way.
    """

    key: str
    label: str = ""
    low: float | None = None
    high: float | None = None
    step: float | None = None
    choices: Sequence | None = None
    expect: int | None = None
    fmt: Callable[[Any], str] = _fmt
    get: Callable[[Any], Any] | None = None
    put: Callable[[Any, Any], Any] | None = None
    name: Callable[[Any, Any], str] | None = None
    meta: Callable[[Any, Any], dict] | None = None

    def current(self, state):
        return self.get(state) if self.get else state[self.key]

    def values(self, state, sign: int = 1) -> list:
        """Feasible new values on one side, ascending for ranges; the current value is excluded."""
        cur = self.current(state)
        if self.choices is not None:
            vals = [v for v in self.choices if v != cur]
        else:
            n = int(round((self.high - self.low) / self.step))
            vals = [round(self.low + i * self.step, 6) for i in range(n + 1)]
            vals = [v for v in vals if abs(v - cur) > 1e-9]
        if self.expect:
            vals = [v for v in vals if (v - cur) * self.expect * sign > 0]
        return vals

    def set(self, state, value):
        return self.put(state, value) if self.put else {**state, self.key: _num(value)}

    def action(self, state, value) -> Action:
        old = self.current(state)
        name = self.name(old, value) if self.name else f"{self.label or self.key} {self.fmt(old)} → {self.fmt(value)}"
        meta = self.meta(old, value) if self.meta else {"set": {self.key: _num(value)}}
        return Action(self.key, name, lambda s, v=value: self.set(s, v), expect=self.expect, meta=meta)


@dataclass
class WhatIf:
    base: float
    best: Side
    worst: Side
    singles: list[dict]
    flagged: list[dict]
    calls: int


def _sig(design: dict) -> tuple:
    return tuple(sorted(design.items(), key=lambda t: t[0]))


def _state(state, by_key, design: dict):
    for key, v in design.items():
        state = by_key[key].set(state, v)
    return state


def _space(state, knobs, sign) -> list:
    return [(kb, vals) for kb in knobs if (vals := kb.values(state, sign))]


def _size(space, k) -> dict:
    """Designs with at most k changes (elementary symmetric sums) and without a budget."""
    e = [1] + [0] * k
    for _, vals in space:
        for r in range(k, 0, -1):
            e[r] += e[r - 1] * len(vals)
    return {"k": sum(e), "all": prod(len(v) + 1 for _, v in space)}


class _Study:
    """One side of the search: an Optuna study over do-flags and values."""

    def __init__(self, state, knobs, sign, k, conflicts, seed, probe):
        import optuna

        self.sign, self.k, self.conflicts = sign, k, conflicts
        self.space = _space(state, knobs, sign)
        self.joint = k >= len(self.space) and len(self.space) > 0  # every feature, every trial
        self.screen = [{}]
        if not self.joint:
            for kb, vals in self.space:
                idx = range(len(vals)) if kb.choices is not None else np.unique(np.linspace(0, len(vals) - 1, probe).round().astype(int))
                self.screen += [{kb.key: vals[int(i)]} for i in idx]
        self.study = optuna.create_study(
            direction="maximize" if sign > 0 else "minimize",
            sampler=optuna.samplers.TPESampler(
                seed=seed, multivariate=True, group=True, constant_liar=True,
                n_startup_trials=10 if self.joint else len(self.screen),
            ),
        )
        self.seen: list[tuple] = []
        self._seen: set = set()
        self.queued = 0
        self.phases: list[int] = []

    def _untangle(self, d: dict, salt: int) -> dict:
        """Reassign clashing choices so one player is not used twice. Keeps every slot filled."""
        used = set()
        out = {}
        for i, (kb, vals) in enumerate(self.space):
            v = d.get(kb.key)
            if v in used or v is None:
                free = [x for x in vals if x not in used]
                if not free:
                    return d
                v = free[(salt + i) % len(free)]
            used.add(v)
            out[kb.key] = v
        return out

    def violation(self, d: dict) -> int:
        return max(0, len(d) - self.k) + (self.conflicts(d) if self.conflicts else 0)

    def enqueue(self, designs: list[dict]):
        for d in designs:
            p = {}
            for kb, vals in self.space:
                p["do:" + kb.key] = kb.key in d
                if kb.key in d:
                    p[kb.key] = vals.index(d[kb.key]) if kb.choices is None else d[kb.key]
            self.study.enqueue_trial(p)
            self.queued += 1

    def ask(self, n: int) -> list:
        out = []
        for _ in range(n + self.queued):
            t = self.study.ask()
            d = {}
            for kb, vals in self.space:
                if self.joint or t.suggest_categorical("do:" + kb.key, [False, True]):
                    d[kb.key] = (vals[t.suggest_int(kb.key, 0, len(vals) - 1)] if kb.choices is None
                                 else t.suggest_categorical(kb.key, list(vals)))
            if self.joint and self.conflicts and self.conflicts(d):
                d = self._untangle(d, t.number)
            out.append((t, d))
        self.queued = 0
        return out

    def tell(self, asked, cache, fallback):
        for t, d in asked:
            v = self.violation(d)
            t.set_constraint("violation", float(v))
            sig = _sig(d)
            if v == 0 and sig not in self._seen:
                self._seen.add(sig)
                self.seen.append(sig)
            self.study.tell(t, cache[sig] if v == 0 else fallback)

    def neighbors(self, cache) -> list[dict]:
        """One-change moves around the incumbent: drop a change, or move its value up to two steps."""
        best = dict(max(self.seen, key=lambda s: self.sign * cache[s]))
        space = {kb.key: (kb, vals) for kb, vals in self.space}
        out = []
        for key, v in best.items():
            kb, vals = space[key]
            out.append({kk: vv for kk, vv in best.items() if kk != key})
            if kb.choices is None:
                i = vals.index(v)
                alts = [vals[j] for j in (i - 2, i - 1, i + 1, i + 2) if 0 <= j < len(vals)]
            else:
                alts = [o for o in vals if o != v]
            out += [{**best, key: a} for a in alts]
        return [d for d in out if self.violation(d) == 0 and _sig(d) not in cache]

    def warm(self, cache, base, m) -> list[dict]:
        """Feasible combinations of the m strongest single changes (several values per knob allowed)."""
        gain = lambda d: self.sign * (cache[_sig(d)] - base)
        top = sorted((d for d in self.screen[1:] if gain(d) > 0), key=gain, reverse=True)[:m]
        out = []
        for r in range(2, self.k + 1):
            for combo in combinations(top, r):
                d = {key: v for one in combo for key, v in one.items()}
                if len(d) == r and self.violation(d) == 0:
                    out.append(d)
        return out


def whatif(
    predict: Callable[[list], Sequence[float]],
    state: Any,
    knobs: list[Knob],
    k: int | None = None,
    budget: int = 300,
    batch: int = 32,
    probe: int = 3,
    warm: int = 6,
    polish: int = 4,
    seed: int = 0,
    support: Callable[[list], Sequence[float]] | None = None,
    conflicts: Callable[[dict], int] | None = None,
    goal: str = "max",
) -> WhatIf:
    """Input values that push the prediction where you want it. At most `k` change; `k=None` lets all.

    `goal="max"` searches the highest `predict`, `"min"` the lowest, `"both"` runs both
    studies. For a target value or range of a regression, pass `models.in_range(...)` or
    `models.near(...)` as `predict` and keep `goal="max"`. Only the requested side is
    searched; the other side of the result is empty.

    `predict` maps a list of states to the objective (one float each); every batch is one call.
    When `k` covers every knob, each trial sets every feature at once and the search stops at
    about `budget` scored designs per side. Otherwise a screen of single changes and their best
    combinations seeds the study, then TPE proposes `batch` designs per round. Designs with more
    than `k` changes, or with `conflicts(design) > 0`, are never scored.
    """
    import optuna

    k = len(knobs) if k is None else k
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)
    by_key = {kb.key: kb for kb in knobs}
    signs = {"max": (1,), "min": (-1,), "both": (1, -1)}[goal]
    runs = [_Study(state, knobs, s, k, conflicts, seed, probe) for s in signs]
    cache: dict[tuple, float] = {}
    calls = 0

    def step(n):
        nonlocal calls
        ns = n if isinstance(n, list) else [n] * len(runs)
        asked = [r.ask(ni) for r, ni in zip(runs, ns)]
        new = {}
        for r, a in zip(runs, asked):
            for _, d in a:
                sig = _sig(d)
                if r.violation(d) == 0 and sig not in cache:
                    new[sig] = d
        if new:
            vals = predict([_state(state, by_key, d) for d in new.values()])
            calls += len(new)
            cache.update({sig: float(v) for sig, v in zip(new, vals)})
        fallback = cache.get((), 0.0)
        for r, a in zip(runs, asked):
            r.tell(a, cache, fallback)

    joint = all(r.joint for r in runs)
    if joint:
        cache[()] = float(list(predict([state]))[0])
        calls = 1
        base = cache[()]
        rounds = 0
        while any(len(r.seen) < budget for r in runs) and rounds < max(8, 8 * budget // max(batch, 1)):
            step([min(batch, max(0, budget - len(r.seen))) for r in runs])
            rounds += 1
        for r in runs:
            r.phases = [0, 0, len(r.seen)]
    else:
        for r in runs:
            r.enqueue(r.screen)
        step(0)
        base = cache[()]
        for r in runs:
            r.phases = [len(r.seen)]
            r.enqueue(r.warm(cache, base, warm))
        step(0)
        for r in runs:
            r.phases.append(len(r.seen))
        stall, rounds = 0, 0
        while calls < 2 * budget and stall < 3 and rounds < 3 * budget // batch:
            before = calls
            step(batch)
            rounds += 1
            stall = stall + 1 if calls - before < batch // 4 else 0  # mostly repeats: converged
        for r in runs:
            r.phases.append(len(r.seen))
        for _ in range(polish):
            before = calls
            for r in runs:
                r.enqueue(r.neighbors(cache))
            step(0)
            if calls == before:
                break

    if joint:
        probes = []
        for kb in knobs:
            if not kb.expect:
                continue
            vals = kb.values(state, 1)
            if vals:
                probes.append({kb.key: vals[len(vals) // 2]})
        missing = { _sig(d): d for d in probes if _sig(d) not in cache }
        if missing:
            vals = predict([_state(state, by_key, d) for d in missing.values()])
            calls += len(missing)
            cache.update({sig: float(v) for sig, v in zip(missing, vals)})
        for r in runs:
            r.screen = [{}] + probes

    singles, flagged, named = [], [], set()
    for r in runs:
        for d in r.screen[1:]:
            (key, val), = d.items()
            kb = by_key[key]
            a = kb.action(state, val)
            if a.name in named:
                continue
            named.add(a.name)
            row = {"slot": key, "name": a.name, "delta": round(cache[_sig(d)] - base, 5), **a.meta}
            if kb.expect and row["delta"] * (val - kb.current(state)) * kb.expect < 0:
                row["flag"] = "contradicts expected direction"
                flagged.append(row)
            singles.append(row)

    def side(r: _Study) -> Side:
        nonlocal calls
        if not r.seen:
            return Side([], np.asarray([base]), 0, None, [], 0, {}, r.phases)
        sig = max(r.seen, key=lambda s: r.sign * cache[s])
        d = dict(sig) if r.sign * (cache[sig] - base) > 0 else {}
        label = lambda s: " + ".join(by_key[key].action(state, v).name for key, v in s)
        shown = lambda s: [by_key[kb.key].fmt(dict(s)[kb.key]) if kb.key in dict(s) else None for kb in knobs]
        trials = [[len(s), round(cache[s], 5), label(s), shown(s)] for s in r.seen]  # last: value per knob, None = as is
        space = _size(r.space, k)
        keys = [kb.key for kb in knobs if kb.key in d]
        if not keys:
            return Side([], np.asarray([base]), 0, None, trials, len(r.seen), space, r.phases)
        acts = [by_key[key].action(state, d[key]) for key in keys]
        if r.joint:
            sup = None
            if support is not None:
                sup = float(support([_state(state, by_key, d)])[0])
            return Side(acts, np.asarray([cache[sig]]), 0, sup, trials, len(r.seen), space, r.phases)
        vals = _lattice(predict, state, acts)
        calls += len(vals)
        mask = _pick(vals, k, r.sign)
        sup = None
        if support is not None:
            chosen = {key: d[key] for i, key in enumerate(keys) if mask >> i & 1}
            sup = float(support([_state(state, by_key, chosen)])[0])
        return Side(acts, vals, mask, sup, trials, len(r.seen), space, r.phases)

    done = {r.sign: side(r) for r in runs}
    none = Side([], np.asarray([base]), 0, None, [], 0, {}, [])
    return WhatIf(base, done.get(1, none), done.get(-1, none), singles, flagged, calls)


def grid(
    predict: Callable[[list], Sequence[float]] | None,
    state: Any,
    knobs: list[Knob],
    k: int | None = None,
    conflicts: Callable[[dict], int] | None = None,
) -> dict:
    """Brute-force reference on the same discretization: every feasible design, one batch.

    With `predict=None` only the number of rows is returned.
    """
    k = len(knobs) if k is None else k
    by_key = {kb.key: kb for kb in knobs}
    sides, designs = {}, {(): {}}
    for sign in (1, -1):
        sigs = [()]
        for r in range(1, k + 1):
            for combo in combinations(_space(state, knobs, sign), r):
                for vals in product(*(v for _, v in combo)):
                    d = {kb.key: x for (kb, _), x in zip(combo, vals)}
                    if conflicts and conflicts(d):
                        continue
                    sig = _sig(d)
                    sigs.append(sig)
                    designs[sig] = d
        sides[sign] = sigs
    if predict is None:
        return {"rows": len(designs)}
    order = list(designs)
    val = dict(zip(order, map(float, predict([_state(state, by_key, designs[s]) for s in order]))))
    hi, lo = max(sides[1], key=val.get), min(sides[-1], key=val.get)
    names = lambda sig: [by_key[key].action(state, v).name for key, v in sig]
    return {
        "rows": len(order),
        "best": round(val[hi], 5), "best_set": names(hi),
        "worst": round(val[lo], 5), "worst_set": names(lo),
    }


def whatif_json(w: WhatIf) -> dict:
    return {
        "base": round(w.base, 5),
        "singles": w.singles,
        "flagged": w.flagged,
        "best": side_json(w.best),
        "worst": side_json(w.worst),
        "calls": w.calls,
    }
