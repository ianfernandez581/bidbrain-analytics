/*
 * expected/build.test.js - locks the baseline arithmetic and the refusal paths.
 *
 * Runs the REAL build_expected.js against fixture plan.json files in a temp
 * out/ dir, so exit codes and artifacts are exercised exactly as the run engine
 * exercises them. Free, deterministic, no key, no server, no network.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };

const cited = (value) => ({ value, citation: { file: 'media_plan.xlsx', location: "sheet 'Plan', row 8" } });
// A usable line needs a budget AND at least one volume goal AND dates -
// anything less is an exception by design, so the default fixture carries all
// three and each refusal test removes exactly one.
const line = (name, budget, extra) => Object.assign({
  campaign_name: name, platform: 'LinkedIn',
  budget: cited(budget), rate_type: 'CPM', rate_value: cited(null),
  goal_impressions: cited(100000), goal_clicks: cited(null), goal_ctr: null,
  start: null, end: null,
}, extra || {});

const basePlan = (over) => Object.assign({
  client: cited('Acme'), job_number: cited('2053'), campaign_name: cited('Launch'),
  currency: cited('AUD'), total_budget: cited(20000),
  flight_start: { value: '2026-06-01', candidates: [], resolution_rationale: null },
  flight_end: { value: '2026-08-22', candidates: [], resolution_rationale: null },
  stated_duration_days: cited(83),
  campaigns: [line('LinkedIn A', 6000), line('Programmatic', 14000)],
  platform_campaigns: { rows: [], claimed_total: { value: null, citation: null } },
  urls: [], approval_records: [], referenced_files: [], name_collisions: [],
  extractor: { model: 'test', generated_at: '2026-08-06T00:00:00Z' },
}, over || {});

/** Run build_expected.js against a fixture; returns {code, out, dir}. */
function build(plan, findings) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gl-build-'));
  fs.writeFileSync(path.join(dir, 'plan.json'), JSON.stringify(plan));
  fs.writeFileSync(path.join(dir, 'findings.json'), JSON.stringify(findings || { origins: { code: 0, model: 0 }, findings: [] }));
  const r = spawnSync(process.execPath, [path.join(__dirname, 'build_expected.js')], {
    env: Object.assign({}, process.env, { GREENLIGHT_OUT_DIR: dir }), encoding: 'utf8',
  });
  const read = (f) => { try { return JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')); } catch { return null; } };
  return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '', dir, kpi: read('daily_kpi.json'), findings: read('findings.json') };
}
const cleanup = (r) => fs.rmSync(r.dir, { recursive: true, force: true });

// ---- the happy path ----
const ok = build(basePlan());
check('a complete plan builds (exit 0)', ok.code === 0, ok.stderr.slice(-200));
check('83 inclusive days per campaign', ok.kpi.campaigns.every((c) => c.daily.length === 83), ok.kpi.campaigns.map((c) => c.daily.length));
check('final cumulative equals the goal EXACTLY', ok.kpi.campaigns.map((c) => c.daily[82].expected_spend_cum).sort((a, b) => a - b).join('/') === '6000/14000',
  ok.kpi.campaigns.map((c) => c.daily[82].expected_spend_cum));
check('first day is the flight start', ok.kpi.campaigns[0].daily[0].date === '2026-06-01');
check('last day is the flight end', ok.kpi.campaigns[0].daily[82].date === '2026-08-22');
check('daily spend sums to the goal', Math.abs(ok.kpi.campaigns[0].daily.reduce((a, d) => a + d.expected_spend_day, 0) - 6000) < 0.01);
check('all 7 artifacts written',
  ['daily_kpi.xlsx', 'daily_kpi.json', 'pacing.html', 'flowchart.html', 'report.md'].every((f) => fs.existsSync(path.join(ok.dir, f))));
check('no em or en dashes in the outputs',
  !/[–—]/.test(fs.readFileSync(path.join(ok.dir, 'report.md'), 'utf8') + JSON.stringify(ok.kpi)));
