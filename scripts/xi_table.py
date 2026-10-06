"""Explicit Bundesliga XI tables.

Reliable inputs (checked against live sources):
- OpenLigaDB: fixtures, scores, matchdays, clubs. No lineups.
- Transfermarkt match pages: starting XI and bench, after the game.

``build_tables`` caches lineups (``datasets/lineups.json``) and writes each club's latest XI
to ``datasets/last_sides.json``.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets"
LINEUPS_PATH = DATA / "lineups.json"
LAST_SIDES_PATH = DATA / "last_sides.json"
CACHE = DATA / "cache" / "tm"
API = "https://api.openligadb.de"
TM = "https://www.transfermarkt.com"
FD = "https://www.football-data.co.uk/mmz4281"
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
    ("mgladbach", "gladbach"),
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
    ("fckoln", "koln"),
    ("bochum", "bochum"),
    ("darmstadt", "darmstadt"),
    ("holstein", "kiel"),
    ("kiel", "kiel"),
    ("elversberg", "elversberg"),
    ("paderborn", "paderborn"),
    ("schalke", "schalke"),
    ("hertha", "hertha"),
    ("dusseldorf", "dusseldorf"),
    ("furth", "furth"),
    ("biefeld", "bielefeld"),
    ("bielefeld", "bielefeld"),
    ("nurnberg", "nurnberg"),
    ("hannover", "hannover"),
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


def _fd_code(season: int) -> str:
    """football-data season folder, e.g. 2019 -> 1920, 2025 -> 2526."""
    return f"{season % 100:02d}{(season + 1) % 100:02d}"


def fetch_fd_season(season: int) -> pd.DataFrame:
    """Bundesliga results + stats + avg odds from football-data.co.uk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"fd-D1-{season}.csv"
    if not path.is_file() or path.stat().st_size < 200:
        url = f"{FD}/{_fd_code(season)}/D1.csv"
        time.sleep(0.2)
        path.write_bytes(_get(url))
    df = pd.read_csv(path)
    if df.empty:
        return df
    rows = []
    for r in df.itertuples(index=False):
        home = getattr(r, "HomeTeam", None)
        away = getattr(r, "AwayTeam", None)
        if not home or not away:
            continue
        ftr = str(getattr(r, "FTR", "") or "")
        outcome = {"H": "home_win", "D": "draw", "A": "away_win"}.get(ftr)
        date_raw = str(getattr(r, "Date", "") or "")
        try:
            date = pd.to_datetime(date_raw, dayfirst=True)
        except Exception:
            date = pd.NaT
        rows.append({
            "season": season,
            "date": date,
            "home_team": home,
            "away_team": away,
            "home_key": club_key(home),
            "away_key": club_key(away),
            "home_goals": pd.to_numeric(getattr(r, "FTHG", None), errors="coerce"),
            "away_goals": pd.to_numeric(getattr(r, "FTAG", None), errors="coerce"),
            "outcome": outcome,
            "home_shots": pd.to_numeric(getattr(r, "HS", None), errors="coerce"),
            "away_shots": pd.to_numeric(getattr(r, "AS", None), errors="coerce"),
            "home_sot": pd.to_numeric(getattr(r, "HST", None), errors="coerce"),
            "away_sot": pd.to_numeric(getattr(r, "AST", None), errors="coerce"),
            "home_corners": pd.to_numeric(getattr(r, "HC", None), errors="coerce"),
            "away_corners": pd.to_numeric(getattr(r, "AC", None), errors="coerce"),
            "odds_h": pd.to_numeric(getattr(r, "AvgH", None), errors="coerce"),
            "odds_d": pd.to_numeric(getattr(r, "AvgD", None), errors="coerce"),
            "odds_a": pd.to_numeric(getattr(r, "AvgA", None), errors="coerce"),
        })
    out = pd.DataFrame(rows)
    out = out.dropna(subset=["date", "outcome"]).sort_values("date").reset_index(drop=True)
    return out


