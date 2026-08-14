// Build campaign_id_reference.xlsx - READ ONLY. Pulls campaign identity
// (account id/name, campaign id/name, status, dates, spend) for every in-scope
// client from the BigQuery mirrors of the platform feeds, and writes one tab
// per client plus an All tab.
//
// Source choice: the BigQuery mirrors ARE the Snowflake tables (ingest/
// snowflake_data_pull mirrors them 1:1) plus the Windsor feeds, which carry
// the campaign IDs the Snowflake TTD/Reddit feeds do not have. No warehouse
// credits, no key handling, identical data.
'use strict';

const fs = require('fs');
const path = require('path');
const GRID = path.join('c:', 'Users', 'DELL', 'Desktop', 'bidbrain-analytics', 'grid-core');
const { BigQuery } = require(path.join(GRID, 'node_modules', '@google-cloud', 'bigquery'));
const XLSX = require(path.join(GRID, 'node_modules', 'xlsx'));

const bq = new BigQuery({ projectId: 'bidbrain-analytics' });
const q = async (sql) => (await bq.query({ query: sql, location: 'australia-southeast1' }))[0];
const T = (t) => '`bidbrain-analytics.' + t + '`';
const esc = (v) => String(v).replace(/'/g, "\\'");

// EVERY column must carry its alias in EVERY builder - unaliased expressions
// come back as f0_, f1_ ... and the values silently land nowhere.
const A = ['platform', 'account_or_advertiser_id', 'account_name', 'campaign_id', 'campaign_name',
  'status', 'first_seen', 'last_seen', 'spend_to_date', 'grain', 'source_table', 'notes'];
/** sel(expr[]) -> "e0 AS platform, e1 AS account_or_advertiser_id, ..." */
const sel = (exprs) => exprs.map((e, i) => `${e} AS ${A[i]}`).join(',\n      ');

const SRC = {
  // Snowflake TTD: no ID columns at all in this feed (known repo gap).
  sf_ttd: (v) => `SELECT ${sel([
    `'Trade Desk'`, 'CAST(NULL AS STRING)', 'ADVERTISER_NAME', 'CAST(NULL AS STRING)', 'CAMPAIGN_NAME',
    'CAST(NULL AS STRING)', 'CAST(MIN(DAY) AS STRING)', 'CAST(MAX(DAY) AS STRING)',
    'ROUND(SUM(COALESCE(COSTS,0)),2)', `'campaign'`, `'raw_snowflake.tradedesk_apac_all'`,
    `'campaign id NOT IN THIS FEED (Snowflake TTD carries no id columns) - take it from the TTD UI'`,
  ])}
    FROM ${T('raw_snowflake.tradedesk_apac_all')} WHERE ADVERTISER_NAME = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table, notes`,

  // Windsor TTD: HAS advertiser_id + campaign_id.
  w_ttd: (v) => `SELECT ${sel([
    `'Trade Desk'`, 'CAST(advertiser_id AS STRING)', 'advertiser_name',
    'CAST(campaign_id AS STRING)', 'campaign_name', 'CAST(NULL AS STRING)',
    'CAST(MIN(metric_date) AS STRING)', 'CAST(MAX(metric_date) AS STRING)',
    'ROUND(SUM(COALESCE(cost,0)),2)', `'campaign'`, `'raw_windsor.perf_the_trade_desk'`, `''`,
  ])}
    FROM ${T('raw_windsor.perf_the_trade_desk')} WHERE advertiser_name = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table, notes`,

  // LinkedIn: CAMPAIGN GROUP grain (where budgets reconcile). The feed carries
  // child CAMPAIGN_IDs but no group id, so child ids ride in notes.
  sf_li: (v) => `SELECT ${sel([
    `'LinkedIn'`, 'CAST(ACCOUNT_ID AS STRING)', 'ACCOUNT_NAME', 'CAST(NULL AS STRING)', 'CAMPAIGN_GROUP_NAME',
    `STRING_AGG(DISTINCT CAMPAIGN_STATE, ', ' ORDER BY CAMPAIGN_STATE LIMIT 3)`,
    'CAST(MIN(DAY) AS STRING)', 'CAST(MAX(DAY) AS STRING)',
    'ROUND(SUM(COALESCE(COSTS,0)),2)', `'campaign group'`, `'raw_snowflake.linkedin_ads_apac'`,
    `CONCAT('group id not in feed. child campaign ids: ', SUBSTR(STRING_AGG(DISTINCT CAST(CAMPAIGN_ID AS STRING), ', '), 1, 280))`,
  ])}
    FROM ${T('raw_snowflake.linkedin_ads_apac')} WHERE ACCOUNT_NAME = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, grain, source_table`,

  w_li: (v) => `SELECT ${sel([
    `'LinkedIn'`, 'CAST(account_id AS STRING)', 'account_name', 'CAST(NULL AS STRING)', 'campaign_group_name',
    `STRING_AGG(DISTINCT campaign_status, ', ' ORDER BY campaign_status LIMIT 3)`,
    'CAST(MIN(metric_date) AS STRING)', 'CAST(MAX(metric_date) AS STRING)',
    'ROUND(SUM(COALESCE(spend,0)),2)', `'campaign group'`, `'raw_windsor.perf_linkedin'`,
    `CONCAT('group id not in feed. child campaign ids: ', SUBSTR(STRING_AGG(DISTINCT CAST(campaign_id AS STRING), ', '), 1, 280))`,
  ])}
    FROM ${T('raw_windsor.perf_linkedin')} WHERE account_name = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, grain, source_table`,

  // DV360: INSERTION ORDER grain, and the feed HAS insertion_order_id.
  sf_dv: (v) => `SELECT ${sel([
    `'DV360'`, 'CAST(ADVERTISER_ID AS STRING)', 'ADVERTISER_NAME',
    'CAST(INSERTION_ORDER_ID AS STRING)', 'INSERTION_ORDER_NAME', 'CAST(NULL AS STRING)',
    'CAST(MIN(DAY) AS STRING)', 'CAST(MAX(DAY) AS STRING)',
    'ROUND(SUM(COALESCE(REVENUE_ADV_CURRENCY,0)),2)', `'insertion order'`, `'raw_snowflake.dv360_apac'`,
    `CONCAT('parent campaign: ', SUBSTR(STRING_AGG(DISTINCT CAMPAIGN_NAME, ' | '), 1, 200))`,
  ])}
    FROM ${T('raw_snowflake.dv360_apac')} WHERE ADVERTISER_NAME = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table`,

  sf_ga: (v) => `SELECT ${sel([
    `'Google Ads'`, 'CAST(ACCOUNT_ID AS STRING)', 'ACCOUNT_NAME',
    'CAST(CAMPAIGN_ID AS STRING)', 'CAMPAIGN_NAME', 'CAST(NULL AS STRING)',
    'CAST(MIN(DAY) AS STRING)', 'CAST(MAX(DAY) AS STRING)',
    'ROUND(SUM(COALESCE(COSTS,0)),2)', `'campaign'`, `'raw_snowflake.google_ads_apac'`, `''`,
  ])}
    FROM ${T('raw_snowflake.google_ads_apac')} WHERE ACCOUNT_NAME = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table, notes`,

  dts_ga: (v) => `SELECT ${sel([
    `'Google Ads'`, 'CAST(customer_id AS STRING)', 'account_name',
    'CAST(campaign_id AS STRING)', 'campaign_name', 'CAST(NULL AS STRING)',
    'CAST(MIN(metric_date) AS STRING)', 'CAST(MAX(metric_date) AS STRING)',
    'ROUND(SUM(COALESCE(spend,0)),2)', `'campaign'`, `'raw_google_ads.perf_google_ads'`, `''`,
  ])}
    FROM ${T('raw_google_ads.perf_google_ads')} WHERE account_name = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table, notes`,

  w_meta: (v) => `SELECT ${sel([
    `'Meta'`, 'CAST(account_id AS STRING)', 'account_name',
    'CAST(campaign_id AS STRING)', 'campaign_name',
    `STRING_AGG(DISTINCT effective_status, ', ' ORDER BY effective_status LIMIT 3)`,
    'CAST(MIN(metric_date) AS STRING)', 'CAST(MAX(metric_date) AS STRING)',
    'ROUND(SUM(COALESCE(cost,0)),2)', `'campaign'`, `'raw_windsor.perf_meta'`, `''`,
  ])}
    FROM ${T('raw_windsor.perf_meta')} WHERE account_name = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, grain, source_table, notes`,

  w_reddit: (v) => `SELECT ${sel([
    `'Reddit'`, 'CAST(account_id AS STRING)', 'account_name',
    'CAST(campaign_id AS STRING)', 'campaign_name', 'CAST(NULL AS STRING)',
    'CAST(MIN(metric_date) AS STRING)', 'CAST(MAX(metric_date) AS STRING)',
    'ROUND(SUM(COALESCE(spend,0)),2)', `'campaign'`, `'raw_windsor.perf_reddit'`, `''`,
  ])}
    FROM ${T('raw_windsor.perf_reddit')} WHERE account_name = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table, notes`,

  sf_reddit: (v) => `SELECT ${sel([
    `'Reddit'`, 'CAST(ACCOUNT_ID AS STRING)', 'ACCOUNT_NAME', 'CAST(NULL AS STRING)', 'CAMPAIGN_NAME',
    'ACCOUNT_STATE', 'CAST(MIN(DAY) AS STRING)', 'CAST(MAX(DAY) AS STRING)',
    'ROUND(SUM(COALESCE(COSTS,0)),2)', `'campaign'`, `'raw_snowflake.reddit_ads_apac_all'`,
    `'campaign id not in this feed - the Windsor Reddit row for the same account has it'`,
  ])}
    FROM ${T('raw_snowflake.reddit_ads_apac_all')} WHERE ACCOUNT_NAME = '${esc(v)}'
    GROUP BY platform, account_or_advertiser_id, account_name, campaign_id, campaign_name, status, grain, source_table, notes`,
};

// Client -> sources. Account values come from grid-core/config/central-clients.json
// (the Grid's own mapping) plus accounts discovered in the mirrors for clients
// that config does not cover yet (Caltex, Gateway).
const CLIENTS = {
  Schneider: [['sf_ttd', 'Schneider Electric'], ['sf_li', 'SchneiderElectric_TransmissionSG_AUD'],
    ['sf_li', 'SchneiderElectric_TransmissionSG_USD'], ['sf_li', 'SchneiderElectric_TransmissionSG_SGD'],
    ['w_li', 'SchneiderElectric_TransmissionSG_AUD'],
    ['sf_dv', 'APAC | Schneider Electric AUD'], ['sf_dv', 'APAC | Schneider Electric SGD'],
    ['sf_dv', 'APAC | Schneider Electric (USD)']],
  Cloudflare: [['sf_li', 'Cloudflare APAC'], ['w_li', 'Cloudflare APAC'], ['sf_ttd', 'Cloudflare'],
    ['sf_reddit', 'Transmission_Cloudflare'], ['w_reddit', 'Transmission_Cloudflare']],
  MongoDB: [['sf_ttd', 'MongoDB']],
  STT: [['sf_dv', 'APAC | STT GDC - SGD'], ['sf_dv', 'APAC | STTelemdia GDC'],
    ['sf_ga', 'STT GDC_SGD'], ['sf_ga', 'STT Global Data'],
    ['sf_li', 'APAC - STT GDC - SGD '], ['sf_li', 'STTGDC_TransmissionSG_USD'],
    ['w_li', 'APAC - STT GDC - SGD ']],
  PropTrack: [['sf_dv', 'APAC | PropTrack (AUD)'], ['sf_li', 'PropTrack_TransmissionSG_AUD'],
    ['w_li', 'PropTrack_TransmissionSG_AUD'], ['sf_ttd', 'PropTrack'], ['sf_ttd', 'PopTrack']],
  ResetData: [['dts_ga', 'Reset Data'], ['w_meta', 'Reset backup \u2013 Ad account'],
    ['w_ttd', 'ResetData'], ['w_reddit', 'ResetData Ad Account (100Digital)']],
  Caltex: [['w_ttd', 'Caltex']],
  Gateway: [['w_meta', '100% Digital - Clients']],
  VMCH: [['w_ttd', 'VMCH ']],
  'The Little Marionette': [['dts_ga', 'The Little Marionette'], ['w_ttd', 'The Little Marionette']],
  'Ad Assembly': [['w_meta', 'Ad Assembly - ACRS'], ['w_meta', 'Ad Assembly - BuyerX'],
    ['w_ttd', 'ACRS'], ['w_ttd', 'Altech'], ['w_ttd', 'WEHI']],
  Splunk: [],
};

(async () => {
  const intake = fs.readFileSync('C:/Users/DELL/Downloads/pacing_intake_v2.csv', 'utf8')
    .split(/\r?\n/).slice(1).filter(Boolean);
  const jobsByClient = {};
  for (const line of intake) {
    const client = (line.split(',')[0] || '').trim();
    if (!jobsByClient[client]) jobsByClient[client] = new Set();
    [...line.matchAll(/job\s*(\d{3,5})/gi)].forEach((m) => jobsByClient[client].add(m[1]));
  }

  const all = [];
  const coverage = [];
  const perClient = {};
  for (const [client, sources] of Object.entries(CLIENTS)) {
    const rows = [];
    if (!sources.length) {
      coverage.push({ client, src: 'ALL', account: '-', rows: 0,
        note: 'no advertiser account found in any mirror for this client - IDs must come from the platform UI' });
    }
    for (const [srcKey, acct] of sources) {
      let got = [];
      try {
        got = await q(SRC[srcKey](acct));
      } catch (e) {
        coverage.push({ client, src: srcKey, account: acct, rows: 0, note: 'QUERY FAILED: ' + e.message.slice(0, 140) });
        continue;
      }
      if (!got.length) {
        coverage.push({ client, src: srcKey, account: acct, rows: 0, note: 'account is mapped but the mirror holds no rows for it' });
      }
      for (const r of got) {
        const name = String(r.campaign_name || '');
        const jobHit = [...(jobsByClient[client] || [])].find((j) => name.includes(j));
        rows.push(Object.assign({ client }, r, { likely_intake_job: jobHit ? 'job ' + jobHit : '' }));
      }
    }
    rows.sort((a, b) => String(a.platform).localeCompare(String(b.platform))
      || String(a.campaign_name).localeCompare(String(b.campaign_name)));
    perClient[client] = rows;
    all.push(...rows);
    const withId = rows.filter((r) => String(r.campaign_id || '').trim()).length;
    console.log(`${client}: ${rows.length} campaigns (${withId} with ids)`);
  }

  const wb = XLSX.utils.book_new();
  const HEAD = ['client', ...A, 'likely_intake_job'];
  const sheetFrom = (rows, withClient) => {
    const head = withClient ? HEAD : HEAD.filter((h) => h !== 'client');
    const aoa = [head, ...rows.map((r) => head.map((h) => (r[h] == null ? '' : r[h])))];
    const ws = XLSX.utils.aoa_to_sheet(aoa);
    ws['!cols'] = head.map((h) => ({ wch: h === 'campaign_name' ? 54 : h === 'notes' ? 44 : h === 'account_name' ? 32 : 16 }));
    ws['!autofilter'] = { ref: XLSX.utils.encode_range({ s: { c: 0, r: 0 }, e: { c: head.length - 1, r: aoa.length - 1 } }) };
    ws['!freeze'] = { xSplit: 0, ySplit: 1 };
    return ws;
  };

  const allSorted = all.slice().sort((a, b) => a.client.localeCompare(b.client)
    || String(a.platform).localeCompare(String(b.platform))
    || String(a.campaign_name).localeCompare(String(b.campaign_name)));
  XLSX.utils.book_append_sheet(wb, sheetFrom(allSorted, true), 'All');

  for (const client of Object.keys(CLIENTS)) {
    const rows = perClient[client] || [];
    const tab = client.slice(0, 28).replace(/[\\/*?:[\]]/g, '');
    XLSX.utils.book_append_sheet(wb,
      rows.length ? sheetFrom(rows, false)
        : XLSX.utils.aoa_to_sheet([['No campaigns found in any platform mirror for this client.'],
          ['Get these IDs from the platform UI - see the Coverage gaps tab.']]),
      tab);
  }

  const wsCov = XLSX.utils.aoa_to_sheet([['client', 'source', 'account', 'rows', 'note'],
    ...coverage.map((c) => [c.client, c.src, c.account, c.rows, c.note])]);
  wsCov['!cols'] = [{ wch: 22 }, { wch: 12 }, { wch: 38 }, { wch: 8 }, { wch: 95 }];
  XLSX.utils.book_append_sheet(wb, wsCov, 'Coverage gaps');

  const out = path.join(GRID, 'pacing_intake', 'campaign_id_reference.xlsx');
  XLSX.writeFile(wb, out);
  const withId = all.filter((r) => String(r.campaign_id || '').trim()).length;
  console.log(`\nTOTAL ${all.length} campaigns, ${withId} carry a platform id (${Math.round(withId / all.length * 100)}%)`);
  console.log('coverage gaps:', coverage.length);
  console.log('wrote', out);
})().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
