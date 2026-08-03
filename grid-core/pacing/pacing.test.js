'use strict';

/**
 * Run with:  node --test pacing.test.js
 * Zero dependencies. Uses the Node built-in test runner.
 *
 * Fixtures are real campaigns with verdicts supplied by the media buyer.
 * The buyer's judgement is the assertion. If this suite passes, the engine
 * agrees with the people who do this for a living.
 *
 * RECONSTRUCTED marks a fixture where only an aggregate was available and
 * the daily series has been spread evenly. Figures that depend on the shape
 * of the series (recentRate, peakRate) are NOT asserted on those fixtures.
 * Replace with the real BigQuery series and the assertions get stronger.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { computePacing, profitAtRisk, rollUp, STATES } = require('./pacing');

const AS_OF = '2026-08-03';

function evenSeries(start, days, total) {
  const per = total / days;
  const out = [];
  const [y, m, d] = start.split('-').map(Number);
  for (let i = 0; i < days; i++) {
    const dt = new Date(Date.UTC(y, m - 1, d + i));
    out.push({ date: dt.toISOString().slice(0, 10), amount: per });
  }
  return out;
}

// ---------------------------------------------------------------------------
// 2279_SE_EcoConsult_ECAA_2026_ANZ_Awareness
// LinkedIn, A$10,500, 0% margin, 21 Jul to 19 Sep. Verdict: healthy.
// RECONSTRUCTED series: A$2,396.10 over 13 complete days.
// ---------------------------------------------------------------------------
test('EcoConsult reads healthy and slightly ahead', () => {
  const r = computePacing({
    budget: 10500, budgetBasis: 'client', currency: 'AUD', platform: 'linkedin',
    plannedStart: '2026-07-21', flightEnd: '2026-09-19',
    dailySpend: evenSeries('2026-07-21', 13, 2396.10),
    asOf: AS_OF
  });

  assert.equal(r.daysTotal, 61);
  assert.equal(r.daysElapsed, 13);
  assert.equal(r.remainingDays, 48);
  assert.equal(r.evenDaily, 172.13);
  assert.equal(r.spent, 2396.1);
  assert.equal(r.deadDays, 0);

  // The buyer's manual figure was 0.99 because it counted today, a partial day.
  // Excluding today the campaign is 7% ahead, and needs LESS per day from here.
  assert.equal(r.paceIndex, 1.07);
  assert.equal(r.requiredDaily, 168.83);
  assert.ok(r.requiredDaily < r.evenDaily, 'required daily should now be below even pace');

  assert.equal(r.state, STATES.ON_TRACK);
  assert.equal(r.reachable, true);
});

// ---------------------------------------------------------------------------
// Caltex Star Card | QLD+WA
// TTD, A$15,000 client budget, 60% platform margin, 29 Jul to 29 Oct.
// Verdict: healthy. RECONSTRUCTED: A$976.24 over 5 complete days.
// ---------------------------------------------------------------------------
test('Caltex reads healthy on a client-basis budget', () => {
  const r = computePacing({
    budget: 15000, budgetBasis: 'client', currency: 'AUD', platform: 'ttd',
    plannedStart: '2026-07-29', flightEnd: '2026-10-29',
    dailySpend: evenSeries('2026-07-29', 5, 976.24),
    asOf: AS_OF
  });

  assert.equal(r.daysTotal, 93);
  assert.equal(r.daysElapsed, 5);
  assert.equal(r.evenDaily, 161.29);
  assert.equal(r.paceIndex, 1.21);
  assert.equal(r.requiredDaily, 159.36);
  assert.equal(r.state, STATES.ON_TRACK);
});

test('Caltex on a media-basis budget is a false alarm, which is why basis is explicit', () => {
  const wrong = computePacing({
    budget: 6000, budgetBasis: 'media', currency: 'AUD', platform: 'ttd',
    plannedStart: '2026-07-29', flightEnd: '2026-10-29',
    dailySpend: evenSeries('2026-07-29', 5, 976.24),
    asOf: AS_OF
  });
  // TTD reports gross of platform margin, so haircutting the budget by 60%
  // makes a healthy campaign look like it is burning 3x too fast.
  assert.equal(wrong.paceIndex, 3.03);
  assert.equal(wrong.state, STATES.TOO_FAST);
});

// ---------------------------------------------------------------------------
// 2463_SE_ANZ Industrial Edge W3 Prefab_Programmatic_Awareness
// TTD, 1 Jul to 30 Nov. Flight A$9,150 across two Fixed ad groups.
// Nothing delivered until 1 Aug: 31 dead days.
// Verdict: should have been caught.
// ---------------------------------------------------------------------------
const JOB_2463 = {
  plannedStart: '2026-07-01',
  flightEnd: '2026-11-30',
  platform: 'ttd',
  currency: 'AUD',
  budgetBasis: 'client'
};

function withDeadJuly(firstSpendSeries) {
  const zeros = [];
  for (let d = 1; d <= 31; d++) {
    zeros.push({ date: `2026-07-${String(d).padStart(2, '0')}`, amount: 0 });
  }
  return zeros.concat(firstSpendSeries);
}

test('job 2463 flags 31 dead days at launch', () => {
  const r = computePacing(Object.assign({}, JOB_2463, {
    budget: 9150,
    dailySpend: withDeadJuly([
      { date: '2026-08-01', amount: 126.64 },
      { date: '2026-08-02', amount: 42.66 }
    ]),
    asOf: AS_OF
  }));

  assert.equal(r.daysTotal, 153);
  assert.equal(r.deadDays, 31);
  assert.equal(r.deadDayFlag, true);
  assert.equal(r.firstSpendDate, '2026-08-01');
  assert.equal(r.deliveryDays, 2);
  assert.ok(r.reasons.some(x => x.includes('31 day(s) after planned start')));

  // Anchoring the schedule to first spend would report this campaign as
  // AHEAD of pace. It is not. The end date never moved.
  assert.equal(r.daysElapsed, 33);
  assert.ok(r.paceIndex < 0.1, `pace index should be near zero, got ${r.paceIndex}`);

  // Two delivery days is not enough to judge pacing. Dead days carry the alert.
  assert.equal(r.state, STATES.TOO_EARLY);
});

test('job 2463 reports NOT_LAUNCHED before any delivery', () => {
  const r = computePacing(Object.assign({}, JOB_2463, {
    budget: 9150,
    dailySpend: withDeadJuly([]).slice(0, 10),
    asOf: '2026-07-11'
  }));
  assert.equal(r.state, STATES.NOT_LAUNCHED);
  assert.equal(r.deadDays, 10);
});

test('job 2463 ad groups disagree, and the campaign roll up hides it', () => {
  const nz = computePacing(Object.assign({}, JOB_2463, {
    budget: 1830, level: 'adset',
    dailySpend: withDeadJuly([
      { date: '2026-08-01', amount: 65.63 },
      { date: '2026-08-02', amount: 26.57 }
    ]),
    asOf: AS_OF
  }));
  const au = computePacing(Object.assign({}, JOB_2463, {
    budget: 7320, level: 'adset',
    dailySpend: withDeadJuly([
      { date: '2026-08-01', amount: 61.02 },
      { date: '2026-08-02', amount: 16.09 }
    ]),
    asOf: AS_OF
  }));

  // 20% of the budget needs A$14/day. 80% of it needs A$60/day.
  assert.equal(nz.requiredDaily, 14.48);
  assert.equal(au.requiredDaily, 60.36);
  assert.ok(au.requiredDaily / nz.requiredDaily > 4);

  // NZ is already running above what it needs; AU is far below.
  assert.ok(nz.recentRate > nz.requiredDaily, 'NZ is over-delivering against its own target');
  assert.ok(au.recentRate < au.requiredDaily, 'AU is under-delivering against its own target');

  const total = rollUp([nz, au]);
  assert.equal(total.budget, 9150);
  assert.equal(total.percentSpent, 1.85);
  // The roll up shows one number that describes neither ad group.
  assert.ok(total.shortfall > 2500 && total.shortfall < 7500);
  // NZ projects past its own budget, so its shortfall is zero. All the risk
  // sits in AU. Projection confidence is low on two delivery days.
  assert.equal(au.projectionConfidence, 'low');
  assert.equal(nz.shortfall, 0);
});

// ---------------------------------------------------------------------------
// The regression test for the incident. A campaign whose creative was double
// the expected size, spending 19 of 1000 over a month. Placeholder dates.
// Replace with the real campaign's figures when available.
// ---------------------------------------------------------------------------
test('the 19 dollar incident is caught as unreachable', () => {
  const series = [];
  for (let d = 1; d <= 30; d++) {
    series.push({ date: `2026-06-${String(d).padStart(2, '0')}`, amount: 19 / 30 });
  }
  const r = computePacing({
    budget: 1000, budgetBasis: 'client', currency: 'USD', platform: 'ttd',
    plannedStart: '2026-06-01', flightEnd: '2026-06-30',
    dailySpend: series, asOf: '2026-07-01'
  });
  assert.equal(r.state, STATES.ENDED);
  assert.equal(r.spent, 19);
  assert.ok(r.shortfall > 900);
});

test('the same campaign is flagged unreachable on day five, not at month end', () => {
  const series = [];
  for (let d = 1; d <= 5; d++) {
    series.push({ date: `2026-06-${String(d).padStart(2, '0')}`, amount: 19 / 30 });
  }
  const r = computePacing({
    budget: 1000, budgetBasis: 'client', currency: 'USD', platform: 'ttd',
    plannedStart: '2026-06-01', flightEnd: '2026-06-30',
    dailySpend: series, asOf: '2026-06-06'
  });
  assert.equal(r.state, STATES.UNREACHABLE);
  assert.ok(r.requiredDaily > 39);
  assert.ok(r.peakRate < 1);
  assert.equal(r.reachable, false);
});

// ---------------------------------------------------------------------------
// Convention tests. These are the traps, asserted so they cannot regress.
// ---------------------------------------------------------------------------
test('today is excluded from every calculation', () => {
  const base = {
    budget: 1000, budgetBasis: 'client', plannedStart: '2026-07-01',
    flightEnd: '2026-07-31', asOf: '2026-07-11'
  };
  const withoutToday = computePacing(Object.assign({}, base, {
    dailySpend: evenSeries('2026-07-01', 10, 300)
  }));
  const withPartialToday = computePacing(Object.assign({}, base, {
    dailySpend: evenSeries('2026-07-01', 10, 300).concat([{ date: '2026-07-11', amount: 5 }])
  }));
  assert.equal(withoutToday.spent, withPartialToday.spent);
  assert.equal(withoutToday.paceIndex, withPartialToday.paceIndex);
});

test('rows explicitly marked partial are excluded', () => {
  const r = computePacing({
    budget: 1000, budgetBasis: 'client', plannedStart: '2026-07-01',
    flightEnd: '2026-07-31', asOf: '2026-07-11',
    dailySpend: evenSeries('2026-07-01', 9, 270).concat([
      { date: '2026-07-10', amount: 999, partial: true }
    ])
  });
  assert.equal(r.spent, 270);
  assert.ok(r.reasons.some(x => x.includes('excluded as partial')));
});

test('a late launch raises required daily rather than forgiving the target', () => {
  const onTime = computePacing({
    budget: 900, budgetBasis: 'client', plannedStart: '2026-07-01',
    flightEnd: '2026-07-30', asOf: '2026-07-11',
    dailySpend: evenSeries('2026-07-01', 10, 300)
  });
  const late = computePacing({
    budget: 900, budgetBasis: 'client', plannedStart: '2026-07-01',
    flightEnd: '2026-07-30', asOf: '2026-07-11',
    dailySpend: evenSeries('2026-07-01', 5, 0).concat(evenSeries('2026-07-06', 5, 150))
  });
  assert.ok(late.requiredDaily > onTime.requiredDaily);
  assert.equal(late.deadDays, 5);
  assert.equal(onTime.remainingDays, late.remainingDays);
});

test('peak rate is a rolling three day mean, not a single spiky day', () => {
  const r = computePacing({
    budget: 1000, budgetBasis: 'client', plannedStart: '2026-07-01',
    flightEnd: '2026-07-31', asOf: '2026-07-11',
    dailySpend: [
      { date: '2026-07-01', amount: 10 }, { date: '2026-07-02', amount: 10 },
      { date: '2026-07-03', amount: 10 }, { date: '2026-07-04', amount: 300 },
      { date: '2026-07-05', amount: 10 }, { date: '2026-07-06', amount: 10 },
      { date: '2026-07-07', amount: 10 }, { date: '2026-07-08', amount: 10 },
      { date: '2026-07-09', amount: 10 }, { date: '2026-07-10', amount: 10 }
    ]
  });
  assert.ok(r.peakRate < 300, 'a single 300 day must not become the capacity ceiling');
  assert.ok(r.peakRate > 100);
});

test('profit at risk uses the client basis and the platform margin', () => {
  const r = computePacing({
    budget: 10000, budgetBasis: 'client', platform: 'ttd',
    plannedStart: '2026-07-01', flightEnd: '2026-07-31', asOf: '2026-07-11',
    dailySpend: evenSeries('2026-07-01', 10, 1000)
  });
  assert.ok(r.shortfall > 5000);
  assert.equal(profitAtRisk(r, 0.6), Math.round(r.shortfall * 0.6 * 100) / 100);
  assert.throws(() => profitAtRisk(Object.assign({}, r, { budgetBasis: 'media' }), 0.6));
});

test('a campaign with no spend at all does not divide by zero', () => {
  const r = computePacing({
    budget: 5000, budgetBasis: 'client', plannedStart: '2026-08-01',
    flightEnd: '2026-10-31', asOf: '2026-08-03', dailySpend: []
  });
  assert.equal(r.spent, 0);
  assert.equal(r.observedDaily, null);
  assert.ok(Number.isFinite(r.requiredDaily));
  assert.equal(r.state, STATES.NOT_LAUNCHED);
});

test('the final day does not divide by zero remaining days', () => {
  const r = computePacing({
    budget: 300, budgetBasis: 'client', plannedStart: '2026-07-01',
    flightEnd: '2026-07-10', asOf: '2026-07-11',
    dailySpend: evenSeries('2026-07-01', 10, 290)
  });
  assert.equal(r.remainingDays, 0);
  assert.equal(r.requiredDaily, null);
  assert.equal(r.state, STATES.ENDED);
});
