"""Sanity: Elo/form features for match i must not use match i result."""

import numpy as np
import pandas as pd

from pipeline.features.build import compute_elo_and_form


def test_elo_updates_only_after_match():
    df = pd.DataFrame(
        [
            {
                "match_uid": "m1",
                "kickoff": pd.Timestamp("2024-01-01"),
                "home_slug": "bayern",
                "away_slug": "dortmund",
                "season_year": 2023,
                "FTHG": 2,
                "FTAG": 0,
                "FTR": "H",
            },
            {
                "match_uid": "m2",
                "kickoff": pd.Timestamp("2024-01-08"),
                "home_slug": "bayern",
                "away_slug": "leipzig",
                "season_year": 2023,
                "FTHG": 1,
                "FTAG": 1,
                "FTR": "D",
            },
        ]
    )
    feat = compute_elo_and_form(df)
    # first match both start at 1500
    assert feat.loc[0, "elo_home"] == 1500
    assert feat.loc[0, "elo_away"] == 1500
    # second match home Elo should have moved after first win
    assert feat.loc[1, "elo_home"] > 1500
