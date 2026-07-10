/**
 * src/central/calc.js — Central tab: the SINGLE SOURCE OF TRUTH for every derived
 * campaign field. Pure functions, no DOM, no fetching. Mirrors the pattern of
 * src/derive.js (dependency-free, runs in Node + the browser) so the app and any
 * reconciliation harness compute the numbers exactly one way.
 *
 * The whole point of the Central tab is that these formulas live HERE, never
 * inlined in the view. Every division is guarded: a 0 / null / missing / non-finite
 * denominator returns null, and the view renders null as "—". No NaN or Infinity
 * may ever reach the UI. This is the explicit fix for the divide-by-zero and
 * hardcoded-margin bugs in the old central.xlsx "Live Campaigns" sheet.
 *
 * Field ORIGIN tags (drive later automation — see the Campaign typedef):
 *   [API]     pulled from platform APIs (Trade Desk / LinkedIn / Windsor)
 *   [CONFIG]  from the launchpad / media-plan (manual or synced)
 *   [DERIVED] computed here from other fields, NEVER user-editable
 */

'use strict';

/**
 * @typedef {'Active'|'Paused'|'Not Active'|'Ended'|'Draft'} CampaignStatus
 *   Active/Paused/Not Active/Ended come from the sheet verbatim ("Not Active" is a real
 *   sheet status, never coerced). Draft is app-only: newly created thin rows + blank import.
 * @typedef {'On'|'Over'|'Under'|'-'} PacingStatus
 *
 * The raw campaign shape the Central table renders. DERIVED fields are NOT stored
 * on the raw row — they are produced by computeRow() below. Origin tag per field:
 *
 * @typedef {Object} Campaign
 * @property {string}  agency            grouping section: "100% Digital" | "Transmission"   [CONFIG]
 * @property {string}  client            client group within the section                     [CONFIG]
 * @property {string}  [currency]        ISO-ish code for money formatting (AUD|USD|…)        [CONFIG]
 * @property {string}  jobNumber         Job Number                                           [CONFIG]
 * @property {string}  name              Campaign                                             [CONFIG]
 * @property {string}  objective         Objective                                            [CONFIG]
 * @property {string}  channel           Channel                                              [CONFIG]
 * @property {string}  managedBy         Managed By                                           [CONFIG]
 * @property {CampaignStatus} status     Status                                               [CONFIG]
 * @property {string}  startDate         Start Date (ISO 'YYYY-MM-DD')                        [CONFIG]
 * @property {string}  endDate           End Date   (ISO 'YYYY-MM-DD')                         [CONFIG]
 * @property {number}  [platformMargin]  Platform Margin (0..1)                               [CONFIG]
 * @property {string}  [adServing]       Ad-Serving                                           [CONFIG]
 * @property {number}  [adServingCost]   Adserving Cost                                       [CONFIG]
 * @property {number}  [forecastCpm]     Forecast CPM                                         [CONFIG]
 * @property {string}  [keyKpi]          Key KPI                                              [CONFIG]
 * @property {string}  [kpiPerformance]  KPI Performance (formula TBD — passthrough for now)  [DERIVED]
 * @property {number}  [budgetGross]     Budget Gross                                         [CONFIG]
 * @property {number}  [totalBudget]     Total Budget                                         [CONFIG]
 * @property {number}  [impressions]     Impressions to Date                                  [API]
 * @property {number}  [mediaSpend]      Media Spend to Date (partner spend in TTD)           [API]
 * @property {number}  [clientSpend]     Client Spend to Date                                 [API]
 * @property {string}  [campaignLink]    Campaign Link (url)                                  [CONFIG]
 * @property {string}  [nextReportingDue] Next Reporting Due (ISO date)                       [CONFIG]
 * @property {string}  [notes]           Links / Notes                                        [CONFIG]
 *
 * @typedef {Object} DerivedFields
 * @property {number|null} campaignMargin    (clientSpend - mediaSpend - adServingCost) / clientSpend
 * @property {number|null} cpmPerformance    (clientSpend / impressions) * 1000
 * @property {string|null} kpiPerformance    passthrough until a formula is defined
 * @property {number|null} budgetRemaining   totalBudget - clientSpend
 * @property {number|null} pctBudgetSpent    clientSpend / totalBudget
 * @property {number|null} pctFlightElapsed  clamp((today - start) / (end - start), 0..1)
 * @property {PacingStatus} pacingStatus     pctBudgetSpent / pctFlightElapsed banded
 * @property {number|null} marginDelta       campaignMargin - platformMargin                       [DERIVED]
 * @property {'above'|'near'|'below'|null} marginBand   banded marginDelta (>=0 above; >=-0.10 near; else below; cm<0 below)  [DERIVED]
 * @property {'winner'|'watch'|'steady'|null} health    portfolio-health bucket from margin + pacing + CPM  [DERIVED]
 */

