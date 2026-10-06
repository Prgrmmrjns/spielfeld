"""AZT1D (Khamesian et al. 2025, CC BY 4.0): download and build the glucose table.

    python scripts/azt1d.py

1. Downloads "AZT1D 2025.zip" (776 MB, Mendeley Data, doi 10.17632/gk9m674wcx.1)
   and unpacks it to datasets/azt1d/raw/.
2. Writes datasets/azt1d/azt1d_all_patients.parquet, one row per 5-minute step:
   CGM_0..23        glucose, the last 2 hours (CGM_23 is the newest)
   Insulin_0..23    active bolus insulin per step (units x absorption curve)
   Carbs_0..23      active carbohydrate per step (grams x absorption curve)
   hour, time       clock time of the step to predict (time = hour + minutes/60)
   target           glucose 1 hour ahead minus glucose at that step (mg/dL)
   subject_id       1..25 (subject 14 shares CGM and fingersticks in one column and is skipped)
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "datasets" / "azt1d"
RAW = DIR / "raw"
OUT = DIR / "azt1d_all_patients.parquet"
URL = "https://data.mendeley.com/public-files/datasets/gk9m674wcx/files/b02a20be-27c4-4dd0-8bb5-9171c66262fb/file_downloaded"
SKIP = {14}
LOOKBACK, AHEAD = 24, 12  # 5-minute steps: 2 h of history, 1 h ahead


def download() -> Path:
    """Fetch and unpack the raw subject CSVs. Returns the 'CGM Records' folder."""
    found = next(RAW.glob("**/CGM Records"), None)
    if found:
        return found
    RAW.mkdir(parents=True, exist_ok=True)
    zpath = DIR / "AZT1D 2025.zip"
    if not zpath.exists():
        with requests.get(URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(zpath, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(RAW)
    zpath.unlink()
    return next(RAW.glob("**/CGM Records"))


def _response(t: np.ndarray, onset: float, peak: float, decay: float) -> np.ndarray:
    """Absorption curve, scaled to a maximum of 1. Zero before `onset` and after onset + 8 peaks."""
    r = np.zeros_like(t, dtype=np.float32)
    m = (t >= onset) & (t <= onset + peak * 8)
    ta = t[m] - onset
    r[m] = ((ta / peak) ** decay) * np.exp(-decay * (ta / peak))
    return r / r.max() if r.max() > 0 else r


def _active(t_min: np.ndarray, amounts: np.ndarray, onset: float, peak: float, decay: float) -> np.ndarray:
    """Sum of every logged dose's absorption curve, evaluated at each row."""
    out = np.zeros(len(t_min), dtype=np.float32)
    for et in np.flatnonzero(amounts > 0):
        out += amounts[et] * _response(np.maximum(t_min - t_min[et], 0), onset, peak, decay)
    return out


def subject(path: Path, sid: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["EventDateTime"])
    df["glucose"] = df["CGM"].ffill()
    df["insulin"] = df["TotalBolusInsulinDelivered"].fillna(0)
    df["carbs"] = df["CarbSize"].fillna(0)
    df = df[["datetime", "glucose", "insulin", "carbs"]].dropna(subset=["glucose"]).sort_values("datetime").reset_index(drop=True)

    t_min = (df["datetime"] - df["datetime"].iloc[0]).dt.total_seconds().to_numpy() / 60
    ins = _active(t_min, df["insulin"].to_numpy(), onset=15, peak=45, decay=2.5)
    car = _active(t_min, df["carbs"].to_numpy(), onset=10, peak=35, decay=3)
    g = df["glucose"].to_numpy()
    n = len(df)
    idx = np.arange(LOOKBACK, n - AHEAD)  # step to predict
    win = idx[:, None] - LOOKBACK + np.arange(LOOKBACK)[None, :]

    cols = {f"CGM_{t}": g[win[:, t]] for t in range(LOOKBACK)}
    cols |= {f"Insulin_{t}": ins[win[:, t]] for t in range(LOOKBACK)}
    cols |= {f"Carbs_{t}": car[win[:, t]] for t in range(LOOKBACK)}
    cols["hour"] = df["datetime"].dt.hour.to_numpy()[idx]
    cols["time"] = cols["hour"] + df["datetime"].dt.minute.to_numpy()[idx] / 60.0
    cols["target"] = g[idx + AHEAD] - g[idx]
    cols["subject_id"] = sid
    return pd.DataFrame(cols)


def build(records: Path | None = None, out: Path = OUT) -> pd.DataFrame:
    records = records or download()
    parts = []
    for sid in range(1, 26):
        path = records / f"Subject {sid}" / f"Subject {sid}.csv"
        if sid in SKIP or not path.is_file():
            continue
        parts.append(subject(path, sid))
        print(f"  subject {sid}: {len(parts[-1])} rows")
    d = pd.concat(parts, ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(out, index=False)
    print(f"wrote {out} ({len(d)} rows)")
    return d


def load() -> pd.DataFrame:
    if not OUT.is_file():
        raise SystemExit(f"{OUT} is missing. Run: python scripts/azt1d.py")
    return pd.read_parquet(OUT)


if __name__ == "__main__":
    build()
