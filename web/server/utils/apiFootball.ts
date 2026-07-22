const BASE = 'https://v3.football.api-sports.io'
export const LEAGUE_ID = 78

const ALIASES: Record<string, string[]> = {
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

export function norm(s: string) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .replace(/ü/g, 'u').replace(/ö/g, 'o').replace(/ä/g, 'a').replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

export function apiKey() {
  return process.env.API_FOOTBALL_KEY || process.env.APIFOOTBALL_KEY || process.env.API_SPORTS_KEY || ''
}

export async function apiFootball(path: string, params: Record<string, string | number> = {}) {
  const key = apiKey()
  if (!key) throw createError({ statusCode: 503, statusMessage: 'API_FOOTBALL_KEY not configured' })
  const url = new URL(BASE + path)
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v))
  const res = await fetch(url, { headers: { 'x-apisports-key': key } })
  if (!res.ok) throw createError({ statusCode: res.status, statusMessage: `API-Football ${path} failed` })
  return res.json() as Promise<any>
}

export function currentSeason() {
  const now = new Date()
  return now.getUTCMonth() >= 6 ? now.getUTCFullYear() : now.getUTCFullYear() - 1
}

export function resolveTeamId(name: string, teams: Array<{ id: number, name: string }>) {
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

export type XiPlayer = { id?: number, name?: string, number?: number, pos?: string }
export type XiSide = {
  source: 'confirmed' | 'last_xi' | 'unknown'
  formation: string | null
  players: XiPlayer[]
}

const lastXi = new Map<number, { formation: string | null, players: XiPlayer[], fixtureId: number }>()

export function rememberXi(teamId: number, formation: string | null, players: XiPlayer[], fixtureId: number) {
  if (teamId && players?.length) {
    lastXi.set(teamId, { formation, players, fixtureId })
  }
}

export function getLastXi(teamId: number | null): XiSide {
  if (!teamId || !lastXi.has(teamId)) {
    return { source: 'unknown', formation: null, players: [] }
  }
  const hit = lastXi.get(teamId)!
  return { source: 'last_xi', formation: hit.formation, players: hit.players }
}

export function parseSides(response: any[]) {
  return (response || []).map((side) => {
    const teamId = side?.team?.id as number
    const formation = side?.formation || null
    const players = (side?.startXI || []).map((x: any) => ({
      id: x.player?.id,
      name: x.player?.name,
      number: x.player?.number,
      pos: x.player?.pos
    })) as XiPlayer[]
    return { teamId, formation, players }
  })
}

/** Find most recent finished fixture for a team and load its starting XI into memory. */
export async function warmLastXiForTeam(teamId: number, fixtures: any[]) {
  if (!teamId || lastXi.has(teamId)) return
  const finished = fixtures
    .filter((row) => {
      const st = row.fixture?.status?.short
      if (!['FT', 'AET', 'PEN'].includes(st)) return false
      return row.teams?.home?.id === teamId || row.teams?.away?.id === teamId
    })
    .sort((a, b) => (b.fixture?.timestamp || 0) - (a.fixture?.timestamp || 0))

  for (const row of finished.slice(0, 3)) {
    const fid = row.fixture?.id
    if (!fid) continue
    try {
      const lu = await apiFootball('/fixtures/lineups', { fixture: fid })
      const sides = parseSides(lu.response || [])
      for (const s of sides) {
        if (s.players.length) rememberXi(s.teamId, s.formation, s.players, fid)
      }
      if (lastXi.has(teamId)) return
    } catch {
      // try older fixture
    }
  }
}

export async function buildLiveLineups(predictions: any[]) {
  if (!apiKey()) {
    return {
      provider: null as string | null,
      refreshed_at: new Date().toISOString(),
      note: 'Set API_FOOTBALL_KEY for live lineups',
      lineups: Object.fromEntries((predictions || []).map((p: any) => [String(p.match_id), p.lineups || null]))
    }
  }

  const season = currentSeason()
  const teamsRes = await apiFootball('/teams', { league: LEAGUE_ID, season })
  const teams = (teamsRes.response || []).map((r: any) => r.team)
  const fixturesRes = await apiFootball('/fixtures', { league: LEAGUE_ID, season })
  const fixtures = fixturesRes.response || []

  for (const p of predictions || []) {
    if (p.lineups?.home?.source === 'confirmed' && p.lineups.home.players?.length) {
      const homeId = resolveTeamId(p.home_team, teams)
      if (homeId) rememberXi(homeId, p.lineups.home.formation, p.lineups.home.players, p.lineups.api_fixture_id || 0)
    }
    if (p.lineups?.away?.source === 'confirmed' && p.lineups.away.players?.length) {
      const awayId = resolveTeamId(p.away_team, teams)
      if (awayId) rememberXi(awayId, p.lineups.away.formation, p.lineups.away.players, p.lineups.api_fixture_id || 0)
    }
  }

  const out: Record<string, any> = {}
  for (const p of predictions || []) {
    const homeId = resolveTeamId(p.home_team, teams)
    const awayId = resolveTeamId(p.away_team, teams)
    const datePrefix = String(p.date || '').slice(0, 10)
    const fx = fixtures.find((row: any) => {
      return homeId && awayId
        && row.teams?.home?.id === homeId
        && row.teams?.away?.id === awayId
        && (!datePrefix || String(row.fixture?.date || '').startsWith(datePrefix))
    })

    if (homeId) await warmLastXiForTeam(homeId, fixtures)
    if (awayId) await warmLastXiForTeam(awayId, fixtures)

    let home = getLastXi(homeId)
    let away = getLastXi(awayId)
    let fixtureId = fx?.fixture?.id || p.lineups?.api_fixture_id || null

    if (fx?.fixture?.id) {
      try {
        const lu = await apiFootball('/fixtures/lineups', { fixture: fx.fixture.id })
        const sides = parseSides(lu.response || [])
        for (const s of sides) {
          if (s.players.length) rememberXi(s.teamId, s.formation, s.players, fx.fixture.id)
          if (s.teamId === homeId && s.players.length) {
            home = { source: 'confirmed', formation: s.formation, players: s.players }
          }
          if (s.teamId === awayId && s.players.length) {
            away = { source: 'confirmed', formation: s.formation, players: s.players }
          }
        }
        fixtureId = fx.fixture.id
      } catch {
        // not published yet → keep last XI
      }
    }

    if (!home.players.length && p.lineups?.home?.players?.length) {
      home = {
        source: p.lineups.home.source || 'last_xi',
        formation: p.lineups.home.formation || null,
        players: p.lineups.home.players
      }
    }
    if (!away.players.length && p.lineups?.away?.players?.length) {
      away = {
        source: p.lineups.away.source || 'last_xi',
        formation: p.lineups.away.formation || null,
        players: p.lineups.away.players
      }
    }

    out[String(p.match_id)] = {
      api_fixture_id: fixtureId,
      home,
      away
    }
  }

  return {
    provider: 'api-football' as string | null,
    refreshed_at: new Date().toISOString(),
    season,
    note: undefined as string | undefined,
    lineups: out
  }
}
