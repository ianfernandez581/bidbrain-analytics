// Regression gate for the Expected side, run against the live server (the
// same API path the UI drives). Requires the server on EXPECTED_PORT (8791)
// and the Schneider NEL dump in grid-core/files. This is the ONE place the
// known-good numbers live; the pipeline itself carries no client literals.
//
//   node test_regression.js
//
// PASSES only when the cold run extracts: job 2053, AUD, total 35000 split
// 8000 TradeDesk + 6000/14000/7000 LinkedIn, flight 2026-06-01..2026-08-22
// (83 days), AND the code validator re-catches the 35,000-vs-27,000 label
// and the 82-vs-83 day discrepancy.
'use strict';

const PORT = Number(process.env.EXPECTED_PORT || 8791);
const BASE = `http://localhost:${PORT}`;
const TIMEOUT_MS = 8 * 60 * 1000;

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok, detail });
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' - ' + detail : ''}`);
}

async function jget(p) {
  const r = await fetch(BASE + p);
  if (!r.ok) throw new Error(`${p} -> HTTP ${r.status}`);
  return r.json();
}

async function main() {
  console.log('regression: starting cold run via POST /api/expected/analyze');
  const start = await fetch(BASE + '/api/expected/analyze', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
  });
  if (!start.ok) throw new Error(`analyze -> HTTP ${start.status}: ${await start.text()}`);
  const { runId } = await start.json();
  console.log('runId:', runId);

  const t0 = Date.now();
  let run;
  for (;;) {
    await new Promise((r) => setTimeout(r, 2000));
    run = await jget('/api/expected/runs/' + runId);
    if (run.status !== 'running') break;
    if (Date.now() - t0 > TIMEOUT_MS) throw new Error('run timed out');
  }
  if (run.status === 'error') throw new Error('run failed: ' + run.error);
  console.log(`run done in ${((Date.now() - t0) / 1000).toFixed(0)}s\n`);

  const kpi = await jget('/out/daily_kpi.json');
  const findings = (await jget('/out/findings.json')).findings;
  const plan = await jget('/out/plan.json');

  // ---- extraction sanity
  check('job number 2053', String(kpi.job) === '2053', `got ${kpi.job}`);
  check('currency AUD', kpi.currency === 'AUD', `got ${kpi.currency}`);
  check('4 campaigns', kpi.campaigns.length === 4, `got ${kpi.campaigns.length}: ${kpi.campaigns.map((c) => c.campaign_name).join(' | ')}`);

  const budgets = kpi.campaigns.map((c) => c.total_budget).sort((a, b) => a - b);
  check('budgets 6000/7000/8000/14000', JSON.stringify(budgets) === JSON.stringify([6000, 7000, 8000, 14000]), `got ${budgets.join('/')}`);
  const total = kpi.campaigns.reduce((a, c) => a + c.total_budget, 0);
  check('total 35000', total === 35000, `got ${total}`);

  const ttd = kpi.campaigns.find((c) => /trade\s*desk|ttd|programmatic/i.test(`${c.platform} ${c.campaign_name}`));
  check('TradeDesk line is 8000', !!ttd && ttd.total_budget === 8000, ttd ? `got ${ttd.total_budget}` : 'no TradeDesk campaign found');

  const c0 = kpi.campaigns[0];
  check('flight 2026-06-01 to 2026-08-22', c0.start === '2026-06-01' && c0.end === '2026-08-22', `got ${c0.start} to ${c0.end}`);
  check('83 daily rows per campaign', kpi.campaigns.every((c) => c.daily.length === 83), `got ${kpi.campaigns.map((c) => c.daily.length).join('/')}`);

  const finals = kpi.campaigns.map((c) => c.daily[c.daily.length - 1].expected_spend_cum).sort((a, b) => a - b);
  check('final-day cumulatives exact', JSON.stringify(finals) === JSON.stringify([6000, 7000, 8000, 14000]), `got ${finals.join('/')}`);

  // ---- re-caught findings (must come from CODE, not the model)
  const label = findings.find((f) => f.origin === 'code' && /27,?000/.test(f.title) && /35,?000/.test(f.title));
  check('re-caught 35,000 vs 27,000 label (code)', !!label, label ? label.title : 'not found in code findings');
  const dur = findings.find((f) => f.origin === 'code' && /\b82\b/.test(f.title) && /\b83\b/.test(f.title));
  check('re-caught 82 vs 83 days (code)', !!dur, dur ? dur.title : 'not found in code findings');

  // ---- hygiene
  const allText = JSON.stringify({ kpi, findings, plan });
  check('no em/en dashes in outputs', !/[–—]/.test(allText));
  check('plan cites total budget', !!(plan.total_budget && plan.total_budget.citation && plan.total_budget.citation.file), plan.total_budget ? JSON.stringify(plan.total_budget.citation) : 'missing');

  const failed = checks.filter((c) => !c.ok);
  console.log(`\n${failed.length === 0 ? 'REGRESSION GREEN' : 'REGRESSION RED'}: ${checks.length - failed.length}/${checks.length} checks passed`);
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error('regression error:', e.message || e);
  process.exit(1);
});
