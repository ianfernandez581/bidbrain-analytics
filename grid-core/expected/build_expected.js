// Expected-side output builder. GENERIC: reads out/plan.json + out/findings.json
// (written by extract.js) and emits out/daily_kpi.xlsx, out/daily_kpi.json,
// out/pacing.html, out/flowchart.html, out/report.md. No client names, job
// numbers, or plan figures live in this file - they all come from plan.json.
//
// All arithmetic is plain code: daily = goal / days,
// cumulative = (days elapsed / total days) x goal, days inclusive of both ends.
// A campaign missing budget, dates, or rate goals produces an exception entry,
// never zero-valued rows. Final-day cumulatives equal the goals exactly.
'use strict';

const fs = require('fs');
const path = require('path');
const XLSX = require('xlsx');

const ROOT = __dirname;
const OUT = process.env.GREENLIGHT_OUT_DIR || path.join(ROOT, 'out');
const DAY_MS = 86400000;

const val = (node) => (node && node.value != null ? node.value : null);
const citeStr = (node) => {
  if (!node || !node.citation) return '';
  return `${node.citation.file}${node.citation.location ? ', ' + node.citation.location : ''}`;
};
const parseDate = (s) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null;
};
const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
const r2 = (x) => Math.round(x * 100) / 100;

// ---------------------------------------------------------------- load
const plan = JSON.parse(fs.readFileSync(path.join(OUT, 'plan.json'), 'utf8'));
const findingsDoc = JSON.parse(fs.readFileSync(path.join(OUT, 'findings.json'), 'utf8'));
const rulebook = JSON.parse(fs.readFileSync(path.join(ROOT, 'rulebook.json'), 'utf8'));

const client = val(plan.client) || 'Unknown client';
const job = val(plan.job_number) || 'unknown-job';
const campaignName = val(plan.campaign_name) || 'Unknown campaign';
const currency = val(plan.currency) || 'UNKNOWN';
const flightStartS = val(plan.flight_start);
const flightEndS = val(plan.flight_end);
const FLIGHT_START = parseDate(flightStartS);
const FLIGHT_END = parseDate(flightEndS);
if (FLIGHT_START == null || FLIGHT_END == null || FLIGHT_END < FLIGHT_START) {
  console.error('[build] BLOCKED: flight dates unresolved in plan.json (start=' + flightStartS + ', end=' + flightEndS + '). The extractor recorded the conflict; resolve it before a baseline can exist.');
  process.exit(3);
}
const TOTAL_DAYS = Math.round((FLIGHT_END - FLIGHT_START) / DAY_MS) + 1;

// ---------------------------------------------------------------- rows
const usable = [];
const exceptions = [];
for (const c of plan.campaigns || []) {
  const missing = [];
  if (val(c.budget) == null) missing.push('budget');
  if (val(c.goal_impressions) == null && val(c.goal_clicks) == null) missing.push('volume goals');
  const start = parseDate(c.start) ?? FLIGHT_START;
  const end = parseDate(c.end) ?? FLIGHT_END;
  if (start == null || end == null || end < start) missing.push('dates');
  if (missing.length) {
    exceptions.push({ campaign: c.campaign_name, missing, note: 'no rows emitted - resolve and rerun' });
    continue;
  }
  usable.push({
    name: c.campaign_name,
    platform: c.platform || null,
    spend: val(c.budget),
    impressions: val(c.goal_impressions),
    clicks: val(c.goal_clicks),
    start, end,
    days: Math.round((end - start) / DAY_MS) + 1,
    citation: citeStr(c.budget),
  });
}
if (!usable.length) {
  console.error('[build] BLOCKED: no campaign has enough data (budget + goals + dates) to emit rows. Exceptions: ' + JSON.stringify(exceptions));
  process.exit(3);
}

