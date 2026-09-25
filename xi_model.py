"""Best-XI model: TabPFN 3.5 on the last-game squad, refit after each new matchday."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from xi_table import (
    LAST_SIDES_PATH,
    MATCHES_CSV,
    PLAYERS_CSV,
    ROOT,
    _order_xi,
    build_tables,
    upcoming_fixtures,
)

RESULTS_CSV = ROOT / "data" / "results.csv"
RESULT_TEXT = [f"home_p{i}" for i in range(1, 12)] + [f"away_p{i}" for i in range(1, 12)]
RESULT_NUM = ["home_rest", "away_rest", "home_last_points", "away_last_points", "home_last_gd", "away_last_gd"]
RESULT_FEATURES = RESULT_TEXT + RESULT_NUM

HISTORY = ROOT / "history"

FEATURES = [
    "team",
    "opponent",
    "is_home",
    "matchday",
    "rest_days",
    "last_points",
    "last_gd",
    "player_id",
    "player_name",
    "position",
    "started_last",
    "on_bench_last",
]
TEXT = ["team", "opponent", "player_id", "player_name", "position"]
MODEL_VERSION = "v3.5"


def _load_dotenv() -> None:
    for path in (ROOT / ".env", Path("/workspace/.env")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def _token() -> str | None:
    for key in ("TABPFN_TOKEN", "TABPFN_API_KEY", "TAP_PFN_API_KEY"):
        value = os.getenv(key)
        if value:
            return value.strip().strip('"').strip("'")
    return None


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df[FEATURES].copy()
    for col in TEXT:
        out[col] = out[col].astype("string")
    for col in ("is_home", "matchday", "rest_days", "last_points", "last_gd", "started_last", "on_bench_last"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _fit(players: pd.DataFrame):
    token = _token()
    if not token:
        raise SystemExit("TabPFN required: set TABPFN_API_KEY in .env")
    os.environ["TABPFN_TOKEN"] = token
    from tabpfn_client import TabPFNClassifier, init, set_access_token
    from tabpfn_client.config import Config

    set_access_token(token)
    # set_access_token marks the client initialized without checking the key.
    Config.is_initialized = False
    init()
    y = players["y_started"].astype(int)
    print(f"Training TabPFN {MODEL_VERSION} on {len(players)} player rows "
          f"({int(y.sum())} starts)…")
    clf = TabPFNClassifier.create_default_for_version(MODEL_VERSION)
    clf.fit(_frame(players), y)
    return clf


def _p_start(clf, frame: pd.DataFrame) -> list[float]:
    proba = clf.predict_proba(frame)
    classes = [int(c) for c in list(clf.classes_)]
    if 1 not in classes:
        return [0.0] * len(frame)
    idx = classes.index(1)
    return [float(row[idx]) for row in proba]


def _pick(scored: list[dict]) -> list[dict]:
    gks = sorted((p for p in scored if p["pos"] == "G"), key=lambda p: -p["p"])
    outfield = sorted((p for p in scored if p["pos"] != "G"), key=lambda p: -p["p"])
    chosen = []
    if gks:
        chosen.append(gks[0])
    chosen.extend(outfield[:10])
    if len(chosen) < 11:
        used = {p["id"] for p in chosen}
        rest = sorted((p for p in scored if p["id"] not in used), key=lambda p: -p["p"])
        chosen.extend(rest[: 11 - len(chosen)])
    return chosen[:11]


def _predict_side(clf, side: dict, opponent: str, is_home: int, matchday: int, kick: pd.Timestamp) -> dict:
    last_kick = pd.to_datetime(side["date"])
    rest = int((kick - last_kick).days)
    xi_ids = {p["id"] for p in side["xi"]}
    bench_ids = {p["id"] for p in side["bench"]}
    candidates = []
    seen = set()
    for p in list(side["xi"]) + list(side["bench"]):
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        candidates.append(p)
    rows = []
    for p in candidates:
        rows.append({
            "team": side["team"],
            "opponent": opponent,
            "is_home": is_home,
            "matchday": matchday,
            "rest_days": rest,
            "last_points": side["points"],
            "last_gd": side["gd"],
            "player_id": str(p["id"]),
            "player_name": p["name"],
            "position": p["pos"],
            "started_last": int(p["id"] in xi_ids),
            "on_bench_last": int(p["id"] in bench_ids and p["id"] not in xi_ids),
        })
    frame = _frame(pd.DataFrame(rows))
    probs = _p_start(clf, frame)
    scored = []
    for p, prob in zip(candidates, probs):
        scored.append({**p, "p": prob})
    chosen = _pick(scored)
    chosen_ids = {p["id"] for p in chosen}
    incoming = [p["name"] for p in chosen if p["id"] not in xi_ids]
    outgoing = [p["name"] for p in side["xi"] if p["id"] not in chosen_ids]
    pool = [p for p in scored if p["id"] not in chosen_ids]
    pool.sort(key=lambda p: -p["p"])

    def pack(p: dict) -> dict:
        return {
            "id": p["id"],
            "name": p["name"],
            "number": p.get("number"),
            "pos": p.get("pos"),
            "strength": round(float(p["p"]), 3),
        }

    if not incoming:
        summary = "same as last game"
    else:
        summary = "in " + ", ".join(incoming[:4])
    return {
        "source": "predicted",
        "formation": None,
        "players": [pack(p) for p in chosen],
        "pool": [pack(p) for p in pool[:16]],
        "strength": round(sum(p["p"] for p in chosen), 3),
        "changes": len(incoming),
        "incoming": incoming,
        "outgoing": outgoing,
        "summary": summary,
        "mean_p": round(sum(p["p"] for p in chosen) / max(len(chosen), 1), 3),
        "last_xi": [p["name"] for p in side["xi"]],
        "last_result": f"{side['points']} pts, GD {side['gd']:+d} vs {side['opponent']}",
    }


def _write(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for dest in (
        ROOT / "app" / "data" / "predictions.json",
        ROOT / "public" / "data" / "predictions.json",
        ROOT / "predictions.json",
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def _current_payload() -> dict:
    path = ROOT / "app" / "data" / "predictions.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _result_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df[RESULT_FEATURES].copy()
    for col in RESULT_TEXT:
        out[col] = out[col].fillna("").astype("string")
    for col in RESULT_NUM:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def build_results(matches: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per match. Features are each side's previous starting XI."""
    if matches is None:
        matches = pd.read_csv(MATCHES_CSV)
    home = matches[matches["is_home"] == 1]
    away = matches[matches["is_home"] == 0]
    merged = home.merge(away, on="match_id", suffixes=("_h", "_a"))
    has_xi = (
        merged["last_1_h"].fillna("").astype(str).str.len().gt(0)
        & merged["last_1_a"].fillna("").astype(str).str.len().gt(0)
    )
    merged = merged.loc[has_xi].copy()
    out = pd.DataFrame({
        "season": merged["season_h"].astype(int),
        "matchday": merged["matchday_h"].astype(int),
        "match_id": merged["match_id"].astype(int),
        "date": merged["date_h"],
        "home_team": merged["team_h"],
        "away_team": merged["team_a"],
        "home_rest": merged["rest_days_h"],
        "away_rest": merged["rest_days_a"],
        "home_last_points": merged["last_points_h"],
        "away_last_points": merged["last_points_a"],
        "home_last_gd": merged["last_gd_h"],
        "away_last_gd": merged["last_gd_a"],
    })
    for i in range(1, 12):
        out[f"home_p{i}"] = merged[f"last_{i}_h"].fillna("").astype(str).values
        out[f"away_p{i}"] = merged[f"last_{i}_a"].fillna("").astype(str).values
    gf = pd.to_numeric(merged["gf_h"], errors="coerce")
    ga = pd.to_numeric(merged["ga_h"], errors="coerce")
    out["outcome"] = [
        "home_win" if h > a else ("away_win" if h < a else "draw")
        for h, a in zip(gf, ga)
    ]
    out = out.loc[gf.notna() & ga.notna()].reset_index(drop=True)
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(RESULTS_CSV, index=False)
    print(f"Result table: {len(out)} matches with both previous XIs -> {RESULTS_CSV.name}")
    return out


