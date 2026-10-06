"""TabPFN 3.5 Bundesliga result model + lineup what-if lab."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from dataset import (
    MATCHES_PATH,
    MODEL_FEATURES,
    build_matches,
    feature_frame,
    trainable,
)
from xi_table import (
    LAST_SIDES_PATH,
    ROOT,
    _order_xi,
    load_lineups,
    upcoming_fixtures,
)

SQUADS_PATH = ROOT / "datasets" / "squads.json"
MODEL_VERSION = "v3.5"
OUTCOME_MAP = {"H": "home_win", "D": "draw", "A": "away_win", "home_win": "home_win", "draw": "draw", "away_win": "away_win"}


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


def _init_tabpfn():
    token = _token()
    if not token:
        raise SystemExit("TabPFN required: set TABPFN_API_KEY in .env")
    os.environ["TABPFN_TOKEN"] = token
    from tabpfn_client import init, set_access_token
    from tabpfn_client.config import Config

    set_access_token(token)
    Config.is_initialized = False
    init()


def _make_clf(mode: str = "plus"):
    from tabpfn_client import TabPFNClassifier

    mode = (mode or "plus").lower()
    if mode == "fast":
        try:
            return TabPFNClassifier.create_default_for_version(MODEL_VERSION, model_path="fast")
        except TypeError:
            clf = TabPFNClassifier.create_default_for_version(MODEL_VERSION)
            if hasattr(clf, "model") or True:
                return clf
    if mode == "thinking":
        try:
            return TabPFNClassifier.create_default_for_version("v3.5-thinking")
        except Exception:
            try:
                return TabPFNClassifier(model_path="tabpfn-3.5-thinking")
            except Exception:
                return TabPFNClassifier.create_default_for_version(MODEL_VERSION)
    return TabPFNClassifier.create_default_for_version(MODEL_VERSION)


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    return feature_frame(df, for_model=True)


def _fit_results(results: pd.DataFrame, mode: str = "plus"):
    y = results["outcome"].astype(str).map(lambda x: OUTCOME_MAP.get(x, x))
    print(f"Training TabPFN {MODEL_VERSION} ({mode}) on {len(results)} matches ({y.value_counts().to_dict()})…")
    _init_tabpfn()
    clf = _make_clf(mode)
    X = _frame(results)
    kwargs = {}
    if mode == "thinking":
        if "date" in results.columns:
            # Thinking mode: pass temporal context when the client supports it.
            try:
                clf.fit(X, y, time_col=pd.to_datetime(results["date"]))
                return clf
            except TypeError:
                pass
    clf.fit(X, y, **kwargs)
    return clf


def _outcome_probs(clf, frame: pd.DataFrame) -> list[dict]:
    proba = clf.predict_proba(frame)
    classes = [str(c) for c in list(clf.classes_)]

    def one(row) -> dict:
        packed = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
        for label, value in zip(classes, row):
            key = OUTCOME_MAP.get(label, label)
            if key in packed:
                packed[key] = float(value)
        return packed

    return [one(row) for row in proba]


def _write(payload: dict) -> None:
    dest = ROOT / "app" / "data" / "predictions.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _current_payload() -> dict:
    path = ROOT / "app" / "data" / "predictions.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _lineup_pack(players: list[dict], source: str = "last_xi") -> dict:
    ordered = _order_xi(players)[:11]
    return {
        "source": source,
        "formation": None,
        "players": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "number": p.get("number"),
                "pos": p.get("pos"),
                "age": p.get("age"),
                "value_eur": p.get("value_eur"),
                "strength": 1,
            }
            for p in ordered
        ],
        "pool": [],
    }


def build_squads(seasons: list[int] | None = None) -> dict:
    """Season squad pool per club from lineups.json."""
    blob = load_lineups()
    now = pd.Timestamp.now()
    end = now.year if now.month >= 7 else now.year - 1
    latest = max((int(r.get("season") or 0) for r in blob.values()), default=end)
    seasons = seasons or [latest]  # current season only: last season's players may have left
    pools: dict[str, dict] = {}
    for rec in blob.values():
        if int(rec.get("season") or 0) not in seasons:
            continue
        for side in ("home", "away"):
            key = rec.get(f"{side}_key")
            if not key:
                continue
            bucket = pools.setdefault(key, {"team": rec.get(f"{side}_name") or key, "players": {}})
            for p in list(rec.get(f"{side}_xi") or []) + list(rec.get(f"{side}_bench") or []):
                pid = str(p.get("id"))
                prev = bucket["players"].get(pid)
                if prev is None or (p.get("value_eur") or 0) >= (prev.get("value_eur") or 0):
                    bucket["players"][pid] = {
                        "id": p.get("id"),
                        "name": p.get("name"),
                        "number": p.get("number"),
                        "pos": p.get("pos"),
                        "age": p.get("age"),
                        "value_eur": p.get("value_eur") or 0,
                    }
    out = {}
    for key, bucket in pools.items():
        players = sorted(bucket["players"].values(), key=lambda p: (p.get("pos") or "M", -(p.get("value_eur") or 0)))
        out[key] = {"team": bucket["team"], "players": players}
    SQUADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQUADS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Squads: {len(out)} clubs -> {SQUADS_PATH.name}")
    return out


def load_squads() -> dict:
    if SQUADS_PATH.is_file():
        return json.loads(SQUADS_PATH.read_text(encoding="utf-8"))
    return build_squads()


def _xi_feats_from_players(players: list[dict], prefix: str, player_stats: dict | None = None) -> dict:
    ordered = _order_xi(players)[:11]
    by_pos = {"G": 0.0, "D": 0.0, "M": 0.0, "F": 0.0}
    total = 0.0
    ages = []
    names = []
    ids = []
    for p in ordered:
        val = float(p.get("value_eur") or 0.0)
        pos = p.get("pos") or "M"
        by_pos[pos] = by_pos.get(pos, 0.0) + val
        total += val
        if p.get("age"):
            ages.append(float(p["age"]))
        names.append(p.get("name") or "")
        ids.append(int(p["id"]))
    ppg, pgd = 1.0, 0.0
    if player_stats and ids:
        vals_ppg, vals_gd = [], []
        for pid in ids:
            hist = player_stats.get(pid) or player_stats.get(str(pid)) or []
            if hist:
                vals_ppg.append(float(np.mean([h[0] for h in hist[-8:]])))
                vals_gd.append(float(np.mean([h[1] for h in hist[-8:]])))
        if vals_ppg:
            ppg, pgd = float(np.mean(vals_ppg)), float(np.mean(vals_gd))
    return {
        f"{prefix}_value": total / 1e6,
        f"{prefix}_gk_value": by_pos["G"] / 1e6,
        f"{prefix}_def_value": by_pos["D"] / 1e6,
        f"{prefix}_mid_value": by_pos["M"] / 1e6,
        f"{prefix}_fwd_value": by_pos["F"] / 1e6,
        f"{prefix}_age": float(np.mean(ages)) if ages else 26.0,
        f"{prefix}_player_ppg": ppg,
        f"{prefix}_player_gd": pgd,
        f"{prefix}_xi": ", ".join(names),
        f"{prefix}_continuity": 11,
    }


def _template_row_from_last(matches: pd.DataFrame, home_key: str, away_key: str) -> dict:
    """Latest feature snapshot for each club (team strength half of the row)."""
    df = matches.copy()
    df["date"] = pd.to_datetime(df["date"])
    # Prefer most recent appearance for each side, home or away.
    def last_team_row(key: str) -> pd.Series | None:
        as_home = df[df["home_key"] == key]
        as_away = df[df["away_key"] == key]
        cands = []
        if not as_home.empty:
            cands.append(("home", as_home.sort_values("date").iloc[-1]))
        if not as_away.empty:
            cands.append(("away", as_away.sort_values("date").iloc[-1]))
        if not cands:
            return None
        cands.sort(key=lambda x: x[1]["date"])
        side, row = cands[-1]
        return side, row

    h = last_team_row(home_key)
    a = last_team_row(away_key)
    row = {c: 0.0 for c in MODEL_FEATURES}
    row["home_xi"] = ""
    row["away_xi"] = ""
    if h:
        side, r = h
        p = "home" if side == "home" else "away"
        row["home_elo"] = float(r[f"{p}_elo"])
        row["home_form5"] = float(r[f"{p}_form5"])
        row["home_gd5"] = float(r[f"{p}_gd5"])
        row["home_shots5"] = float(r[f"{p}_shots5"])
        row["home_sot5"] = float(r[f"{p}_sot5"])
        row["home_rest"] = 7
    if a:
        side, r = a
        p = "home" if side == "home" else "away"
        row["away_elo"] = float(r[f"{p}_elo"])
        row["away_form5"] = float(r[f"{p}_form5"])
        row["away_gd5"] = float(r[f"{p}_gd5"])
        row["away_shots5"] = float(r[f"{p}_shots5"])
        row["away_sot5"] = float(r[f"{p}_sot5"])
        row["away_rest"] = 7
    row["elo_diff"] = row["home_elo"] + 65.0 - row["away_elo"]
    row["form5_diff"] = row["home_form5"] - row["away_form5"]
    return row


def row_from_xis(
    base: dict,
    home_players: list[dict],
    away_players: list[dict],
    home_rest: int = 7,
    away_rest: int = 7,
    home_cont: int = 11,
    away_cont: int = 11,
) -> dict:
    row = dict(base)
    row.update(_xi_feats_from_players(home_players, "home"))
    row.update(_xi_feats_from_players(away_players, "away"))
    row["home_rest"] = home_rest
    row["away_rest"] = away_rest
    row["home_continuity"] = home_cont
    row["away_continuity"] = away_cont
    row["value_diff"] = float(row["home_value"]) - float(row["away_value"])
    return row


def predict_rows(clf, rows: list[dict]) -> list[dict]:
    frame = _frame(pd.DataFrame(rows))
    return _outcome_probs(clf, frame)


_CLF_CACHE: dict = {}


def get_clf(mode: str | None = None):
    mode = mode or os.getenv("TABPFN_MODE", "plus")
    key = f"{mode}:{MATCHES_PATH.stat().st_mtime if MATCHES_PATH.is_file() else 0}"
    if key in _CLF_CACHE:
        return _CLF_CACHE[key]
    matches = pd.read_csv(MATCHES_PATH) if MATCHES_PATH.is_file() else build_matches(sync=False)
    train = trainable(matches)
    clf = _fit_results(train, mode=mode)
    _CLF_CACHE.clear()
    _CLF_CACHE[key] = (clf, train)
    return _CLF_CACHE[key]


FEATURE_GROUPS = [
    ("Elo", ["home_elo", "away_elo", "elo_diff"]),
    ("Form", ["home_form5", "away_form5", "form5_diff", "home_gd5", "away_gd5"]),
    ("Rest", ["home_rest", "away_rest"]),
    ("Head-to-head", ["h2h_n", "h2h_home_winrate", "h2h_draw_rate", "h2h_gd"]),
    ("Market value", [
        "home_value", "away_value", "value_diff",
        "home_gk_value", "away_gk_value", "home_def_value", "away_def_value",
        "home_mid_value", "away_mid_value", "home_fwd_value", "away_fwd_value",
    ]),
    ("Continuity", ["home_continuity", "away_continuity"]),
    ("On-pitch form", ["home_player_ppg", "away_player_ppg", "home_player_gd", "away_player_gd"]),
    ("XI names", ["home_xi", "away_xi"]),
]


def run() -> None:
    """Refresh app/data/predictions.json: next matchday, each side's last XI and squad pool."""
    _load_dotenv()
    os.environ.setdefault("TABPFN_NO_BROWSER", "1")
    matches = build_matches(sync=True)
    meta, fixtures = upcoming_fixtures()
    train = trainable(matches)
    if train.empty:
        raise SystemExit("No trainable matches with previous XIs")
    clf = _fit_results(train, mode=os.getenv("TABPFN_MODE", "plus"))
    sides = json.loads(LAST_SIDES_PATH.read_text(encoding="utf-8")) if LAST_SIDES_PATH.is_file() else {}
    squads = build_squads([meta["season"] - 1, meta["season"]])

    pred_rows = []
    for fx in fixtures:
        xi, pool = {}, {}
        for which in ("home", "away"):
            key = fx[f"{which}_key"]
            squad = list((squads.get(key) or {}).get("players") or [])
            xi[which] = list((sides.get(key) or {}).get("xi") or []) or _order_xi(squad)[:11]
            pool[which] = [
                {k: p.get(k) for k in ("id", "name", "number", "pos", "value_eur")} for p in squad[:24]
            ]
        base = _template_row_from_last(train, fx["home_key"], fx["away_key"])
        probs = predict_rows(clf, [row_from_xis(base, xi["home"], xi["away"])])[0]
        print(f"  {fx['home_short']} vs {fx['away_short']}: H {probs['home_win']:.0%} D {probs['draw']:.0%} A {probs['away_win']:.0%}")
        lineups = {w: {**_lineup_pack(xi[w]), "pool": pool[w]} for w in ("home", "away")}
        pred_rows.append({
            "match_id": fx["match_id"],
            "date": pd.to_datetime(fx["date"], utc=True).isoformat(),
            "home_team": fx["home_team"], "away_team": fx["away_team"],
            "home_short": fx["home_short"], "away_short": fx["away_short"],
            "home_key": fx["home_key"], "away_key": fx["away_key"],
            "p_home_win": probs["home_win"], "p_draw": probs["draw"], "p_away_win": probs["away_win"],
            "lineups": lineups,
        })

    _write({
        "league": "Bundesliga",
        "season": f"{meta['season']}/{meta['season'] + 1}",
        "matchday": meta["matchday"],
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "model": f"TabPFN-3.5 ({os.getenv('TABPFN_MODE', 'plus')})",
        "train_rows": int(len(train)),
        "table": "datasets/matches.csv",
        "predictions": pred_rows,
    })
    print(f"Wrote {len(pred_rows)} fixtures")


if __name__ == "__main__":
    run()
