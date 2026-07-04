#!/usr/bin/env node
/**
 * derive.test.js — proves derive.js reproduces the "Live Campaigns" sheet's own
 * computed values. Each fixture is a real row: raw inputs on the left, the
 * sheet's cached output on the right. If a formula drifts, this fails loudly.
 *
 * Run: node derive.test.js
 */
'use strict';
const D = require('./derive');

// Fixtures taken directly from CENTRAL_100__Digital.xlsx "Live Campaigns".
// asOf pins the snapshot the sheet was captured at (26 Jun 2026) so %elapsed matches.
const ASOF = '2026-06-26';
const F = [
  { name: 'City Perfume · Always On · TradeDesk (row 6)',
    raw: { start: '2026-06-01', end: '2026-06-30', totalBudget: 5000, mediaSpend: 1048.36,
           clientSpent: 3957.75, impressions: 327885, adServingRate: 5, platformMargin: 0.4 },
    expect: { adservingCost: 1639.425, pctSpent: 0.7915, budgetRemaining: 1042.25 } },
  { name: 'Gateway Project · Meta (row 7, hacks stripped)',
    raw: { start: '2026-05-01', end: '2026-07-20', totalBudget: 11250, mediaSpend: 8128.64,
           clientSpent: 16257.28, impressions: 1588902, adServingRate: 0, platformMargin: 0.5 },
    expect: { campaignMargin: 0.5, budgetRemaining: -5007.28 } },
  { name: 'VMCH · Retirement · TradeDesk (row ~11)',
    raw: { start: '2026-05-12', end: '2026-08-15', totalBudget: 15000, mediaSpend: 2623.34,
           clientSpent: 7495.24, impressions: 1515172, adServingRate: 0, platformMargin: 0.65 },
    expect: { pctSpent: 0.4997, budgetRemaining: 7504.76 } },
];

let pass = 0, fail = 0;
const near = (a, b, tol = 0.01) => a != null && b != null && Math.abs(a - b) <= Math.max(tol, Math.abs(b) * 0.001);
const pc = n => n == null ? '—' : (n * 100).toFixed(2) + '%';

for (const f of F) {
  const d = D.derive(f.raw, { asOf: ASOF });
  const results = Object.entries(f.expect).map(([k, exp]) => {
    const got = d[k];
    const ok = near(got, exp);
    return { k, got, exp, ok };
  });
  const allOk = results.every(r => r.ok);
  console.log(`${allOk ? '✓' : '✗'} ${f.name}`);
  for (const r of results) {
    if (!r.ok) console.log(`    ${r.k}: got ${r.got}, expected ${r.exp}`);
  }
  // show the full pacing line for eyeballing
  console.log(`    pctSpent=${pc(d.pctSpent)} pctElapsed=${pc(d.pctElapsed)} pacing=${d.pacingStatus?.toFixed(3) ?? '—'} margin=${d.campaignMargin?.toFixed(3) ?? '—'} adServ=${d.adservingCost?.toFixed(2) ?? '—'}`);
  allOk ? pass++ : fail++;
}
console.log(`\n${pass} passed, ${fail} failed.`);
process.exit(fail ? 1 : 0);
