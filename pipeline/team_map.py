"""Canonical team name mapping across OpenLigaDB and football-data.co.uk."""

from __future__ import annotations

# football-data.co.uk HomeTeam/AwayTeam → canonical slug
FD_TO_SLUG: dict[str, str] = {
    "Bayern Munich": "bayern",
    "Dortmund": "dortmund",
    "RB Leipzig": "leipzig",
    "Leverkusen": "leverkusen",
    "Frankfurt": "frankfurt",
    "Wolfsburg": "wolfsburg",
    "Hoffenheim": "hoffenheim",
    "Stuttgart": "stuttgart",
    "Gladbach": "gladbach",
    "M'gladbach": "gladbach",
    "Werder Bremen": "bremen",
    "Freiburg": "freiburg",
    "Augsburg": "augsburg",
    "Mainz": "mainz",
    "Union Berlin": "union",
    "Bochum": "bochum",
    "FC Koln": "koeln",
    "Cologne": "koeln",
    "Heidenheim": "heidenheim",
    "Darmstadt": "darmstadt",
    "Schalke 04": "schalke",
    "Hertha": "hertha",
    "Bielefeld": "bielefeld",
    "Greuther Furth": "fuerth",
    "Paderborn": "paderborn",
    "Fortuna Dusseldorf": "duesseldorf",
    "Dusseldorf": "duesseldorf",
    "Hamburg": "hamburg",
    "Hannover": "hannover",
    "Nurnberg": "nuernberg",
    "St Pauli": "stpauli",
    "Holstein Kiel": "kiel",
    "Elversberg": "elversberg",
    "SV Elversberg": "elversberg",
}

# OpenLigaDB shortName / teamName fragments → slug
OL_TO_SLUG: dict[str, str] = {
    "Bayern": "bayern",
    "FC Bayern München": "bayern",
    "Dortmund": "dortmund",
    "Borussia Dortmund": "dortmund",
    "Leipzig": "leipzig",
    "RB Leipzig": "leipzig",
    "RasenBallsport Leipzig": "leipzig",
    "Leverkusen": "leverkusen",
    "Bayer Leverkusen": "leverkusen",
    "Bayer 04 Leverkusen": "leverkusen",
    "Frankfurt": "frankfurt",
    "Eintracht Frankfurt": "frankfurt",
    "Wolfsburg": "wolfsburg",
    "VfL Wolfsburg": "wolfsburg",
    "Hoffenheim": "hoffenheim",
    "TSG 1899 Hoffenheim": "hoffenheim",
    "TSG Hoffenheim": "hoffenheim",
    "Stuttgart": "stuttgart",
    "VfB Stuttgart": "stuttgart",
    "M'gladbach": "gladbach",
    "Gladbach": "gladbach",
    "Borussia Mönchengladbach": "gladbach",
    "Bremen": "bremen",
    "Werder Bremen": "bremen",
    "SV Werder Bremen": "bremen",
    "Freiburg": "freiburg",
    "SC Freiburg": "freiburg",
    "Augsburg": "augsburg",
    "FC Augsburg": "augsburg",
    "Mainz": "mainz",
    "Mainz 05": "mainz",
    "1. FSV Mainz 05": "mainz",
    "Union Berlin": "union",
    "1. FC Union Berlin": "union",
    "Bochum": "bochum",
    "VfL Bochum": "bochum",
    "VfL Bochum 1848": "bochum",
    "Köln": "koeln",
    "FC Köln": "koeln",
    "1. FC Köln": "koeln",
    "Heidenheim": "heidenheim",
    "1. FC Heidenheim 1846": "heidenheim",
    "Darmstadt": "darmstadt",
    "SV Darmstadt 98": "darmstadt",
    "Schalke": "schalke",
    "Schalke 04": "schalke",
    "FC Schalke 04": "schalke",
    "Hertha": "hertha",
    "Hertha BSC": "hertha",
    "Bielefeld": "bielefeld",
    "Arminia Bielefeld": "bielefeld",
    "Fürth": "fuerth",
    "Greuther Fürth": "fuerth",
    "SpVgg Greuther Fürth": "fuerth",
    "Paderborn": "paderborn",
    "SC Paderborn 07": "paderborn",
    "Düsseldorf": "duesseldorf",
    "Fortuna Düsseldorf": "duesseldorf",
    "Hamburg": "hamburg",
    "Hamburger SV": "hamburg",
    "Hannover": "hannover",
    "Hannover 96": "hannover",
    "Nürnberg": "nuernberg",
    "1. FC Nürnberg": "nuernberg",
    "St. Pauli": "stpauli",
    "FC St. Pauli": "stpauli",
    "Kiel": "kiel",
    "Holstein Kiel": "kiel",
    "Elversberg": "elversberg",
    "SV Elversberg": "elversberg",
}

DISPLAY_NAMES: dict[str, str] = {
    "bayern": "Bayern München",
    "dortmund": "Borussia Dortmund",
    "leipzig": "RB Leipzig",
    "leverkusen": "Bayer Leverkusen",
    "frankfurt": "Eintracht Frankfurt",
    "wolfsburg": "VfL Wolfsburg",
    "hoffenheim": "TSG Hoffenheim",
    "stuttgart": "VfB Stuttgart",
    "gladbach": "Borussia Mönchengladbach",
    "bremen": "Werder Bremen",
    "freiburg": "SC Freiburg",
    "augsburg": "FC Augsburg",
    "mainz": "Mainz 05",
    "union": "Union Berlin",
    "bochum": "VfL Bochum",
    "koeln": "1. FC Köln",
    "heidenheim": "Heidenheim",
    "darmstadt": "Darmstadt 98",
    "schalke": "Schalke 04",
    "hertha": "Hertha BSC",
    "bielefeld": "Arminia Bielefeld",
    "fuerth": "Greuther Fürth",
    "paderborn": "Paderborn",
    "duesseldorf": "Fortuna Düsseldorf",
    "hamburg": "Hamburger SV",
    "hannover": "Hannover 96",
    "nuernberg": "1. FC Nürnberg",
    "stpauli": "FC St. Pauli",
    "kiel": "Holstein Kiel",
    "elversberg": "SV Elversberg",
}


def slug_from_fd(name: str) -> str | None:
    if name in FD_TO_SLUG:
        return FD_TO_SLUG[name]
    # fuzzy fallback
    lower = name.lower()
    for k, v in FD_TO_SLUG.items():
        if k.lower() in lower or lower in k.lower():
            return v
    return None


def slug_from_ol(team: dict | str) -> str | None:
    if isinstance(team, dict):
        for key in ("shortName", "teamName"):
            val = team.get(key)
            if val and val in OL_TO_SLUG:
                return OL_TO_SLUG[val]
        name = team.get("teamName") or team.get("shortName") or ""
    else:
        name = team
    if name in OL_TO_SLUG:
        return OL_TO_SLUG[name]
    for k, v in OL_TO_SLUG.items():
        if k.lower() == name.lower():
            return v
    # substring
    for k, v in OL_TO_SLUG.items():
        if k.lower() in name.lower() or name.lower() in k.lower():
            return v
    return None
