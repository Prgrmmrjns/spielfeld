"""API-Football client for Bundesliga squads and starting XIs.

Env: API_FOOTBALL_KEY (or APIFOOTBALL_KEY / API_SPORTS_KEY)
Docs: https://www.api-football.com/
Bundesliga league id: 78
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

BASE = "https://v3.football.api-sports.io"
LEAGUE_ID = 78
CACHE_PATH = Path("api_football_cache.json")

# OpenLigaDB team name -> fuzzy aliases for API-Football matching
NAME_ALIASES = {
    "fc bayern münchen": ["bayern munich", "bayern münchen", "fc bayern munich"],
    "borussia mönchengladbach": ["borussia monchengladbach", "mönchengladbach", "gladbach"],
    "1. fsv mainz 05": ["mainz", "fsv mainz 05", "mainz 05"],
    "1. fc union berlin": ["union berlin", "1.fc union berlin"],
    "1. fc köln": ["fc koln", "1. fc koln", "cologne", "1.fc köln", "fc cologne"],
    "bayer 04 leverkusen": ["bayer leverkusen", "leverkusen"],
    "borussia dortmund": ["dortmund", "bvb"],
    "eintracht frankfurt": ["frankfurt"],
    "rb leipzig": ["rasenballsport leipzig", "leipzig"],
    "vfb stuttgart": ["stuttgart"],
    "sc freiburg": ["freiburg"],
    "tsg hoffenheim": ["tsg 1899 hoffenheim", "hoffenheim", "1899 hoffenheim"],
    "sv werder bremen": ["werder bremen", "bremen"],
    "fc augsburg": ["augsburg"],
    "hamburger sv": ["hamburger sv", "hamburg", "hsv"],
    "fc schalke 04": ["schalke 04", "schalke"],
    "sc paderborn 07": ["paderborn", "sc paderborn"],
    "sv 07 elversberg": ["elversberg", "sv elversberg"],
    "vfl wolfsburg": ["wolfsburg"],
}


def _norm(name: str) -> str:
    s = (name or "").lower().strip()
    s = s.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class ApiFootball:
    def __init__(self, api_key: str | None = None, cache_path: Path = CACHE_PATH):
        self.api_key = (
            api_key
            or os.getenv("API_FOOTBALL_KEY")
            or os.getenv("APIFOOTBALL_KEY")
            or os.getenv("API_SPORTS_KEY")
        )
        self.cache_path = Path(cache_path)
        self.cache = self._load_cache()
        self._session = requests.Session()
        if self.api_key:
            self._session.headers.update({
                "x-apisports-key": self.api_key,
                "Accept": "application/json",
            })

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _empty_cache(self) -> dict:
        return {
            "teams": {},          # api_team_id -> {id,name,...}
            "name_to_id": {},     # normalized openliga/api name -> api_team_id
            "squads": {},         # str(team_id) -> [{id,name,position,number}]
            "player_stats": {},   # f"{season}:{player_id}" -> {minutes,goals,assists,rating}
            "fixtures": {},       # f"{season}" -> [fixture dicts]
            "lineups": {},        # str(fixture_id) -> lineup payload
            "last_xi": {},        # str(team_id) -> {fixture_id, formation, players:[...], source}
        }

    def _load_cache(self) -> dict:
        base = self._empty_cache()
        if self.cache_path.exists():
            try:
                loaded = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    base.update({k: v for k, v in loaded.items() if v is not None})
            except Exception:
                pass
        for key in self._empty_cache():
            base.setdefault(key, {})
        return base

    def save(self):
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get(self, path: str, params: dict | None = None, sleep: float = 0.25) -> dict:
        if not self.enabled:
            raise RuntimeError("API_FOOTBALL_KEY not set")
        url = f"{BASE}{path}"
        r = self._session.get(url, params=params or {}, timeout=45)
        if r.status_code == 429:
            time.sleep(5)
            r = self._session.get(url, params=params or {}, timeout=45)
        r.raise_for_status()
        if sleep:
            time.sleep(sleep)
        return r.json()

    def ensure_teams(self, season: int | None = None):
        """Load Bundesliga (+ 2.BL) teams for an accessible season into cache."""
        season = season or _accessible_season(self)
        key = f"teams_{season}"
        if self.cache.get(key):
            return
        for league in (LEAGUE_ID, 79):
            data = self._get("/teams", {"league": league, "season": season})
            for row in data.get("response") or []:
                team = row.get("team") or {}
                tid = team.get("id")
                if not tid:
                    continue
                self.cache["teams"][str(tid)] = team
                self.cache["name_to_id"][_norm(team.get("name", ""))] = tid
                if team.get("code"):
                    self.cache["name_to_id"][_norm(team["code"])] = tid
        self.cache[key] = True
        self.cache["data_season"] = season
        self._build_alias_map()
        self.save()

    def _build_alias_map(self):
        # Map OpenLiga aliases onto cached API team ids
        api_names = {tid: _norm(t.get("name", "")) for tid, t in self.cache["teams"].items()}
        for openliga, aliases in NAME_ALIASES.items():
            candidates = [_norm(openliga)] + [_norm(a) for a in aliases]
            for tid, aname in api_names.items():
                if aname in candidates or any(c in aname or aname in c for c in candidates if len(c) > 4):
                    self.cache["name_to_id"][_norm(openliga)] = int(tid)
                    for a in aliases:
                        self.cache["name_to_id"][_norm(a)] = int(tid)
                    break

    def resolve_team_id(self, openliga_name: str) -> int | None:
        n = _norm(openliga_name)
        if n in self.cache["name_to_id"]:
            return int(self.cache["name_to_id"][n])
        # try aliases table
        for openliga, aliases in NAME_ALIASES.items():
            if n == _norm(openliga) or n in {_norm(a) for a in aliases}:
                if _norm(openliga) in self.cache["name_to_id"]:
                    return int(self.cache["name_to_id"][_norm(openliga)])
        # substring fallback
        for tid, team in self.cache["teams"].items():
            an = _norm(team.get("name", ""))
            if n in an or an in n:
                return int(tid)
        return None

    def ensure_squad(self, team_id: int):
        sid = str(team_id)
        if sid in self.cache["squads"] and self.cache["squads"][sid]:
            return self.cache["squads"][sid]
        data = self._get("/players/squads", {"team": team_id})
        players = []
        for block in data.get("response") or []:
            for p in block.get("players") or []:
                players.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "age": p.get("age"),
                    "number": p.get("number"),
                    "position": p.get("position"),
                    "photo": p.get("photo"),
                })
        self.cache["squads"][sid] = players
        self.save()
        return players

    def ensure_fixtures(self, season: int):
        season = _accessible_season(self, season)
        sk = str(season)
        if sk in self.cache["fixtures"] and self.cache["fixtures"][sk]:
            return self.cache["fixtures"][sk]
        fixtures = []
        for league in (LEAGUE_ID, 79):
            data = self._get("/fixtures", {"league": league, "season": season}, sleep=0.4)
            for row in data.get("response") or []:
                fx = row.get("fixture") or {}
                teams = row.get("teams") or {}
                goals = row.get("goals") or {}
                league_meta = row.get("league") or {}
                fixtures.append({
                    "id": fx.get("id"),
                    "date": fx.get("date"),
                    "timestamp": fx.get("timestamp"),
                    "status": (fx.get("status") or {}).get("short"),
                    "round": league_meta.get("round"),
                    "league_id": league_meta.get("id") or league,
                    "home_id": (teams.get("home") or {}).get("id"),
                    "away_id": (teams.get("away") or {}).get("id"),
                    "home_name": (teams.get("home") or {}).get("name"),
                    "away_name": (teams.get("away") or {}).get("name"),
                    "home_goals": goals.get("home"),
                    "away_goals": goals.get("away"),
                })
        self.cache["fixtures"][sk] = fixtures
        self.cache["data_season"] = season
        self.save()
        return fixtures

    def fetch_lineup(self, fixture_id: int, force: bool = False) -> dict | None:
        fid = str(fixture_id)
        if not force and fid in self.cache["lineups"]:
            return self.cache["lineups"][fid]
        data = self._get("/fixtures/lineups", {"fixture": fixture_id}, sleep=0.35)
        resp = data.get("response") or []
        if not resp:
            return None
        parsed = []
        for side in resp:
            team = side.get("team") or {}
            start = []
            for item in side.get("startXI") or []:
                p = item.get("player") or {}
                start.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "number": p.get("number"),
                    "pos": p.get("pos"),
                    "grid": p.get("grid"),
                })
            bench = []
            for item in side.get("substitutes") or []:
                p = item.get("player") or {}
                bench.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "number": p.get("number"),
                    "pos": p.get("pos"),
                })
            parsed.append({
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "formation": side.get("formation"),
                "coach": (side.get("coach") or {}).get("name"),
                "startXI": start,
                "substitutes": bench,
            })
            # update last XI
            if start and team.get("id"):
                self.cache["last_xi"][str(team["id"])] = {
                    "fixture_id": fixture_id,
                    "formation": side.get("formation"),
                    "players": start,
                    "source": "confirmed",
                }
        self.cache["lineups"][fid] = parsed
        self.save()
        return parsed

    def sync_recent_lineups(self, seasons: list[int] | None = None, max_fetches: int = 40):
        """Backfill missing lineups for finished fixtures (rate-limit friendly)."""
        seasons = seasons or [_current_season() - 1, _current_season()]
        fetches = 0
        for season in seasons:
            self.ensure_teams(season)
            fixtures = self.ensure_fixtures(season)
            for fx in fixtures:
                if fetches >= max_fetches:
                    return fetches
                if fx.get("status") not in {"FT", "AET", "PEN"}:
                    continue
                fid = fx.get("id")
                if not fid or str(fid) in self.cache["lineups"]:
                    continue
                try:
                    self.fetch_lineup(fid)
                    fetches += 1
                except Exception:
                    continue
        return fetches

    def lineup_for_fixture(self, fixture_id: int | None, home_id: int | None, away_id: int | None) -> dict:
        """Return home/away XI: confirmed lineup or last starting XI fallback."""
        confirmed = None
        if fixture_id:
            try:
                confirmed = self.fetch_lineup(fixture_id, force=False)
            except Exception:
                confirmed = self.cache["lineups"].get(str(fixture_id))

        def side(team_id: int | None, which: str) -> dict:
            if not team_id:
                return {"source": "unknown", "formation": None, "players": [], "team_id": None}
            if confirmed:
                for block in confirmed:
                    if block.get("team_id") == team_id and block.get("startXI"):
                        return {
                            "source": "confirmed",
                            "formation": block.get("formation"),
                            "players": block.get("startXI") or [],
                            "substitutes": block.get("substitutes") or [],
                            "coach": block.get("coach"),
                            "team_id": team_id,
                        }
            last = self.cache["last_xi"].get(str(team_id))
            if last and last.get("players"):
                return {
                    "source": "last_xi",
                    "formation": last.get("formation"),
                    "players": last.get("players") or [],
                    "substitutes": [],
                    "coach": None,
                    "team_id": team_id,
                    "from_fixture_id": last.get("fixture_id"),
                }
            # squad fallback: first 11 listed by position preference
            squad = self.ensure_squad(team_id) if self.enabled else []
            ordered = _order_squad_as_xi(squad)
            return {
                "source": "squad_estimate" if ordered else "unknown",
                "formation": None,
                "players": ordered,
                "substitutes": [],
                "coach": None,
                "team_id": team_id,
            }

        return {
            "home": side(home_id, "home"),
            "away": side(away_id, "away"),
            "fixture_id": fixture_id,
        }

    def find_fixture(self, home_name: str, away_name: str, date_iso: str | None = None, season: int | None = None):
        # Use plan-accessible season for lineup history; only return a fixture when
        # the kickoff date matches (so we don't mark old games as "confirmed").
        data_season = _accessible_season(self, season)
        self.ensure_teams(data_season)
        fixtures = self.ensure_fixtures(data_season)
        hid = self.resolve_team_id(home_name)
        aid = self.resolve_team_id(away_name)
        date_prefix = (date_iso or "")[:10]
        if not date_prefix:
            return None
        for fx in fixtures:
            if hid and aid and fx.get("home_id") == hid and fx.get("away_id") == aid:
                if (fx.get("date") or "").startswith(date_prefix):
                    return fx
            if (
                _norm(fx.get("home_name", "")) == _norm(home_name)
                and _norm(fx.get("away_name", "")) == _norm(away_name)
                and (fx.get("date") or "").startswith(date_prefix)
            ):
                return fx
        return None

    def player_strength(self, player_id: int | None, season: int | None = None) -> float:
        if not player_id:
            return 1.0
        season = season or _current_season()
        key = f"{season}:{player_id}"
        st = self.cache["player_stats"].get(key)
        if not st:
            return 1.0
        minutes = float(st.get("minutes") or 0)
        goals = float(st.get("goals") or 0)
        assists = float(st.get("assists") or 0)
        rating = float(st.get("rating") or 0)
        return 1.0 + minutes / 900.0 + 0.35 * goals + 0.25 * assists + 0.15 * max(rating - 6.5, 0)

    def serialize_player(self, p: dict, season: int | None = None) -> dict:
        pos = p.get("pos")
        if not pos and p.get("position"):
            pos = str(p["position"])[:1]
        pid = p.get("id")
        return {
            "id": pid,
            "name": p.get("name"),
            "number": p.get("number"),
            "pos": pos or None,
            "grid": p.get("grid"),
            "strength": round(self.player_strength(pid, season), 3),
        }

    def serialize_side(self, block: dict, season: int | None = None, include_pool: bool = True) -> dict:
        """Pack a lineup side for the web UI (grid, strength, bench/squad pool)."""
        players = [self.serialize_player(p, season) for p in (block.get("players") or [])]
        strength = float(sum(p["strength"] for p in players)) if players else None
        out = {
            "source": block.get("source") or "unknown",
            "formation": block.get("formation"),
            "players": players,
            "strength": strength,
            "team_id": block.get("team_id"),
        }
        if not include_pool:
            return out
        pool: list[dict] = []
        seen = {p.get("id") for p in players if p.get("id") is not None}
        for p in block.get("substitutes") or []:
            sp = self.serialize_player(p, season)
            if sp.get("id") is not None and sp["id"] in seen:
                continue
            if sp.get("id") is not None:
                seen.add(sp["id"])
            pool.append(sp)
        tid = block.get("team_id")
        if tid:
            try:
                for p in self.ensure_squad(tid) or []:
                    if p.get("id") in seen:
                        continue
                    sp = self.serialize_player(p, season)
                    if sp.get("id") is not None:
                        seen.add(sp["id"])
                    pool.append(sp)
            except Exception:
                pass
        # Strongest alternatives first for the XI lab
        pool.sort(key=lambda p: (-(p.get("strength") or 0), p.get("number") or 99))
        out["pool"] = pool
        return out

    def xi_strength(self, players: list[dict], season: int | None = None) -> float:
        if not players:
            return 0.0
        return float(sum(self.player_strength(p.get("id"), season) for p in players))

    def enrich_player_stats_for_teams(self, team_ids: list[int], season: int, max_pages_per_team: int = 3):
        """Optionally pull season player stats (uses several requests)."""
        for tid in team_ids:
            page = 1
            while page <= max_pages_per_team:
                try:
                    data = self._get("/players", {"team": tid, "season": season, "league": LEAGUE_ID, "page": page}, sleep=0.4)
                except Exception:
                    break
                resp = data.get("response") or []
                if not resp:
                    break
                for row in resp:
                    player = row.get("player") or {}
                    pid = player.get("id")
                    stats = (row.get("statistics") or [{}])[0]
                    games = stats.get("games") or {}
                    goals = stats.get("goals") or {}
                    self.cache["player_stats"][f"{season}:{pid}"] = {
                        "minutes": games.get("minutes") or 0,
                        "rating": float(games.get("rating") or 0) if games.get("rating") else 0,
                        "goals": goals.get("total") or 0,
                        "assists": goals.get("assists") or 0,
                        "name": player.get("name"),
                    }
                paging = data.get("paging") or {}
                if page >= int(paging.get("total") or 1):
                    break
                page += 1
            self.save()


def _current_season() -> int:
    import pandas as pd
    now = pd.Timestamp.now()
    return now.year if now.month >= 7 else now.year - 1


def _accessible_season(client: "ApiFootball", preferred: int | None = None) -> int:
    """Pick newest Bundesliga season the API key/plan can read (free ≈ 2022–2024)."""
    override = os.getenv("AF_DATA_SEASON")
    if override:
        return int(override)
    preferred = preferred or _current_season()
    for season in range(preferred, preferred - 5, -1):
        try:
            data = client._get("/teams", {"league": LEAGUE_ID, "season": season}, sleep=0.15)
            if data.get("response"):
                if season != preferred:
                    print(f"API-Football: season {preferred} unavailable on plan — using {season}")
                return season
        except Exception:
            continue
    return preferred


def _order_squad_as_xi(squad: list[dict]) -> list[dict]:
    order = {"Goalkeeper": 0, "Defender": 1, "Midfielder": 2, "Attacker": 3}
    ranked = sorted(squad, key=lambda p: (order.get(p.get("position") or "", 9), p.get("number") or 99))
    out = []
    for p in ranked[:11]:
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "number": p.get("number"),
            "pos": (p.get("position") or "")[:1] or None,
            "grid": None,
        })
    return out
