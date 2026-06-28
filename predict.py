"""Predict international football fixtures with TabPFN on engineered features."""
import argparse
import os
import pandas as pd
import numpy as np
from collections import defaultdict
from tabpfn_client import TabPFNClassifier

TRAIN_START = pd.Timestamp("2021-01-01")
MAX_TRAIN = 10000
HOME_ADV = 65.0
DATA = "results.csv"
RAW_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
KO_START = pd.Timestamp("2026-06-28")
WC_IMPORTANCE = 60.0
KO_HOSTS = {"United States", "Mexico"}

# Round of 32 — confirmed bracket (Sportschau / results.csv, June 2026).
R32 = [
    (73, "2026-06-28", "South Africa", "Canada"),
    (74, "2026-06-29", "Germany", "Paraguay"),
    (75, "2026-06-29", "Netherlands", "Morocco"),
    (76, "2026-06-29", "Brazil", "Japan"),
    (77, "2026-06-30", "France", "Sweden"),
    (78, "2026-06-30", "Ivory Coast", "Norway"),
    (79, "2026-06-30", "Mexico", "Ecuador"),
    (80, "2026-07-01", "England", "DR Congo"),
    (81, "2026-07-01", "United States", "Bosnia and Herzegovina"),
    (82, "2026-07-01", "Belgium", "Senegal"),
    (83, "2026-07-02", "Portugal", "Croatia"),
    (84, "2026-07-02", "Spain", "Austria"),
    (85, "2026-07-02", "Switzerland", "Algeria"),
    (86, "2026-07-03", "Argentina", "Cape Verde"),
    (87, "2026-07-03", "Colombia", "Ghana"),
    (88, "2026-07-03", "Australia", "Egypt"),
]

LATER_ROUNDS = [
    [(89, "2026-07-04", "W74", "W77"), (90, "2026-07-04", "W73", "W75"),
     (91, "2026-07-05", "W76", "W78"), (92, "2026-07-05", "W79", "W80"),
     (93, "2026-07-06", "W83", "W84"), (94, "2026-07-06", "W81", "W82"),
     (95, "2026-07-07", "W86", "W88"), (96, "2026-07-07", "W85", "W87")],
    [(97, "2026-07-09", "W89", "W90"), (98, "2026-07-10", "W93", "W94"),
     (99, "2026-07-11", "W91", "W92"), (100, "2026-07-11", "W95", "W96")],
    [(101, "2026-07-14", "W97", "W98"), (102, "2026-07-15", "W99", "W100")],
    [(103, "2026-07-18", "L101", "L102")],
    [(104, "2026-07-19", "W101", "W102")],
]

KO_ROUND_NAMES = ["Round of 32", "Round of 16", "Quarter-final", "Semi-final", "Third place", "Final"]

# WC2026 squad totals (€m), source: Transfermarkt, June 2026.
SQUAD_VALUE = {
    "France": 1520.0, "England": 1360.0, "Spain": 1220.0, "Portugal": 1010.0,
    "Germany": 947.0, "Brazil": 928.2, "Argentina": 807.5, "Netherlands": 754.2,
    "Norway": 589.9, "Belgium": 547.5, "Ivory Coast": 522.1, "Senegal": 478.1,
    "Turkey": 473.7, "Morocco": 447.7, "Sweden": 406.08, "Croatia": 387.3,
    "United States": 385.65, "Ecuador": 368.7, "Uruguay": 359.3, "Switzerland": 332.5,
    "Colombia": 302.35, "Japan": 270.85, "Algeria": 256.9, "Austria": 245.2,
    "Ghana": 234.35, "Canada": 198.65, "Mexico": 191.85, "Czech Republic": 188.18,
    "Scotland": 170.25, "Paraguay": 153.65, "Bosnia and Herzegovina": 146.4,
    "DR Congo": 143.9, "South Korea": 139.05, "Egypt": 116.48, "Uzbekistan": 85.13,
    "Australia": 77.45, "Tunisia": 69.95, "Haiti": 55.9, "Cape Verde": 54.5,
    "South Africa": 49.25, "Saudi Arabia": 40.68, "Panama": 34.55, "New Zealand": 34.3,
    "Iran": 32.05, "Curaçao": 25.78, "Iraq": 21.2, "Jordan": 20.3, "Qatar": 19.93,
}
SQUAD_VALUE_DEFAULT = float(np.median(list(SQUAD_VALUE.values())))

