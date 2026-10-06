"""Build datasets/matches.csv — one pre-kickoff row per Bundesliga match."""
from __future__ import annotations

import os
from collections import defaultdict

import numpy as np
import pandas as pd

from xi_table import (
    DATA,
    _order_xi,
    backfill_lineups,
    build_tables,
    fetch_fd_seasons,
    fetch_openliga_season,
    load_lineups,
    save_lineups,
)

MATCHES_PATH = DATA / "matches.csv"
HOME_ADV = 65.0
IMPORTANCE = 20.0

MODEL_FEATURES = [
    "home_elo", "away_elo", "elo_diff",
    "home_form5", "away_form5", "form5_diff",
    "home_gd5", "away_gd5",
    "home_rest", "away_rest",
    "h2h_n", "h2h_home_winrate", "h2h_draw_rate", "h2h_gd",
    "home_value", "away_value", "value_diff",
    "home_gk_value", "away_gk_value",
    "home_def_value", "away_def_value",
    "home_mid_value", "away_mid_value",
    "home_fwd_value", "away_fwd_value",
    "home_continuity", "away_continuity",
    "home_player_ppg", "away_player_ppg",
    "home_player_gd", "away_player_gd",
    "home_xi", "away_xi",
]
TEXT_FEATURES = ["home_xi", "away_xi"]
BENCHMARK_FEATURES = ["odds_h", "odds_d", "odds_a"]
LABELS = ["outcome", "home_goals", "away_goals"]


def _elo_margin(gd: int) -> float:
    g = abs(int(gd))
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8


def _xi_value_by_pos(players: list[dict]) -> dict:
    out = {"G": 0.0, "D": 0.0, "M": 0.0, "F": 0.0, "total": 0.0, "age": [], "ids": set(), "names": []}
    for p in _order_xi(players)[:11]:
        val = float(p.get("value_eur") or 0.0)
        pos = p.get("pos") or "M"
        out[pos] = out.get(pos, 0.0) + val
        out["total"] += val
        if p.get("age"):
            out["age"].append(float(p["age"]))
        out["ids"].add(int(p["id"]))
        out["names"].append(p.get("name") or "")
    return out


def _player_strength(ids: set[int], stats: dict) -> tuple[float, float]:
    if not ids:
        return 1.0, 0.0
    ppgs, gds = [], []
    for pid in ids:
        hist = stats.get(pid) or []
        if not hist:
            continue
        window = hist[-8:]
        ppgs.append(float(np.mean([h[0] for h in window])))
        gds.append(float(np.mean([h[1] for h in window])))
    if not ppgs:
        return 1.0, 0.0
    return float(np.mean(ppgs)), float(np.mean(gds))


