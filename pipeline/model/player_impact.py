"""Estimate individual player impact on team win probability."""

from __future__ import annotations

import json
from collections import defaultdict

import joblib
import numpy as np
import pandas as pd

from pipeline.paths import ARTIFACTS, MODELS, PROCESSED, RAW
from pipeline.team_map import DISPLAY_NAMES


def _player_team_history(df: pd.DataFrame) -> pd.DataFrame:
    """Build player–team goal history from OpenLiga goal events embedded in features build source.
    We re-read OpenLiga raw JSON for richer player lists.
    """
    import json as _json
    from pathlib import Path

    rows = []
    for path in sorted(RAW.glob("ol_matches_*.json")):
        season_year = int(path.stem.split("_")[-1])
        matches = _json.loads(path.read_text(encoding="utf-8"))
        for m in matches:
            if not m.get("matchIsFinished"):
                continue
            from pipeline.team_map import slug_from_ol

            h = slug_from_ol(m["team1"])
            a = slug_from_ol(m["team2"])
            if not h or not a:
                continue
            kickoff = pd.to_datetime(m.get("matchDateTimeUTC") or m.get("matchDateTime"))
            for g in m.get("goals") or []:
                if g.get("isOwnGoal"):
                    continue
                pid = g.get("goalGetterID")
                if pid is None:
                    continue
                sid = g.get("scoringTeamId")
                slug = h if sid == m["team1"]["teamId"] else a if sid == m["team2"]["teamId"] else None
                if not slug:
                    continue
                rows.append(
                    {
                        "player_id": int(pid),
                        "player_name": g.get("goalGetterName"),
                        "team_slug": slug,
                        "season_year": season_year,
                        "kickoff": kickoff,
                        "goals": 1,
                        "penalty": bool(g.get("isPenalty")),
                    }
                )
    return pd.DataFrame(rows)


def build_player_index(df_goals: pd.DataFrame | None = None) -> list[dict]:
    if df_goals is None:
        df_goals = _player_team_history(pd.DataFrame())
    if df_goals.empty:
        return []
    # latest team association = most recent goals
    df_goals = df_goals.sort_values("kickoff")
    latest = df_goals.groupby("player_id").tail(1)[["player_id", "player_name", "team_slug"]]
    stats = (
        df_goals.groupby("player_id")
        .agg(goals=("goals", "sum"), matches_scored=("kickoff", "nunique"), last_goal=("kickoff", "max"))
        .reset_index()
    )
    # rolling last 120d goals relative to "now" = max kickoff
    now = df_goals["kickoff"].max()
    recent = df_goals[df_goals["kickoff"] >= now - pd.Timedelta(days=120)]
    recent_goals = recent.groupby("player_id")["goals"].sum().rename("goals_120d")
    out = latest.merge(stats, on="player_id").merge(recent_goals, on="player_id", how="left")
    out["goals_120d"] = out["goals_120d"].fillna(0).astype(int)
    out["team_name"] = out["team_slug"].map(DISPLAY_NAMES)
    records = out.sort_values(["goals_120d", "goals"], ascending=False).to_dict(orient="records")
    for r in records:
        r["last_goal"] = str(r["last_goal"])
        r["player_id"] = int(r["player_id"])
        r["goals"] = int(r["goals"])
        r["matches_scored"] = int(r["matches_scored"])
        r["goals_120d"] = int(r["goals_120d"])
    (ARTIFACTS / "players.json").write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    return records


