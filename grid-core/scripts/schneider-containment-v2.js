#!/usr/bin/env node
// schneider-containment-v2.js — run from grid-core/
// Fixes what v1 missed: restores spend values (import file keys are
// campaign/clientSpent, not name/clientSpend) and flips validated
// inside the nested .clients structure. Verifies by reading back.

const fs = require('fs');
const Database = require('better-sqlite3');

const DB_PATH = 'data/brain-historical.db';
const IMPORT_PATH = 'config/central-import.json';
const CLIENTS_PATH = 'config/central-clients.json';

const TARGETS = [
  { name: 'NEL',                   channel: 'TradeDesk' },
  { name: 'Water and Environment', channel: 'TradeDesk' },
  { name: 'Airset',                channel: 'TradeDesk' },
  { name: 'EBA',                   channel: 'TradeDesk' },
  { name: 'Advancing Energy T',    channel: 'Linkedin'  },
];

// ── open DB, discover column names (same discovery that worked in v1) ──
const db = new Database(DB_PATH);
const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(t => t.name);
const campTable = tables.find(t => /campaign/i.test(t));
if (!campTable) { console.error('No campaign table found:', tables.join(', ')); process.exit(1); }

const cols = db.pragma(`table_info(${campTable})`).map(c => c.name);
const pick = (...names) => names.find(n => cols.includes(n)) || null;
const C = {
  name:    pick('name', 'campaignName', 'campaign_name', 'campaign'),
  channel: pick('channel', 'platform'),
  media:   pick('mediaSpend', 'media_spend', 'mediaSpent'),
  client:  pick('clientSpend', 'client_spend', 'clientSpent'),
  imps:    pick('impressions', 'imps'),
  src:     pick('metricsSource', 'metrics_source'),
  sync:    pick('lastSyncedAt', 'last_synced_at'),
};
console.log('DB column mapping:', JSON.stringify(C), '\n');
if (!C.name || !C.channel || !C.media) { console.error('Column mapping failed. Columns:', cols.join(', ')); process.exit(1); }

// ── load import originals with the CORRECT keys ──
const raw = JSON.parse(fs.readFileSync(IMPORT_PATH, 'utf8'));
const importRows = Array.isArray(raw) ? raw : (raw.campaigns || raw.rows || []);
console.log(`Import file: ${importRows.length} rows\n`);

function findOriginal(t) {
  // import keys: campaign, channel, mediaSpend, clientSpent, impressions
  return importRows.find(r => r.campaign === t.name && r.channel === t.channel
    && (r.advertiser || '').toLowerCase().includes('schneider'));
}

// ── restore, then READ BACK and print actual DB state ──
console.log('========== RESTORING SPEND VALUES ==========\n');
let failures = 0;

const tx = db.transaction(() => {
  for (const t of TARGETS) {
    const orig = findOriginal(t);
    if (!orig) {
      console.error(`FAIL: ${t.name} · ${t.channel} — no matching row in import file`);
      failures++;
      continue;
    }

    const before = db.prepare(
      `SELECT ${C.media} AS m, ${C.client} AS c, ${C.src} AS s FROM ${campTable}
       WHERE ${C.name} = ? AND ${C.channel} = ?`
    ).get(t.name, t.channel);

    let sql = `UPDATE ${campTable} SET ${C.media} = ?, ${C.src} = 'sheet-import', ${C.sync} = NULL`;
    const params = [orig.mediaSpend];
    if (C.client) { sql += `, ${C.client} = ?`; params.push(orig.clientSpent); }
    if (C.imps && orig.impressions != null) { sql += `, ${C.imps} = ?`; params.push(orig.impressions); }
    sql += ` WHERE ${C.name} = ? AND ${C.channel} = ?`;
    params.push(t.name, t.channel);

    const res = db.prepare(sql).run(...params);

    // read back — print what is ACTUALLY in the DB now
    const after = db.prepare(
      `SELECT ${C.media} AS m, ${C.client} AS c, ${C.src} AS s, ${C.sync} AS y FROM ${campTable}
       WHERE ${C.name} = ? AND ${C.channel} = ?`
    ).get(t.name, t.channel);

    const ok = res.changes === 1 && after && Math.abs(after.m - orig.mediaSpend) < 0.01;
    if (!ok) failures++;
    console.log(`${ok ? 'OK  ' : 'FAIL'}: ${t.name} · ${t.channel}`);
    console.log(`      before: media=${before?.m}, client=${before?.c}, src=${before?.s}`);
    console.log(`      now:    media=${after?.m}, client=${after?.c}, src=${after?.s}, synced=${after?.y}\n`);
  }
});
tx();

// ── flip validated inside .clients (handles array or object) ──
console.log('========== DISABLING SCHNEIDER SYNC ==========\n');
const cRaw = JSON.parse(fs.readFileSync(CLIENTS_PATH, 'utf8'));
const container = cRaw.clients;
let flipped = false;

function isSchneider(entry, key) {
  const label = (entry?.name || entry?.client || key || '').toString().toLowerCase();
  return label.includes('schneider');
}

if (Array.isArray(container)) {
  for (const entry of container) {
    if (isSchneider(entry)) {
      console.log(`  ${entry.name || entry.client}: validated ${entry.validated} -> false`);
      entry.validated = false;
      flipped = true;
    }
  }
} else if (container && typeof container === 'object') {
  for (const [key, entry] of Object.entries(container)) {
    if (isSchneider(entry, key)) {
      console.log(`  ${key}: validated ${entry.validated} -> false`);
      entry.validated = false;
      flipped = true;
    }
  }
}

if (flipped) {
  fs.writeFileSync(CLIENTS_PATH, JSON.stringify(cRaw, null, 2) + '\n');
  // read back to verify
  const check = JSON.parse(fs.readFileSync(CLIENTS_PATH, 'utf8'));
  const cc = check.clients;
  const entries = Array.isArray(cc) ? cc : Object.entries(cc).map(([k, v]) => ({ key: k, ...v }));
  const schn = entries.filter(e => isSchneider(e, e.key));
  const allFalse = schn.length > 0 && schn.every(e => e.validated === false);
  console.log(`  Read-back: ${schn.length} Schneider entr${schn.length === 1 ? 'y' : 'ies'}, validated=false: ${allFalse ? 'CONFIRMED' : 'NOT CONFIRMED — check manually'}`);
  if (!allFalse) failures++;
} else {
  console.error('  FAIL: no Schneider entry found under .clients — printing structure for manual fix:');
  if (Array.isArray(container)) {
    console.error('  clients is an ARRAY. Entries:', container.map(e => e.name || e.client || '(unnamed)').join(', '));
  } else {
    console.error('  clients is an OBJECT. Keys:', Object.keys(container || {}).join(', '));
  }
  failures++;
}

db.close();

console.log(`\n========== ${failures === 0 ? 'ALL CLEAN' : failures + ' FAILURE(S) — read output above'} ==========`);
if (failures === 0) {
  console.log(`
Every value above was read back from the DB/file AFTER writing.
Next: node server.js, then re-run the curl check to see it through the API.`);
}