const DAY_MS = 86400000;

/* ---- guarded primitives: the ONLY place division / date math happens ---- */

/** Finite number or null (treats null/undefined/''/NaN/Infinity as missing). */
function num(x) {
  if (x === null || x === undefined || x === '') return null;
  const n = typeof x === 'number' ? x : Number(x);
  return Number.isFinite(n) ? n : null;
}

/** a / b, or null when the result can't be a finite number (guards divide-by-zero). */
function div(a, b) {
  const x = num(a), y = num(b);
  if (x === null || y === null || y === 0) return null;
  const r = x / y;
  return Number.isFinite(r) ? r : null;
}

/** Parse an ISO date (or Date) to epoch ms, or null. */
function ms(d) {
  if (!d) return null;
  const t = d instanceof Date ? d.getTime() : Date.parse(d);
  return Number.isFinite(t) ? t : null;
}

/* ---- derived fields (each a pure function of a Campaign) ---- */

/** Budget Remaining = Total Budget - Client Spend. Null if either is missing. */
function budgetRemaining(c) {
  const tb = num(c.totalBudget), cs = num(c.clientSpend);
  if (tb === null || cs === null) return null;
  return tb - cs;
}

/** % Budget Spent = Client Spend / Total Budget (0..1). */
function pctBudgetSpent(c) {
  return div(c.clientSpend, c.totalBudget);
}

/** % Flight Elapsed = clamp((today - start) / (end - start), 0..1). */
function pctFlightElapsed(c, today = new Date()) {
  const s = ms(c.startDate), e = ms(c.endDate), t = ms(today);
  if (s === null || e === null || t === null || e <= s) return null;
  const r = (t - s) / (e - s);
  if (!Number.isFinite(r)) return null;
  return Math.max(0, Math.min(r, 1));
}

/** Campaign Margin = (clientSpend - mediaSpend - adServingCost) / clientSpend. */
function campaignMargin(c) {
  const cs = num(c.clientSpend), md = num(c.mediaSpend), as = num(c.adServingCost);
  if (cs === null || cs === 0 || md === null || as === null) return null;
  return (cs - md - as) / cs;
}

/** CPM Performance = (clientSpend / impressions) * 1000. */
function cpmPerformance(c) {
  const r = div(c.clientSpend, c.impressions);
  return r === null ? null : r * 1000;
}

/**
 * KPI Performance — marked [DERIVED] but no formula is defined yet (it depends on
 * the campaign's Key KPI). Passthrough of any provided value for now.
 * TODO: implement per-objective KPI computation once the rule is specified.
 */
function kpiPerformance(c) {
  return c.kpiPerformance === undefined || c.kpiPerformance === '' ? null : c.kpiPerformance;
}

/**
 * Pacing Status from ratio = pctBudgetSpent / pctFlightElapsed:
 *   > 1.05 -> "Over", < 0.95 -> "Under", else "On". "-" when it can't be computed.
 */
function pacingStatus(c, today = new Date()) {
  const spent = pctBudgetSpent(c), elapsed = pctFlightElapsed(c, today);
  const ratio = div(spent, elapsed);
  if (ratio === null) return '-';
  if (ratio > 1.05) return 'Over';
  if (ratio < 0.95) return 'Under';
  return 'On';
}

/* ---- margin banding + portfolio health (ADDED; do not touch the formulas above) ---- */

