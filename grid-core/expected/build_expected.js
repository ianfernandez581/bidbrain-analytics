// Expected-side plan baseline for Job 2053 (Schneider Electric NEL, ANZ).
// Produces out/daily_kpi.xlsx and out/pacing.html.
//
// EVERY number below is extracted from the media buyer's files; every derived
// figure is computed here in plain code. Nothing numeric is model-generated.
//
// Extraction sources:
//   budgets / impressions / clicks / CPM per line:
//     "2053_SE_ANZ_New Energy Landscape Awareness - Media Plan.xlsx",
//     sheet "Media Plan", rows 11 (TradeDesk), 12 (Video), 18 (Doc Ads), 19 (SIA);
//     overall budget AUD 35,000 row 8.
//   flight 2026-06-01 to 2026-08-22:
//     "2053_SE_NEL_LinkedIn_Setup_Sheet.xlsx", sheet "2. Campaign Setup Grid",
//     Flight Start / Flight End on all 12 rows; same dates on every row of the
//     TTD bulk upload ("2053_SE_NEL_TTD_Creative_Bulk_Upload.xlsx", Hosted Display).
//     The media plan header's 28-Apr to 18-Jul window is superseded (its own
//     annotation says "revise to june start through august") - see report.md.
'use strict';

const fs = require('fs');
const path = require('path');
const XLSX = require('xlsx');

const FLIGHT_START = Date.UTC(2026, 5, 1);   // 2026-06-01
const FLIGHT_END = Date.UTC(2026, 7, 22);    // 2026-08-22
const DAY_MS = 86400000;
const TOTAL_DAYS = Math.round((FLIGHT_END - FLIGHT_START) / DAY_MS) + 1; // 83 inclusive
const CURRENCY = 'AUD';

const CAMPAIGNS = [
  { name: 'TradeDesk Display', platform: 'TradeDesk', spend: 8000, impressions: 444444, clicks: 444 },
  { name: 'LinkedIn Video', platform: 'LinkedIn', spend: 6000, impressions: 100000, clicks: 650 },
  { name: 'LinkedIn Doc Ads', platform: 'LinkedIn', spend: 14000, impressions: 175000, clicks: 1138 },
  { name: 'LinkedIn SIA', platform: 'LinkedIn', spend: 7000, impressions: 93333, clicks: 513 },
];

const TOTAL_SPEND = CAMPAIGNS.reduce((a, c) => a + c.spend, 0);
if (TOTAL_SPEND !== 35000) throw new Error(`sanity: campaign spends sum to ${TOTAL_SPEND}, expected 35000`);

const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
const r2 = (x) => Math.round(x * 100) / 100;

// One row per campaign per day. Cumulative = (days elapsed / total days) x goal.
const rows = [];
for (let k = 1; k <= TOTAL_DAYS; k++) {
  const date = iso(FLIGHT_START + (k - 1) * DAY_MS);
  for (const c of CAMPAIGNS) {
    const share = k / TOTAL_DAYS;
    const prev = (k - 1) / TOTAL_DAYS;
    rows.push({
      date,
      campaign: c.name,
      platform: c.platform,
      expected_spend: r2(c.spend * (share - prev)),
      expected_impressions: r2(c.impressions * (share - prev)),
      expected_clicks: r2(c.clicks * (share - prev)),
      cum_spend: r2(c.spend * share),
      cum_impressions: r2(c.impressions * share),
      cum_clicks: r2(c.clicks * share),
      days_elapsed: k,
      days_remaining: TOTAL_DAYS - k,
    });
  }
}

// ---------------------------------------------------------------- xlsx
const OUT = path.join(__dirname, 'out');
fs.mkdirSync(OUT, { recursive: true });

