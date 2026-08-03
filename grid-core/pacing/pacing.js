'use strict';

/**
 * Pacing engine. Pure function. No I/O, no database, no clock.
 *
 * Every pacing figure the Grid displays must come from here. If a number
 * appears in two places on screen, it was computed once, in this file.
 *
 * Key conventions, decided deliberately:
 *  - Today is never included in any calculation. Platform days are partial
 *    until the account timezone rolls over, and a partial day compared
 *    against a full day of target understates pace. The distortion is
 *    largest when a campaign is newest, which is exactly when you care.
 *  - The schedule denominator runs from planned start to flight end. A late
 *    launch does NOT get a lenient target: the end date has not moved, so
 *    the same money must be spent in fewer days. Required daily goes UP.
 *  - Rate and capacity use delivery days only, because a spend rate over
 *    days with no delivery is meaningless.
 *  - Dead days at launch are their own state. A campaign that never started
 *    is a launch failure with a different owner, not a slow campaign.
 */

const DAY = 86400000;

const DEFAULTS = {
  driftDaysBand: 3,         // primary band: days of budget ahead or behind
  onTrackLow: 0.9,          // pace index band, reported but secondary
  onTrackHigh: 1.1,
  minDeliveryDays: 3,       // no verdict before this many complete delivery days
  minFlightFraction: 0.05,  // and not before this fraction of flight elapsed
  recentWindow: 3,          // complete days used for the recent rate
  peakWindow: 3,            // rolling mean width for peak observed rate
  reachTolerance: 1.15,     // required may exceed the rolling peak by this and stay reachable
  reachToleranceDegraded: 3, // wider, because an average is a weaker ceiling than a peak
  rampMultiple: 2,          // latest day this far above the peak means it is accelerating
  staleDataDays: 3,         // matches the-grid.html's as-of amber badge
  deadDayThreshold: 2       // consecutive zero days from planned start before flagging
};

/**
 * Per-platform facts, derived from verified BigQuery evidence and the
 * Fees & Margins sheet. Never derive one cost figure from another: read the
 * column that is already the basis you need.
 *
 *   billedColumn  which BQ column is the billed (client-facing) figure
 *   marginOfPartner  margin expressed as a fraction OF PARTNER COST
 *                    (the fee card reads "60% of partner cost", so billed is
 *                    partner x 1.6 plus per-impression fees, NOT partner / 0.4)
 *   adServingCpm  per thousand impressions, in the seat's currency
 */
const PLATFORM_RULES = {
  ttd:       { billedColumn: 'COSTS',                   reportsBilled: true,  marginOfPartner: 0.60 },
  linkedin:  { billedColumn: 'COSTS',                   reportsBilled: true,  marginOfPartner: 0 },
  meta:      { billedColumn: 'cost',                    reportsBilled: true,  marginOfPartner: 0 },
  googleads: { billedColumn: 'spend',                   reportsBilled: true,  marginOfPartner: 0 },
  dv360:     { billedColumn: 'REVENUE_ADV_CURRENCY',    reportsBilled: true,  marginOfPartner: 0 },
  reddit:    { billedColumn: 'COSTS',                   reportsBilled: true,  marginOfPartner: 0 }
};

const AD_SERVING_CPM = { transmission: 1.50, '100digital': 0.90 };

function normPlatform(p) {
  return String(p || '').toLowerCase().replace(/[^a-z0-9]/g, '')
    .replace('thetradedesk', 'ttd').replace('tradedesk', 'ttd')
    .replace('googleads', 'googleads').replace('facebook', 'meta');
}

/**
 * Margin comes from the platform, never from a per-row field. Central carries
 * platformMargin = 0.006 on Caltex where 0.6 was meant; a per-row read makes a
 * single typo corrupt one campaign's profit figure by 100x.
 */
function resolveMargin(platform) {
  const r = PLATFORM_RULES[normPlatform(platform)];
  return r ? r.marginOfPartner : 0;
}

