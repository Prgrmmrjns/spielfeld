"""Download Bundesliga CSVs from football-data.co.uk (results + odds + shots/xG)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

from pipeline.paths import RAW, SEASONS
from pipeline.team_map import slug_from_fd

BASE = "https://www.football-data.co.uk/mmz4281/{code}/D1.csv"


def download_season(code: str, force: bool = False) -> Path:
    out = RAW / f"fd_{code}.csv"
    if out.exists() and not force:
        return out
    url = BASE.format(code=code)
    r = requests.get(url, timeout=60, allow_redirects=True)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    if "HomeTeam" not in text.splitlines()[0]:
        raise RuntimeError(f"Unexpected CSV header for {code}: {text[:120]}")
    out.write_text(text, encoding="utf-8")
    return out


def load_season(code: str) -> pd.DataFrame:
    path = download_season(code)
    raw = pd.read_csv(path)
    raw = raw.dropna(subset=["HomeTeam", "AwayTeam", "Date"]).copy()
    kickoff = pd.to_datetime(raw["Date"], dayfirst=True, errors="coerce")
    if "Time" in raw.columns:
        t = raw["Time"].fillna("15:30")
        kickoff = pd.to_datetime(
            raw["Date"].astype(str) + " " + t.astype(str),
            dayfirst=True,
            errors="coerce",
        )
    df = raw.assign(
        season_code=code,
        season_label=SEASONS[code]["label"],
        season_year=SEASONS[code]["openliga"],
        home_slug=raw["HomeTeam"].map(slug_from_fd),
        away_slug=raw["AwayTeam"].map(slug_from_fd),
        kickoff=kickoff,
    )
    unmatched = df[df["home_slug"].isna() | df["away_slug"].isna()]
    if len(unmatched):
        missing = sorted(
            set(unmatched.loc[unmatched["home_slug"].isna(), "HomeTeam"])
            | set(unmatched.loc[unmatched["away_slug"].isna(), "AwayTeam"])
        )
        raise ValueError(f"Unmapped football-data teams in {code}: {missing}")
    return df


def load_all_seasons(codes: list[str] | None = None) -> pd.DataFrame:
    codes = codes or list(SEASONS.keys())
    frames = [load_season(c) for c in codes]
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("kickoff").reset_index(drop=True)
    df["match_uid"] = (
        df["season_code"]
        + "_"
        + df["home_slug"]
        + "_"
        + df["away_slug"]
        + "_"
        + df["kickoff"].dt.strftime("%Y%m%d")
    )
    return df


if __name__ == "__main__":
    df = load_all_seasons()
    print(df.shape, df["season_label"].value_counts().to_dict())
    print(df.tail(3)[["season_label", "HomeTeam", "AwayTeam", "FTR", "AvgH", "AvgD", "AvgA"]])