def _fit_results(results: pd.DataFrame):
    y = results["outcome"].astype(str)
    print(
        f"Training TabPFN {MODEL_VERSION} on {len(results)} matches "
        f"({y.value_counts().to_dict()})…"
    )
    token = _token()
    if not token:
        raise SystemExit("TabPFN required: set TABPFN_API_KEY in .env")
    os.environ["TABPFN_TOKEN"] = token
    from tabpfn_client import TabPFNClassifier, init, set_access_token
    from tabpfn_client.config import Config

    set_access_token(token)
    Config.is_initialized = False
    init()
    clf = TabPFNClassifier.create_default_for_version(MODEL_VERSION)
    clf.fit(_result_frame(results), y)
    return clf


def _outcome_probs(clf, frame: pd.DataFrame) -> list[dict]:
    proba = clf.predict_proba(frame)
    classes = [str(c) for c in list(clf.classes_)]

    def one(row) -> dict:
        packed = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
        for label, value in zip(classes, row):
            if label in packed:
                packed[label] = float(value)
        return packed

    return [one(row) for row in proba]


def _names_from_side(side: dict | None) -> list[str]:
    if not side:
        return [""] * 11
    ordered = _order_xi(side.get("xi") or [])[:11]
    names = [p.get("name") or "" for p in ordered]
    return names + [""] * (11 - len(names))


