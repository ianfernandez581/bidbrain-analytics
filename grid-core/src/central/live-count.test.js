/*
 * src/central/live-count.test.js — locks the EcoStruxure status fix + the live count.
 *
 * Seeds a temp DB exactly like the server (sheet import + HireRight scan-extra) and asserts:
 *   1. Schneider "Software First EcoStruxure" / LinkedIn imports as Active (the confirmed
 *      source correction — its blank sheet status was a data gap, not a deliberate Draft).
 *   2. The live Active+Paused total is 38.
 *
 * NB on the number: the flip yields 38 Active+Paused (and the app's Live chip, which also
 * counts Draft, stays 39) — NOT 40. EcoStruxure was already a Draft, which the app counts as
 * live, so flipping it to Active RECLASSIFIES an already-live row rather than adding a new one.
 * Reaching 40 would require two more currently-non-live rows to become live (unconfirmed), so
 * this test encodes the verified reality (38), not the 40 target.
 */
'use strict';
const fs = require('fs'), path = require('path'), os = require('os');
process.env.BRAIN_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'lc-test-'));
const db = require('../brain/db');
const rc = require('./render-central');

const ROOT = path.join(__dirname, '..', '..');
db.importCentralSnapshot(JSON.parse(fs.readFileSync(path.join(ROOT, 'config/central-import.json'), 'utf8')).map(r => rc._mapGridRowToCentral(r)));
JSON.parse(fs.readFileSync(path.join(ROOT, 'config/central-extra-campaigns.json'), 'utf8')).campaigns
  .forEach(r => { const dup = db.getCampaigns().some(c => c.client === r.client && c.name === r.name && (c.channel || null) === (r.channel || null)); if (!dup) db.createCampaign(r, 'scan'); });

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };

const all = db.getCampaigns().filter(c => !c.archivedAt);
const eco = all.find(c => c.client === 'Schneider' && c.name === 'Software First EcoStruxure' && (c.channel || '').toLowerCase().indexOf('linkedin') >= 0);
const AP = all.filter(c => ['Active', 'Paused'].indexOf(c.status) >= 0);

check('EcoStruxure/LinkedIn imports as Active (source fix applied)', eco && eco.status === 'Active', eco && { status: eco.status, channel: eco.channel });
check('EcoStruxure is counted in the Active+Paused live set', !!AP.find(c => c === eco));
check('live Active+Paused total = 38 (post-fix reality; see header note re: 40)', AP.length === 38, AP.length);

console.log('\n' + (fail ? '✗' : '✓') + ' live-count: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
