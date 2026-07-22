"""Bundesliga squads / estimated XIs for the XI lab.

Primary: footballsquads.co.uk (2026/27 when present, else 2025/26).
Fallback: Wikipedia season pages.
Cache: wiki_squads_cache.json
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CACHE_PATH = Path("wiki_squads_cache.json")
UA = "SpielfeldBot/1.0 (https://github.com/Prgrmmrjns/spielfeld; lineup research)"
FS_BASE = "https://www.footballsquads.co.uk"

# OpenLigaDB team -> footballsquads path fragments (tried newest-first)
FS_CLUBS = {
    "fc bayern muenchen": [
        "ger/2026-2027/bundes/bayern.htm",
        "ger/2025-2026/bundes/bayern.htm",
    ],
    "borussia dortmund": [
        "ger/2026-2027/bundes/dortmund.htm",
        "ger/2025-2026/bundes/dortmund.htm",
    ],
    "rb leipzig": [
        "ger/2026-2027/bundes/leipzig.htm",
        "ger/2025-2026/bundes/leipzig.htm",
    ],
    "vfb stuttgart": [
        "ger/2026-2027/bundes/stuttg.htm",
        "ger/2025-2026/bundes/stuttg.htm",
    ],
    "bayer 04 leverkusen": [
        "ger/2026-2027/bundes/bayerlev.htm",
        "ger/2025-2026/bundes/bayerlev.htm",
    ],
    "eintracht frankfurt": [
        "ger/2026-2027/bundes/einfrank.htm",
        "ger/2025-2026/bundes/einfrank.htm",
    ],
    "sc freiburg": [
        "ger/2026-2027/bundes/freiburg.htm",
        "ger/2025-2026/bundes/freiburg.htm",
    ],
    "vfl wolfsburg": [
        "ger/2026-2027/bundes/wolfsburg.htm",
        "ger/2025-2026/bundes/wolfsburg.htm",
    ],
    "tsg hoffenheim": [
        "ger/2026-2027/bundes/hoffen.htm",
        "ger/2025-2026/bundes/hoffen.htm",
    ],
    "1 fc union berlin": [
        "ger/2026-2027/bundes/unionber.htm",
        "ger/2025-2026/bundes/unionber.htm",
    ],
    "borussia moenchengladbach": [
        "ger/2026-2027/bundes/monchen.htm",
        "ger/2025-2026/bundes/monchen.htm",
    ],
    "1 fsv mainz 05": [
        "ger/2026-2027/bundes/mainz.htm",
        "ger/2025-2026/bundes/mainz.htm",
    ],
    "fc augsburg": [
        "ger/2026-2027/bundes/augsburg.htm",
        "ger/2025-2026/bundes/augsburg.htm",
    ],
    "1 fc koeln": [
        "ger/2026-2027/bundes/koln.htm",
        "ger/2025-2026/bundes/koln.htm",
    ],
    "sv werder bremen": [
        "ger/2026-2027/bundes/wbremen.htm",
        "ger/2025-2026/bundes/wbremen.htm",
    ],
    "hamburger sv": [
        "ger/2026-2027/bundes/hamburg.htm",
        "ger/2025-2026/bundes/hamburg.htm",
    ],
    "fc schalke 04": [
        "ger/2026-2027/bundes/schalke.htm",
        "ger/2025-2026/bundes2/schalke.htm",
    ],
    "sc paderborn 07": [
        "ger/2026-2027/bundes/paderbo.htm",
        "ger/2025-2026/bundes2/paderbo.htm",
    ],
    "sv 07 elversberg": [
        "ger/2026-2027/bundes/elversberg.htm",
        "ger/2025-2026/bundes2/elversberg.htm",
    ],
    "1 fc heidenheim 1846": [
        "ger/2025-2026/bundes/heiden.htm",
    ],
    "fc st pauli": [
        "ger/2025-2026/bundes/stpauli.htm",
    ],
}

# Wikipedia fallback slugs
WIKI_SLUGS = {
    "fc bayern muenchen": ["FC_Bayern_Munich"],
    "borussia dortmund": ["Borussia_Dortmund"],
    "rb leipzig": ["RB_Leipzig"],
    "vfb stuttgart": ["VfB_Stuttgart"],
    "bayer 04 leverkusen": ["Bayer_04_Leverkusen"],
    "eintracht frankfurt": ["Eintracht_Frankfurt"],
    "sc freiburg": ["SC_Freiburg"],
    "vfl wolfsburg": ["VfL_Wolfsburg"],
    "tsg hoffenheim": ["TSG_1899_Hoffenheim"],
    "1 fc union berlin": ["1._FC_Union_Berlin"],
    "borussia moenchengladbach": ["Borussia_Mönchengladbach"],
    "1 fsv mainz 05": ["1._FSV_Mainz_05"],
    "fc augsburg": ["FC_Augsburg"],
    "1 fc koeln": ["1._FC_Köln"],
    "sv werder bremen": ["SV_Werder_Bremen"],
    "hamburger sv": ["Hamburger_SV"],
    "fc schalke 04": ["FC_Schalke_04"],
    "sc paderborn 07": ["SC_Paderborn_07", "SC_Paderborn"],
    "sv 07 elversberg": ["SV_Elversberg"],
}

POS_MAP = {
    "G": "G", "GK": "G",
    "D": "D", "DF": "D",
    "M": "M", "MF": "M",
    "F": "F", "FW": "F", "A": "F",
}


def _norm(name: str) -> str:
    s = (name or "").lower().strip()
    s = s.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def preferred_wiki_seasons(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    start = now.year if now.month >= 7 else now.year - 1
    return [f"{y}–{str(y + 1)[2:]}" for y in (start, start - 1, start - 2)]


def _split_template_args(inner: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in inner:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _clean_wiki_name(raw: str) -> str:
    s = re.sub(r"\[\[([^|\]]+\|)?([^\]]+)\]\]", r"\2", raw or "")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"'{2,}", "", s)
    return s.strip()


def parse_fs_players(wikitext: str) -> list[dict]:
    out = []
    for m in re.finditer(r"\{\{[Ff]s player\|([^}]+)\}\}", wikitext):
        fields = {}
        for part in _split_template_args(m.group(1)):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            fields[k.strip().lower()] = v.strip()
        name = _clean_wiki_name(fields.get("name", ""))
        if not name:
            continue
        no = fields.get("no", "")
        pos = POS_MAP.get((fields.get("pos") or "").upper(), "M")
        out.append({
            "id": None,
            "name": name,
            "number": int(no) if no.isdigit() else None,
            "pos": pos,
            "grid": None,
            "source": "wikipedia",
        })
    return out


def parse_footballsquads_html(html: str) -> list[dict]:
    """Parse Number/Name/Nat/Pos table rows from footballsquads.co.uk."""
    out = []
    # Rows look like: <TD>1</TD><td>Manuel Neuer</td><td>GER</td><td...>G</td>
    pattern = re.compile(
        r"<tr>\s*<t[dh][^>]*>\s*(\d+)\s*</t[dh]>\s*"
        r"<t[dh][^>]*>\s*([^<]+?)\s*</t[dh]>\s*"
        r"<t[dh][^>]*>\s*([^<]*?)\s*</t[dh]>\s*"
        r"<t[dh][^>]*>\s*([A-Za-z/]{1,3})\s*</t[dh]>",
        re.I | re.S,
    )
    for m in pattern.finditer(html):
        name = re.sub(r"\s+", " ", m.group(2)).strip()
        if not name or name.lower() == "name":
            continue
        pos_raw = m.group(4).upper().split("/")[0]
        pos = POS_MAP.get(pos_raw, "M")
        out.append({
            "id": None,
            "name": name,
            "number": int(m.group(1)),
            "pos": pos,
            "grid": None,
            "source": "footballsquads",
        })
    return out


class WikiSquads:
    def __init__(self, cache_path: Path = CACHE_PATH):
        self.cache_path = Path(cache_path)
        self.cache = self._load()
        self._last_fetch = 0.0

    def _load(self) -> dict:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"teams": {}, "fetched_at": None}

    def save(self):
        self.cache["fetched_at"] = datetime.now(timezone.utc).isoformat()
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _throttle(self):
        elapsed = time.time() - self._last_fetch
        if elapsed < 0.45:
            time.sleep(0.45 - elapsed)

    def _fetch_text(self, url: str) -> str | None:
        self._throttle()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._last_fetch = time.time()
                if getattr(resp, "status", 200) >= 400:
                    return None
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            self._last_fetch = time.time()
            if exc.code == 429:
                time.sleep(2.5)
                return self._fetch_text(url)
            return None
        except Exception:
            self._last_fetch = time.time()
            return None

    def _wiki_json(self, params: dict) -> dict | None:
        self._throttle()
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._last_fetch = time.time()
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            self._last_fetch = time.time()
            return None

    def _decorate(self, team_key: str, players: list[dict]) -> list[dict]:
        """Assign ids + strengths. Stars outrank list order so Best XI can promote them."""
        pos_base = {"G": 2.35, "D": 2.4, "M": 2.45, "F": 2.5}
        # Hand-tuned quality bumps for obvious first-team regulars (squad-list order is noisy).
        star_boost = {
            "harry kane": 1.15, "jamal musiala": 1.1, "michael olise": 1.05, "luis diaz": 1.0,
            "serge gnabry": 0.75, "leroy sane": 0.7, "alphonso davies": 0.85, "joshua kimmich": 0.95,
            "manuel neuer": 0.8, "dayot upamecano": 0.7, "kim min jae": 0.75, "jonathan tah": 0.65,
            "aleksandar pavlovic": 0.7, "joao palhinha": 0.55, "kingsley coman": 0.55,
            "florian wirtz": 1.2, "granit xhaka": 0.7, "victor boniface": 0.85, "patrick schick": 0.7,
            "jeremie frimpong": 0.75, "alejandro grimaldo": 0.7, "exequiel palacios": 0.55,
            "serhou guirassy": 1.0, "deniz undav": 0.85, "angelo stiller": 0.7, "chris fuehrich": 0.65,
            "maximilian mittelstaedt": 0.55, "alexander nuebel": 0.5,
            "julian brandt": 0.85, "karim adeyemi": 0.8, "jamie bynoe gittens": 0.7,
            "nico schlotterbeck": 0.75, "felix nmecha": 0.55, "gregor kobel": 0.8,
            "benjamin sesko": 0.9, "xavi simons": 0.95, "lois openda": 0.85, "david raum": 0.7,
            "willi orban": 0.6, "xaver schlager": 0.55,
            "omar marmoush": 0.95, "hugo ekitike": 0.8, "randal kolo muani": 0.7,
            "mario gotze": 0.55, "ansgar knauff": 0.5,
            "niclas fuellkrug": 0.75, "marvin ducksch": 0.65, "romano schmid": 0.55,
            "tim kleindienst": 0.7, "ermedin demirovic": 0.7, "jonathan burkardt": 0.75,
            "andrej kramaric": 0.7, "grischa proemel": 0.5, "maximilian beiderbeck": 0.55,
        }
        # Normalize keys once
        boost_norm = {_norm(k): v for k, v in star_boost.items()}
        ranked = sorted(
            enumerate(players),
            key=lambda t: (
                -boost_norm.get(_norm(t[1].get("name") or ""), 0),
                t[0],
            ),
        )
        for rank, (orig_i, p) in enumerate(ranked):
            p["id"] = abs(hash(f"{team_key}:{p['name']}:{p.get('number')}")) % (10**9)
            boost = boost_norm.get(_norm(p.get("name") or ""), 0.0)
            base = pos_base.get(p.get("pos") or "M", 2.4)
            # Small decay by quality rank so Best XI has a clear ordering
            p["strength"] = round(base + boost - rank * 0.012, 3)
        return players

    def _from_footballsquads(self, team_name: str) -> dict | None:
        key = _norm(team_name)
        paths = FS_CLUBS.get(key)
        if not paths:
            return None
        for path in paths:
            html = self._fetch_text(f"{FS_BASE}/{path}")
            if not html or "Number" not in html:
                continue
            players = parse_footballsquads_html(html)
            if len(players) < 11:
                continue
            season = "2026–27" if "2026-2027" in path else "2025–26"
            return {
                "team": team_name,
                "season": season,
                "page": f"{FS_BASE}/{path}",
                "players": self._decorate(key, players),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "footballsquads",
            }
        return None

    def _from_wikipedia(self, team_name: str) -> dict | None:
        key = _norm(team_name)
        slugs = WIKI_SLUGS.get(key)
        if not slugs:
            return None
        for season in preferred_wiki_seasons():
            for slug in slugs:
                title = f"{season}_{slug}_season"
                data = self._wiki_json({"action": "parse", "page": title, "prop": "sections", "format": "json"})
                if not data or "parse" not in data:
                    continue
                sections = data["parse"].get("sections") or []
                idx = next((s["index"] for s in sections if s.get("line") == "Players"), None)
                if idx is None:
                    continue
                body = self._wiki_json({
                    "action": "parse", "page": title, "prop": "wikitext",
                    "format": "json", "section": str(idx),
                })
                wt = (body or {}).get("parse", {}).get("wikitext", {}).get("*") or ""
                players = parse_fs_players(wt)
                if len(players) < 11:
                    continue
                return {
                    "team": team_name,
                    "season": season,
                    "page": title,
                    "players": self._decorate(key, players),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "source": "wikipedia",
                }
        return None

    def fetch_squad(self, team_name: str, force: bool = False) -> dict | None:
        key = _norm(team_name)
        cached = self.cache.get("teams", {}).get(f"squad:{key}")
        if cached and not force and cached.get("players"):
            return cached

        row = self._from_footballsquads(team_name) or self._from_wikipedia(team_name)
        if not row:
            return None if force else cached
        self.cache.setdefault("teams", {})[f"squad:{key}"] = row
        self.save()
        return row

    def estimate_xi(self, squad: list[dict], formation: str = "4-2-3-1") -> list[dict]:
        parts = [int(x) for x in re.split(r"[-–]", formation) if x.isdigit()]
        if not parts:
            parts = [4, 2, 3, 1]
        need = {"G": 1, "D": parts[0], "M": sum(parts[1:-1]) if len(parts) > 2 else parts[1], "F": parts[-1]}
        if need["D"] + need["M"] + need["F"] != 10:
            need = {"G": 1, "D": 4, "M": 3, "F": 3}
        buckets = {"G": [], "D": [], "M": [], "F": []}
        for p in squad:
            buckets[p.get("pos") or "M"].append(p)
        for k in buckets:
            buckets[k].sort(key=lambda p: (-(p.get("strength") or 0), p.get("number") or 99))
        xi = []
        for pos, n in (("G", need["G"]), ("D", need["D"]), ("M", need["M"]), ("F", need["F"])):
            xi.extend(buckets[pos][:n])
        used = {p["id"] for p in xi}
        rest = sorted([p for p in squad if p["id"] not in used], key=lambda p: -(p.get("strength") or 0))
        while len(xi) < 11 and rest:
            xi.append(rest.pop(0))
        return xi[:11]

    def side_for_team(self, team_name: str, formation: str | None = None) -> dict | None:
        squad_row = self.fetch_squad(team_name)
        if not squad_row or not squad_row.get("players"):
            return None
        formation = formation or "4-2-3-1"
        players = squad_row["players"]
        xi = self.estimate_xi(players, formation)
        xi_ids = {p["id"] for p in xi}
        pool = [p for p in players if p["id"] not in xi_ids]
        pool.sort(key=lambda p: (-(p.get("strength") or 0), p.get("number") or 99))
        src = "wiki_squad" if squad_row.get("source") == "wikipedia" else "squad_2026"
        return {
            "source": src,
            "formation": formation,
            "players": [{k: p.get(k) for k in ("id", "name", "number", "pos", "grid", "strength")} for p in xi],
            "pool": [{k: p.get(k) for k in ("id", "name", "number", "pos", "grid", "strength")} for p in pool],
            "strength": round(sum(p.get("strength") or 0 for p in xi), 3),
            "season": squad_row.get("season"),
            "page": squad_row.get("page"),
        }


def enrich_side_with_wiki(side: dict | None, team_name: str, wiki: WikiSquads | None = None,
                          replace_players: bool = False) -> dict:
    """Attach current squad pool (and optionally replace stale XI)."""
    wiki = wiki or WikiSquads()
    side = dict(side or {})
    w = wiki.side_for_team(team_name, side.get("formation"))
    if not w:
        side.setdefault("pool", side.get("pool") or [])
        return side

    if replace_players or not side.get("players"):
        side["players"] = w["players"]
        side["formation"] = w.get("formation") or side.get("formation")
        side["source"] = w["source"]
        side["strength"] = w.get("strength")
    else:
        by_name = {_norm(p["name"]): p for p in w["players"] + w["pool"]}
        for p in side.get("players") or []:
            hit = by_name.get(_norm(p.get("name") or ""))
            if hit and p.get("strength") is None:
                p["strength"] = hit.get("strength")
        if not side.get("strength"):
            side["strength"] = round(sum(p.get("strength") or 0 for p in side.get("players") or []), 3)

    existing_ids = {p.get("id") for p in (side.get("players") or []) if p.get("id") is not None}
    existing_names = {_norm(p.get("name")) for p in (side.get("players") or [])}
    pool = []
    seen = set(existing_ids)
    for p in w["pool"]:
        if p.get("id") in seen or _norm(p.get("name")) in existing_names:
            continue
        seen.add(p.get("id"))
        pool.append(p)
    pool.sort(key=lambda p: (-(p.get("strength") or 0), p.get("number") or 99))
    side["pool"] = pool
    side["wiki_season"] = w.get("season")
    return side
