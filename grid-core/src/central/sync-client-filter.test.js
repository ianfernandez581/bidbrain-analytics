/*
 * src/central/sync-client-filter.test.js — locks the Phase 4 ?client= fix on
 * POST /api/central/sync (PHASE3_CLOUDFLARE_REPORT.md §9/§10.6: the param used to be
 * silently ignored, so every sync was global and Schneider was corrupted alongside a
 * "Cloudflare" sync).
 *
 * Boots the REAL server as a child process (temp DB via BRAIN_DATA_DIR, fixture sync
 * doc via CENTRAL_SYNC_FIXTURE, temp client config via CENTRAL_CLIENTS_PATH — no BQ,
 * no live data touched) and asserts:
 *   1. ?client=cloudflare (case-insensitive) syncs ONLY Cloudflare — Schneider is
 *      skipped with 'not requested (client filter)' and its rows stay unsynced.
 *   2. ?client=<bogus> → 400, nothing synced.
 *   3. ?client=<not-validated> → 400, nothing synced.
 *   4. ?client=Cloudflare&includeEnded=1 combines: the Ended row backfills only then.
 *   5. No param → all validated clients sync (unchanged behaviour).
 */
'use strict';
const fs = require('fs'), path = require('path'), os = require('os');
const { spawn } = require('child_process');

const ROOT = path.join(__dirname, '..', '..');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'sync-filter-test-'));
const PORT = 18000 + Math.floor(Math.random() * 2000);
const BASE = `http://localhost:${PORT}`;

// fixture sync doc: rows for BOTH validated clients (the fixture path ignores --client;
// the route-level write filter is what this test locks)
const FIXTURE = path.join(TMP, 'sync-fixture.json');
fs.writeFileSync(FIXTURE, JSON.stringify({
  fetchedAt: '2026-07-23T00:00:00Z',
  clients: {
    Cloudflare: {
      rows: [
        { bqName: 'CLOUD_ACQ_2026-Q3_SURROUND-ABM - ANZ', advertiserName: 'Cloudflare', channel: 'Trade Desk', impressions: 1000, mediaSpend: 100 },
        { bqName: 'CLOUD_ACQ_2026-Q2_CNC_TTD_CORE-DG - ANZ', advertiserName: 'Cloudflare', channel: 'Trade Desk', impressions: 2000, mediaSpend: 200 }
      ], errors: []
    },
    Schneider: {
      rows: [
        { bqName: '2079_SE_ANZ_EBA_Activate', advertiserName: 'Schneider Electric', channel: 'Trade Desk', impressions: 3000, mediaSpend: 300 }
      ], errors: []
    }
  }
}));

// temp client config: 2 validated + 1 not (map entries resolve by campaignName against
// the sheet snapshot the server imports on boot — Surround ABM Active, Q2 Core DG Ended)
const CLIENTS = path.join(TMP, 'central-clients.json');
fs.writeFileSync(CLIENTS, JSON.stringify({
  clients: [
    {
      client: 'Cloudflare', validated: true, source: 'raw', map: [
        { channel: 'Trade Desk', advertiserName: 'Cloudflare', campaignMatch: { mode: 'contains', value: 'SURROUND-ABM' }, campaignName: 'Surround ABM' },
        { channel: 'Trade Desk', advertiserName: 'Cloudflare', campaignMatch: { mode: 'contains', value: 'CORE-DG' }, campaignName: 'Q2 Core DG' }
      ]
    },
    {
      client: 'Schneider', validated: true, source: 'raw', map: [
        { channel: 'Trade Desk', advertiserName: 'Schneider Electric', campaignMatch: { mode: 'contains', value: 'EBA_Activate' }, campaignName: 'EBA' }
      ]
    },
    { client: 'STT', validated: false, source: 'raw', map: [] }
  ]
}));

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };

const child = spawn(process.execPath, [path.join(ROOT, 'server.js')], {
  cwd: ROOT,
  env: Object.assign({}, process.env, {
    PORT: String(PORT),
    BRAIN_DATA_DIR: TMP,
    CENTRAL_SYNC_FIXTURE: FIXTURE,
    CENTRAL_CLIENTS_PATH: CLIENTS,
    PYTHON: 'python-not-found-test-stub',   // exec-KPI boot refresh fails fast + is captured; sync uses the fixture
    EXEC_AUTOSYNC_MIN: '0'
  }),
  stdio: ['ignore', 'pipe', 'pipe']
});
child.stderr.on('data', d => process.stderr.write('[server] ' + d));