const STATES = {
  NOT_LAUNCHED: 'NOT_LAUNCHED',
  TOO_EARLY: 'TOO_EARLY',
  ON_TRACK: 'ON_TRACK',
  TOO_FAST: 'TOO_FAST',
  BEHIND_RECOVERING: 'BEHIND_RECOVERING',
  BEHIND_NOT_RECOVERING: 'BEHIND_NOT_RECOVERING',
  UNREACHABLE: 'UNREACHABLE',
  ENDED: 'ENDED',
  BASIS_UNKNOWN: 'BASIS_UNKNOWN'
};

function toUTC(d) {
  if (d instanceof Date) return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  const [y, m, day] = String(d).slice(0, 10).split('-').map(Number);
  return Date.UTC(y, m - 1, day);
}
const iso = ms => new Date(ms).toISOString().slice(0, 10);
const daysInclusive = (a, b) => Math.floor((b - a) / DAY) + 1;
const round2 = n => Math.round(n * 100) / 100;

function rollingMax(values, width) {
  if (values.length === 0) return null;
  const w = Math.min(width, values.length);
  let best = -Infinity;
  for (let i = 0; i + w <= values.length; i++) {
    let sum = 0;
    for (let j = i; j < i + w; j++) sum += values[j];
    best = Math.max(best, sum / w);
  }
  return best;
}

/**
 * @param {object} input
 * @param {number} input.budget            in the basis given below
 * @param {string} input.budgetBasis       'client' | 'media'
 * @param {string} input.currency
 * @param {string} input.plannedStart      ISO date
 * @param {string} input.flightEnd         ISO date
 * @param {Array}  input.dailySpend        [{ date, amount, partial? }]
 * @param {string} input.asOf              ISO date treated as today, always excluded
 * @param {string} [input.platform]
 * @param {string} [input.level]           'campaign' | 'adset', for display only
 * @param {object} [input.thresholds]      partial override of DEFAULTS
 */
