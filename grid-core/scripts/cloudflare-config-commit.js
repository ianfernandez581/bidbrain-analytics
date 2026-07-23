#!/usr/bin/env node
// cloudflare-config-commit.js — run from grid-core/
// Four targeted CONFIG writes for Cloudflare Phase 3 completion:
//   1. Coles DOOH AU · TradeDesk   → platformMargin = 0.60
//   2. Coles DOOH NZ · TradeDesk   → platformMargin = 0.60
//   3. Coles Prog · TradeDesk      → platformMargin = 0.60
//   4. Q2 PubSec · LinkedIn        → budget/dates/objective seed
//
// Rules: writes only to CONFIG columns; every write read back from the DB
// after commit; script reports FAIL if any read-back disagrees.

const fs = require('fs');
const Database = require('better-sqlite3');

const DB_PATH = 'data/brain-historical.db';

// Writes: {name, channel, updates: {col: value}}
const WRITES = [
  {
    name: 'Coles DOOH AU',
    channel: 'TradeDesk',
    updates: { platformMargin: 0.60 },
  },
  {
    name: 'Coles DOOH NZ',
    channel: 'TradeDesk',
    updates: { platformMargin: 0.60 },
  },
  {
    name: 'Coles Prog',
    channel: 'TradeDesk',
    updates: { platformMargin: 0.60 },
  },
  {
    name: 'Q2 PubSec',
    channel: 'Linkedin',
    updates: {
      // From report §1 (VER-PUBSEC BQ orphan = $1,225) + Q2 Core DG scope
      totalBudget: 1225,
      startDate: '2026-04-01',
      endDate:   '2026-06-30',
      objective: 'Site Traffic / LGF',
      status:    'Ended',       // Q2 rows are Ended per Central sheet
      platformMargin: 0,        // LinkedIn — Campaign Margin rule; PlatMargin not applicable
    },
  },
];

// ── open DB, discover column names ──
const db = new Database(DB_PATH);
const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(t => t.name);
const campTable = tables.find(t => /campaign/i.test(t));
if (!campTable) { console.error('No campaign table found.'); process.exit(1); }

const cols = db.pragma(`table_info(${campTable})`).map(c => c.name);
const pick = (...names) => names.find(n => cols.includes(n)) || null;

// Column mapping — many possible schemas, we discover the actual names
const C = {
  name:           pick('name', 'campaignName', 'campaign_name', 'campaign'),
  channel:        pick('channel', 'platform'),
  platformMargin: pick('platformMargin', 'platform_margin', 'platMargin'),
  totalBudget:    pick('totalBudget', 'total_budget'),
  budgetGross:    pick('budgetGross', 'budget_gross'),
  startDate:      pick('startDate', 'start_date', 'start'),
  endDate:        pick('endDate', 'end_date', 'end'),
  objective:      pick('objective'),
  status:         pick('status'),
  client:         pick('client', 'advertiser'),
};
console.log('DB column mapping:', JSON.stringify(C, null, 2), '\n');

// ── check Q2 PubSec exists (added tonight — may or may not be present) ──
const pubsec = db.prepare(
  `SELECT * FROM ${campTable} WHERE ${C.name} = ? AND ${C.channel} = ?`
).get('Q2 PubSec', 'Linkedin') || db.prepare(
  `SELECT * FROM ${campTable} WHERE ${C.name} = ? AND ${C.channel} = ?`
).get('Q2 PubSec', 'LinkedIn');

if (!pubsec) {
  console.warn('WARN: Q2 PubSec · LinkedIn row NOT found in DB.');
  console.warn('      You said tonight you added it via the reconcile panel.');
  console.warn('      If it was only added as a MAP entry (not a Central row), it may not exist yet.');
  console.warn('      Skipping PubSec seed — do the other 3 margins only? [proceeding, PubSec will be logged as skipped]\n');
} else {
  console.log(`Q2 PubSec found: id=${pubsec.id || pubsec.campaignId || '(no id col)'} current status=${pubsec.status}\n`);
}