const rows = [];
for (const c of usable) {
  for (let k = 1; k <= c.days; k++) {
    const share = k / c.days;
    const prev = (k - 1) / c.days;
    rows.push({
      date: iso(c.start + (k - 1) * DAY_MS),
      campaign: c.name,
      platform: c.platform,
      expected_spend: r2(c.spend * (share - prev)),
      expected_impressions: c.impressions != null ? r2(c.impressions * (share - prev)) : null,
      expected_clicks: c.clicks != null ? r2(c.clicks * (share - prev)) : null,
      cum_spend: r2(c.spend * share),
      cum_impressions: c.impressions != null ? r2(c.impressions * share) : null,
      cum_clicks: c.clicks != null ? r2(c.clicks * share) : null,
      days_elapsed: k,
      days_remaining: c.days - k,
    });
  }
}
rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.campaign.localeCompare(b.campaign)));
const TOTAL_SPEND = usable.reduce((a, c) => a + c.spend, 0);

// ---------------------------------------------------------------- xlsx
fs.mkdirSync(OUT, { recursive: true });
const wb = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Daily KPI');
XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
  ['Client', client],
  ['Campaign', campaignName],
  ['Job', job],
  ['Currency', currency],
  ['Flight', `${flightStartS} to ${flightEndS} (${TOTAL_DAYS} days inclusive)`],
  ['Campaign budgets sum', TOTAL_SPEND],
  ['Stated plan total', val(plan.total_budget) != null ? val(plan.total_budget) : 'not stated'],
  ['Curve', 'flat (no source specified a weighted curve)'],
  ['Cumulative formula', '(days elapsed / total days) x goal'],
  ['Extractor', plan.extractor ? `${plan.extractor.model} at ${plan.extractor.generated_at}` : 'unknown'],
  ['Generated', new Date().toISOString()],
  [],
  ['Campaign', 'Platform', 'Spend goal', 'Impressions goal', 'Clicks goal', 'Days', 'Source'],
  ...usable.map((c) => [c.name, c.platform, c.spend, c.impressions, c.clicks, c.days, c.citation]),
  [],
  ...(exceptions.length ? [['EXCEPTIONS (no rows emitted)'], ...exceptions.map((e) => [e.campaign, e.missing.join(', '), e.note])] : [['Exceptions', 'none']]),
]), 'Info');
XLSX.writeFile(wb, path.join(OUT, 'daily_kpi.xlsx'));

// ---------------------------------------------------------------- json (same rows array = same numbers)
const kpiJson = {
  job, client, currency,
  generated_at: new Date().toISOString(),
  exceptions,
  campaigns: usable.map((c) => ({
    campaign_name: c.name,
    platform: c.platform,
    start: iso(c.start),
    end: iso(c.end),
    total_budget: c.spend,
    goal_impressions: c.impressions,
    goal_clicks: c.clicks,
    daily: rows.filter((r) => r.campaign === c.name).map((r) => ({
      date: r.date,
      expected_spend_cum: r.cum_spend,
      expected_impressions_cum: r.cum_impressions,
      expected_clicks_cum: r.cum_clicks,
      expected_spend_day: r.expected_spend,
      expected_impressions_day: r.expected_impressions,
      expected_clicks_day: r.expected_clicks,
    })),
  })),
};
fs.writeFileSync(path.join(OUT, 'daily_kpi.json'), JSON.stringify(kpiJson, null, 2));

// ---------------------------------------------------------------- pacing.html
const dates = [];
for (let k = 1; k <= TOTAL_DAYS; k++) dates.push(iso(FLIGHT_START + (k - 1) * DAY_MS));
const series = kpiJson.campaigns.map((c) => {
  const byDate = new Map(c.daily.map((d) => [d.date, d]));
  let last = { expected_spend_cum: 0, expected_impressions_cum: 0, expected_clicks_cum: 0 };
  const cum = { spend: [], impressions: [], clicks: [] };
  for (const d of dates) {
    if (byDate.has(d)) last = byDate.get(d);
    cum.spend.push(last.expected_spend_cum);
    cum.impressions.push(last.expected_impressions_cum);
    cum.clicks.push(last.expected_clicks_cum);
  }
  return { name: c.campaign_name, goal: { spend: c.total_budget, impressions: c.goal_impressions, clicks: c.goal_clicks }, cum };
});
const DATA = { dates, series, currency, totalDays: TOTAL_DAYS, client, job, campaignName, flight: `${flightStartS} to ${flightEndS}` };

