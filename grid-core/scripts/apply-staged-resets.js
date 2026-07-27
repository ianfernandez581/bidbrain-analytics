#!/usr/bin/env node
/*
 * apply-staged-resets.js — apply ONE client's staged spendMult resets (and optional
 * staged config writes) from config/reconcile-staged/<Client>.json, through the
 * GOVERNED path. Run from grid-core/:
 *
 *   node scripts/apply-staged-resets.js <Client>            # dry run (default)
 *   node scripts/apply-staged-resets.js <Client> --apply    # write
 *
 * Used by the Mission-1 batch approval run (2026-07-28). Per the runbook the resets
 * MUST land before the client's pairs are approved (the approve click arms the sync;
 * a surviving sheet mult would write clientSpend at a multiple of billed).
 *
 * What it does per staged reset {campaignId, campaignName, channel, from, to}:
 *   1. DB write via db.updateCampaignField (scope 'edit', provenance in central_rows) —
 *      REFUSES if the row's current spendMult doesn't match the staged `from`
 *      (protects against double-apply and drifted state); read-back verified.
 *   2. Durability: patches the same row in config/central-import.json (the fresh-DB
 *      seed) so a rebuild cannot resurrect the artifact mult — same rule as the
 *      Schneider §9 addendum + margin-anomaly-fix.
 * Also applies optional staged `configWrites` [{campaignId, field, value, reason}]
 * (e.g. a platformMargin a staged warning says must be set) through the same path —
 * DB only (import patch only for spendMult/platformMargin rows that exist there).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const db = require('../src/brain/db');

const CLIENT = process.argv[2];
const APPLY = process.argv.includes('--apply');
if (!CLIENT) { console.error('usage: node scripts/apply-staged-resets.js <Client> [--apply]'); process.exit(2); }

const STAGED = path.join(__dirname, '..', 'config', 'reconcile-staged', path.basename(CLIENT) + '.json');
const IMPORT = path.join(__dirname, '..', 'config', 'central-import.json');
const staged = JSON.parse(fs.readFileSync(STAGED, 'utf8'));
const resets = staged.spendMultResets || [];
const configWrites = staged.configWrites || [];
const normCh = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');

console.log(`========== ${CLIENT} staged resets ${APPLY ? '(--apply)' : '(DRY RUN — no writes)'} ==========`);
let failures = 0;

// ---- 1. spendMult resets via the governed path ----
for (const r of resets) {
  const cur = db.getCampaign(r.campaignId);
  if (!cur) { console.error(`FAIL: ${r.campaignName} — id ${r.campaignId} not found (DB rebuilt?)`); failures++; continue; }
  const curMult = cur.spendMult == null ? null : Number(cur.spendMult);
  const expect = r.from == null ? null : Number(r.from);
  const already = curMult != null && Number(curMult) === Number(r.to);
  if (already) { console.log(`SKIP (already ${r.to}): ${cur.name} · ${cur.channel}`); continue; }
  if (String(curMult) !== String(expect)) {
    console.error(`REFUSE: ${cur.name} · ${cur.channel} spendMult is ${curMult}, staged expected ${expect} — re-verify before applying`);
    failures++; continue;
  }
  console.log(`${cur.name} · ${cur.channel}  spendMult ${curMult} -> ${r.to}  (${r.reason || 'staged'})`);
  if (!APPLY) continue;
  const w = db.updateCampaignField(r.campaignId, 'spendMult', r.to, 'edit', {
    filename: 'config/reconcile-staged/' + path.basename(CLIENT) + '.json',
    cellRef: r.reason || 'staged spendMult reset (batch approval)'
  });
  if (!w.ok) { console.error('  WRITE FAILED: ' + w.error); failures++; continue; }
  const after = db.getCampaign(r.campaignId);
  if (Number(after.spendMult) !== Number(r.to)) { console.error('  READ-BACK MISMATCH'); failures++; }
  else console.log('  read-back OK');
}

// ---- 2. optional staged config writes (platformMargin etc.) ----
for (const c of configWrites) {
  const cur = db.getCampaign(c.campaignId);
  if (!cur) { console.error(`FAIL configWrite: id ${c.campaignId} not found`); failures++; continue; }
  console.log(`${cur.name} · ${cur.channel}  ${c.field} ${cur[c.field]} -> ${c.value}  (${c.reason || 'staged'})`);
  if (!APPLY) continue;
  const w = db.updateCampaignField(c.campaignId, c.field, c.value, 'edit', {
    filename: 'config/reconcile-staged/' + path.basename(CLIENT) + '.json',
    cellRef: c.reason || 'staged config write (batch approval)'
  });
  if (!w.ok) { console.error('  WRITE FAILED: ' + w.error); failures++; continue; }
  const after = db.getCampaign(c.campaignId);
  if (String(after[c.field]) !== String(c.value)) { console.error('  READ-BACK MISMATCH'); failures++; }
  else console.log('  read-back OK');
}

// ---- 3. durability: patch central-import.json for the reset rows ----
const snap = JSON.parse(fs.readFileSync(IMPORT, 'utf8'));
let patched = 0;
for (const r of resets) {
  const cur = db.getCampaign(r.campaignId);
  const rows = snap.filter(x => x.advertiser === (staged.client || CLIENT) &&
    x.campaign === (r.campaignName || (cur && cur.name)) && normCh(x.channel) === normCh(r.channel || (cur && cur.channel)));
  if (!rows.length) { console.log(`import: no row for ${r.campaignName} · ${r.channel} (scan-sourced or renamed — DB write still governs)`); continue; }
  for (const row of rows) {
    console.log(`import: ${row.campaign} · ${row.channel} spendMult ${row.spendMult} -> ${r.to}`);
    if (APPLY) { row.spendMult = r.to; patched++; }
  }
}
if (APPLY && patched) {
  fs.writeFileSync(IMPORT, JSON.stringify(snap, null, 2) + '\n');
  console.log(`central-import.json written (${patched} row(s) patched)`);
}

console.log(`========== ${APPLY ? (failures ? 'FAILURES — see above' : 'ALL WRITES CLEAN') : 'dry run complete'} ==========`);
process.exit(failures ? 1 : 0);
