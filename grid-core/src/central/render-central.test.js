/*
 * src/central/render-central.test.js — the health SUMMARY counts only Active+Paused.
 * Regression lock for the "53 watch over 39 live rows" bug: Ended / Not Active / Draft
 * campaigns must NOT colour the portfolio-health summary (they dominated the tally).
 * Pure: exercises the exported _healthCountsLive on synthetic rows (no DOM, no calc).
 */
'use strict';
const view = require('./render-central');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };
const row = (status, health) => ({ status: status, _d: { health: health } });

// A portfolio where the Ended/Not-Active backlog is full of 'watch', but only 2 live rows.
const rows = [
  row('Active', 'winner'), row('Active', 'watch'), row('Paused', 'steady'),
  row('Ended', 'watch'), row('Ended', 'watch'), row('Ended', 'watch'), row('Ended', 'winner'),
  row('Not Active', 'watch'), row('Not Active', 'steady'),
  row('Draft', null), row('Draft', null)
];

const live = view._healthCountsLive(rows);
const all = view._healthCounts(rows);

check('HEALTH_STATUSES is exactly [Active, Paused]', JSON.stringify(view.HEALTH_STATUSES) === '["Active","Paused"]', view.HEALTH_STATUSES);
check('live health ignores Ended/Not Active/Draft: winner 1 / watch 1 / steady 1',
  live.winner === 1 && live.watch === 1 && live.steady === 1, live);
check('naive count (all rows) over-counts watch (5: 1 live + 3 Ended + 1 Not Active)', all.watch === 5, all);
check('the fix removes the 4 non-live watch rows from the summary', all.watch - live.watch === 4, { all: all.watch, live: live.watch });
check('Draft (null health) contributes nothing either way', live.winner + live.watch + live.steady === 3);

// empty / no-live portfolio → all zero, never NaN
const none = view._healthCountsLive([row('Ended', 'watch'), row('Not Active', 'watch')]);
check('no live rows → zeros (not NaN)', none.winner === 0 && none.watch === 0 && none.steady === 0, none);

console.log('\n' + (fail ? '✗' : '✓') + ' render-central health summary: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
