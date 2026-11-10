import { readFile } from "fs/promises";
import path from "path";

const ARTIFACT_DIR = path.join(process.cwd(), "public", "data");

async function readJson<T>(name: string): Promise<T> {
  const raw = await readFile(path.join(ARTIFACT_DIR, name), "utf8");
  return JSON.parse(raw) as T;
}

export type ForecastMatch = {
  match_uid: string;
  ol_match_id: number | null;
  season_year: number;
  matchday: number | null;
  kickoff: string;
  home_slug: string;
  away_slug: string;
  home_display: string;
  away_display: string;
  home_icon?: string | null;
  away_icon?: string | null;
  p_home: number;
  p_draw: number;
  p_away: number;
  pick: string;
  imp_home?: number | null;
  imp_draw?: number | null;
  imp_away?: number | null;
  elo_home?: number | null;
  elo_away?: number | null;
  elo_diff?: number | null;
  drivers: { feature: string; value: number; score: number }[];
  is_current_matchday?: boolean;
};

export type Forecasts = {
  generated_at: string;
  season_year: number;
  current_matchday: number | null;
  matches: ForecastMatch[];
};

export async function getForecasts() {
  return readJson<Forecasts>("forecasts.json");
}

export async function getMetrics() {
  return readJson<Record<string, unknown>>("metrics.json");
}

export async function getAblation() {
  return readJson<Record<string, unknown>>("ablation.json");
}

export async function getShap() {
  return readJson<{ features: { feature: string; mean_abs_shap: number }[]; n_samples: number }>(
    "shap_importance.json"
  );
}

export async function getPlayerImpact() {
  return readJson<{
    method: string;
    impacts: Record<string, unknown>[];
    leaderboard: Record<string, unknown>[];
    players: Record<string, unknown>[];
  }>("player_impact.json");
}

export async function getTrackRecord() {
  return readJson<{
    summary: { n: number; accuracy: number; by_season: Record<string, number> };
    matches: Record<string, unknown>[];
  }>("track_record.json");
}

export async function getTeams() {
  return readJson<
    { slug: string; name: string; short_name?: string; icon_url?: string; ol_team_id?: number }[]
  >("teams.json");
}

export function pct(p: number | null | undefined, digits = 0) {
  if (p == null || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(digits)}%`;
}

export function formatKickoff(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Berlin",
  });
}