def _lineup_from_side(side: dict | None) -> dict:
    if not side:
        return {"source": "unknown", "players": [], "pool": []}
    players = []
    for p in _order_xi(side.get("xi") or [])[:11]:
        players.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "number": p.get("number"),
            "pos": p.get("pos"),
            "strength": 1,
        })
    return {"source": "last_xi", "formation": None, "players": players, "pool": []}


def run() -> None:
    _load_dotenv()
    os.environ.setdefault("TABPFN_NO_BROWSER", "1")
    os.environ.setdefault("TABPFN_CLIENT_NO_BROWSER", "1")
    stats = build_tables()
    meta, fixtures = upcoming_fixtures()
    print(f"Next matchday: {meta['matchday_name']} ({meta['season']}) — {len(fixtures)} fixtures")
    baked = _current_payload()
    same_md = (
        baked.get("task") == "result"
        and baked.get("matchday") == meta["matchday"]
        and str(baked.get("season", "")).startswith(str(meta["season"]))
        and "3.5" in str(baked.get("model", ""))
    )
    if stats["added_lineups"] == 0 and same_md and os.getenv("FORCE_RETRAIN") != "1":
        print("No new matchday rows — TabPFN refit skipped")
        return
    results = build_results()
    if results.empty:
        raise SystemExit("No matches with a previous XI on both sides")
    clf = _fit_results(results)
    version = "TabPFN-3.5"
    meta_info = getattr(clf, "last_meta", None)
    if isinstance(meta_info, dict) and meta_info.get("model_version"):
        version = f"TabPFN-3.5 ({meta_info['model_version']})"

    sides = json.loads(LAST_SIDES_PATH.read_text(encoding="utf-8"))
    pred_rows = []
    for fx in fixtures:
        kick = pd.to_datetime(fx["date"], utc=True).tz_localize(None)
        home = sides.get(fx["home_key"])
        away = sides.get(fx["away_key"])
        home_names = _names_from_side(home)
        away_names = _names_from_side(away)
        home_kick = pd.to_datetime(home["date"]) if home else kick
        away_kick = pd.to_datetime(away["date"]) if away else kick
        row = {
            "home_rest": int((kick - home_kick).days) if home else 7,
            "away_rest": int((kick - away_kick).days) if away else 7,
            "home_last_points": home["points"] if home else 1,
            "away_last_points": away["points"] if away else 1,
            "home_last_gd": home["gd"] if home else 0,
            "away_last_gd": away["gd"] if away else 0,
        }
        for i, name in enumerate(home_names, start=1):
            row[f"home_p{i}"] = name
        for i, name in enumerate(away_names, start=1):
            row[f"away_p{i}"] = name
        probs = _outcome_probs(clf, _result_frame(pd.DataFrame([row])))[0]
        predicted = max(probs, key=probs.get)
        print(
            f"  {fx['home_short']} vs {fx['away_short']}: {predicted} "
            f"H {probs['home_win']:.0%} D {probs['draw']:.0%} A {probs['away_win']:.0%}"
        )
        pred_rows.append({
            "match_id": fx["match_id"],
            "date": pd.to_datetime(fx["date"], utc=True).isoformat(),
            "home_team": fx["home_team"],
            "away_team": fx["away_team"],
            "home_short": fx["home_short"],
            "away_short": fx["away_short"],
            "home_icon": fx["home_icon"],
            "away_icon": fx["away_icon"],
            "predicted": predicted,
            "p_home_win": probs["home_win"],
            "p_draw": probs["draw"],
            "p_away_win": probs["away_win"],
            "lineups": {
                "home": _lineup_from_side(home),
                "away": _lineup_from_side(away),
            },
        })

    payload = {
        "league": "Bundesliga",
        "season": f"{meta['season']}/{meta['season'] + 1}",
        "matchday": meta["matchday"],
        "matchday_name": meta["matchday_name"],
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "model": version,
        "task": "result",
        "train_rows": int(len(results)),
        "train_matches": int(len(results)),
        "lineups_provider": "last-xi",
        "table": "data/results.csv",
        "match_table": "data/xi_matches.csv",
        "data_note": (
            "Win, draw, or away win. Features are the eleven players from each side’s previous game."
        ),
        "predictions": pred_rows,
    }
    _write(payload)
    print(f"Wrote {len(pred_rows)} match predictions")


