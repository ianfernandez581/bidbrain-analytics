/*
 * src/central/readiness.test.js — unit tests for the live-coverage readiness builder.
 * Pure (no BQ, no DB): feeds synthetic campaigns + config + a fetched-preview fixture.
 * Locks the three cases the task calls out + live-set derivation. Run: node this file.
 */
'use strict';
const readiness = require('./readiness');

let pass = 0, fail = 0;
function check(name, cond, got) { if (cond) { pass++; console.log('  ✓', name); } else { fail++; console.log('  ✗', name, got !== undefined ? JSON.stringify(got) : ''); } }
const rowFor = (rows, client, channel) => rows.find(r => r.client === client && (channel == null || r.channel === channel));

// ---- fixtures ---------------------------------------------------------------------------
// Campaigns (DB source of truth). Live = Active/Paused, non-archived.
const campaigns = [
  { client: 'Schneider', name: 'EBA', channel: 'DV360', status: 'Active', archivedAt: null },
  { client: 'MongoDB', name: 'Always On', channel: 'Trade Desk', status: 'Active', archivedAt: null },
  { client: 'STT', name: 'Awareness', channel: 'DV360', status: 'Active', archivedAt: null },
  { client: 'ResetData', name: 'Prospecting', channel: 'Trade Desk', status: 'Active', archivedAt: null },
  { client: 'HireRight', name: 'Digital Air Cover', channel: 'Trade Desk', status: 'Active', archivedAt: null },
  // dead + no-BQ + archived — must NOT appear
  { client: 'City Perfume', name: 'Old', channel: 'Meta', status: 'Ended', archivedAt: null },
  { client: 'QTopia', name: 'Old', channel: 'Trade Desk', status: 'Ended', archivedAt: null },
  { client: 'Gateway', name: 'Live', channel: 'Meta', status: 'Active', archivedAt: null },   // source none
  { client: 'MongoDB', name: 'Archived', channel: 'Trade Desk', status: 'Active', archivedAt: '2026-01-01' }
];

const config = { clients: [
  { client: 'Schneider', validated: true, bq: { dataset: 'client_schneider', table: 'pm_delivery' },
    map: [{ bqName: 'eba', campaignName: 'EBA' }] },
  { client: 'MongoDB', validated: false, source: 'raw', map: [], tables: [
    { dataset: 'raw_snowflake', table: 'tradedesk_apac_all', advertiserValue: 'MongoDB' },
    { dataset: 'raw_snowflake', table: 'tradedesk_apac_conversion', advertiserValue: '9c1w83i', channel: 'Trade Desk' }
  ] },
  { client: 'STT', validated: false, source: 'raw', map: [], tables: [] },
  { client: 'ResetData', validated: false, source: 'raw', map: [], tables: [] },
  { client: 'HireRight', validated: false, source: 'raw', map: [
    { channel: 'Trade Desk', advertiserName: 'HireRight', campaignMatch: { mode: 'contains', value: 'HireRight_Digital-Air-Cover' }, campaignName: 'Digital Air Cover' }
  ], tables: [] },
  { client: 'City Perfume', validated: false, source: 'raw', map: [], tables: [] },
  { client: 'QTopia', validated: false, source: 'raw', map: [], tables: [] },
  { client: 'Gateway', validated: false, source: 'none', map: [] }
] };

// fetched preview (central_sync --readiness .clients shape). raw rows are per-campaign, tagged.
const fetched = {
  Schneider: { rows: [{ bqName: 'eba', impressions: 1000000, mediaSpend: 5000 }] },
  MongoDB: { rows: [
    // NAME row (real-world trap): 0 impressions but REAL spend ($18K each) — must still be
    // ignored in favour of the ID row, because impressions are the delivery signal.
    { bqName: 'MDB Legacy A', advertiserName: 'MongoDB', channel: 'Trade Desk', dataset: 'raw_snowflake', table: 'tradedesk_apac_all', impressions: 0, mediaSpend: 18000 },
    { bqName: 'MDB Legacy B', advertiserName: 'MongoDB', channel: 'Trade Desk', dataset: 'raw_snowflake', table: 'tradedesk_apac_all', impressions: 0, mediaSpend: 18052.7 },
    // ID row (ADVERTISER_ID 9c1w83i): the real delivery, no cost column.
    { bqName: 'DNB Gartner MQ', advertiserName: '9c1w83i', channel: 'Trade Desk', dataset: 'raw_snowflake', table: 'tradedesk_apac_conversion', impressions: 3000000, mediaSpend: 0 },
    { bqName: 'KGA IDC', advertiserName: '9c1w83i', channel: 'Trade Desk', dataset: 'raw_snowflake', table: 'tradedesk_apac_conversion', impressions: 479515, mediaSpend: 0 }
  ] },
  STT: { rows: [
    // DV360: TWO advertiser spellings, SAME campaign name across both → rollup dedupes to 1.
    { bqName: 'STT Brand', advertiserName: 'APAC | STT GDC - SGD', channel: 'DV360', dataset: 'raw_snowflake', table: 'dv360_apac', impressions: 500000, mediaSpend: 2000 },
    { bqName: 'STT Brand', advertiserName: 'APAC | STTelemdia GDC', channel: 'DV360', dataset: 'raw_snowflake', table: 'dv360_apac', impressions: 300000, mediaSpend: 1500 },
    { bqName: 'STT Reach', advertiserName: 'APAC | STTelemdia GDC', channel: 'DV360', dataset: 'raw_snowflake', table: 'dv360_apac', impressions: 200000, mediaSpend: 1000 }
  ] },
  ResetData: { rows: [
    { bqName: 'RD Search', advertiserName: 'Reset Data', channel: 'Google Ads', dataset: 'raw_windsor', table: 'perf_google_ads', impressions: 100000, mediaSpend: 800 }
  ] },
  HireRight: { rows: [
    { bqName: 'HireRight_Digital-Air-Cover_FebApr2026 - HR+TAL', advertiserName: 'HireRight', channel: 'Trade Desk', dataset: 'raw_snowflake', table: 'tradedesk_apac_all', impressions: 200000, mediaSpend: 900 },
    { bqName: 'HireRight_Digital-Air-Cover_FebApr2026 - Contact List', advertiserName: 'HireRight', channel: 'Trade Desk', dataset: 'raw_snowflake', table: 'tradedesk_apac_all', impressions: 150000, mediaSpend: 700 }
  ] }
};

