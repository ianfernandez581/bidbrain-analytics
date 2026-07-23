/*
 * src/central/staleness.test.js — locks the ONE freshness-threshold config
 * (Phase 4 item 4): warn > 6h, red > 24h, never-synced is never "fresh", and the
 * per-client mixed-state rollup (§9's invisible containment state).
 */
'use strict';
const st = require('./staleness');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };

const NOW = Date.parse('2026-07-23T12:00:00Z');
const H = 3600000;

// ---- thresholds live here and only here ----
check('warn threshold is 6h', st.STALE_WARN_MS === 6 * H);
check('red threshold is 24h', st.STALE_RED_MS === 24 * H);

// ---- classify ----
check('within 6h → fresh', st.classify(NOW - 5.9 * H, NOW) === 'fresh');
check('just over 6h → warn', st.classify(NOW - 6.1 * H, NOW) === 'warn');
check('just over 24h → red', st.classify(NOW - 24.1 * H, NOW) === 'red');
check('null → never (not fresh)', st.classify(null, NOW) === 'never');
check('ISO string accepted', st.classify('2026-07-23T11:00:00Z', NOW) === 'fresh');
check('garbage string → never', st.classify('not-a-date', NOW) === 'never');

// ---- agoLabel ----
check('agoLabel minutes', st.agoLabel(NOW - 35 * 60000, NOW) === '35m ago');
check('agoLabel hours (floored)', st.agoLabel(NOW - 9.6 * H, NOW) === '9h ago');
check('agoLabel days', st.agoLabel(NOW - 72 * H, NOW) === '3d ago');
check('agoLabel never', st.agoLabel(null, NOW) === 'never');

// ---- clientSyncState ----
const live = t => ({ metricsSource: 'bq', lastSyncedAt: new Date(t).toISOString() });
const sheet = () => ({ metricsSource: 'sheet-import', lastSyncedAt: null });

const never = st.clientSyncState([sheet(), sheet()], NOW);
check('all sheet-import → never (not fresh)', never.state === 'never' && never.live === 0 && never.sheet === 2, never);
check('never is not mixed', never.mixed === false);

const mixed = st.clientSyncState([live(NOW - 1 * H), live(NOW - 2 * H), sheet()], NOW);
check('live+sheet → mixed, newest wins, fresh', mixed.mixed === true && mixed.state === 'fresh' && mixed.sheet === 1 && mixed.live === 2, mixed);

const old = st.clientSyncState([live(NOW - 30 * H)], NOW);
check('single live row 30h old → red', old.state === 'red' && !old.mixed, old);

const warn = st.clientSyncState([live(NOW - 7 * H), sheet()], NOW);
check('mixed + 7h old → warn + mixed', warn.state === 'warn' && warn.mixed === true, warn);

check('uppercase BQ metricsSource counts as live', st.clientSyncState([{ metricsSource: 'BQ', lastSyncedAt: new Date(NOW).toISOString() }], NOW).state === 'fresh');
check('empty rows → never', st.clientSyncState([], NOW).state === 'never');

console.log('\n' + (fail ? '✗' : '✓') + ' staleness: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
