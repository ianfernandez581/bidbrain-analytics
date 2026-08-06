/*
 * expected/tokens.test.js - the pre-run token estimate and its self-calibration.
 *
 * The estimate exists so a buyer can see what a run costs BEFORE paying for it.
 * It must never present a guess as a measurement, and one bad observation must
 * not poison it. Free, deterministic, no key, no server, no network.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const t = require('./tokens');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'gl-tok-'));

// ---- uncalibrated: honest about being a guess ----
let d = tmp();
let e = t.estimate(d, 200000, 6000, 64000);
check('estimates from characters', e.input_tokens === Math.round(206000 / t.SEED_CHARS_PER_TOKEN), e.input_tokens);
check('says it is NOT calibrated before any run', e.calibrated === false);
check('reports a wider band when uncalibrated', e.accuracy === 0.25, e.accuracy);
check('reports the output ceiling, not a guess', e.output_tokens_max === 64000);
check('carries the char count it used', e.chars === 200000);

// ---- one real observation calibrates it ----
// 200,000 chars really cost 100,000 tokens -> 2.0 chars/token
check('an observation is accepted', t.observe(d, 200000, 100000) === 2);
e = t.estimate(d, 200000, 0, 64000);
check('now calibrated', e.calibrated === true && e.samples === 1, e);
check('uses the MEASURED ratio', e.chars_per_token === 2, e.chars_per_token);
check('estimate matches the measurement', e.input_tokens === 100000, e.input_tokens);
check('tighter band once measured', e.accuracy === 0.10);

// ---- averages across runs ----
t.observe(d, 100000, 25000);           // 4.0 chars/token
e = t.estimate(d, 300000, 0, 64000);
check('averages observations (2.0 and 4.0 -> 3.0)', e.chars_per_token === 3, e.chars_per_token);
check('two samples recorded', e.samples === 2);

// ---- implausible observations are rejected, not averaged in ----
d = tmp();
t.observe(d, 200000, 100000);          // good: 2.0
check('absurdly low ratio rejected', t.observe(d, 1000, 10000) === null);      // 0.1
check('absurdly high ratio rejected', t.observe(d, 1000000, 1000) === null);   // 1000
check('zero tokens rejected', t.observe(d, 200000, 0) === null);
check('null tokens rejected', t.observe(d, 200000, null) === null);
check('zero chars rejected', t.observe(d, 0, 100) === null);
check('the good sample survives intact', t.estimate(d, 200000, 0, 64000).chars_per_token === 2);

// ---- durability + resilience ----
check('calibration persists to disk', fs.existsSync(path.join(d, '_token_calibration.json')));
fs.writeFileSync(path.join(d, '_token_calibration.json'), 'not json at all');
check('a corrupt calibration file falls back to the seed, does not throw',
  t.estimate(d, 200000, 0, 64000).calibrated === false);

// ---- a missing directory must not throw ----
check('unknown dir estimates from the seed',
  t.estimate(path.join(os.tmpdir(), 'gl-does-not-exist-' + Date.now()), 1000, 0, 64000).calibrated === false);

// ---- the ratio only ever reflects the last MAX_SAMPLES runs ----
d = tmp();
for (let i = 0; i < 30; i++) t.observe(d, 200000, 100000);
check('sample window is bounded', t.estimate(d, 1000, 0, 64000).samples === 20, t.estimate(d, 1000, 0, 64000).samples);

console.log('\n' + (fail ? '✗' : '✓') + ' tokens: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
