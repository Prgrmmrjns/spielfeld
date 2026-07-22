"""Predict Bundesliga next-matchday outcomes with TabPFN on engineered features."""
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier

TRAIN_START = pd.Timestamp("2019-07-01")
MAX_TRAIN = 10000
HOME_ADV = 65.0
LEAGUE = "bl1"
CACHE = "bundesliga_results.csv"
API = "https://api.openligadb.de"
IMPORTANCE = 45.0
os.environ.setdefault("TABPFN_NO_BROWSER", "1")
os.environ.setdefault("TABPFN_CLIENT_NO_BROWSER", "1")


def load_dotenv(path=".env"):
    """Load KEY=VALUE pairs from a local .env without requiring python-dotenv."""
    p = Path(path)
    if not p.is_file():
        # Also accept a sibling workspace .env when running from a local clone.
        for candidate in (Path("/workspace/.env"), Path(__file__).resolve().parent / ".env"):
            if candidate.is_file():
                p = candidate
                break
        else:
            return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()
# tabpfn-client reads TABPFN_TOKEN; accept TABPFN_API_KEY as an alias.
if not os.getenv("TABPFN_TOKEN") and os.getenv("TABPFN_API_KEY"):
    os.environ["TABPFN_TOKEN"] = os.environ["TABPFN_API_KEY"]

# Approximate squad market values (€m). Unknown clubs use the median.
SQUAD_VALUE = {
    "FC Bayern München": 950.0,
    "Bayer 04 Leverkusen": 620.0,
    "Borussia Dortmund": 540.0,
    "RB Leipzig": 480.0,
    "VfB Stuttgart": 380.0,
    "Eintracht Frankfurt": 340.0,
    "VfL Wolfsburg": 260.0,
    "SC Freiburg": 220.0,
    "TSG Hoffenheim": 210.0,
    "Borussia Mönchengladbach": 200.0,
    "1. FC Union Berlin": 180.0,
    "SV Werder Bremen": 170.0,
    "1. FC Köln": 150.0,
    "1. FSV Mainz 05": 150.0,
    "FC Augsburg": 130.0,
    "Hamburger SV": 140.0,
    "FC Schalke 04": 120.0,
    "SC Paderborn 07": 55.0,
    "SV 07 Elversberg": 40.0,
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
]


def squad_value(team):
    return SQUAD_VALUE.get(team, SQUAD_VALUE_DEFAULT)


def _final_score(match):
    results = match.get("matchResults") or []
    end = next((r for r in results if r.get("resultTypeID") == 2), None)
    if end is None and results:
        end = max(results, key=lambda r: r.get("resultOrderID", 0))
    if end is None:
        return None, None
    return end.get("pointsTeam1"), end.get("pointsTeam2")


def _season_years(through=None):
    """Seasons to pull for training history (OpenLigaDB uses start year)."""
    now = pd.Timestamp.now()
    end = through if through is not None else (now.year if now.month >= 7 else now.year - 1)
    return list(range(2019, end + 1))


def fetch_season(season):
    url = f"{API}/getmatchdata/{LEAGUE}/{season}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def matches_to_frame(matches):
    rows = []
    for m in matches:
        hs, aws = _final_score(m)
        rows.append({
            "date": m.get("matchDateTimeUTC") or m.get("matchDateTime"),
            "home_team": m["team1"]["teamName"],
            "away_team": m["team2"]["teamName"],
            "home_score": hs,
            "away_score": aws,
            "neutral": 0,
            "match_id": m.get("matchID"),
            "matchday": (m.get("group") or {}).get("groupOrderID"),
            "matchday_name": (m.get("group") or {}).get("groupName"),
            "finished": bool(m.get("matchIsFinished")),
            "home_icon": m["team1"].get("teamIconUrl"),
            "away_icon": m["team2"].get("teamIconUrl"),
            "home_short": m["team1"].get("shortName") or m["team1"]["teamName"],
            "away_short": m["team2"].get("shortName") or m["team2"]["teamName"],
            "season": m.get("leagueSeason"),
        })
    return pd.DataFrame(rows)


