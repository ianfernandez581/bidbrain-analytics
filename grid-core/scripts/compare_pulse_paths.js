#!/usr/bin/env node
/**
 * compare_pulse_paths.js — PHASE 1 SAFETY NET (playbook Deliverable 3).
 *
 * For every Schneider campaign (default; --client X / --all to widen) computes the
 * key Pulse numbers through BOTH pipes and prints a diff:
 *
 *   OLD path  = the baked `const DATA` literal (frozen at
 *               test-fixtures/pulse-legacy/const-data-2026-07-08.json) + a VERBATIM
 *               replica of the legacy inline engine from the-grid.html
 *               (SNAP=2026-07-08, PACE_BAND=0.15, gap-banded pace, totalBudget base).
 *   NEW path  = the live SQLite DB (src/brain/db.js; seeded from
 *               config/central-import.json exactly like server.js boot) +
 *               src/central/calc.js computeRow() PINNED to the same as-of date, so
 *               every difference is formula/input, never calendar drift.
 *
 * Every difference is mechanically classified:
 *   SAME         values agree within tolerance
 *   FORMULA(Rn)  replaying the OLD formula on the NEW inputs reproduces the old
 *                value -> the difference is exactly reconciliation-table row Rn
 *                (see PHASE1_REPORT.md Deliverable 2)
 *   INPUT-DRIFT  the raw inputs themselves differ (const DATA and central-import.json
 *                are different vintages of the same sheet) — reported, expected
 *   UNEXPLAINED  none of the above -> a BUG; the script exits 1
 *
 * Run: node scripts/compare_pulse_paths.js [--client Schneider] [--all] [--quiet]
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const calc = require('../src/central/calc');
const db = require('../src/brain/db');
const centralView = require('../src/central/render-central');

// ---------- args ----------
const argv = process.argv.slice(2);
const ALL = argv.includes('--all');
const QUIET = argv.includes('--quiet');
const ci = argv.indexOf('--client');
const CLIENT = ALL ? null : (ci >= 0 ? argv[ci + 1] : 'Schneider');

// ---------- the pinned as-of (the legacy SNAP) ----------
const SNAP = new Date('2026-07-08T00:00:00');
const DAY = 86400000;

// ---------- OLD path: verbatim replica of the legacy inline engine ----------
const PACE_BAND = 0.15, PROJ_BAND = 0.05, MARGIN_MIN = 0.001, ASSUMED_MARGIN = 0.60;
function oldDerive(c) {
  // exact transcription of derive() from the retired the-grid.html inline engine
  const b = c.totalBudget, s = c.clientSpent;
  const d = { daysTotal: null, daysElapsed: null, daysLeft: null, runRate: null, reqDaily: null,
    projTotal: null, projVar: null, marginPct: null, marginKnown: false, marginAtRisk: null,
    projState: 'none', paceState: 'none', atStake: 0 };
  d.marginPct = (c.campaignMargin != null && c.campaignMargin > MARGIN_MIN) ? c.campaignMargin : null;
  d.marginKnown = d.marginPct != null;
  if (c.pctSpent != null && c.pctElapsed != null) {
    const g = c.pctSpent - c.pctElapsed;
    d.paceState = g > PACE_BAND ? 'over' : g < -PACE_BAND ? 'under' : 'ok';
  }
  if (c.start && c.end && b) {
    const sd = new Date(c.start), ed = new Date(c.end);
    d.daysTotal = Math.round((ed - sd) / DAY); d.daysElapsed = Math.round((SNAP - sd) / DAY); d.daysLeft = Math.round((ed - SNAP) / DAY);
    if (d.daysTotal > 0) {
      if (d.daysElapsed > 0 && s != null) { d.runRate = s / d.daysElapsed; d.projTotal = d.runRate * d.daysTotal; d.projVar = d.projTotal - b; }
      if (d.daysLeft > 0 && c.budgetRemaining != null) d.reqDaily = c.budgetRemaining / d.daysLeft;
    }
  }
  if (d.projVar != null) { const tol = PROJ_BAND * b; d.projState = d.projVar > tol ? 'over' : d.projVar < -tol ? 'under' : 'onplan'; }
  const shortfall = (d.projVar != null && d.projVar < 0) ? -d.projVar : 0;
  const overrun = (d.projVar != null && d.projVar > 0) ? d.projVar : 0;
  const effM = d.marginPct != null ? d.marginPct : ASSUMED_MARGIN;
  if (shortfall > 0) d.marginAtRisk = shortfall * effM;
  d.atStake = shortfall > 0 ? d.marginAtRisk : overrun;
  return d;
}

// OLD formulas replayed on the NEW row's inputs (for FORMULA vs INPUT-DRIFT
// classification). Same math as oldDerive but fed from the calc-shaped DB row.
function oldFormulaOnNewInputs(n) {
  const c = {
    totalBudget: n.totalBudget, clientSpent: n.clientSpend,
    start: n.startDate, end: n.endDate,
    // sheet formulas: X = V/S, Y = MIN((asof-H)/(I-H),1), W = S-V
    pctSpent: (n.clientSpend != null && n.totalBudget) ? n.clientSpend / n.totalBudget : null,
    pctElapsed: null, budgetRemaining: (n.totalBudget != null && n.clientSpend != null) ? n.totalBudget - n.clientSpend : null,
    campaignMargin: null,
  };
  if (n.startDate && n.endDate) {
    const sd = new Date(n.startDate), ed = new Date(n.endDate);
    const span = ed - sd;
    if (span > 0) c.pctElapsed = Math.min((SNAP - sd) / span, 1);
  }
  // sheet J = (V-U-M)/V with M = T/1000*L (the derived rate cost)
  const rate = Number(n.adServing), imp = Number(n.impressions);
  const mCost = (Number.isFinite(rate) && rate !== 0 && Number.isFinite(imp) && imp !== 0) ? (imp / 1000) * rate : 0;
  if (n.clientSpend != null && n.clientSpend !== 0 && n.mediaSpend != null) {
    c.campaignMargin = (n.clientSpend - n.mediaSpend - mCost) / n.clientSpend;
  }
  return { row: c, d: oldDerive(c) };
}

// ---------- NEW path: seed the DB exactly like server.js boot, then calc.js ----------
function seedDbIfEmpty() {
  const snapPath = path.join(ROOT, 'config', 'central-import.json');
  if (fs.existsSync(snapPath)) {
    const snap = JSON.parse(fs.readFileSync(snapPath, 'utf8'));
    const mapped = snap.map(r => centralView._mapGridRowToCentral(r));
    const res = db.importCentralSnapshot(mapped);
    if (res.inserted) console.log(`[seed] imported ${res.inserted} campaigns from the sheet snapshot`);
  }
  const extraPath = path.join(ROOT, 'config', 'central-extra-campaigns.json');
  if (fs.existsSync(extraPath)) {
    const doc = JSON.parse(fs.readFileSync(extraPath, 'utf8'));
    const rows = Array.isArray(doc) ? doc : (doc.campaigns || []);
    let created = 0;
    for (const r of rows) {
      if (!r || !r.client || !r.name) continue;
      const dup = db.getCampaigns().some(c => c.client === r.client && c.name === r.name && (c.channel || null) === (r.channel || null) && !c.archivedAt);
      if (dup) continue;
      const cr = db.createCampaign(r, 'scan');
      if (cr.ok) created++;
    }
    if (created) console.log(`[seed] created ${created} scan-sourced rows`);
  }
}

// ---------- matching (old row <-> new row) ----------
const norm = s => String(s == null ? '' : s).trim().toLowerCase().replace(/\s+/g, ' ');
const key = (client, name, channel) => norm(client) + '|' + norm(name) + '|' + norm(channel);
function groupBy(rows, fk) { const m = {}; rows.forEach(r => { const k = fk(r); (m[k] || (m[k] = [])).push(r); }); return m; }
const bySize = (a, b) => (b.totalBudget || 0) - (a.totalBudget || 0) || ((b.clientSpend != null ? b.clientSpend : b.clientSpent) || 0) - ((a.clientSpend != null ? a.clientSpend : a.clientSpent) || 0);

// ---------- comparison core ----------
const nearAbs = (a, b, tol) => Math.abs(a - b) <= tol;
function same(a, b, tolAbs = 0.005) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  const na = Number(a), nb = Number(b);   // DB stores some numerics as TEXT (adServing) — compare numerically when possible
  if (Number.isFinite(na) && Number.isFinite(nb)) return nearAbs(na, nb, Math.max(tolAbs, Math.abs(nb) * 0.005));
  if (typeof a === 'string' || typeof b === 'string') return String(a) === String(b);
  return nearAbs(a, b, Math.max(tolAbs, Math.abs(b) * 0.005));
}
const fm = v => v == null ? '—' : (typeof v === 'number' ? (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : v.toFixed(4)) : String(v));

// metric spec: [label, old-displayed, new(calc.js), old-formula-on-new-inputs, D2 code, inputs-used]
function buildMetrics(o, od, n, nd, rf) {
  const rd = rf.d, rr = rf.row;
  return [
    ['% budget spent', o.pctSpent, nd.pctBudgetSpent, rr.pctSpent, 'R1 (base: totalBudget -> effectiveBudget)', ['clientSpend', 'totalBudget', 'budgetGross']],
    ['% flight elapsed', o.pctElapsed, nd.pctFlightElapsed, rr.pctElapsed, 'R3 (as-of anchoring + clamp)', ['startDate', 'endDate']],
    ['pace state', od.paceState, nd.paceBucket, rd.paceState, 'R4 (gap ±0.15 -> ratio 0.90/1.10)', ['clientSpend', 'totalBudget', 'budgetGross', 'startDate', 'endDate']],
    ['campaign margin', o.campaignMargin, nd.campaignMargin, rr.campaignMargin, 'R8 (adserving cost: baked cell -> derived)', ['clientSpend', 'mediaSpend', 'impressions', 'adServing']],
    ['profit at risk', od.marginAtRisk, nd.profitAtRisk, rd.marginAtRisk, 'R6+R7 (effective-margin rule + budget base)', ['clientSpend', 'totalBudget', 'budgetGross', 'startDate', 'endDate', 'platformMargin', 'channel', 'mediaSpend']],
    ['needs $/day', od.reqDaily, nd.reqDaily, rd.reqDaily, 'R2+R7 (remaining base: totalBudget -> effectiveBudget)', ['clientSpend', 'totalBudget', 'budgetGross', 'endDate']],
    // sheet O = (V/T)*1000 — replayed on new inputs for the basis-change check
    ['CPM performance', o.cpmPerf, nd.cpmPerformance,
      (n.clientSpend != null && n.impressions) ? (n.clientSpend / n.impressions) * 1000 : null,
      'R5 (basis: clientSpend -> mediaSpend)', ['clientSpend', 'mediaSpend', 'impressions']],
  ];
}

// raw-input drift between the old baked row and the new DB row
function inputDrift(o, n) {
  const pairs = [
    ['clientSpend', o.clientSpent, n.clientSpend], ['mediaSpend', o.mediaSpend, n.mediaSpend],
    ['impressions', o.impressions, n.impressions], ['totalBudget', o.totalBudget, n.totalBudget],
    ['budgetGross', o.budgetGross, n.budgetGross], ['platformMargin', o.platformMargin, n.platformMargin],
    ['adServing', o.adServing, n.adServing], ['startDate', o.start, n.startDate], ['endDate', o.end, n.endDate],
    ['status', o.status, n.status],
  ];
  return pairs.filter(([, a, b]) => !same(a, b, 0.01)).map(([k, a, b]) => `${k}: ${fm(a)} -> ${fm(b)}`);
}

function main() {
  seedDbIfEmpty();
  const oldRows = JSON.parse(fs.readFileSync(path.join(ROOT, 'test-fixtures', 'pulse-legacy', 'const-data-2026-07-08.json'), 'utf8'))
    .filter(r => ALL || norm(r.advertiser) === norm(CLIENT));
  const newRows = db.getCampaigns().filter(r => !r.archivedAt && (ALL || norm(r.client) === norm(CLIENT)));

  const og = groupBy(oldRows, r => key(r.advertiser, r.campaign, r.channel));
  const ng = groupBy(newRows, r => key(r.client, r.name, r.channel));

  let counts = { SAME: 0, FORMULA: 0, 'INPUT-DRIFT': 0, 'BAKED-ARTIFACT': 0, UNEXPLAINED: 0 };
  const unexplained = [];
  const onlyOld = [], onlyNew = [];

  console.log(`\n=== Pulse OLD (const DATA + legacy inline engine) vs NEW (SQLite + calc.js) ===`);
  console.log(`scope: ${ALL ? 'ALL clients' : CLIENT} · both paths pinned as-of ${SNAP.toISOString().slice(0, 10)}\n`);

  for (const k of Object.keys(og).sort()) {
    const olds = og[k].slice().sort(bySize);
    const news = (ng[k] || []).slice().sort(bySize);
    olds.forEach((o, i) => {
      const n = news[i];
      if (!n) { onlyOld.push(`${o.advertiser} · ${o.campaign} · ${o.channel}`); return; }
      const od = oldDerive(o);
      const nd = calc.computeRow(n, SNAP);
      const rf = oldFormulaOnNewInputs(n);
      const drift = inputDrift(o, n);
      const metrics = buildMetrics(o, od, n, nd, rf);
      const lines = [];
      const preFlight = n.startDate && new Date(n.startDate) > SNAP;
      for (const [label, oldV, newV, replayV, code, inputs] of metrics) {
        let cls;
        if (same(oldV, newV)) cls = 'SAME';
        else if (same(replayV, oldV)) cls = `FORMULA ${code}`;
        // the metric's own inputs changed between sheet vintages -> input drift
        else if (drift.some(dr => inputs.some(f => dr.startsWith(f + ':')))) cls = 'INPUT-DRIFT';
        // replay == new: the OLD formula on the row's own inputs agrees with the new
        // engine, so the baked sheet CELL disagrees with its own row (stale cell, or
        // Excel blank-as-zero artifacts like margin=1.0 with no media spend).
        else if (same(replayV, newV)) cls = 'BAKED-ARTIFACT (sheet cell inconsistent with its own inputs)';
        // pre-flight rows: calc.js clamps % elapsed to 0; the sheet's MIN(...,1) had
        // no lower clamp (negative) and usually a blank cell — the R3 clamp change.
        else if (preFlight && typeof newV === 'number' && newV === 0) cls = 'FORMULA R3 (pre-flight lower clamp to 0)';
        else cls = 'UNEXPLAINED';
        const bucket = cls.startsWith('FORMULA') ? 'FORMULA' : cls.startsWith('BAKED-ARTIFACT') ? 'BAKED-ARTIFACT' : cls;
        counts[bucket] = (counts[bucket] || 0) + 1;
        if (bucket === 'UNEXPLAINED') unexplained.push(`${o.advertiser} · ${o.campaign} · ${o.channel} · ${label}: old=${fm(oldV)} new=${fm(newV)} replay=${fm(replayV)}`);
        if (bucket !== 'SAME') lines.push(`    ${label.padEnd(17)} old=${fm(oldV).padStart(12)}  new=${fm(newV).padStart(12)}  -> ${cls}`);
      }
      if (!QUIET && lines.length) {
        console.log(`▸ ${o.advertiser} · ${o.campaign} · ${o.channel} (${o.status})`);
        if (drift.length) console.log(`    input drift: ${drift.join(' | ')}`);
        lines.forEach(l => console.log(l));
      }
    });
    if (news.length > olds.length) news.slice(olds.length).forEach(n => onlyNew.push(`${n.client} · ${n.name} · ${n.channel}`));
  }
  // rows present on one side only
  for (const k of Object.keys(ng)) if (!og[k]) ng[k].forEach(n => onlyNew.push(`${n.client} · ${n.name} · ${n.channel}`));

  console.log(`\n--- summary ---`);
  console.log(`metric comparisons: SAME=${counts.SAME}  FORMULA=${counts.FORMULA}  INPUT-DRIFT=${counts['INPUT-DRIFT']}  BAKED-ARTIFACT=${counts['BAKED-ARTIFACT']}  UNEXPLAINED=${counts.UNEXPLAINED}`);
  if (onlyOld.length) console.log(`rows only in the OLD baked data (dropped from the sheet since): ${onlyOld.length}\n  ` + onlyOld.join('\n  '));
  if (onlyNew.length) console.log(`rows only in the NEW DB (added to the sheet since / scan-sourced): ${onlyNew.length}\n  ` + onlyNew.join('\n  '));
  if (unexplained.length) {
    console.log(`\n✗ UNEXPLAINED differences (bugs — fix before the switch):`);
    unexplained.forEach(u => console.log('  ' + u));
    process.exit(1);
  }
  console.log(`\n✓ every difference is explained by the reconciliation table (FORMULA) or by sheet-vintage input drift.`);
}

main();
