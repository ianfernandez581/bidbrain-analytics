#!/usr/bin/env node
/**
 * reconcile.js — the FIRST thing to run once real credentials go in.
 *
 * The dangerous class of bug in a budget tool isn't "no data" (that errors
 * loudly) — it's a silently WRONG number: cost_micros not divided, Reddit spend
 * in the wrong unit, a currency mismatch. Those pass every "did it return data?"
 * check and quietly corrupt the pacing math people make decisions on.
 *
 * This harness catches every scaling/units error at once by comparing, per
 * platform, ONE campaign's pulled spend/impressions against a figure you read
 * straight off the platform UI. If they don't match within tolerance, it tells
 * you exactly which field and by what ratio (a clean 1,000,000x or 100x ratio is
 * an instant "units" smoking gun).
 *
 * Usage:
 *   node reconcile.js --expected expected.json [--env .env] [--asof 2026-06-26]
 *
 * expected.json (you fill this from the platform dashboards):
 *   {
 *     "asOf": "2026-06-26",
 *     "window": { "start": "2026-06-01", "end": "2026-06-30" },
 *     "checks": [
 *       { "source": "google", "campaign": "Always On",
 *         "spend": 34953.10, "impressions": 2490816, "tolerancePct": 0.5 }
 *     ]
 *   }
 *
 * It also re-derives pacing from the pulled raw values and shows the computed
 * pctSpent / pctElapsed / pacingStatus so you can eyeball the derived layer too.
 */

'use strict';

// ---------------- PHASE 1 KILL SWITCH ----------------
// This harness computed with src/derive.js, which is QUARANTINED (src/_retired/):
// the single engine is now src/central/calc.js and the old-vs-new safety net is
// scripts/compare_pulse_paths.js. Nothing may import derive.js, so this CLI exits
// loudly instead of crashing on a missing module. Phase 4 decides its final fate.
console.error('[reconcile] RETIRED in Phase 1 - derive.js is quarantined. Use scripts/compare_pulse_paths.js (old-vs-new diff) or src/central/calc.js directly.');
process.exit(1);

const fs = require('fs');
const path = require('path');
const { fetchLiveCampaigns } = require('./orchestrator');
// (retired) const D = require('./derive'); — quarantined in src/_retired/; the stub
// below keeps the dead code beneath syntactically alive until Phase 4 deletes it.
const D = null;

function parseArgs(argv) {
  const a = { env: '.env', expected: null, asof: null };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--env') a.env = argv[++i];
    else if (k === '--expected') a.expected = argv[++i];
    else if (k === '--asof') a.asof = argv[++i];
    else if (k === '--help') a.help = true;
  }
  return a;
}

function loadEnv(file) {
  const env = { ...process.env };
  try {
    const txt = fs.readFileSync(file, 'utf8');
    for (const line of txt.split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  } catch { /* no .env — connectors will report NOT CONFIGURED */ }
  return env;
}

function ratioFlag(pulled, expected) {
  if (!expected || pulled == null) return '';
  const r = pulled / expected;
  // classic units smells
  for (const [f, name] of [[1e6, '÷1e6 (micros)'], [100, '÷100 (cents)'], [1000, '÷1000'], [1 / 1e6, '×1e6'], [1 / 100, '×100']]) {
    if (Math.abs(r - f) / f < 0.02) return `  ⚠ ratio≈${r.toExponential(2)} → likely ${name}`;
  }
  return `  (ratio ${r.toFixed(4)})`;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help || !args.expected) {
    console.log('Usage: node reconcile.js --expected expected.json [--env .env] [--asof YYYY-MM-DD]');
    process.exit(args.help ? 0 : 1);
  }
  const env = loadEnv(args.env);
  const spec = JSON.parse(fs.readFileSync(path.resolve(args.expected), 'utf8'));
  const asOf = args.asof || spec.asOf || null;
  const { start, end } = spec.window;
  const only = [...new Set(spec.checks.map(c => c.source))];

  console.log(`\nReconciling ${spec.checks.length} campaign(s) · window ${start}..${end} · asOf ${asOf || 'now'}\n`);

  const { rows, status } = await fetchLiveCampaigns({ env, start, end, only, asOf });

  let pass = 0, fail = 0;
  for (const chk of spec.checks) {
    const st = status[chk.source];
    if (!st || !st.ok) {
      console.log(`✗ ${chk.source} · ${chk.campaign}`);
      console.log(`    connector not GREEN (stage=${st?.stage}): ${st?.message || 'unknown'}\n`);
      fail++; continue;
    }
    const match = rows.find(r => r.sourceKey === chk.source &&
      (r.campaign || '').toLowerCase().includes((chk.campaign || '').toLowerCase()));
    if (!match) {
      console.log(`✗ ${chk.source} · ${chk.campaign} — campaign not found in pulled rows\n`);
      fail++; continue;
    }
    const tol = (chk.tolerancePct ?? 0.5) / 100;
    const checks = [];
    if (chk.spend != null) {
      const ok = Math.abs((match.clientSpent ?? match.mediaSpend) - chk.spend) <= chk.spend * tol;
      checks.push(['spend', match.clientSpent ?? match.mediaSpend, chk.spend, ok]);
    }
    if (chk.impressions != null) {
      const ok = Math.abs(match.impressions - chk.impressions) <= chk.impressions * tol;
      checks.push(['impressions', match.impressions, chk.impressions, ok]);
    }
    const allOk = checks.every(c => c[3]);
    console.log(`${allOk ? '✓' : '✗'} ${chk.source} · ${match.campaign}`);
    for (const [field, pulled, exp, ok] of checks) {
      console.log(`    ${field.padEnd(11)} pulled=${fmt(pulled)}  expected=${fmt(exp)}  ${ok ? 'OK' : 'MISMATCH'}${ok ? '' : ratioFlag(pulled, exp)}`);
    }
    // show the derived layer for a human sanity check
    console.log(`    derived     pctSpent=${pctf(match.pctSpent)}  pctElapsed=${pctf(match.pctElapsed)}  pacing=${match.pacingStatus?.toFixed(2) ?? '—'} (${match.paceState})\n`);
    allOk ? pass++ : fail++;
  }

  console.log(`Result: ${pass} passed, ${fail} failed.`);
  process.exit(fail ? 1 : 0);
}

const fmt = n => n == null ? '—' : (Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 2 }));
const pctf = n => n == null ? '—' : (n * 100).toFixed(1) + '%';

main().catch(e => { console.error('reconcile error:', e); process.exit(1); });
