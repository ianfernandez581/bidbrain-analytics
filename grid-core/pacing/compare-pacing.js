'use strict';

/**
 * Comparison harness. Reads nothing but the database, writes nothing, changes
 * nothing. Runs the new engine against every campaign and prints where it
 * disagrees with what the Grid says today.
 *
 *   node pacing/compare-pacing.js
 *   node pacing/compare-pacing.js --csv > tmp/pacing-diff.csv
 *
 * Every disagreement is a bug in one of the two. Expect to find some in each.
 */

const path = require('path');
const { computePacing, profitAtRisk, rollUpByCurrency, resolveMargin, normPlatform } = require('./pacing');

const AS_OF = process.env.PACING_AS_OF || new Date().toISOString().slice(0, 10);
const CSV = process.argv.includes('--csv');

function load(rel) {
  try { return require(path.join('..', rel)); } catch (e) { return null; }
}
const db = load('src/brain/db.js');
const calc = load('src/central/calc.js');
if (!db) {
  console.error('Could not load src/brain/db.js from this path. Run from the repo root as: node pacing/compare-pacing.js');
  process.exit(1);
}

const campaigns = (db.getCampaigns() || []).filter(c => !c.archivedAt);

/** What the Grid shows today. Prefers calc.js; falls back to the documented formula. */
function currentVerdict(c) {
  const budget = c.budgetGross != null && c.budgetGross !== '' ? Number(c.budgetGross) : Number(c.totalBudget);
  const spent = Number(c.clientSpend);
  let pctSpent = null, pctElapsed = null, label = null, via = 'inline';

  if (calc && typeof calc.pctBudgetSpent === 'function') {
    try { pctSpent = calc.pctBudgetSpent(c); via = 'calc.js'; } catch (e) { /* fall through */ }
  }
  if (calc && typeof calc.pctFlightElapsed === 'function') {
    try { pctElapsed = calc.pctFlightElapsed(c); via = 'calc.js'; } catch (e) { /* fall through */ }
  }
  if (calc && typeof calc.pacingStatus === 'function') {
    try { label = calc.pacingStatus(c); via = 'calc.js'; } catch (e) { /* fall through */ }
  }

  if (pctSpent == null && budget > 0 && Number.isFinite(spent)) pctSpent = spent / budget;
  if (pctElapsed == null && c.startDate && c.endDate) {
    const s = Date.parse(c.startDate), e = Date.parse(c.endDate), n = Date.parse(AS_OF);
    if (Number.isFinite(s) && Number.isFinite(e) && e > s) {
      pctElapsed = Math.max(0, Math.min(1, (n - s) / (e - s)));
    }
  }
  const ratio = (pctSpent != null && pctElapsed > 0) ? pctSpent / pctElapsed : null;
  if (!label && ratio != null) {
    label = pctElapsed < 0.15 ? 'Early' : ratio > 1.10 ? 'Over' : ratio < 0.90 ? 'Under' : 'On';
  }
  return { budget, spent, pctSpent, pctElapsed, ratio, label, via };
}

/**
 * The new engine, in degraded mode, because grid-core has no daily series yet.
 * Basis is resolved per platform: every platform's stored figure is billed,
 * either because it reports billed (TradeDesk) or because margin is zero and
 * media equals billed. Anything unmapped is left unknown rather than assumed.
 */
function newVerdict(c) {
  const platform = normPlatform(c.channel);
  const budget = c.budgetGross != null && c.budgetGross !== '' ? Number(c.budgetGross) : Number(c.totalBudget);

  // clientSpend is only written when spendMult is set (db.js:370-375). With a
  // null spendMult the sync updates mediaSpend and leaves clientSpend empty, so
  // reading clientSpend alone reports a delivering campaign as zero spend. This
  // hid Software First EcoStruxure's A$2,451.20 entirely.
  //
  // Falling back to mediaSpend is correct here: TradeDesk reports billed, and
  // everywhere else margin is zero so media equals billed. See PLATFORM_RULES.
  let spent = Number(c.clientSpend);
  let spentFrom = 'clientSpend';
  if (!Number.isFinite(spent) && Number.isFinite(Number(c.mediaSpend))) {
    spent = Number(c.mediaSpend);
    spentFrom = 'mediaSpend fallback';
  }
  const lastData = c.lastSyncedAt ? String(c.lastSyncedAt).slice(0, 10) : null;

  if (!(budget > 0) || !Number.isFinite(spent) || !c.startDate || !c.endDate || !lastData) {
    return { skipped: true, why: !(budget > 0) ? 'no budget' : !Number.isFinite(spent) ? 'no spend'
      : !c.startDate || !c.endDate ? 'missing flight dates' : 'never synced' };
  }
  try {
    const out = computePacing({
      budget,
      spendBasis: resolveMargin(platform) >= 0 && platform ? 'billed' : 'unknown',
      currency: c.currency || null,
      platform: c.channel,
      plannedStart: String(c.startDate).slice(0, 10),
      flightEnd: String(c.endDate).slice(0, 10),
      spentToDate: spent,
      lastDataDate: lastData,
      asOf: AS_OF
    });
    out.spentFrom = spentFrom;
    if (spentFrom !== 'clientSpend') out.reasons.push('spend read from ' + spentFrom);
    return out;
  } catch (e) {
    return { skipped: true, why: e.message };
  }
}

