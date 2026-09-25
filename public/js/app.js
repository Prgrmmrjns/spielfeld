(() => {
  const state = {
    data: JSON.parse(document.getElementById('payload-data').textContent),
    selectedId: null,
    lab: null,
    mode: 'board', // board | shap
    globalBoost: 0,
  }

  if (state.data.task === 'best_xi') {
    document.querySelectorAll('[data-mode="shap"]').forEach(el => { el.hidden = true })
    const impact = document.getElementById('live-impact')
    if (impact) impact.hidden = true
  }

  const modal = document.getElementById('modal')
  const stamp = document.getElementById('lineups-stamp')

  const DEFAULT_SENS = {
    home_strength: { p_home_win: 0.028, p_draw: -0.01, p_away_win: -0.018 },
    away_strength: { p_home_win: -0.024, p_draw: -0.008, p_away_win: 0.032 },
  }

  function sourceLabel(source) {
    if (source === 'confirmed') return 'Confirmed XI'
    if (source === 'last_xi') return 'Last starting XI'
    if (source === 'squad_estimate') return 'Squad estimate'
    if (source === 'wiki_squad') return 'Wikipedia squad (2025–27)'
    if (source === 'squad_2026') return 'Squad 2025–27'
    if (source === 'predicted') return 'Predicted XI'
    return 'XI pending'
  }

  function xiShort(source) {
    if (source === 'confirmed') return 'confirmed'
    if (source === 'last_xi') return 'last XI'
    if (source === 'squad_estimate') return 'squad est.'
    if (source === 'wiki_squad') return 'wiki 25–27'
    if (source === 'squad_2026') return 'squad 25–27'
    if (source === 'predicted') return 'predicted'
    return 'pending'
  }

  function tipLabel(match) {
    if (match.best_xi?.home?.summary || match.best_xi?.away?.summary) return 'Best XI'
    if (match.predicted === 'home_win') return match.home_short
    if (match.predicted === 'away_win') return match.away_short
    return 'Draw'
  }

  function pct(p) {
    return Math.round((Number(p) || 0) * 100)
  }

  function ppLabel(delta) {
    const pp = (Number(delta) || 0) * 100
    if (Math.abs(pp) < 0.05) return '0pp'
    const abs = Math.abs(pp)
    const body = abs >= 1 ? String(Math.round(pp)) : pp.toFixed(1)
    return `${pp >= 0 ? '+' : ''}${body}pp`
  }

  function clamp01(x) {
    return Math.max(0, Math.min(1, x))
  }

  function renormalize(h, d, a) {
    const s = h + d + a
    if (s <= 0) return { p_home_win: 1 / 3, p_draw: 1 / 3, p_away_win: 1 / 3 }
    return { p_home_win: h / s, p_draw: d / s, p_away_win: a / s }
  }

  function formatStamp(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    return new Intl.DateTimeFormat('en-GB', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Berlin',
    }).format(d)
  }

  function updateStamp(iso) {
    const label = formatStamp(iso || state.data.lineups_refreshed_at || state.data.generated_at)
    stamp.textContent = label ? `Lineups ${label}` : ''
  }

  function updateXiLabels() {
    for (const match of state.data.predictions || []) {
      const btn = document.querySelector(`[data-match-id="${match.match_id}"]`)
      if (!btn) continue
      const el = btn.querySelector('[data-xi-label]')
      if (!el) continue
      const h = match.lineups?.home?.source
      const a = match.lineups?.away?.source
      if (!h && !a) { el.hidden = true; continue }
      el.hidden = false
      el.textContent = `XI ${xiShort(h)} · ${xiShort(a)}`
    }
  }

  function parseFormation(formation) {
    if (!formation) return null
    const parts = String(formation).split(/[-–]/).map(n => parseInt(n, 10)).filter(n => n > 0)
    return parts.length ? parts : null
  }

  function posBucket(pos) {
    const p = (pos || '').toUpperCase()
    if (p.startsWith('G')) return 'G'
    if (p.startsWith('D')) return 'D'
    if (p.startsWith('M')) return 'M'
    if (p.startsWith('F') || p.startsWith('A')) return 'F'
    return 'M'
  }

  /** Place players on a 0–1 pitch half using API grid or formation heuristic. */
  function layoutPlayers(players, formation, side) {
    const list = (players || []).map((p, i) => ({ ...p, _i: i }))
    const withGrid = list.filter(p => p.grid && String(p.grid).includes(':'))
    let placed
    if (withGrid.length >= Math.min(8, list.length)) {
      placed = list.map(p => {
        if (!p.grid || !String(p.grid).includes(':')) {
          return { ...p, x: 0.5, y: side === 'home' ? 0.2 : 0.8 }
        }
        const [row, col] = String(p.grid).split(':').map(Number)
        return { ...p, _row: row, _col: col }
      })
      const rows = {}
      for (const p of placed) {
        if (p._row == null) continue
        ;(rows[p._row] ||= []).push(p)
      }
      const rowKeys = Object.keys(rows).map(Number).sort((a, b) => a - b)
      const maxRow = rowKeys[rowKeys.length - 1] || 1
      for (const r of rowKeys) {
        const group = rows[r].sort((a, b) => a._col - b._col)
        group.forEach((p, idx) => {
          const depth = (r - 1) / Math.max(maxRow - 1, 1) // 0 = GK line
          // Home attacks up (bottom→top), away attacks down (top→bottom)
          const yHalf = 0.06 + depth * 0.38
          p.y = side === 'home' ? 1 - yHalf : yHalf
          p.x = group.length === 1 ? 0.5 : (idx + 1) / (group.length + 1)
        })
      }
      for (const p of placed) {
        if (p.x == null) { p.x = 0.5; p.y = side === 'home' ? 0.75 : 0.25 }
      }
    } else {
      const buckets = { G: [], D: [], M: [], F: [] }
      for (const p of list) buckets[posBucket(p.pos)].push(p)
      const lines = parseFormation(formation)
      const layers = [{ key: 'G', players: buckets.G }]
      if (lines) {
        const field = [...buckets.D, ...buckets.M, ...buckets.F]
        let cursor = 0
        for (const n of lines) {
          layers.push({ key: 'L', players: field.slice(cursor, cursor + n) })
          cursor += n
        }
        if (cursor < field.length) layers.push({ key: 'L', players: field.slice(cursor) })
      } else {
        layers.push({ key: 'D', players: buckets.D })
        layers.push({ key: 'M', players: buckets.M })
        layers.push({ key: 'F', players: buckets.F })
      }
      const active = layers.filter(l => l.players.length)
      placed = []
      active.forEach((layer, li) => {
        const depth = active.length === 1 ? 0.2 : li / (active.length - 1)
        const yHalf = 0.06 + depth * 0.38
        const y = side === 'home' ? 1 - yHalf : yHalf
        layer.players.forEach((p, idx) => {
          placed.push({
            ...p,
            x: layer.players.length === 1 ? 0.5 : (idx + 1) / (layer.players.length + 1),
            y,
          })
        })
      })
    }
    return placed
  }

  function surname(name) {
    if (!name) return '—'
    const parts = String(name).trim().split(/\s+/)
    return parts[parts.length - 1].slice(0, 9)
  }

  function labView(match) {
    return {
      ...match,
      lineups: {
        ...match.lineups,
        home: { ...match.lineups?.home, players: state.lab.home },
        away: { ...match.lineups?.away, players: state.lab.away },
      },
    }
  }

  function tipFromProbs(match, probs) {
    const h = probs.p_home_win, d = probs.p_draw, a = probs.p_away_win
    if (h >= d && h >= a) return match.home_short
    if (a >= d && a >= h) return match.away_short
    return 'Draw'
  }

  function applyBoostToMatch(match, boost, extraHome = 0, extraAway = 0) {
    const base = {
      p_home_win: match.p_home_win,
      p_draw: match.p_draw,
      p_away_win: match.p_away_win,
    }
    const dHome = extraHome + boost
    const dAway = extraAway - boost * 0.35
    let probs = applyStrengthDelta(match, dHome, dAway)
    if (boost) {
      const feat = match.features || {}
      const overrides = {}
      if (feat.xi_strength_diff != null) overrides.xi_strength_diff = feat.xi_strength_diff + boost
      if (feat.home_xi_strength != null) overrides.home_xi_strength = feat.home_xi_strength + boost
      if (Object.keys(overrides).length) {
        const shapProbs = estimateFromFeatures(match, overrides)
        probs = renormalize(
          (probs.p_home_win + shapProbs.p_home_win) / 2,
          (probs.p_draw + shapProbs.p_draw) / 2,
          (probs.p_away_win + shapProbs.p_away_win) / 2,
        )
      }
    }
    return { base, probs, dHome, dAway, boost }
  }

  function computeWhatIf(match) {
    const lab = state.lab
    const baseHome = strengthOf(match.lineups?.home?.players)
    const baseAway = strengthOf(match.lineups?.away?.players)
    const boost = state.mode === 'shap' ? (Number(state.globalBoost) || 0) : 0
    const extraHome = strengthOf(lab?.home) - baseHome
    const extraAway = strengthOf(lab?.away) - baseAway
    return applyBoostToMatch(match, boost, extraHome, extraAway)
  }

  function renderPitch(match) {
    const home = layoutPlayers(match.lineups?.home?.players, match.lineups?.home?.formation, 'home')
    const away = layoutPlayers(match.lineups?.away?.players, match.lineups?.away?.formation, 'away')
    const dots = [
      ...home.map(p => ({ ...p, side: 'home' })),
      ...away.map(p => ({ ...p, side: 'away' })),
    ]
    if (!dots.length) {
      return `<div class="empty-inline">No starting XI to plot yet.</div>`
    }
    const hf = match.lineups?.home?.formation || '—'
    const af = match.lineups?.away?.formation || '—'
    const sel = state.lab?.selectedStarterId
    const justIn = state.lab?.justInId
    const pickMode = sel == null
    return `
      <div class="pitch-block">
        <div class="pitch-meta">
          <span>${match.home_short} <em>${hf}</em></span>
          <span class="pitch-vs">${pickMode ? 'tap a player' : 'replacement next →'}</span>
          <span><em>${af}</em> ${match.away_short}</span>
        </div>
        <div class="pitch ${pickMode ? 'pick-out' : 'pick-in'}" role="img" aria-label="Starting elevens on the pitch">
          <div class="pitch-grass"></div>
          <div class="pitch-mark center-circle"></div>
          <div class="pitch-mark halfway"></div>
          <div class="pitch-mark box top"></div>
          <div class="pitch-mark box bottom"></div>
          <div class="pitch-mark spot top"></div>
          <div class="pitch-mark spot bottom"></div>
          ${dots.map((p, i) => {
            const selected = sel != null && p.id === sel
            const incoming = justIn != null && p.id === justIn
            const dim = sel != null && !selected
            return `
            <button type="button" class="dot ${p.side}${selected ? ' selected' : ''}${incoming ? ' just-in' : ''}${dim ? ' dim' : ''}${pickMode ? ' tappable' : ''}"
              data-side="${p.side}" data-id="${p.id ?? ''}" data-idx="${p._i}"
              style="left:${(p.x * 100).toFixed(2)}%;top:${(p.y * 100).toFixed(2)}%;animation-delay:${(i * 0.02).toFixed(2)}s"
              title="${p.name || ''}${p.strength != null ? ` · str ${Number(p.strength).toFixed(2)}` : ''}">
              <span class="dot-num">${p.number != null ? p.number : ''}</span>
              <span class="dot-name">${surname(p.name)}</span>
            </button>`
          }).join('')}
        </div>
      </div>`
  }

  function strengthOf(players) {
    return (players || []).reduce((s, p) => s + (Number(p.strength) || 0), 0)
  }

  function hasStrength(players) {
    return (players || []).some(p => p.strength != null && Number(p.strength) > 0)
  }

  function sensitivity(match) {
    const s = match.xi_sensitivity
    const h = s?.home_strength
    const alive = h && (Math.abs(h.p_home_win) + Math.abs(h.p_draw) + Math.abs(h.p_away_win) > 1e-6)
    if (s && alive) return s
    return {
      delta: s?.delta || 1,
      home_strength: DEFAULT_SENS.home_strength,
      away_strength: DEFAULT_SENS.away_strength,
    }
  }

  function applyStrengthDelta(match, dHome, dAway) {
    const sens = sensitivity(match)
    const scaleH = dHome / (sens.delta || 1)
    const scaleA = dAway / (sens.delta || 1)
    const hs = sens.home_strength
    const as = sens.away_strength
    let h = match.p_home_win + hs.p_home_win * scaleH + as.p_home_win * scaleA
    let d = match.p_draw + hs.p_draw * scaleH + as.p_draw * scaleA
    let a = match.p_away_win + hs.p_away_win * scaleH + as.p_away_win * scaleA
    return renormalize(clamp01(h), clamp01(d), clamp01(a))
  }

  function shapMap(match) {
    const m = {}
    for (const f of match.explanation?.top_features || []) m[f.feature] = f
    return m
  }

  function estimateFromFeatures(match, overrides) {
    // Local linear approx from shapiq contributions on the tipped class, then reshape probs.
    const tip = match.predicted
    const shap = shapMap(match)
    let tipP = tip === 'home_win' ? match.p_home_win : tip === 'away_win' ? match.p_away_win : match.p_draw
    for (const [feat, newVal] of Object.entries(overrides)) {
      const oldVal = Number(match.features?.[feat])
      if (!Number.isFinite(oldVal) || Math.abs(oldVal) < 1e-9) continue
      const sv = shap[feat]?.shap
      if (sv == null) continue
      tipP += sv * ((Number(newVal) - oldVal) / Math.abs(oldVal))
    }
    tipP = clamp01(tipP)
    const others = 1 - tipP
    if (tip === 'home_win') {
      const rest = match.p_draw + match.p_away_win || 1
      return renormalize(tipP, others * (match.p_draw / rest), others * (match.p_away_win / rest))
    }
    if (tip === 'away_win') {
      const rest = match.p_home_win + match.p_draw || 1
      return renormalize(others * (match.p_home_win / rest), others * (match.p_draw / rest), tipP)
    }
    const rest = match.p_home_win + match.p_away_win || 1
    return renormalize(others * (match.p_home_win / rest), tipP, others * (match.p_away_win / rest))
  }

  function playerKey(p) {
    return p.id != null ? `id:${p.id}` : `n:${p.name}`
  }

  function arrangeIntoFormation(players, formation) {
    const lines = parseFormation(formation) || [4, 3, 3]
    const need = { G: 1, D: lines[0] || 4, M: 0, F: 0 }
    need.M = (lines.slice(1, -1).reduce((s, n) => s + n, 0)) || 3
    need.F = lines[lines.length - 1] || 2
    if (need.D + need.M + need.F !== 10) need.M = Math.max(0, 10 - need.D - need.F)
    const byPos = { G: [], D: [], M: [], F: [] }
    for (const p of players) byPos[posBucket(p.pos)].push(p)
    for (const k of Object.keys(byPos)) {
      byPos[k].sort((a, b) => (Number(b.strength) || 0) - (Number(a.strength) || 0))
    }
    const arranged = []
    const used = new Set()
    for (const [pos, n] of [['G', need.G], ['D', need.D], ['M', need.M], ['F', need.F]]) {
      for (const p of byPos[pos]) {
        if (arranged.length >= 11) break
        if (used.has(playerKey(p))) continue
        if (arranged.filter(x => posBucket(x.pos) === pos).length >= n) continue
        arranged.push(p)
        used.add(playerKey(p))
      }
    }
    const rest = players
      .filter(p => !used.has(playerKey(p)))
      .sort((a, b) => (Number(b.strength) || 0) - (Number(a.strength) || 0))
    while (arranged.length < 11 && rest.length) {
      const p = rest.shift()
      arranged.push(p)
      used.add(playerKey(p))
    }
    return arranged.slice(0, 11)
  }

  function bestXi(match, side) {
    const meta = sideMeta(match, side)
    const current = state.lab?.[side] || meta.players || []
    const pool = [...current, ...(meta.pool || [])]
    if (!hasStrength(pool)) return null
    const uniq = []
    const seen = new Set()
    for (const p of pool) {
      const key = playerKey(p)
      if (seen.has(key)) continue
      seen.add(key)
      uniq.push(p)
    }
    const gks = uniq.filter(p => posBucket(p.pos) === 'G')
      .sort((a, b) => (Number(b.strength) || 0) - (Number(a.strength) || 0))
    const outfield = uniq.filter(p => posBucket(p.pos) !== 'G')
      .sort((a, b) => (Number(b.strength) || 0) - (Number(a.strength) || 0))
    if (!gks.length || outfield.length < 10) return null
    // Strongest GK + strongest 10 outfield (not locked to weak formation fillers)
    const raw = [gks[0], ...outfield.slice(0, 10)]
    const chosen = arrangeIntoFormation(raw, meta.formation)
    const curKeys = new Set(current.map(playerKey))
    const chosenKeys = new Set(chosen.map(playerKey))
    const incoming = chosen.filter(p => !curKeys.has(playerKey(p)))
    const outgoing = current.filter(p => !chosenKeys.has(playerKey(p)))
    return {
      players: chosen,
      changed: incoming.length > 0,
      delta: strengthOf(chosen) - strengthOf(current),
      incoming,
      outgoing,
    }
  }

  function initLab(match) {
    state.lab = {
      matchId: match.match_id,
      side: 'home',
      home: (match.lineups?.home?.players || []).map(p => ({ ...p })),
      away: (match.lineups?.away?.players || []).map(p => ({ ...p })),
      selectedStarterId: null,
      justInId: null,
      lastSwap: null,
      flashImpact: false,
      xiPreset: 'squad', // squad | best | custom
    }
  }

  function sideMeta(match, side) {
    return match.lineups?.[side] || {}
  }

  function renderLiveImpact(match, { flash = false } = {}) {
    const { base, probs } = computeWhatIf(match)
    const tipNow = tipFromProbs(match, probs)
    const tipWas = tipLabel(match)
    const cells = [
      ['H', 'home', probs.p_home_win, base.p_home_win],
      ['D', 'draw', probs.p_draw, base.p_draw],
      ['A', 'away', probs.p_away_win, base.p_away_win],
    ]
    const el = document.getElementById('live-impact')
    if (!el) return
    el.className = `live-impact${flash ? ' flash' : ''}`
    el.innerHTML = cells.map(([k, cls, v, b]) => {
      const delta = v - b
      const move = delta > 0.0005 ? 'up' : delta < -0.0005 ? 'down' : ''
      return `<div class="impact-cell ${cls} ${move}">
        <p class="lbl">${k}</p>
        <p class="val"><span class="num${flash ? ' pop' : ''}">${pct(v)}%</span><span class="pp ${delta >= 0 ? 'pos' : 'neg'}">${ppLabel(delta)}</span></p>
        <div class="bar"><i style="width:${Math.max(pct(v), 2)}%"></i></div>
      </div>`
    }).join('')
    document.getElementById('modal-tip').textContent = tipNow === tipWas ? tipWas : `${tipNow} (was ${tipWas})`
    if (flash) {
      requestAnimationFrame(() => {
        el.classList.remove('flash')
        void el.offsetWidth
        el.classList.add('flash')
      })
    }
  }

  function renderLab(match) {
    const lab = state.lab
    const side = lab.side
    const meta = sideMeta(match, side)
    const players = lab[side]
    const pool = meta.pool || []
    const starterIds = new Set(players.map(p => p.id).filter(x => x != null))
    const poolAvail = pool.filter(p => p.id == null || !starterIds.has(p.id))
    const canOptimize = hasStrength([...(meta.players || []), ...pool])
    const selected = lab.selectedStarterId != null
      ? players.find(p => p.id === lab.selectedStarterId)
      : null
    const step = selected ? 2 : 1
    const preset = lab.xiPreset || 'squad'
    const presetLabel = preset === 'best' ? 'Best XI' : preset === 'custom' ? 'Custom XI' : 'Squad XI'
    const swapMsg = lab.lastSwap
      ? `<p class="swap-done">Swapped <strong>${lab.lastSwap.out}</strong> → <strong>${lab.lastSwap.in}</strong> · tip updated ↑</p>`
      : `<p class="swap-done idle">Showing <strong>${presetLabel}</strong>${preset === 'squad' ? ' (predicted starters)' : preset === 'best' ? ' (strongest ratings)' : ''}</p>`

    return `
      <div class="lab-compact" id="xi-lab">
        <p class="panel-title">Swap lab · 2 taps</p>
        <div class="lab-sides">
          <button type="button" class="chip ${side === 'home' ? 'on' : ''}" data-lab-side="home">${match.home_short}</button>
          <button type="button" class="chip ${side === 'away' ? 'on' : ''}" data-lab-side="away">${match.away_short}</button>
        </div>
        <ol class="swap-steps">
          <li class="${step === 1 ? 'active' : 'done'}">
            <span class="n">1</span>
            <span>${selected ? `OUT: <strong>${selected.name}</strong>` : 'Tap a player on the pitch'}</span>
          </li>
          <li class="${step === 2 ? 'active' : ''}">
            <span class="n">2</span>
            <span>${selected ? 'Tap a bench chip to bring IN' : 'Then pick a replacement'}</span>
          </li>
        </ol>
        ${swapMsg}
        <div class="bench-scroll ${selected ? 'awaiting' : ''}" data-lab-pool>
          ${poolAvail.length ? poolAvail.slice(0, 28).map(p => `
            <button type="button" class="bench-chip ${selected ? 'ready' : ''}" data-lab-sub="${p.id ?? ''}"
              ${selected ? '' : 'disabled'} title="${p.name}">
              <span class="num">${p.number != null ? p.number : '—'}</span>
              <span>${surname(p.name)}</span>
              <span class="meta">${p.pos || '?'}</span>
            </button>`).join('') : `<p class="empty-inline">No bench pool for this side.</p>`}
        </div>
        <div class="lab-actions" role="group" aria-label="XI preset">
          <button type="button" class="ghost-btn ${preset === 'squad' ? 'on' : ''}" data-lab-reset aria-pressed="${preset === 'squad'}">
            Reset XI
            <span class="btn-sub">squad</span>
          </button>
          <button type="button" class="ghost-btn accent ${preset === 'best' ? 'on' : ''}" data-lab-optimize
            ${canOptimize ? '' : 'disabled'} aria-pressed="${preset === 'best'}">
            Best XI
            <span class="btn-sub">strongest</span>
          </button>
        </div>
      </div>`
  }

  function renderMatchdayNudge(currentMatch) {
    const boost = Number(state.globalBoost) || 0
    const rows = (state.data.predictions || []).map(m => {
      const { base, probs } = applyBoostToMatch(m, boost)
      const tipWas = tipLabel(m)
      const tipNow = tipFromProbs(m, probs)
      const leanWas = Math.max(base.p_home_win, base.p_draw, base.p_away_win)
      const leanNow = Math.max(probs.p_home_win, probs.p_draw, probs.p_away_win)
      const dH = probs.p_home_win - base.p_home_win
      const dD = probs.p_draw - base.p_draw
      const dA = probs.p_away_win - base.p_away_win
      return {
        m, tipWas, tipNow, leanWas, leanNow, dH, dD, dA, probs, base,
        changed: tipWas !== tipNow,
        current: m.match_id === currentMatch.match_id,
      }
    })
    const flips = rows.filter(r => r.changed).length
    const head = `<div class="nudge-summary">
      <span>${boost === 0 ? 'All fixtures at current XI quality edge' : `Home XI edge ${boost > 0 ? '+' : ''}${boost}`}</span>
      <span class="${flips ? 'pos' : ''}">${flips ? `${flips} tip flip${flips === 1 ? '' : 's'}` : 'no tip flips yet'}</span>
    </div>`
    const body = rows.map((r, i) => `
      <div class="nudge-row ${r.current ? 'current' : ''} ${boost ? 'moved' : ''} ${r.changed ? 'flipped' : ''}"
        style="animation-delay:${(i * 0.03).toFixed(2)}s">
        <div class="nudge-top">
          <span class="fixture">${r.m.home_short} <em>vs</em> ${r.m.away_short}</span>
          <span class="tip-flow">
            <span class="tip-was">${r.tipWas} ${pct(r.leanWas)}%</span>
            <span class="arrow" aria-hidden="true">→</span>
            <span class="tip-now">${r.tipNow} ${pct(r.leanNow)}%</span>
            ${r.changed ? '<span class="flip-tag">FLIP</span>' : ''}
          </span>
        </div>
        <div class="nudge-bars" aria-hidden="true">
          <div class="nb home" style="flex:${Math.max(pct(r.probs.p_home_win), 1)}"></div>
          <div class="nb draw" style="flex:${Math.max(pct(r.probs.p_draw), 1)}"></div>
          <div class="nb away" style="flex:${Math.max(pct(r.probs.p_away_win), 1)}"></div>
        </div>
        <div class="tip-delta">
          H <span class="${r.dH >= 0 ? 'pos' : 'neg'}">${ppLabel(r.dH)}</span>
          · D <span class="${r.dD >= 0 ? 'pos' : 'neg'}">${ppLabel(r.dD)}</span>
          · A <span class="${r.dA >= 0 ? 'pos' : 'neg'}">${ppLabel(r.dA)}</span>
        </div>
      </div>`).join('')
    return head + body
  }

  function renderDriverList(items, { compact = false } = {}) {
    const list = items || []
    const maxAbs = Math.max(...list.map(f => Math.abs(Number(f.shap) || 0)), 0.001)
    if (!list.length) return `<li class="empty-inline">No drivers yet.</li>`
    return list.map(f => {
      const shap = Number(f.shap) || 0
      const w = Math.round((Math.abs(shap) / maxAbs) * 100)
      const neg = shap < 0
      const kind = f.kind || 'team'
      return `<li>
        <span class="kind ${kind}">${kind === 'interaction' ? 'vs' : kind}</span>
        <span>${f.label}</span>
        <span class="${neg ? 'neg' : 'pos'}">${shap >= 0 ? '+' : ''}${shap.toFixed(3)}</span>
        <div class="driver-bar ${neg ? 'neg' : ''}"><i style="width:${w}%"></i></div>
      </li>`
    }).join('')
  }

  function renderShapPane(match) {
    const expl = match.explanation || {}
    const teamFeats = expl.top_features || []
    const players = expl.player_features || []
    const interactions = expl.interaction_features || []
    const lines = expl.line_features || []
    const boost = Number(state.globalBoost) || 0
    const nFix = (state.data.predictions || []).length
    const method = String(expl.method || 'ShapIQ').replace(/ShapeIQ/g, 'ShapIQ')
    return `
      <div class="shap-left">
        <p class="panel-title">ShapIQ · ${match.home_short} vs ${match.away_short}</p>
        <p class="xi-sources">${method}
          ${expl.baseline != null ? ` · baseline ${Number(expl.baseline).toFixed(3)}` : ''}
          · who plays + how lines match up</p>
        <div class="shap-plot">
          ${expl.plot
            ? `<img src="${expl.plot}" alt="ShapIQ waterfall" />`
            : `<div class="empty-inline">No waterfall — re-run predict.py</div>`}
        </div>
        <div class="shap-section">
          <h4>Match drivers</h4>
          <p class="sec-help">Team-level ShapIQ factors for the tipped result.</p>
          <ul class="drivers compact">${renderDriverList(teamFeats.slice(0, 10), { compact: true })}</ul>
        </div>
        <div class="shap-section">
          <h4>Players who start</h4>
          <p class="sec-help">Each starter’s share of the XI quality edge — stronger names push harder.</p>
          <ul class="drivers">${renderDriverList(players.slice(0, 16))}</ul>
        </div>
        <div class="shap-section">
          <h4>Line vs line · interactions</h4>
          <p class="sec-help">Home attack vs away defence, midfield battle, star edge, and other matchups.</p>
          <ul class="drivers">${renderDriverList([...(interactions || []), ...(lines || [])].slice(0, 14))}</ul>
        </div>
      </div>
      <div class="shap-right">
        <p class="panel-title">Spieltag what-if</p>
        <div class="nudge-box">
          <p class="nudge-title">Home XI quality edge</p>
          <p class="nudge-help">
            The model’s <strong>XI strength gap</strong> is “how much better is the home starting eleven than the away one?”
            Dragging this slider pretends every home side on the matchday is a bit
            <strong>stronger (+)</strong> or <strong>weaker (−)</strong> than we currently think —
            like a bigger or smaller home-side quality / advantage from who is selected.
            Tips for all ${nFix} fixtures update live below.
          </p>
          <label>
            <span>Adjust home XI quality gap</span>
            <input type="range" min="-3" max="3" step="0.5" value="${boost}" data-global-boost />
            <span class="boost-val">${boost > 0 ? '+' : ''}${boost}</span>
          </label>
          <div class="nudge-ends"><span>Weaker home XIs</span><span>Stronger home XIs</span></div>
        </div>
        <div class="matchday-nudge" id="matchday-nudge">${renderMatchdayNudge(match)}</div>
      </div>`
  }

  function flyChip(fromEl, toEl, label) {
    if (!fromEl || !toEl) return
    const a = fromEl.getBoundingClientRect()
    const b = toEl.getBoundingClientRect()
    const chip = document.createElement('div')
    chip.className = 'swap-fly'
    chip.textContent = label
    chip.style.left = `${a.left + a.width / 2}px`
    chip.style.top = `${a.top + a.height / 2}px`
    chip.style.setProperty('--dx', `${b.left - a.left}px`)
    chip.style.setProperty('--dy', `${b.top - a.top}px`)
    document.body.appendChild(chip)
    setTimeout(() => chip.remove(), 560)
  }

  function doSwap(match, subId, fromBtn) {
    const starterId = state.lab.selectedStarterId
    if (!Number.isFinite(subId) || !Number.isFinite(starterId)) return
    const side = state.lab.side
    const meta = sideMeta(match, side)
    const pool = [...(meta.players || []), ...(meta.pool || [])]
    const sub = pool.find(p => p.id === subId)
    const idx = state.lab[side].findIndex(p => p.id === starterId)
    if (!sub || idx < 0) return
    const prev = state.lab[side][idx]
    const targetDot = document.querySelector(`.pitch .dot[data-id="${starterId}"]`)
    flyChip(fromBtn, targetDot, surname(sub.name))
    state.lab[side][idx] = { ...sub, grid: prev.grid, pos: sub.pos || prev.pos }
    state.lab.lastSwap = { out: prev.name, in: sub.name }
    state.lab.justInId = sub.id
    state.lab.selectedStarterId = null
    state.lab.xiPreset = 'custom'
    state.lab.flashImpact = true
    setTimeout(() => renderModal(match), 180)
    setTimeout(() => { if (state.lab) state.lab.justInId = null }, 800)
  }

  function bindLab(match) {
    const root = document.getElementById('xi-lab')
    if (!root) return
    root.querySelectorAll('[data-lab-side]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.lab.side = btn.dataset.labSide
        state.lab.selectedStarterId = null
        renderModal(match)
      })
    })
    root.querySelectorAll('[data-lab-sub]').forEach(btn => {
      btn.addEventListener('click', () => doSwap(match, Number(btn.dataset.labSub), btn))
    })
    root.querySelector('[data-lab-reset]')?.addEventListener('click', () => {
      const side = state.lab.side
      initLab(match)
      state.lab.side = side
      state.lab.xiPreset = 'squad'
      state.lab.lastSwap = null
      state.lab.flashImpact = true
      renderModal(match)
    })
    root.querySelector('[data-lab-optimize]')?.addEventListener('click', () => {
      const side = state.lab.side
      const best = bestXi(match, side)
      if (!best) return
      const current = state.lab[side]
      state.lab.xiPreset = 'best'
      if (!best.changed) {
        state.lab.lastSwap = { out: 'Best XI', in: 'already strongest by rating' }
        state.lab.selectedStarterId = null
        renderModal(match)
        return
      }
      // Keep pitch slots: map new XI onto old grids by position order
      const grids = current.map(p => p.grid)
      state.lab[side] = best.players.map((p, i) => ({ ...p, grid: grids[i] ?? p.grid }))
      state.lab.selectedStarterId = null
      const outNames = best.outgoing.slice(0, 3).map(p => surname(p.name)).join(', ')
      const inNames = best.incoming.slice(0, 3).map(p => surname(p.name)).join(', ')
      state.lab.lastSwap = {
        out: outNames || 'XI',
        in: `${inNames || 'Best XI'} (${best.delta >= 0 ? '+' : ''}${best.delta.toFixed(2)} str)`,
      }
      state.lab.flashImpact = true
      renderModal(match)
    })
  }

  function bindPitchClicks(match) {
    document.querySelectorAll('.pitch .dot').forEach(dot => {
      dot.addEventListener('click', () => {
        const side = dot.dataset.side
        const id = Number(dot.dataset.id)
        if (!state.lab) initLab(match)
        state.lab.side = side
        state.lab.selectedStarterId = Number.isFinite(id) ? id : null
        state.mode = 'board'
        renderModal(match)
      })
    })
  }

  function bindModeTabs(match) {
    document.querySelectorAll('[data-mode]').forEach(btn => {
      btn.classList.toggle('on', btn.dataset.mode === state.mode)
      btn.onclick = () => {
        state.mode = btn.dataset.mode
        renderModal(match)
      }
    })
  }

  function bindShapNudge(match) {
    const slider = document.querySelector('[data-global-boost]')
    if (!slider) return
    slider.addEventListener('input', (e) => {
      state.globalBoost = Number(e.target.value) || 0
      const val = document.querySelector('.shap-right .boost-val')
      if (val) val.textContent = `${state.globalBoost > 0 ? '+' : ''}${state.globalBoost}`
      const box = document.getElementById('matchday-nudge')
      if (box) box.innerHTML = renderMatchdayNudge(match)
      renderLiveImpact(match, { flash: true })
    })
  }

  function renderModal(match) {
    document.getElementById('modal-title').textContent = `${match.home_short} vs ${match.away_short}`
    if (!state.lab || state.lab.matchId !== match.match_id) initLab(match)
    const flash = !!state.lab.flashImpact
    state.lab.flashImpact = false

    const view = labView(match)
    const hSrc = sourceLabel(match.lineups?.home?.source)
    const aSrc = sourceLabel(match.lineups?.away?.source)
    const body = document.getElementById('modal-body')
    body.innerHTML = `
      <div class="detail-shell">
        <section class="mode-pane board-pane ${state.mode === 'board' ? 'on' : ''}">
          <div class="board-pitch">
            <p class="panel-title">Pitch · ${hSrc} / ${aSrc}</p>
            ${renderPitch(view)}
          </div>
          <div class="board-lab">${renderLab(match)}</div>
        </section>
        <section class="mode-pane shap-pane ${state.mode === 'shap' ? 'on' : ''}">
          ${renderShapPane(match)}
        </section>
      </div>`
    renderLiveImpact(match, { flash })
    bindModeTabs(match)
    if (state.mode === 'board') {
      bindLab(match)
      bindPitchClicks(match)
    } else {
      bindShapNudge(match)
    }
  }

  function openModal(match) {
    state.selectedId = match.match_id
    state.lab = null
    state.mode = 'board'
    state.globalBoost = 0
    renderModal(match)
    modal.hidden = false
    modal.classList.add('open')
    document.body.style.overflow = 'hidden'
  }

  function closeModal() {
    state.selectedId = null
    state.lab = null
    modal.hidden = true
    modal.classList.remove('open')
    document.body.style.overflow = ''
  }

  document.querySelectorAll('.match-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = Number(btn.dataset.matchId)
      const match = state.data.predictions.find(m => m.match_id === id)
      if (match) openModal(match)
    })
  })
  document.getElementById('modal-close').addEventListener('click', closeModal)
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal() })
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal() })

  async function mergeLiveLineups() {
    try {
      const res = await fetch('/api/lineups')
      if (!res.ok) return
      const live = await res.json()
      if (!live?.lineups) return
      state.data.predictions = state.data.predictions.map(m => {
        const row = live.lineups[String(m.match_id)]
        return row ? { ...m, lineups: row } : m
      })
      updateXiLabels()
      updateStamp(live.refreshed_at)
      if (state.selectedId != null) {
        const match = state.data.predictions.find(m => m.match_id === state.selectedId)
        if (match) {
          // Keep lab edits if same match
          renderModal(match)
        }
      }
    } catch (_) { /* keep baked */ }
  }

  // Mini pitches on cards
  function paintMiniPitches() {
    document.querySelectorAll('[data-mini-pitch]').forEach(el => {
      const id = Number(el.dataset.miniPitch)
      const match = state.data.predictions.find(m => m.match_id === id)
      if (!match?.lineups?.home?.players?.length) return
      const home = layoutPlayers(match.lineups.home.players, match.lineups.home.formation, 'home')
      const away = layoutPlayers(match.lineups.away?.players, match.lineups.away?.formation, 'away')
      el.innerHTML = [...home.map(p => ({ ...p, side: 'home' })), ...away.map(p => ({ ...p, side: 'away' }))]
        .map(p => `<span class="mini-dot ${p.side}" style="left:${(p.x * 100).toFixed(1)}%;top:${(p.y * 100).toFixed(1)}%"></span>`)
        .join('')
    })
  }

  updateStamp()
  paintMiniPitches()
  mergeLiveLineups().then(paintMiniPitches)
  setInterval(mergeLiveLineups, 15 * 60 * 1000)
})()