def _join_lineups(fd: pd.DataFrame, blob: dict, openliga: list[dict]) -> pd.DataFrame:
    """Attach previous-match XI (no leakage) to each football-data row."""
    ol_by_pair: dict = defaultdict(list)
    for f in openliga:
        if not f.get("finished") or f.get("home_score") is None:
            continue
        key = (int(f["season"]), frozenset((f["home_key"], f["away_key"])))
        ol_by_pair[key].append(f)

    def _nearest_ol(season: int, home_key: str, away_key: str, kick: pd.Timestamp):
        cands = ol_by_pair.get((season, frozenset((home_key, away_key)))) or []
        best, best_gap = None, None
        for f in cands:
            dt = pd.to_datetime(f["date"], utc=True).tz_localize(None)
            gap = abs((dt - kick).days)
            if best is None or gap < best_gap:
                best, best_gap = f, gap
        if best is None or best_gap > 3:
            return None
        return best

    # Chronological list of finished XIs per club.
    appearances = []
    for rec in blob.values():
        season = int(rec.get("season") or 0)
        matchday = int(rec.get("matchday") or 0)
        appearances.append({
            "season": season,
            "matchday": matchday,
            "match_id": None,
            "kick": None,
            "home_key": rec["home_key"],
            "away_key": rec["away_key"],
            "home_xi": rec.get("home_xi") or [],
            "away_xi": rec.get("away_xi") or [],
            "home_bench": rec.get("home_bench") or [],
            "away_bench": rec.get("away_bench") or [],
            "home_score": None,
            "away_score": None,
        })

    # Index FD matches and attach the most recent finished XI for each club before kickoff.
    fd = fd.copy()
    fd["date"] = pd.to_datetime(fd["date"])
    fd = fd.sort_values("date").reset_index(drop=True)

    last_xi = {}  # team_key -> {xi, bench, kick, points, gd}
    player_stats = defaultdict(list)  # player_id -> [(points, gd), ...]
    rows = []

    # Also walk TM appearances in date order to seed last_xi when FD date matches.
    tm_by_keys = defaultdict(list)
    for app in appearances:
        tm_by_keys[(app["season"], app["home_key"], app["away_key"])].append(app)
    for key in tm_by_keys:
        tm_by_keys[key].sort(key=lambda a: int(a.get("matchday") or 0))

    for r in fd.itertuples(index=False):
        season = int(r.season)
        home_key, away_key = r.home_key, r.away_key
        kick = pd.Timestamp(r.date)

        home_prev = last_xi.get(home_key)
        away_prev = last_xi.get(away_key)
        # Drop stale XIs (e.g. missing seasons in the TM backfill).
        if home_prev and home_prev.get("kick") and (kick - home_prev["kick"]).days > 45:
            home_prev = None
        if away_prev and away_prev.get("kick") and (kick - away_prev["kick"]).days > 45:
            away_prev = None

        home_pack = _xi_value_by_pos(home_prev["xi"]) if home_prev else None
        away_pack = _xi_value_by_pos(away_prev["xi"]) if away_prev else None
        home_ppg, home_pgd = _player_strength(home_pack["ids"], player_stats) if home_pack else (1.0, 0.0)
        away_ppg, away_pgd = _player_strength(away_pack["ids"], player_stats) if away_pack else (1.0, 0.0)

        home_cont = 0
        away_cont = 0
        if home_prev:
            home_cont = len(set(home_prev.get("xi_ids") or []) & set(home_prev.get("prev_ids") or []))
        if away_prev:
            away_cont = len(set(away_prev.get("xi_ids") or []) & set(away_prev.get("prev_ids") or []))

        row = {
            "season": season,
            "date": kick.isoformat(),
            "home_team": r.home_team,
            "away_team": r.away_team,
            "home_key": home_key,
            "away_key": away_key,
            "home_goals": int(r.home_goals) if pd.notna(r.home_goals) else None,
            "away_goals": int(r.away_goals) if pd.notna(r.away_goals) else None,
            "outcome": r.outcome,
            "odds_h": float(r.odds_h) if pd.notna(r.odds_h) else None,
            "odds_d": float(r.odds_d) if pd.notna(r.odds_d) else None,
            "odds_a": float(r.odds_a) if pd.notna(r.odds_a) else None,
            "home_shots": float(r.home_shots) if pd.notna(r.home_shots) else None,
            "away_shots": float(r.away_shots) if pd.notna(r.away_shots) else None,
            "home_sot": float(r.home_sot) if pd.notna(r.home_sot) else None,
            "away_sot": float(r.away_sot) if pd.notna(r.away_sot) else None,
            "has_xi": int(bool(home_prev and away_prev)),
            "home_value": home_pack["total"] / 1e6 if home_pack else 0.0,
            "away_value": away_pack["total"] / 1e6 if away_pack else 0.0,
            "home_gk_value": home_pack["G"] / 1e6 if home_pack else 0.0,
            "away_gk_value": away_pack["G"] / 1e6 if away_pack else 0.0,
            "home_def_value": home_pack["D"] / 1e6 if home_pack else 0.0,
            "away_def_value": away_pack["D"] / 1e6 if away_pack else 0.0,
            "home_mid_value": home_pack["M"] / 1e6 if home_pack else 0.0,
            "away_mid_value": away_pack["M"] / 1e6 if away_pack else 0.0,
            "home_fwd_value": home_pack["F"] / 1e6 if home_pack else 0.0,
            "away_fwd_value": away_pack["F"] / 1e6 if away_pack else 0.0,
            "home_age": float(np.mean(home_pack["age"])) if home_pack and home_pack["age"] else 26.0,
            "away_age": float(np.mean(away_pack["age"])) if away_pack and away_pack["age"] else 26.0,
            "home_continuity": home_cont,
            "away_continuity": away_cont,
            "home_player_ppg": home_ppg,
            "away_player_ppg": away_ppg,
            "home_player_gd": home_pgd,
            "away_player_gd": away_pgd,
            "home_xi": ", ".join(home_pack["names"]) if home_pack else "",
            "away_xi": ", ".join(away_pack["names"]) if away_pack else "",
            "home_xi_ids": list(home_pack["ids"]) if home_pack else [],
            "away_xi_ids": list(away_pack["ids"]) if away_pack else [],
            "home_rest_raw": int((kick - home_prev["kick"]).days) if home_prev and home_prev.get("kick") else None,
            "away_rest_raw": int((kick - away_prev["kick"]).days) if away_prev and away_prev.get("kick") else None,
            "home_shots_post": float(r.home_shots) if pd.notna(r.home_shots) else None,
            "away_shots_post": float(r.away_shots) if pd.notna(r.away_shots) else None,
            "home_sot_post": float(r.home_sot) if pd.notna(r.home_sot) else None,
            "away_sot_post": float(r.away_sot) if pd.notna(r.away_sot) else None,
        }

        # Matchday from OpenLiga — nearest fixture by date (pairs meet twice).
        ol = _nearest_ol(season, home_key, away_key, kick)
        row["matchday"] = int(ol["matchday"]) if ol else None
        row["match_id"] = ol.get("match_id") if ol else None
        rows.append(row)

        # Update last XI from TM record for this fixture (actual starters).
        tm = None
        for orient in ((home_key, away_key), (away_key, home_key)):
            queue = tm_by_keys.get((season, orient[0], orient[1]))
            if queue:
                tm = queue.pop(0)
                break
        hg = int(r.home_goals) if pd.notna(r.home_goals) else None
        ag = int(r.away_goals) if pd.notna(r.away_goals) else None
        if hg is None or ag is None:
            continue
        h_pts = 3 if hg > ag else (1 if hg == ag else 0)
        a_pts = 3 if ag > hg else (1 if ag == hg else 0)
        h_gd, a_gd = hg - ag, ag - hg

        def _update(team_key: str, xi: list[dict], pts: int, gd: int):
            prev = last_xi.get(team_key)
            ids = {int(p["id"]) for p in xi}
            last_xi[team_key] = {
                "xi": xi,
                "kick": kick,
                "points": pts,
                "gd": gd,
                "xi_ids": ids,
                "prev_ids": set(prev["xi_ids"]) if prev else set(),
            }
            for pid in ids:
                player_stats[pid].append((pts, gd))

        if tm and tm["home_key"] == home_key:
            _update(home_key, tm["home_xi"], h_pts, h_gd)
            _update(away_key, tm["away_xi"], a_pts, a_gd)
        elif tm and tm["home_key"] == away_key:
            _update(away_key, tm["home_xi"], a_pts, a_gd)
            _update(home_key, tm["away_xi"], h_pts, h_gd)

    return pd.DataFrame(rows)