function computePacing(input) {
  const t = Object.assign({}, DEFAULTS, input.thresholds || {});
  const reasons = [];

  const budget = Number(input.budget);
  const start = toUTC(input.plannedStart);
  const end = toUTC(input.flightEnd);
  const asOf = toUTC(input.asOf);

  if (!(budget > 0)) throw new Error('budget must be a positive number');
  if (end < start) throw new Error('flightEnd is before plannedStart');

  // Vocabulary follows plan-reader-v2: media | billed | unknown. 'client' is
  // accepted as a synonym for 'billed' so earlier callers keep working.
  const rawBasis = String(input.spendBasis || input.budgetBasis || '').toLowerCase();
  const basis = rawBasis === 'client' ? 'billed' : rawBasis;
  if (!basis) throw new Error('spendBasis must be "media", "billed" or "unknown"');

  // An unknown basis cannot produce a verdict. plan-reader-v2 R1 requires a
  // human to choose; a guess here silently halves or doubles every figure.
  if (basis === 'unknown') {
    return {
      state: STATES.BASIS_UNKNOWN, budget, spendBasis: 'unknown', degraded: true,
      spent: null, paceIndex: null, driftDays: null, requiredDaily: null,
      reasons: ['spend basis is unknown: a human must choose media or billed before pacing can be judged']
    };
  }

  // ---- complete days only -------------------------------------------------
  const rows = (input.dailySpend || [])
    .map(r => ({ ms: toUTC(r.date), amount: Number(r.amount) || 0, partial: !!r.partial }))
    .filter(r => r.ms >= start && r.ms <= end)
    .sort((a, b) => a.ms - b.ms);

  // Degraded mode. grid-core has no daily series today: central_sync.py collapses
  // the grain with GROUP BY 1 before anything is stored. So the engine must work
  // from a single to-date figure, returning null for everything that genuinely
  // needs the shape of the series rather than inventing it.
  const degraded = rows.length === 0 && input.spentToDate != null;
  if (degraded && !input.lastDataDate) {
    throw new Error('lastDataDate is required with spentToDate: without it, elapsed days are unknowable');
  }

  const complete = rows.filter(r => !r.partial && r.ms < asOf);
  const excluded = rows.length - complete.length;
  if (excluded > 0) reasons.push(`${excluded} row(s) excluded as partial or not yet closed`);

  const spent = degraded
    ? round2(Number(input.spentToDate))
    : round2(complete.reduce((s, r) => s + r.amount, 0));
  const lastComplete = degraded
    ? Math.min(toUTC(input.lastDataDate), asOf - DAY)
    : (complete.length ? complete[complete.length - 1].ms : null);
  const firstSpendRow = complete.find(r => r.amount > 0) || null;
  const firstSpend = firstSpendRow ? firstSpendRow.ms : null;

  // ---- schedule, always against the fixed end date ------------------------
  const daysTotal = daysInclusive(start, end);
  const evenDaily = round2(budget / daysTotal);

  const anchorEnd = lastComplete !== null ? Math.min(lastComplete, asOf - DAY) : asOf - DAY;
  const daysElapsed = Math.max(0, daysInclusive(start, anchorEnd));
  const remainingDays = Math.max(0, daysInclusive(anchorEnd + DAY, end));

  const expectedByNow = daysTotal > 0 ? round2(budget * (daysElapsed / daysTotal)) : 0;
  const paceIndex = expectedByNow > 0 ? round2(spent / expectedByNow) : null;
  const requiredDaily = remainingDays > 0 ? round2((budget - spent) / remainingDays) : null;

  // ---- dead days at launch ------------------------------------------------
  let deadDays = degraded ? null : 0;
  if (degraded) {
    // no series, so the first delivery date is not recoverable
  } else if (firstSpend !== null) {
    deadDays = Math.max(0, daysInclusive(start, firstSpend) - 1);
  } else if (daysElapsed > 0) {
    deadDays = daysElapsed;
  }
  if (degraded) reasons.push('no daily series: dead days, recent rate and peak rate are unavailable');

  // ---- rate and capacity, delivery days only -----------------------------
  const deliveryRows = firstSpend !== null ? complete.filter(r => r.ms >= firstSpend) : [];
  const deliveryDays = deliveryRows.length;
  const amounts = deliveryRows.map(r => r.amount);

  const observedDaily = degraded
    ? (daysElapsed > 0 ? round2(spent / daysElapsed) : null)
    : (deliveryDays > 0 ? round2(spent / deliveryDays) : null);
  const recentRate = (!degraded) && deliveryDays > 0
    ? round2(amounts.slice(-t.recentWindow).reduce((a, b) => a + b, 0) / Math.min(t.recentWindow, deliveryDays))
    : null;

  let peakRate = (!degraded) && deliveryDays > 0 ? round2(rollingMax(amounts, t.peakWindow)) : null;
  let peakIsFallback = false;
  let capacityBasis = degraded ? 'observed_average' : 'rolling_peak';
  if (degraded) {
    // The average achieved so far is a weaker capacity proxy than a rolling
    // peak, so the tolerance widens. It still catches the case that matters:
    // Water and Environment needs 16x its own average.
    peakRate = observedDaily != null ? Math.max(observedDaily, 0) : evenDaily;
    peakIsFallback = true;
  } else if (peakRate === null || deliveryDays < t.peakWindow) {
    peakRate = Math.max(peakRate || 0, evenDaily);
    peakIsFallback = true;
    reasons.push(`peak rate falls back to even pace: only ${deliveryDays} delivery day(s)`);
  }

  const tol = degraded ? t.reachToleranceDegraded : t.reachTolerance;
  const reachable = requiredDaily === null ? true
    : (peakRate > 0 ? requiredDaily <= peakRate * tol : false);
  const recovering = requiredDaily !== null && recentRate !== null && recentRate >= requiredDaily;
  const requiredVsPeak = requiredDaily !== null && peakRate > 0 ? round2(requiredDaily / peakRate) : null;
  // Drift expressed in days of budget. This self-scales: 20% ahead on day 5
  // is under one day of drift, while 20% behind on day 60 is twelve days.
  // It is also the only pacing figure that explains itself in one sentence.
  const driftDays = evenDaily > 0 ? round2((spent - expectedByNow) / evenDaily) : null;

  // Never project more than the budget: a fixed allocation cannot overspend.
  // Few delivery days make any projection unreliable, so say so rather than
  // publishing a confident number built on two days of data.
  const rawProjection = observedDaily !== null && remainingDays > 0
    ? spent + observedDaily * remainingDays
    : spent;
  const projectedFinal = round2(Math.min(rawProjection, budget));
  const projectionConfidence =
    deliveryDays >= 14 ? 'high' : deliveryDays >= 7 ? 'medium' : 'low';

  // A campaign that has just started scaling will show a rolling peak still
  // full of near-zero days. Job 2463 reads unreachable today and clears in two
  // days. Flag it rather than letting people learn to distrust the alert.
  const latestDay = (!degraded) && amounts.length ? amounts[amounts.length - 1] : null;
  const ramping = latestDay != null && peakRate > 0 && latestDay >= peakRate * t.rampMultiple;
  if (ramping) reasons.push('accelerating: latest day is well above the 3-day peak, re-check tomorrow');

  // Data age. BigQuery runs 1 to 2 days behind; the Grid's staleness is app-side
  // (no scheduler running). A stale verdict is not a current verdict.
  const dataAgeDays = lastComplete === null ? null : Math.floor((asOf - lastComplete) / DAY);
  const stale = dataAgeDays !== null && dataAgeDays > t.staleDataDays;
  if (stale) reasons.push(`spend data is ${dataAgeDays} days old: run a sync before acting on this`);

  // ---- state -------------------------------------------------------------
  let state;
  if (remainingDays === 0) {
    state = STATES.ENDED;
  } else if (degraded) {
    // No series, so delivery days are unknown. Gate on elapsed flight instead.
    if (daysElapsed < t.minDeliveryDays || daysElapsed / daysTotal < t.minFlightFraction) {
      state = STATES.TOO_EARLY;
      reasons.push(`too early to judge: ${round2(100 * daysElapsed / daysTotal)}% of flight elapsed`);
    } else if (driftDays > t.driftDaysBand) {
      state = STATES.TOO_FAST;
      reasons.push(`${driftDays} days of budget ahead of schedule`);
    } else if (driftDays >= -t.driftDaysBand) {
      state = STATES.ON_TRACK;
    } else if (!reachable) {
      state = STATES.UNREACHABLE;
      reasons.push(`needs ${requiredDaily}/day against an average of ${observedDaily}/day achieved so far`);
    } else {
      state = STATES.BEHIND_NOT_RECOVERING;
      reasons.push(`${Math.abs(driftDays)} days behind`);
    }
  } else if (firstSpend === null) {
    state = deadDays >= t.deadDayThreshold ? STATES.NOT_LAUNCHED : STATES.TOO_EARLY;
    if (state === STATES.NOT_LAUNCHED) reasons.push(`no delivery in ${deadDays} day(s) since planned start`);
  } else if (deliveryDays < t.minDeliveryDays || daysElapsed / daysTotal < t.minFlightFraction) {
    state = STATES.TOO_EARLY;
    reasons.push(`too early to judge: ${deliveryDays} delivery day(s), ${round2(100 * daysElapsed / daysTotal)}% of flight elapsed`);
  } else if (driftDays > t.driftDaysBand) {
    state = STATES.TOO_FAST;
    reasons.push(`${driftDays} days of budget ahead of schedule`);
  } else if (driftDays >= -t.driftDaysBand) {
    state = STATES.ON_TRACK;
  } else if (!reachable && !ramping) {
    state = STATES.UNREACHABLE;
    reasons.push(`needs ${requiredDaily}/day but best observed 3-day rate is ${peakRate}`);
  } else if (recovering) {
    state = STATES.BEHIND_RECOVERING;
    reasons.push(`${Math.abs(driftDays)} days behind, but current rate covers what is required`);
  } else {
    state = STATES.BEHIND_NOT_RECOVERING;
    reasons.push(`${Math.abs(driftDays)} days behind and not catching up`);
  }

  // Dead days are reported alongside every state, not instead of it. A
  // campaign can have launched a month late and still be catching up.
  const deadDayFlag = deadDays >= t.deadDayThreshold;
  if (deadDayFlag && state !== STATES.NOT_LAUNCHED) {
    reasons.push(`launched ${deadDays} day(s) after planned start`);
  }

  return {
    state,
    degraded,
    deadDays,
    deadDayFlag,
    ramping,
    dataAgeDays,
    stale,
    capacityBasis,
    budget,
    spendBasis: basis,
    currency: input.currency || null,
    platform: input.platform || null,
    level: input.level || 'campaign',
    spent,
    daysTotal,
    daysElapsed,
    remainingDays,
    deliveryDays,
    lastCompleteDate: lastComplete === null ? null : iso(lastComplete),
    firstSpendDate: firstSpend === null ? null : iso(firstSpend),
    evenDaily,
    expectedByNow,
    paceIndex,
    driftDays,
    requiredDaily,
    observedDaily,
    recentRate,
    peakRate: round2(peakRate),
    peakIsFallback,
    requiredVsPeak,
    reachable,
    recovering,
    projectedFinal,
    projectionConfidence,
    shortfall: round2(Math.max(0, budget - projectedFinal)),
    reasons
  };
}

