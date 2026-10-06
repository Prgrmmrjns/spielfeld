"""Write public/data/scenarios/{football,mortality,glucose}.json with spielfeld.

Run all: python scripts/scenarios.py     One: DOMAINS=mortality python scripts/scenarios.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("SCIPY_ARRAY_API", "1")
os.environ.setdefault("TABPFN_NO_BROWSER", "1")

import azt1d
from spielfeld import Knob, Support, grid, whatif, whatif_json
from spielfeld.models import fit_classifier, fit_regressor, in_range

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data" / "scenarios"
K = None  # every feature may change
BUDGET = 100  # scored designs per side
MODEL = "TabPFN-3.5"
GRID_CAP = 12_000  # above this, the brute-force check only counts designs; it does not score them


def _init():
    import xi_model

    xi_model._load_dotenv()
    xi_model._init_tabpfn()


def sweep(objective, state, key, xs, label, labels=None, fmt="num"):
    """Outcome when one feature is varied over `xs` (one batch)."""
    ys = np.asarray(objective([{**state, key: x} for x in xs]), dtype=float)
    cur = state[key]
    return {
        "key": key, "label": label, "xs": [float(x) for x in xs], "labels": labels,
        "ys": [round(float(y), 4) for y in ys], "current": float(cur),
        "best_x": float(xs[int(np.argmax(ys))]), "worst_x": float(xs[int(np.argmin(ys))]),
    }


def check(objective, state, knobs, w, conflicts=None) -> dict:
    """Grid brute force on the same feasible values. Large grids are counted, not scored."""
    if objective is None:
        return {"rows": w.best.space.get("all", 0), "optuna_rows": w.calls}
    counted = grid(None, state, knobs, k=K, conflicts=conflicts)
    if counted["rows"] > GRID_CAP:
        return {**counted, "optuna_rows": w.calls}
    return {**grid(objective, state, knobs, k=K, conflicts=conflicts), "optuna_rows": w.calls}


def knobs_json(knobs, state) -> list[dict]:
    """Feasible range of each knob, for the page."""
    out = []
    for kb in knobs:
        cur = kb.current(state)
        row = {"key": kb.key, "label": kb.label, "expect": kb.expect, "current": cur if isinstance(cur, str) else float(cur),
               "now": kb.fmt(cur)}
        if kb.choices is None:
            row.update(low=kb.low, high=kb.high, step=kb.step, range=f"{kb.fmt(kb.low)} to {kb.fmt(kb.high)}")
        else:
            row["choices"] = [kb.fmt(c) for c in kb.choices]
            row["range"] = " / ".join(row["choices"]) if len(kb.choices) <= 4 else f"{len(kb.choices)} options"
        out.append(row)
    return out


def get(domain: str, refresh: bool = False) -> dict:
    """Cached scenario JSON; computes with TabPFN when missing or refresh=True."""
    path = OUT / f"{domain}.json"
    if path.is_file() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    _init()
    return _save(domain, globals()[domain]())


def _save(name: str, payload: dict):
    from datetime import datetime, timezone

    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {name}.json")
    return payload


# ---------------------------------------------------------------- mortality
HF_FEATURES = [
    "age", "anaemia", "creatinine_phosphokinase", "diabetes", "ejection_fraction",
    "high_blood_pressure", "platelets", "serum_creatinine", "serum_sodium", "sex", "smoking",
]


def mortality() -> dict:
    from sklearn.metrics import roc_auc_score

    df = pd.read_csv(ROOT / "datasets" / "heart_failure.csv")
    X, y = df[HF_FEATURES], df["DEATH_EVENT"]
    rng = np.random.default_rng(7)
    idx = rng.permutation(len(df))
    test, train = idx[:60], idx[60:]
    model = fit_classifier(X.iloc[train], y.iloc[train])
    auc = float(roc_auc_score(y.iloc[test], model.predict_proba(X.iloc[test])[:, 1]))

    def to_frame(states):
        return pd.DataFrame(states)[HF_FEATURES]

    def survive(states):
        return np.asarray(model.predict_proba(to_frame(states)))[:, 0]  # P(survive)

    sup = Support(X.iloc[train].to_numpy())
    support = lambda states: sup.score(to_frame(states).to_numpy())

    yn = lambda v: "yes" if v else "no"

    def knobs(r):
        # expect = clinically expected direction on survival: the best case only moves a feature that way
        return [
            Knob("ejection_fraction", "Ejection fraction", 15, 80, 5, expect=1, fmt=lambda v: f"{v:g}%"),
            Knob("serum_sodium", "Sodium", 125, 145, 2, expect=1 if r["serum_sodium"] < 135 else None),
            Knob("serum_creatinine", "Creatinine", 0.6, 4.0, 0.2, expect=-1, fmt=lambda v: f"{v:.1f}"),
            Knob("high_blood_pressure", "Blood pressure", choices=[0, 1], expect=-1, fmt=lambda v: "high" if v else "normal"),
            Knob("smoking", "Smoking", choices=[0, 1], expect=-1, fmt=yn),
            Knob("anaemia", "Anaemia", choices=[0, 1], expect=-1, fmt=yn),
        ]

    test_rows = df.iloc[test]
    risky = test_rows.sort_values("DEATH_EVENT", ascending=False).head(10)
    instances = []
    for i, row in list(risky.sample(3, random_state=3).iterrows()):
        r = {k: (float(row[k]) if k not in ("anaemia", "diabetes", "high_blood_pressure", "sex", "smoking") else int(row[k]))
             for k in HF_FEATURES}
        kn = knobs(r)
        env = whatif(survive, r, kn, k=K, budget=BUDGET, batch=24, support=support, goal="both")
        instances.append({
            "id": int(i),
            "title": f"Patient {int(i)}, age {int(r['age'])}",
            "check": check(survive, r, kn, env),
            "knobs": knobs_json(kn, r),
            "facts": {k: r[k] for k in HF_FEATURES},
            "held": ["age", "sex", "diabetes", "creatinine_phosphokinase", "platelets"],
            "observed": "died" if row["DEATH_EVENT"] else "survived",
            "curves": [
                sweep(survive, r, "ejection_fraction", list(range(15, 81, 5)), "Ejection fraction (%)"),
                sweep(survive, r, "serum_sodium", list(range(120, 146, 2)), "Serum sodium (mEq/L)"),
                sweep(survive, r, "serum_creatinine", [round(0.6 + 0.3 * i, 1) for i in range(15)], "Serum creatinine (mg/dL)"),
                sweep(survive, r, "high_blood_pressure", [0, 1], "Blood pressure", ["normal", "high"]),
                sweep(survive, r, "smoking", [0, 1], "Smoking", ["no", "yes"]),
                sweep(survive, r, "anaemia", [0, 1], "Anaemia", ["no", "yes"]),
            ],
            **whatif_json(env),
        })
        print(f"  patient {i}: base {env.base:.2f} best {env.best.values[env.best.best_mask]:.2f} worst {env.worst.values[env.worst.best_mask]:.2f}")
    return {
        "domain": "mortality",
        "title": "Mortality",
        "question": "Which values of the modifiable factors, within clinical ranges, give a heart-failure patient the highest predicted survival?",
        "outcome": "Survival probability",
        "unit": "probability",
        "higher_is_better": True,
        "pipeline": [
            "Source: 299 heart-failure patients, UCI (Chicco & Jurman, BMC 2020), CC BY 4.0. File datasets/heart_failure.csv.",
            "Target: survival, the complement of DEATH_EVENT (death during follow-up).",
            "Inputs: the 11 clinical columns. Follow-up time is dropped because it leaks the outcome.",
            "Split: 60 patients held out at random (seed 7), the rest train the model.",
            "Feasible range: ejection fraction 15-80% in steps of 5, sodium 125-145 mEq/L in steps of 2, creatinine 0.6-4.0 mg/dL in steps of 0.2, and blood pressure, smoking and anaemia on or off. Age, sex, diabetes, platelets and CPK keep the patient's values.",
            "Each factor has a clinically expected direction: higher ejection fraction, lower creatinine, normal blood pressure, no smoking and no anaemia should not lower survival. The best case may only move a factor that way, the worst case only the other way. Sodium is free unless the patient is hyponatraemic. When a single change contradicts the expected direction in the model, it is flagged.",
            "Search: The optimization algorithm (TPE) proposes interventions on any number of factors at once, in batches of 24 per side, about 300 model rows per side. A grid brute force over every allowed design at the same step sizes checks the result.",
        ],
        "card": {
            "dataset": "UCI Heart Failure Clinical Records (Chicco & Jurman 2020)",
            "license": "CC BY 4.0",
            "rows": int(len(df)),
            "model": MODEL + " classifier",
            "holdout": f"AUC {auc:.2f} on {len(test)} held-out patients",
            "note": "Follow-up time excluded (leaks the outcome). Age, sex, diabetes fixed.",
        },
        "k": None,
        "instances": instances,
    }


# ------------------------------------------------------------------ glucose
def glucose() -> dict:
    d = azt1d.load()
    ins, car = [f"Insulin_{i}" for i in range(24)], [f"Carbs_{i}" for i in range(24)]
    f = pd.DataFrame({
        "cgm_now": d["CGM_23"], "cgm_15m_ago": d["CGM_20"], "cgm_1h_ago": d["CGM_11"],
        "insulin_30m": d[ins[18:]].sum(axis=1), "insulin_30_60m": d[ins[12:18]].sum(axis=1),
        "carbs_30m": d[car[18:]].sum(axis=1), "carbs_30_60m": d[car[12:18]].sum(axis=1),
        "hour": d["hour"],
    })
    y = d["CGM_23"] + d["target"]
    subj = d["subject_id"].to_numpy()
    rng = np.random.default_rng(11)
    test_subj = rng.choice(np.unique(subj), 4, replace=False)
    tr = np.where(~np.isin(subj, test_subj))[0]
    tr = rng.choice(tr, 3000, replace=False)
    te = np.where(np.isin(subj, test_subj))[0]
    model = fit_regressor(f.iloc[tr], y.iloc[tr])
    te_s = rng.choice(te, 150, replace=False)
    mae = float(np.abs(np.asarray(model.predict(f.iloc[te_s])) - y.iloc[te_s]).mean())
    cols = list(f.columns)

    def to_frame(states):
        return pd.DataFrame(states)[cols]

    objective = in_range(model, to_frame, 70, 180)
    sup = Support(f.iloc[tr].to_numpy())
    support = lambda states: sup.score(to_frame(states).to_numpy())

    def knobs(r):
        u, g = (lambda v: f"{round(v, 1):g} U"), (lambda v: f"{round(v):g} g")
        return [
            Knob("insulin_30m", "Insulin, last 30 min", 0, round(r["insulin_30m"]) + 8, 1, fmt=u),
            Knob("insulin_30_60m", "Insulin, 30-60 min ago", 0, round(r["insulin_30_60m"]) + 8, 1, fmt=u),
            Knob("carbs_30m", "Carbs, last 30 min", 0, 10 * round(r["carbs_30m"] / 10) + 60, 10, fmt=g),
            Knob("carbs_30_60m", "Carbs, 30-60 min ago", 0, 10 * round(r["carbs_30_60m"] / 10) + 60, 10, fmt=g),
        ]

    pool = te[(f.iloc[te]["cgm_now"].between(120, 260)).to_numpy()]
    cand = rng.choice(pool, 60, replace=False)
    b0 = np.asarray(objective([{k: float(v) for k, v in f.iloc[i].items()} for i in cand]))
    pick = [c for c, b in zip(cand, b0) if 0.15 <= b <= 0.85][:3] or list(cand[:3])
    instances = []
    for i in pick:
        r = {k: float(v) for k, v in f.iloc[i].items()}
        kn = knobs(r)
        env = whatif(objective, r, kn, k=K, budget=BUDGET, batch=24, support=support, goal="both")
        instances.append({
            "id": int(i),
            "title": f"CGM {r['cgm_now']:.0f} mg/dL at {int(r['hour']):02d}:00",
            "check": check(objective, r, kn, env),
            "knobs": knobs_json(kn, r),
            "facts": {k: round(r[k], 1) for k in cols},
            "held": ["cgm_now", "cgm_15m_ago", "cgm_1h_ago", "hour"],
            "observed": f"{y.iloc[i]:.0f} mg/dL next hour",
            "curves": [
                sweep(objective, r, "insulin_30m", [0, 1, 2, 3, 4, 5, 6, 8, 10], "Insulin, last 30 min (U)"),
                sweep(objective, r, "carbs_30m", list(range(0, 81, 10)), "Carbs, last 30 min (g)"),
            ],
            **whatif_json(env),
        })
        print(f"  cgm {r['cgm_now']:.0f}: base {env.base:.2f} best {env.best.values[env.best.best_mask]:.2f} worst {env.worst.values[env.worst.best_mask]:.2f}")
    return {
        "domain": "glucose",
        "title": "Glucose",
        "question": "Which insulin and carb amounts, within a feasible range, make glucose most likely to stay in 70-180 mg/dL over the next hour?",
        "outcome": "P(in range 70-180 mg/dL)",
        "unit": "probability",
        "higher_is_better": True,
        "pipeline": [
            "Source: AZT1D, 25 people with type 1 diabetes on automated insulin delivery, 6-8 weeks of 5-minute CGM, insulin and carbohydrate logs (Khamesian et al. 2025, CC BY 4.0).",
            "Each row is one moment. Glucose now, 15 minutes ago and 1 hour ago come from the CGM trace.",
            "Insulin and carbohydrate are active amounts: each logged dose or meal is weighted by an absorption curve (scripts/azt1d.py), then summed over the last 30 minutes and over the 30 minutes before that, so timing is visible.",
            "Hour of day is kept. The target is glucose one hour ahead.",
            "Train: 3,000 rows. Four patients are held out entirely and never seen in training.",
            "The outcome is P(70 <= glucose <= 180 mg/dL), read from the model's predictive distribution (quantiles, interpolated CDF).",
            "Feasible range: insulin in each window from 0 to the logged dose + 8 U in 1 U steps, carbohydrate from 0 to the logged amount + 60 g in 10 g steps. The CGM history and the hour stay fixed.",
            "Search: The optimization algorithm (TPE) proposes any number of changed inputs at once, about 300 model rows per side. A grid brute force over every allowed design checks the result.",
        ],
        "card": {
            "dataset": "AZT1D, type 1 diabetes on automated insulin delivery (Khamesian et al. 2025)",
            "license": "CC BY 4.0",
            "rows": int(len(tr)),
            "model": MODEL + " regressor, quantile distribution",
            "holdout": f"MAE {mae:.1f} mg/dL on 4 unseen patients",
            "note": "Associational model: dosing effects are confounded by why people dose.",
        },
        "k": None,
        "instances": instances,
    }


# ----------------------------------------------------------------- football
def football() -> dict:
    import xi_model as xm

    payload = xm._current_payload()
    clf, train = xm.get_clf(os.getenv("TABPFN_MODE", "fast"))
    squads = xm.load_squads()
    sides = json.loads(xm.LAST_SIDES_PATH.read_text()) if xm.LAST_SIDES_PATH.is_file() else {}
    alias = {"schalke": "fcschalke04", "paderborn": "scpaderborn07", "elversberg": "sv07elversberg"}

    def stored(key):
        return sides.get(key) or sides.get(alias.get(key, ""), {})

    instances = []
    preds = payload.get("predictions") or []
    freiburg = [fx for fx in preds if fx.get("home_key") == "freiburg" or fx.get("away_key") == "freiburg"]
    for fx in (freiburg or preds)[:1]:
        lu = fx["lineups"]

        def lineup(which, fx=fx, lu=lu):
            got = list(lu[which]["players"] or [])
            if len(got) >= 11:
                return got[:11]
            return list(stored(fx[f"{which}_key"]).get("xi") or [])[:11]

        home, away = lineup("home"), lineup("away")
        if len(home) < 11 or len(away) < 11:
            print(f"  skip {fx.get('home_key')} vs {fx.get('away_key')}: XI {len(home)}/{len(away)}")
            continue
        base = xm._template_row_from_last(train, fx["home_key"], fx["away_key"])
        actual = xm.predict_rows(clf, [xm.row_from_xis(base, home, away)])[0]

        def pack(players):
            return [{"name": p["name"], "pos": p.get("pos") or "M",
                     "value": round(float(p.get("value_eur") or 0) / 1e6, 1)} for p in players]

        def side_env(which, xi, opp):
            key = fx[f"{which}_key"]
            pool = (squads.get(key) or squads.get(alias.get(key, "")) or {}).get("players") or lu[which].get("pool") or []
            ids = {str(p["id"]) for p in xi}
            by_id = {str(c["id"]): c for c in pool if c.get("id") is not None}
            pos = lambda p: p.get("pos") or "M"
            h = which == "home"
            kn, kslots = [], []
            nm = {str(p["id"]): p["name"] for p in xi}
            for i, st in enumerate(xi):
                cands = [cid for cid, c in by_id.items() if cid not in ids and pos(c) == pos(st)]
                if not cands:
                    continue

                def put(s, cid, i=i):
                    cur = list(s[0] if h else s[1])
                    cur[i] = by_id[cid]
                    return (cur, s[1]) if h else (s[0], cur)

                kn.append(Knob(
                    f"slot{i}", st["name"], choices=cands, put=put, fmt=lambda cid: (by_id.get(cid) or {}).get("name") or nm.get(cid, cid),
                    get=lambda s, i=i: str((s[0] if h else s[1])[i]["id"]),
                    name=lambda old, new, st=st: f"{st['name']} → {by_id[new]['name']}",
                    meta=lambda old, new, i=i, st=st: {"i": i, "out": st["name"], "in": by_id[new]["name"], "pos": pos(st)},
                ))
                kslots.append(st)
            clash = lambda d: len(d) - len(set(d.values()))  # one player cannot fill two slots
            out = "home_win" if h else "away_win"

            def predict(states, base=base, out=out):
                rows = [xm.row_from_xis(base, hx, ax) for hx, ax in states]
                return [p[out] for p in xm.predict_rows(clf, rows)]

            env = whatif(predict, (home, away), kn, k=K, budget=BUDGET, batch=25, conflicts=clash, goal="both")
            short = lambda w: {"S04": "Schalke"}.get(fx[f"{w}_short"], fx[f"{w}_short"])
            return {
                "label": short(which), "outcome": f"P({which} win)",
                "xi": pack(xi), "opponent": pack(opp), "opponent_label": short("away" if h else "home"),
                "knobs": [{**k, "label": f"{pos(st)} · {k['label']}", "range": ", ".join(k["choices"])}
                          for k, st in zip(knobs_json(kn, (home, away)), kslots)],
                **whatif_json(env),
                "check": check(None, (home, away), kn, env, conflicts=clash),
            }

        home_side = side_env("home", home, away)
        away_side = side_env("away", away, home)
        instances.append({
            "id": fx["match_id"],
            "title": f"{fx['home_short']} vs {'Schalke' if fx['away_short'] == 'S04' else fx['away_short']}",
            "facts": {"home": fx["home_short"], "away": fx["away_short"]},
            "observed": fx.get("date", "")[:10],
            "probs": {k: round(actual[k], 3) for k in ("home_win", "draw", "away_win")},
            "snapshot": [
                {"label": "Elo", "home": round(base["home_elo"]), "away": round(base["away_elo"])},
                {"label": "Form, last 5 (pts/game)", "home": round(base["home_form5"], 2), "away": round(base["away_form5"], 2)},
                {"label": "Goal diff, last 5", "home": round(base["home_gd5"], 1), "away": round(base["away_gd5"], 1)},
                {"label": "Rest (days)", "home": base["home_rest"], "away": base["away_rest"]},
            ],
            "xi": home_side["xi"],
            "sides": {"home": home_side, "away": away_side},
            **{k: home_side[k] for k in ("base", "best", "worst", "calls", "singles", "flagged", "check") if k in home_side},
        })
        print(f"  {fx['home_short']}: home {home_side['base']:.2f}->{home_side['best']['value']:.2f}  away {away_side['base']:.2f}->{away_side['best']['value']:.2f}")
    return {
        "domain": "football",
        "title": "Football",
        "question": "Which same-position squad changes give a side its highest win probability?",
        "outcome": "Win probability",
        "pipeline": [
            "One row per Bundesliga match, built only from what is known before kickoff (datasets/matches.csv, 2019-2026).",
            "Club strength: Elo, points and goal difference over the last 5 games, days of rest, and the head-to-head record. Each is taken from that club's most recent match, home or away.",
            "The starting XI is each club's previous lineup; squads come from datasets/squads.json.",
            "The eleven names go in as text features. A swap rebuilds the name string; Elo, form and rest stay as they are.",
            "Feasible range: each starter may stay or be replaced by any same-position squad player not in the XI, any number of changes, and one player can fill only one slot. The other club's XI is held fixed.",
            "Search: the optimization algorithm (TPE), about 400 model rows per side, out of billions of allowed lineups. Home and away are searched separately; the outcome is that side's win probability.",
        ],
        "card": {
            "dataset": "Bundesliga results plus Elo, rest, form and starting XIs",
            "license": "open match data; squads via the squad snapshot",
            "rows": int(len(train)),
            "model": MODEL + " classifier, XI names as features",
            "holdout": "trained on every finished match in datasets/matches.csv",
            "note": "A swap only changes the XI. The opponent's lineup, Elo and form stay put.",
        },
        "k": None,
        "instances": instances,
    }


if __name__ == "__main__":
    _init()
    todo = os.getenv("DOMAINS", "mortality,glucose,football").split(",")
    for name in todo:
        print(name)
        _save(name, globals()[name]())