def estimate_impacts(df: pd.DataFrame | None = None) -> dict:
    """For each upcoming match and notable player, estimate ΔP(win) if player unavailable.

    Method: reduce the team's `squad_goals_*` / top_scorer / depth features by the
    player's recent goal contribution, re-predict, and diff probabilities.
    """
    if df is None:
        df = pd.read_csv(PROCESSED / "features.csv", parse_dates=["kickoff"])
    bundle = joblib.load(MODELS / "lgbm_1x2.joblib")
    model = bundle["model"]
    cols = bundle["features"]
    abl = ARTIFACTS / "ablation.json"
    if abl.exists():
        sel = json.loads(abl.read_text(encoding="utf-8")).get("selected_features")
        if sel:
            cols = [c for c in sel if c in df.columns]

    goals = _player_team_history(df)
    players = build_player_index(goals)
    upcoming = df[df["y"].isna()].copy()
    if upcoming.empty:
        upcoming = df[~df["finished"].fillna(False)].copy()

    # map player recent goals
    now = goals["kickoff"].max() if len(goals) else pd.Timestamp.utcnow()
    recent = goals[goals["kickoff"] >= now - pd.Timedelta(days=120)] if len(goals) else goals
    player_recent = recent.groupby(["player_id", "team_slug"])["goals"].sum().to_dict() if len(recent) else {}

    impacts = []
    # Limit to current matchday slate for bundle size
    if upcoming["matchday"].notna().any():
        md = upcoming.loc[upcoming["season_year"] == upcoming["season_year"].max(), "matchday"].min()
        slate = upcoming[upcoming["matchday"] == md]
    else:
        slate = upcoming.head(9)

    for _, match in slate.iterrows():
        base_x = match[cols].to_frame().T.astype(float)
        base_raw = model.predict_proba(base_x)[0]
        ordered = np.zeros(3)
        for j, c in enumerate(model.classes_):
            ordered[int(c)] = base_raw[j]
        # Market blend weight: player shocks only move the model share (1-w)
        w = float(bundle.get("blend_weight", 0.6))
        book = np.array(
            [
                float(match["imp_home"]) if pd.notna(match.get("imp_home")) else ordered[0],
                float(match["imp_draw"]) if pd.notna(match.get("imp_draw")) else ordered[1],
                float(match["imp_away"]) if pd.notna(match.get("imp_away")) else ordered[2],
            ],
            dtype=float,
        )
        book = book / book.sum()
        base_p = (1 - w) * ordered + w * book
        base_p = base_p / base_p.sum()

        for side, slug, win_idx, squad_col, top_col, depth_col in [
            ("home", match["home_slug"], 0, "squad_goals_home_5", "top_scorer_goals_home", "scorer_depth_home"),
            ("away", match["away_slug"], 2, "squad_goals_away_5", "top_scorer_goals_away", "scorer_depth_away"),
        ]:
            team_players = [p for p in players if p["team_slug"] == slug and p["goals_120d"] > 0][:8]
            for p in team_players:
                key = (p["player_id"], slug)
                contrib = float(player_recent.get(key, p["goals_120d"]))
                if contrib <= 0:
                    continue
                x = base_x.copy().astype(float)
                # Dampen: remove at most 35% of the team squad-goal feature so
                # counterfactuals stay in-distribution for the tree model.
                squad_val = float(match.get(squad_col) or 0)
                damp = min(contrib, max(0.5, 0.35 * squad_val)) if squad_val else min(contrib, 2.0)
                for c, delta in [
                    (squad_col, damp),
                    (top_col, min(damp, float(match.get(top_col) or 0))),
                ]:
                    if c in x.columns and pd.notna(x.iloc[0][c]):
                        x.loc[:, c] = max(0.0, float(x.iloc[0][c]) - delta)
                if depth_col in x.columns and pd.notna(x.iloc[0][depth_col]):
                    x.loc[:, depth_col] = max(0.0, float(x.iloc[0][depth_col]) - 1)
                if "player_strength_diff" in x.columns and pd.notna(match.get("player_strength_diff")):
                    sign = 1 if side == "home" else -1
                    x.loc[:, "player_strength_diff"] = float(match["player_strength_diff"]) - sign * damp

                new_raw = model.predict_proba(x.astype(float))[0]
                ordered_n = np.zeros(3)
                for j, c in enumerate(model.classes_):
                    ordered_n[int(c)] = new_raw[j]
                without = (1 - w) * ordered_n + w * book
                without = without / without.sum()
                delta_win = float(without[win_idx] - base_p[win_idx])
                impacts.append(
                    {
                        "match_uid": match["match_uid"],
                        "ol_match_id": None if pd.isna(match.get("ol_match_id")) else int(match["ol_match_id"]),
                        "kickoff": str(match["kickoff"]),
                        "team_slug": slug,
                        "team_name": DISPLAY_NAMES.get(slug, slug),
                        "side": side,
                        "player_id": p["player_id"],
                        "player_name": p["player_name"],
                        "goals_120d": p["goals_120d"],
                        "base_p_home": float(base_p[0]),
                        "base_p_draw": float(base_p[1]),
                        "base_p_away": float(base_p[2]),
                        "without_p_home": float(without[0]),
                        "without_p_draw": float(without[1]),
                        "without_p_away": float(without[2]),
                        "delta_team_win": delta_win,
                        "delta_team_win_pp": delta_win * 100,
                        "blend_weight": w,
                    }
                )

    impacts.sort(key=lambda x: abs(x["delta_team_win"]), reverse=True)
    # per-player average abs impact
    by_player: dict[int, list] = defaultdict(list)
    for row in impacts:
        by_player[row["player_id"]].append(row)
    leaderboard = []
    for pid, rows in by_player.items():
        leaderboard.append(
            {
                "player_id": pid,
                "player_name": rows[0]["player_name"],
                "team_slug": rows[0]["team_slug"],
                "team_name": rows[0]["team_name"],
                "goals_120d": rows[0]["goals_120d"],
                "avg_delta_win_pp": float(np.mean([abs(r["delta_team_win_pp"]) for r in rows])),
                "n_matches": len(rows),
            }
        )
    leaderboard.sort(key=lambda x: -x["avg_delta_win_pp"])

    out = {
        "method": (
            "Counterfactual: subtract player's recent goal contribution from pre-match "
            "squad-strength features and re-score the LightGBM 1X2 model."
        ),
        "impacts": impacts,
        "leaderboard": leaderboard[:40],
        "players": players[:80],
    }
    (ARTIFACTS / "player_impact.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


if __name__ == "__main__":
    out = estimate_impacts()
    print("players", len(out["players"]), "impacts", len(out["impacts"]))
    print(out["leaderboard"][:5])
