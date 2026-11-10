"""Leakage-safe pre-match features: Elo, form, H2H, rest, odds, rolling shots/xG."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from pipeline.ingest.football_data import load_all_seasons
from pipeline.ingest.openliga import explode_goals, matches_frame, teams_frame
from pipeline.paths import PROCESSED
from pipeline.team_map import DISPLAY_NAMES

FEATURE_GROUPS = {
    "elo": ["elo_home", "elo_away", "elo_diff"],
    "form": [
        "form_pts_home_5", "form_pts_away_5", "form_gd_home_5", "form_gd_away_5",
        "form_pts_home_10", "form_pts_away_10", "home_form_home_5", "away_form_away_5",
    ],
    "rest_h2h": ["rest_days_home", "rest_days_away", "rest_diff", "h2h_home_win_rate", "h2h_games"],
    "shots_xg": [
        "roll_hs_for_5", "roll_as_for_5", "roll_hst_for_5", "roll_ast_for_5",
        "roll_hs_against_5", "roll_as_against_5",
        "roll_hxg_for_5", "roll_axg_for_5", "roll_hxg_against_5", "roll_axg_against_5",
        "shots_for_diff", "xg_for_diff",
    ],
    "odds": ["odds_home", "odds_draw", "odds_away", "imp_home", "imp_draw", "imp_away"],
    "table": [
        "rank_home", "rank_away", "pts_home", "pts_away", "gd_home", "gd_away",
        "rank_diff", "pts_diff",
    ],
    "players": [
        "squad_goals_home_5", "squad_goals_away_5", "top_scorer_goals_home",
        "top_scorer_goals_away", "scorer_depth_home", "scorer_depth_away",
        "player_strength_diff",
    ],
}


def _implied(odds: float) -> float:
    if odds is None or np.isnan(odds) or odds <= 1.0:
        return np.nan
    return 1.0 / odds


def _normalize_implied(h, d, a):
    vals = np.array([h, d, a], dtype=float)
    if np.any(np.isnan(vals)):
        return vals
    s = vals.sum()
    return vals / s if s > 0 else vals


def merge_sources() -> pd.DataFrame:
    fd = load_all_seasons()
    ol = matches_frame()

    # Prefer football-data rows for historical finished matches (odds + stats).
    # Attach OpenLiga IDs / icons / upcoming fixtures via fuzzy date+teams join.
    fd = fd.copy()
    fd["source"] = "football_data"
    keep_cols = [
        "match_uid", "season_code", "season_label", "season_year", "kickoff",
        "home_slug", "away_slug", "HomeTeam", "AwayTeam",
        "FTHG", "FTAG", "FTR", "HS", "AS", "HST", "AST",
        "B365H", "B365D", "B365A", "AvgH", "AvgD", "AvgA", "PSH", "PSD", "PSA",
        "MaxH", "MaxD", "MaxA",
    ]
    # optional xG columns (present in newer seasons)
    for c in ("HxG", "AxG"):
        if c in fd.columns:
            keep_cols.append(c)
    fd = fd[[c for c in keep_cols if c in fd.columns]]

    ol_key = ol.copy()
    ol_key["kickoff_day"] = (
        pd.to_datetime(ol_key["kickoff"], utc=True).dt.tz_convert(None).dt.normalize()
    )
    fd["kickoff_day"] = (
        pd.to_datetime(fd["kickoff"], utc=True).dt.tz_convert(None).dt.normalize()
    )

    merged = fd.merge(
        ol_key[
            [
                "ol_match_id", "matchday", "kickoff_day", "home_slug", "away_slug",
                "home_name", "away_name", "home_team_id", "away_team_id",
                "home_icon", "away_icon", "finished", "goal_events",
            ]
        ],
        on=["kickoff_day", "home_slug", "away_slug"],
        how="left",
        suffixes=("", "_ol"),
    )

    # Upcoming / missing from FD: append OpenLiga unfinished (or unmatched) matches
    matched_ids = set(merged["ol_match_id"].dropna().astype(int))
    upcoming = ol[~ol["ol_match_id"].isin(matched_ids)].copy()
    if len(upcoming):
        extra = pd.DataFrame(
            {
                "match_uid": "ol_" + upcoming["ol_match_id"].astype(str),
                "season_code": upcoming["season_year"].map(
                    {v["openliga"]: k for k, v in __import__("pipeline.paths", fromlist=["SEASONS"]).SEASONS.items()}
                ),
                "season_label": upcoming["season_year"].map(
                    {v["openliga"]: v["label"] for v in __import__("pipeline.paths", fromlist=["SEASONS"]).SEASONS.values()}
                ),
                "season_year": upcoming["season_year"],
                "kickoff": upcoming["kickoff"],
                "home_slug": upcoming["home_slug"],
                "away_slug": upcoming["away_slug"],
                "HomeTeam": upcoming["home_name"],
                "AwayTeam": upcoming["away_name"],
                "FTHG": upcoming["home_goals"],
                "FTAG": upcoming["away_goals"],
                "FTR": upcoming["result"],
                "ol_match_id": upcoming["ol_match_id"],
                "matchday": upcoming["matchday"],
                "home_name": upcoming["home_name"],
                "away_name": upcoming["away_name"],
                "home_team_id": upcoming["home_team_id"],
                "away_team_id": upcoming["away_team_id"],
                "home_icon": upcoming["home_icon"],
                "away_icon": upcoming["away_icon"],
                "finished": upcoming["finished"],
                "goal_events": upcoming["goal_events"],
                "source": "openliga",
            }
        )
        merged = pd.concat([merged, extra], ignore_index=True)

    merged["kickoff"] = pd.to_datetime(merged["kickoff"], utc=True).dt.tz_convert(None)
    merged = merged.sort_values("kickoff").reset_index(drop=True)
    merged["home_name"] = merged["home_name"].fillna(merged["home_slug"].map(DISPLAY_NAMES))
    merged["away_name"] = merged["away_name"].fillna(merged["away_slug"].map(DISPLAY_NAMES))
    finished_mask = merged["FTR"].notna()
    merged["finished"] = merged.get("finished", finished_mask).fillna(finished_mask).astype(bool)
    return merged


def compute_elo_and_form(df: pd.DataFrame, k: float = 20.0, home_adv: float = 60.0) -> pd.DataFrame:
    """Walk chronologically; store pre-match Elo/form only."""
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    history: dict[str, list[dict]] = defaultdict(list)
    last_played: dict[str, pd.Timestamp] = {}
    table = defaultdict(lambda: {"pts": 0, "gd": 0, "played": 0})

    rows = []
    for _, m in df.iterrows():
        h, a = m["home_slug"], m["away_slug"]
        eh, ea = elo[h], elo[a]
        kickoff = m["kickoff"]

        def form_stats(team: str, n: int, home_only: bool | None = None) -> tuple[float, float]:
            games = history[team]
            if home_only is True:
                games = [g for g in games if g["was_home"]]
            elif home_only is False:
                games = [g for g in games if not g["was_home"]]
            recent = games[-n:]
            if not recent:
                return 0.0, 0.0
            pts = sum(g["pts"] for g in recent) / len(recent)
            gd = sum(g["gd"] for g in recent) / len(recent)
            return pts, gd

        def h2h(home: str, away: str, n: int = 6) -> tuple[float, int]:
            games = [g for g in history[home] if g["opp"] == away][-n:]
            if not games:
                return 0.5, 0
            return sum(1 for g in games if g["pts"] == 3) / len(games), len(games)

        rest_h = (kickoff - last_played[h]).days if h in last_played else 7
        rest_a = (kickoff - last_played[a]).days if a in last_played else 7
        h2h_rate, h2h_n = h2h(h, a)

        # table ranks pre-match
        season = m["season_year"]
        season_teams = {
            t: table[(season, t)] for t in set(list(elo.keys()) + [h, a])
            if table[(season, t)]["played"] > 0 or t in (h, a)
        }
        standings = sorted(
            season_teams.items(),
            key=lambda kv: (kv[1]["pts"], kv[1]["gd"], -kv[1]["played"]),
            reverse=True,
        )
        rank = {t: i + 1 for i, (t, _) in enumerate(standings)}

        fp5h, fg5h = form_stats(h, 5)
        fp5a, fg5a = form_stats(a, 5)
        fp10h, _ = form_stats(h, 10)
        fp10a, _ = form_stats(a, 10)
        hf5, _ = form_stats(h, 5, home_only=True)
        af5, _ = form_stats(a, 5, home_only=False)

        rows.append(
            {
                "match_uid": m["match_uid"],
                "elo_home": eh,
                "elo_away": ea,
                "elo_diff": eh - ea,
                "form_pts_home_5": fp5h,
                "form_pts_away_5": fp5a,
                "form_gd_home_5": fg5h,
                "form_gd_away_5": fg5a,
                "form_pts_home_10": fp10h,
                "form_pts_away_10": fp10a,
                "home_form_home_5": hf5,
                "away_form_away_5": af5,
                "rest_days_home": float(min(rest_h, 21)),
                "rest_days_away": float(min(rest_a, 21)),
                "rest_diff": float(min(rest_h, 21) - min(rest_a, 21)),
                "h2h_home_win_rate": h2h_rate,
                "h2h_games": float(h2h_n),
                "rank_home": float(rank.get(h, 9)),
                "rank_away": float(rank.get(a, 9)),
                "pts_home": float(table[(season, h)]["pts"]),
                "pts_away": float(table[(season, a)]["pts"]),
                "gd_home": float(table[(season, h)]["gd"]),
                "gd_away": float(table[(season, a)]["gd"]),
                "rank_diff": float(rank.get(a, 9) - rank.get(h, 9)),
                "pts_diff": float(table[(season, h)]["pts"] - table[(season, a)]["pts"]),
            }
        )

        # update after match if finished
        if pd.notna(m.get("FTR")):
            hg, ag = int(m["FTHG"]), int(m["FTAG"])
            exp_h = 1.0 / (1.0 + 10 ** (((ea) - (eh + home_adv)) / 400.0))
            if hg > ag:
                score_h, ph, pa = 1.0, 3, 0
            elif hg < ag:
                score_h, ph, pa = 0.0, 0, 3
            else:
                score_h, ph, pa = 0.5, 1, 1
            elo[h] = eh + k * (score_h - exp_h)
            elo[a] = ea + k * ((1.0 - score_h) - (1.0 - exp_h))
            history[h].append({"opp": a, "pts": ph, "gd": hg - ag, "was_home": True})
            history[a].append({"opp": h, "pts": pa, "gd": ag - hg, "was_home": False})
            last_played[h] = kickoff
            last_played[a] = kickoff
            table[(season, h)]["pts"] += ph
            table[(season, a)]["pts"] += pa
            table[(season, h)]["gd"] += hg - ag
            table[(season, a)]["gd"] += ag - hg
            table[(season, h)]["played"] += 1
            table[(season, a)]["played"] += 1

    return pd.DataFrame(rows)


def compute_rolling_shots(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Rolling shot/xG averages using only past matches."""
    # per-team rolling of for/against
    team_hist: dict[str, list[dict]] = defaultdict(list)
    rows = []
    for _, m in df.iterrows():
        h, a = m["home_slug"], m["away_slug"]

        def agg(team: str, key_for: str, key_against: str):
            recent = team_hist[team][-window:]
            if not recent:
                return np.nan, np.nan
            return (
                float(np.nanmean([g[key_for] for g in recent])),
                float(np.nanmean([g[key_against] for g in recent])),
            )

        hs_f, hs_a = agg(h, "shots_for", "shots_against")
        as_f, as_a = agg(a, "shots_for", "shots_against")
        hst_f, _ = agg(h, "sot_for", "sot_against")
        ast_f, _ = agg(a, "sot_for", "sot_against")
        hxg_f, hxg_a = agg(h, "xg_for", "xg_against")
        axg_f, axg_a = agg(a, "xg_for", "xg_against")

        rows.append(
            {
                "match_uid": m["match_uid"],
                "roll_hs_for_5": hs_f,
                "roll_as_for_5": as_f,
                "roll_hst_for_5": hst_f,
                "roll_ast_for_5": ast_f,
                "roll_hs_against_5": hs_a,
                "roll_as_against_5": as_a,
                "roll_hxg_for_5": hxg_f,
                "roll_axg_for_5": axg_f,
                "roll_hxg_against_5": hxg_a,
                "roll_axg_against_5": axg_a,
                "shots_for_diff": (hs_f - as_f) if pd.notna(hs_f) and pd.notna(as_f) else np.nan,
                "xg_for_diff": (hxg_f - axg_f) if pd.notna(hxg_f) and pd.notna(axg_f) else np.nan,
            }
        )

        if pd.notna(m.get("FTR")):
            hs = m.get("HS"); aus = m.get("AS")
            hst = m.get("HST"); ast = m.get("AST")
            hxg = m.get("HxG"); axg = m.get("AxG")
            team_hist[h].append(
                {
                    "shots_for": hs, "shots_against": aus,
                    "sot_for": hst, "sot_against": ast,
                    "xg_for": hxg, "xg_against": axg,
                }
            )
            team_hist[a].append(
                {
                    "shots_for": aus, "shots_against": hs,
                    "sot_for": ast, "sot_against": hst,
                    "xg_for": axg, "xg_against": hxg,
                }
            )
    return pd.DataFrame(rows)