def _add_team_form(df: pd.DataFrame) -> pd.DataFrame:
    elo = defaultdict(lambda: 1500.0)
    form = defaultdict(list)  # (pts, gd, shots, sot)
    last_date = {}
    h2h = defaultdict(list)

    out_rows = []
    for r in df.itertuples(index=False):
        home, away = r.home_key, r.away_key
        kick = pd.to_datetime(r.date)

        def side_feats(team: str):
            hist = form[team]
            last5 = hist[-5:] if hist else []
            return {
                "elo": elo[team],
                "form5": float(np.mean([x[0] for x in last5])) if last5 else 1.0,
                "gd5": float(np.mean([x[1] for x in last5])) if last5 else 0.0,
                "shots5": float(np.mean([x[2] for x in last5 if x[2] is not None])) if any(x[2] is not None for x in last5) else 10.0,
                "sot5": float(np.mean([x[3] for x in last5 if x[3] is not None])) if any(x[3] is not None for x in last5) else 3.5,
                "rest": min((kick - last_date[team]).days, 90) if team in last_date else 7,
            }

        hf, af = side_feats(home), side_feats(away)
        pair = tuple(sorted((home, away)))
        h2h_hist = h2h[pair]
        n = len(h2h_hist)
        if n:
            # Each entry: (home_key_that_match, gd_from_that_home, winner_key_or_"draw")
            h2h_home_wins = 0
            h2h_draws = 0
            gd_from_current_home = []
            for prev_home, gd, w in h2h_hist:
                if w == "draw":
                    h2h_draws += 1
                elif w == home:
                    h2h_home_wins += 1
                gd_from_current_home.append(gd if prev_home == home else -gd)
            h2h_wr = h2h_home_wins / n
            h2h_dr = h2h_draws / n
            h2h_gd = float(np.mean(gd_from_current_home))
        else:
            h2h_wr, h2h_dr, h2h_gd = 0.5, 0.25, 0.0

        rest_h = hf["rest"] if pd.isna(getattr(r, "home_rest_raw", np.nan)) else int(r.home_rest_raw)
        rest_a = af["rest"] if pd.isna(getattr(r, "away_rest_raw", np.nan)) else int(r.away_rest_raw)

        out_rows.append({
            "home_elo": hf["elo"],
            "away_elo": af["elo"],
            "elo_diff": hf["elo"] + HOME_ADV - af["elo"],
            "home_form5": hf["form5"],
            "away_form5": af["form5"],
            "form5_diff": hf["form5"] - af["form5"],
            "home_gd5": hf["gd5"],
            "away_gd5": af["gd5"],
            "home_shots5": hf["shots5"],
            "away_shots5": af["shots5"],
            "home_sot5": hf["sot5"],
            "away_sot5": af["sot5"],
            "home_rest": rest_h,
            "away_rest": rest_a,
            "h2h_n": n,
            "h2h_home_winrate": h2h_wr,
            "h2h_draw_rate": h2h_dr,
            "h2h_gd": h2h_gd,
            "value_diff": float(r.home_value) - float(r.away_value),
        })

        if pd.isna(r.home_goals) or pd.isna(r.away_goals):
            continue
        hg, ag = int(r.home_goals), int(r.away_goals)
        gd = hg - ag
        exp = 1 / (1 + 10 ** ((af["elo"] - hf["elo"] - HOME_ADV) / 400))
        s = 1.0 if gd > 0 else (0.0 if gd < 0 else 0.5)
        delta = IMPORTANCE * _elo_margin(gd) * (s - exp)
        elo[home] += delta
        elo[away] -= delta
        h_pts = 3 if gd > 0 else (1 if gd == 0 else 0)
        a_pts = 3 if gd < 0 else (1 if gd == 0 else 0)
        form[home].append((h_pts, gd, r.home_shots_post, r.home_sot_post))
        form[away].append((a_pts, -gd, r.away_shots_post, r.away_sot_post))
        last_date[home] = last_date[away] = kick
        winner = home if gd > 0 else (away if gd < 0 else "draw")
        h2h[pair].append((home, gd, winner))

    return df.join(pd.DataFrame(out_rows, index=df.index))


