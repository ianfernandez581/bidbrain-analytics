#!/usr/bin/env node
// api-probe — read-only reporting-access diagnostic for our ad platforms.
// Runs every connector's fetchReport(), then prints a status table + a
// GREEN/YELLOW/RED readiness summary + setup notes for anything unconfigured.
//
// Usage:
//   node index.js                 run all configured platforms
//   node index.js --only meta      run just one (matches the platform slug)
//   node index.js --json           machine-readable output
//   node index.js --verbose        include raw provider error detail
//   node index.js --env path/.env  use a specific env file (default ./.env)
//
// Exit code is non-zero if any platform is RED (useful in CI); NOT CONFIGURED
// alone never fails the run.

import { loadEnv } from './lib/env.js';
import { ProbeError } from './lib/errors.js';
import { c, renderTable } from './lib/table.js';

import * as googleAds from './connectors/google-ads.js';
import * as meta from './connectors/meta.js';
import * as linkedin from './connectors/linkedin.js';
import * as reddit from './connectors/reddit.js';
import * as tradeDesk from './connectors/trade-desk.js';
import * as dv360 from './connectors/dv360.js';

const CONNECTORS = [googleAds, meta, linkedin, reddit, tradeDesk, dv360];

// ── CLI args ────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const opt = (name, def) => {
  const i = argv.indexOf(name);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : def;
};
if (flag('--help') || flag('-h')) {
  console.log(
    'api-probe — read-only ad-platform reporting diagnostic\n\n' +
      '  --only <slug>   run one platform (google-ads|meta|linkedin|reddit|trade-desk|dv360)\n' +
      '  --json          machine-readable output\n' +
      '  --verbose       include raw provider error detail\n' +
      '  --env <path>    env file to load (default ./.env)\n' +
      '  --no-color      disable ANSI colour (or set NO_COLOR=1)\n'
  );
  process.exit(0);
}
const asJson = flag('--json');
const verbose = flag('--verbose');
const only = opt('--only', null);
const envPath = opt('--env', '.env');

const slug = (name) =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

// ── date window: last 7 full days (UTC), yyyy-mm-dd ──────────────────────────
function ymd(d) {
  return d.toISOString().slice(0, 10);
}
const today = new Date();
const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
const start = new Date(end);
start.setUTCDate(start.getUTCDate() - 7);
const WINDOW = { start: ymd(start), end: ymd(end) };

// ── classification ───────────────────────────────────────────────────────────
// status ∈ NOT_CONFIGURED | GREEN | YELLOW | RED
function classify(mod, outcome) {
  if (outcome.notConfigured) {
    return { status: 'NOT_CONFIGURED', authOk: null, dataOk: null, error: 'missing credentials' };
  }
  if (outcome.ok) {
    const rows = outcome.rows;
    if (rows.length > 0) {
      return { status: 'GREEN', authOk: true, dataOk: true, error: '', rows };
    }
    return {
      status: 'YELLOW',
      authOk: true,
      dataOk: false,
      error: 'authenticated, but the report returned 0 rows (no spend in window?)',
      rows,
    };
  }
  // an error was thrown
  const err = outcome.error;
  if (err instanceof ProbeError) {
    const map = {
      auth: { status: 'RED', authOk: false, dataOk: false },
      scope: { status: 'YELLOW', authOk: true, dataOk: false },
      data: { status: 'YELLOW', authOk: true, dataOk: false },
      enablement: { status: 'RED', authOk: true, dataOk: false },
    };
    const base = map[err.stage] || map.data;
    return { ...base, error: err.message, stage: err.stage, hint: err.hint, detail: err.detail };
  }
  // unexpected (bug / non-ProbeError) — treat as RED, auth unknown
  return {
    status: 'RED',
    authOk: null,
    dataOk: false,
    error: `unexpected: ${err?.message || err}`,
    detail: err?.stack,
  };
}

// ── run one connector ─────────────────────────────────────────────────────────
async function probe(mod, env) {
  if (!mod.isConfigured(env)) {
    return { mod, ...classify(mod, { notConfigured: true }) };
  }
  const t0 = Date.now();
  try {
    const rows = await mod.fetchReport({ env, start: WINDOW.start, end: WINDOW.end });
    return { mod, ...classify(mod, { ok: true, rows: rows || [] }), ms: Date.now() - t0 };
  } catch (error) {
    return { mod, ...classify(mod, { error }), ms: Date.now() - t0 };
  }
}