FEATURES = [
    "elo_diff", "home_elo", "away_elo",
    "value_diff", "home_squad_value", "away_squad_value",
    "form5_diff", "form10_diff", "home_form5", "away_form5",
    "home_winrate", "away_winrate",
    "home_gf5", "away_gf5", "home_ga5", "away_ga5", "gd10_diff",
    "home_streak", "away_streak", "home_rest", "away_rest",
    "home_played", "away_played",
    "h2h_n", "h2h_home_winrate", "h2h_draw_rate", "h2h_gd",
    "neutral", "importance",
]


def squad_value(team):
    """Total squad market value in €m (Transfermarkt WC2026); median for unknown teams."""
    return SQUAD_VALUE.get(team, SQUAD_VALUE_DEFAULT)


def importance(t):
    """Map tournament name to an ELO K-factor weight; higher means bigger rating swings."""
    t = t.lower()
    if "world cup" in t and "qual" not in t:
        return 60.0
    if "confederations" in t:
        return 50.0
    if any(k in t for k in [
        "uefa euro", "copa am", "african cup", "asian cup",
        "gold cup", "nations league", "oceania nations"
        ]):
        return 45.0
    if "qualif" in t:
        return 35.0
    if "friendly" in t:
        return 20.0
    return 30.0


def load_data(refresh=False):
    """Load and lightly clean the results CSV, downloading it if missing or refresh=True."""
    if refresh or not os.path.exists(DATA):
        df = pd.read_csv(RAW_URL)
        df.to_csv(DATA, index=False)
    else:
        df = pd.read_csv(DATA)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["neutral"] = df["neutral"].astype(str).str.upper().eq("TRUE").astype(int)
    df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
    df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
    df["outcome"] = np.select(
        [df["home_score"] > df["away_score"], df["home_score"] < df["away_score"]],
        ["home_win", "away_win"], default="draw")
    df.loc[df["home_score"].isna(), "outcome"] = np.nan
    df["importance"] = df["tournament"].apply(importance)
    return df[df["date"] >= TRAIN_START].reset_index(drop=True)


def _team_feats(team, elo, res):
    """Return pre-match stats for a team from accumulated state."""
    r = res[team]
    if not r:
        return elo[team], 1.3, 1.3, 0.33, 1.0, 1.0, 0.0, 0.0, 0
    last5, last10 = r[-5:], r[-10:]
    streak = 0
    for p, *_ in reversed(r):
        if p < 1:
            break
        streak += 1
    return (elo[team],
            np.mean([p for p, *_ in last5]), np.mean([p for p, *_ in last10]),
            np.mean([w for *_, w in last10]),
            np.mean([g for _, g, _, _ in last5]), np.mean([a for _, _, a, _ in last5]),
            np.mean([g - a for _, g, a, _ in last10]), streak, len(r))


def _h2h_feats(home, away, h2h):
    m = h2h[tuple(sorted((home, away)))]
    if not m:
        return 0, 0.5, 0.25, 0.0
    n = len(m)
    return (n,
            sum(w == home for _, _, w in m) / n,
            sum(w == "draw" for _, _, w in m) / n,
            np.mean([g if h == home else -g for h, g, _ in m]))


