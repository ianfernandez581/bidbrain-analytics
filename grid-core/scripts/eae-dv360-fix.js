#!/usr/bin/env node
// eae-dv360-fix.js — run from grid-core/
// Post-approval follow-up for Schneider Phase 3:
//   - EAE Consideration · DV360   → spendMult=1, platformMargin=0.60
//   - EAE Conversion   · DV360    → spendMult=1, platformMargin=0.60
//
// Why: DV360 REVENUE_ADV_CURRENCY is client-billed (same basis as TTD COSTS).
// Without spendMult=1, the sheet-derived spendMult would double-count on top
// of an already-billed figure — the same landmine as Schneider TTD.
// The 60% platform margin follows the standard DV360 rule.

const Database = require('better-sqlite3');
const db = new Database('data/brain-historical.db');

const WRITES = [
  { name: 'EAE Consideration', channel: 'DV360', platformMargin: 0.60, spendMult: 1 },
  { name: 'EAE Conversion',    channel: 'DV360', platformMargin: 0.60, spendMult: 1 },
];

console.log('========== EAE DV360 POST-APPROVAL FIX ==========\n');

let failures = 0;
let skipped = 0;

const tx = db.transaction(() => {
  for (const w of WRITES) {
    // find row — try DV360, dv360, DV 360 variants
    let cur = db.prepare(
      `SELECT id, name, channel, platformMargin, spendMult FROM campaigns
       WHERE name = ? AND channel = ?`
    ).get(w.name, w.channel);

    if (!cur) {
      // try common casings
      for (const alt of ['dv360', 'DV 360', 'Dv360']) {
        cur = db.prepare(
          `SELECT id, name, channel, platformMargin, spendMult FROM campaigns
           WHERE name = ? AND channel = ?`
        ).get(w.name, alt);
        if (cur) break;
      }
    }

    if (!cur) {
      console.warn(`SKIP: ${w.name} · ${w.channel} — row not found in DB`);
      console.warn(`      (tried channel spellings: DV360, dv360, DV 360, Dv360)`);
      skipped++;
      continue;
    }

    const res = db.prepare(
      `UPDATE campaigns
       SET platformMargin = ?, spendMult = ?
       WHERE name = ? AND channel = ?`
    ).run(w.platformMargin, w.spendMult, w.name, cur.channel);

    // read back
    const after = db.prepare(
      `SELECT name, channel, platformMargin, spendMult FROM campaigns
       WHERE name = ? AND channel = ?`
    ).get(w.name, cur.channel);

    const ok = res.changes === 1
      && Math.abs(after.platformMargin - w.platformMargin) < 0.0001
      && Math.abs(after.spendMult - w.spendMult) < 0.0001;
    if (!ok) failures++;

    console.log(`${ok ? 'OK  ' : 'FAIL'}: ${w.name} · ${cur.channel}`);
    console.log(`      platformMargin: ${cur.platformMargin} → ${after.platformMargin}`);
    console.log(`      spendMult:      ${cur.spendMult} → ${after.spendMult}`);
    console.log();
  }
});
tx();

db.close();

console.log(`========== ${failures === 0 && skipped === 0 ? 'ALL WRITES CLEAN' : 'SEE ABOVE'} ==========`);
console.log(`  Wrote:   ${WRITES.length - skipped - failures}`);
console.log(`  Skipped: ${skipped}`);
console.log(`  Failed:  ${failures}`);
if (failures === 0 && skipped === 0) {
  console.log('\nEvery value read back from the DB after writing.');
  console.log('Next: run the includeEnded sync so the EAE Ended rows get their first BQ pull.');
}
