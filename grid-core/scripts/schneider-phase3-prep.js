#!/usr/bin/env node
// schneider-phase3-prep.js — run from grid-core/. Kept for audit (like
// cloudflare-config-commit.js / schneider-containment-v2.js).
//
// Phase 3 Schneider prep, per the phase prompt's carry-forward items (PHASE3_CLOUDFLARE_REPORT
// §9 "Not resolved" + §6.2): BEFORE Schneider can be re-validated,
//   (4) TTD spendMult must be 1 on every Schneider TTD row — raw_snowflake TTD COSTS is the
//       CLIENT-BILLED basis (§1 money finding; Airset cross-check $2,798 to 07-08 vs billed
//       $2,650), so the sheet-derived mults (2.5–3.0) would re-multiply an already-billed
//       figure on first sync (the exact §9 corruption).
//   (5) The three Software First EcoStruxure · Linkedin rows must carry their distinguishing
//       Objectives — VERIFIED ONLY here: the 2026-07-22 DB rebuild re-imported them from the
//       newer central-import.json which already carries Awareness / Retargeting 1 /
//       Consideration. This script asserts that and writes NOTHING if true.
//
// Writes go through db.updateCampaignField (the governed CONFIG path: whitelist + provenance
// in central_rows). Every write is read back; the script prints ALL CLEAN only when every
// read-back matches. It does NOT touch validated (stays false), the map, metrics columns,
// calc.js, or any non-Schneider row.

const db = require('../src/brain/db.js');

let failures = 0;

// ---- (4) spendMult = 1 on every Schneider TradeDesk row ----
console.log('========== TTD spendMult -> 1 (billed-basis COSTS feed) ==========\n');
const ttdRows = db.getCampaigns().filter(c => c.client === 'Schneider' && c.channel === 'TradeDesk' && !c.archivedAt);
if (ttdRows.length !== 8) { console.error(`EXPECTED 8 Schneider TTD rows, found ${ttdRows.length} — aborting before any write`); process.exit(1); }
for (const c of ttdRows) {
  const before = c.spendMult;
  const r = db.updateCampaignField(c.id, 'spendMult', 1, 'edit', {
    source: 'phase3-schneider-prep',
    filename: 'PHASE3_SCHNEIDER_REPORT.md',
    cellRef: 'TTD billed-basis rule (PHASE3_CLOUDFLARE_REPORT §1/§9)'
  });
  const after = db.getCampaign(c.id);
  const ok = r.ok && after.spendMult === 1;
  if (!ok) failures++;
  console.log(`${ok ? 'OK  ' : 'FAIL'}: ${c.name} · TradeDesk (${c.id})  spendMult ${before} -> ${after.spendMult}`);
}

// ---- (5) EcoStruxure LinkedIn objectives — VERIFY (no write expected) ----
console.log('\n========== EcoStruxure · Linkedin objectives (verify) ==========\n');
const eco = db.getCampaigns().filter(c => c.client === 'Schneider' && c.name === 'Software First EcoStruxure' && c.channel === 'Linkedin' && !c.archivedAt);
const want = ['Awareness', 'Retargeting 1', 'Consideration'];
const got = eco.map(c => c.objective).sort();
const ok = eco.length === 3 && JSON.stringify(got) === JSON.stringify([...want].sort());
if (!ok) failures++;
for (const c of eco) console.log(`  ${c.id}  objective=${JSON.stringify(c.objective)}  budget=${c.totalBudget}  end=${c.endDate}`);
console.log(`${ok ? 'OK  ' : 'FAIL'}: 3 rows with distinct objectives ${JSON.stringify(want)} — ${ok ? 'already correct (2026-07-22 rebuild import), nothing written' : 'MISMATCH, fix by hand'}`);

// ---- sanity: nothing else on Schneider was touched ----
console.log('\n========== Post-check: metrics + validation untouched ==========\n');
const se = db.getCampaigns().filter(c => c.client === 'Schneider' && !c.archivedAt);
const dirtyMetrics = se.filter(c => c.lastSyncedAt !== null || (c.metricsSource && c.metricsSource !== 'sheet-import'));
if (dirtyMetrics.length) { failures++; console.error('FAIL: unexpected metricsSource/lastSyncedAt on', dirtyMetrics.map(c => c.id)); }
else console.log('OK  : all 25 Schneider rows still metricsSource=sheet-import, lastSyncedAt=NULL');
const cfg = JSON.parse(require('fs').readFileSync('config/central-clients.json', 'utf8'));
const spec = cfg.clients.find(c => c.client === 'Schneider');
const specOk = spec && spec.validated === false && Array.isArray(spec.map) && spec.map.length === 0 && spec.source === 'raw';
if (!specOk) failures++;
console.log(`${specOk ? 'OK  ' : 'FAIL'}: central-clients.json Schneider — validated=false, map=[], source=raw`);

console.log(`\n========== ${failures === 0 ? 'ALL CLEAN' : failures + ' FAILURE(S) — read output above'} ==========`);
process.exit(failures === 0 ? 0 : 1);
