#!/usr/bin/env node
/*
 * margin-anomaly-fix.js — STAGED correction for the two anomalous Schneider TTD
 * platform margins (Phase 4 item 3). Run from grid-core/.
 *
 *   node scripts/margin-anomaly-fix.js            # dry run (default): print current vs proposed, write NOTHING
 *   node scripts/margin-anomaly-fix.js --apply    # perform the writes (HUMAN APPROVAL REQUIRED FIRST)
 *
 * THE FINDING (full detail in PHASE4_REPORT.md item 3):
 *   EBA · TradeDesk                      platformMargin 0.9729
 *   Software First EcoStruxure · TradeDesk  platformMargin 0.843
 * Both are HAND-TYPED LITERALS in the agency sheet ('sample data/Central Updated.xlsx',
 * 'Live Campaigns' rows 65 / 71 — cell has no formula), imported verbatim by
 * build_central_import.js (its sanity check only rejects values outside 0..1).
 * They are inconsistent with (a) the agency's standard TTD margin 0.60-0.65, (b) every
 * other Schneider TTD row (all 0.60), and (c) the margin backed out of the sheet's own
 * media/billed figures at import vintage (EBA 0.6557, EcoStruxure 0.6708). The typed
 * values imply media costs of ~$233 / ~$408 against the billed figures — consistent with
 * a margin computed from a much earlier spend snapshot and never refreshed.
 *
 * PROPOSED VALUE: 0.60 for both (the agency's standard Schneider TTD margin; matches the
 * other 6 mapped Schneider TTD rows). Confirm with the sheet owner (Zhen) before --apply.
 *
 * Writes go through the GOVERNED path (db.updateCampaignField, scope 'edit') so
 * provenance lands in central_rows — unlike the direct-SQLite eae-dv360-fix.js.
 * Also patches config/central-import.json (the fresh-DB seed) so a rebuild does not
 * resurrect the anomalies — same durability rule as the Schneider spendMult patch
 * (PHASE3_SCHNEIDER §9). Every write is read back; prints ALL WRITES CLEAN only when
 * every read-back matches.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const db = require('../src/brain/db');

const APPLY = process.argv.includes('--apply');
const PROPOSED = 0.60;
const TARGETS = [
  { id: 'cmp-53b4975d5b6e', name: 'EBA', channel: 'TradeDesk', current: 0.9729 },
  { id: 'cmp-eaf93725e24e', name: 'Software First EcoStruxure', channel: 'TradeDesk', current: 0.843 },
];

console.log(`========== SCHNEIDER TTD MARGIN ANOMALY ${APPLY ? 'FIX (--apply)' : 'DRY RUN (no writes)'} ==========\n`);

let failures = 0;
for (const t of TARGETS) {
  const cur = db.getCampaign(t.id);
  if (!cur) { console.error(`FAIL: ${t.name} · ${t.channel} — id ${t.id} not found (DB rebuilt? re-check ids)`); failures++; continue; }
  const match = cur.name === t.name && Number(cur.platformMargin) === t.current;
  console.log(`${t.name} · ${cur.channel}  platformMargin ${cur.platformMargin} -> ${PROPOSED}` +
    (match ? '' : `  [WARN: row state differs from staging expectation (name=${cur.name}, PM=${cur.platformMargin})]`));
  if (!APPLY) continue;
  if (!match) { console.error('  REFUSING to write: row no longer matches the staged expectation — re-verify first.'); failures++; continue; }
  const r = db.updateCampaignField(t.id, 'platformMargin', PROPOSED, 'edit', {
    filename: 'scripts/margin-anomaly-fix.js',
    cellRef: 'PHASE4_REPORT.md item 3 — sheet-literal anomaly, human-approved standard TTD margin'
  });
  if (!r.ok) { console.error('  WRITE FAILED:', r.error); failures++; continue; }
  const after = db.getCampaign(t.id);
  const ok = Math.abs(Number(after.platformMargin) - PROPOSED) < 1e-9;
  console.log(`  read-back: platformMargin=${after.platformMargin} ${ok ? 'OK' : 'MISMATCH'}`);
  if (!ok) failures++;
}

// durable seed patch (fresh DB rebuilds re-import from central-import.json)
const IMPORT = path.join(__dirname, '..', 'config', 'central-import.json');
const snap = JSON.parse(fs.readFileSync(IMPORT, 'utf8'));
const seedRows = snap.filter(r => r.advertiser === 'Schneider' && /tradedesk/i.test(r.channel || '') &&
  (r.campaign === 'EBA' || r.campaign === 'Software First EcoStruxure'));
for (const r of seedRows) {
  console.log(`central-import.json: ${r.campaign} platformMargin ${r.platformMargin} -> ${PROPOSED}`);
  if (APPLY) r.platformMargin = PROPOSED;
}
if (APPLY) {
  fs.writeFileSync(IMPORT, JSON.stringify(snap, null, 2) + '\n');
  const check = JSON.parse(fs.readFileSync(IMPORT, 'utf8')).filter(r => r.advertiser === 'Schneider' &&
    /tradedesk/i.test(r.channel || '') && (r.campaign === 'EBA' || r.campaign === 'Software First EcoStruxure'));
  if (!check.every(r => r.platformMargin === PROPOSED)) { console.error('central-import.json read-back MISMATCH'); failures++; }
  else console.log('central-import.json read-back OK (' + check.length + ' rows)');
}

console.log(`\n========== ${APPLY ? (failures ? 'SEE FAILURES ABOVE' : 'ALL WRITES CLEAN') : 'DRY RUN COMPLETE — nothing written'} ==========`);
if (!APPLY) console.log('To apply after human sign-off: node scripts/margin-anomaly-fix.js --apply');
process.exit(failures ? 1 : 0);