def load_history(refresh=False):
    if not refresh and os.path.exists(CACHE):
        df = pd.read_csv(CACHE)
    else:
        frames = []
        for season in _season_years():
            try:
                frames.append(matches_to_frame(fetch_season(season)))
            except requests.HTTPError:
                continue
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        df.to_csv(CACHE, index=False)

    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    df = df.sort_values("date").reset_index(drop=True)
    df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
    df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
    df["outcome"] = np.select(
        [df["home_score"] > df["away_score"], df["home_score"] < df["away_score"]],
        ["home_win", "away_win"], default="draw")
    df.loc[df["home_score"].isna() | ~df["finished"].astype(bool), "outcome"] = np.nan
    return df[df["date"] >= TRAIN_START].reset_index(drop=True)


def fetch_current_group():
    r = requests.get(f"{API}/getcurrentgroup/{LEAGUE}", timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_next_matchday():
    """Return fixtures for the upcoming (or current unfinished) matchday."""
    group = fetch_current_group()
    order = int(group["groupOrderID"])
    season = int(pd.Timestamp.now().year if pd.Timestamp.now().month >= 7 else pd.Timestamp.now().year - 1)

    # Prefer the season that has the next unfinished match.
    next_match = requests.get(f"{API}/getnextmatchbyleagueshortcut/{LEAGUE}", timeout=30)
    next_match.raise_for_status()
    nm = next_match.json()
    if nm:
        season = int(nm.get("leagueSeason") or season)
        order = int((nm.get("group") or {}).get("groupOrderID") or order)

    matches = fetch_season_matchday(season, order)
    # If current group is fully finished, try the following matchday.
    if matches and all(m.get("matchIsFinished") for m in matches) and order < 34:
        nxt = fetch_season_matchday(season, order + 1)
        if nxt:
            order += 1
            matches = nxt

    meta = {
        "season": season,
        "matchday": order,
        "matchday_name": (matches[0].get("group") or {}).get("groupName") if matches else group.get("groupName"),
    }
    fixtures = matches_to_frame(matches)
    fixtures["date"] = pd.to_datetime(fixtures["date"], utc=True).dt.tz_localize(None)
    return meta, fixtures.sort_values("date").reset_index(drop=True)


def fetch_season_matchday(season, matchday):
    url = f"{API}/getmatchdata/{LEAGUE}/{season}/{matchday}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def _team_feats(team, elo, res):
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


def _feature_row(home, away, date, elo, res, last_date, h2h):
    he, hf5, hf10, hwr, hgf, hga, hgd, hstk, hn = _team_feats(home, elo, res)
    ae, af5, af10, awr, agf, aga, agd, astk, an = _team_feats(away, elo, res)
    nm, h2h_wr, h2h_dr, h2h_gd = _h2h_feats(home, away, h2h)
    hv, av = squad_value(home), squad_value(away)
    return {
        "elo_diff": he + HOME_ADV - ae, "home_elo": he, "away_elo": ae,
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


def _elo_margin_multiplier(goal_diff):
    gd = abs(int(goal_diff))
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def _update_state(home, away, date, home_score, away_score, elo, res, last_date, h2h):
    he, ae = elo[home], elo[away]
    gd = int(home_score) - int(away_score)
    exp = 1 / (1 + 10 ** ((ae - he - HOME_ADV) / 400))
    s = 1.0 if gd > 0 else (0.0 if gd < 0 else 0.5)
    delta = IMPORTANCE * _elo_margin_multiplier(gd) * (s - exp)
    elo[home] += delta
    elo[away] -= delta
    res[home].append((3 if gd > 0 else (1 if gd == 0 else 0), home_score, away_score, gd > 0))
    res[away].append((3 if gd < 0 else (1 if gd == 0 else 0), away_score, home_score, gd < 0))
    last_date[home] = last_date[away] = date
    h2h[tuple(sorted((home, away)))].append(
        (home, gd, home if gd > 0 else (away if gd < 0 else "draw")))


def _init_state():
    return (defaultdict(lambda: 1500.0), defaultdict(list), {}, defaultdict(list))


def build_state(df):
    elo, res, last_date, h2h = _init_state()
    for r in df.itertuples():
        if pd.isna(r.home_score) or pd.isna(r.away_score):
            continue
        _update_state(r.home_team, r.away_team, r.date, r.home_score, r.away_score,
                      elo, res, last_date, h2h)
    return elo, res, last_date, h2h


def build_features(df):
    elo, res, last_date, h2h = _init_state()
    rows = []
    for r in df.itertuples():
        rows.append(_feature_row(r.home_team, r.away_team, r.date, elo, res, last_date, h2h))
        if not pd.isna(r.home_score) and not pd.isna(r.away_score):
            _update_state(r.home_team, r.away_team, r.date, r.home_score, r.away_score,
                          elo, res, last_date, h2h)
    return df.join(pd.DataFrame(rows, index=df.index))


def train(pool):
    """Prefer TabPFN when authenticated; otherwise use a local gradient boosting model."""
    X, y = pool[FEATURES].values, pool["outcome"].values
    token = os.getenv("TABPFN_TOKEN") or os.getenv("TABPFN_API_KEY")
    if token:
        try:
            from tabpfn_client import TabPFNClassifier, set_access_token
            import tabpfn_client.constants as tabpfn_constants

            os.environ["TABPFN_TOKEN"] = token
            tabpfn_constants.TABPFN_TOKEN = token
            set_access_token(token)
            print("Training with TabPFN…")
            clf = TabPFNClassifier(ignore_pretraining_limits=True, random_state=42)
            clf.fit(X, y)
            clf.model_name_ = "TabPFN"
            return clf
        except Exception as exc:
            print(f"TabPFN unavailable ({exc}); falling back to HistGradientBoosting.")
    base = HistGradientBoostingClassifier(max_depth=5, learning_rate=0.06, max_iter=150, random_state=42)
    clf = CalibratedClassifierCV(base, method="isotonic", cv=3)
    clf.fit(X, y)
    clf.model_name_ = "HistGradientBoosting"
    return clf


def predict_matchday(clf, history, fixtures):
    state = build_state(history[history["outcome"].notna()])
    batch, meta = [], []
    for r in fixtures.itertuples():
        batch.append(_feature_row(r.home_team, r.away_team, r.date, *state))
        meta.append(r)

    proba = clf.predict_proba(pd.DataFrame(batch)[FEATURES].values)
    classes = list(clf.classes_)
    rows = []
    for i, r in enumerate(meta):
        pred = classes[int(proba[i].argmax())]
        rows.append({
            "match_id": int(r.match_id) if not pd.isna(r.match_id) else None,
            "date": r.date.isoformat(),
            "home_team": r.home_team,
            "away_team": r.away_team,
            "home_short": r.home_short,
            "away_short": r.away_short,
            "home_icon": r.home_icon,
            "away_icon": r.away_icon,
            "predicted": pred,
            "p_home_win": float(proba[i, classes.index("home_win")]),
            "p_draw": float(proba[i, classes.index("draw")]),
            "p_away_win": float(proba[i, classes.index("away_win")]),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-download Bundesliga history")
    parser.add_argument("--json", default="predictions.json", help="JSON output path")
    parser.add_argument("--csv", default="predictions.csv", help="CSV output path")
    args = parser.parse_args()

    history = load_history(refresh=args.refresh)
    played = history[history["outcome"].notna()]
    latest = played["date"].max() if len(played) else None
    print(f"Training matches: {len(played)}")
    if latest is not None:
        print(f"Latest finished game: {latest.date()}")

    meta, fixtures = fetch_next_matchday()
    print(f"Next matchday: {meta['matchday_name']} (Saison {meta['season']}/{meta['season'] + 1}) — {len(fixtures)} fixtures")

    feats = build_features(played)
    clf = train(feats.tail(MAX_TRAIN))
    rows = predict_matchday(clf, history, fixtures)
    model_name = getattr(clf, "model_name_", type(clf).__name__)

    out = pd.DataFrame(rows)
    out.to_csv(args.csv, index=False)
    payload = {
        "league": "Bundesliga",
        "season": f"{meta['season']}/{meta['season'] + 1}",
        "matchday": meta["matchday"],
        "matchday_name": meta["matchday_name"],
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "model": model_name,
        "train_matches": int(len(played)),
        "predictions": rows,
    }
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n{len(rows)} predictions -> {args.csv}, {args.json}\n")
    for r in rows:
        print(f"  {r['date'][:16]}  {r['home_team']:>24} vs {r['away_team']:<24}  "
              f"-> {r['predicted']:<9}  H {r['p_home_win']:4.0%} | D {r['p_draw']:4.0%} | A {r['p_away_win']:4.0%}")


if __name__ == "__main__":
    main()
