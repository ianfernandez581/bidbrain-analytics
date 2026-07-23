#!/usr/bin/env node
/**
 * calc.test.js — Phase 1: the per-channel MARGIN RULE + the Pulse formulas ported
 * into calc.js (the single engine). Covers the five playbook-mandated cases:
 *   1. a TradeDesk row            -> Platform Margin
 *   2. a DV360 row                -> Platform Margin
 *   3. a Google Ads row           -> Campaign Margin
 *   4. platformMargin PRESENT but channel=Meta -> Campaign Margin (rule wins)
 *   5. TTD row MISSING platformMargin -> degrades LOUDLY (warning set, fallback
 *      to realized campaign margin, else ASSUMED_MARGIN — documented in calc.js)
 * Plus: profit-at-risk uses the effective margin, projection math, paceBucket
 * band consistency with pacingStatus.
 *
 * Run: node src/central/calc.test.js
 */
'use strict';
const C = require('./calc');

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log('✓ ' + name); }
  else { fail++; console.log('✗ ' + name + (detail ? '  [' + detail + ']' : '')); }
}
const near = (a, b, tol = 1e-6) => a != null && b != null && Math.abs(a - b) <= tol;

// A row heading UNDER budget so profit-at-risk is non-zero and hand-checkable.
// Flight 2026-06-01 -> 2026-07-31 (60 days), asOf 2026-07-01 (30 elapsed, 30 left).
// budget 60,000; clientSpend 15,000 -> runRate 500/day -> projTotal 30,000 ->
// projVar -30,000 (shortfall 30,000); reqDaily = 45,000/30 = 1,500.
const BASE = {
  startDate: '2026-06-01', endDate: '2026-07-31', totalBudget: 60000,
  clientSpend: 15000, mediaSpend: 6000, impressions: 1000000, adServing: null,
};
const ASOF = new Date('2026-07-01T00:00:00');
// realized campaignMargin for BASE = (15000-6000-0)/15000 = 0.60

// ---- 1. TTD row with platformMargin -> Platform Margin ----
{
  const c = Object.assign({}, BASE, { channel: 'TradeDesk', platformMargin: 0.45 });
  const d = C.computeRow(c, ASOF);
  check('TTD: rule is platform', d.effectiveMarginRule === 'platform', d.effectiveMarginRule);
  check('TTD: uses Platform Margin 0.45 (not realized 0.60)', near(d.effectiveMargin, 0.45), d.effectiveMargin);
  check('TTD: source=platform, no warning', d.effectiveMarginSource === 'platform' && d.marginWarning === null);
  check('TTD: profitAtRisk = 30,000 x 0.45 = 13,500', near(d.profitAtRisk, 13500), d.profitAtRisk);
  check('TTD: "Trade Desk" (spaced) also matches the rule', C.marginRuleFor('Trade Desk') === 'platform');
}

// ---- 2. DV360 row with platformMargin -> Platform Margin ----
{
  const c = Object.assign({}, BASE, { channel: 'DV360', platformMargin: 0.5 });
  const d = C.computeRow(c, ASOF);
  check('DV360: uses Platform Margin 0.5', near(d.effectiveMargin, 0.5) && d.effectiveMarginSource === 'platform');
  check('DV360: profitAtRisk = 30,000 x 0.5 = 15,000', near(d.profitAtRisk, 15000), d.profitAtRisk);
}

// ---- 3. Google Ads row -> Campaign Margin ----
{
  const c = Object.assign({}, BASE, { channel: 'Google Ads', platformMargin: null });
  const d = C.computeRow(c, ASOF);
  check('Google: rule is campaign', d.effectiveMarginRule === 'campaign');
  check('Google: uses realized Campaign Margin 0.60', near(d.effectiveMargin, 0.60) && d.effectiveMarginSource === 'campaign');
  check('Google: profitAtRisk = 30,000 x 0.60 = 18,000', near(d.profitAtRisk, 18000), d.profitAtRisk);
  check('Google: no warning', d.marginWarning === null);
}

// ---- 4. platformMargin PRESENT but channel = Meta -> Campaign Margin wins ----
{
  const c = Object.assign({}, BASE, { channel: 'Meta', platformMargin: 0.9 });
  const d = C.computeRow(c, ASOF);
  check('Meta: rule is campaign even with platformMargin present', d.effectiveMarginRule === 'campaign');
  check('Meta: uses Campaign Margin 0.60, NOT the 0.9 platform margin', near(d.effectiveMargin, 0.60) && d.effectiveMarginSource === 'campaign');
  check('Meta: profitAtRisk on campaign margin (18,000)', near(d.profitAtRisk, 18000), d.profitAtRisk);
}