def _actual_names(matches: pd.DataFrame, match_id: int, team: str) -> list[str]:
    hit = matches[(matches["match_id"] == match_id) & (matches["team"] == team)]
    if hit.empty:
        return []
    row = hit.iloc[0]
    names = []
    for i in range(1, 12):
        name = row.get(f"xi_{i}")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _result_label(code: str, home: str, away: str) -> str:
    if code == "home_win":
        return home
    if code == "away_win":
        return away
    return "Draw"


def write_history() -> None:
    """Walk-forward match tips: each Spieltag is fit only on games already played."""
    _load_dotenv()
    os.environ.setdefault("TABPFN_NO_BROWSER", "1")
    os.environ.setdefault("TABPFN_CLIENT_NO_BROWSER", "1")
    results = build_results()
    results["date"] = pd.to_datetime(results["date"])
    HISTORY.mkdir(parents=True, exist_ok=True)
    days = (
        results.groupby(["season", "matchday"], as_index=False)["date"]
        .min()
        .sort_values(["date", "season", "matchday"])
    )
    for day in days.itertuples(index=False):
        season, matchday = int(day.season), int(day.matchday)
        path = HISTORY / f"{season}-md{matchday:02d}.json"
        if path.is_file() and os.getenv("FORCE_HISTORY") != "1":
            print(f"skip {path.name}")
            continue
        cutoff = day.date
        train = results[results["date"] < cutoff]
        test = results[(results["season"] == season) & (results["matchday"] == matchday)].copy()
        if train.empty or train["outcome"].nunique() < 2 or test.empty:
            print(f"skip {season} MD{matchday}: not enough prior matches")
            continue
        print(f"History {season} MD{matchday}: train {len(train)} / predict {len(test)}")
        clf = _fit_results(train)
        probs = _outcome_probs(clf, _result_frame(test))
        fixtures = []
        correct = 0
        for row, prob in zip(test.itertuples(index=False), probs):
            predicted = max(prob, key=prob.get)
            actual = str(row.outcome)
            hit = predicted == actual
            correct += int(hit)
            fixtures.append({
                "match_id": int(row.match_id),
                "home_team": row.home_team,
                "away_team": row.away_team,
                "p_home_win": prob["home_win"],
                "p_draw": prob["draw"],
                "p_away_win": prob["away_win"],
                "predicted": predicted,
                "actual": actual,
                "predicted_label": _result_label(predicted, row.home_team, row.away_team),
                "actual_label": _result_label(actual, row.home_team, row.away_team),
                "correct": hit,
            })
        payload = {
            "faithful": True,
            "task": "result",
            "season": season,
            "matchday": matchday,
            "matchday_name": f"{matchday}. Spieltag",
            "cutoff": pd.Timestamp(cutoff).isoformat(),
            "train_rows": int(len(train)),
            "model": "TabPFN-3.5",
            "correct": correct,
            "slots": len(fixtures),
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "note": "Fit only on matches played before this Spieltag. Features are each side’s previous XI.",
            "fixtures": fixtures,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        rate = correct / len(fixtures) if fixtures else 0
        print(f"  wrote {path.name} {correct}/{len(fixtures)} ({rate:.0%})")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "history":
        write_history()
    else:
        run()