// ── commit each row ──
console.log('========== 4 CONFIG WRITES ==========\n');
let failures = 0;
let skipped = 0;

const tx = db.transaction(() => {
  for (const w of WRITES) {
    // find row (try both channel spellings)
    let cur = db.prepare(
      `SELECT * FROM ${campTable} WHERE ${C.name} = ? AND ${C.channel} = ?`
    ).get(w.name, w.channel);
    if (!cur && w.channel === 'Linkedin') {
      cur = db.prepare(
        `SELECT * FROM ${campTable} WHERE ${C.name} = ? AND ${C.channel} = ?`
      ).get(w.name, 'LinkedIn');
    }
    if (!cur) {
      console.warn(`SKIP: ${w.name} · ${w.channel} — row not found in DB`);
      skipped++;
      continue;
    }

    // build SET clause using discovered column names
    const setParts = [];
    const params = [];
    for (const [logical, value] of Object.entries(w.updates)) {
      const dbCol = C[logical];
      if (!dbCol) {
        console.warn(`  WARN: no DB column for logical field '${logical}' — skipping this field`);
        continue;
      }
      setParts.push(`${dbCol} = ?`);
      params.push(value);
    }
    if (setParts.length === 0) {
      console.warn(`SKIP: ${w.name} · ${w.channel} — no writable fields`);
      skipped++;
      continue;
    }

    // where clause matches by name + channel exactly as we found it
    const sql = `UPDATE ${campTable} SET ${setParts.join(', ')} WHERE ${C.name} = ? AND ${C.channel} = ?`;
    params.push(w.name, cur[C.channel]); // use the channel spelling we found
    const res = db.prepare(sql).run(...params);

    // read back
    const after = db.prepare(
      `SELECT * FROM ${campTable} WHERE ${C.name} = ? AND ${C.channel} = ?`
    ).get(w.name, cur[C.channel]);

    // verify each field written matches
    let ok = res.changes === 1;
    const mismatches = [];
    for (const [logical, expected] of Object.entries(w.updates)) {
      const dbCol = C[logical];
      if (!dbCol) continue;
      const actual = after[dbCol];
      // numeric tolerance for margin/budget
      if (typeof expected === 'number' && typeof actual === 'number') {
        if (Math.abs(actual - expected) > 0.0001) {
          ok = false;
          mismatches.push(`${logical}: wrote ${expected} but reads ${actual}`);
        }
      } else if (String(actual) !== String(expected)) {
        // dates may come back as ISO strings — accept those
        if (!(typeof expected === 'string' && String(actual).startsWith(expected))) {
          ok = false;
          mismatches.push(`${logical}: wrote ${JSON.stringify(expected)} but reads ${JSON.stringify(actual)}`);
        }
      }
    }
    if (!ok) failures++;

    console.log(`${ok ? 'OK  ' : 'FAIL'}: ${w.name} · ${cur[C.channel]}`);
    for (const [logical, expected] of Object.entries(w.updates)) {
      const dbCol = C[logical];
      const before = cur[dbCol];
      const now = after[dbCol];
      console.log(`      ${logical.padEnd(16)} ${JSON.stringify(before)} → ${JSON.stringify(now)}`);
    }
    if (mismatches.length) {
      for (const m of mismatches) console.log(`      MISMATCH: ${m}`);
    }
    console.log();
  }
});
tx();

db.close();

// ── summary ──
console.log(`========== ${failures === 0 ? 'ALL WRITES CLEAN' : failures + ' FAILURE(S)'} ==========`);
console.log(`  Wrote:   ${WRITES.length - skipped - failures}`);
console.log(`  Skipped: ${skipped}`);
console.log(`  Failed:  ${failures}`);
console.log();
if (failures === 0 && skipped === 0) {
  console.log('Every value above was read back from the DB after writing.');
  console.log('Next: restart server, verify the 3 Coles TTD rows now show 0.60 platform margin');
  console.log('      and Q2 PubSec has a real budget + dates.');
}
