#!/usr/bin/env node
/**
 * Deploy-time lineup refresh via API-Football.
 * Updates starting XIs in predictions JSON (confirmed, else last XI).
 *
 * Env: API_FOOTBALL_KEY (or APIFOOTBALL_KEY)
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '../..')
const web = join(__dirname, '..')
const BASE = 'https://v3.football.api-sports.io'
const LEAGUE_ID = 78

const KEY = process.env.API_FOOTBALL_KEY || process.env.APIFOOTBALL_KEY || process.env.API_SPORTS_KEY
if (!KEY) {
  console.log('refresh-lineups: no API_FOOTBALL_KEY — skipping')
  process.exit(0)
}

const targets = [
  join(web, 'app/data/predictions.json'),
  join(web, 'server/data/predictions.json'),
  join(web, 'public/data/predictions.json'),
  join(root, 'predictions.json')
].filter(existsSync)

if (!targets.length) {
  console.log('refresh-lineups: no predictions.json found — skipping')
  process.exit(0)
}

const ALIASES = {
  'fc bayern munchen': ['bayern munich', 'bayern'],
  'borussia monchengladbach': ['monchengladbach', 'gladbach'],
  '1 fsv mainz 05': ['mainz', 'mainz 05'],
  '1 fc union berlin': ['union berlin'],
  '1 fc koln': ['fc koln', 'cologne'],
  'bayer 04 leverkusen': ['bayer leverkusen', 'leverkusen'],
  'borussia dortmund': ['dortmund'],
  'eintracht frankfurt': ['frankfurt'],
  'rb leipzig': ['leipzig'],
  'vfb stuttgart': ['stuttgart'],
  'sc freiburg': ['freiburg'],
  'tsg hoffenheim': ['hoffenheim', '1899 hoffenheim'],
  'sv werder bremen': ['werder bremen'],
  'fc augsburg': ['augsburg'],
  'hamburger sv': ['hamburg', 'hsv'],
  'fc schalke 04': ['schalke'],
  'sc paderborn 07': ['paderborn'],
  'sv 07 elversberg': ['elversberg'],
  'vfl wolfsburg': ['wolfsburg']
}

function norm(s) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .replace(/ü/g, 'u').replace(/ö/g, 'o').replace(/ä/g, 'a').replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

async function api(path, params = {}) {
  const url = new URL(BASE + path)
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v))
  const res = await fetch(url, { headers: { 'x-apisports-key': KEY } })
  if (!res.ok) throw new Error(`${path} ${res.status}`)
  return res.json()
}

function resolveTeamId(name, teams) {
  const n = norm(name)
  for (const t of teams) {
    const tn = norm(t.name)
    if (tn === n || tn.includes(n) || n.includes(tn)) return t.id
  }
  for (const [canon, aliases] of Object.entries(ALIASES)) {
    const bag = [canon, ...aliases].map(norm)
    if (!bag.includes(n) && !bag.some(a => n.includes(a) || a.includes(n))) continue
    for (const t of teams) {
      const tn = norm(t.name)
      if (bag.some(a => tn.includes(a) || a.includes(tn))) return t.id
    }
  }
  return null
}

function parseLineupSide(side) {
  return {
    team_id: side?.team?.id,
    formation: side?.formation || null,
    players: (side?.startXI || []).map(x => ({
      id: x.player?.id,
      name: x.player?.name,
      number: x.player?.number,
      pos: x.player?.pos
    })),
    substitutes: (side?.substitutes || []).map(x => ({
      id: x.player?.id,
      name: x.player?.name,
      number: x.player?.number,
      pos: x.player?.pos
    }))
  }
}

async function fetchLastXi(teamId, fixtures, cache) {
  if (!teamId) return null
  if (cache.last_xi?.[String(teamId)]?.players?.length) {
    return cache.last_xi[String(teamId)]
  }
  const finished = fixtures
    .filter((row) => {
      const st = row.fixture?.status?.short
      if (!['FT', 'AET', 'PEN'].includes(st)) return false
      return row.teams?.home?.id === teamId || row.teams?.away?.id === teamId
    })
    .sort((a, b) => (b.fixture?.timestamp || 0) - (a.fixture?.timestamp || 0))

  for (const row of finished.slice(0, 4)) {
    const fid = row.fixture?.id
    if (!fid) continue
    try {
      const lu = await api('/fixtures/lineups', { fixture: fid })
      const sides = (lu.response || []).map(parseLineupSide)
      cache.lineups[String(fid)] = sides.map(s => ({
        team_id: s.team_id,
        formation: s.formation,
        startXI: s.players
      }))
      for (const s of sides) {
        if (s.team_id && s.players.length) {
          cache.last_xi[String(s.team_id)] = {
            fixture_id: fid,
            formation: s.formation,
            players: s.players,
            source: 'confirmed'
          }
        }
      }
      if (cache.last_xi[String(teamId)]?.players?.length) {
        return cache.last_xi[String(teamId)]
      }
    } catch {
      // try older
    }
  }
  return null
}

async function main() {
  const season = new Date().getUTCMonth() >= 6 ? new Date().getUTCFullYear() : new Date().getUTCFullYear() - 1
  const payload = JSON.parse(readFileSync(targets[0], 'utf8'))
  const teamsRes = await api('/teams', { league: LEAGUE_ID, season })
  const teams = (teamsRes.response || []).map(r => r.team)
  const fixturesRes = await api('/fixtures', { league: LEAGUE_ID, season })
  const fixtures = fixturesRes.response || []

  const cachePath = join(root, 'api_football_cache.json')
  const cache = existsSync(cachePath)
    ? JSON.parse(readFileSync(cachePath, 'utf8'))
    : { last_xi: {}, lineups: {} }
  cache.last_xi ||= {}
  cache.lineups ||= {}

  for (const pred of payload.predictions || []) {
    const hid = resolveTeamId(pred.home_team, teams)
    const aid = resolveTeamId(pred.away_team, teams)
    const datePrefix = String(pred.date || '').slice(0, 10)
    const fx = fixtures.find((row) => {
      const homeOk = hid && row.teams?.home?.id === hid
      const awayOk = aid && row.teams?.away?.id === aid
      const dateOk = !datePrefix || String(row.fixture?.date || '').startsWith(datePrefix)
      return homeOk && awayOk && dateOk
    })

    let homeSide = null
    let awaySide = null
    let sourceHome = 'last_xi'
    let sourceAway = 'last_xi'

    if (fx?.fixture?.id) {
      try {
        const lu = await api('/fixtures/lineups', { fixture: fx.fixture.id })
        const sides = (lu.response || []).map(parseLineupSide)
        cache.lineups[String(fx.fixture.id)] = sides.map(s => ({
          team_id: s.team_id,
          formation: s.formation,
          startXI: s.players
        }))
        for (const s of sides) {
          if (s.team_id === hid && s.players.length) {
            homeSide = s
            sourceHome = 'confirmed'
            cache.last_xi[String(hid)] = {
              fixture_id: fx.fixture.id,
              formation: s.formation,
              players: s.players,
              source: 'confirmed'
            }
          }
          if (s.team_id === aid && s.players.length) {
            awaySide = s
            sourceAway = 'confirmed'
            cache.last_xi[String(aid)] = {
              fixture_id: fx.fixture.id,
              formation: s.formation,
              players: s.players,
              source: 'confirmed'
            }
          }
        }
      } catch {
        // lineups not published yet
      }
    }

    if (!homeSide?.players?.length) {
      const last = await fetchLastXi(hid, fixtures, cache)
      if (last?.players?.length) {
        homeSide = { team_id: hid, formation: last.formation, players: last.players }
        sourceHome = 'last_xi'
      }
    }
    if (!awaySide?.players?.length) {
      const last = await fetchLastXi(aid, fixtures, cache)
      if (last?.players?.length) {
        awaySide = { team_id: aid, formation: last.formation, players: last.players }
        sourceAway = 'last_xi'
      }
    }

    pred.lineups = {
      api_fixture_id: fx?.fixture?.id || null,
      home: {
        source: homeSide?.players?.length ? sourceHome : 'unknown',
        formation: homeSide?.formation || null,
        players: homeSide?.players || [],
        strength: pred.lineups?.home?.strength ?? null
      },
      away: {
        source: awaySide?.players?.length ? sourceAway : 'unknown',
        formation: awaySide?.formation || null,
        players: awaySide?.players || [],
        strength: pred.lineups?.away?.strength ?? null
      }
    }
    console.log(`XI ${pred.home_short} vs ${pred.away_short}: ${pred.lineups.home.source}/${pred.lineups.away.source}`)
  }

  payload.lineups_provider = 'api-football'
  payload.lineups_refreshed_at = new Date().toISOString()
  const text = JSON.stringify(payload, null, 2)
  for (const t of targets) writeFileSync(t, text)
  writeFileSync(cachePath, JSON.stringify(cache, null, 2))
  console.log(`refresh-lineups: updated ${targets.length} prediction files`)
}

main().catch((err) => {
  console.error('refresh-lineups failed:', err)
  process.exit(0) // do not fail deploy
})
