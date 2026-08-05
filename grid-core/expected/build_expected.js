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

// ------------------------------------------------- flight window (ladder)
// All three rungs are deterministic - no guessing:
//   1. the extractor's resolved plan-level values (as always);
//   2. min/max of the campaign lines' OWN cited dates;
//   3. an endpoint whose candidate list holds exactly ONE distinct parseable
//      date adopts it - and the assumption is written into findings.json so
//      it shows as a visible gap, never silently.
// Only when all three fail is the baseline blocked (exit 3): at that point
// any window would be an invention.
let flightStartS = val(plan.flight_start);
let flightEndS = val(plan.flight_end);
let FLIGHT_START = parseDate(flightStartS);
let FLIGHT_END = parseDate(flightEndS);
let flightNote = null;
if (FLIGHT_START == null || FLIGHT_END == null || FLIGHT_END < FLIGHT_START) {
  const starts = (plan.campaigns || []).map((c) => parseDate(c.start)).filter((x) => x != null);
  const ends = (plan.campaigns || []).map((c) => parseDate(c.end)).filter((x) => x != null);
  const soleCandidate = (node) => {
    const vals = [...new Set(((node && node.candidates) || []).map((c) => c.value).filter((v) => parseDate(v) != null))];
    return vals.length === 1 ? vals[0] : null;
  };
  if (starts.length && ends.length && Math.max(...ends) >= Math.min(...starts)) {
    FLIGHT_START = Math.min(...starts);
    FLIGHT_END = Math.max(...ends);
    flightNote = 'derived from the campaign lines\' own dates - the plan never states a resolved overall flight';
  } else {
    const s = FLIGHT_START != null ? flightStartS : soleCandidate(plan.flight_start);
    const e = FLIGHT_END != null ? flightEndS : soleCandidate(plan.flight_end);
    if (parseDate(s) != null && parseDate(e) != null && parseDate(e) >= parseDate(s)) {
      FLIGHT_START = parseDate(s);
      FLIGHT_END = parseDate(e);
      flightNote = 'assumed from the only dated candidate the dump contains for each endpoint - confirm with the client';
    }
  }
  if (flightNote) {
    flightStartS = iso(FLIGHT_START);
    flightEndS = iso(FLIGHT_END);
    console.log(`[build] flight window ${flightStartS}..${flightEndS} (${flightNote})`);
  } else {
    console.error('[build] BLOCKED: flight dates unresolved in plan.json (start=' + flightStartS + ', end=' + flightEndS + '), no campaign line carries its own dates, and the recorded candidates do not single out one date per endpoint. Resolve the dates (plan revision or client confirmation) and rerun.');
    process.exit(3);
  }
}
const TOTAL_DAYS = Math.round((FLIGHT_END - FLIGHT_START) / DAY_MS) + 1;

// A ladder-resolved window is a real finding: make it impossible to miss.
if (flightNote) {
  findingsDoc.findings = findingsDoc.findings || [];
  findingsDoc.findings.unshift({
    severity: 'gap',
    stage: 'Media Plan Approved',
    chip: 'ASSUMED FLIGHT',
    title: `Baseline flight ${flightStartS} to ${flightEndS} is not a resolved plan value`,
    detail: `The dump never resolves the overall flight window; the baseline window was ${flightNote}. If the real dates differ, every daily expected value shifts - confirm before relying on pacing.`,
    source: 'build_expected.js flight-window ladder',
    origin: 'code',
  });
  findingsDoc.origins = findingsDoc.origins || {};
  findingsDoc.origins.code = (findingsDoc.origins.code || 0) + 1;
  fs.writeFileSync(path.join(OUT, 'findings.json'), JSON.stringify(findingsDoc, null, 2));
}

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
  ['Flight', `${flightStartS} to ${flightEndS} (${TOTAL_DAYS} days inclusive${flightNote ? '; ' + flightNote : ''})`],
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
// Table-first baseline page (the cumulative chart was removed 2026-08-05 -
// the daily curve still lives in daily_kpi.xlsx/.json for the actuals join;
// this page is the human-readable summary). One row per plan line, with its
// own flight window and source citation so every row traces back to a real
// media-plan line. Expected-to-date is computed client-side from the viewer's
// "today", clamped to each line's window - same math as the daily rows.
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const DATA = {
  client, job, campaignName, currency,
  flight: { start: flightStartS, end: flightEndS, days: TOTAL_DAYS, note: flightNote },
  campaigns: usable.map((c) => ({
    name: c.name,
    platform: c.platform,
    source: c.citation,
    start: iso(c.start),
    end: iso(c.end),
    days: c.days,
    spend: c.spend,
    impressions: c.impressions,
    clicks: c.clicks,
  })),
  exceptions,
  generated: new Date().toISOString().slice(0, 10),
};

