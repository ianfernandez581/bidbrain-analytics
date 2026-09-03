/* Foodbank Australia - campaign performance dashboard.
   Reads ONE payload (data.json) and renders seven tabs from it. Every figure on screen is a filter
   + sum over that payload (facts[] / site_daily[] / reach_daily[]) for the selected date window
   and channels; nothing is hardcoded here. Names come from window.BRAND (main.py config).

   Chart.js v4 house rules (repo-wide): never put a FUNCTION inside options.plugins.<custom> -
   Chart.js treats it as a scriptable option, auto-invokes it and blanks the chart. Custom plugins
   below read data-only option objects, and each one requires an EXPLICIT option (a string mode, a
   label, an array) before it draws - Chart.js v4 hands back a truthy resolver proxy for a plugin
   key that was never configured, so `if (!opts) return` is not a guard at all. Animation is off: the page has one entrance moment. */
(function () {
  'use strict';

  const BRAND = window.BRAND || {};
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ------------------------------------------------------------------ brand + chart theme
  const CSS = getComputedStyle(document.documentElement);
  const TOK = (n) => CSS.getPropertyValue(n).trim();
  const INK = TOK('--fb-ink') || '#332336';
  const CH_COLOR = { meta: TOK('--ch-meta') || '#671E75', youtube: TOK('--ch-youtube') || '#FFA096', programmatic: TOK('--ch-programmatic') || '#CDB1F9' };
  const FALLBACK_COLORS = ['#671E75', '#FFA096', '#CDB1F9', '#4E1459', '#E08A2E'];
  const chColor = (key, i) => CH_COLOR[key] || FALLBACK_COLORS[(i || 0) % FALLBACK_COLORS.length];
  const alpha = (hex, a) => { const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16); return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`; };
  const SEQ = ['#671E75', '#8A4A96', '#AD78B8', '#CDB1F9', '#E3D2FA', '#F2F2E2'];

  if (window.Chart) {
    Chart.defaults.font.family = '"Inter", system-ui, sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = 'rgba(51,35,54,.66)';
    Chart.defaults.borderColor = 'rgba(51,35,54,.08)';
    /* animation timing is set by the motion kit bootstrap in <head>; nothing here overrides it */
    Chart.defaults.responsive = true;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = '#FFFFFF';
    Chart.defaults.plugins.tooltip.titleColor = INK;
    Chart.defaults.plugins.tooltip.bodyColor = 'rgba(51,35,54,.8)';
    Chart.defaults.plugins.tooltip.borderColor = 'rgba(51,35,54,.14)';
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
    Chart.defaults.plugins.tooltip.titleFont = { weight: '600', size: 12 };
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.elements.point.radius = 0;
    Chart.defaults.elements.point.hoverRadius = 4;
    Chart.defaults.elements.line.borderWidth = 1.5;
    Chart.defaults.elements.bar.borderRadius = 3;
  }

  // ------------------------------------------------------------------ formatting (AUD, 1dp %, abbreviations)
  const PFX = () => (DATA && DATA.meta && DATA.meta.currency_prefix) || 'A$';
  const fmt = {
    int: (v) => (v == null || !isFinite(v)) ? '-' : Math.round(v).toLocaleString('en-AU'),
    abbr: (v) => {
      if (v == null || !isFinite(v)) return '-';
      const a = Math.abs(v);
      if (a >= 1e6) return (v / 1e6).toFixed(1) + 'M';
      if (a >= 1e4) return (v / 1e3).toFixed(1) + 'K';
      return Math.round(v).toLocaleString('en-AU');
    },
    money: (v, dp) => {
      if (v == null || !isFinite(v)) return '-';
      if (dp == null) dp = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 1 ? 2 : 3;
      if (Math.abs(v) < Math.pow(10, -dp) / 2) v = 0;   // no "A$-0"
      const s = Math.abs(v).toLocaleString('en-AU', { minimumFractionDigits: dp, maximumFractionDigits: dp });
      return (v < 0 ? '-' : '') + PFX() + s;
    },
    moneyAbbr: (v) => {
      if (v == null || !isFinite(v)) return '-';
      const a = Math.abs(v);
      if (a >= 1e6) return PFX() + (v / 1e6).toFixed(2) + 'M';
      if (a >= 1e4) return PFX() + (v / 1e3).toFixed(1) + 'K';
      return fmt.money(v, 0);
    },
    pct: (v, dp) => {
      if (v == null || !isFinite(v)) return '-';
      if (dp == null) dp = Math.abs(v) < 0.01 ? 2 : 1;
      return (v * 100).toFixed(dp) + '%';
    },
    x: (v) => (v == null || !isFinite(v)) ? '-' : v.toFixed(1) + 'x',
    secs: (v) => { if (v == null || !isFinite(v)) return '-'; const m = Math.floor(v / 60), s = Math.round(v % 60); return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`; },
    delta: (v, dp) => { if (v == null || !isFinite(v)) return '-'; const d = dp == null ? 0 : dp; if (Math.abs(v * 100) < Math.pow(10, -d) / 2) v = 0; return (v > 0 ? '+' : '') + (v * 100).toFixed(d) + '%'; },
  };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const parseD = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
  const dLabel = (s, opts) => { const d = parseD(s); const o = opts || {}; let out = `${d.getDate()} ${MONTHS[d.getMonth()]}`; if (o.dow) out = `${DOW[d.getDay()]} ${out}`; if (o.year) out += ` ${d.getFullYear()}`; return out; };

  // ------------------------------------------------------------------ state
  let DATA = null;
  let DATES = [];          // sorted unique dates in the payload
  let DIDX = {};           // date -> index
  let RD = {};             // channel -> daily reach array (by date index)
  const state = { tab: 'overview', range: 'flight', channels: new Set(), siteGrain: 'day', ovMetric: 'impressions', siteMetric: 'sessions' };
  const charts = {};
  const dirty = new Set();
  const TABS = ['overview', 'channels', 'audience', 'video', 'website', 'pacing', 'methodology'];
  const TAB_INTRO = {
    channels: ['Channels', (n) => `How ${listNames(n)} compared on delivery, efficiency and response.`],
    audience: ['Audience and reach', () => 'Who the campaign reached, how often, and where.'],
    video: ['Video and creative', () => 'How the video ran through to completion, and which creatives earned the most attention.'],
    website: ['Website and actions', () => 'What people did after seeing the campaign - visits, report downloads, sign-ups and donations.'],
    pacing: ['Pacing', () => 'Spend against the media plan, week by week.'],
    methodology: ['Methodology', () => 'How every figure is defined, what it can and cannot claim, and where the data comes from.'],
  };
  function listNames(names) { if (names.length <= 1) return names.join(''); return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]; }

  // ------------------------------------------------------------------ window + filters
  function windowIdx() {
    const e = DIDX[DATA.meta.data_through] != null ? DIDX[DATA.meta.data_through] : DATES.length - 1;
    const len = state.range === 'last7' ? 7 : state.range === 'last28' ? 28 : DATES.length;
    return [Math.max(0, e - len + 1), e];
  }
  const inWin = (r, w) => r._i >= w[0] && r._i <= w[1];
  const chanOk = (r) => state.channels.has(r.channel);
  const chans = () => DATA.channels.filter((c) => state.channels.has(c.key));
  const chanKeys = () => chans().map((c) => c.key);
  const chanName = (k) => { const c = DATA.channels.find((x) => x.key === k); return c ? c.name : k; };
  const F = (w) => DATA.facts.filter((r) => inWin(r, w) && chanOk(r));
  const S = (w) => DATA.site_daily.filter((r) => inWin(r, w) && chanOk(r));

  function agg(rows, keys) {
    const out = { _has: {} };
    keys.forEach((k) => { out[k] = 0; out._has[k] = false; });
    for (const r of rows) for (const k of keys) { const v = r[k]; if (v != null) { out[k] += v; out._has[k] = true; } }
    keys.forEach((k) => { if (!out._has[k]) out[k] = null; });
    return out;
  }
  const FACT_KEYS = ['spend', 'impressions', 'clicks', 'video_impressions', 'video_views', 'q25', 'q50', 'q75', 'q100', 'viewable_impressions'];
  const SITE_KEYS = ['sessions', 'engaged_sessions', 'engagement_time_sec', 'downloads', 'signups', 'donations', 'donation_value'];
  const div = (a, b) => (a == null || b == null || !b) ? null : a / b;

  function reachFor(keys, w) {
    const n = w[1] - w[0] + 1;
    let tot = 0;
    for (const k of keys) {
      let s = 0; const arr = RD[k] || [];
      for (let i = w[0]; i <= w[1]; i++) s += arr[i] || 0;
      tot += s * Math.pow(n, -(DATA.reach_model.window_exponent[k] || 0));
    }
    const m = keys.length, M = DATA.channels.length;
    if (m > 1 && M > 1) tot *= 1 - (1 - DATA.reach_model.cross_channel_dedup) * (m - 1) / (M - 1);
    return tot;
  }

  function weeksIn(w) { return DATA.plan.weeks.filter((wk) => DIDX[wk.end] >= w[0] && DIDX[wk.start] <= w[1]); }

  // ------------------------------------------------------------------ chart plugins (data-only options)
  if (window.Chart) {
    // Vendored: dynamic donut centre value (canonical copy: clients/client_resetdata/dash/dashboard.html)
    Chart.register({
      id: 'bbDonutCenter',
      afterDraw(chart) {
        try {
          const o = chart.options && chart.options.plugins && chart.options.plugins.bbCenter; if (!o || typeof o.label !== 'string') return;
          const ds = (chart.data.datasets || [])[0]; if (!ds) return;
          const a = chart.chartArea; if (!a) return;
          let sum = 0; (ds.data || []).forEach((v, i) => { if (chart.getDataVisibility(i)) sum += (+v || 0); });
          const cx = (a.left + a.right) / 2, cy = (a.top + a.bottom) / 2;
          const ring = Math.min(a.right - a.left, a.bottom - a.top);
          const cutout = (typeof chart.options.cutout === 'string' ? parseFloat(chart.options.cutout) / 100 : 0.5) || 0.5;
          const hole = ring * cutout * 0.92;
          const fam = (Chart.defaults.font && Chart.defaults.font.family) || 'Inter,system-ui,sans-serif';
          const val = o.mode === 'abbr' ? fmt.abbr(sum) : o.mode === 'money' ? fmt.moneyAbbr(sum) : (o.prefix || '') + Math.round(sum).toLocaleString();
          const ctx = chart.ctx; ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          let vs = Math.max(13, Math.min(28, ring * 0.16));
          ctx.font = '600 ' + vs + 'px ' + fam;
          while (vs > 10 && ctx.measureText(val).width > hole) { vs -= 1; ctx.font = '600 ' + vs + 'px ' + fam; }
          ctx.fillStyle = o.color || INK; ctx.fillText(val, cx, cy - vs * 0.14);
          ctx.font = '600 10.5px ' + fam; ctx.globalAlpha = 0.6; ctx.fillStyle = o.labelColor || INK;
          ctx.fillText(String(o.label || ''), cx, cy + vs * 0.72); ctx.globalAlpha = 1; ctx.restore();
        } catch (e) { /* never let a centre-label error blank the chart */ }
      },
    });
    // Moment bands on a time axis: options.plugins.bbMoments = { bands:[{from,to,label,color}] } (indices)
    Chart.register({
      id: 'bbMoments',
      beforeDatasetsDraw(chart) {
        try {
          const o = chart.options.plugins && chart.options.plugins.bbMoments; if (!o || !Array.isArray(o.bands) || !o.bands.length) return;
          const x = chart.scales.x, a = chart.chartArea; if (!x || !a) return;
          const ctx = chart.ctx; ctx.save();
          for (const b of o.bands) {
            const x0 = x.getPixelForValue(b.from) - (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2;
            const x1 = x.getPixelForValue(b.to) + (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2;
            const L = Math.max(a.left, x0), R = Math.min(a.right, x1); if (R <= L) continue;
            ctx.fillStyle = b.color || 'rgba(103,30,117,.07)'; ctx.fillRect(L, a.top, R - L, a.bottom - a.top);
            ctx.fillStyle = b.edge || 'rgba(103,30,117,.35)'; ctx.fillRect(L, a.top, 1, a.bottom - a.top); ctx.fillRect(R - 1, a.top, 1, a.bottom - a.top);
            ctx.font = '600 11px "Inter", system-ui, sans-serif'; ctx.fillStyle = INK; ctx.textBaseline = 'top'; ctx.textAlign = 'left';
            const tw = ctx.measureText(b.label).width; const tx = Math.min(L + 8, a.right - tw - 4);
            ctx.fillText(b.label, tx, a.top + 6);
          }
          ctx.restore();
        } catch (e) { /* decoration only */ }
      },
    });
    // Value labels on bars: options.plugins.bbValues = { mode:'int'|'abbr'|'pct'|'money'|'moneyAbbr', axis:'x'|'y', labels:[...optional per-index override] }
    Chart.register({
      id: 'bbValues',
      afterDatasetsDraw(chart) {
        try {
          const o = chart.options.plugins && chart.options.plugins.bbValues; if (!o || typeof o.mode !== 'string') return;
          const ctx = chart.ctx; ctx.save(); ctx.font = '600 11.5px "Inter", system-ui, sans-serif'; ctx.fillStyle = 'rgba(51,35,54,.78)';
          const horiz = chart.options.indexAxis === 'y';
          chart.data.datasets.forEach((ds, di) => {
            if (o.dataset != null && o.dataset !== di) return;
            const meta = chart.getDatasetMeta(di); if (meta.hidden) return;
            meta.data.forEach((bar, i) => {
              const v = ds.data[i]; if (v == null) return;
              const txt = o.labels && o.labels[i] != null ? o.labels[i]
                : o.mode === 'abbr' ? fmt.abbr(v) : o.mode === 'pct' ? fmt.pct(v / 100) : o.mode === 'money' ? fmt.money(v) : o.mode === 'moneyAbbr' ? fmt.moneyAbbr(v) : fmt.int(v);
              if (horiz) { ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, bar.x + 6, bar.y); }
              else { ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillText(txt, bar.x, bar.y - 4); }
            });
          });
          ctx.restore();
        } catch (e) { /* decoration only */ }
      },
    });
    // Labels beside bubbles: options.plugins.bbBubbleLabels = { labels:[[...per dataset]] }
    Chart.register({
      id: 'bbBubbleLabels',
      afterDatasetsDraw(chart) {
        try {
          const o = chart.options.plugins && chart.options.plugins.bbBubbleLabels; if (!o || !Array.isArray(o.labels)) return;
          const ctx = chart.ctx; ctx.save(); ctx.font = '600 11px "Inter", system-ui, sans-serif'; ctx.fillStyle = 'rgba(51,35,54,.82)'; ctx.textBaseline = 'middle';
          chart.data.datasets.forEach((ds, di) => {
            const meta = chart.getDatasetMeta(di); if (meta.hidden) return;
            meta.data.forEach((pt, i) => { const lab = (o.labels[di] || [])[i]; if (!lab) return; const r = pt.options.radius || 6; ctx.textAlign = 'left'; ctx.fillText(lab, pt.x + r + 6, pt.y); });
          });
          ctx.restore();
        } catch (e) { /* decoration only */ }
      },
    });
  }

  function mk(id, cfg) {
    const c = $(id); if (!c) return null;
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    charts[id] = new Chart(c.getContext('2d'), cfg);
    return charts[id];
  }
  const axisMoney = { ticks: { callback: (v) => fmt.moneyAbbr(v) }, grid: { drawTicks: false }, border: { display: false } };
  const axisAbbr = { ticks: { callback: (v) => fmt.abbr(v) }, grid: { drawTicks: false }, border: { display: false } };
  const axisCat = { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 18 } };

  // ------------------------------------------------------------------ table helper
  // cols: [{h, k|f, n(numeric), cls, total:'sum'|'avg'|f|false}]
  function table(id, cols, rows, opts) {
    const t = $(id); if (!t) return;
    const o = opts || {};
    let h = '<thead><tr>' + cols.map((c) => `<th${c.n ? ' class="n"' : ''}>${esc(c.h)}</th>`).join('') + '</tr></thead><tbody>';
    for (const r of rows) h += '<tr>' + cols.map((c) => `<td class="${c.n ? 'n ' : ''}${c.cls || ''}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join('') + '</tr>';
    if (o.total) h += '<tr class="total">' + cols.map((c, i) => `<td class="${c.n ? 'n' : ''}">${i === 0 ? 'Total' : (c.t ? c.t(o.total) : '')}</td>`).join('') + '</tr>';
    t.innerHTML = h + '</tbody>';
  }
  const chip = (v, opts) => {
    const o = opts || {};
    if (v == null || !isFinite(v)) return '<span class="vchip">-</span>';
    const cls = Math.abs(v) < (o.band == null ? 0.05 : o.band) ? '' : (v > 0) === !o.invert ? 'pos' : 'neg';
    return `<span class="vchip ${cls}">${fmt.delta(v)}</span>`;
  };
  const dot = (k, i) => `<span class="dot" style="background:${chColor(k, i)}"></span>`;
  // sel = {metric, group} makes the card a metric selector for the chart its group drives
  const kpi = (lab, val, sub, sel) => {
    const txt = /[A-Za-z]{3,}/.test(String(val).replace(/<[^>]+>/g, '')) && !/^[A-Z$0-9.,%x+\- ]+$/.test(String(val));
    const on = sel && state[sel.group + 'Metric'] === sel.metric;
    const attrs = sel ? ` data-metric="${esc(sel.metric)}" data-group="${esc(sel.group)}" role="button" tabindex="0" aria-pressed="${on ? 'true' : 'false'}" title="Plot ${esc(lab.toLowerCase())} on the chart"` : '';
    return `<div class="kpi${sel ? ' clk' : ''}${on ? ' is-active' : ''}"${attrs}><div class="kpi-lab">${esc(lab)}</div><div class="kpi-val value num${txt ? ' txt' : ''}">${val}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
  };
  const fmtKind = (kind, v) => kind === 'abbr' ? fmt.abbr(v) : kind === 'int' ? fmt.int(v) : kind === 'money' ? fmt.money(v, 0) : kind === 'money2' ? fmt.money(v, 2)
    : kind === 'money3' ? fmt.money(v, 3) : kind === 'pct' ? fmt.pct(v) : kind === 'x' ? fmt.x(v) : kind === 'secs' ? fmt.secs(v) : fmt.int(v);
  const ADDITIVE = { abbr: 1, int: 1, money: 1 };
  // Metrics a card can put on the Overview daily chart. `v` reads one channel-day bucket.
  const OV_METRICS = {
    impressions: { label: 'impressions', kind: 'abbr', v: (d) => d.impressions },
    reach: { label: 'reach', kind: 'abbr', v: (d) => d.reach },
    frequency: { label: 'frequency', kind: 'x', v: (d) => div(d.impressions, d.reach) },
    video_views: { label: 'video views', kind: 'abbr', v: (d) => d.video_views },
    sessions: { label: 'website visits', kind: 'abbr', v: (d) => d.sessions },
    spend: { label: 'net media spend', kind: 'money', v: (d) => d.spend },
    cpm: { label: 'CPM', kind: 'money2', v: (d) => d.impressions ? d.spend / d.impressions * 1000 : null },
    clicks: { label: 'clicks', kind: 'int', v: (d) => d.clicks },
    ctr: { label: 'CTR', kind: 'pct', v: (d) => div(d.clicks, d.impressions) },
    cpc: { label: 'CPC', kind: 'money2', v: (d) => div(d.spend, d.clicks) },
    view_rate: { label: 'view rate', kind: 'pct', v: (d) => div(d.video_views, d.video_impressions) },
    cpv: { label: 'CPV', kind: 'money3', v: (d) => div(d.spend, d.video_views) },
    cost_per_visit: { label: 'cost per visit', kind: 'money2', v: (d) => div(d.spend, d.sessions) },
  };
  // Metrics a Website card can put on the site trend line (per day or per plan week).
  const SITE_METRICS = {
    sessions: { label: 'visits', kind: 'abbr', v: (d) => d.sessions },
    engaged: { label: 'engaged sessions', kind: 'abbr', v: (d) => d.engaged_sessions },
    avg_time: { label: 'average engagement time', kind: 'secs', v: (d) => div(d.engagement_time_sec, d.sessions) },
    cost_per_visit: { label: 'cost per visit', kind: 'money2', v: (d) => div(d.spend, d.sessions) },
    downloads: { label: 'report downloads', kind: 'int', v: (d) => d.downloads },
    signups: { label: 'email sign-ups', kind: 'int', v: (d) => d.signups },
    donations: { label: 'donations', kind: 'int', v: (d) => d.donations },
    donation_value: { label: 'donated value', kind: 'money', v: (d) => d.donation_value },
  };
  // one channel-day bucket per (channel, date index) with every additive measure the metrics need
  function dayBuckets(w) {
    const m = {};
    const get = (c, i) => m[c + '|' + i] || (m[c + '|' + i] = { spend: 0, impressions: 0, clicks: 0, video_impressions: 0, video_views: 0, sessions: 0, engaged_sessions: 0, engagement_time_sec: 0, downloads: 0, signups: 0, donations: 0, donation_value: 0, reach: 0 });
    F(w).forEach((r) => { const b = get(r.channel, r._i); b.spend += r.spend; b.impressions += r.impressions; b.clicks += r.clicks; if (r.video_impressions != null) { b.video_impressions += r.video_impressions; b.video_views += r.video_views; } });
    S(w).forEach((r) => { const b = get(r.channel, r._i); SITE_KEYS.forEach((k) => { b[k] += r[k] || 0; }); });
    chanKeys().forEach((c) => { for (let i = w[0]; i <= w[1]; i++) get(c, i).reach += (RD[c] || [])[i] || 0; });
    return { get: (c, i) => m[c + '|' + i] || null };
  }
  function wireMetricCards(containerId, group, onChange) {
    const box = $(containerId); if (!box || box._bbMetricWired) return; box._bbMetricWired = true;
    const pick = (card) => { const k = card.getAttribute('data-metric'); if (!k || state[group + 'Metric'] === k) return; state[group + 'Metric'] = k;
      document.querySelectorAll(`.clk[data-group="${group}"]`).forEach((c) => { const on = c.getAttribute('data-metric') === k; c.classList.toggle('is-active', on); c.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      onChange(); };
    box.addEventListener('click', (e) => { const card = e.target.closest('.clk[data-metric]'); if (card) pick(card); });
    box.addEventListener('keydown', (e) => { if (e.key !== 'Enter' && e.key !== ' ') return; const card = e.target.closest('.clk[data-metric]'); if (card) { e.preventDefault(); pick(card); } });
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    let res;
    try {
      res = await fetch('data.json', { cache: 'no-store' });
      if (res.status === 401) { location.href = './'; return; }
      if (!res.ok) throw new Error('data.json returned ' + res.status);
      DATA = await res.json();
    } catch (e) { showError(e); return; }
    if (!DATA || !Array.isArray(DATA.facts) || !DATA.facts.length) { showError(new Error('payload has no delivery rows')); return; }
    index();
    reconcile();
    wireControls();
    const h = (location.hash || '').replace('#', '');
    switchTab(TABS.includes(h) ? h : 'overview', true);
    window.addEventListener('hashchange', () => { const t = (location.hash || '').replace('#', ''); if (TABS.includes(t) && t !== state.tab) switchTab(t, true); });
    window.FB_DASH = { state, setRange, toggleChannel, switchTab, ready: true };
  }
  function showError(e) {
    const c = $('loadError'); if (c) { c.hidden = false; $('loadErrorMsg').textContent = 'Please refresh the page. If it keeps happening, sign out and back in. (' + (e && e.message || 'unknown error') + ')'; }
    document.querySelectorAll('.tabpanel').forEach((t) => { t.hidden = true; });
  }
  function index() {
    const set = new Set(); DATA.facts.forEach((r) => set.add(r.date)); DATA.site_daily.forEach((r) => set.add(r.date));
    DATES = [...set].sort(); DATES.forEach((d, i) => { DIDX[d] = i; });
    DATA.facts.forEach((r) => { r._i = DIDX[r.date]; });
    DATA.site_daily.forEach((r) => { r._i = DIDX[r.date]; });
    DATA.channels.forEach((c) => { RD[c.key] = new Array(DATES.length).fill(0); state.channels.add(c.key); });
    DATA.reach_daily.forEach((r) => { if (RD[r.channel]) RD[r.channel][DIDX[r.date]] = r.reach; });
  }
  function reconcile() {
    // Dev-only cross-check of the fact table against the payload's own totals. Console, never page.
    try {
      const g = DATA.totals && DATA.totals.grand; if (!g) return;
      const a = agg(DATA.facts, FACT_KEYS); const s = agg(DATA.site_daily, SITE_KEYS);
      const bad = [];
      ['spend', 'impressions', 'clicks'].forEach((k) => { if (Math.abs(a[k] - g[k]) > 0.01) bad.push(`${k} ${a[k]} vs ${g[k]}`); });
      ['sessions', 'downloads', 'signups', 'donations'].forEach((k) => { if (s[k] !== g[k]) bad.push(`${k} ${s[k]} vs ${g[k]}`); });
      if (bad.length) console.warn('payload totals do not reconcile:', bad); else console.info('payload reconciles: facts and site rows sum to the stated totals');
    } catch (e) { /* diagnostics only */ }
  }

  // ------------------------------------------------------------------ controls
  function wireControls() {
    document.querySelectorAll('.tab-btn').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    document.querySelectorAll('#dateSeg .seg-btn').forEach((b) => b.addEventListener('click', () => setRange(b.dataset.range)));
    document.querySelectorAll('#siteGrain .seg-btn').forEach((b) => b.addEventListener('click', () => { state.siteGrain = b.dataset.grain; document.querySelectorAll('#siteGrain .seg-btn').forEach((x) => x.classList.toggle('is-active', x === b)); renderSiteTrend(windowIdx()); }));
    renderChips();
  }
  function setRange(r) {
    if (!['last7', 'last28', 'flight'].includes(r)) return;
    state.range = r;
    document.querySelectorAll('#dateSeg .seg-btn').forEach((b) => b.classList.toggle('is-active', b.dataset.range === r));
    invalidate();
  }
  function toggleChannel(key) {
    if (state.channels.has(key)) { if (state.channels.size === 1) return; state.channels.delete(key); } else state.channels.add(key);
    renderChips(); invalidate();
  }
  function renderChips() {
    const box = $('chanChips'); if (!box) return; box.innerHTML = '';
    DATA.channels.forEach((c, i) => {
      const on = state.channels.has(c.key); const locked = on && state.channels.size === 1;
      const b = el('button', 'chip ' + (on ? 'is-on' : 'is-off') + (locked ? ' is-locked' : ''));
      b.type = 'button'; b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.style.setProperty('--sw', chColor(c.key, i));
      b.title = locked ? 'At least one channel stays selected' : (on ? 'Hide ' : 'Show ') + c.name;
      b.innerHTML = `<span class="sw"></span>${esc(c.name)}`;
      b.addEventListener('click', () => toggleChannel(c.key));
      box.appendChild(b);
    });
  }
  function invalidate() { TABS.forEach((t) => dirty.add(t)); renderHero(); renderScope(); renderTab(state.tab); }

  function switchTab(name, fromHash) {
    if (!TABS.includes(name)) return;
    state.tab = name;
    document.body.classList.forEach((c) => { if (c.indexOf('tab-') === 0) document.body.classList.remove(c); });
    document.body.classList.add('tab-' + name);
    document.querySelectorAll('.tab-btn').forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); });
    document.querySelectorAll('.tabpanel').forEach((s) => { s.hidden = s.id !== 'tab-' + name; });
    const sec = $('tab-' + name); if (sec) { sec.classList.remove('tab-enter'); void sec.offsetWidth; sec.classList.add('tab-enter'); }
    $('hero').hidden = name !== 'overview';
    $('tabIntro').hidden = name === 'overview';
    if (name !== 'overview') { const [t, d] = TAB_INTRO[name]; $('tabIntroTitle').textContent = t; $('tabIntroDesc').textContent = d(DATA.channels.map((c) => c.name)); }
    $('filters').style.visibility = name === 'methodology' ? 'hidden' : 'visible';
    if (!fromHash || location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
    if (!dirty.size) TABS.forEach((t) => dirty.add(t));
    renderHero(); renderScope(); renderTab(name);
    if (!fromHash) window.scrollTo({ top: 0, behavior: 'auto' });
  }
  function renderTab(name) {
    if (!dirty.has(name)) return;
    const w = windowIdx();
    ({ overview: renderOverview, channels: renderChannels, audience: renderAudience, video: renderVideo, website: renderWebsite, pacing: renderPacing, methodology: renderMethodology })[name](w);
    dirty.delete(name);
  }

  // ------------------------------------------------------------------ hero + scope
  function flightStatus() {
    const start = parseD(DATA.meta.flight_start), end = parseD(DATA.meta.flight_end);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    if (today > end) return { label: 'Flight complete', short: 'Complete', days: 0, done: true };
    if (today < start) return { label: `Starts in ${Math.ceil((start - today) / 864e5)} days`, short: 'Not started', days: Math.ceil((end - today) / 864e5) + 1, done: false };
    const days = Math.ceil((end - today) / 864e5) + 1; return { label: `${days} day${days === 1 ? '' : 's'} remaining`, short: `${days} days left`, days, done: false };
  }
  function renderHero() {
    const m = DATA.meta; const w = windowIdx(); const f = F(w); const a = agg(f, FACT_KEYS); const s = agg(S(w), SITE_KEYS);
    $('topbarCampaign').textContent = m.campaign_name;
    $('heroEyebrow').textContent = `${BRAND.client || ''} · ${m.campaign_objective || 'Awareness'} campaign`;
    $('heroTitle').textContent = m.campaign_name;
    const weeks = Math.round(m.flight_days / 7); const st = flightStatus();
    $('heroFlight').innerHTML = `${esc(dLabel(m.flight_start, { dow: true }))} to ${esc(dLabel(m.flight_end, { dow: true, year: true }))} · ${weeks} weeks · ${DATA.channels.map((c) => esc(c.name)).join(', ')}<span class="flag">${esc(st.label)}</span>`;
    // budget: whole flight, selected channels (a budget is a flight-level figure; the window filter does not apply)
    const keys = chanKeys(); const planned = keys.reduce((t, k) => t + (DATA.plan.channel_budget[k] || 0), 0);
    const delivered = DATA.facts.filter(chanOk).reduce((t, r) => t + r.spend, 0);
    const pctD = planned ? delivered / planned : 0;
    $('hbVal').textContent = fmt.money(delivered, 0);
    $('hbFill').style.width = Math.min(100, pctD * 100).toFixed(1) + '%';
    $('hbSub').textContent = `${fmt.pct(pctD, 1)} of the ${fmt.money(planned, 0)} plan · whole flight${keys.length < DATA.channels.length ? ' · selected channels' : ''}`;
    const reach = reachFor(keys, w);
    const cards = [
      ['Reach', fmt.abbr(reach), keys.length > 1 ? 'people, de-duplicated across channels' : 'people reached', 'reach'],
      ['Impressions', fmt.abbr(a.impressions), `across ${keys.length} channel${keys.length === 1 ? '' : 's'}`, 'impressions'],
      ['Frequency', fmt.x(div(a.impressions, reach)), 'impressions per person reached', 'frequency'],
      ['Video views', fmt.abbr(a.video_views), a.video_views ? 'as each platform defines a view' : 'no video placements in this selection', 'video_views'],
      ['Website visits', fmt.abbr(s.sessions), 'campaign-attributed sessions', 'sessions'],
    ];
    $('heroKpis').innerHTML = cards.map(([l, v, sub, mk]) => { const on = state.ovMetric === mk; return `<div class="hero-kpi stat clk${on ? ' is-active' : ''}" data-metric="${mk}" data-group="ov" role="button" tabindex="0" aria-pressed="${on ? 'true' : 'false'}" title="Plot ${esc(l.toLowerCase())} on the daily chart"><div class="hero-num v">${v}</div><div class="hero-lab">${esc(l)}</div><div class="hero-sub">${esc(sub)}</div></div>`; }).join('');
    wireMetricCards('heroKpis', 'ov', () => renderDailyChart(windowIdx()));
  }
  function renderScope() {
    const w = windowIdx(); const names = chans().map((c) => c.name);
    const rl = state.range === 'last7' ? 'Last 7 days' : state.range === 'last28' ? 'Last 28 days' : 'Full flight';
    $('scopeLine').innerHTML = `Showing <b>${rl}</b> · ${esc(dLabel(DATES[w[0]], { dow: true }))} to ${esc(dLabel(DATES[w[1]], { dow: true, year: true }))} · ${w[1] - w[0] + 1} days · <b>${names.map(esc).join(', ')}</b>${state.tab === 'methodology' ? ' · filters do not apply on this tab' : ''}`;
  }

  // ------------------------------------------------------------------ OVERVIEW
  function momentBands(w) {
    return (DATA.meta.moments || []).map((m) => ({ from: DIDX[m.start], to: DIDX[m.end], label: m.label, kind: m.kind, color: m.kind === 'outcome' ? 'rgba(255,160,150,.14)' : 'rgba(103,30,117,.07)', edge: m.kind === 'outcome' ? 'rgba(196,69,59,.35)' : 'rgba(103,30,117,.35)' }))
      .filter((b) => b.to >= w[0] && b.from <= w[1]).map((b) => Object.assign({}, b, { from: b.from - w[0], to: b.to - w[0] }));
  }
  function renderOverview(w) {
    const f = F(w); const labels = DATES.slice(w[0], w[1] + 1);
    const A = agg(f, FACT_KEYS); const SS = agg(S(w), SITE_KEYS);
    const OV = (k) => ({ metric: k, group: 'ov' });
    $('ovKpis').innerHTML = kpi('Net media spend', fmt.money(A.spend, 0), 'delivered, selected window', OV('spend'))
      + kpi('CPM', fmt.money(div(A.spend, A.impressions) * 1000, 2), 'per 1,000 impressions', OV('cpm'))
      + kpi('Clicks', fmt.abbr(A.clicks), 'all selected channels', OV('clicks'))
      + kpi('CTR', fmt.pct(div(A.clicks, A.impressions)), 'clicks per impression', OV('ctr'))
      + kpi('CPC', fmt.money(div(A.spend, A.clicks), 2), 'per click', OV('cpc'))
      + kpi('View rate', fmt.pct(div(A.video_views, A.video_impressions)), 'views per video impression', OV('view_rate'))
      + kpi('CPV', fmt.money(div(A.spend, A.video_views), 3), 'per video view', OV('cpv'))
      + kpi('Cost per visit', fmt.money(div(A.spend, SS.sessions), 2), 'net media over visits', OV('cost_per_visit'));
    wireMetricCards('ovKpis', 'ov', () => renderDailyChart(windowIdx()));
    renderDailyChart(w);
    const bands = (DATA.meta.moments || []).filter((m) => DIDX[m.end] >= w[0] && DIDX[m.start] <= w[1]);
    $('momentsList').innerHTML = bands.map((m) => `<div class="moment kind-${esc(m.kind)}"><i></i><div><b>Week ${m.week} · ${esc(m.label)}</b>${esc(dLabel(m.start))} to ${esc(dLabel(m.end))}. ${esc(m.note)}</div></div>`).join('');

    // channel mix
    const rows = chans().map((c, i) => { const a = agg(f.filter((r) => r.channel === c.key), FACT_KEYS); return { key: c.key, i, name: c.name, spend: a.spend || 0, impressions: a.impressions || 0, cpm: div(a.spend, a.impressions) * 1000 }; });
    const tot = rows.reduce((t, r) => t + r.spend, 0);
    mk('chMix', { type: 'doughnut', data: { labels: rows.map((r) => r.name), datasets: [{ data: rows.map((r) => Math.round(r.spend)), backgroundColor: rows.map((r) => chColor(r.key, r.i)), borderColor: '#fff', borderWidth: 2, hoverOffset: 4 }] },
      options: { cutout: '68%', plugins: { bbCenter: { label: 'net media', mode: 'money' }, tooltip: { callbacks: { label: (c) => ` ${c.label}: ${fmt.money(c.parsed, 0)} (${fmt.pct(c.parsed / tot, 1)})` } } } } });
    table('tblMix', [
      { h: 'Channel', f: (r) => dot(r.key, r.i) + esc(r.name) },
      { h: 'Spend', n: true, f: (r) => fmt.money(r.spend, 0), t: (T) => fmt.money(T.spend, 0) },
      { h: 'Share', n: true, f: (r) => fmt.pct(tot ? r.spend / tot : 0, 1), t: () => '100%' },
      { h: 'Impressions', n: true, f: (r) => fmt.int(r.impressions), t: (T) => fmt.int(T.impressions) },
    ], rows, { total: rows.length > 1 ? { spend: tot, impressions: rows.reduce((t, r) => t + r.impressions, 0) } : null });

    // outcomes
    const a = agg(f, FACT_KEYS); const s = agg(S(w), SITE_KEYS);
    const oc = [
      ['Clicks', fmt.int(a.clicks), `CTR ${fmt.pct(div(a.clicks, a.impressions))} · CPC ${fmt.money(div(a.spend, a.clicks), 2)}`],
      ['Hunger Report downloads', fmt.int(s.downloads), `${fmt.money(div(a.spend, s.downloads), 2)} per download`],
      ['Email sign-ups', fmt.int(s.signups), `${fmt.money(div(a.spend, s.signups), 0)} per sign-up`],
      ['Donations', fmt.int(s.donations), `${fmt.money(s.donation_value, 0)} given · avg gift ${fmt.money(div(s.donation_value, s.donations), 2)}`],
    ];
    $('outcomes').innerHTML = oc.map(([l, v, sub]) => `<div class="outcome"><div class="kpi-lab">${esc(l)}</div><div class="kpi-val num">${v}</div><div class="kpi-sub">${esc(sub)}</div></div>`).join('');
    $('outcomesNote').textContent = 'Downloads, sign-ups and donations are attributed on a click and view-through basis from platform and site analytics. Donations are a supporting outcome of an awareness campaign, not a return on spend, and are not reported as a ratio.';
  }

  function renderDailyChart(w) {
    const met = OV_METRICS[state.ovMetric] || OV_METRICS.impressions;
    const labels = DATES.slice(w[0], w[1] + 1);
    const B = dayBuckets(w);
    const ds = chans().map((c, i) => ({ label: c.name, data: labels.map((d) => { const b = B.get(c.key, DIDX[d]); const v = b ? met.v(b) : null; return (v == null || !isFinite(v)) ? null : v; }),
      borderColor: chColor(c.key, i), backgroundColor: alpha(chColor(c.key, i), 0.08), borderWidth: 2.25, fill: true, tension: 0.3, spanGaps: false, pointRadius: 0, pointHoverRadius: 4, pointHoverBackgroundColor: chColor(c.key, i) }));
    const additive = !!ADDITIVE[met.kind];
    mk('chDaily', { type: 'line', data: { labels: labels.map((d) => dLabel(d)), datasets: ds }, options: {
      interaction: { mode: 'index', intersect: false },
      scales: { x: axisCat, y: { beginAtZero: true, grid: { drawTicks: false }, border: { display: false }, ticks: { callback: (v) => fmtKind(met.kind, v), maxTicksLimit: 7 } } },
      plugins: { bbMoments: { bands: momentBands(w) }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmtKind(met.kind === 'abbr' ? 'int' : met.kind, c.parsed.y)}`, footer: (items) => additive ? 'Total ' + fmtKind(met.kind === 'abbr' ? 'int' : met.kind, items.reduce((t, i) => t + (i.parsed.y || 0), 0)) : '' } } },
    } });
    $('dailyTitle').textContent = `Daily ${met.label} by channel`;
    $('dailySub').textContent = (additive ? 'One line per channel. ' : 'One line per channel; a day with no denominator is left blank, never drawn as zero. ') + 'Click any figure above to plot it here. The two shaded bands are the campaign moments the plan was built around.';
    $('dailyLegend').innerHTML = chans().map((c, i) => `<span><i style="background:${chColor(c.key, i)}"></i>${esc(c.name)}</span>`).join('');
  }

  // ------------------------------------------------------------------ CHANNELS
  function channelRow(c, i, f, s, w) {
    const a = agg(f.filter((r) => r.channel === c.key), FACT_KEYS); const t = agg(s.filter((r) => r.channel === c.key), SITE_KEYS);
    const reach = reachFor([c.key], w);
    return { key: c.key, i, name: c.name, a, t, reach, spend: a.spend || 0, impressions: a.impressions || 0, cpm: div(a.spend, a.impressions) * 1000, freq: div(a.impressions, reach), clicks: a.clicks || 0, ctr: div(a.clicks, a.impressions), cpc: div(a.spend, a.clicks), views: a.video_views, cpv: div(a.spend, a.video_views), vtr: div(a.video_views, a.video_impressions), sessions: t.sessions || 0, cpvisit: div(a.spend, t.sessions) };
  }
  function renderChannels(w) {
    const f = F(w), s = S(w);
    const rows = chans().map((c, i) => channelRow(c, i, f, s, w));
    const T = agg(f, FACT_KEYS); const TS = agg(s, SITE_KEYS); const TR = reachFor(chanKeys(), w);
    table('tblChannels', [
      { h: 'Channel', f: (r) => dot(r.key, r.i) + esc(r.name) },
      { h: 'Spend', n: true, f: (r) => fmt.money(r.spend, 0), t: () => fmt.money(T.spend, 0) },
      { h: 'Impressions', n: true, f: (r) => fmt.int(r.impressions), t: () => fmt.int(T.impressions) },
      { h: 'CPM', n: true, f: (r) => fmt.money(r.cpm, 2), t: () => fmt.money(div(T.spend, T.impressions) * 1000, 2) },
      { h: 'Reach', n: true, f: (r) => fmt.abbr(r.reach), t: () => fmt.abbr(TR) },
      { h: 'Frequency', n: true, f: (r) => fmt.x(r.freq), t: () => fmt.x(div(T.impressions, TR)) },
      { h: 'Clicks', n: true, f: (r) => fmt.int(r.clicks), t: () => fmt.int(T.clicks) },
      { h: 'CTR', n: true, f: (r) => fmt.pct(r.ctr), t: () => fmt.pct(div(T.clicks, T.impressions)) },
      { h: 'CPC', n: true, f: (r) => fmt.money(r.cpc, 2), t: () => fmt.money(div(T.spend, T.clicks), 2) },
      { h: 'Video views', n: true, f: (r) => fmt.int(r.views), t: () => fmt.int(T.video_views) },
      { h: 'View rate', n: true, f: (r) => fmt.pct(r.vtr), t: () => fmt.pct(div(T.video_views, T.video_impressions)) },
      { h: 'CPV', n: true, f: (r) => fmt.money(r.cpv, 3), t: () => fmt.money(div(T.spend, T.video_views), 3) },
      { h: 'Site visits', n: true, f: (r) => fmt.int(r.sessions), t: () => fmt.int(TS.sessions) },
      { h: 'Cost per visit', n: true, f: (r) => fmt.money(r.cpvisit, 2), t: () => fmt.money(div(T.spend, TS.sessions), 2) },
    ], rows, { total: rows.length > 1 ? {} : null });

    // small multiples on a shared y scale
    const labels = DATES.slice(w[0], w[1] + 1);
    const grid = $('smGrid'); grid.innerHTML = '';
    const series = rows.map((r) => { const m = {}; f.filter((x) => x.channel === r.key).forEach((x) => { m[x._i] = (m[x._i] || 0) + x.impressions; }); return labels.map((d) => m[DIDX[d]] || 0); });
    const ymax = Math.max(1, ...series.flat()) * 1.08;
    rows.forEach((r, i) => {
      const box = el('div', 'sm', `<div class="sm-head"><b>${dot(r.key, r.i)}${esc(r.name)}</b><span>${fmt.abbr(r.impressions)} impressions · ${fmt.money(r.cpm, 2)} CPM</span></div><div class="chart"><canvas id="sm_${esc(r.key)}"></canvas></div>`);
      grid.appendChild(box);
      mk('sm_' + r.key, { type: 'line', data: { labels: labels.map((d) => dLabel(d)), datasets: [{ data: series[i], borderColor: chColor(r.key, r.i), backgroundColor: alpha(chColor(r.key, r.i), 0.18), fill: true, tension: 0.32, borderWidth: 1.5 }] },
        options: { scales: { x: Object.assign({}, axisCat, { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 4 } }), y: Object.assign({ min: 0, max: ymax }, axisAbbr, { ticks: { callback: (v) => fmt.abbr(v), maxTicksLimit: 4 } }) }, plugins: { tooltip: { callbacks: { label: (c) => ' ' + fmt.int(c.parsed.y) } } } } });
    });

    // efficiency: CPM x CTR by placement, bubble = spend
    const pl = {}; f.forEach((r) => { const k = r.channel + '|' + r.placement; const o = pl[k] || (pl[k] = { channel: r.channel, placement: r.placement, spend: 0, imps: 0, clicks: 0 }); o.spend += r.spend; o.imps += r.impressions; o.clicks += r.clicks; });
    const pts = Object.values(pl); const maxS = Math.max(1, ...pts.map((p) => p.spend));
    const dsets = chans().map((c, i) => { const mine = pts.filter((p) => p.channel === c.key); return { label: c.name, data: mine.map((p) => ({ x: p.spend / p.imps * 1000, y: p.clicks / p.imps * 100, r: 6 + 22 * Math.sqrt(p.spend / maxS), _p: p })), backgroundColor: alpha(chColor(c.key, i), 0.7), borderColor: chColor(c.key, i), borderWidth: 1.5, _labels: mine.map((p) => p.placement) }; });
    mk('chEff', { type: 'bubble', data: { datasets: dsets }, options: {
      scales: { x: Object.assign({ title: { display: true, text: 'CPM (cost per thousand impressions)' }, beginAtZero: true }, axisMoney, { ticks: { callback: (v) => fmt.money(v, 0) } }), y: Object.assign({ title: { display: true, text: 'Click-through rate' }, beginAtZero: true }, { ticks: { callback: (v) => v.toFixed(2) + '%' }, grid: { drawTicks: false }, border: { display: false } }) },
      layout: { padding: { right: 120, top: 12 } },
      plugins: { bbBubbleLabels: { labels: dsets.map((d) => d._labels) }, tooltip: { callbacks: { title: (items) => items.length ? items[0].raw._p.placement : '', label: (c) => { const p = c.raw._p; return [` ${chanName(p.channel)}`, ` Spend ${fmt.money(p.spend, 0)}`, ` CPM ${fmt.money(c.parsed.x, 2)} · CTR ${fmt.pct(c.parsed.y / 100)}`]; } } } },
    } });
  }

  // ------------------------------------------------------------------ AUDIENCE
  function weightedShares(dim, weights) {
    // weights: {channelKey: weight}; returns [{label, share}] weighted across selected channels
    const labels = DATA.splits.dimensions[dim]; const tot = Object.values(weights).reduce((t, v) => t + v, 0) || 1;
    return labels.map((lab) => ({ label: lab, share: Object.keys(weights).reduce((t, k) => t + (DATA.splits.by_channel[k][dim][lab] || 0) * weights[k], 0) / tot }));
  }
  function renderAudience(w) {
    const f = F(w); const keys = chanKeys(); const a = agg(f, FACT_KEYS);
    const reach = reachFor(keys, w); const freq = div(a.impressions, reach);
    const impW = {}; keys.forEach((k) => { impW[k] = f.filter((r) => r.channel === k).reduce((t, r) => t + r.impressions, 0); });
    const reachW = {}; keys.forEach((k) => { reachW[k] = reachFor([k], w); });
    const fr = weightedShares('frequency', reachW); const onceShare = fr.find((x) => x.label === '1x');
    const stTop = weightedShares('state', impW).slice().sort((p, q) => q.share - p.share)[0];
    $('audKpis').innerHTML = kpi('People reached', fmt.abbr(reach), keys.length > 1 ? 'de-duplicated across channels' : 'platform-reported')
      + kpi('Impressions', fmt.abbr(a.impressions), 'in this window')
      + kpi('Average frequency', fmt.x(freq), 'impressions per person')
      + kpi('Reached once only', fmt.pct(onceShare ? onceShare.share : null, 0), 'share of people reached')
      + kpi('Reached 4 or more times', fmt.pct(fr.filter((x) => ['4-6x', '7-10x', '11+'].includes(x.label)).reduce((t, x) => t + x.share, 0), 0), 'the effective-frequency band')
      + kpi('Largest region', stTop ? stTop.label : '-', stTop ? `${fmt.pct(stTop.share, 0)} of impressions` : '');

    // reach curve: flight-to-date, cropped to the window; recomputed for the selected channels
    const labels = DATES.slice(w[0], w[1] + 1);
    const cum = labels.map((d, j) => reachFor(keys, [0, w[0] + j]));
    let ci = 0; const cumImps = labels.map((d, j) => { ci += DATA.facts.filter((r) => r._i === w[0] + j && chanOk(r)).reduce((t, r) => t + r.impressions, 0); return ci; });
    // impressions accrued before the window start (so frequency is flight-to-date, like reach)
    const pre = DATA.facts.filter((r) => r._i < w[0] && chanOk(r)).reduce((t, r) => t + r.impressions, 0);
    mk('chReachCurve', { type: 'line', data: { labels: labels.map((d) => dLabel(d)), datasets: [
      { label: 'Cumulative reach', data: cum, borderColor: CH_COLOR.meta, backgroundColor: alpha(CH_COLOR.meta, 0.12), fill: true, tension: 0.3, yAxisID: 'y' },
      { label: 'Frequency', data: cum.map((r, j) => r ? (pre + cumImps[j]) / r : null), borderColor: '#C4453B', borderDash: [5, 4], borderWidth: 1.5, tension: 0.3, yAxisID: 'y2' },
    ] }, options: { interaction: { mode: 'index', intersect: false }, scales: { x: axisCat, y: Object.assign({ beginAtZero: true, title: { display: true, text: 'People reached' } }, axisAbbr), y2: { position: 'right', beginAtZero: true, grid: { display: false }, border: { display: false }, title: { display: true, text: 'Frequency' }, ticks: { callback: (v) => v.toFixed(1) + 'x' } } },
      plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'rectRounded' } }, tooltip: { callbacks: { label: (c) => c.datasetIndex === 0 ? ` Reach ${fmt.abbr(c.parsed.y)}` : ` Frequency ${fmt.x(c.parsed.y)}` } } } } });

    mk('chFreq', { type: 'bar', data: { labels: fr.map((x) => x.label), datasets: [{ data: fr.map((x) => Math.round(x.share * reach)), backgroundColor: fr.map((x, i) => SEQ[Math.min(i, 3)]), borderRadius: 3 }] },
      options: { scales: { x: Object.assign({}, axisCat, { title: { display: true, text: 'Times seen' } }), y: Object.assign({ beginAtZero: true }, axisAbbr) }, layout: { padding: { top: 18 } }, plugins: { bbValues: { mode: 'int', labels: fr.map((x) => fmt.pct(x.share, 0)) }, tooltip: { callbacks: { label: (c) => ` ${fmt.abbr(c.parsed.y)} people (${fmt.pct(fr[c.dataIndex].share, 1)})` } } } } });

    const st = weightedShares('state', impW).sort((p, q) => q.share - p.share);
    mk('chStates', { type: 'bar', data: { labels: st.map((x) => x.label), datasets: [{ data: st.map((x) => Math.round(x.share * a.impressions)), backgroundColor: CH_COLOR.meta, borderRadius: 3, barThickness: 22 }] },
      options: { indexAxis: 'y', scales: { x: Object.assign({ beginAtZero: true }, axisAbbr), y: { grid: { display: false }, border: { display: false } } }, layout: { padding: { right: 90 } }, plugins: { bbValues: { mode: 'int', labels: st.map((x) => `${fmt.abbr(x.share * a.impressions)} · ${fmt.pct(x.share, 0)}`) }, tooltip: { callbacks: { label: (c) => ` ${fmt.int(c.parsed.x)} impressions` } } } } });

    const ag = weightedShares('age', impW);
    mk('chAge', { type: 'bar', data: { labels: ag.map((x) => x.label), datasets: [{ data: ag.map((x) => Math.round(x.share * a.impressions)), backgroundColor: CH_COLOR.programmatic, borderColor: CH_COLOR.meta, borderWidth: 1, borderRadius: 3 }] },
      options: { scales: { x: axisCat, y: Object.assign({ beginAtZero: true }, axisAbbr) }, layout: { padding: { top: 18 } }, plugins: { bbValues: { mode: 'int', labels: ag.map((x) => fmt.pct(x.share, 0)) }, tooltip: { callbacks: { label: (c) => ` ${fmt.int(c.parsed.y)} impressions` } } } } });

    const donut = (id, dim, colors) => {
      const sh = weightedShares(dim, impW).filter((x) => x.share > 0);
      mk(id, { type: 'doughnut', data: { labels: sh.map((x) => `${x.label}  ${fmt.pct(x.share, 0)}`), datasets: [{ data: sh.map((x) => Math.round(x.share * a.impressions)), backgroundColor: sh.map((x, i) => colors[i % colors.length]), borderColor: '#fff', borderWidth: 2 }] },
        options: { cutout: '64%', layout: { padding: 8 }, plugins: { legend: { display: true, position: 'right', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'circle', padding: 14 } }, bbCenter: { label: 'impressions', mode: 'abbr' }, tooltip: { callbacks: { label: (c) => ` ${fmt.int(c.parsed)} impressions` } } } } });
    };
    donut('chGender', 'gender', [CH_COLOR.meta, CH_COLOR.programmatic, '#D9CFDC']);
    donut('chDevice', 'device', [CH_COLOR.meta, CH_COLOR.youtube, CH_COLOR.programmatic, '#8A4A96']);
  }

  // ------------------------------------------------------------------ VIDEO + CREATIVE
  function renderVideo(w) {
    const f = F(w); const a = agg(f, FACT_KEYS);
    const vt = a.video_views ? div(a.video_views, a.video_impressions) : null;
    $('vidKpis').innerHTML = kpi('Video impressions', fmt.abbr(a.video_impressions), a.impressions ? `${fmt.pct(div(a.video_impressions, a.impressions), 0)} of all impressions` : '') + kpi('Video views', fmt.abbr(a.video_views), 'as each platform defines a view') + kpi('View rate', fmt.pct(vt), 'views per video impression') + kpi('Cost per view', fmt.money(div(a.spend, a.video_views), 3), 'video spend is not isolated - blended') + kpi('Played to completion', fmt.pct(div(a.q100, a.video_impressions)), 'share of video impressions');

    const fun = [['Video impressions', a.video_impressions], ['Played to 25%', a.q25], ['Played to 50%', a.q50], ['Played to 75%', a.q75], ['Played to 100%', a.q100]];
    mk('chFunnel', { type: 'bar', data: { labels: fun.map((x) => x[0]), datasets: [{ data: fun.map((x) => x[1] || 0), backgroundColor: [CH_COLOR.meta, SEQ[1], SEQ[2], SEQ[3], CH_COLOR.youtube], borderRadius: 3, barThickness: 26 }] },
      options: { indexAxis: 'y', scales: { x: Object.assign({ beginAtZero: true }, axisAbbr), y: { grid: { display: false }, border: { display: false } } }, layout: { padding: { right: 110 } },
        plugins: { bbValues: { mode: 'int', labels: fun.map((x) => `${fmt.abbr(x[1])} · ${fmt.pct(div(x[1], a.video_impressions), 0)}`) }, tooltip: { callbacks: { label: (c) => ` ${fmt.int(c.parsed.x)} (${fmt.pct(div(c.parsed.x, a.video_impressions), 1)} of video impressions)` } } } } });

    const pl = {}; f.forEach((r) => { if (r.video_impressions == null) return; const k = r.channel + '|' + r.placement; const o = pl[k] || (pl[k] = { channel: r.channel, placement: r.placement, spend: 0, imps: 0, vimps: 0, views: 0, q100: 0 }); o.spend += r.spend; o.imps += r.impressions; o.vimps += r.video_impressions; o.views += r.video_views; o.q100 += r.q100; });
    const prow = Object.values(pl).map((p) => Object.assign(p, { i: DATA.channels.findIndex((c) => c.key === p.channel) })).sort((p, q) => q.vimps - p.vimps);
    table('tblPlacements', [
      { h: 'Placement', f: (r) => esc(r.placement) },
      { h: 'Channel', f: (r) => dot(r.channel, r.i) + esc(chanName(r.channel)) },
      { h: 'Video impressions', n: true, f: (r) => fmt.int(r.vimps), t: () => fmt.int(a.video_impressions) },
      { h: 'Views', n: true, f: (r) => fmt.int(r.views), t: () => fmt.int(a.video_views) },
      { h: 'View rate', n: true, f: (r) => fmt.pct(div(r.views, r.vimps)), t: () => fmt.pct(vt) },
      { h: 'Completion', n: true, f: (r) => fmt.pct(div(r.q100, r.vimps)), t: () => fmt.pct(div(a.q100, a.video_impressions)) },
      { h: 'CPM', n: true, f: (r) => fmt.money(div(r.spend, r.imps) * 1000, 2), t: () => '' },
    ], prow, { total: prow.length > 1 ? {} : null });

    // creatives: aggregate over window; variance vs own channel in the same window
    const chAgg = {}; chanKeys().forEach((k) => { chAgg[k] = agg(f.filter((r) => r.channel === k), FACT_KEYS); });
    const cr = {}; f.forEach((r) => { const o = cr[r.creative_id] || (cr[r.creative_id] = { id: r.creative_id, channel: r.channel, spend: 0, imps: 0, clicks: 0, vimps: null, views: null }); o.spend += r.spend; o.imps += r.impressions; o.clicks += r.clicks; if (r.video_impressions != null) { o.vimps = (o.vimps || 0) + r.video_impressions; o.views = (o.views || 0) + r.video_views; } });
    const crow = Object.values(cr).map((c) => { const d = DATA.creatives.find((x) => x.id === c.id) || {}; const ch = chAgg[c.channel]; const ctr = div(c.clicks, c.imps), chCtr = div(ch.clicks, ch.impressions); const vtr = div(c.views, c.vimps), chVtr = div(ch.video_views, ch.video_impressions); return Object.assign(c, { name: d.name || c.id, format: d.format || '', i: DATA.channels.findIndex((x) => x.key === c.channel), ctr, vtr, cpm: div(c.spend, c.imps) * 1000, dCtr: chCtr ? ctr / chCtr - 1 : null, dVtr: (vtr != null && chVtr) ? vtr / chVtr - 1 : null }); }).sort((p, q) => q.imps - p.imps).slice(0, 12);
    table('tblCreatives', [
      { h: 'Creative', f: (r) => `<span class="creative">${esc(r.name)}</span>` },
      { h: 'Channel', f: (r) => dot(r.channel, r.i) + esc(chanName(r.channel)) },
      { h: 'Format', f: (r) => `<span class="muted">${esc(r.format)}</span>` },
      { h: 'Impressions', n: true, f: (r) => fmt.int(r.imps) },
      { h: 'CPM', n: true, f: (r) => fmt.money(r.cpm, 2) },
      { h: 'CTR', n: true, f: (r) => fmt.pct(r.ctr) },
      { h: 'vs channel', n: true, f: (r) => chip(r.dCtr) },
      { h: 'View rate', n: true, f: (r) => r.vtr == null ? '<span class="muted">-</span>' : fmt.pct(r.vtr) },
      { h: 'vs channel', n: true, f: (r) => r.vtr == null ? '<span class="muted">-</span>' : chip(r.dVtr) },
    ], crow);
  }

  // ------------------------------------------------------------------ WEBSITE + ACTIONS
  function renderWebsite(w) {
    const f = F(w); const s = S(w); const a = agg(f, FACT_KEYS); const t = agg(s, SITE_KEYS);
    const SM = (k) => ({ metric: k, group: 'site' });
    $('siteKpis').innerHTML = kpi('Website visits', fmt.abbr(t.sessions), 'campaign-attributed sessions', SM('sessions'))
      + kpi('Engaged sessions', fmt.abbr(t.engaged_sessions), `${fmt.pct(div(t.engaged_sessions, t.sessions), 0)} of visits`, SM('engaged'))
      + kpi('Average engagement time', fmt.secs(div(t.engagement_time_sec, t.sessions)), 'per session', SM('avg_time'))
      + kpi('Cost per visit', fmt.money(div(a.spend, t.sessions), 2), 'net media over visits', SM('cost_per_visit'))
      + kpi('Report downloads', fmt.int(t.downloads), `${fmt.money(div(a.spend, t.downloads), 0)} each`, SM('downloads'))
      + kpi('Email sign-ups', fmt.int(t.signups), `${fmt.money(div(a.spend, t.signups), 0)} each`, SM('signups'))
      + kpi('Donations', fmt.int(t.donations), `${fmt.money(div(a.spend, t.donations), 0)} each`, SM('donations'))
      + kpi('Donated', fmt.money(t.donation_value, 0), `average gift ${fmt.money(div(t.donation_value, t.donations), 2)}`, SM('donation_value'));
    wireMetricCards('siteKpis', 'site', () => renderSiteTrend(windowIdx()));
    renderSiteTrend(w);

    const steps = [['Website visits', t.sessions, null], ['Hunger Report downloads', t.downloads, t.sessions], ['Email sign-ups', t.signups, t.downloads], ['Donations', t.donations, t.signups]];
    const mx = Math.max(1, t.sessions || 1);
    $('actionFunnel').innerHTML = steps.map(([l, v, prev], i) => {
      const width = Math.max(6, 100 * Math.pow((v || 0) / mx, 0.5));
      const rate = prev ? `<span class="rate">${fmt.pct(div(v, prev), 1)} of previous step</span>` : '<span class="rate">start of the funnel</span>';
      const cpa = `<div class="cpa">${fmt.money(div(a.spend, v), i === 0 ? 2 : 0)} per ${['visit', 'download', 'sign-up', 'donation'][i]}</div>`;
      return `<div class="astep"><div class="bar"><i style="width:${width.toFixed(1)}%"></i></div><div class="kpi-lab">${esc(l)}</div><div class="kpi-val num">${fmt.int(v)}</div>${rate}${cpa}</div>`;
    }).join('');
    $('donationNote').textContent = `${fmt.int(t.donations)} donations gave ${fmt.money(t.donation_value, 0)} (average gift ${fmt.money(div(t.donation_value, t.donations), 2)}). Donations are counted where a donor saw or clicked campaign media before giving, which includes view-through attribution. They are a supporting outcome of an awareness campaign and are not reported as a return on ad spend.`;
  }
  function renderSiteTrend(w) {
    const f = F(w); const s = S(w);
    const met = SITE_METRICS[state.siteMetric] || SITE_METRICS.sessions;
    const zero = () => ({ spend: 0, impressions: 0, sessions: 0, engaged_sessions: 0, engagement_time_sec: 0, downloads: 0, signups: 0, donations: 0, donation_value: 0 });
    const addF = (b, r) => { b.spend += r.spend; b.impressions += r.impressions; };
    const addS = (b, r) => { SITE_KEYS.forEach((k) => { b[k] += r[k] || 0; }); };
    let labels, buckets;
    if (state.siteGrain === 'week') {
      const wks = weeksIn(w); labels = wks.map((k) => `Week ${k.week}`);
      buckets = wks.map((k) => { const b = zero(); f.forEach((r) => { if (r._i >= DIDX[k.start] && r._i <= DIDX[k.end]) addF(b, r); }); s.forEach((r) => { if (r._i >= DIDX[k.start] && r._i <= DIDX[k.end]) addS(b, r); }); return b; });
    } else {
      const ds = DATES.slice(w[0], w[1] + 1); labels = ds.map((d) => dLabel(d));
      const m = {}; ds.forEach((d) => { m[DIDX[d]] = zero(); });
      f.forEach((r) => { if (m[r._i]) addF(m[r._i], r); }); s.forEach((r) => { if (m[r._i]) addS(m[r._i], r); });
      buckets = ds.map((d) => m[DIDX[d]]);
    }
    const line = buckets.map((b) => { const v = met.v(b); return (v == null || !isFinite(v)) ? null : v; });
    const imps = buckets.map((b) => b.impressions);
    const lab = met.label.charAt(0).toUpperCase() + met.label.slice(1);
    mk('chSiteTrend', { type: 'bar', data: { labels, datasets: [
      { type: 'line', label: lab, data: line, borderColor: CH_COLOR.meta, backgroundColor: CH_COLOR.meta, tension: 0.3, yAxisID: 'y', order: 0, spanGaps: false, pointRadius: state.siteGrain === 'week' ? 3 : 0 },
      { type: 'bar', label: 'Impressions', data: imps, backgroundColor: alpha(CH_COLOR.programmatic, 0.55), borderRadius: 3, yAxisID: 'y2', order: 1 },
    ] }, options: { interaction: { mode: 'index', intersect: false }, scales: { x: axisCat, y: { beginAtZero: true, title: { display: true, text: lab }, grid: { drawTicks: false }, border: { display: false }, ticks: { callback: (v) => fmtKind(met.kind, v), maxTicksLimit: 7 } }, y2: Object.assign({ position: 'right', beginAtZero: true, grid: { display: false }, title: { display: true, text: 'Impressions' } }, { ticks: { callback: (v) => fmt.abbr(v) }, border: { display: false } }) },
      plugins: { bbMoments: state.siteGrain === 'day' ? { bands: momentBands(w) } : {}, legend: { display: true, position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'rectRounded' } }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.datasetIndex === 0 ? fmtKind(met.kind === 'abbr' ? 'int' : met.kind, c.parsed.y) : fmt.int(c.parsed.y)}` } } } } });
    const tt = $('siteTrendTitle'); if (tt) tt.textContent = `Website ${met.label} against impressions`;
    const ts = $('siteTrendSub'); if (ts) ts.textContent = `Campaign-attributed ${met.label} (line) over the impressions that drove them (bars). Click a figure above to plot it instead.`;
  }

  // ------------------------------------------------------------------ PACING
  function renderPacing(w) {
    const keys = chanKeys(); const wks = weeksIn(w); const f = F(w);
    const rows = wks.map((k) => { const planned = keys.reduce((t, c) => t + (k.planned[c] || 0), 0); const del = f.filter((r) => r._i >= DIDX[k.start] && r._i <= DIDX[k.end]).reduce((t, r) => t + r.spend, 0); return { week: k.week, start: k.start, end: k.end, planned, delivered: del, byCh: keys.map((c) => ({ key: c, planned: k.planned[c] || 0, delivered: f.filter((r) => r.channel === c && r._i >= DIDX[k.start] && r._i <= DIDX[k.end]).reduce((t, r) => t + r.spend, 0) })) }; });
    const P = rows.reduce((t, r) => t + r.planned, 0), D = rows.reduce((t, r) => t + r.delivered, 0);
    const st = flightStatus();
    const varRows = rows.filter((r) => r.planned).map((r) => ({ week: r.week, v: r.delivered / r.planned - 1 }));
    const within = varRows.filter((r) => Math.abs(r.v) <= 0.05).length;
    const best = varRows.length ? varRows.reduce((m, r) => (r.v > m.v ? r : m)) : null;
    const weakest = varRows.length ? varRows.reduce((m, r) => (r.v < m.v ? r : m)) : null;
    $('paceKpis').innerHTML = kpi('Delivered', fmt.money(D, 0), 'net media, selected window')
      + kpi('Planned', fmt.money(P, 0), `${wks.length} plan week${wks.length === 1 ? '' : 's'}`)
      + kpi('Variance', fmt.delta(P ? D / P - 1 : null, 1), P ? `${fmt.money(D - P, 0)} against plan` : '')
      + kpi('Flight status', st.short, st.done ? `ended ${dLabel(DATA.meta.flight_end, { year: true })}` : `ends ${dLabel(DATA.meta.flight_end, { year: true })}`)
      + kpi('Average week', fmt.money(rows.length ? D / rows.length : null, 0), 'delivered per week')
      + kpi('Weeks within 5% of plan', varRows.length ? `${within} of ${varRows.length}` : '-', 'delivered inside tolerance')
      + kpi('Best week vs plan', best ? fmt.delta(best.v, 0) : '-', best ? `week ${best.week}` : '')
      + kpi('Weakest week vs plan', weakest ? fmt.delta(weakest.v, 0) : '-', weakest ? `week ${weakest.week}` : '');

    mk('chPacing', { type: 'bar', data: { labels: rows.map((r) => `Week ${r.week}`), datasets: [
      { label: 'Planned', data: rows.map((r) => r.planned), backgroundColor: alpha(CH_COLOR.programmatic, 0.9), borderRadius: 3 },
      { label: 'Delivered', data: rows.map((r) => r.delivered), backgroundColor: CH_COLOR.meta, borderRadius: 3 },
    ] }, options: { scales: { x: axisCat, y: Object.assign({ beginAtZero: true }, axisMoney) }, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'rectRounded' } }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt.money(c.parsed.y, 0)}`, footer: (items) => { const r = rows[items[0].dataIndex]; return `Variance ${fmt.delta(r.planned ? r.delivered / r.planned - 1 : null, 1)}`; } } } } } });

    let cp = 0, cd = 0;
    mk('chCumulative', { type: 'line', data: { labels: rows.map((r) => `Week ${r.week}`), datasets: [
      { label: 'Planned (cumulative)', data: rows.map((r) => (cp += r.planned)), borderColor: 'rgba(51,35,54,.45)', borderDash: [6, 4], borderWidth: 1.5, tension: 0.2 },
      { label: 'Delivered (cumulative)', data: rows.map((r) => (cd += r.delivered)), borderColor: CH_COLOR.meta, backgroundColor: alpha(CH_COLOR.meta, 0.12), fill: true, tension: 0.2, pointRadius: 3 },
    ] }, options: { interaction: { mode: 'index', intersect: false }, scales: { x: axisCat, y: Object.assign({ beginAtZero: true }, axisMoney) }, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'rectRounded' } }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt.money(c.parsed.y, 0)}` } } } } });

    const cols = [{ h: 'Week', f: (r) => `<b>Week ${r.week}</b><span class="muted wk-dates">${esc(dLabel(r.start))} to ${esc(dLabel(r.end))}</span>` }];
    keys.forEach((c, i) => {
      cols.push({ h: `${chanName(c)} plan`, n: true, f: (r) => fmt.money(r.byCh[i].planned, 0), t: () => fmt.money(rows.reduce((t, r) => t + r.byCh[i].planned, 0), 0) });
      cols.push({ h: `${chanName(c)} actual`, n: true, f: (r) => fmt.money(r.byCh[i].delivered, 0), t: () => fmt.money(rows.reduce((t, r) => t + r.byCh[i].delivered, 0), 0) });
      cols.push({ h: 'Variance', n: true, f: (r) => chip(r.byCh[i].planned ? r.byCh[i].delivered / r.byCh[i].planned - 1 : null, { band: 0.05 }), t: () => { const p = rows.reduce((t, r) => t + r.byCh[i].planned, 0), d = rows.reduce((t, r) => t + r.byCh[i].delivered, 0); return chip(p ? d / p - 1 : null, { band: 0.05 }); } });
    });
    cols.push({ h: 'Total plan', n: true, f: (r) => fmt.money(r.planned, 0), t: () => fmt.money(P, 0) });
    cols.push({ h: 'Total actual', n: true, f: (r) => fmt.money(r.delivered, 0), t: () => fmt.money(D, 0) });
    cols.push({ h: 'Variance', n: true, f: (r) => chip(r.planned ? r.delivered / r.planned - 1 : null, { band: 0.05 }), t: () => chip(P ? D / P - 1 : null, { band: 0.05 }) });
    table('tblPacing', cols, rows, { total: rows.length > 1 ? {} : null });
  }

  // ------------------------------------------------------------------ METHODOLOGY
  function renderMethodology() {
    const m = DATA.meta;
    const vdefs = DATA.channels.map((c) => `${c.name}: ${c.video_views_definition}`).join('. ');
    const viewCh = DATA.channels.filter((c) => c.reports_viewability).map((c) => c.name);
    const defs = [
      ['Impressions', 'Times an ad was served, as reported by each platform. Summed across channels with no de-duplication.', 'Meta Ads Manager, Google Ads (YouTube), DSP reporting'],
      ['Reach', 'Unique people who saw at least one ad. Within a channel, reach is platform-reported. Across channels it is de-duplicated with a cross-channel overlap factor, so the combined figure is lower than the sum of the channels and is an estimate.', 'Platform reach + overlap model'],
      ['Frequency', 'Impressions divided by reach for the same channels and date window.', 'Derived'],
      ['CPM', 'Net media spend divided by impressions, per thousand. Spend is net media, excluding fees and production.', 'Derived'],
      ['Clicks and CTR', 'Clicks on an ad, and clicks divided by impressions. Click-through rates on awareness formats are small by design; compare within a channel, not across channels.', 'Platform reporting'],
      ['Video views and view rate', `A view is counted the way each platform defines it, so views are not identical units across channels. ${vdefs}. View rate is views divided by video impressions.`, 'Platform reporting'],
      ['Completion (25 / 50 / 75 / 100%)', 'Video impressions that played to each quartile, summed across video placements and shown as a share of video impressions. Static and carousel placements carry no video metrics and are excluded, not counted as zero.', 'Platform reporting'],
      ['Viewability', `Share of impressions measured as viewable (MRC standard). Reported for ${viewCh.length ? listNames(viewCh) : 'no channel'} only; the other channels do not report MRC viewability in this feed and are shown as not measured rather than as zero.`, 'DSP reporting'],
      ['Website visits and engaged sessions', 'Sessions attributed to the campaign in site analytics, by channel. An engaged session lasted 10 seconds or more, had two or more page views, or included a key event. Average engagement time is total engagement time divided by sessions.', 'Site analytics (GA4)'],
      ['Downloads, sign-ups, donations', 'Site actions attributed to the campaign on a click or view-through basis. Cost per action is net media divided by the action count for the same channels and window. Donation value is the sum of gifts attributed the same way; it is not a return on ad spend and is never shown as a ratio.', 'Site analytics + platform conversions'],
      ['Plan and pacing', 'Planned spend is the media plan by week and channel. Delivered is actual net media. Variance is delivered less planned as a share of planned. A window that starts or ends mid-week is compared with the whole plan weeks it overlaps.', 'Media plan, platform billing'],
      ['Formatting', `Currency is ${m.currency} shown as ${m.currency_prefix}. Percentages are shown to one decimal place, or two below one percent. Large counts are abbreviated (K, M) in headline figures and shown in full in tables.`, 'Presentation'],
    ];
    $('tblDefs').innerHTML = '<thead><tr><th>Metric</th><th>Definition</th><th>Source</th></tr></thead><tbody>' + defs.map((d) => `<tr><td>${esc(d[0])}</td><td>${esc(d[1])}</td><td>${esc(d[2])}</td></tr>`).join('') + '</tbody>';
    $('methCaveats').innerHTML = [
      '<b>View-through attribution.</b> Outcomes counted after an ad was seen but not clicked depend on each platform\'s attribution window and cannot be verified independently. Read them as directional.',
      '<b>Reach is estimated across channels.</b> Platforms do not share user identity, so combined reach applies an overlap factor rather than a true match. Channel-level reach is platform-reported.',
      '<b>Views are not one unit.</b> A Meta ThruPlay, a YouTube view and a completed programmatic video are measured differently. Cost per view is blended for convenience and should be compared within a channel.',
      '<b>Audience splits are platform-reported</b> and rely on declared or modelled demographics. Small segments are directional.',
      '<b>Regions</b> follow Foodbank\'s own state structure (NSW-ACT, VIC, QLD, WA, SA-NT, TAS), resolved from platform location reporting.',
    ].map((x) => `<li>${x}</li>`).join('');
    $('methCampaign').innerHTML = [
      `<b>Campaign.</b> ${esc(m.campaign_name)}, ${esc(m.campaign_objective || 'awareness')} objective, ${esc(dLabel(m.flight_start, { dow: true }))} to ${esc(dLabel(m.flight_end, { dow: true, year: true }))} (${m.flight_days} days). Net media budget ${fmt.money(m.budget_planned, 0)} across ${DATA.channels.map((c) => esc(c.name)).join(', ')}.`,
      `<b>Agency of record.</b> ${esc(BRAND.agency || '')} planned and bought this campaign for ${esc(BRAND.client || '')} and produces this reporting.`,
      `<b>Refresh.</b> A live dashboard refreshes within about ten minutes of each platform's reporting update, and shows the date its data runs to.${m.data_mode === 'sample' ? ' This preview shows data to ' + esc(dLabel(m.data_through, { year: true })) + '.' : ''}`,
      m.data_mode === 'sample' ? `<b>Sample data.</b> ${esc(m.illustrative_note || 'Every figure here is illustrative.')}` : '',
    ].filter(Boolean).map((x) => `<li>${x}</li>`).join('');
  }

  // ------------------------------------------------------------------ vendored: sortable tables (canonical copy: client_resetdata)
  (function () {
    const parseNum = (t) => { const x = String(t == null ? '' : t).replace(/,/g, '').replace(/[^0-9.\-]/g, ''); if (x === '' || x === '-' || x === '.' || x === '-.') return NaN; const v = parseFloat(x); return isNaN(v) ? NaN : v; };
    const headerRow = (t) => { const rs = [...t.rows]; return rs.find((r) => r.querySelector('th')) || rs[0] || null; };
    const isTotal = (r) => { const c = r.cells[0]; if (!c) return false; if ((c.textContent || '').trim().toLowerCase().startsWith('total')) return true; return r.classList.contains('total') || c.classList.contains('total'); };
    const dataRows = (t, h) => [...t.rows].filter((r) => r !== h && !r.querySelector('th') && !isTotal(r));
    const totalRows = (t, h) => [...t.rows].filter((r) => r !== h && r.querySelector('td') && isTotal(r));
    function decorate(t, h, col, dir) { if (!h) return; [...h.cells].forEach((th, i) => { let base = th.getAttribute('data-bbl'); if (base == null) { base = th.innerHTML; th.setAttribute('data-bbl', base); } th.innerHTML = (i === col) ? base + ' <span class="bb-sort-ind">' + (dir === 'asc' ? '▲' : '▼') + '</span>' : base; }); }
    function sortRows(t, h, st) {
      const drows = dataRows(t, h); if (drows.length < 2) return; let anyNum = false;
      const vals = drows.map((r) => { const cell = r.cells[st.col]; const raw = cell ? cell.textContent : ''; const num = parseNum(raw); if (!isNaN(num)) anyNum = true; return { r, raw: (raw || '').trim(), num }; });
      vals.sort((a, b) => { if (anyNum) { const an = isNaN(a.num), bn = isNaN(b.num); if (an && bn) return 0; if (an) return 1; if (bn) return -1; return st.dir === 'asc' ? a.num - b.num : b.num - a.num; } const cmp = a.raw.localeCompare(b.raw, undefined, { numeric: true, sensitivity: 'base' }); return st.dir === 'asc' ? cmp : -cmp; });
      const parent = h.parentNode.tagName === 'THEAD' ? (t.tBodies[0] || h.parentNode) : h.parentNode;
      vals.forEach((v) => parent.appendChild(v.r)); totalRows(t, h).forEach((tr) => parent.appendChild(tr));
    }
    function refresh(t) { const mo = t._bbMO; if (mo) mo.disconnect(); const h = headerRow(t), st = t._bbSort; if (h && st && st.col != null) sortRows(t, h, st); decorate(t, h, st ? st.col : null, st ? st.dir : null); if (mo) mo.observe(t, { childList: true, subtree: true }); }
    function wire(t) {
      if (t._bbWired) return; t._bbWired = true; t.classList.add('bb-sortable');
      t.addEventListener('click', (e) => { const cell = e.target.closest('th,td'); if (!cell) return; const h = headerRow(t); if (!h || cell.parentNode !== h) return; const col = [...h.cells].indexOf(cell); if (col < 0) return; const st = t._bbSort || { col: null, dir: 'desc' }; if (st.col === col) st.dir = (st.dir === 'desc' ? 'asc' : 'desc'); else { st.col = col; st.dir = 'desc'; } t._bbSort = st; refresh(t); });
      t._bbMO = new MutationObserver(() => refresh(t)); refresh(t);
    }
    const css = 'table.bb-sortable th{cursor:pointer;user-select:none}table.bb-sortable th:hover{color:var(--ink)}.bb-sort-ind{font-size:.8em;opacity:.8;margin-left:3px}table.defs th{cursor:default}';
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
    const wireAll = () => document.querySelectorAll('table').forEach((t) => { if (!t.classList.contains('defs')) wire(t); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wireAll); else wireAll();
  })();

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
