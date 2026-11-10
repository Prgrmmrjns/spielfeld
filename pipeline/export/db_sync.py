"""Apply migrations and upsert artifacts into Neon Postgres when DATABASE_URL is set."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pipeline.paths import ARTIFACTS, ROOT

MIGRATIONS = ROOT / "db" / "migrations"


def _database_url() -> str | None:
    for key in ("DATABASE_URL_UNPOOLED", "DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING"):
        val = os.environ.get(key)
        if val:
            return val
    return None


def apply_migrations(conn) -> list[str]:
    applied = []
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              id text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        for path in sorted(MIGRATIONS.glob("*.sql")):
            mid = path.name
            cur.execute("SELECT 1 FROM schema_migrations WHERE id = %s", (mid,))
            if cur.fetchone():
                continue
            sql = path.read_text(encoding="utf-8")
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations (id) VALUES (%s)", (mid,))
            applied.append(mid)
    conn.commit()
    return applied


def upsert_artifacts(conn) -> dict:
    cur = conn.cursor()
    stats = {}

    forecasts = ARTIFACTS / "forecasts.json"
    if forecasts.exists():
        payload = json.loads(forecasts.read_text(encoding="utf-8"))
        cur.execute("DELETE FROM forecasts")
        for m in payload.get("matches", []):
            cur.execute(
                """
                INSERT INTO forecasts (
                  match_uid, ol_match_id, season_year, matchday, kickoff,
                  home_slug, away_slug, home_name, away_name,
                  p_home, p_draw, p_away, pick, drivers, is_current_matchday, payload
                ) VALUES (
                  %(match_uid)s, %(ol_match_id)s, %(season_year)s, %(matchday)s, %(kickoff)s,
                  %(home_slug)s, %(away_slug)s, %(home_display)s, %(away_display)s,
                  %(p_home)s, %(p_draw)s, %(p_away)s, %(pick)s, %(drivers)s::jsonb,
                  %(is_current_matchday)s, %(payload)s::jsonb
                )
                ON CONFLICT (match_uid) DO UPDATE SET
                  p_home = EXCLUDED.p_home,
                  p_draw = EXCLUDED.p_draw,
                  p_away = EXCLUDED.p_away,
                  pick = EXCLUDED.pick,
                  drivers = EXCLUDED.drivers,
                  payload = EXCLUDED.payload,
                  updated_at = now()
                """,
                {
                    **m,
                    "drivers": json.dumps(m.get("drivers") or []),
                    "payload": json.dumps(m),
                },
            )
        stats["forecasts"] = len(payload.get("matches", []))

    metrics = ARTIFACTS / "metrics.json"
    if metrics.exists():
        payload = json.loads(metrics.read_text(encoding="utf-8"))
        cur.execute(
            """
            INSERT INTO model_runs (kind, metrics)
            VALUES ('walk_forward', %s::jsonb)
            """,
            (json.dumps(payload),),
        )
        stats["model_runs"] = 1

    findings = ARTIFACTS / "ablation.json"
    if findings.exists():
        payload = json.loads(findings.read_text(encoding="utf-8"))
        cur.execute(
            """
            INSERT INTO findings_log (title, body)
            VALUES (%s, %s::jsonb)
            """,
            ("weekly_ablation", json.dumps(payload)),
        )
        stats["findings"] = 1

    impact = ARTIFACTS / "player_impact.json"
    if impact.exists():
        payload = json.loads(impact.read_text(encoding="utf-8"))
        cur.execute("DELETE FROM player_impacts")
        for row in payload.get("impacts", []):
            cur.execute(
                """
                INSERT INTO player_impacts (match_uid, player_id, player_name, team_slug, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    row["match_uid"],
                    row["player_id"],
                    row["player_name"],
                    row["team_slug"],
                    json.dumps(row),
                ),
            )
        stats["player_impacts"] = len(payload.get("impacts", []))

    track = ARTIFACTS / "track_record.json"
    if track.exists():
        payload = json.loads(track.read_text(encoding="utf-8"))
        cur.execute(
            """
            INSERT INTO track_record_snapshots (summary, matches)
            VALUES (%s::jsonb, %s::jsonb)
            """,
            (json.dumps(payload.get("summary") or {}), json.dumps(payload.get("matches") or [])),
        )
        stats["track_record"] = 1

    conn.commit()
    cur.close()
    return stats


def sync() -> dict:
    url = _database_url()
    if not url:
        return {"skipped": True, "reason": "DATABASE_URL not set"}
    import psycopg2

    conn = psycopg2.connect(url)
    try:
        applied = apply_migrations(conn)
        stats = upsert_artifacts(conn)
        return {"skipped": False, "migrations": applied, "upserted": stats}
    finally:
        conn.close()


if __name__ == "__main__":
    print(json.dumps(sync(), indent=2))