cleanup(ok);

// ---- F3: duplicate campaign names must not merge into each other ----
// (normalizePlan uniquifies upstream; this proves the builder keeps them apart
// even if two distinctly-named lines arrive.)
const dup = build(basePlan({ campaigns: [line('Awareness', 6000), line('Awareness (2)', 4000)], total_budget: cited(10000) }));
check('two same-ish lines stay separate', dup.kpi.campaigns.length === 2, dup.kpi.campaigns.length);
check('neither line absorbs the other\'s rows', dup.kpi.campaigns.every((c) => c.daily.length === 83), dup.kpi.campaigns.map((c) => c.daily.length));
check('each keeps its own goal', dup.kpi.campaigns.map((c) => c.daily[82].expected_spend_cum).sort((a, b) => a - b).join('/') === '4000/6000',
  dup.kpi.campaigns.map((c) => c.daily[82].expected_spend_cum));
cleanup(dup);

// ---- exceptions: an under-specified line is named, never zero rows ----
const exc = build(basePlan({ campaigns: [line('Good', 6000), line('NoBudget', null)] }));
check('under-specified line builds the rest (exit 0)', exc.code === 0);
check('under-specified line becomes an exception', exc.kpi.exceptions.length === 1 && exc.kpi.exceptions[0].campaign === 'NoBudget', exc.kpi.exceptions);
check('no zero-valued rows are emitted for it', exc.kpi.campaigns.length === 1);
cleanup(exc);

// ---- refusal: no usable campaign at all ----
const none = build(basePlan({ campaigns: [line('NoBudget', null)] }));
check('no usable campaign refuses (exit 3)', none.code === 3, none.code);
check('refusal explains itself', /no campaign has enough data/i.test(none.stderr), none.stderr.slice(0, 120));
cleanup(none);

// ---- refusal: unresolvable flight, and the ladder that avoids it ----
const noDates = build(basePlan({
  flight_start: { value: null, candidates: [], resolution_rationale: null },
  flight_end: { value: null, candidates: [], resolution_rationale: null },
}));
check('unresolvable flight refuses (exit 3) rather than inventing one', noDates.code === 3, noDates.code);
cleanup(noDates);

// ladder rung 2: the campaign lines carry their own dates
const rung2 = build(basePlan({
  flight_start: { value: null, candidates: [], resolution_rationale: null },
  flight_end: { value: null, candidates: [], resolution_rationale: null },
  campaigns: [line('A', 6000, { start: '2026-06-01', end: '2026-06-30' })],
}));
check('ladder: falls back to the lines own dates (exit 0)', rung2.code === 0, rung2.stderr.slice(-160));
check('ladder: 30 inclusive days', rung2.kpi.campaigns[0].daily.length === 30, rung2.kpi.campaigns[0].daily.length);
check('ladder: the assumption is raised as a VISIBLE finding',
  rung2.findings.findings.some((f) => f.chip === 'ASSUMED FLIGHT' && f.origin === 'code'), rung2.findings.findings.map((f) => f.chip));
cleanup(rung2);

// ladder rung 3: a single dated candidate per endpoint
const rung3 = build(basePlan({
  flight_start: { value: null, candidates: [{ value: '2026-07-01', file: 'a.xlsx' }], resolution_rationale: null },
  flight_end: { value: null, candidates: [{ value: '2026-07-31', file: 'a.xlsx' }], resolution_rationale: null },
  campaigns: [line('A', 6000)],
}));
check('ladder: adopts a sole dated candidate (exit 0)', rung3.code === 0, rung3.stderr.slice(-160));
check('ladder: 31 inclusive days', rung3.kpi.campaigns[0].daily.length === 31, rung3.kpi.campaigns[0].daily.length);
cleanup(rung3);

console.log('\n' + (fail ? '✗' : '✓') + ' build: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
