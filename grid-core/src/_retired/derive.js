/**
 * ============================ QUARANTINED — PHASE 1 ============================
 * derive.js is RETIRED. The single formula engine is src/central/calc.js:
 * every formula here was either already in calc.js or was ported there in Phase 1
 * (see PHASE1_REPORT.md for the reconciliation table). NOTHING may import this
 * file. It is kept only as the audit reference for the old sheet formulas until
 * Phase 4 deletes it.
 * ===============================================================================
 *
 * derive.js — the single source of truth for The Grid's calculated fields. (STALE CLAIM — see above)
 *
 * Every formula here is transcribed directly from the "Live Campaigns" sheet
 * in CENTRAL_100__Digital.xlsx. Column letters from the sheet are noted so you
 * can audit each one against the original. Both the live app and the probe's
 * reconciliation harness import THIS file, so the dashboard and the spreadsheet
 * can never disagree because someone reimplemented the math slightly differently.
 *
 * IMPORTANT — the sheet contains manual "fudge factor" hacks in a handful of
 * cells (e.g. R7 = S7*2, N7 = 20*2, V7 = U7*2, T7 = 2*850859). Those exist only
 * because a flight was half-recorded by hand. When data comes from the APIs the
 * true full numbers arrive on their own, so those *2 patches are DELIBERATELY
 * NOT reproduced here. Reproducing them would double-count. See NOTES at bottom.
 *
 * No dependencies. Runs in Node and in the browser.
 */

'use strict';

const DAY_MS = 86400000;

/* ------------------------------------------------------------------ *
 * Raw input shape (what every connector's fetchReport() must return)
 * ------------------------------------------------------------------ *
 *   {
 *     agency, advertiser, jobNumber, campaign, objective, channel,
 *     managedBy, status,
 *     start, end,                 // ISO date strings 'YYYY-MM-DD' or Date
 *     platformMargin,             // K — MANUAL input (agreed % with client), 0..1 or null
 *     adServingRate,              // L "Ad-Serving " — CPM rate for ad serving, e.g. 5 ($ per 1000 impr)
 *     forecastCPM,                // N — planned/forecast CPM (manual/plan), nullable
 *     keyKPI, kpiPerf,            // P, Q — text KPI + performance (mostly manual/plan)
 *     budgetGross,                // R — usually equals totalBudget; nullable
 *     totalBudget,                // S — client budget for the flight ($)
 *     impressions,                // T — impressions to date (from platform)
 *     mediaSpend,                 // U — partner/media spend to date (raw platform cost)
 *     clientSpent,                // V — client spend to date (what we bill client)
 *     campaignLink, nextReport, notes,   // AA, AB, AC — passthrough
 *     // provenance (set by orchestrator, not the sheet):
 *     sourceKey, sourceLabel, sourceApi, syncMode, syncedAt,
 *   }
 *
 * Note on U vs V: on many rows the sheet has clientSpent (V) already grossed up
 * from mediaSpend (U) by the platform margin. Connectors should return BOTH the
 * raw platform cost (mediaSpend/U) and, where the client is billed on a margin,
 * the client-facing figure (clientSpent/V). If a connector only knows raw cost,
 * see grossUpClientSpend() below to derive V from U and the platform margin.
 * ------------------------------------------------------------------ */

function toDate(v) {
  if (v == null || v === '') return null;
  if (v instanceof Date) return v;
  const d = new Date(v);
  return isNaN(d) ? null : d;
}

function num(v) {
  if (v == null || v === '' || v === '-') return null;
  const n = typeof v === 'number' ? v : Number(String(v).replace(/[$,\s]/g, ''));
  return isNaN(n) ? null : n;
}

/**
 * Optional helper: when a connector only has raw media/partner spend (U) and the
 * client is billed cost + margin, gross up to client spend (V).
 *   platformMargin is the fraction retained, so V = U / (1 - margin).
 * If margin is null/0, client spend equals media spend (pass-through billing).
 */
function grossUpClientSpend(mediaSpend, platformMargin) {
  const u = num(mediaSpend);
  if (u == null) return null;
  const m = num(platformMargin);
  if (m == null || m <= 0) return u;
  if (m >= 1) return null; // 100% margin is nonsensical for a divisor
  return u / (1 - m);
}

/* ------------------------------------------------------------------ *
 * The sheet formulas, one function each. Column refs in comments.
 * ------------------------------------------------------------------ */

// M — Adserving cost = T/1000 * L   (impressions in thousands × ad-serving CPM)
function adservingCost({ impressions, adServingRate }) {
  const t = num(impressions), l = num(adServingRate);
  if (t == null || l == null) return null;
  return (t / 1000) * l;
}

// J — Campaign Margin = (V - U - M) / V
//     (client spend − media/partner spend − ad-serving cost) ÷ client spend
function campaignMargin({ clientSpent, mediaSpend, adservingCost: mCost }) {
  const v = num(clientSpent), u = num(mediaSpend), m = num(mCost) ?? 0;
  if (v == null || u == null || v === 0) return null;
  return (v - u - m) / v;
}

// O — CPM Performance = (V / T) * 1000   (actual client CPM to date)
function cpmPerformance({ clientSpent, impressions }) {
  const v = num(clientSpent), t = num(impressions);
  if (v == null || t == null || t === 0) return null;
  return (v / t) * 1000;
}

// R — Budget Gross = S   (defaults to total budget; connectors may override)
function budgetGross({ budgetGross: r, totalBudget }) {
  const explicit = num(r);
  if (explicit != null) return explicit;
  return num(totalBudget);
}

// W — Budget Remaining = S - V
function budgetRemaining({ totalBudget, clientSpent }) {
  const s = num(totalBudget), v = num(clientSpent);
  if (s == null || v == null) return null;
  return s - v;
}

