// Resolve every pacing-intake row to the join key that ACTUALLY matches the
// BigQuery feed, and prove it by pulling real spend. READ ONLY.
//
// Why this exists: the intake's `Campaign IDs` cannot be used as the sole join
// key. Four verified reasons (2026-08-11):
//   1. Snowflake TTD (Cloudflare / MongoDB / Schneider / PropTrack) has NO
//      campaign_id column at all - those rows can only join on campaign name.
//   2. LinkedIn intake ids are campaign GROUP ids; the feeds store child
//      CAMPAIGN ids plus the group NAME - so LinkedIn joins on group name.
//   3. Meta ids lost their last 3 digits to Excel float64 precision
//      (120248473109820 vs the real 120248473109820573) - repaired by prefix.
//   4. `Platform Campaign Names` are abbreviated with "..." - repaired by
//      matching on the prefix and suffix either side of the ellipsis.
//
// Output: campaign_join_keys.xlsx - one row per intake row with the working
// method, the matched platform objects, and spend to date. That file is the
// input the Central import should trust, not the raw ids.
'use strict';

const path = require('path');
const GRID = path.join(__dirname, '..');
const X = require(path.join(GRID, 'node_modules', 'xlsx'));
const { BigQuery } = require(path.join(GRID, 'node_modules', '@google-cloud', 'bigquery'));

const INTAKE = process.argv[2] || 'C:/Users/DELL/Downloads/pacing_intake_FINAL.xlsx';
const bq = new BigQuery({ projectId: 'bidbrain-analytics' });
const q = async (sql) => (await bq.query({ query: sql, location: 'australia-southeast1' }))[0];

// Feed pools per platform. `idCol: null` = the feed carries no campaign id.
const FEEDS = {
  'Trade Desk': [
    { key: 'raw_windsor.perf_the_trade_desk', sql: `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, advertiser_name acct, ROUND(SUM(cost),2) spend, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_the_trade_desk\` GROUP BY 1,2,3` },
    { key: 'raw_snowflake.tradedesk_apac_all', sql: `SELECT CAST(NULL AS STRING) id, CAMPAIGN_NAME nm, ADVERTISER_NAME acct, ROUND(SUM(COSTS),2) spend, CAST(MAX(DAY) AS STRING) last_day FROM \`bidbrain-analytics.raw_snowflake.tradedesk_apac_all\` GROUP BY 1,2,3` },
  ],
  Meta: [
    { key: 'raw_windsor.perf_meta', sql: `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, ROUND(SUM(cost),2) spend, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_meta\` GROUP BY 1,2,3` },
  ],
  LinkedIn: [
    { key: 'raw_snowflake.linkedin_ads_apac', sql: `SELECT CAST(NULL AS STRING) id, CAMPAIGN_GROUP_NAME nm, ACCOUNT_NAME acct, ROUND(SUM(COSTS),2) spend, CAST(MAX(DAY) AS STRING) last_day FROM \`bidbrain-analytics.raw_snowflake.linkedin_ads_apac\` GROUP BY 1,2,3` },
    { key: 'raw_windsor.perf_linkedin', sql: `SELECT CAST(NULL AS STRING) id, campaign_group_name nm, account_name acct, ROUND(SUM(spend),2) spend, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_linkedin\` GROUP BY 1,2,3` },
  ],
  'Google Ads': [
    { key: 'raw_google_ads.perf_google_ads', sql: `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, ROUND(SUM(spend),2) spend, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_google_ads.perf_google_ads\` GROUP BY 1,2,3` },
    { key: 'raw_snowflake.google_ads_apac', sql: `SELECT CAST(CAMPAIGN_ID AS STRING) id, CAMPAIGN_NAME nm, ACCOUNT_NAME acct, ROUND(SUM(COSTS),2) spend, CAST(MAX(DAY) AS STRING) last_day FROM \`bidbrain-analytics.raw_snowflake.google_ads_apac\` GROUP BY 1,2,3` },
  ],
  Reddit: [
    { key: 'raw_windsor.perf_reddit', sql: `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, ROUND(SUM(spend),2) spend, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_reddit\` GROUP BY 1,2,3` },
  ],
};

/** An abbreviated intake name ("2193_..._ANZ") matches a real name that starts
 *  with the part before "..." and ends with the part after it. */