// ---- 5. TTD row MISSING platformMargin -> LOUD degrade ----
{
  // 5a: realized campaign margin available -> fall back to it, warning SET
  const c = Object.assign({}, BASE, { channel: 'TradeDesk', platformMargin: null });
  const d = C.computeRow(c, ASOF);
  check('TTD missing PM: warning=platform-margin-missing', d.marginWarning === 'platform-margin-missing');
  check('TTD missing PM: falls back to realized campaign margin', near(d.effectiveMargin, 0.60) && d.effectiveMarginSource === 'campaign');
  // 5b: platformMargin 0 counts as missing (sheet filler; x0 would silently zero risk)
  const c0 = Object.assign({}, BASE, { channel: 'TradeDesk', platformMargin: 0 });
  const d0 = C.computeRow(c0, ASOF);
  check('TTD PM=0: treated as missing (loud), not a x0 multiplier', d0.marginWarning === 'platform-margin-missing' && d0.profitAtRisk > 0);
  // 5c: no platform margin AND no usable realized margin -> ASSUMED_MARGIN, warning SET
  const cx = Object.assign({}, BASE, { channel: 'TradeDesk', platformMargin: null, mediaSpend: 15000 }); // margin 0 -> unusable
  const dx = C.computeRow(cx, ASOF);
  check('TTD missing PM + unusable CM: ASSUMED_MARGIN, source=assumed, warning set',
    near(dx.effectiveMargin, C.ASSUMED_MARGIN) && dx.effectiveMarginSource === 'assumed' && dx.marginWarning === 'platform-margin-missing');
}

// ---- channel without a platform-margin concept (DOOH / null) -> campaign rule ----
{
  check('DOOH: campaign rule', C.marginRuleFor('DOOH') === 'campaign');
  check('null channel: campaign rule', C.marginRuleFor(null) === 'campaign');
  check('LinkedIn/Reddit: campaign rule', C.marginRuleFor('Linkedin') === 'campaign' && C.marginRuleFor('Reddit') === 'campaign');
}

// ---- ported projection math (hand-checked against the BASE fixture) ----
{
  const c = Object.assign({}, BASE, { channel: 'Google Ads' });
  const d = C.computeRow(c, ASOF);
  check('days: 60 total / 30 elapsed / 30 left', d.daysTotal === 60 && d.daysElapsed === 30 && d.daysLeft === 30);
  check('runRate 500/day', near(d.runRate, 500), d.runRate);
  check('projTotal 30,000; projVar -30,000', near(d.projTotal, 30000) && near(d.projVar, -30000));
  check('reqDaily = 45,000/30 = 1,500 ("needs $X/day")', near(d.reqDaily, 1500), d.reqDaily);
  check('projState under (beyond the 5% band)', d.projState === 'under');
  check('pacingAction: reqDaily/runRate = 3x -> "Push hard / add room"', d.pacingAction === 'Push hard / add room', d.pacingAction);
  check('atStake equals profitAtRisk when under', near(d.atStake, d.profitAtRisk));
}

// ---- overrun side: atStake is the raw overrun $, profitAtRisk null ----
{
  const c = Object.assign({}, BASE, { channel: 'Google Ads', clientSpend: 45000, mediaSpend: 18000 });
  const d = C.computeRow(c, ASOF);   // runRate 1500 -> projTotal 90,000 -> +30,000 over
  check('over: projVar +30,000, projState over', near(d.projVar, 30000) && d.projState === 'over');
  check('over: profitAtRisk null, atStake = overrun 30,000', d.profitAtRisk === null && near(d.atStake, 30000));
  check('over: pacingAction "Cap or rebrief"', d.pacingAction === 'Cap or rebrief');
}