def compute_odds_features(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, m in df.iterrows():
        # Prefer closing Avg, then Pinnacle, then B365
        oh = m.get("AvgH") if pd.notna(m.get("AvgH")) else m.get("PSH") if pd.notna(m.get("PSH")) else m.get("B365H")
        od = m.get("AvgD") if pd.notna(m.get("AvgD")) else m.get("PSD") if pd.notna(m.get("PSD")) else m.get("B365D")
        oa = m.get("AvgA") if pd.notna(m.get("AvgA")) else m.get("PSA") if pd.notna(m.get("PSA")) else m.get("B365A")
        ih, id_, ia = _implied(oh), _implied(od), _implied(oa)
        norm = _normalize_implied(ih, id_, ia)
        rows.append(
            {
                "match_uid": m["match_uid"],
                "odds_home": oh,
                "odds_draw": od,
                "odds_away": oa,
                "imp_home": norm[0],
                "imp_draw": norm[1],
                "imp_away": norm[2],
            }
        )
    return pd.DataFrame(rows)


def compute_player_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling scorer strength from OpenLiga goal events (pre-match only)."""
    # Build chronological goal contributions per player per team
    player_team_goals: dict[tuple[str, int], list[tuple[pd.Timestamp, int]]] = defaultdict(list)
    # We need goal events ordered; rebuild from matches that have them
    rows = []
    # Pre-index goals by match for speed
    for _, m in df.iterrows():
        h, a = m["home_slug"], m["away_slug"]
        kickoff = m["kickoff"]

        def team_strength(slug: str, team_id) -> tuple[float, float, float]:
            # sum of recent non-penalty goals by players associated with team
            # Approximate: players who scored while on this team in past 5 team matches window (~120 days)
            cutoff = kickoff - pd.Timedelta(days=120)
            contrib = []
            for (pslug, pid), events in player_team_goals.items():
                if pslug != slug:
                    continue
                recent = [g for ts, g in events if cutoff <= ts < kickoff]
                if recent:
                    contrib.append(sum(recent))
            if not contrib:
                return 0.0, 0.0, 0.0
            contrib = sorted(contrib, reverse=True)
            return float(sum(contrib)), float(contrib[0]), float(len([c for c in contrib if c > 0]))

        sh, top_h, depth_h = team_strength(h, m.get("home_team_id"))
        sa, top_a, depth_a = team_strength(a, m.get("away_team_id"))
        rows.append(
            {
                "match_uid": m["match_uid"],
                "squad_goals_home_5": sh,
                "squad_goals_away_5": sa,
                "top_scorer_goals_home": top_h,
                "top_scorer_goals_away": top_a,
                "scorer_depth_home": depth_h,
                "scorer_depth_away": depth_a,
                "player_strength_diff": sh - sa,
            }
        )

        # update after match
        for g in (m.get("goal_events") or []):
            if g.get("isOwnGoal"):
                continue
            pid = g.get("goalGetterID")
            if pid is None:
                continue
            goals = 0 if g.get("isPenalty") else 1
            # map scoring team id to slug
            sid = g.get("scoringTeamId")
            slug = h if sid == m.get("home_team_id") else a if sid == m.get("away_team_id") else None
            if slug is None:
                # fallback: if home scored more recent — skip
                continue
            player_team_goals[(slug, int(pid))].append((kickoff, goals if goals else (1 if g.get("isPenalty") else 0)))
            if g.get("isPenalty"):
                # count penalties at half weight already handled; add 1 for availability signal
                player_team_goals[(slug, int(pid))][-1] = (kickoff, 1)

    return pd.DataFrame(rows)


def build_feature_matrix() -> pd.DataFrame:
    base = merge_sources()
    elo = compute_elo_and_form(base)
    shots = compute_rolling_shots(base)
    odds = compute_odds_features(base)
    players = compute_player_features(base)

    feat = base.merge(elo, on="match_uid", how="left")
    feat = feat.merge(shots, on="match_uid", how="left")
    feat = feat.merge(odds, on="match_uid", how="left")
    feat = feat.merge(players, on="match_uid", how="left")

    # target
    feat["y"] = feat["FTR"].map({"H": 0, "D": 1, "A": 2})
    out = PROCESSED / "features.parquet"
    # drop heavy goal_events for parquet
    save = feat.drop(columns=["goal_events"], errors="ignore")
    save.to_parquet(out, index=False)
    save.to_csv(PROCESSED / "features.csv", index=False)
    return feat


def all_feature_columns() -> list[str]:
    cols = []
    for g in FEATURE_GROUPS.values():
        cols.extend(g)
    return cols


if __name__ == "__main__":
    df = build_feature_matrix()
    print(df.shape)
    print(df["season_label"].value_counts())
    print("finished with y", df["y"].notna().sum())
