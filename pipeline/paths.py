from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
ARTIFACTS = DATA / "artifacts"
MODELS = DATA / "models"

for p in (RAW, PROCESSED, ARTIFACTS, MODELS):
    p.mkdir(parents=True, exist_ok=True)

# football-data.co.uk season codes → (openliga season year, label)
SEASONS = {
    "1920": {"openliga": 2019, "label": "2019/20"},
    "2021": {"openliga": 2020, "label": "2020/21"},
    "2122": {"openliga": 2021, "label": "2021/22"},
    "2223": {"openliga": 2022, "label": "2022/23"},
    "2324": {"openliga": 2023, "label": "2023/24"},
    "2425": {"openliga": 2024, "label": "2024/25"},
    "2526": {"openliga": 2025, "label": "2025/26"},
    "2627": {"openliga": 2026, "label": "2026/27"},
}

CURRENT_FD_SEASON = "2627"
CURRENT_OPENLIGA_SEASON = 2026