function abbrevMatch(intakeName, realName) {
  const i = String(intakeName).toLowerCase();
  const r = String(realName).toLowerCase();
  if (!i.includes('...')) return i === r;
  const [head, tail] = i.split('...');
  return r.startsWith(head.trim()) && r.endsWith(tail.trim());
}

async function main() {
  const wb = X.readFile(INTAKE);
  const rows = X.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '' });

  const pools = {};
  for (const [plat, feeds] of Object.entries(FEEDS)) {
    pools[plat] = [];
    for (const f of feeds) {
      const res = await q(f.sql);
      res.forEach((r) => pools[plat].push(Object.assign({ feed: f.key }, r)));
    }
  }

  const out = [];
  for (const r of rows) {
    const plat = String(r.Platform || '').trim();
    const ids = String(r['Campaign IDs'] || '').split(',').map((s) => s.trim()).filter(Boolean);
    const names = String(r['Platform Campaign Names'] || '').split('|').map((s) => s.trim()).filter(Boolean);
    const pool = pools[plat] || [];
    let hits = [];
    let method = 'UNRESOLVED';

    if (ids.length) {                                    // 1. exact id
      hits = pool.filter((x) => x.id && ids.includes(x.id));
      if (hits.length) method = 'campaign_id';
    }
    if (!hits.length && ids.length) {                    // 2. Excel-truncated id
      hits = pool.filter((x) => x.id && ids.some((i) => i.length >= 12 && x.id.startsWith(i)));
      if (hits.length) method = 'campaign_id (Excel-truncated, prefix-repaired)';
    }
    if (!hits.length && names.length) {                  // 3. name / group name
      hits = pool.filter((x) => x.nm && names.some((n) => abbrevMatch(n, x.nm)));
      if (hits.length) method = names.some((n) => n.includes('...')) ? 'name (abbreviated, prefix+suffix)' : 'name';
    }

    const spend = Math.round(hits.reduce((a, x) => a + Number(x.spend || 0), 0) * 100) / 100;
    const lastDay = hits.map((x) => x.last_day).filter(Boolean).sort().pop() || '';
    out.push({
      client: r.Client, platform: plat, tracker_campaign_name: r['Tracker Campaign Name'],
      join_method: method, feed: [...new Set(hits.map((x) => x.feed))].join(' + '),
      matched_objects: hits.length,
      matched_keys: hits.map((x) => x.id || x.nm).join(' | ').slice(0, 500),
      spend_to_date: spend, last_data_day: lastDay,
      budget: r['Budget (Total Budget)'], currency: r.Currency,
      flight_start: r['Flight Start'], flight_end: r['Flight End'], status: r.Status,
      intake_ids: r['Campaign IDs'],
    });
  }

  const byMethod = {};
  out.forEach((r) => { byMethod[r.join_method] = (byMethod[r.join_method] || 0) + 1; });
  console.log('=== JOIN METHOD THAT ACTUALLY WORKS (72 rows) ===');
  Object.entries(byMethod).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => console.log(`  ${String(v).padStart(3)}  ${k}`));
  console.log('\nresolved with real spend:', out.filter((r) => r.spend_to_date > 0).length, 'of 72');
  console.log('unresolved:', out.filter((r) => r.join_method === 'UNRESOLVED').length);
  console.log('\n=== STILL UNRESOLVED ===');
  out.filter((r) => r.join_method === 'UNRESOLVED')
    .forEach((r) => console.log(`  ${r.client} | ${r.platform} | ${r.tracker_campaign_name} (intake ids: ${r.intake_ids || 'none'})`));
  const cal = out.find((r) => /caltex/i.test(r.client));
  if (cal) console.log(`\nCALTEX: spend ${cal.spend_to_date} vs budget ${cal.budget} via ${cal.join_method} (data to ${cal.last_data_day})`);

  const head = Object.keys(out[0]);
  const ws = X.utils.aoa_to_sheet([head, ...out.map((r) => head.map((h) => r[h]))]);
  ws['!cols'] = head.map((h) => ({ wch: /matched_keys|tracker|join_method|feed/.test(h) ? 46 : 16 }));
  const wb2 = X.utils.book_new();
  X.utils.book_append_sheet(wb2, ws, 'Join keys');
  const outPath = path.join(__dirname, 'campaign_join_keys.xlsx');
  X.writeFile(wb2, outPath);
  console.log('\nwrote', outPath);
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
