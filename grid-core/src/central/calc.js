/**
 * src/central/calc.js — THE single formula engine for The Grid (Phase 1: Pulse,
 * Register AND Central all compute through this file; the old src/derive.js is
 * quarantined in src/_retired/). Pure functions, no DOM, no fetching —
 * dependency-free, runs in Node + the browser — so the app and any
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

// IIFE: in the browser this file loads as a CLASSIC script, so top-level const/let
// would land in the page's shared global lexical scope and collide with the app's
// own declarations (ASSUMED_MARGIN did exactly that in Phase 1). Only the two
// exports at the bottom may escape.
(function () {

/**
 * @typedef {'Active'|'Paused'|'Not Active'|'Ended'|'Draft'} CampaignStatus
 *   Active/Paused/Not Active/Ended come from the sheet verbatim ("Not Active" is a real
 *   sheet status, never coerced). Draft is app-only: newly created thin rows + blank import.
 * @typedef {'On'|'Over'|'Under'|'Early'|'-'} PacingStatus
 *   'Early' = flight <15% elapsed — the ratio is noise at that point, so pacing is
 *   deliberately NOT judged (see PACE_EARLY_FLIGHT_THRESHOLD).
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
 *
 * Phase-1 additions (the Pulse fields, ported from the legacy inline engine in
 * the-grid.html + the per-channel margin rule) — all [DERIVED]:
 * @property {'ok'|'over'|'under'|'none'} paceBucket   lowercase twin of pacingStatus (same ratio bands)
 * @property {number|null} daysTotal        rounded flight length in days
 * @property {number|null} daysElapsed      rounded days from start to asOf
 * @property {number|null} daysLeft         rounded days from asOf to end
 * @property {number|null} runRate          clientSpend / daysElapsed ($ per day, to date)
 * @property {number|null} reqDaily         budgetRemaining / daysLeft ("needs $X/day")
 * @property {number|null} projTotal        runRate * daysTotal (projected full-flight client spend)
 * @property {number|null} projVar          projTotal - effectiveBudget (+over / -under)
 * @property {'over'|'under'|'onplan'|'none'} projState  projVar banded at ±PROJ_BAND of budget
 * @property {number|null} effectiveMargin  THE MONEY RULE — see effectiveMargin() below
 * @property {'platform'|'campaign'|'assumed'|null} effectiveMarginSource  where the value came from
 * @property {'platform'|'campaign'} effectiveMarginRule  which margin this CHANNEL should use
 * @property {string|null} marginWarning    'platform-margin-missing' = loud degrade (TTD/DV360 without a set margin)
 * @property {number|null} profitAtRisk     projected shortfall × effectiveMargin (under-pacing only)
 * @property {number|null} atStake          profitAtRisk when under, overrun $ when over (queue sort key)
 * @property {string|null} pacingAction     plain-English recommendation ("Lift daily spend", …)
 * @property {'over'|'under'|'warn'|'ok'|'none'} pacingActionColor  severity bucket for pacingAction
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

/** Effective budget = Budget Gross (the client-billed budget) where present, else Total
 * Budget. Budget tracking is on the client-spend basis, so it must use the client budget;
 * some rows carry the media budget in Total Budget and the client budget in Budget Gross. */
function effectiveBudget(c) { const g = num(c.budgetGross); return g !== null ? g : num(c.totalBudget); }

/** Budget Remaining = effectiveBudget - Client Spend. Null if either is missing. */
function budgetRemaining(c) {
  const b = effectiveBudget(c), cs = num(c.clientSpend);
  if (b === null || cs === null) return null;
  return b - cs;
}

/** % Budget Spent = Client Spend / effectiveBudget (0..1). */
function pctBudgetSpent(c) {
  return div(c.clientSpend, effectiveBudget(c));
}

/** % Flight Elapsed = clamp((today - start) / (end - start), 0..1). */
function pctFlightElapsed(c, today = new Date()) {
  const s = ms(c.startDate), e = ms(c.endDate), t = ms(today);
  if (s === null || e === null || t === null || e <= s) return null;
  const r = (t - s) / (e - s);
  if (!Number.isFinite(r)) return null;
  return Math.max(0, Math.min(r, 1));
}