// ---- paceBucket bands are EXACTLY pacingStatus bands (lowercased) ----
// Band = PACE_BAND_UNDER/OVER (0.90/1.10 since the 2026-07-22 widening decision).
{
  const mk = (spent, elapsed) => C.paceBucket(spent, elapsed);
  check('paceBucket: ratio 1.12 -> over', mk(0.56, 0.5) === 'over');
  check('paceBucket: ratio 0.88 -> under', mk(0.44, 0.5) === 'under');
  check('paceBucket: ratio 1.06 inside the widened band -> ok', mk(0.53, 0.5) === 'ok');
  check('paceBucket: ratio 0.94 inside the widened band -> ok', mk(0.47, 0.5) === 'ok');
  check('paceBucket: ratio 1.0 -> ok', mk(0.5, 0.5) === 'ok');
  check('paceBucket: band constants exported (0.90/1.10)', C.PACE_BAND_UNDER === 0.90 && C.PACE_BAND_OVER === 1.10);
  check('paceBucket: null inputs -> none', mk(null, 0.5) === 'none' && mk(0.5, null) === 'none');
  const c = Object.assign({}, BASE, { channel: 'Google Ads' });
  const d = C.computeRow(c, ASOF);
  const map = { Over: 'over', Under: 'under', On: 'ok', Early: 'early', '-': 'none' };
  check('computeRow: paceBucket agrees with pacingStatus', map[d.pacingStatus] === d.paceBucket, d.pacingStatus + ' vs ' + d.paceBucket);
}

// ---- early-flight suppression: below 15% elapsed the ratio is noise, not judged ----
{
  const mk = (spent, elapsed) => C.paceBucket(spent, elapsed);
  check('early: threshold constant exported (0.15)', C.PACE_EARLY_FLIGHT_THRESHOLD === 0.15);
  check('early: elapsed 0.10 -> early regardless of a huge over ratio (3.0)', mk(0.30, 0.10) === 'early');
  check('early: elapsed 0.10 -> early regardless of a deep under ratio (0.5)', mk(0.05, 0.10) === 'early');
  check('early: elapsed 0.10 with NO spend data -> still early', mk(null, 0.10) === 'early');
  check('early: elapsed 0 (pre-flight/day one) -> early, not none', mk(0, 0) === 'early');
  check('early: elapsed 0.20 evaluates normally (ratio 0.5 -> under)', mk(0.10, 0.20) === 'under');
  check('early: elapsed 0.20 evaluates normally (ratio 1.0 -> ok)', mk(0.20, 0.20) === 'ok');
  check('early: boundary elapsed exactly 0.15 is JUDGED (rule is <, not <=)', mk(0.075, 0.15) === 'under');
  // pacingStatus twin: 10% through a 100-day flight -> 'Early' (not '-'/'Under')
  const cEarly = { startDate: '2026-07-01', endDate: '2026-10-09', totalBudget: 10000, clientSpend: 200 };
  const dE = C.computeRow(cEarly, new Date('2026-07-11T00:00:00'));   // 10/100 days elapsed
  check('computeRow at 10% elapsed: pacingStatus Early + paceBucket early', dE.pacingStatus === 'Early' && dE.paceBucket === 'early',
    dE.pacingStatus + '/' + dE.paceBucket + ' elapsed=' + dE.pctFlightElapsed);
  const dL = C.computeRow(cEarly, new Date('2026-08-10T00:00:00'));   // 40% elapsed, 2% spent -> judged
  check('computeRow at 40% elapsed: judged normally (Under)', dL.pacingStatus === 'Under' && dL.paceBucket === 'under');
}

// ---- effectiveBudget base: budgetGross wins over totalBudget in projections ----
{
  const c = Object.assign({}, BASE, { channel: 'Google Ads', budgetGross: 30000 }); // gross < total
  const d = C.computeRow(c, ASOF);   // projTotal 30,000 vs gross 30,000 -> on plan
  check('projection uses effectiveBudget (budgetGross-first)', d.projState === 'onplan', d.projState + ' projVar=' + d.projVar);
}

// ---- latestSyncAsOf: newest lastSyncedAt wins; null when never synced ----
{
  const rows = [{ lastSyncedAt: '2026-07-10T02:00:00Z' }, { lastSyncedAt: '2026-07-12T02:00:00Z' }, {}];
  const asOf = C.latestSyncAsOf(rows);
  check('latestSyncAsOf picks the max', asOf && asOf.toISOString().slice(0, 10) === '2026-07-12');
  check('latestSyncAsOf null when no row ever synced', C.latestSyncAsOf([{}, { lastSyncedAt: null }]) === null);
}

console.log('\n' + pass + ' passed, ' + fail + ' failed.');
process.exit(fail ? 1 : 0);