def build_matches(seasons: list[int] | None = None, sync: bool = True) -> pd.DataFrame:
    now = pd.Timestamp.now()
    end = now.year if now.month >= 7 else now.year - 1
    seasons = seasons or list(range(2019, end + 1))

    if sync:
        backfill_lineups(seasons[0], seasons[-1])
        build_tables(seasons=seasons[-2:] if len(seasons) >= 2 else seasons)

    blob = load_lineups()
    if sync or os.getenv("REFRESH_VALUES") == "1":
        refreshed = 0
        for key, rec in list(blob.items()):
            xi = rec.get("home_xi") or []
            if xi and all((p.get("value_eur") or 0) == 0 for p in xi[:3]):
                from xi_table import _tm_html, parse_aufstellung
                try:
                    parsed = parse_aufstellung(_tm_html(int(rec["season"]), int(rec["matchday"]), int(key)))
                except Exception:
                    continue
                if parsed and parsed.get("home_xi"):
                    parsed["tm_id"] = int(key)
                    parsed["season"] = rec.get("season")
                    parsed["matchday"] = rec.get("matchday")
                    blob[key] = parsed
                    refreshed += 1
        if refreshed:
            save_lineups(blob)
            print(f"Refreshed market values on {refreshed} lineup pages")

    fd = fetch_fd_seasons(seasons)
    openliga = []
    for season in seasons:
        try:
            openliga.extend(fetch_openliga_season(season))
        except Exception as exc:
            print(f"OpenLiga {season}: {exc}")

    joined = _join_lineups(fd, blob, openliga)
    full = _add_team_form(joined)

    drop = [
        c for c in full.columns
        if c.endswith("_raw") or c.endswith("_ids") or c.endswith("_post")
    ]
    out = full.drop(columns=[c for c in drop if c in full.columns], errors="ignore")

    # Prefer rows with both previous XIs for training; keep all for odds benchmark.
    DATA.mkdir(parents=True, exist_ok=True)
    out.to_csv(MATCHES_PATH, index=False)
    with_xi = int(out["has_xi"].sum()) if "has_xi" in out.columns else 0
    print(f"Wrote {MATCHES_PATH.name}: {len(out)} matches ({with_xi} with both previous XIs)")
    return out


def feature_frame(df: pd.DataFrame, for_model: bool = True) -> pd.DataFrame:
    cols = MODEL_FEATURES if for_model else MODEL_FEATURES + BENCHMARK_FEATURES
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing columns: {missing}")
    out = df[cols].copy()
    for col in TEXT_FEATURES:
        out[col] = out[col].fillna("").astype("string")
    for col in out.columns:
        if col not in TEXT_FEATURES:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def trainable(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "has_xi" in out.columns:
        out = out[out["has_xi"] == 1]
    out = out[out["outcome"].notna()]
    out = out[out["home_xi"].fillna("").astype(str).str.len().gt(0)]
    out = out[out["away_xi"].fillna("").astype(str).str.len().gt(0)]
    return out.reset_index(drop=True)


if __name__ == "__main__":
    import sys
    sync = "nosync" not in sys.argv
    start = 2019
    for arg in sys.argv[1:]:
        if arg.isdigit():
            start = int(arg)
            break
    now = pd.Timestamp.now()
    end = now.year if now.month >= 7 else now.year - 1
    build_matches(list(range(start, end + 1)), sync=sync)
