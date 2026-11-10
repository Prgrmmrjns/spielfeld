"""OpenLigaDB: matches, teams, goals, goal getters for Bundesliga."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

from pipeline.paths import CURRENT_OPENLIGA_SEASON, RAW, SEASONS
from pipeline.team_map import DISPLAY_NAMES, slug_from_ol

BASE = "https://api.openligadb.de"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "spielfeld-bundesliga-forecast/1.0"})


def _get(path: str):
    r = SESSION.get(f"{BASE}{path}", timeout=60)
    r.raise_for_status()
    return r.json()


def download_season_matches(year: int, force: bool = False) -> Path:
    out = RAW / f"ol_matches_{year}.json"
    if out.exists() and not force:
        return out
    data = _get(f"/getmatchdata/bl1/{year}")
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return out


def download_goal_getters(year: int, force: bool = False) -> Path:
    out = RAW / f"ol_goalgetters_{year}.json"
    if out.exists() and not force:
        return out
    data = _get(f"/getgoalgetters/bl1/{year}")
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return out


def download_teams(year: int, force: bool = False) -> Path:
    out = RAW / f"ol_teams_{year}.json"
    if out.exists() and not force:
        return out
    data = _get(f"/getavailableteams/bl1/{year}")
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return out


def _ft_score(match: dict) -> tuple[int | None, int | None]:
    results = match.get("matchResults") or []
    ft = None
    for r in results:
        if r.get("resultTypeID") == 2 or r.get("resultTypeKind") == "After90Minutes":
            ft = r
            break
    if ft is None and results:
        ft = max(results, key=lambda x: x.get("resultOrderID", 0))
    if not ft:
        return None, None
    return ft.get("pointsTeam1"), ft.get("pointsTeam2")


def matches_frame(years: list[int] | None = None) -> pd.DataFrame:
    years = years or sorted({s["openliga"] for s in SEASONS.values()})
    rows = []
    for year in years:
        path = download_season_matches(year)
        matches = json.loads(path.read_text(encoding="utf-8"))
        for m in matches:
            home = slug_from_ol(m["team1"])
            away = slug_from_ol(m["team2"])
            if not home or not away:
                continue
            hg, ag = _ft_score(m)
            finished = bool(m.get("matchIsFinished"))
            kickoff = pd.to_datetime(m.get("matchDateTimeUTC") or m.get("matchDateTime"))
            goals = m.get("goals") or []
            rows.append(
                {
                    "ol_match_id": m["matchID"],
                    "season_year": year,
                    "matchday": (m.get("group") or {}).get("groupOrderID"),
                    "kickoff": kickoff,
                    "home_slug": home,
                    "away_slug": away,
                    "home_name": DISPLAY_NAMES.get(home, m["team1"].get("teamName")),
                    "away_name": DISPLAY_NAMES.get(away, m["team2"].get("teamName")),
                    "home_team_id": m["team1"].get("teamId"),
                    "away_team_id": m["team2"].get("teamId"),
                    "finished": finished,
                    "home_goals": hg if finished else None,
                    "away_goals": ag if finished else None,
                    "result": (
                        "H" if finished and hg is not None and hg > ag else
                        "A" if finished and ag is not None and ag > hg else
                        "D" if finished and hg is not None else None
                    ),
                    "n_goals_events": len(goals),
                    "goal_events": goals,
                    "home_icon": m["team1"].get("teamIconUrl"),
                    "away_icon": m["team2"].get("teamIconUrl"),
                }
            )
    df = pd.DataFrame(rows).sort_values("kickoff").reset_index(drop=True)
    return df


def explode_goals(matches: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, m in matches.iterrows():
        for g in m["goal_events"] or []:
            rows.append(
                {
                    "ol_match_id": m["ol_match_id"],
                    "season_year": m["season_year"],
                    "kickoff": m["kickoff"],
                    "player_id": g.get("goalGetterID"),
                    "player_name": g.get("goalGetterName"),
                    "scoring_team_id": g.get("scoringTeamId"),
                    "is_penalty": bool(g.get("isPenalty")),
                    "is_own_goal": bool(g.get("isOwnGoal")),
                    "minute": g.get("matchMinute"),
                    "home_slug": m["home_slug"],
                    "away_slug": m["away_slug"],
                    "home_team_id": m["home_team_id"],
                    "away_team_id": m["away_team_id"],
                }
            )
    return pd.DataFrame(rows)


def teams_frame(year: int = CURRENT_OPENLIGA_SEASON) -> pd.DataFrame:
    path = download_teams(year)
    teams = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for t in teams:
        slug = slug_from_ol(t)
        if not slug:
            continue
        rows.append(
            {
                "slug": slug,
                "ol_team_id": t["teamId"],
                "name": DISPLAY_NAMES.get(slug, t.get("teamName")),
                "short_name": t.get("shortName"),
                "icon_url": t.get("teamIconUrl"),
            }
        )
    return pd.DataFrame(rows).drop_duplicates("slug")


def goal_getters_frame(years: list[int] | None = None) -> pd.DataFrame:
    years = years or sorted({s["openliga"] for s in SEASONS.values()})
    rows = []
    for year in years:
        path = download_goal_getters(year)
        data = json.loads(path.read_text(encoding="utf-8"))
        for g in data:
            rows.append(
                {
                    "season_year": year,
                    "player_id": g.get("goalGetterId"),
                    "player_name": g.get("goalGetterName"),
                    "goals": g.get("goalCount"),
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    m = matches_frame()
    print(m.shape, m["season_year"].value_counts().sort_index().to_dict())
    print("upcoming", (~m["finished"]).sum())
    print(teams_frame().head())