def _feature_row(home, away, date, neutral, importance, elo, res, last_date, h2h):
    adj = HOME_ADV * (1 - neutral)
    he, hf5, hf10, hwr, hgf, hga, hgd, hstk, hn = _team_feats(home, elo, res)
    ae, af5, af10, awr, agf, aga, agd, astk, an = _team_feats(away, elo, res)
    nm, h2h_wr, h2h_dr, h2h_gd = _h2h_feats(home, away, h2h)
    hv, av = squad_value(home), squad_value(away)
    row = {
        "elo_diff": he + adj - ae, "home_elo": he, "away_elo": ae,
        "value_diff": hv - av, "home_squad_value": hv, "away_squad_value": av,
        "form5_diff": hf5 - af5, "form10_diff": hf10 - af10,
        "home_form5": hf5, "away_form5": af5,
        "home_winrate": hwr, "away_winrate": awr,
        "home_gf5": hgf, "away_gf5": agf, "home_ga5": hga, "away_ga5": aga,
        "gd10_diff": hgd - agd, "home_streak": hstk, "away_streak": astk,
        "home_rest": min((date - last_date[home]).days, 90) if home in last_date else 30,
        "away_rest": min((date - last_date[away]).days, 90) if away in last_date else 30,
        "home_played": hn, "away_played": an,
        "h2h_n": nm, "h2h_home_winrate": h2h_wr, "h2h_draw_rate": h2h_dr, "h2h_gd": h2h_gd,
    }
    if importance is not None:
        row["neutral"] = neutral
        row["importance"] = importance
    return row


def _elo_margin_multiplier(goal_diff):
    """FIFA-style goal-difference weight: bigger wins/losses move ELO more."""
    gd = abs(int(goal_diff))
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def _ko_result_scores(home, away, winner, proba_row, classes):
    """Synthetic KO scoreline; margin scales with prediction confidence."""
    hi = list(classes).index("home_win")
    ai = list(classes).index("away_win")
    margin = max(1, min(5, int(1 + abs(proba_row[hi] - proba_row[ai]) * 4)))
    if winner == home:
        return margin, 0
    return 0, margin


def _update_state(home, away, date, home_score, away_score, neutral, imp, elo, res, last_date, h2h):
    adj = HOME_ADV * (1 - neutral)
    he, ae = elo[home], elo[away]
    gd = int(home_score) - int(away_score)
    exp = 1 / (1 + 10 ** ((ae - he - adj) / 400))
    s = 1.0 if gd > 0 else (0.0 if gd < 0 else 0.5)
    delta = imp * _elo_margin_multiplier(gd) * (s - exp)
    elo[home] += delta
    elo[away] -= delta
    res[home].append((3 if gd > 0 else (1 if gd == 0 else 0), home_score, away_score, gd > 0))
    res[away].append((3 if gd < 0 else (1 if gd == 0 else 0), away_score, home_score, gd < 0))
    last_date[home] = last_date[away] = date
    h2h[tuple(sorted((home, away)))].append(
        (home, gd, home if gd > 0 else (away if gd < 0 else "draw")))


def _init_state():
    return (defaultdict(lambda: 1500.0), defaultdict(list), {}, defaultdict(list))


def _apply_result(home, away, date, home_score, away_score, neutral, imp, state):
    elo, res, last_date, h2h = state
    _update_state(home, away, date, home_score, away_score, neutral, imp, elo, res, last_date, h2h)


def build_state(df):
    """Replay all scored matches and return mutable feature state."""
    state = _init_state()
    elo, res, last_date, h2h = state
    for r in df.itertuples():
        if np.isnan(r.home_score):
            continue
        _update_state(r.home_team, r.away_team, r.date, r.home_score, r.away_score,
                      r.neutral, r.importance, elo, res, last_date, h2h)
    return state


def build_features(df):
    """One chronological pass: every feature uses only matches before kickoff."""
    elo, res, last_date, h2h = _init_state()
    rows = []
    for r in df.itertuples():
        rows.append(_feature_row(r.home_team, r.away_team, r.date, r.neutral, None,
                                 elo, res, last_date, h2h))
        if not np.isnan(r.home_score):
            _update_state(r.home_team, r.away_team, r.date, r.home_score, r.away_score,
                          r.neutral, r.importance, elo, res, last_date, h2h)
    return df.join(pd.DataFrame(rows, index=df.index))


def _ko_resolve(team, winners, losers):
    if team.startswith("W"):
        return winners[int(team[1:])]
    if team.startswith("L"):
        return losers[int(team[1:])]
    return team


