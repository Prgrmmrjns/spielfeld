(() => {
  const $ = id => document.getElementById(id)
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
  const pct = (v, d = 1) => (v * 100).toFixed(d) + '%'
  const pp = (v, d = 1) => (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(d) + ' pp'
  const sur = n => String(n).split(' ').slice(-1)[0]
  const R = String.raw

  const TEX = {
    objective: R`(S^{\star},v^{\star})=\underset{S,\ v\in\mathcal{F}_S}{\arg\max}\ f\big(\mathrm{do}(X_S=v),\,x_{\bar S}\big)`,
    game: R`v(T)=f\big(\mathrm{do}(X_T=v^{\star}_T),\,x_{\bar T}\big),\qquad T\subseteq S^{\star}`,
    search: R`x_{t+1}=\underset{x\sim\ell}{\arg\max}\ \frac{\ell(x)}{g(x)}`,
    explain: R`v_{\text{explain}}(T)=\mathbb{E}\big[f(x_T,X_{\bar T})\big]`,
    design: R`v_{\text{what-if}}(T)=f\big(\mathrm{do}(X_T=v^{\star}_T),\,x_{\bar T}\big)`,
    ice: R`f\big(\mathrm{do}(X_j=v),\,x_{-j}\big)`,
    pdp: R`\mathbb{E}_{X}\,f\big(\mathrm{do}(X_j=v),\,X_{-j}\big)`,
    shap: R`\mathbb{E}\big[f(x_T,X_{\bar T})\big]`,
    whatif: R`\max_{S,\ v\in\mathcal{F}_S} f\big(\mathrm{do}(X_S=v),\,x_{\bar S}\big)`,
  }

  function tex(el, s, display) {
    if (window.katex) {
      try { katex.render(s, el, { throwOnError: false, displayMode: display }); return } catch (e) { /* fall through */ }
    }
    el.textContent = s
  }
  document.querySelectorAll('.tex[data-k]').forEach(el =>
    tex(el, TEX[el.dataset.k], el.classList.contains('display') || !!el.closest('.defs, .rel')))

  // ------------------------------------------------- search explorer
  // Every dot is one design the optimizer proposed and the model scored. Click a dot for its inputs.
  function explorer(root, cfg) {
    const side = { best: cfg.best, worst: cfg.worst }, b0 = cfg.base, K = cfg.knobs || []
    const TB = cfg.best.trials || [], TW = cfg.worst.trials || []
    const W = 600, H = 400, ml = 54, mr = 16, mt = 34, mb = 48
    const n = Math.max(TB.length, TW.length, 2)
    const X = i => ml + (i + 0.5) / n * (W - ml - mr)
    const all = TB.map(t => t[1])
    let lo = Math.min(...all), hi = Math.max(...all)
    const pad = (hi - lo) * 0.08 || 0.01
    lo -= pad; hi += pad
    const Y = v => mt + (hi - v) / (hi - lo) * (H - mt - mb)
    const f1 = x => x.toFixed(1)

    let o = ''
    const cuts = [0, ...(cfg.best.phases || []), TB.length]
    const PH = ['screen', 'warm start', 'search', 'polish']
    for (let p = 0; p < cuts.length - 1; p++) {
      const x0 = ml + cuts[p] / n * (W - ml - mr), x1 = ml + cuts[p + 1] / n * (W - ml - mr)
      if (x1 - x0 < 1) continue
      o += `<rect class="phase p${p}" x="${f1(x0)}" y="${mt - 14}" width="${f1(x1 - x0)}" height="${H - mt - mb + 14}"/>`
      if (x1 - x0 > 30) o += `<text class="ax phase-t" x="${f1(x0 + 4)}" y="${mt - 4}">${PH[p] || ''}</text>`
    }
    const span = hi - lo, step = span > 0.3 ? 0.1 : span > 0.12 ? 0.05 : span > 0.05 ? 0.02 : 0.01
    for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) {
      o += `<line class="gl" x1="${ml}" x2="${W - mr}" y1="${f1(Y(t))}" y2="${f1(Y(t))}"/><text class="ax" x="${ml - 8}" y="${f1(Y(t) + 3)}" text-anchor="end">${Math.round(t * 100)}%</text>`
    }
    const tick = n > 600 ? 200 : n > 300 ? 100 : 50
    for (let t = 0; t <= n; t += tick) o += `<text class="ax" x="${f1(X(t))}" y="${H - mb + 18}" text-anchor="middle">${t}</text>`
    o += `<text class="ax ttl" x="${(ml + W - mr) / 2}" y="${H - 10}" text-anchor="middle">designs tried, in order</text>`
    o += `<text class="ax ttl" transform="translate(13 ${(mt + H - mb) / 2}) rotate(-90)" text-anchor="middle">${esc(cfg.outcome)}</text>`

    const vlo = Math.min(...TB.map(t => t[1])), vhi = Math.max(...TB.map(t => t[1]))
    const col = v => { const u = vhi > vlo ? (v - vlo) / (vhi - vlo) : 1, c = (a, b) => Math.round(a + (b - a) * u); return `rgb(${c(88, 52)},${c(96, 211)},${c(112, 153)})` }  // grey to green: brighter is higher
    const dots = (T, s) => T.map((t, i) => `<circle class="hd ${s}" data-s="${s}" data-i="${i}" cx="${f1(X(i))}" cy="${f1(Y(t[1]))}" r="3.2" style="fill:${col(t[1])};animation-delay:${(0.1 + i / n * 1.4).toFixed(2)}s"/>`).join('')
    o += dots(TB, 'b')
    const run = (T, sign) => {
      let m = null, d = ''
      T.forEach((t, i) => { if (t[0] && (m === null || sign * t[1] > sign * m)) { m = t[1]; d += `${d ? 'H' + f1(X(i)) + 'V' : 'M' + f1(X(i)) + ' '}${f1(Y(m))}` } })
      return d + `H${f1(X(T.length - 1))}`
    }
    o += `<path class="env up" pathLength="1" d="${run(TB, 1)}"/>`
    const best = (T, sign) => T.reduce((b, t, j) => (sign * t[1] > sign * T[b][1] ? j : b), 0)
    const mark = (T, sign, s, label, dy) => {
      if (!T.length) return ''
      const i = best(T, sign), x = X(i), y = Y(T[i][1])
      const left = x > W * 0.62, tx = left ? x - 34 : x + 34
      return `<circle class="ring ${s}" cx="${f1(x)}" cy="${f1(y)}" r="7"/><g class="callout ${s}"><line x1="${f1(x + (left ? -6 : 6))}" y1="${f1(y + dy / 5)}" x2="${f1(left ? x - 30 : x + 30)}" y2="${f1(y + dy)}"/><text x="${f1(tx)}" y="${f1(y + dy + 4)}" text-anchor="${left ? 'end' : 'start'}">${label} <tspan>${pct(T[i][1])}</tspan></text></g>`
    }
    o += mark(TB, 1, 'b', 'best found', -22)
    o += `<circle class="sel" r="9" cx="-20" cy="-20"/>`

    root.classList.add('xroot')
    root.innerHTML = `<div class="xchart"><svg class="xsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Designs scored by the model, in search order">${o}</svg><div class="tip" hidden></div>${cfg.short ? '' : '<p class="xhint"><span class="dotkey"></span>Click any dot to see the inputs the optimizer sampled and the model\'s prediction.</p>'}</div><div class="xdet"></div>`
    const svg = root.querySelector('svg'), tip = root.querySelector('.tip'), det = root.querySelector('.xdet'), chart = root.querySelector('.xchart')
    const selRing = svg.querySelector('.sel')

    const show = (s, i) => {
      const T = s === 'w' ? TW : TB, t = T[i] || [0, b0, '', []]
      const c = svg.querySelector(`circle.hd[data-s="${s}"][data-i="${i}"]`)
      if (!c) return
      selRing.setAttribute('cx', c.getAttribute('cx')); selRing.setAttribute('cy', c.getAttribute('cy'))
      const vals = t[3] || []
      const rows = K.map((k, j) => (vals[j] != null ? `<tr><td>${esc(k.label)}</td><td class="mono">${esc(k.range || '')}</td><td class="mono"><b>${esc(vals[j])}</b></td></tr>` : '')).join('')
      const isBest = s === 'b' && i === bestI
      const sub = cfg.short
        ? `${t[0]} input${t[0] === 1 ? '' : 's'} changed`
        : `Design ${i + 1} of ${T.length} · ${t[0]} input${t[0] === 1 ? '' : 's'} changed. Inputs not listed are left unchanged.`
      const label = cfg.short ? '' : `<span>${esc(cfg.model)} prediction, ${esc(cfg.outcome)}</span>`
      const bestLabel = isBest ? (cfg.short ? 'Best' : 'Best design') : (cfg.short ? 'Show best' : 'Select best design')
      det.innerHTML = `<div class="xh"><b>${pct(t[1])}</b>${label}<button type="button" class="xbest" ${isBest ? 'disabled' : ''}>${bestLabel}</button></div>
        <p class="xsub">${sub}</p>
        <div class="xtab"><table><thead><tr><th>Input</th><th>Feasible range</th><th>This design</th></tr></thead><tbody>${rows}</tbody></table></div>`
    }
    const bestI = best(TB, 1)
    det.addEventListener('click', e => { if (e.target.closest('.xbest')) show('b', bestI) })
    show('b', bestI)

    svg.addEventListener('click', e => {
      const c = e.target.closest && e.target.closest('circle.hd')
      if (c) show(c.dataset.s, +c.dataset.i)
    })
    svg.addEventListener('mousemove', e => {
      const c = e.target.closest && e.target.closest('circle.hd')
      if (!c) { tip.hidden = true; return }
      const T = c.dataset.s === 'w' ? TW : TB, t = T[+c.dataset.i] || [0, 0]
      tip.innerHTML = `<b>${pct(t[1])}</b><div class="mono">design ${+c.dataset.i + 1} · click for inputs</div>`
      const r = chart.getBoundingClientRect()
      tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 190) + 'px'
      tip.style.top = (e.clientY - r.top + 16) + 'px'
      tip.hidden = false
    })
    svg.addEventListener('mouseleave', () => { tip.hidden = true })
  }

  const modelName = d => String((d.card || {}).model || 'Model').split(' classifier')[0].split(' regressor')[0]
  Promise.all(['football', 'glucose', 'mortality'].map(d => fetch(`/data/scenarios/${d}.json`).then(r => r.json()))).then(packs => {
    packs.forEach(data => {
      const it = (data.instances || [])[0]
      if (!it) return
      const root = document.querySelector(`.xp[data-domain="${data.domain}"]`)
      if (data.domain === 'football') {
        const v = it.sides.home
        if (root) explorer(root, { model: modelName(data), base: v.base, best: v.best, worst: v.worst, knobs: v.knobs, outcome: 'P(win)' })
      } else if (root) {
        explorer(root, { model: modelName(data), base: it.base, best: it.best, worst: it.worst, knobs: it.knobs, outcome: data.domain === 'glucose' ? 'P(in range)' : 'P(survival)' })
      }
    })
    const mo = packs[2]
    const it = (mo.instances || []).find(i => i.best && (i.best.trials || []).length)
    if (!it) return
    explorer($('hero-x'), { short: true, model: modelName(mo), base: it.base, best: it.best, worst: it.worst, knobs: it.knobs, outcome: 'P(survival)' })
  })

  const panels = ['overview', 'background', 'method', 'mortality', 'football', 'glucose']
  function openHash() {
    let id = location.hash.slice(1)
    if (!panels.includes(id)) id = 'overview'
    panels.forEach(p => {
      const e = $(p)
      e.classList.toggle('on', p === id)
      if (e.tagName === 'DETAILS') e.open = true
    })
    document.querySelectorAll('.site-nav a').forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + id))
    scrollTo(0, 0)
  }
  addEventListener('hashchange', openHash)
  openHash()
})()