// ENDED is not a disagreement: a finished campaign that underspent is both
// "Under" to calc.js and "ENDED" to the engine, and calc.js's label is arguably
// the more useful one. Judge ended campaigns on their final shortfall instead.
const AGREE = {
  On: ['ON_TRACK', 'ENDED'],
  Over: ['TOO_FAST', 'ENDED'],
  Under: ['BEHIND_RECOVERING', 'BEHIND_NOT_RECOVERING', 'UNREACHABLE', 'ENDED'],
  Early: ['TOO_EARLY', 'ENDED'],
  '-': ['TOO_EARLY', 'NOT_LAUNCHED', 'BASIS_UNKNOWN', 'ENDED']
};

const rows = [];
for (const c of campaigns) {
  const old = currentVerdict(c);
  const nw = newVerdict(c);
  if (nw.skipped) { rows.push({ c, old, nw, verdict: 'SKIPPED' }); continue; }
  const expected = AGREE[old.label] || [];
  const agrees = expected.includes(nw.state);
  rows.push({ c, old, nw, verdict: agrees ? 'agree' : 'DISAGREE' });
}

const order = { DISAGREE: 0, SKIPPED: 1, agree: 2 };
rows.sort((a, b) => (order[a.verdict] - order[b.verdict])
  || ((b.nw.shortfall || 0) - (a.nw.shortfall || 0)));

if (CSV) {
  console.log('verdict,client,campaign,channel,currency,budget,spent,grid_pct_spent,grid_pct_elapsed,grid_ratio,grid_label,new_state,drift_days,required_daily,shortfall,data_age_days,stale,reason');
  for (const r of rows) {
    const f = v => v == null ? '' : (typeof v === 'number' ? Math.round(v * 1000) / 1000 : String(v).replace(/[",\n]/g, ' '));
    console.log([r.verdict, f(r.c.client), f(r.c.name), f(r.c.channel), f(r.c.currency), f(r.old.budget),
      f(r.old.spent), f(r.old.pctSpent), f(r.old.pctElapsed), f(r.old.ratio), f(r.old.label),
      f(r.nw.state || 'skipped'), f(r.nw.driftDays), f(r.nw.requiredDaily), f(r.nw.shortfall),
      f(r.nw.dataAgeDays), f(r.nw.stale), f(r.nw.why || (r.nw.reasons || []).join('; '))].join(','));
  }
  process.exit(0);
}

const n = v => v == null ? '—' : (typeof v === 'number' ? v.toFixed(2) : String(v));
const counts = rows.reduce((a, r) => (a[r.verdict] = (a[r.verdict] || 0) + 1, a), {});

console.log(`\nPacing comparison  as of ${AS_OF}  ·  ${campaigns.length} campaigns`);
console.log(`grid figures read via: ${rows.find(r => r.old.via) ? rows[0].old.via : 'inline'}`);
console.log(`disagree ${counts.DISAGREE || 0}   ·   agree ${counts.agree || 0}   ·   skipped ${counts.SKIPPED || 0}\n`);

console.log('DISAGREEMENTS, worst exposure first');
console.log('-'.repeat(112));
for (const r of rows.filter(x => x.verdict === 'DISAGREE')) {
  console.log(`${String(r.c.client || '').slice(0, 16).padEnd(17)}${String(r.c.name || '').slice(0, 30).padEnd(31)}${String(r.c.channel || '').slice(0, 10).padEnd(11)}`);
  console.log(`   grid: ${String(r.old.label).padEnd(6)} ratio ${n(r.old.ratio).padStart(6)}   ` +
              `spent ${n(r.old.pctSpent && r.old.pctSpent * 100).padStart(6)}%  elapsed ${n(r.old.pctElapsed && r.old.pctElapsed * 100).padStart(6)}%`);
  console.log(`   new:  ${String(r.nw.state).padEnd(22)} drift ${n(r.nw.driftDays).padStart(8)}d  ` +
              `needs ${n(r.nw.requiredDaily).padStart(9)}/day  shortfall ${n(r.nw.shortfall).padStart(10)}`);
  if (r.nw.reasons && r.nw.reasons.length) console.log(`   why:  ${r.nw.reasons.join(' | ')}`);
  console.log('');
}

console.log('\nSKIPPED, the engine refused rather than guessing');
for (const r of rows.filter(x => x.verdict === 'SKIPPED')) {
  console.log(`   ${String(r.c.client || '').slice(0, 16).padEnd(17)}${String(r.c.name || '').slice(0, 30).padEnd(31)}${r.nw.why}`);
}

const live = rows.filter(r => !r.nw.skipped && r.nw.shortfall > 0);
console.log('\n\nEXPOSURE BY CURRENCY, never summed across them');
const by = rollUpByCurrency(live.map(r => r.nw));
for (const [cur, agg] of Object.entries(by)) {
  console.log(`   ${cur.padEnd(10)} budget ${agg.budget.toFixed(0).padStart(12)}  spent ${agg.spent.toFixed(0).padStart(12)}  shortfall ${agg.shortfall.toFixed(0).padStart(12)}  worst ${agg.worstState}`);
}

console.log('\nTOP EXPOSURE, single campaigns');
for (const r of live.sort((a, b) => b.nw.shortfall - a.nw.shortfall).slice(0, 10)) {
  const p = profitAtRisk(r.nw);
  console.log(`   ${String(r.c.client || '').slice(0, 14).padEnd(15)}${String(r.c.name || '').slice(0, 28).padEnd(29)}` +
    `${String(r.nw.state).padEnd(22)}shortfall ${r.nw.currency || '?'} ${r.nw.shortfall.toFixed(0).padStart(10)}` +
    `   profit at risk ${p.value == null ? '—' : p.value.toFixed(0)} (est)`);
}
console.log('\nNothing was written. This is a report only.\n');
