import predictions from '../data/predictions.json'
import { buildLiveLineups } from '../utils/apiFootball'

/**
 * Vercel Cron + manual live lineup refresh.
 * Returns fresh API-Football XIs (confirmed, else last starting XI).
 * Static JSON is rewritten at deploy time by web/scripts/refresh-lineups.mjs
 * and via the GitHub Action full predict refresh.
 */
export default defineEventHandler(async () => {
  const live = await buildLiveLineups(predictions.predictions || [])
  const matches = (predictions.predictions || []).map((m: any) => {
    const row = live.lineups?.[String(m.match_id)]
    if (!row) return { match_id: m.match_id, home_team: m.home_team, away_team: m.away_team, lineups: m.lineups || null }
    return {
      match_id: m.match_id,
      home_team: m.home_team,
      away_team: m.away_team,
      lineups: row
    }
  })
  return {
    ok: true,
    provider: live.provider,
    refreshed_at: live.refreshed_at,
    season: live.season,
    note: live.note,
    match_count: matches.length,
    matches
  }
})