/** Ad-serving cost = impressions/1000 * ad-serving RATE (c.adServing, e.g. $5 CPM). 0 when
 * there is no rate or no impressions. DERIVED — the sheet's Adserving-Cost column is discarded. */
function adServingCost(c) {
  const rate = num(c.adServing), imp = num(c.impressions);
  if (rate === null || rate === 0 || imp === null || imp === 0) return 0;
  return (imp / 1000) * rate;
}

/** Campaign Margin = (clientSpend - mediaSpend - adServingCost) / clientSpend. Uses the DERIVED
 * ad-serving cost. Null (—) when clientSpend is 0/missing or mediaSpend is missing. */
function campaignMargin(c) {
  const cs = num(c.clientSpend), md = num(c.mediaSpend);
  if (cs === null || cs === 0 || md === null) return null;
  return (cs - md - adServingCost(c)) / cs;
}

/** CPM Performance = (mediaSpend / impressions) * 1000 — the media-buyer's CPM (cost per 1000
 * impressions we actually pay), on the SAME basis as Forecast CPM. NOT client-spend based. */
function cpmPerformance(c) {
  const r = div(c.mediaSpend, c.impressions);
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

// THE pacing tolerance band — the ONE constant behind pacingStatus, paceBucket, the
// Pulse scatter wedge and the Off-budget KPI count. Widened 0.95/1.05 -> 0.90/1.10
// (2026-07-22 planning decision, post-Phase-1) to cut over-flagging: a campaign within
// ±10% of its ideal spend ratio is "on pace".
const PACE_BAND_OVER = 1.10;
const PACE_BAND_UNDER = 0.90;

// Early-flight suppression (2026-07-22 micro-patch): below this % of flight elapsed the
// pacing ratio is noise, not signal (10% elapsed / 5% spent is a divide-by-almost-zero,
// not a "too slow" campaign). pacingStatus/paceBucket return the dedicated 'Early'/'early'
// state instead of judging — the attention queue, the Off-budget KPI and the scatter's
// warning colours all exclude it.
const PACE_EARLY_FLIGHT_THRESHOLD = 0.15;

/**
 * Pacing Status from ratio = pctBudgetSpent / pctFlightElapsed:
 *   flight < PACE_EARLY_FLIGHT_THRESHOLD elapsed -> "Early" (not judged);
 *   > PACE_BAND_OVER -> "Over", < PACE_BAND_UNDER -> "Under", else "On".
 *   "-" when it can't be computed.
 */
function pacingStatus(c, today = new Date()) {
  const spent = pctBudgetSpent(c), elapsed = pctFlightElapsed(c, today);
  if (elapsed !== null && elapsed < PACE_EARLY_FLIGHT_THRESHOLD) return 'Early';
  const ratio = div(spent, elapsed);
  if (ratio === null) return '-';
  if (ratio > PACE_BAND_OVER) return 'Over';
  if (ratio < PACE_BAND_UNDER) return 'Under';
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

// Cheap-CPM anomaly ("EBA $1.42 vs $28" detector). Spec named forecastCpm × 0.3 (>70% below),
// but the media plans here carry inflated forecast CPMs ($28-$40) while real Trade Desk display
// CPMs run $2-$12 — so sub-forecast CPMs are NORMAL and × 0.3 would re-flag healthy rows
// (Geocon at 29% of forecast = expected winner; ResetData/TD at 12% = expected steady) as watch,
// recreating the over-flagging this change fixes. We fire only at × 0.1 (>90% below forecast):
// still catches the genuine "$1.42 vs $28" (~5%) case, spares normal cheap display.
var ANOMALY_CPM_RATIO = 0.1;

/**
 * Health bucket — LENIENT: never grade a campaign we can't measure, and flag "watch" only when
 * something is genuinely wrong. Order: insufficient-data gate → watch → winner → steady.
 *   null      insufficient data (no impressions / no media spend / no client spend / no budget)
 *   'watch'   negative margin, big over/under-spend, near-out-of-budget-early, or anomalously
 *             cheap CPM (< 10% of forecast)
 *   'winner'  positive margin AND cpm < forecast AND pacing 0.7-1.3
 *   'steady'  has data, nothing wrong, not a standout (the normal state)
 */
function health(c, d) {
  // Step 1 — insufficient-data gate (do not grade what we can't measure).
  const imp = num(c.impressions), md = num(c.mediaSpend), cs = num(c.clientSpend);
  const bud = effectiveBudget(c);
  if (imp === null || imp === 0) return null;
  if (md === null || md === 0) return null;
  if (cs === null || cs === 0) return null;
  if (bud === null || bud === 0) return null;

  const margin = d.campaignMargin;
  const cpm = d.cpmPerformance;
  const fcpm = num(c.forecastCpm);
  const elapsed = d.pctFlightElapsed;
  const spent = d.pctBudgetSpent;
  const pacing = div(spent, elapsed);                  // numeric pace ratio (null if not computable)

  // cheap-CPM anomaly — watch regardless of other metrics (see note above).
  if (fcpm !== null && fcpm > 0 && cpm !== null && cpm < fcpm * ANOMALY_CPM_RATIO) return 'watch';

  // Step 2 — watch (something specific is wrong).
  if (margin !== null && margin < 0) return 'watch';                                  // losing money
  if (pacing !== null && pacing > 1.4) return 'watch';                                // overspending 40%+
  if (pacing !== null && pacing < 0.5 && elapsed !== null && elapsed > 0.3) return 'watch';  // severely underspending, not just early
  if (spent !== null && spent > 0.95 && elapsed !== null && elapsed < 0.7) return 'watch';   // nearly out of budget with flight left

  // Step 3 — winner (beating expectations).
  if (margin !== null && margin > 0 && fcpm !== null && cpm !== null && cpm < fcpm &&
    pacing !== null && pacing >= 0.7 && pacing <= 1.3) return 'winner';

  // Step 4 — steady (default for anything that has data and isn't watch/winner).
  return 'steady';
}

/* ==================== Phase 1: the per-channel MARGIN RULE ==================== */

/**
 * THE MONEY RULE (playbook standing rule, encoded here for the first time):
 *   TradeDesk + DV360  -> Platform Margin (the set/billed margin on grossed-up media)
 *   Google Ads, Meta, LinkedIn, Reddit, and ANY channel without a platform-margin
 *   concept -> Campaign Margin (the realized margin derived from actuals).
 * Profit-at-risk / margin-at-risk always multiply against the channel's EFFECTIVE
 * margin — never one blended formula. Ad-serving cost stays its own line (it is
 * already inside campaignMargin via adServingCost()).
 */
const PLATFORM_MARGIN_CHANNELS = /trade\s*desk|tradedesk|\bttd\b|dv\s*-?\s*360|display\s*&?\s*video\s*360/i;

/** Which margin a channel SHOULD use: 'platform' (TTD/DV360) or 'campaign' (everything else). */
function marginRuleFor(channel) {
  return PLATFORM_MARGIN_CHANNELS.test(String(channel || '')) ? 'platform' : 'campaign';
}

// Fallback used when NO usable margin exists on the row (matches the legacy Pulse
// engine's assumption; always flagged, never silent).
const ASSUMED_MARGIN = 0.60;
// A realized campaignMargin at/below this is treated as "unknown" for use as a
// profit multiplier (the sheet writes 0 as filler; a ~0/negative multiplier would
// print a meaningless $0 profit-at-risk). Legacy Pulse used the same guard.
const MARGIN_MIN = 0.001;

/**
 * effectiveMargin(c, d?) -> { value, source, rule, warning }
 *   rule    'platform' | 'campaign'          — what the channel should use
 *   source  'platform' | 'campaign' | 'assumed' — where the value actually came from
 *   value   number|null                      — the margin to multiply against
 *   warning 'platform-margin-missing' | null — LOUD degrade marker
 *
 * DOCUMENTED DEGRADE BEHAVIOR (deliberate, not silent):
 *  - Platform-margin channel (TTD/DV360) with platformMargin missing/0/>=1:
 *    falls back to the realized campaignMargin when usable, else ASSUMED_MARGIN —
 *    and ALWAYS sets warning='platform-margin-missing' so the UI must render an
 *    estimated treatment (~value + "set margin" nudge). platformMargin=0 counts as
 *    missing: the sheet uses 0 as filler and a ×0 multiplier would silently zero
 *    profit-at-risk, which is exactly the failure mode this rule exists to prevent.
 *  - Campaign-margin channel with no usable realized margin: ASSUMED_MARGIN with
 *    source='assumed' (the legacy "est." chip behavior, kept).
 */
function effectiveMargin(c, d) {
  const rule = marginRuleFor(c.channel);
  const cm = d ? d.campaignMargin : campaignMargin(c);
  const usableCm = (cm !== null && cm > MARGIN_MIN) ? cm : null;
  if (rule === 'platform') {
    const pm = num(c.platformMargin);
    if (pm !== null && pm > 0 && pm < 1) return { value: pm, source: 'platform', rule, warning: null };
    if (usableCm !== null) return { value: usableCm, source: 'campaign', rule, warning: 'platform-margin-missing' };
    return { value: ASSUMED_MARGIN, source: 'assumed', rule, warning: 'platform-margin-missing' };
  }
  if (usableCm !== null) return { value: usableCm, source: 'campaign', rule, warning: null };
  return { value: ASSUMED_MARGIN, source: 'assumed', rule, warning: null };
}

/* ========== Phase 1: Pulse formulas ported from the legacy inline engine ========== */
/* (the-grid.html derive()/recommend(), retired this phase — calc.js is now the ONE
   complete engine. Bands/bases follow the reconciliation table in PHASE1_REPORT.md.) */

const PROJ_BAND = 0.05;   // projection tolerance: ±5% of budget = "on plan"

/** Lowercase pace bucket on the SAME rules as pacingStatus: 'early' below
 * PACE_EARLY_FLIGHT_THRESHOLD elapsed (ratio not judged), else the
 * PACE_BAND_OVER/UNDER ratio bands. This deliberately replaces the legacy Pulse gap
 * band (|spent-elapsed|>0.15) and derive.js's ±0.10 ratio band, so Pulse and Central
 * can never disagree. */
function paceBucket(pctSpent, pctElapsed) {
  const e = num(pctElapsed);
  if (e !== null && e < PACE_EARLY_FLIGHT_THRESHOLD) return 'early';
  const ratio = div(pctSpent, pctElapsed);
  if (ratio === null) return 'none';
  if (ratio > PACE_BAND_OVER) return 'over';
  if (ratio < PACE_BAND_UNDER) return 'under';
  return 'ok';
}

/** Rounded flight-day counts as of a date. Null-guarded; daysTotal must be > 0. */
function flightDays(c, asOf = new Date()) {
  const s = ms(c.startDate), e = ms(c.endDate), t = ms(asOf);
  if (s === null || e === null || t === null) return { daysTotal: null, daysElapsed: null, daysLeft: null };
  const daysTotal = Math.round((e - s) / DAY_MS);
  if (daysTotal <= 0) return { daysTotal: null, daysElapsed: null, daysLeft: null };
  return { daysTotal, daysElapsed: Math.round((t - s) / DAY_MS), daysLeft: Math.round((e - t) / DAY_MS) };
}

/**
 * Run-rate projection (ported 1:1 from legacy Pulse, budget base switched to
 * effectiveBudget per the reconciliation table):
 *   runRate  = clientSpend / daysElapsed        (needs daysElapsed > 0)
 *   projTotal= runRate * daysTotal
 *   projVar  = projTotal - effectiveBudget      (+ heading over, - heading under)
 *   reqDaily = budgetRemaining / daysLeft       (needs daysLeft > 0)
 *   projState= over/under at ±PROJ_BAND×budget, else onplan; 'none' if unknowable
 */
function pacingProjection(c, asOf = new Date()) {
  const { daysTotal, daysElapsed, daysLeft } = flightDays(c, asOf);
  const out = { daysTotal, daysElapsed, daysLeft, runRate: null, reqDaily: null, projTotal: null, projVar: null, projState: 'none' };
  const budget = effectiveBudget(c), spend = num(c.clientSpend);
  if (daysTotal === null || budget === null || budget === 0) return out;
  if (daysElapsed !== null && daysElapsed > 0 && spend !== null) {
    out.runRate = spend / daysElapsed;
    out.projTotal = out.runRate * daysTotal;
    out.projVar = out.projTotal - budget;
  }
  const rem = budgetRemaining(c);
  if (daysLeft !== null && daysLeft > 0 && rem !== null) out.reqDaily = rem / daysLeft;
  if (out.projVar !== null) {
    const tol = PROJ_BAND * budget;
    out.projState = out.projVar > tol ? 'over' : out.projVar < -tol ? 'under' : 'onplan';
  }
  return out;
}

/**
 * Profit at risk = projected shortfall × EFFECTIVE margin (per-channel rule above).
 * atStake = profitAtRisk when heading under budget, the raw overrun $ when heading
 * over (the "What needs attention" sort key). Both null-guarded.
 * @param {Campaign} c
 * @param {{projVar:number|null}} proj  from pacingProjection()
 * @param {{value:number|null}} em      from effectiveMargin()
 */
function profitAtRisk(c, proj, em) {
  const shortfall = (proj.projVar !== null && proj.projVar < 0) ? -proj.projVar : 0;
  const overrun = (proj.projVar !== null && proj.projVar > 0) ? proj.projVar : 0;
  const risk = (shortfall > 0 && em.value !== null) ? shortfall * em.value : null;
  return { profitAtRisk: risk, atStake: shortfall > 0 ? risk : (overrun > 0 ? overrun : 0) };
}

/** Plain-English pacing recommendation (ported 1:1 from legacy Pulse recommend()). */
function pacingAction(proj) {
  if (proj.daysLeft !== null && proj.daysLeft <= 0) return { action: 'Flight ended', color: 'none' };
  if (proj.projState === 'over') return { action: 'Cap or rebrief', color: 'over' };
  if (proj.reqDaily === null || proj.runRate === null || proj.runRate <= 0) return { action: 'No pace data', color: 'none' };
  const m = proj.reqDaily / proj.runRate;
  if (m > 3) return { action: 'Unreachable — reallocate', color: 'under' };
  if (m > 1.5) return { action: 'Push hard / add room', color: 'under' };
  if (m > 1.1) return { action: 'Lift daily spend', color: 'warn' };
  if (m < 0.8) return { action: 'Ease off — running ahead', color: 'ok' };
  return { action: 'Hold — on pace', color: 'ok' };
}

/** The pacing "as of" moment: the newest lastSyncedAt across rows, or null when no
 * sync has ever run (callers must FALL BACK LOUDLY — visible badge, never a silent
 * stale date). */
function latestSyncAsOf(rows) {
  let best = null;
  (rows || []).forEach(r => {
    const t = ms(r && r.lastSyncedAt);
    if (t !== null && (best === null || t > best)) best = t;
  });
  return best === null ? null : new Date(best);
}

/**
 * Compute every derived field for a row in one pass.
 * @param {Campaign} c
 * @param {Date} [today]
 * @returns {DerivedFields}
 */
function computeRow(c, today = new Date()) {
  const d = {
    adServingCost: adServingCost(c),
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
  // Phase-1 Pulse fields (single engine — see the ported section above)
  d.paceBucket = paceBucket(d.pctBudgetSpent, d.pctFlightElapsed);
  const proj = pacingProjection(c, today);
  d.daysTotal = proj.daysTotal; d.daysElapsed = proj.daysElapsed; d.daysLeft = proj.daysLeft;
  d.runRate = proj.runRate; d.reqDaily = proj.reqDaily;
  d.projTotal = proj.projTotal; d.projVar = proj.projVar; d.projState = proj.projState;
  const em = effectiveMargin(c, d);
  d.effectiveMargin = em.value; d.effectiveMarginSource = em.source;
  d.effectiveMarginRule = em.rule; d.marginWarning = em.warning;
  const risk = profitAtRisk(c, proj, em);
  d.profitAtRisk = risk.profitAtRisk; d.atStake = risk.atStake;
  const act = pacingAction(proj);
  d.pacingAction = act.action; d.pacingActionColor = act.color;
  return d;
}

const api = {
  num, div, ms,
  effectiveBudget, budgetRemaining, pctBudgetSpent, pctFlightElapsed,
  adServingCost, campaignMargin, cpmPerformance, kpiPerformance, pacingStatus,
  marginDelta, marginBand, health,
  // Phase-1 single-engine additions
  marginRuleFor, effectiveMargin, paceBucket, flightDays, pacingProjection,
  profitAtRisk, pacingAction, latestSyncAsOf,
  ASSUMED_MARGIN, PROJ_BAND, PACE_BAND_OVER, PACE_BAND_UNDER, PACE_EARLY_FLIGHT_THRESHOLD,
  computeRow,
};

// dual export: CommonJS (Node / tests) + browser global (classic <script src>)
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.CentralCalc = api;

})();