const wb = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Daily KPI');
XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
  ['Client', 'Schneider Electric'],
  ['Campaign', '2053 SE ANZ New Energy Landscape (NEL) Awareness'],
  ['Currency', CURRENCY],
  ['Flight', `${iso(FLIGHT_START)} to ${iso(FLIGHT_END)} (${TOTAL_DAYS} days inclusive)`],
  ['Total budget', TOTAL_SPEND],
  ['Curve', 'flat (no source specified a weighted curve)'],
  ['Cumulative formula', '(days elapsed / total days) x goal'],
  ['Generated', new Date().toISOString()],
  [],
  ['Campaign', 'Platform', 'Spend goal', 'Impressions goal', 'Clicks goal', 'Source'],
  ...CAMPAIGNS.map((c, i) => [c.name, c.platform, c.spend, c.impressions, c.clicks,
    `Media Plan.xlsx, sheet "Media Plan", row ${[11, 12, 18, 19][i]}`]),
  [],
  ['Flight source', 'LinkedIn_Setup_Sheet.xlsx "2. Campaign Setup Grid" + TTD bulk upload flight dates (plan header window superseded, see report.md)'],
]), 'Info');
XLSX.writeFile(wb, path.join(OUT, 'daily_kpi.xlsx'));

// ---------------------------------------------------------------- json
// Same source of truth: built from the identical `rows` array the xlsx uses.
const kpiJson = {
  job: '2053',
  client: 'Schneider Electric',
  currency: CURRENCY,
  generated_at: new Date().toISOString(),
  campaigns: CAMPAIGNS.map((c) => ({
    campaign_name: c.name,
    platform: c.platform,
    start: iso(FLIGHT_START),
    end: iso(FLIGHT_END),
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

// ---------------------------------------------------------------- html
// Series data for the page: per-campaign cumulative arrays straight from rows.
const dates = [];
for (let k = 1; k <= TOTAL_DAYS; k++) dates.push(iso(FLIGHT_START + (k - 1) * DAY_MS));
const series = CAMPAIGNS.map((c) => ({
  name: c.name,
  goal: { spend: c.spend, impressions: c.impressions, clicks: c.clicks },
  cum: {
    spend: rows.filter((r) => r.campaign === c.name).map((r) => r.cum_spend),
    impressions: rows.filter((r) => r.campaign === c.name).map((r) => r.cum_impressions),
    clicks: rows.filter((r) => r.campaign === c.name).map((r) => r.cum_clicks),
  },
}));

const DATA = { dates, series, currency: CURRENCY, totalDays: TOTAL_DAYS, client: 'Schneider Electric', job: '2053 NEL Awareness (ANZ)' };

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEL 2053 - Expected pacing</title>
<style>
  :root { color-scheme: light dark; }
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  }
  @media (prefers-color-scheme: dark) {
    .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
      --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
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
  <h1>Expected pacing - Schneider Electric, Job 2053 NEL Awareness (ANZ)</h1>
  <div class="sub">Flight 2026-06-01 to 2026-08-22 (83 days) - AUD 35,000 - flat curve - cumulative expected per campaign. Source: out/daily_kpi.xlsx</div>
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
  an array of {date:"YYYY-MM-DD", campaign:"LinkedIn Video", spend, impressions, clicks} rows
  (daily actuals, not cumulative) before this script runs, or call <code>joinActuals(rows)</code>
  later. Actuals draw as thicker solid lines in each campaign's own colour; expected stays the thin line.</div>
</div>
<script>
var DATA = __DATA__;
var COLORS = ['var(--s1)','var(--s2)','var(--s3)','var(--s4)'];
var METRIC = 'spend';
var ACTUALS = null; // populated by joinActuals / window.BB_ACTUALS

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
  DATA.series.forEach(function (s) { maxY = Math.max(maxY, s.cum[METRIC][n - 1]); });
  if (ACTUALS) DATA.series.forEach(function (s) {
    var a = actualCum(s.name, METRIC);
    if (a && a.length) maxY = Math.max(maxY, a[a.length - 1]);
  });
  maxY = maxY * 1.05;
  var x = function (i) { return PAD.l + (i / (n - 1)) * iw; };
  var y = function (v) { return PAD.t + ih - (v / maxY) * ih; };

  // gridlines + y labels
  for (var g = 0; g <= 4; g++) {
    var vy = y(maxY * g / 4);
    svg.appendChild(el('line', { x1: PAD.l, x2: PAD.l + iw, y1: vy, y2: vy, stroke: 'var(--grid)', 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: PAD.l - 8, y: vy + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, fmt(maxY * g / 4, METRIC)));
  }
  // x labels: first of each month + last day
  DATA.dates.forEach(function (d, i) {
    if (d.slice(8) === '01' || i === n - 1) {
      svg.appendChild(el('text', { x: x(i), y: H - 12, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--muted)' }, d.slice(5)));
      svg.appendChild(el('line', { x1: x(i), x2: x(i), y1: PAD.t + ih, y2: PAD.t + ih + 4, stroke: 'var(--axis)' }));
    }
  });
  svg.appendChild(el('line', { x1: PAD.l, x2: PAD.l + iw, y1: PAD.t + ih, y2: PAD.t + ih, stroke: 'var(--axis)', 'stroke-width': 1 }));

  // today marker
  var today = new Date().toISOString().slice(0, 10);
  var ti = DATA.dates.indexOf(today);
  if (ti >= 0) {
    svg.appendChild(el('line', { x1: x(ti), x2: x(ti), y1: PAD.t, y2: PAD.t + ih, stroke: 'var(--muted)', 'stroke-width': 1, 'stroke-dasharray': '3 4' }));
    svg.appendChild(el('text', { x: x(ti) + 4, y: PAD.t + 12, 'font-size': 10.5, fill: 'var(--muted)' }, 'today'));
  }

  // expected lines + direct labels
  DATA.series.forEach(function (s, si) {
    var pts = s.cum[METRIC].map(function (v, i) { return x(i) + ',' + y(v); }).join(' ');
    svg.appendChild(el('polyline', { points: pts, fill: 'none', stroke: COLORS[si], 'stroke-width': 2, 'stroke-linejoin': 'round' }));
    svg.appendChild(el('text', { x: x(n - 1) + 7, y: y(s.cum[METRIC][n - 1]) + 4, 'font-size': 11.5, fill: 'var(--ink-2)' }, s.name));
    var a = ACTUALS && actualCum(s.name, METRIC);
    if (a && a.length > 1) {
      var apts = a.map(function (v, i) { return x(i) + ',' + y(v); }).join(' ');
      svg.appendChild(el('polyline', { points: apts, fill: 'none', stroke: COLORS[si], 'stroke-width': 3.5, 'stroke-linecap': 'round', opacity: 0.9 }));
    }
  });

  // hover crosshair + tooltip
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
      total += s.cum[METRIC][i];
      html += '<div><span class="sw" style="background:' + COLORS[si] + ';display:inline-block;width:10px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px"></span>'
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
    sp.innerHTML = '<span class="sw" style="background:' + COLORS[si] + '"></span>' + s.name;
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
    h += '<tr><td><span class="sw" style="background:' + COLORS[si] + ';display:inline-block;width:12px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px"></span>' + s.name + '</td>'
      + '<td>' + fmt(s.goal.spend, 'spend') + '</td><td>' + fmt(s.goal.impressions, 'n') + '</td><td>' + fmt(s.goal.clicks, 'n') + '</td>'
      + '<td>' + fmt(s.goal.spend / DATA.totalDays, 'spend') + '</td>'
      + (ti >= 0 ? '<td>' + fmt(s.cum.spend[ti], 'spend') + '</td>' : '') + '</tr>';
  });
  var totalGoal = DATA.series.reduce(function (a, s) { return a + s.goal.spend; }, 0);
  h += '<tr><td><b>Total</b></td><td><b>' + fmt(totalGoal, 'spend') + '</b></td><td></td><td></td><td>'
    + fmt(totalGoal / DATA.totalDays, 'spend') + '</td>'
    + (ti >= 0 ? '<td><b>' + fmt(DATA.series.reduce(function (a, s) { return a + s.cum.spend[ti]; }, 0), 'spend') + '</b></td>' : '') + '</tr>';
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

fs.writeFileSync(path.join(OUT, 'pacing.html'), html.replace('__DATA__', JSON.stringify(DATA)));

// ---------------------------------------------------------------- verify
const last = rows.slice(-CAMPAIGNS.length);
const finalSpend = last.reduce((a, r) => a + r.cum_spend, 0);
console.log(`rows: ${rows.length} (${TOTAL_DAYS} days x ${CAMPAIGNS.length} campaigns)`);
console.log(`final-day cumulative spend: ${finalSpend} (must be 35000)`);
for (const r of last) console.log(`  ${r.campaign}: cum_spend ${r.cum_spend}, cum_impressions ${r.cum_impressions}, cum_clicks ${r.cum_clicks}`);
console.log('wrote', path.join(OUT, 'daily_kpi.xlsx'));
console.log('wrote', path.join(OUT, 'daily_kpi.json'));
console.log('wrote', path.join(OUT, 'pacing.html'));
