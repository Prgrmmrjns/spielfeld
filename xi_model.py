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
    build_tables,
    upcoming_fixtures,
)

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


def run() -> None:
    _load_dotenv()
    os.environ.setdefault("TABPFN_NO_BROWSER", "1")
    os.environ.setdefault("TABPFN_CLIENT_NO_BROWSER", "1")
    stats = build_tables()
    meta, fixtures = upcoming_fixtures()
    print(f"Next matchday: {meta['matchday_name']} ({meta['season']}) — {len(fixtures)} fixtures")
    baked = _current_payload()
    same_md = (
        baked.get("task") == "best_xi"
        and baked.get("matchday") == meta["matchday"]
        and str(baked.get("season", "")).startswith(str(meta["season"]))
        and "3.5" in str(baked.get("model", ""))
    )
    if stats["added_lineups"] == 0 and same_md and os.getenv("FORCE_RETRAIN") != "1":
        print("No new matchday rows — TabPFN refit skipped")
        return
    if not PLAYERS_CSV.is_file():
        raise SystemExit(f"Missing training table {PLAYERS_CSV}")
    players = pd.read_csv(PLAYERS_CSV)
    if players.empty:
        raise SystemExit("Training table is empty — no previous-XI rows yet")
    clf = _fit(players)
    version = "TabPFN-3.5"
    meta_info = getattr(clf, "last_meta", None)
    if isinstance(meta_info, dict) and meta_info.get("model_version"):
        version = f"TabPFN-3.5 ({meta_info['model_version']})"

    sides = json.loads(LAST_SIDES_PATH.read_text(encoding="utf-8"))
    rows = []
    for fx in fixtures:
        kick = pd.to_datetime(fx["date"], utc=True).tz_localize(None)
        lineups = {}
        best = {}
        for side_name, key, opp, is_home in (
            ("home", fx["home_key"], fx["away_team"], 1),
            ("away", fx["away_key"], fx["home_team"], 0),
        ):
            side = sides.get(key)
            if not side:
                lineups[side_name] = {"source": "unknown", "players": [], "pool": []}
                best[side_name] = {"summary": "no last XI", "changes": None}
                continue
            packed = _predict_side(clf, side, opp, is_home, meta["matchday"], kick)
            best[side_name] = {
                "changes": packed["changes"],
                "incoming": packed["incoming"],
                "outgoing": packed["outgoing"],
                "summary": packed["summary"],
                "mean_p": packed["mean_p"],
                "last_result": packed["last_result"],
            }
            lineups[side_name] = {
                "source": "predicted",
                "formation": None,
                "players": packed["players"],
                "pool": packed["pool"],
                "strength": packed["strength"],
            }
            print(f"  {side['team']}: {packed['summary']}")
        rows.append({
            "match_id": fx["match_id"],
            "date": pd.to_datetime(fx["date"], utc=True).isoformat(),
            "home_team": fx["home_team"],
            "away_team": fx["away_team"],
            "home_short": fx["home_short"],
            "away_short": fx["away_short"],
            "home_icon": fx["home_icon"],
            "away_icon": fx["away_icon"],
            "predicted": None,
            "lineups": lineups,
            "best_xi": best,
        })

    payload = {
        "league": "Bundesliga",
        "season": f"{meta['season']}/{meta['season'] + 1}",
        "matchday": meta["matchday"],
        "matchday_name": meta["matchday_name"],
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "model": version,
        "task": "best_xi",
        "train_rows": int(len(players)),
        "train_matches": int(stats["team_matches"]),
        "lineups_provider": "tabpfn-3.5",
        "table": "data/xi_players.csv",
        "match_table": "data/xi_matches.csv",
        "data_note": (
            "OpenLigaDB fixtures and results. Transfermarkt starting XIs and benches. "
            "Each new finished matchday appends rows, then TabPFN 3.5 is refit via the API."
        ),
        "predictions": rows,
    }
    _write(payload)
    print(f"Wrote {len(rows)} best-XI predictions")


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


def write_history() -> None:
    """Walk-forward XIs: each matchday is fit only on games already played."""
    _load_dotenv()
    os.environ.setdefault("TABPFN_NO_BROWSER", "1")
    os.environ.setdefault("TABPFN_CLIENT_NO_BROWSER", "1")
    players = pd.read_csv(PLAYERS_CSV)
    matches = pd.read_csv(MATCHES_CSV)
    players["date"] = pd.to_datetime(players["date"])
    HISTORY.mkdir(parents=True, exist_ok=True)
    days = (
        players.groupby(["season", "matchday"], as_index=False)["date"]
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
        train = players[players["date"] < cutoff]
        test = players[(players["season"] == season) & (players["matchday"] == matchday)].copy()
        if train.empty or train["y_started"].nunique() < 2 or test.empty:
            print(f"skip {season} MD{matchday}: not enough prior rows")
            continue
        print(f"History {season} MD{matchday}: train {len(train)} / predict {len(test)}")
        clf = _fit(train)
        test["p"] = _p_start(clf, _frame(test))
        by_match: dict[int, dict] = {}
        correct = 0
        slots = 0
        for (match_id, team), group in test.groupby(["match_id", "team"], sort=False):
            scored = [
                {
                    "id": int(r.player_id),
                    "name": r.player_name,
                    "pos": r.position,
                    "number": 0,
                    "p": float(r.p),
                }
                for r in group.itertuples(index=False)
            ]
            chosen = _pick(scored)
            predicted = [p["name"] for p in chosen]
            actual = _actual_names(matches, int(match_id), str(team))
            hit = [n for n in predicted if n in set(actual)]
            correct += len(hit)
            slots += 11
            meta = matches[(matches["match_id"] == match_id) & (matches["team"] == team)]
            is_home = int(meta.iloc[0]["is_home"]) if not meta.empty else 0
            opponent = str(meta.iloc[0]["opponent"]) if not meta.empty else ""
            block = {
                "team": team,
                "opponent": opponent,
                "predicted": [
                    {"name": p["name"], "pos": p["pos"], "p": round(p["p"], 3)}
                    for p in chosen
                ],
                "actual": actual,
                "correct": len(hit),
            }
            entry = by_match.setdefault(int(match_id), {"match_id": int(match_id), "home": None, "away": None})
            entry["home" if is_home else "away"] = block
        fixtures = [f for f in by_match.values() if f.get("home") and f.get("away")]
        payload = {
            "faithful": True,
            "season": season,
            "matchday": matchday,
            "matchday_name": f"{matchday}. Spieltag",
            "cutoff": pd.Timestamp(cutoff).isoformat(),
            "train_rows": int(len(train)),
            "model": "TabPFN-3.5",
            "correct": correct,
            "slots": slots,
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "note": "Fit only on team-matches played before this Spieltag.",
            "fixtures": fixtures,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        rate = correct / slots if slots else 0
        print(f"  wrote {path.name} {correct}/{slots} ({rate:.0%})")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "history":
        write_history()
    else:
        run()