const pacingHtml = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${client} ${job} - Expected pacing</title>
<style>
  :root { color-scheme: light dark; }
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
    --s5: #e87ba4; --s6: #008300; --s7: #4a3aa7; --s8: #e34948;
  }
  @media (prefers-color-scheme: dark) {
    .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
      --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
      --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); color: var(--ink-1);
         font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .viz-root { max-width: 1060px; margin: 0 auto; padding: 24px 20px 48px; }
  h1 { font-size: 19px; margin: 0 0 2px; }
  .sub { color: var(--ink-2); font-size: 12.5px; margin-bottom: 18px; }
  .card { background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px; padding: 18px 18px 10px; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
  .tgl { display: inline-flex; border: 1px solid var(--ring); border-radius: 8px; overflow: hidden; }
  .tgl button { border: 0; background: transparent; color: var(--ink-2); padding: 6px 14px; cursor: pointer; font: inherit; font-size: 12.5px; }
  .tgl button[aria-pressed="true"] { background: var(--ink-1); color: var(--surface-1); font-weight: 600; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; margin-left: auto; font-size: 12px; color: var(--ink-2); }
  .legend .sw { display: inline-block; width: 14px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 5px; }
  .legend .actuals { color: var(--muted); font-style: italic; }
  #chart { width: 100%; }
  .tip { position: absolute; pointer-events: none; background: var(--surface-1); border: 1px solid var(--ring);
         border-radius: 8px; padding: 8px 10px; font-size: 12px; color: var(--ink-1);
         box-shadow: 0 4px 14px rgba(0,0,0,0.12); display: none; min-width: 190px; z-index: 3; }
  .tip b { font-variant-numeric: tabular-nums; }
  table { border-collapse: collapse; width: 100%; margin-top: 20px; background: var(--surface-1);
          border: 1px solid var(--ring); border-radius: 10px; overflow: hidden; font-size: 13px; }
  th, td { text-align: right; padding: 8px 12px; border-top: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  th { color: var(--ink-2); font-weight: 600; font-size: 12px; border-top: 0; }
  th:first-child, td:first-child { text-align: left; }
  .note { color: var(--muted); font-size: 12px; margin-top: 10px; }
</style>
</head>
<body>
<div class="viz-root">
  <h1>Expected pacing - ${client}, ${campaignName}</h1>
  <div class="sub">Flight ${flightStartS} to ${flightEndS} (${TOTAL_DAYS} days) - ${currency} ${TOTAL_SPEND.toLocaleString()} - flat curve - built from out/daily_kpi.xlsx / .json</div>
  <div class="card" style="position:relative">
    <div class="row">
      <div class="tgl" role="group" aria-label="Metric">
        <button data-m="spend" aria-pressed="true">Spend</button>
        <button data-m="impressions" aria-pressed="false">Impressions</button>
        <button data-m="clicks" aria-pressed="false">Clicks</button>
      </div>
      <div class="legend" id="legend"></div>
    </div>
    <svg id="chart" height="420" role="img" aria-label="Cumulative expected pacing lines per campaign"></svg>
    <div class="tip" id="tip"></div>
  </div>
  <table id="tbl"></table>
  <div class="note">Actuals are not joined yet. Teammate hook: set <code>window.BB_ACTUALS</code> to
  daily rows {date:"YYYY-MM-DD", campaign, spend, impressions, clicks} before this script runs, or call
  <code>joinActuals(rows)</code> later. Actuals draw as thicker lines in each campaign's own colour.</div>
</div>
<script>
var DATA = __DATA__;
var COLORS = ['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)','var(--s6)','var(--s7)','var(--s8)'];
var METRIC = 'spend';
var ACTUALS = null;

var svg = document.getElementById('chart');
var tip = document.getElementById('tip');
var NS = 'http://www.w3.org/2000/svg';
var PAD = { l: 62, r: 150, t: 16, b: 34 };

function fmt(v, m) {
  if (v == null) return '';
  if (m === 'spend') return '$' + Math.round(v).toLocaleString();
  return Math.round(v).toLocaleString();
}
function el(tag, attrs, text) {
  var e = document.createElementNS(NS, tag);
  for (var k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}
function actualCum(name, m) {
  if (!ACTUALS) return null;
  var byDate = {};
  ACTUALS.forEach(function (r) { if (r.campaign === name) byDate[r.date] = (byDate[r.date] || 0) + (r[m] || 0); });
  var cum = 0, out = [];
  for (var i = 0; i < DATA.dates.length; i++) {
    var d = DATA.dates[i];
    if (byDate[d] == null && out.length && Object.keys(byDate).every(function (x) { return x < d; })) break;
    cum += (byDate[d] || 0);
    out.push(cum);
  }
  return out;
}
function draw() {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  var W = svg.clientWidth || 1000, H = 420;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  var iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  var n = DATA.dates.length;
  var maxY = 0;
  DATA.series.forEach(function (s) { maxY = Math.max(maxY, s.cum[METRIC][n - 1] || 0); });
  if (ACTUALS) DATA.series.forEach(function (s) {
    var a = actualCum(s.name, METRIC);
    if (a && a.length) maxY = Math.max(maxY, a[a.length - 1]);
  });
  maxY = (maxY || 1) * 1.05;
  var x = function (i) { return PAD.l + (i / (n - 1)) * iw; };
  var y = function (v) { return PAD.t + ih - (v / maxY) * ih; };

  for (var g = 0; g <= 4; g++) {
    var vy = y(maxY * g / 4);
    svg.appendChild(el('line', { x1: PAD.l, x2: PAD.l + iw, y1: vy, y2: vy, stroke: 'var(--grid)', 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: PAD.l - 8, y: vy + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, fmt(maxY * g / 4, METRIC)));
  }
  DATA.dates.forEach(function (d, i) {
    if (d.slice(8) === '01' || i === n - 1) {
      svg.appendChild(el('text', { x: x(i), y: H - 12, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--muted)' }, d.slice(5)));
      svg.appendChild(el('line', { x1: x(i), x2: x(i), y1: PAD.t + ih, y2: PAD.t + ih + 4, stroke: 'var(--axis)' }));
    }
  });
  svg.appendChild(el('line', { x1: PAD.l, x2: PAD.l + iw, y1: PAD.t + ih, y2: PAD.t + ih, stroke: 'var(--axis)', 'stroke-width': 1 }));

  var today = new Date().toISOString().slice(0, 10);
  var ti = DATA.dates.indexOf(today);
  if (ti >= 0) {
    svg.appendChild(el('line', { x1: x(ti), x2: x(ti), y1: PAD.t, y2: PAD.t + ih, stroke: 'var(--muted)', 'stroke-width': 1, 'stroke-dasharray': '3 4' }));
    svg.appendChild(el('text', { x: x(ti) + 4, y: PAD.t + 12, 'font-size': 10.5, fill: 'var(--muted)' }, 'today'));
  }

  DATA.series.forEach(function (s, si) {
    var color = COLORS[si % COLORS.length];
    var pts = s.cum[METRIC].map(function (v, i) { return x(i) + ',' + y(v || 0); }).join(' ');
    svg.appendChild(el('polyline', { points: pts, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round' }));
    if (DATA.series.length <= 4) {
      svg.appendChild(el('text', { x: x(n - 1) + 7, y: y(s.cum[METRIC][n - 1] || 0) + 4, 'font-size': 11.5, fill: 'var(--ink-2)' }, s.name));
    }
    var a = ACTUALS && actualCum(s.name, METRIC);
    if (a && a.length > 1) {
      var apts = a.map(function (v, i) { return x(i) + ',' + y(v); }).join(' ');
      svg.appendChild(el('polyline', { points: apts, fill: 'none', stroke: color, 'stroke-width': 3.5, 'stroke-linecap': 'round', opacity: 0.9 }));
    }
  });

  var hover = el('line', { y1: PAD.t, y2: PAD.t + ih, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden' });
  svg.appendChild(hover);
  var hit = el('rect', { x: PAD.l, y: PAD.t, width: iw, height: ih, fill: 'transparent' });
  svg.appendChild(hit);
  hit.addEventListener('mousemove', function (ev) {
    var box = svg.getBoundingClientRect();
    var i = Math.round(((ev.clientX - box.left) - PAD.l) / iw * (n - 1));
    i = Math.max(0, Math.min(n - 1, i));
    hover.setAttribute('x1', x(i)); hover.setAttribute('x2', x(i));
    hover.setAttribute('visibility', 'visible');
    var total = 0;
    var html = '<div style="color:var(--ink-2);margin-bottom:4px">' + DATA.dates[i] + ' (day ' + (i + 1) + ' of ' + n + ')</div>';
    DATA.series.forEach(function (s, si) {
      total += (s.cum[METRIC][i] || 0);
      html += '<div><span style="background:' + COLORS[si % COLORS.length] + ';display:inline-block;width:10px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px"></span>'
           + s.name + ' <b style="float:right;margin-left:12px">' + fmt(s.cum[METRIC][i], METRIC) + '</b></div>';
    });
    html += '<div style="border-top:1px solid var(--grid);margin-top:4px;padding-top:3px">Total <b style="float:right">' + fmt(total, METRIC) + '</b></div>';
    tip.innerHTML = html;
    tip.style.display = 'block';
    var left = ev.clientX - box.left + 14;
    if (left > W - 230) left = ev.clientX - box.left - 214;
    tip.style.left = left + 'px';
    tip.style.top = (ev.clientY - box.top - 20) + 'px';
  });
  hit.addEventListener('mouseleave', function () { hover.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; });
}

function legend() {
  var lg = document.getElementById('legend');
  lg.innerHTML = '';
  DATA.series.forEach(function (s, si) {
    var sp = document.createElement('span');
    sp.innerHTML = '<span class="sw" style="background:' + COLORS[si % COLORS.length] + '"></span>' + s.name;
    lg.appendChild(sp);
  });
  var a = document.createElement('span');
  a.className = 'actuals';
  a.textContent = ACTUALS ? 'Actuals: joined (thick lines)' : 'Actuals: awaiting join';
  lg.appendChild(a);
}

function table() {
  var t = document.getElementById('tbl');
  var today = new Date().toISOString().slice(0, 10);
  var ti = DATA.dates.indexOf(today);
  var h = '<tr><th>Campaign</th><th>Spend goal</th><th>Impressions goal</th><th>Clicks goal</th><th>Spend / day</th>'
        + (ti >= 0 ? '<th>Expected spend to date</th>' : '') + '</tr>';
  DATA.series.forEach(function (s, si) {
    h += '<tr><td><span class="sw" style="background:' + COLORS[si % COLORS.length] + ';display:inline-block;width:12px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px"></span>' + s.name + '</td>'
      + '<td>' + fmt(s.goal.spend, 'spend') + '</td><td>' + fmt(s.goal.impressions, 'n') + '</td><td>' + fmt(s.goal.clicks, 'n') + '</td>'
      + '<td>' + fmt(s.goal.spend / DATA.totalDays, 'spend') + '</td>'
      + (ti >= 0 ? '<td>' + fmt(s.cum.spend[ti], 'spend') + '</td>' : '') + '</tr>';
  });
  var totalGoal = DATA.series.reduce(function (a, s) { return a + (s.goal.spend || 0); }, 0);
  h += '<tr><td><b>Total</b></td><td><b>' + fmt(totalGoal, 'spend') + '</b></td><td></td><td></td><td>'
    + fmt(totalGoal / DATA.totalDays, 'spend') + '</td>'
    + (ti >= 0 ? '<td><b>' + fmt(DATA.series.reduce(function (a, s) { return a + (s.cum.spend[ti] || 0); }, 0), 'spend') + '</b></td>' : '') + '</tr>';
  t.innerHTML = h;
}

function joinActuals(rowsIn) { ACTUALS = rowsIn; legend(); draw(); }
window.joinActuals = joinActuals;
if (window.BB_ACTUALS) ACTUALS = window.BB_ACTUALS;

document.querySelectorAll('.tgl button').forEach(function (b) {
  b.addEventListener('click', function () {
    METRIC = b.getAttribute('data-m');
    document.querySelectorAll('.tgl button').forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
    draw();
  });
});
window.addEventListener('resize', draw);
legend(); table(); draw();
</script>
</body>
</html>
`;
fs.writeFileSync(path.join(OUT, 'pacing.html'), pacingHtml.replace('__DATA__', JSON.stringify(DATA)));

// ---------------------------------------------------------------- flowchart.html (from findings)
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const findings = findingsDoc.findings || [];
const stages = rulebook.stages;
const stageCards = stages.map((stage) => {
  const items = findings.filter((f) => f.stage === stage);
  const cls = items.some((f) => f.severity === 'blocker') ? 'crit' : (items.length ? 'warn' : 'good');
  const badge = cls === 'crit' ? `&#10007; ${items.length} OPEN ITEM${items.length === 1 ? '' : 'S'}`
    : cls === 'warn' ? `! ${items.length} OPEN ITEM${items.length === 1 ? '' : 'S'}`
    : '&#10003; READY';
  const list = items.length
    ? '<ul>' + items.map((f) => `<li><b>${esc(f.title)}</b>${f.origin === 'model' ? ' <span class="ref">(AI)</span>' : ''}</li>`).join('') + '</ul>'
    : (stage === 'Pacing'
      ? '<div class="ok-note">Expected baseline built: daily_kpi.xlsx / .json + pacing.html. Actuals join pending.</div>'
      : '<div class="ok-note">No open items found in the dump.</div>');
  return `    <div class="stage ${cls}">
      <div class="stage-head"><span class="dot"></span><h2>${esc(stage)}</h2></div>
      <span class="badge">${badge}</span>
${list}
    </div>`;
}).join('\n    <div class="arrow">&#9654;</div>\n');

const flowchartHtml = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(client)} ${esc(job)} - Readiness flowchart</title>
<style>
  :root { color-scheme: light dark; }
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --good: #0ca30c; --warn: #fab219; --crit: #d03b3b;
    --good-bg: rgba(12,163,12,0.10); --warn-bg: rgba(250,178,25,0.14); --crit-bg: rgba(208,59,59,0.10);
  }
  @media (prefers-color-scheme: dark) {
    .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
      --good-bg: rgba(12,163,12,0.16); --warn-bg: rgba(250,178,25,0.14); --crit-bg: rgba(208,59,59,0.18);
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); color: var(--ink-1);
         font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .viz-root { max-width: 1360px; margin: 0 auto; padding: 24px 20px 48px; }
  h1 { font-size: 19px; margin: 0 0 2px; }
  .sub { color: var(--ink-2); font-size: 12.5px; margin-bottom: 18px; }
  .flow { display: flex; align-items: stretch; gap: 0; overflow-x: auto; padding-bottom: 8px; }
  .stage { background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px;
           min-width: 196px; flex: 1 1 0; padding: 12px 14px; }
  .stage-head { display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; flex: none; }
  .stage h2 { font-size: 13px; margin: 0; line-height: 1.25; }
  .badge { font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; padding: 2px 7px;
           border-radius: 99px; margin: 2px 0 8px; display: inline-block; }
  .good  .dot { background: var(--good); }  .good  .badge { color: var(--good); background: var(--good-bg); }
  .warn  .dot { background: var(--warn); }  .warn  .badge { color: #8a5b00; background: var(--warn-bg); }
  .crit  .dot { background: var(--crit); }  .crit  .badge { color: var(--crit); background: var(--crit-bg); }
  @media (prefers-color-scheme: dark) { .warn .badge { color: var(--warn); } }
  .stage ul { margin: 0; padding: 0 0 0 2px; list-style: none; }
  .stage li { font-size: 11.5px; color: var(--ink-2); padding: 4px 0; border-top: 1px solid var(--grid); }
  .stage li b { color: var(--ink-1); font-weight: 600; }
  .stage li .ref { color: var(--muted); }
  .ok-note { font-size: 11.5px; color: var(--ink-2); padding: 4px 0; border-top: 1px solid var(--grid); }
  .arrow { align-self: center; flex: none; width: 26px; text-align: center; color: var(--axis); font-size: 17px; }
  .legend { display: flex; gap: 18px; margin-top: 16px; font-size: 12px; color: var(--ink-2); align-items: center; }
  .legend .dot { display: inline-block; vertical-align: middle; margin-right: 5px; }
  .foot { color: var(--muted); font-size: 12px; margin-top: 10px; }
</style>
</head>
<body>
<div class="viz-root">
  <h1>Readiness flowchart - ${esc(client)}, ${esc(campaignName)}</h1>
  <div class="sub">Flight ${esc(flightStartS)} to ${esc(flightEndS)} - ${esc(currency)} ${TOTAL_SPEND.toLocaleString()} - stage status computed from findings.json (items marked AI were model-authored; the rest are code checks).</div>
  <div class="flow">
${stageCards}
  </div>
  <div class="legend">
    <span><span class="dot" style="background:var(--good)"></span>&#10003; ready</span>
    <span><span class="dot" style="background:var(--warn)"></span>! open items, not blocking</span>
    <span><span class="dot" style="background:var(--crit)"></span>&#10007; blocker in this stage</span>
  </div>
  <div class="foot">Generated ${new Date().toISOString().slice(0, 10)} from findings.json (${findingsDoc.origins.code} code checks, ${findingsDoc.origins.model} AI-authored). Details: report.md. Chase drafts: chase_messages.md.</div>
</div>
</body>
</html>
`;
fs.writeFileSync(path.join(OUT, 'flowchart.html'), flowchartHtml);

// ---------------------------------------------------------------- report.md (from findings)
const sevOrder = ['blocker', 'missing', 'gap', 'inconsistent', 'watch', 'housekeeping'];
const rep = [];
rep.push(`# ${client} ${campaignName} (job ${job}): gaps and inconsistencies\n`);
rep.push(`Extracted by ${plan.extractor ? plan.extractor.model : 'unknown model'} from the file dump; arithmetic checks computed in code. ${findingsDoc.origins.code} code findings + ${findingsDoc.origins.model} AI-authored findings. Baseline: ${currency} ${TOTAL_SPEND.toLocaleString()}, flight ${flightStartS} to ${flightEndS} (${TOTAL_DAYS} days).\n`);
let n = 0;
for (const sev of sevOrder) {
  const group = findings.filter((f) => f.severity === sev);
  if (!group.length) continue;
  rep.push(`## ${sev.charAt(0).toUpperCase() + sev.slice(1)}\n`);
  for (const f of group) {
    n++;
    rep.push(`${n}. **${f.title}** [${f.origin === 'model' ? 'AI-authored' : 'code check'}, stage: ${f.stage}]`);
    if (f.detail) rep.push(`   ${f.detail}`);
    rep.push(`   Source: ${f.source || 'n/a'}\n`);
  }
}
if (exceptions.length) {
  rep.push('## Baseline exceptions\n');
  for (const e of exceptions) rep.push(`- ${e.campaign}: missing ${e.missing.join(', ')} - ${e.note}`);
}
fs.writeFileSync(path.join(OUT, 'report.md'), rep.join('\n') + '\n');

// ---------------------------------------------------------------- verify
const finalByCampaign = kpiJson.campaigns.map((c) => `${c.campaign_name}: ${c.daily[c.daily.length - 1].expected_spend_cum}`);
console.log(`[build] ${client} job ${job}: ${rows.length} rows (${usable.length} campaigns, flight ${TOTAL_DAYS} days), total ${TOTAL_SPEND}`);
for (const line of finalByCampaign) console.log('  final cum spend ' + line);
if (exceptions.length) console.log('[build] exceptions: ' + JSON.stringify(exceptions));
console.log('[build] wrote daily_kpi.xlsx, daily_kpi.json, pacing.html, flowchart.html, report.md');
