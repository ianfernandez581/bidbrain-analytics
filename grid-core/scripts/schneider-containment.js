#!/usr/bin/env node
// schneider-containment.js — run from grid-core/
// Restores 5 Schneider rows that synced through a broken Mode-A map
// and disables Schneider's validated flag so the next sync skips it.
//
// Usage: node scripts/schneider-containment.js [optional-path-to-db]

const fs = require('fs');
const path = require('path');

// The 5 rows that synced (from the curl spot-check)
const TARGETS = [
  { name: 'NEL',                     channel: 'TradeDesk' },
  { name: 'Water and Environment',   channel: 'TradeDesk' },
  { name: 'Airset',                  channel: 'TradeDesk' },
  { name: 'EBA',                     channel: 'TradeDesk' },
  { name: 'Advancing Energy T',      channel: 'Linkedin'  },
];

// ──────────────────────────────────────────────
// 1. Find the SQLite database
// ──────────────────────────────────────────────
let dbPath = process.argv[2] || null;
if (!dbPath) {
  const candidates = [
    'data/grid.db', 'grid.db', 'data/central.db', 'central.db',
    'data/the-grid.db', 'the-grid.db', 'data/campaigns.db',
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) { dbPath = c; break; }
  }
}
if (!dbPath) {
  // Broader search — one level into common dirs
  for (const dir of ['.', 'data', 'config', 'db']) {
    try {
      for (const f of fs.readdirSync(dir)) {
        if (/\.(db|sqlite3?)$/.test(f)) { dbPath = path.join(dir, f); break; }
      }
    } catch {}
    if (dbPath) break;
  }
}
if (!dbPath || !fs.existsSync(dbPath)) {
  console.error('ERROR: Cannot find the SQLite database.');
  console.error('Find it: Get-ChildItem -Recurse -Include "*.db" | Select FullName');
  console.error('Then:    node scripts/schneider-containment.js <path>');
  process.exit(1);
}
console.log(`\nDB found: ${dbPath}\n`);

// ──────────────────────────────────────────────
// 2. Open DB + discover schema
// ──────────────────────────────────────────────
let Database;
try {
  Database = require('better-sqlite3');
} catch {
  console.error('ERROR: better-sqlite3 not available. Run: npm install');
  process.exit(1);
}
const db = new Database(dbPath);

const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(t => t.name);
const campTable = tables.find(t => /campaign/i.test(t));
if (!campTable) {
  console.error('ERROR: No campaign table. Tables found:', tables.join(', '));
  process.exit(1);
}

const cols = db.pragma(`table_info(${campTable})`).map(c => c.name);
const pick = (...names) => names.find(n => cols.includes(n)) || null;

const C = {
  name:    pick('name', 'campaignName', 'campaign_name'),
  channel: pick('channel', 'platform'),
  media:   pick('mediaSpend', 'media_spend', 'mediaSpent'),
  client:  pick('clientSpend', 'client_spend', 'clientSpent'),
  imps:    pick('impressions', 'imps'),
  src:     pick('metricsSource', 'metrics_source'),
  sync:    pick('lastSyncedAt', 'last_synced_at'),
};

if (!C.name || !C.channel || !C.media || !C.src || !C.sync) {
  console.error('Cannot map required columns. All columns:', cols.join(', '));
  console.error('Mapped:', JSON.stringify(C, null, 2));
  process.exit(1);
}

// ──────────────────────────────────────────────
// 3. Load original values from central-import.json
// ──────────────────────────────────────────────
let importRows = null;
for (const p of ['config/central-import.json', 'data/central-import.json', 'central-import.json']) {
  if (!fs.existsSync(p)) continue;
  const raw = JSON.parse(fs.readFileSync(p, 'utf8'));
  const arr = Array.isArray(raw) ? raw : (raw.campaigns || raw.rows || null);
  if (arr && arr.length) { importRows = arr; console.log(`Import source: ${p} (${arr.length} rows)`); break; }
}
if (!importRows) {
  console.warn('WARN: central-import.json not found — will clear sync markers only (spend values unchanged).');
  console.warn('      You can still restore spend manually in Central after restart.\n');
}

// Helper: find the original row in the import
function findOriginal(t) {
  if (!importRows) return null;
  return importRows.find(r => {
    const n = r.name || r.campaignName || r.campaign_name || '';
    const ch = r.channel || r.platform || '';
    return n === t.name && ch === t.channel;
  });
}