// X — % Budget Spent = V / S
function pctSpent({ clientSpent, totalBudget }) {
  const v = num(clientSpent), s = num(totalBudget);
  if (v == null || s == null || s === 0) return null;
  return v / s;
}

// Y — % Flight Elapsed = MIN((today - H)/(I - H), 1)
//     `asOf` lets the reconciliation harness pin a snapshot date; defaults to now.
function pctElapsed({ start, end }, asOf) {
  const h = toDate(start), i = toDate(end);
  if (!h || !i) return null;
  const today = asOf ? toDate(asOf) : new Date();
  const span = i - h;
  if (span <= 0) return null;
  return Math.min((today - h) / span, 1);
}

// Z — Pacing Status = IF(OR(X="-",Y="-",X=0),"-", X/Y)
//     A RATIO, not a band. >1 = overpacing, <1 = underpacing, ~1 = on pace.
function pacingRatio(x, y) {
  if (x == null || y == null || x === 0) return null;
  if (y === 0) return null;
  return x / y;
}

/* ------------------------------------------------------------------ *
 * Interpretive layer (not in the sheet, used by the dashboard)
 * ------------------------------------------------------------------ */

// Turn the pacing ratio into a state label, with a tolerance band.
function paceState(ratio, band = 0.10) {
  if (ratio == null) return 'none';
  if (ratio > 1 + band) return 'over';
  if (ratio < 1 - band) return 'under';
  return 'ok';
}

// Revenue at stake: the client-$ implied by the pacing gap, weighted by margin.
// Used to rank the meeting queue. Only off-pace campaigns carry stake.
const ASSUMED_MARGIN = 0.60;
function revenueAtStake({ pctSpent, pctElapsed, totalBudget, campaignMargin: cm, paceState: ps }) {
  if (ps === 'ok' || ps === 'none') return 0;
  const s = num(totalBudget);
  if (s == null || pctSpent == null || pctElapsed == null) return 0;
  const gapFraction = Math.abs(pctSpent - pctElapsed);
  const gapDollars = gapFraction * s;
  const m = (cm != null) ? Math.max(0, Math.min(1, cm)) : ASSUMED_MARGIN;
  return gapDollars * m;
}

/* ------------------------------------------------------------------ *
 * derive(raw, opts) — run the full chain in dependency order.
 * Returns a NEW object: all raw fields + every computed field.
 * ------------------------------------------------------------------ */
function derive(raw, opts = {}) {
  const asOf = opts.asOf || null;
  const band = opts.paceBand != null ? opts.paceBand : 0.10;

  const out = { ...raw };

  // normalize numerics we depend on
  out.totalBudget = num(raw.totalBudget);
  out.mediaSpend  = num(raw.mediaSpend);
  out.clientSpent = num(raw.clientSpent);
  out.impressions = num(raw.impressions);
  out.platformMargin = num(raw.platformMargin);

  // If clientSpent missing but we can gross up from mediaSpend + margin, do it.
  if (out.clientSpent == null && out.mediaSpend != null) {
    out.clientSpent = grossUpClientSpend(out.mediaSpend, out.platformMargin);
  }

  out.adservingCost   = adservingCost(out);                 // M
  out.campaignMargin  = campaignMargin(out);                // J
  out.cpmPerf         = cpmPerformance(out);                // O
  out.budgetGross     = budgetGross(out);                   // R
  out.budgetRemaining = budgetRemaining(out);               // W
  out.pctSpent        = pctSpent(out);                      // X
  out.pctElapsed      = pctElapsed(out, asOf);              // Y
  out.pacingStatus    = pacingRatio(out.pctSpent, out.pctElapsed); // Z (ratio)

  // interpretive
  out.paceState    = paceState(out.pacingStatus, band);
  out.marginAtRisk = revenueAtStake(out);
  out.atStake      = out.marginAtRisk;

  return out;
}

/* ------------------------------------------------------------------ *
 * NOTES / audit trail
 * ------------------------------------------------------------------ *
 * Sheet formula -> function mapping (verified against the .xlsx):
 *   J  Campaign Margin  = (V-U-M)/V          -> campaignMargin()
 *   M  Adserving cost   = T/1000*L           -> adservingCost()
 *   O  CPM Performance  = (V/T)*1000         -> cpmPerformance()
 *   R  Budget Gross     = S                  -> budgetGross()
 *   W  Budget Remaining = S-V                -> budgetRemaining()
 *   X  % Budget Spent   = V/S                -> pctSpent()
 *   Y  % Flight Elapsed = MIN((today-H)/(I-H),1) -> pctElapsed()
 *   Z  Pacing Status    = IF(...,"-",X/Y)    -> pacingRatio()
 *   K  Platform Margin  = MANUAL INPUT (no formula) — passthrough, not derived
 *   N  Forecast CPM     = plan input (some rows hardcoded *2) — passthrough
 *   Q  KPI Performance  = mostly manual/plan — passthrough
 *
 * Deliberately DROPPED manual hacks (do not reintroduce):
 *   R7=S7*2, N7=20*2, O7=2*10.69, Q7=2*52.29, T7=2*850859, V7=U7*2,
 *   and the "/2" totalBudget splits. APIs return true full-flight numbers.
 * ------------------------------------------------------------------ */

const api = {
  derive,
  // individual formulas exposed for targeted reconciliation tests
  adservingCost, campaignMargin, cpmPerformance, budgetGross,
  budgetRemaining, pctSpent, pctElapsed, pacingRatio, paceState,
  revenueAtStake, grossUpClientSpend, num, toDate,
  DAY_MS, ASSUMED_MARGIN,
};

// dual export: CommonJS (Node/probe) + ESM/browser
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.GridDerive = api;