const pacingHtml = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(client)} ${esc(job)} - Expected baseline</title>
<style>
  :root { color-scheme: light dark; }
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --ring: rgba(11,11,11,0.10);
    --warn-bg: rgba(250,178,25,0.14); --warn-ink: #8a5b00;
  }
  @media (prefers-color-scheme: dark) {
    .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --ring: rgba(255,255,255,0.10);
      --warn-ink: #fab219;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); color: var(--ink-1);
         font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .viz-root { max-width: 1160px; margin: 0 auto; padding: 24px 20px 40px; }
  h1 { font-size: 19px; margin: 0 0 2px; }
  .sub { color: var(--ink-2); font-size: 12.5px; margin-bottom: 6px; }
  .flightnote { display: inline-block; background: var(--warn-bg); color: var(--warn-ink);
                border-radius: 8px; padding: 3px 9px; font-size: 12px; margin-bottom: 12px; }
  .card { background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px;
          padding: 6px 14px 12px; overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: right; padding: 9px 12px; border-top: 1px solid var(--grid);
           font-variant-numeric: tabular-nums; white-space: nowrap; }
  thead th { color: var(--ink-2); font-weight: 600; font-size: 12px; border-top: 0; }
  th:first-child, td:first-child { text-align: left; white-space: normal; min-width: 260px; }
  .cname { font-weight: 600; }
  .cplat { color: var(--ink-2); font-size: 11.5px; }
  .csrc { color: var(--muted); font-size: 11px; margin-top: 2px; }
  tfoot td { font-weight: 700; border-top: 2px solid var(--grid); }
  .note { color: var(--muted); font-size: 12px; margin-top: 10px; }
</style>
</head>
<body>
<div class="viz-root">
  <h1>Expected baseline - ${esc(client)}, ${esc(campaignName)}</h1>
  <div class="sub">Flight ${esc(flightStartS)} to ${esc(flightEndS)} (${TOTAL_DAYS} days) - ${esc(currency)} ${TOTAL_SPEND.toLocaleString()} total - flat curve - daily values in out/daily_kpi.xlsx / .json</div>
  ${flightNote ? `<div class="flightnote">Flight window ${esc(flightNote)}</div>` : ''}
  <div class="card">
    <table id="tbl"></table>
  </div>
  <div class="note" id="foot"></div>
</div>
<script>
var DATA = __DATA__;
var HAS_IMPS = DATA.campaigns.some(function (c) { return c.impressions != null; });
var HAS_CLICKS = DATA.campaigns.some(function (c) { return c.clicks != null; });
var ACTUALS = null;

function money(v) { return v == null ? '' : '$' + Math.round(v).toLocaleString(); }
function num(v) { return v == null ? '' : Math.round(v).toLocaleString(); }
function esc(s) { var d = document.createElement('div'); d.textContent = String(s == null ? '' : s); return d.innerHTML; }

// expected-to-date = goal x clamp(days elapsed / line days, 0..1), inclusive
// days - the same arithmetic that produced the daily rows in daily_kpi.
function expectedToDate(c, today) {
  if (today < c.start) return 0;
  if (today >= c.end) return c.spend;
  var elapsed = (Date.parse(today) - Date.parse(c.start)) / 86400000 + 1;
  return c.spend * Math.min(1, Math.max(0, elapsed / c.days));
}
function actualToDate(name, today) {
  if (!ACTUALS) return null;
  var sum = 0;
  ACTUALS.forEach(function (r) { if (r.campaign === name && r.date <= today) sum += (r.spend || 0); });
  return sum;
}

function render() {
  var today = new Date().toISOString().slice(0, 10);
  var inFlight = today >= DATA.flight.start && today <= DATA.flight.end;
  var h = '<thead><tr><th>Campaign</th><th>Window</th><th>Days</th><th>Spend goal</th>'
    + (HAS_IMPS ? '<th>Impressions goal</th>' : '') + (HAS_CLICKS ? '<th>Clicks goal</th>' : '')
    + '<th>Spend / day</th>'
    + (inFlight ? '<th>Expected to date</th>' : '')
    + (ACTUALS ? '<th>Actual to date</th><th>vs expected</th>' : '')
    + '</tr></thead><tbody>';
  var totals = { spend: 0, exp: 0, act: 0 };
  DATA.campaigns.forEach(function (c) {
    var exp = expectedToDate(c, today);
    var act = actualToDate(c.name, today);
    totals.spend += c.spend; totals.exp += exp; if (act != null) totals.act += act;
    h += '<tr><td><div class="cname">' + esc(c.name) + '</div>'
      + (c.platform ? '<div class="cplat">' + esc(c.platform) + '</div>' : '')
      + (c.source ? '<div class="csrc">Source: ' + esc(c.source) + '</div>' : '') + '</td>'
      + '<td>' + c.start + ' to ' + c.end + '</td>'
      + '<td>' + c.days + '</td>'
      + '<td>' + money(c.spend) + '</td>'
      + (HAS_IMPS ? '<td>' + num(c.impressions) + '</td>' : '')
      + (HAS_CLICKS ? '<td>' + num(c.clicks) + '</td>' : '')
      + '<td>' + money(c.spend / c.days) + '</td>'
      + (inFlight ? '<td>' + money(exp) + '</td>' : '')
      + (ACTUALS ? '<td>' + money(act) + '</td><td>' + (act == null ? '' : money(act - exp)) + '</td>' : '')
      + '</tr>';
  });
  h += '</tbody><tfoot><tr><td>Total</td><td></td><td></td><td>' + money(totals.spend) + '</td>'
    + (HAS_IMPS ? '<td></td>' : '') + (HAS_CLICKS ? '<td></td>' : '')
    + '<td>' + money(totals.spend / DATA.flight.days) + '</td>'
    + (inFlight ? '<td>' + money(totals.exp) + '</td>' : '')
    + (ACTUALS ? '<td>' + money(totals.act) + '</td><td>' + money(totals.act - totals.exp) + '</td>' : '')
    + '</tr></tfoot>';
  document.getElementById('tbl').innerHTML = h;

  var foot = 'Generated ' + DATA.generated + '. Spend / day and expected-to-date use each line\\'s own window, flat curve.';
  if (DATA.exceptions && DATA.exceptions.length) {
    foot += ' Exceptions (no baseline rows): ' + DATA.exceptions.map(function (e) { return e.campaign + ' (missing ' + e.missing.join(', ') + ')'; }).join('; ') + '.';
  }
  foot += ACTUALS ? ' Actuals joined.' : ' Actuals not joined yet - teammate hook: window.BB_ACTUALS = daily rows {date:"YYYY-MM-DD", campaign, spend} before this script runs, or call joinActuals(rows) later.';
  document.getElementById('foot').textContent = foot;
}

function joinActuals(rowsIn) { ACTUALS = rowsIn; render(); }
window.joinActuals = joinActuals;
if (window.BB_ACTUALS) ACTUALS = window.BB_ACTUALS;
render();
</script>
</body>
</html>
`;
fs.writeFileSync(path.join(OUT, 'pacing.html'), pacingHtml.replace('__DATA__', JSON.stringify(DATA)));

// ---------------------------------------------------------------- flowchart.html (from findings)
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
