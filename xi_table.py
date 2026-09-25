"""Explicit Bundesliga XI tables.

Reliable inputs (checked against live sources):
- OpenLigaDB: fixtures, scores, matchdays, clubs. No lineups.
- Transfermarkt match pages: starting XI and bench, after the game.

Each finished team-match becomes one row in ``data/xi_matches.csv``.
``data/xi_players.csv`` is the TabPFN training table: one row per player who
was in the previous game's XI or on that bench, labelled by whether they
started the next game.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LINEUPS_PATH = DATA / "lineups.json"
LAST_SIDES_PATH = DATA / "last_sides.json"
MATCHES_CSV = DATA / "xi_matches.csv"
PLAYERS_CSV = DATA / "xi_players.csv"
CACHE = DATA / "cache" / "tm"
API = "https://api.openligadb.de"
TM = "https://www.transfermarkt.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
POS = {
    "bg_Torwart": "G",
    "bg_Abwehr": "D",
    "bg_Mittelfeld": "M",
    "bg_Sturm": "F",
}
POS_ORDER = {"G": 0, "D": 1, "M": 2, "F": 3}
# Longer needles first so "union" does not steal another club.
_CLUB_NEEDLES = (
    ("monchengladbach", "gladbach"),
    ("gladbach", "gladbach"),
    ("leverkusen", "leverkusen"),
    ("heidenheim", "heidenheim"),
    ("hoffenheim", "hoffenheim"),
    ("frankfurt", "frankfurt"),
    ("stuttgart", "stuttgart"),
    ("wolfsburg", "wolfsburg"),
    ("dortmund", "dortmund"),
    ("augsburg", "augsburg"),
    ("freiburg", "freiburg"),
    ("leipzig", "leipzig"),
    ("bremen", "bremen"),
    ("hamburg", "hsv"),
    ("bayern", "bayern"),
    ("munich", "bayern"),
    ("munchen", "bayern"),
    ("stpauli", "stpauli"),
    ("pauli", "stpauli"),
    ("union", "union"),
    ("mainz", "mainz"),
    ("koeln", "koln"),
    ("koln", "koln"),
    ("cologne", "koln"),
    ("bochum", "bochum"),
    ("darmstadt", "darmstadt"),
    ("holstein", "kiel"),
    ("kiel", "kiel"),
)


def club_key(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().replace("ß", "ss")
    n = re.sub(r"[^a-z0-9]+", "", n)
    for needle, key in _CLUB_NEEDLES:
        if needle in n:
            return key
    return n


def _get(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_openliga_season(season: int) -> list[dict]:
    raw = json.loads(_get(f"{API}/getmatchdata/bl1/{season}").decode())
    rows = []
    for m in raw:
        results = m.get("matchResults") or []
        end = next((r for r in results if r.get("resultTypeID") == 2), None)
        if end is None and results:
            end = max(results, key=lambda r: r.get("resultOrderID", 0))
        hs = end.get("pointsTeam1") if end else None
        aws = end.get("pointsTeam2") if end else None
        rows.append({
            "match_id": m.get("matchID"),
            "date": m.get("matchDateTimeUTC") or m.get("matchDateTime"),
            "season": int(m.get("leagueSeason") or season),
            "matchday": int((m.get("group") or {}).get("groupOrderID") or 0),
            "matchday_name": (m.get("group") or {}).get("groupName"),
            "home_team": m["team1"]["teamName"],
            "away_team": m["team2"]["teamName"],
            "home_short": m["team1"].get("shortName") or m["team1"]["teamName"],
            "away_short": m["team2"].get("shortName") or m["team2"]["teamName"],
            "home_icon": m["team1"].get("teamIconUrl"),
            "away_icon": m["team2"].get("teamIconUrl"),
            "home_key": club_key(m["team1"]["teamName"]),
            "away_key": club_key(m["team2"]["teamName"]),
            "home_score": hs,
            "away_score": aws,
            "finished": bool(m.get("matchIsFinished")),
        })
    return rows


def _tm_html(season: int, matchday: int, spielbericht: int | None = None) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    if spielbericht is None:
        path = CACHE / f"md-{season}-{matchday}.html"
        url = f"{TM}/bundesliga/spieltag/wettbewerb/L1/saison_id/{season}/spieltag/{matchday}"
    else:
        path = CACHE / f"xi-{spielbericht}.html"
        url = f"{TM}/spielbericht/aufstellung/spielbericht/{spielbericht}"
    if path.is_file() and path.stat().st_size > 1000:
        return path.read_text(encoding="utf-8", errors="replace")
    time.sleep(0.35)
    html = _get(url).decode("utf-8", "replace")
    path.write_text(html, encoding="utf-8")
    return html


def spielbericht_ids(season: int, matchday: int) -> list[int]:
    html = _tm_html(season, matchday)
    ids = []
    for raw in re.findall(r"/spielbericht/index/spielbericht/(\d+)", html):
        num = int(raw)
        if num not in ids:
            ids.append(num)
    return ids


def _players_in(chunk: str) -> list[dict]:
    players = []
    seen = set()
    for pos_cls, number, pid, name in re.findall(
        r'class="zentriert rueckennummer (bg_\w+)"[\s\S]*?'
        r'rn_nummer">\s*(\d+)\s*</div>[\s\S]*?'
        r'/profil/spieler/(\d+)"[\s\S]*?alt="([^"]+)"',
        chunk,
    ):
        if pid in seen:
            continue
        seen.add(pid)
        players.append({
            "id": int(pid),
            "name": name.strip(),
            "number": int(number),
            "pos": POS.get(pos_cls, "M"),
        })
    return players


def _section_chunks(html: str, title: str) -> list[str]:
    parts = re.split(rf"{title}", html, flags=re.I)
    # parts[0] is preamble; each later part runs until the next split
    return parts[1:]


def parse_aufstellung(html: str) -> dict | None:
    starts = _section_chunks(html, "Starting Line-up")
    subs = _section_chunks(html, "Substitutes")
    if len(starts) < 2:
        return None
    home_xi = _players_in(starts[0])[:11]
    away_xi = _players_in(starts[1])[:11]
    if len(home_xi) < 11 or len(away_xi) < 11:
        return None
    home_name = ""
    away_name = ""
    titles = re.findall(r'<a title="([^"]+)" href="/[^"]+/startseite/verein/', html)
    if len(titles) >= 2:
        home_name, away_name = titles[0], titles[1]
    return {
        "home_name": home_name,
        "away_name": away_name,
        "home_key": club_key(home_name),
        "away_key": club_key(away_name),
        "home_xi": home_xi,
        "away_xi": away_xi,
        "home_bench": _players_in(subs[0]) if subs else [],
        "away_bench": _players_in(subs[1]) if len(subs) > 1 else [],
    }


def load_lineups() -> dict:
    if not LINEUPS_PATH.is_file():
        return {}
    return json.loads(LINEUPS_PATH.read_text(encoding="utf-8"))


def save_lineups(blob: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    LINEUPS_PATH.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_lineups(seasons: list[int]) -> tuple[dict, int]:
    """Fetch Transfermarkt XIs for finished OpenLiga matchdays. Returns (blob, added)."""
    blob = load_lineups()
    added = 0
    for season in seasons:
        fixtures = fetch_openliga_season(season)
        finished_mds = sorted({
            f["matchday"] for f in fixtures
            if f["finished"] and f["home_score"] is not None and f["matchday"]
        })
        for md in finished_mds:
            known = [
                v for v in blob.values()
                if int(v.get("season", 0)) == season and int(v.get("matchday", 0)) == md
            ]
            if len(known) >= 9:
                continue
            try:
                ids = spielbericht_ids(season, md)
            except Exception as exc:
                print(f"  TM matchday {season} MD{md} skipped: {exc}")
                continue
            if not ids:
                print(f"  TM matchday {season} MD{md}: no lineups yet")
                continue
            for sid in ids:
                key = str(sid)
                if key in blob and blob[key].get("home_xi"):
                    continue
                try:
                    parsed = parse_aufstellung(_tm_html(season, md, sid))
                except Exception as exc:
                    print(f"  TM {sid} failed: {exc}")
                    continue
                if not parsed or not parsed["home_key"] or parsed["home_key"] == parsed["away_key"]:
                    print(f"  TM {sid}: lineup parse incomplete")
                    continue
                parsed["tm_id"] = sid
                parsed["season"] = season
                parsed["matchday"] = md
                blob[key] = parsed
                added += 1
                save_lineups(blob)
                print(
                    f"  XI {season} MD{md} {parsed['home_name']} vs {parsed['away_name']}"
                )
    if added:
        save_lineups(blob)
    return blob, added


def _order_xi(players: list[dict]) -> list[dict]:
    return sorted(players, key=lambda p: (POS_ORDER.get(p.get("pos"), 9), p.get("number") or 99, p.get("name") or ""))


def _names(players: list[dict], n: int = 11) -> list[str]:
    ordered = _order_xi(players)[:n]
    names = [p["name"] for p in ordered]
    return names + [""] * (n - len(names))


def build_tables(seasons: list[int] | None = None) -> dict:
    """Rebuild the CSVs from cached lineups joined to OpenLigaDB."""
    now = pd.Timestamp.now()
    end = now.year if now.month >= 7 else now.year - 1
    seasons = seasons or [end - 1, end]
    blob, added = sync_lineups(seasons)

    fixtures = []
    for season in seasons:
        try:
            fixtures.extend(fetch_openliga_season(season))
        except Exception as exc:
            print(f"OpenLiga {season} failed: {exc}")
    by_pair = {}
    for f in fixtures:
        by_pair[(f["season"], f["matchday"], frozenset((f["home_key"], f["away_key"])))] = f

    # Team appearances in kickoff order.
    appearances = []
    for rec in blob.values():
        fx = by_pair.get((int(rec["season"]), int(rec["matchday"]), frozenset((rec["home_key"], rec["away_key"]))))
        if fx is None or not fx["finished"] or fx["home_score"] is None:
            continue
        kick = pd.to_datetime(fx["date"], utc=True).tz_localize(None)
        for side, opp_side in (("home", "away"), ("away", "home")):
            gf = fx[f"{side}_score"]
            ga = fx[f"{opp_side}_score"]
            points = 3 if gf > ga else (1 if gf == ga else 0)
            appearances.append({
                "kick": kick,
                "season": fx["season"],
                "matchday": fx["matchday"],
                "matchday_name": fx["matchday_name"],
                "match_id": fx["match_id"],
                "date": kick.isoformat(),
                "team": fx[f"{side}_team"],
                "team_short": fx[f"{side}_short"],
                "team_icon": fx[f"{side}_icon"],
                "team_key": fx[f"{side}_key"],
                "opponent": fx[f"{opp_side}_team"],
                "opponent_short": fx[f"{opp_side}_short"],
                "is_home": int(side == "home"),
                "gf": int(gf),
                "ga": int(ga),
                "points": points,
                "gd": int(gf) - int(ga),
                "xi": rec[f"{side}_xi"],
                "bench": rec[f"{side}_bench"],
            })
    appearances.sort(key=lambda r: (r["kick"], r["match_id"], r["is_home"]))

    last = {}
    match_rows = []
    player_rows = []
    for app in appearances:
        prev = last.get(app["team_key"])
        xi_names = _names(app["xi"])
        row = {
            "season": app["season"],
            "matchday": app["matchday"],
            "match_id": app["match_id"],
            "date": app["date"],
            "team": app["team"],
            "team_key": app["team_key"],
            "opponent": app["opponent"],
            "is_home": app["is_home"],
            "points": app["points"],
            "gd": app["gd"],
            "gf": app["gf"],
            "ga": app["ga"],
            "rest_days": None,
            "last_points": None,
            "last_gd": None,
            "last_opponent": None,
            "last_date": None,
        }
        for i, name in enumerate(xi_names, start=1):
            row[f"xi_{i}"] = name
        if prev is not None:
            rest = (app["kick"] - prev["kick"]).days
            row["rest_days"] = int(rest)
            row["last_points"] = prev["points"]
            row["last_gd"] = prev["gd"]
            row["last_opponent"] = prev["opponent"]
            row["last_date"] = prev["date"]
            for i, name in enumerate(_names(prev["xi"]), start=1):
                row[f"last_{i}"] = name
            prev_ids = {p["id"] for p in prev["xi"]}
            bench_ids = {p["id"] for p in prev["bench"]}
            seen_ids: set[int] = set()
            for p in list(prev["xi"]) + list(prev["bench"]):
                if p["id"] in seen_ids:
                    continue
                seen_ids.add(p["id"])
                player_rows.append({
                    "season": app["season"],
                    "matchday": app["matchday"],
                    "match_id": app["match_id"],
                    "date": app["date"],
                    "team": app["team"],
                    "opponent": app["opponent"],
                    "is_home": app["is_home"],
                    "rest_days": int(rest),
                    "last_points": prev["points"],
                    "last_gd": prev["gd"],
                    "player_id": str(p["id"]),
                    "player_name": p["name"],
                    "position": p["pos"],
                    "started_last": int(p["id"] in prev_ids),
                    "on_bench_last": int(p["id"] in bench_ids and p["id"] not in prev_ids),
                    "y_started": int(p["id"] in {x["id"] for x in app["xi"]}),
                })
        else:
            for i in range(1, 12):
                row[f"last_{i}"] = ""
        match_rows.append(row)
        last[app["team_key"]] = app

    DATA.mkdir(parents=True, exist_ok=True)
    sides = {}
    for key, app in last.items():
        sides[key] = {
            "team": app["team"],
            "team_short": app["team_short"],
            "date": app["date"],
            "opponent": app["opponent"],
            "points": app["points"],
            "gd": app["gd"],
            "xi": app["xi"],
            "bench": app["bench"],
        }
    LAST_SIDES_PATH.write_text(json.dumps(sides, ensure_ascii=False, indent=2), encoding="utf-8")
    matches = pd.DataFrame(match_rows)
    players = pd.DataFrame(player_rows)
    # One row per player even if listed twice.
    if len(players):
        players = players.drop_duplicates(["match_id", "team", "player_id"])
    matches.to_csv(MATCHES_CSV, index=False)
    players.to_csv(PLAYERS_CSV, index=False)
    trainable = int(matches["last_1"].ne("").sum()) if "last_1" in matches.columns else 0
    print(
        f"Table: {len(matches)} team-matches ({trainable} with a previous XI), "
        f"{len(players)} player rows, {added} new lineup pages"
    )
    return {
        "added_lineups": added,
        "team_matches": int(len(matches)),
        "player_rows": int(len(players)),
        "matches_path": str(MATCHES_CSV),
        "players_path": str(PLAYERS_CSV),
    }


def latest_side(team_key: str) -> dict | None:
    """Last finished XI + bench for a club, from the lineup store joined later by the model."""
    if not MATCHES_CSV.is_file():
        return None
    df = pd.read_csv(MATCHES_CSV)
    sub = df[df["team_key"] == team_key]
    if sub.empty:
        return None
    return sub.sort_values("date").iloc[-1].to_dict()


def upcoming_fixtures() -> tuple[dict, list[dict]]:
    now = pd.Timestamp.now()
    season = int(now.year if now.month >= 7 else now.year - 1)
    group = json.loads(_get(f"{API}/getcurrentgroup/bl1").decode())
    order = int(group["groupOrderID"])
    nxt = json.loads(_get(f"{API}/getnextmatchbyleagueshortcut/bl1").decode())
    if nxt:
        season = int(nxt.get("leagueSeason") or season)
        order = int((nxt.get("group") or {}).get("groupOrderID") or order)
    matches = json.loads(_get(f"{API}/getmatchdata/bl1/{season}/{order}").decode())
    if matches and all(m.get("matchIsFinished") for m in matches) and order < 34:
        order += 1
        matches = json.loads(_get(f"{API}/getmatchdata/bl1/{season}/{order}").decode())
    fixtures = []
    for m in matches:
        fixtures.append({
            "match_id": m.get("matchID"),
            "date": m.get("matchDateTimeUTC") or m.get("matchDateTime"),
            "home_team": m["team1"]["teamName"],
            "away_team": m["team2"]["teamName"],
            "home_short": m["team1"].get("shortName") or m["team1"]["teamName"],
            "away_short": m["team2"].get("shortName") or m["team2"]["teamName"],
            "home_icon": m["team1"].get("teamIconUrl"),
            "away_icon": m["team2"].get("teamIconUrl"),
            "home_key": club_key(m["team1"]["teamName"]),
            "away_key": club_key(m["team2"]["teamName"]),
            "finished": bool(m.get("matchIsFinished")),
        })
    meta = {
        "season": season,
        "matchday": order,
        "matchday_name": (matches[0].get("group") or {}).get("groupName") if matches else group.get("groupName"),
    }
    return meta, fixtures
