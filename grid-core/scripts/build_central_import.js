/*
 * scripts/build_central_import.js — rebuild config/central-import.json from the media-buyer's
 * "Live Campaigns" sheet. DEFAULT ZONE (grid-core). Reproducible: re-run when Zhen sends a new sheet.
 *
 *   node scripts/build_central_import.js ["sample data/Central Updated.xlsx"]
 *
 * Import rules (see the definitive-rebuild spec):
 *   - DISCARD every DERIVED column (Campaign Margin, CPM Performance, Adserving Cost, Budget
 *     Remaining, %Budget Spent, %Flight Elapsed, Pacing Status) — calc.js computes them. This
 *     also sidesteps the sheet's $V$65 campaign-margin bug (17 rows).
 *   - Import CONFIG/API columns only. The "Ad-Serving" column is the RATE (e.g. 5.0), stored in
 *     `adServing`; calc.js derives adServingCost = impressions/1000 * rate.
 *   - spendMult = round(clientSpend/mediaSpend, 4) when both > 0 (the per-channel client markup),
 *     else null. This seeds the billed-spend gross-up so the sync can keep clientSpend live.
 *   - platformMargin sanity: keep only 0..1; "NA"/negative/>1 -> null (needs-input, never negative).
 *   - Output is the grid-shaped array central-seed/render expects (advertiser/campaign/start/...).
 *     HireRight is NOT here (added separately via central-extra-campaigns.json).
 */
'use strict';
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '..');
const XLSX = require(path.join(ROOT, 'node_modules', 'xlsx'));
const SRC = process.argv[2] || path.join(ROOT, 'sample data', 'Central Updated.xlsx');
const OUT = path.join(ROOT, 'config', 'central-import.json');

const wb = XLSX.readFile(SRC);
const ws = wb.Sheets[wb.SheetNames[0]];
const aoa = XLSX.utils.sheet_to_json(ws, { header: 1, defval: null, blankrows: false });
const H = aoa[1].map(c => String(c == null ? '' : c).trim());
const ci = re => H.findIndex(h => re.test(h.toLowerCase()));
const C = {
  job: ci(/job number/), campaign: 2, objective: ci(/objective/), channel: ci(/channel/), mgr: ci(/managed/),
  status: ci(/status/), start: ci(/start date/), end: ci(/end date/), platMargin: ci(/platform margin/),
  adServing: ci(/^ad-?serving\b/), forecastCpm: ci(/forecast cpm/), keyKpi: ci(/key kpi/), kpiPerf: ci(/kpi performance/),
  budgetGross: ci(/budget gross/), totalBudget: ci(/total budget/), imp: ci(/impressions to date/),
  media: ci(/media spend to date/), client: ci(/client spent/), link: ci(/campaign or account/), nextRep: ci(/next reporting/), notes: ci(/links ?\/ ?notes/)
};

const norm = s => String(s == null ? '' : s).trim();
function serial(n) { return new Date(Date.UTC(1899, 11, 30) + Math.round(n) * 86400000).toISOString().slice(0, 10); }
function asDate(v) { if (v == null || v === '') return null; if (v instanceof Date) return v.toISOString().slice(0, 10); if (typeof v === 'number' && v > 30000 && v < 90000) return serial(v); const t = Date.parse(v); return isNaN(t) ? String(v) : new Date(t).toISOString().slice(0, 10); }
function numOrNull(v) { if (v == null || v === '' || /^na$/i.test(String(v).trim())) return null; const n = Number(String(v).replace(/[$,%\s]/g, '')); return isFinite(n) ? n : null; }
function platSanity(v) { const n = numOrNull(v); if (n == null || n < 0 || n > 1) return null; return n; }
function round4(n) { return Math.round(n * 10000) / 10000; }
const isSection = (a, camp, chan) => a && !camp && !chan && /^(100% ?digital|transmission)$/i.test(a);

let curSection = null, curClient = null;
const rows = [];
aoa.slice(2).forEach(r => {
  if (!r) return;
  const a = norm(r[0]), camp = norm(r[C.campaign]), chan = norm(r[C.channel]);
  if (isSection(a, camp, chan)) { curSection = a.toUpperCase().replace('100%DIGITAL', '100% DIGITAL'); return; }
  if (a) curClient = a;
  if (!camp && !chan) return;                       // spacer / total row
  const media = numOrNull(r[C.media]), client = numOrNull(r[C.client]);
  const spendMult = (media != null && media > 0 && client != null && client > 0) ? round4(client / media) : null;
  rows.push({
    agency: curSection, advertiser: curClient,
    jobNumber: norm(r[C.job]) === 'NA' ? null : (norm(r[C.job]) || null),
    campaign: camp || null, objective: norm(r[C.objective]) || null, channel: chan || null,
    managedBy: norm(r[C.mgr]) || null, status: norm(r[C.status]) || null,
    start: asDate(r[C.start]), end: asDate(r[C.end]),
    platformMargin: platSanity(r[C.platMargin]),
    adServing: numOrNull(r[C.adServing]),           // the RATE (calc derives adServingCost)
    forecastCPM: numOrNull(r[C.forecastCpm]),
    keyKPI: norm(r[C.keyKpi]) || null, kpiPerf: norm(r[C.kpiPerf]) || null,
    budgetGross: numOrNull(r[C.budgetGross]), totalBudget: numOrNull(r[C.totalBudget]),
    impressions: numOrNull(r[C.imp]), mediaSpend: media, clientSpent: client, spendMult: spendMult,
    campaignLink: norm(r[C.link]) || null, nextReport: norm(r[C.nextRep]) || null, notes: norm(r[C.notes]) || null
  });
});

fs.writeFileSync(OUT, JSON.stringify(rows, null, 0) + '\n');
// report
const byClient = {}; rows.forEach(r => byClient[r.advertiser] = (byClient[r.advertiser] || 0) + 1);
console.log('WROTE ' + OUT);
console.log('rows: ' + rows.length + ' | clients: ' + Object.keys(byClient).length);
console.log('with spendMult: ' + rows.filter(r => r.spendMult != null).length + ' | platformMargin null (NA/out-of-range): ' + rows.filter(r => r.platformMargin == null).length);
console.log('sections: ' + [...new Set(rows.map(r => r.agency))].join(', '));