/**
 * Margin Delta = campaignMargin - platformMargin. Null when either is missing.
 * @param {Campaign} c
 * @param {DerivedFields} [d] pre-computed core fields (avoids recomputing campaignMargin)
 */
function marginDelta(c, d) {
  const cm = d ? d.campaignMargin : campaignMargin(c);
  const pm = num(c.platformMargin);
  if (cm === null || pm === null) return null;
  return cm - pm;
}

/**
 * Margin Band from the realized-vs-set gap:
 *   'above'  marginDelta >= 0
 *   'near'   -0.10 <= marginDelta < 0
 *   'below'  marginDelta < -0.10  OR  campaignMargin < 0
 *   null     platformMargin missing (nothing to compare against) or margin unknowable
 */
function marginBand(c, d) {
  const pm = num(c.platformMargin);
  if (pm === null) return null;                       // no set margin to compare against
  const cm = d ? d.campaignMargin : campaignMargin(c);
  if (cm === null) return null;                       // can't judge without a realized margin
  if (cm < 0) return 'below';                          // losing money is always 'below'
  const delta = cm - pm;
  if (delta >= 0) return 'above';
  if (delta >= -0.10) return 'near';
  return 'below';
}

/**
 * Health bucket. WATCH is evaluated BEFORE WINNER on purpose: an anomalously
 * cheap CPM (< 0.5x forecast) is a targeting red flag (the "EBA $1.42" detector),
 * so it must win over an otherwise-green margin/pacing row.
 *   'winner' marginBand 'above' AND pacing 'On' AND (cpm <= forecastCpm when both present)
 *   'watch'  marginBand 'below' OR campaignMargin<0 OR pacing 'Over'
 *            OR (pacing 'Under' AND pctFlightElapsed>0.5)
 *            OR (forecastCpm && cpm > 2*forecastCpm) OR (forecastCpm && cpm < 0.5*forecastCpm)
 *   'steady' otherwise
 *   null     insufficient data to judge (no band, no pacing, no realized margin)
 */
function health(c, d) {
  const band = marginBand(c, d);
  const pacing = d.pacingStatus;                       // 'On'|'Over'|'Under'|'-'
  const cm = d.campaignMargin;
  const cpm = d.cpmPerformance;
  const fcpm = num(c.forecastCpm);
  const elapsed = d.pctFlightElapsed;

  // WATCH first (so the cheap-CPM anomaly overrides a would-be winner)
  if (band === 'below') return 'watch';
  if (cm !== null && cm < 0) return 'watch';
  if (pacing === 'Over') return 'watch';
  if (pacing === 'Under' && elapsed !== null && elapsed > 0.5) return 'watch';
  if (fcpm !== null && cpm !== null && cpm > 2 * fcpm) return 'watch';
  if (fcpm !== null && cpm !== null && cpm < 0.5 * fcpm) return 'watch';

  // WINNER
  if (band === 'above' && pacing === 'On' && (fcpm === null || cpm === null || cpm <= fcpm)) return 'winner';

  // insufficient data → let the UI render "—"
  if (band === null && pacing === '-' && cm === null) return null;

  return 'steady';
}

/**
 * Compute every derived field for a row in one pass.
 * @param {Campaign} c
 * @param {Date} [today]
 * @returns {DerivedFields}
 */
function computeRow(c, today = new Date()) {
  const d = {
    campaignMargin: campaignMargin(c),
    cpmPerformance: cpmPerformance(c),
    kpiPerformance: kpiPerformance(c),
    budgetRemaining: budgetRemaining(c),
    pctBudgetSpent: pctBudgetSpent(c),
    pctFlightElapsed: pctFlightElapsed(c, today),
    pacingStatus: pacingStatus(c, today),
  };
  d.marginDelta = marginDelta(c, d);
  d.marginBand = marginBand(c, d);
  d.health = health(c, d);
  return d;
}

const api = {
  num, div, ms,
  budgetRemaining, pctBudgetSpent, pctFlightElapsed,
  campaignMargin, cpmPerformance, kpiPerformance, pacingStatus,
  marginDelta, marginBand, health,
  computeRow,
};

// dual export: CommonJS (Node / tests) + browser global (classic <script src>)
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.CentralCalc = api;