/**
 * Money the agency loses if the projection holds.
 *
 * Margin resolves from the platform, not from a per-row field. Pass marginPct
 * only to override deliberately.
 *
 * Caveat worth carrying into the UI: on TradeDesk the fee card reads "60% of
 * partner cost", and billed also carries per-impression ad serving plus audience
 * data fees. On Caltex the observed billed-to-partner ratio was 8.16x where the
 * margin alone predicts 1.6x, so treat this figure as an estimate and label it
 * as one.
 */
function profitAtRisk(pacing, marginPct) {
  const m = marginPct === undefined ? resolveMargin(pacing.platform) : marginPct;
  if (!(m >= 0 && m < 1)) {
    throw new Error('margin must be >= 0 and < 1: a margin of 1 or more makes the maths undefined');
  }
  if (pacing.spendBasis !== 'billed') {
    return { value: null, estimated: true, reason: 'profit at risk needs a billed-basis budget' };
  }
  return { value: round2(pacing.shortfall * m), marginUsed: m, estimated: true };
}

/** Roll ad-set level results up. Never averages a pace index. */
function rollUp(results) {
  const budget = results.reduce((s, r) => s + r.budget, 0);
  const spent = round2(results.reduce((s, r) => s + r.spent, 0));
  const shortfall = round2(results.reduce((s, r) => s + r.shortfall, 0));
  return {
    budget,
    spent,
    shortfall,
    percentSpent: budget > 0 ? round2(100 * spent / budget) : null,
    worstState: results.slice().sort((a, b) => severity(b.state) - severity(a.state))[0]?.state ?? null,
    children: results.length
  };
}

function severity(state) {
  return {
    ENDED: 0, TOO_EARLY: 1, ON_TRACK: 2, BEHIND_RECOVERING: 3,
    TOO_FAST: 4, BEHIND_NOT_RECOVERING: 5, UNREACHABLE: 6, NOT_LAUNCHED: 7
  }[state] ?? 0;
}

/** Never sum across currencies. Aggregates return one entry per currency. */
function rollUpByCurrency(results) {
  const out = {};
  for (const r of results) {
    const c = r.currency || 'UNKNOWN';
    (out[c] = out[c] || []).push(r);
  }
  for (const c of Object.keys(out)) out[c] = rollUp(out[c]);
  return out;
}

module.exports = {
  computePacing, profitAtRisk, rollUp, rollUpByCurrency, resolveMargin,
  STATES, DEFAULTS, PLATFORM_RULES, AD_SERVING_CPM, normPlatform, severity
};