// ── presentation helpers ──────────────────────────────────────────────────────
const MARK = { yes: c('green', '✓'), no: c('red', '✗'), na: c('gray', '—'), warn: c('yellow', '✗') };
function authCell(r) {
  if (r.authOk === null) return MARK.na;
  return r.authOk ? MARK.yes : MARK.no;
}
function dataCell(r) {
  if (r.dataOk === null) return MARK.na;
  if (r.dataOk) return MARK.yes;
  return r.status === 'RED' ? MARK.no : MARK.warn;
}
function truncate(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
const STATUS_COLOR = { GREEN: 'green', YELLOW: 'yellow', RED: 'red', NOT_CONFIGURED: 'gray' };
function paintStatus(status) {
  return c(STATUS_COLOR[status], status.replace('_', ' '));
}

// ── main ──────────────────────────────────────────────────────────────────────
const { vars: env, fileFound } = loadEnv(envPath);

let selected = CONNECTORS;
if (only) {
  selected = CONNECTORS.filter((m) => slug(m.platform).includes(only.toLowerCase()));
  if (selected.length === 0) {
    console.error(`No platform matches --only "${only}".`);
    process.exit(2);
  }
}

const results = await Promise.all(selected.map((m) => probe(m, env)));

// exit non-zero if anything is RED (CI signal); set here, applied at the end.
// NOTE: we intentionally never call process.exit() — an abrupt exit while
// fetch/undici handles are still closing trips a libuv assertion on Windows.
// Setting process.exitCode and letting the event loop drain is the safe way.
process.exitCode = results.some((r) => r.status === 'RED') ? 1 : 0;

// ── JSON mode ──
if (asJson) {
  const out = results.map((r) => ({
    platform: r.mod.platform,
    slug: slug(r.mod.platform),
    status: r.status,
    authOk: r.authOk,
    dataOk: r.dataOk,
    stage: r.stage || null,
    error: r.error || null,
    hint: r.hint || null,
    rows: r.rows ? r.rows.length : 0,
    sample: r.rows && r.rows[0] ? r.rows[0] : null,
    ms: r.ms ?? null,
  }));
  console.log(JSON.stringify({ window: WINDOW, envFile: fileFound ? envPath : null, results: out }, null, 2));
} else {
  printHuman();
}

function printHuman() {
// ── human output ──
console.log('');
console.log(c('bold', 'api-probe') + c('gray', `  — read-only reporting access · window ${WINDOW.start} → ${WINDOW.end}`));
if (!fileFound) {
  console.log(c('yellow', `  ⚠ no env file at "${envPath}" — every platform will read as NOT CONFIGURED.`));
  console.log(c('gray', '    copy .env.example → .env and fill in what you can.'));
}
console.log('');

const table = renderTable(
  ['PLATFORM', 'AUTH OK?', 'DATA OK?', 'STATUS', 'ERROR'],
  results.map((r) => [
    r.mod.platform,
    authCell(r),
    dataCell(r),
    paintStatus(r.status),
    r.status === 'GREEN' ? c('gray', 'ready') : truncate(r.error, 64),
  ])
);
console.log(table);
console.log('');

// per-platform detail: hints, and (verbose) raw provider detail
for (const r of results) {
  if (r.status === 'GREEN') {
    const s = r.rows[0];
    console.log(
      `  ${c('green', '●')} ${c('bold', r.mod.platform)} — ` +
        c('gray', `${r.rows.length} row(s); e.g. "${truncate(s.campaign, 30)}" spend=${s.spend} imps=${s.impressions}`)
    );
    continue;
  }
  if (r.status === 'NOT_CONFIGURED') continue;
  const dot = r.status === 'RED' ? c('red', '●') : c('yellow', '●');
  console.log(`  ${dot} ${c('bold', r.mod.platform)} — ${r.error}`);
  if (r.hint) console.log(c('gray', `      → ${r.hint}`));
  if (verbose && r.detail) console.log(c('dim', `      ${truncate(r.detail, 300)}`));
}

// ── readiness summary ──
const bucket = (s) => results.filter((r) => r.status === s).map((r) => r.mod.platform);
const green = bucket('GREEN');
const yellow = bucket('YELLOW');
const red = bucket('RED');
const notConf = bucket('NOT_CONFIGURED');

console.log('');
console.log(c('bold', 'Readiness'));
console.log(`  ${c('green', 'GREEN ')} ready ................. ${green.length ? green.join(', ') : c('gray', 'none')}`);
console.log(`  ${c('yellow', 'YELLOW')} auth ok, no data/scope . ${yellow.length ? yellow.join(', ') : c('gray', 'none')}`);
console.log(`  ${c('red', 'RED   ')} blocked / needs enable . ${red.length ? red.join(', ') : c('gray', 'none')}`);
console.log(`  ${c('gray', 'GRAY  ')} not configured ......... ${notConf.length ? notConf.join(', ') : c('gray', 'none')}`);

// ── setup instructions for anything unconfigured ──
if (notConf.length) {
  console.log('');
  console.log(c('bold', 'Setup instructions for NOT CONFIGURED platforms'));
  for (const r of results.filter((x) => x.status === 'NOT_CONFIGURED')) {
    const missing = r.mod.requiredEnv.filter((k) => !env[k]);
    console.log('');
    console.log(c('blue', `  ${r.mod.platform}`) + c('gray', `  (missing: ${missing.join(', ')})`));
    console.log(
      r.mod.setup
        .split('\n')
        .map((l) => '  ' + l)
        .join('\n')
    );
  }
}
console.log('');
} // end printHuman()
