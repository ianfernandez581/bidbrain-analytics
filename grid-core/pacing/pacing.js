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
  reachTolerance: 1.15,     // required may exceed peak by this much and still be reachable
  deadDayThreshold: 2       // consecutive zero days from planned start before flagging
};

const STATES = {
  NOT_LAUNCHED: 'NOT_LAUNCHED',
  TOO_EARLY: 'TOO_EARLY',
  ON_TRACK: 'ON_TRACK',
  TOO_FAST: 'TOO_FAST',
  BEHIND_RECOVERING: 'BEHIND_RECOVERING',
  BEHIND_NOT_RECOVERING: 'BEHIND_NOT_RECOVERING',
  UNREACHABLE: 'UNREACHABLE',
  ENDED: 'ENDED'
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
  if (!input.budgetBasis) throw new Error('budgetBasis must be "client" or "media"');

  // ---- complete days only -------------------------------------------------
  const rows = (input.dailySpend || [])
    .map(r => ({ ms: toUTC(r.date), amount: Number(r.amount) || 0, partial: !!r.partial }))
    .filter(r => r.ms >= start && r.ms <= end)
    .sort((a, b) => a.ms - b.ms);

  const complete = rows.filter(r => !r.partial && r.ms < asOf);
  const excluded = rows.length - complete.length;
  if (excluded > 0) reasons.push(`${excluded} row(s) excluded as partial or not yet closed`);

  const spent = round2(complete.reduce((s, r) => s + r.amount, 0));
  const lastComplete = complete.length ? complete[complete.length - 1].ms : null;
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
  let deadDays = 0;
  if (firstSpend !== null) {
    deadDays = Math.max(0, daysInclusive(start, firstSpend) - 1);
  } else if (daysElapsed > 0) {
    deadDays = daysElapsed;
  }

  // ---- rate and capacity, delivery days only -----------------------------
  const deliveryRows = firstSpend !== null ? complete.filter(r => r.ms >= firstSpend) : [];
  const deliveryDays = deliveryRows.length;
  const amounts = deliveryRows.map(r => r.amount);

  const observedDaily = deliveryDays > 0 ? round2(spent / deliveryDays) : null;
  const recentRate = deliveryDays > 0
    ? round2(amounts.slice(-t.recentWindow).reduce((a, b) => a + b, 0) / Math.min(t.recentWindow, deliveryDays))
    : null;

  let peakRate = deliveryDays > 0 ? round2(rollingMax(amounts, t.peakWindow)) : null;
  let peakIsFallback = false;
  if (peakRate === null || deliveryDays < t.peakWindow) {
    peakRate = Math.max(peakRate || 0, evenDaily);
    peakIsFallback = true;
    reasons.push(`peak rate falls back to even pace: only ${deliveryDays} delivery day(s)`);
  }

  const reachable = requiredDaily === null ? true : requiredDaily <= peakRate * t.reachTolerance;
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

  // ---- state -------------------------------------------------------------
  let state;
  if (remainingDays === 0) {
    state = STATES.ENDED;
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
  } else if (!reachable) {
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
    deadDays,
    deadDayFlag,
    budget,
    budgetBasis: input.budgetBasis,
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

/** Money the agency loses if the projection holds. Margin is a per-platform fact. */
function profitAtRisk(pacing, marginPct) {
  if (!(marginPct >= 0 && marginPct <= 1)) throw new Error('marginPct must be between 0 and 1');
  if (pacing.budgetBasis !== 'client') {
    throw new Error('profitAtRisk expects a client-basis budget');
  }
  return round2(pacing.shortfall * marginPct);
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

module.exports = { computePacing, profitAtRisk, rollUp, STATES, DEFAULTS, severity };