function origVal(row, ...keys) {
  if (!row) return null;
  for (const k of keys) { if (row[k] !== undefined && row[k] !== null) return row[k]; }
  return null;
}

// ──────────────────────────────────────────────
// 4. Restore each row
// ──────────────────────────────────────────────
console.log('\n========== RESTORING 5 SCHNEIDER ROWS ==========\n');

const restoreTx = db.transaction(() => {
  for (const t of TARGETS) {
    const cur = db.prepare(
      `SELECT ${C.media}, ${C.client || "'n/a'"} AS clientVal, ${C.src}, ${C.sync} FROM ${campTable} WHERE ${C.name} = ? AND ${C.channel} = ?`
    ).get(t.name, t.channel);

    if (!cur) {
      console.warn(`SKIP: ${t.name} · ${t.channel} — row not found in DB\n`);
      continue;
    }

    const orig = findOriginal(t);
    const oMedia  = origVal(orig, 'mediaSpend', 'media_spend', 'mediaSpent');
    const oClient = origVal(orig, 'clientSpend', 'client_spend', 'clientSpent');
    const oImps   = origVal(orig, 'impressions', 'imps');

    console.log(`${t.name} · ${t.channel}`);
    console.log(`  BEFORE: media=${cur[C.media]}, client=${cur.clientVal}, src=${cur[C.src]}, synced=${cur[C.sync]}`);

    // Build the UPDATE dynamically
    let sql = `UPDATE ${campTable} SET ${C.src} = 'sheet-import', ${C.sync} = NULL`;
    const params = [];

    if (oMedia !== null)              { sql += `, ${C.media} = ?`;  params.push(oMedia);  }
    if (oClient !== null && C.client) { sql += `, ${C.client} = ?`; params.push(oClient); }
    if (oImps !== null && C.imps)     { sql += `, ${C.imps} = ?`;   params.push(oImps);   }

    sql += ` WHERE ${C.name} = ? AND ${C.channel} = ?`;
    params.push(t.name, t.channel);

    const result = db.prepare(sql).run(...params);

    console.log(`  AFTER:  media=${oMedia ?? '(unchanged)'}, client=${oClient ?? '(unchanged)'}, src=sheet-import, synced=null`);
    console.log(`  Rows affected: ${result.changes}\n`);
  }
});

restoreTx();

// ──────────────────────────────────────────────
// 5. Disable Schneider in central-clients.json
// ──────────────────────────────────────────────
console.log('========== DISABLING SCHNEIDER SYNC ==========\n');

const clientsFile = ['config/central-clients.json', 'central-clients.json'].find(p => fs.existsSync(p));
if (clientsFile) {
  const clients = JSON.parse(fs.readFileSync(clientsFile, 'utf8'));
  let hit = false;
  for (const [key, val] of Object.entries(clients)) {
    const label = (val.name || key || '').toLowerCase();
    if (label.includes('schneider')) {
      console.log(`  ${key}: validated ${val.validated} → false`);
      clients[key].validated = false;
      hit = true;
    }
  }
  if (hit) {
    fs.writeFileSync(clientsFile, JSON.stringify(clients, null, 2) + '\n');
    console.log(`  Saved ${clientsFile}`);
  } else {
    console.warn('  Schneider entry not found — set validated: false manually');
  }
} else {
  console.warn('  central-clients.json not found — set validated: false manually');
}

// ──────────────────────────────────────────────
// 6. Summary
// ──────────────────────────────────────────────
db.close();
console.log(`
========== DONE ==========

What just happened:
  • 4 TTD rows (NEL, W&E, Airset, EBA) restored to import-file values
  • 1 LinkedIn row (Advancing Energy T) restored to import-file values
  • All 5: metricsSource → sheet-import, lastSyncedAt → null
  • Schneider validated → false (sync will skip it)

Next steps:
  1. Restart the server:  node server.js
  2. Verify with:
     curl -s "http://localhost:8787/api/central/campaigns" | jq "[.campaigns[] | select((.name // \\"\\") | test(\\"NEL|Water and Environment|Airset|EBA|Advancing Energy T\\"))] | map({name, channel, metricsSource, lastSyncedAt, mediaSpend, clientSpend})"
  3. Check Pulse — Schneider should look like this morning (no LIVE badges on these rows)
  4. Cloudflare rows should still show LIVE — they were not touched
`);