const rows = readiness.buildReadiness({ campaigns, config, fetched });

// ---- live-set derivation ----------------------------------------------------------------
check('dead client City Perfume excluded (Ended only)', !rowFor(rows, 'City Perfume'));
check('dead client QTopia excluded (Ended only)', !rowFor(rows, 'QTopia'));
check('no-BQ client Gateway excluded (source none, even though Active)', !rowFor(rows, 'Gateway'));
check('live clients present: Schneider/MongoDB/STT/ResetData/HireRight',
  ['Schneider', 'MongoDB', 'STT', 'ResetData', 'HireRight'].every(c => !!rowFor(rows, c)));
check('Schneider (validated) sorts to the top / marked done', rows[0].client === 'Schneider' && rows[0].validated === true);

// ---- CASE 1: MongoDB matches on ADVERTISER_ID 9c1w83i, NOT the name -----------------------
const mdb = rowFor(rows, 'MongoDB', 'Trade Desk');
check('MongoDB rule advertiserName = the ID 9c1w83i ONLY (not "MongoDB", not a rollup of both)',
  mdb && mdb.rule.advertiserName === '9c1w83i', mdb && mdb.rule);
check('MongoDB rule is contains (single active ID spelling), NOT rollup', mdb && mdb.rule.mode === 'contains', mdb && mdb.rule);
check('MongoDB preview = 2 campaigns / 3,479,515 imps (ID delivery; the 0-imp spend-only name rows dropped)',
  mdb && mdb.preview.campaigns === 2 && mdb.preview.impressions === 3479515, mdb && mdb.preview);
check('MongoDB bqSource = tradedesk_apac_conversion (the ID table)', mdb && mdb.bqSource === 'raw_snowflake.tradedesk_apac_conversion', mdb && mdb.bqSource);
check('MongoDB mediaSpend 0 (conversion table has no cost; the $36K name-row spend is not on the ID rule)', mdb && mdb.preview.mediaSpend === 0);
check('MongoDB not flagged needs-manual (it matched)', mdb && mdb.needsManualRule === false);

// ---- CASE 2: rollup multi-spelling (STT) sums + dedupes by campaign name -------------------
const stt = rowFor(rows, 'STT', 'DV360');
check('STT DV360 seeded as rollup (2 active spellings)', stt && stt.rule.mode === 'rollup', stt && stt.rule);
check('STT rollup dedupes "STT Brand" across the two spellings → 2 campaigns',
  stt && stt.preview.campaigns === 2, stt && stt.preview);
// rollup counts each campaign ONCE (first-seen spelling's metrics win — the whole point of
// dedup-by-name), so "STT Brand" contributes 500,000 (not 500k+300k) + "STT Reach" 200,000.
check('STT rollup: duplicate-name campaign counted once (700,000, not double-counted)',
  stt && stt.preview.impressions === 700000, stt && stt.preview);
check('STT advertiserName lists both spellings', stt && /STT GDC - SGD/.test(stt.rule.advertiserName) && /STTelemdia/.test(stt.rule.advertiserName));
// ResetData: single spelling per channel but KNOWN_ROLLUP → still rollup (task rule)
const rd = rowFor(rows, 'ResetData', 'Google Ads');
check('ResetData seeded rollup (known multi-spelling client) even at 1 spelling', rd && rd.rule.mode === 'rollup', rd && rd.rule);

// ---- CASE 3: 0-match row renders as needs-manual-rule (red) --------------------------------
// A mapped rule whose contains-value matches no BQ campaign name.
const missCfg = JSON.parse(JSON.stringify(config));
missCfg.clients.find(c => c.client === 'HireRight').map[0].campaignMatch.value = 'DOES-NOT-EXIST';
const missRows = readiness.buildReadiness({ campaigns, config: missCfg, fetched });
const hr = rowFor(missRows, 'HireRight', 'Trade Desk');
check('0-match mapped rule → preview 0 campaigns', hr && hr.preview.campaigns === 0, hr && hr.preview);
check('0-match → needsManualRule true (red, surfaced for Zhen)', hr && hr.needsManualRule === true);
// and the happy path (seed value hits): matches both Digital-Air-Cover rows
const hrOk = rowFor(rows, 'HireRight', 'Trade Desk');
check('HireRight seeded rule matches its 2 BQ campaigns', hrOk && hrOk.preview.campaigns === 2, hrOk && hrOk.preview);
check('HireRight carries the Design A contains rule + advertiserName', hrOk && hrOk.rule.mode === 'contains' && hrOk.rule.advertiserName === 'HireRight');

// ---- Schneider Mode A view preview --------------------------------------------------------
const sch = rowFor(rows, 'Schneider');
check('Schneider Mode A previews the pm_delivery program (1 campaign, 1M imps)',
  sch && sch.preview.campaigns === 1 && sch.preview.impressions === 1000000, sch && sch.preview);
check('Schneider bqSource = client_schneider.pm_delivery', sch && sch.bqSource === 'client_schneider.pm_delivery');

console.log('\n' + (fail ? '✗' : '✓') + ' readiness builder: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