function waitUp(tries) {
  return fetch(BASE + '/api/central/campaigns').then(r => r.json()).catch(e => {
    if (tries <= 0) throw new Error('server never came up: ' + e.message);
    return new Promise(r => setTimeout(r, 250)).then(() => waitUp(tries - 1));
  });
}
const post = p => fetch(BASE + p, { method: 'POST' }).then(r => r.json().then(j => ({ status: r.status, body: j })));

(async () => {
  await waitUp(40);

  // ---- 1. filtered sync: ONLY the requested client is written ----
  const f1 = await post('/api/central/sync?client=cloudflare');   // lowercase on purpose
  check('filtered sync returns 200', f1.status === 200, f1);
  check('perClient contains ONLY Cloudflare', JSON.stringify(Object.keys(f1.body.perClient || {})) === '["Cloudflare"]', f1.body.perClient);
  check('Schneider skipped as "not requested (client filter)"',
    (f1.body.skippedClients || []).some(s => s.client === 'Schneider' && /not requested/.test(s.reason)), f1.body.skippedClients);
  check('STT also skipped (filter reason wins over not-validated)',
    (f1.body.skippedClients || []).some(s => s.client === 'STT' && /not requested/.test(s.reason)), f1.body.skippedClients);
  check('Cloudflare updated its Active row (Ended row still skipped)', f1.body.perClient.Cloudflare.updated === 1, f1.body.perClient);

  const rows1 = (await (await fetch(BASE + '/api/central/campaigns')).json()).campaigns;
  const eba = rows1.find(c => c.client === 'Schneider' && c.name === 'EBA');
  const abm = rows1.find(c => c.client === 'Cloudflare' && c.name === 'Surround ABM');
  check('Schneider EBA row NOT touched by the filtered sync (lastSyncedAt null)', eba && eba.lastSyncedAt === null, eba && eba.lastSyncedAt);
  check('Cloudflare Surround ABM row IS synced', abm && abm.lastSyncedAt !== null && abm.mediaSpend === 100, abm && { at: abm.lastSyncedAt, spend: abm.mediaSpend });

  // ---- 2/3. bad names are a loud 400, never a silent no-op ----
  const f2 = await post('/api/central/sync?client=Bogus');
  check('unknown client → 400', f2.status === 400 && /unknown client/i.test(f2.body.error || ''), f2);
  const f3 = await post('/api/central/sync?client=STT');
  check('not-validated client → 400', f3.status === 400 && /not validated/i.test(f3.body.error || ''), f3);

  // ---- 4. includeEnded combines with the filter ----
  const f4 = await post('/api/central/sync?client=Cloudflare&includeEnded=1');
  check('filter + includeEnded → 200, Ended row now backfills (updated=2)',
    f4.status === 200 && f4.body.perClient.Cloudflare.updated === 2, f4.body.perClient);
  check('filter + includeEnded still only Cloudflare', JSON.stringify(Object.keys(f4.body.perClient || {})) === '["Cloudflare"]', f4.body.perClient);

  // ---- 5. no param = all validated clients (unchanged) ----
  const f5 = await post('/api/central/sync');
  const keys5 = Object.keys(f5.body.perClient || {}).sort();
  check('unfiltered sync covers both validated clients', JSON.stringify(keys5) === '["Cloudflare","Schneider"]', keys5);
  const eba2 = ((await (await fetch(BASE + '/api/central/campaigns')).json()).campaigns).find(c => c.client === 'Schneider' && c.name === 'EBA');
  check('Schneider EBA syncs in the unfiltered pass', eba2 && eba2.lastSyncedAt !== null && eba2.mediaSpend === 300, eba2 && { at: eba2.lastSyncedAt, spend: eba2.mediaSpend });

  console.log('\n' + (fail ? '✗' : '✓') + ' sync-client-filter: ' + pass + ' passed, ' + fail + ' failed');
  child.kill();
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('✗ sync-client-filter crashed:', e.message); child.kill(); process.exit(1); });