def _ko_rounds():
    """Yield (round_name, fixtures) where each fixture is (match_id, date, home, away)."""
    yield KO_ROUND_NAMES[0], [(m, pd.Timestamp(d), h, a) for m, d, h, a in R32]
    for name, fixtures in zip(KO_ROUND_NAMES[1:], LATER_ROUNDS):
        yield name, [(m, pd.Timestamp(d), h, a) for m, d, h, a in fixtures]


def _ko_neutral(home):
    """KO fixtures are neutral except when USA or Mexico are the designated home team."""
    return 0 if home in KO_HOSTS else 1


def _ko_winner(home, away, pred, proba_row, classes):
    if pred != "draw":
        return home if pred == "home_win" else away
    hi, ai = list(classes).index("home_win"), list(classes).index("away_win")
    return home if proba_row[hi] >= proba_row[ai] else away


def predict_ko_bracket(clf, df=None):
    """Simulate the full WC2026 knockout bracket, updating state between rounds."""
    state = build_state(df if df is not None else load_data())
    winners, losers = {}, {}
    rows = []

    for round_name, fixtures in _ko_rounds():
        batch, meta = [], []
        for mid, date, home_ref, away_ref in fixtures:
            home = _ko_resolve(home_ref, winners, losers)
            away = _ko_resolve(away_ref, winners, losers)
            neutral = _ko_neutral(home)
            batch.append(_feature_row(home, away, date, neutral, WC_IMPORTANCE, *state))
            meta.append((mid, date, home, away, round_name, neutral))

        proba = clf.predict_proba(pd.DataFrame(batch)[FEATURES].values)
        for i, (mid, date, home, away, round_name, neutral) in enumerate(meta):
            pred = clf.classes_[proba[i].argmax()]
            winner = _ko_winner(home, away, pred, proba[i], clf.classes_)
            loser = away if winner == home else home
            winners[mid] = winner
            losers[mid] = loser
            hs, aws = _ko_result_scores(home, away, winner, proba[i], clf.classes_)
            _apply_result(home, away, date, hs, aws, neutral, WC_IMPORTANCE, state)
            rows.append({
                "match_id": mid, "round": round_name, "date": date,
                "home_team": home, "away_team": away, "predicted": pred,
                "p_home_win": proba[i, list(clf.classes_).index("home_win")],
                "p_draw": proba[i, list(clf.classes_).index("draw")],
                "p_away_win": proba[i, list(clf.classes_).index("away_win")],
                "predicted_winner": winner,
            })

    return pd.DataFrame(rows)


def train(pool):
    """Fit TabPFN on the feature matrix; ignore_pretraining_limits allows >1000 rows."""
    clf = TabPFNClassifier(ignore_pretraining_limits=True, random_state=42)
    clf.fit(pool[FEATURES].values, pool["outcome"].values)
    return clf


def main():
    """Train on recent matches and predict WC2026 knockout fixtures."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-download dataset from source")
    args = parser.parse_args()

    df = load_data(refresh=args.refresh)
    latest_date = df[df["date"].notna()]["date"].max()
    print(f"Latest game in dataset: {latest_date.date()}")
    print(f"Data freshness: {pd.Timestamp.now() - latest_date}")

    feats = build_features(df)
    played = feats[feats["outcome"].notna()]

    clf = train(played.tail(MAX_TRAIN))
    out = predict_ko_bracket(clf, df)
    out = out[["date", "home_team", "away_team", "predicted", "p_home_win", "p_draw", "p_away_win"]]

    out.to_csv("predictions.csv", index=False)

    print(f"\nWC2026 knockout ({len(out)} matches, from {KO_START.date()}) -> predictions.csv\n")
    for r in out.itertuples():
        print(f"  {r.date.date()}  {r.home_team:>20} vs {r.away_team:<20}  "
              f"-> {r.predicted:<9}  H {r.p_home_win:4.0%} | D {r.p_draw:4.0%} | A {r.p_away_win:4.0%}")


if __name__ == "__main__":
    main()