def fetch_fd_seasons(seasons: list[int]) -> pd.DataFrame:
    frames = []
    for season in seasons:
        try:
            frame = fetch_fd_season(season)
        except Exception as exc:
            print(f"  football-data {season} skipped: {exc}")
            continue
        if not frame.empty:
            frames.append(frame)
            print(f"  football-data {season}: {len(frame)} matches")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

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


def _parse_value_eur(raw: str, unit: str) -> float:
    try:
        num = float(raw.replace(",", ""))
    except ValueError:
        return 0.0
    u = (unit or "m").lower()
    if u.startswith("k") or "th" in u:
        return num * 1_000.0
    return num * 1_000_000.0


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
        # Age and market value sit in the same player cell after the link.
        tail = chunk[chunk.find(f'/profil/spieler/{pid}"'): chunk.find(f'/profil/spieler/{pid}"') + 1800]
        age_m = re.search(r"\((\d+)\s*years?\s*old\)", tail)
        val_m = re.search(r"€([0-9.,]+)\s*(m|k|Th\.?)?", tail)
        players.append({
            "id": int(pid),
            "name": name.strip(),
            "number": int(number),
            "pos": POS.get(pos_cls, "M"),
            "age": int(age_m.group(1)) if age_m else None,
            "value_eur": _parse_value_eur(val_m.group(1), val_m.group(2) or "m") if val_m else 0.0,
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
        try:
            fixtures = fetch_openliga_season(season)
        except Exception as exc:
            print(f"  OpenLiga {season} skipped: {exc}")
            fixtures = []
        finished_mds = sorted({
            f["matchday"] for f in fixtures
            if f["finished"] and f["home_score"] is not None and f["matchday"]
        })
        # Fall back to full calendar when OpenLiga history is thin.
        if len(finished_mds) < 10:
            finished_mds = list(range(1, 35))
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
                if key in blob and blob[key].get("home_xi") and all(
                    p.get("value_eur") for p in blob[key]["home_xi"][:1]
                ):
                    # Refresh if values missing on older caches.
                    if all((p.get("value_eur") or 0) > 0 for p in blob[key]["home_xi"][:3]):
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
                was_new = key not in blob
                blob[key] = parsed
                if was_new:
                    added += 1
                save_lineups(blob)
                print(
                    f"  XI {season} MD{md} {parsed['home_name']} vs {parsed['away_name']}"
                )
    if added:
        save_lineups(blob)
    return blob, added


def backfill_lineups(start: int = 2019, end: int | None = None) -> tuple[dict, int]:
    """Pull Transfermarkt XIs from ``start`` through the current season."""
    now = pd.Timestamp.now()
    end = end if end is not None else (now.year if now.month >= 7 else now.year - 1)
    seasons = list(range(start, end + 1))
    print(f"Backfill TM lineups {seasons[0]}–{seasons[-1]}")
    return sync_lineups(seasons)

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

    last = {app["team_key"]: app for app in appearances}  # latest appearance per club
    DATA.mkdir(parents=True, exist_ok=True)
    sides = {
        key: {k: app[k] for k in ("team", "team_short", "date", "opponent", "points", "gd", "xi", "bench")}
        for key, app in last.items()
    }
    LAST_SIDES_PATH.write_text(json.dumps(sides, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Last XI for {len(sides)} clubs, {added} new lineup pages")
    return {"added_lineups": added, "clubs": len(sides)}


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


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 2019
        end = int(sys.argv[3]) if len(sys.argv) > 3 else None
        blob, added = backfill_lineups(start, end)
        print(f"Done: {len(blob)} lineup pages, {added} new")
    elif len(sys.argv) > 1 and sys.argv[1] == "fd":
        now = pd.Timestamp.now()
        end = now.year if now.month >= 7 else now.year - 1
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 2019
        df = fetch_fd_seasons(list(range(start, end + 1)))
        print(df.head())
        print(len(df), "matches")
    else:
        build_tables()
