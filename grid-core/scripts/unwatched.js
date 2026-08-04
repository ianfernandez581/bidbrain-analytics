#!/usr/bin/env node
/*
 * scripts/unwatched.js — campaigns SPENDING in BigQuery that the Grid cannot see.
 *
 *   node scripts/unwatched.js            # dry-run bytes, then query, print + write JSON
 *   node scripts/unwatched.js --dry      # report the dry-run bytes only, query nothing
 *
 * WHY: the Grid can only pace campaigns that exist in the campaigns table, which comes
 * from a spreadsheet. Anything delivering in BigQuery that was never typed in is
 * invisible - no budget, so no pacing verdict, and its spend is missing from every
 * portfolio figure. This script names that gap; it does NOT fix it (no rows are created,
 * no budgets are guessed).
 *
 * SCOPE: every validated:true client in config/central-clients.json whose campaigns sit
 * in the TRANSMISSION section of the campaigns DB, and every platform table on its spec.
 *
 * WATCHED means the BQ campaign name resolves to a campaign row by:
 *   1. the approved match rules in src/central/match.js (nameMatch, scoped by channel +
 *      advertiser exactly as matchCampaign does - rollup spans advertiser spellings), or
 *   2. campaignKey equality against a campaign row's name for that client.
 * campaignKey collapses the two name vintages: renames in this data are always the
 * addition of an NNNN_ prefix, so both forms reduce to one key. Resolution is deliberately
 * LENIENT (client-wide on the key, not per-channel) - this panel accuses a campaign of
 * being untracked, so a false accusation is worse than a miss.
 *
 * BigQuery: SELECT only, every query dry-run first, aborts if the total scan would
 * exceed 2 GB. Currency is READ from config/currency-map.json (measured, never inferred);
 * tables with no currency column (LinkedIn, Reddit) stay null rather than being guessed.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { BigQuery } = require('@google-cloud/bigquery');

const ROOT = path.join(__dirname, '..');
const PROJECT = process.env.BQ_PROJECT || 'bidbrain-analytics';
const BYTE_CAP = 2 * 1024 * 1024 * 1024;          // 2 GB, per the brief
const DRY_ONLY = process.argv.includes('--dry');
const OUT = path.join(ROOT, 'data', 'unwatched.json');

// The ONE normaliser for comparing names across the pre/post-rename vintages.
const campaignKey = n => String(n || '').replace(/^(PO_)?\d{4}[-_ ]\s*/, '').trim();

// same table -> channel defaulting as scripts/central_sync.py TABLE_CHANNEL
const TABLE_CHANNEL = {
  tradedesk_apac_all: 'Trade Desk', perf_the_trade_desk: 'Trade Desk',
  linkedin_ads_apac: 'LinkedIn', google_ads_apac: 'Google Ads', perf_google_ads: 'Google Ads',
  perf_meta: 'Meta', reddit_ads_apac_all: 'Reddit', perf_reddit: 'Reddit', dv360_apac: 'DV360'
};
const channelOf = t => t.channel || TABLE_CHANNEL[t.table] || t.table;

const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'central-clients.json'), 'utf8'));
const curMap = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'currency-map.json'), 'utf8'));
const { nameMatch } = require(path.join(ROOT, 'src', 'central', 'match.js'));
const db = require(path.join(ROOT, 'src', 'brain', 'db.js'));

const currencyOf = (t, advValue) => {
  const pair = (curMap.pairs || {})[t.dataset + '.' + t.table + '||' + advValue];
  return pair ? pair.currency : null;
};

// ---- scope: validated clients that are TRANSMISSION in the campaigns DB ----
const campaigns = db.getCampaigns().filter(c => !c.archivedAt);
const isTransmission = {};
campaigns.forEach(c => {
  if (String(c.section || '').toUpperCase().indexOf('TRANSMISSION') >= 0) isTransmission[c.client] = true;
});
const specs = (cfg.clients || []).filter(s => s.validated && isTransmission[s.client] && (s.tables || []).length);

// ---- the per-(client, table) queries ----
function buildQuery(t) {
  const cost = t.costColumn, date = t.dateColumn, camp = t.campaignColumn;
  if (!cost || !camp) return null;                 // no spend or no name column -> nothing to report
  const spend = `ROUND(SUM(SAFE_CAST(${cost} AS FLOAT64)), 2)`;
  return {
    query:
      `SELECT CAST(${camp} AS STRING) AS name, ${spend} AS spend, ` +
      (date ? `CAST(MIN(${date}) AS STRING) AS firstDate, CAST(MAX(${date}) AS STRING) AS lastDate `
            : `NULL AS firstDate, NULL AS lastDate `) +
      `FROM \`${PROJECT}.${t.dataset}.${t.table}\` ` +
      `WHERE ${t.advertiserColumn} = @adv AND ${camp} IS NOT NULL ` +
      `GROUP BY 1 HAVING ${spend} > 0 ORDER BY spend DESC`,
    params: { adv: t.advertiserValue }
  };
}

// A BQ name is watched if an approved match rule claims it, or its key equals a row's key.
function resolves(spec, channel, advertiser, name, keysByClient) {
  const key = campaignKey(name);
  if ((keysByClient[spec.client] || {})[key]) return 'campaign row (key match)';
  const rules = spec.map || [];
  for (const m of rules) {
    const cm = m.campaignMatch || {};
    const rollup = cm.mode === 'rollup';
    if (m.channel !== channel) continue;
    if (!rollup && m.advertiserName !== advertiser) continue;      // rollup spans spellings
    if (nameMatch(cm, name)) return 'match rule: ' + cm.mode + ' "' + cm.value + '"';
    // exact rules are written against ONE vintage of the name; compare on the key too
    if (cm.mode === 'exact' && cm.value != null && campaignKey(cm.value) === key) return 'match rule: exact (key match)';
  }
  return null;
}

(async () => {
  const bq = new BigQuery({ projectId: PROJECT });
  const jobs = [];
  for (const spec of specs) {
    for (const t of spec.tables || []) {
      const q = buildQuery(t);
      if (!q) { console.warn(`SKIP ${spec.client} ${t.dataset}.${t.table}: no cost/campaign column`); continue; }
      jobs.push({ spec, t, channel: channelOf(t), q });
    }
  }
  if (!jobs.length) { console.error('No queryable (client, table) pairs in scope.'); process.exit(1); }

  console.log(`Scope: ${specs.length} validated Transmission client(s), ${jobs.length} platform quer${jobs.length === 1 ? 'y' : 'ies'}\n`);

  // ---- 1. dry run everything, enforce the 2 GB cap BEFORE reading a byte ----
  let totalBytes = 0;
  for (const j of jobs) {
    const [job] = await bq.createQueryJob({ query: j.q.query, params: j.q.params, dryRun: true });
    const bytes = Number(job.metadata.statistics.totalBytesProcessed || 0);
    j.bytes = bytes; totalBytes += bytes;
    console.log(`  dry-run ${(bytes / 1048576).toFixed(1).padStart(9)} MB  ${j.spec.client} · ${j.channel} · ${j.t.advertiserValue}`);
  }
  const gb = (totalBytes / 1073741824).toFixed(3);
  console.log(`\nTotal dry-run scan: ${totalBytes.toLocaleString()} bytes (${gb} GB) · cap 2.000 GB`);
  if (totalBytes > BYTE_CAP) {
    console.error(`ABORT: would scan ${gb} GB, over the 2 GB cap. Nothing was queried.`);
    process.exit(2);
  }
  if (DRY_ONLY) { console.log('--dry: stopping before the real queries.'); return; }

  // ---- 2. campaign-row keys per client (the rename-tolerant fallback) ----
  const keysByClient = {};
  campaigns.forEach(c => {
    const k = campaignKey(c.name);
    if (!k) return;
    (keysByClient[c.client] = keysByClient[c.client] || {})[k] = true;
  });

  // ---- 3. run, resolve, collect ----
  const unwatched = [];
  let seen = 0, watched = 0;
  for (const j of jobs) {
    const [rows] = await bq.query({ query: j.q.query, params: j.q.params });
    const currency = currencyOf(j.t, j.t.advertiserValue);
    for (const r of rows) {
      seen++;
      const why = resolves(j.spec, j.channel, j.t.advertiserValue, r.name, keysByClient);
      if (why) { watched++; continue; }
      unwatched.push({
        client: j.spec.client, platform: j.channel, advertiser: j.t.advertiserValue,
        campaign: r.name, spend: Number(r.spend) || 0, currency,
        firstDate: r.firstDate ? String(r.firstDate).slice(0, 10) : null,
        lastDate: r.lastDate ? String(r.lastDate).slice(0, 10) : null,
        source: j.t.dataset + '.' + j.t.table
      });
    }
  }
  unwatched.sort((a, b) => b.spend - a.spend);

  // totals PER CURRENCY - never sum across them (currency-map leaves LinkedIn/Reddit null)
  const byCurrency = {};
  unwatched.forEach(r => {
    const k = r.currency || 'unknown';
    byCurrency[k] = Math.round(((byCurrency[k] || 0) + r.spend) * 100) / 100;
  });
  const total = Math.round(unwatched.reduce((s, r) => s + r.spend, 0) * 100) / 100;

  const doc = {
    generatedAt: new Date().toISOString(),
    scope: { clients: specs.map(s => s.client), queries: jobs.length },
    bytesScanned: totalBytes,
    bqCampaignsSeen: seen, watched, unwatchedCount: unwatched.length,
    total, byCurrency,
    note: 'Campaigns delivering in BigQuery with no campaign row, so no budget and no pacing verdict. '
        + 'Currency is measured (config/currency-map.json); null = the source table has no currency column. '
        + 'total is a face-value sum and MIXES currencies - read byCurrency.',
    rows: unwatched
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(doc, null, 1));

  // ---- 4. print ----
  const money = n => n.toLocaleString('en-AU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  console.log(`\nBQ campaigns with spend: ${seen} · watched ${watched} · UNWATCHED ${unwatched.length}\n`);
  console.log('PLATFORM    ADVERTISER                        CAMPAIGN                                           SPEND  CUR  FIRST       LAST');
  for (const r of unwatched) {
    console.log([String(r.platform).padEnd(11), String(r.advertiser).slice(0, 33).padEnd(33),
      String(r.campaign).slice(0, 48).padEnd(48), money(r.spend).padStart(12),
      String(r.currency || '?').padEnd(4), String(r.firstDate || '?').padEnd(11), String(r.lastDate || '?')].join(' '));
  }
  console.log('\nTotals per currency (never summed across):');
  Object.keys(byCurrency).sort().forEach(k => console.log(`  ${k.padEnd(8)} ${money(byCurrency[k]).padStart(14)}`));
  console.log(`  ${'FACE SUM'.padEnd(8)} ${money(total).padStart(14)}  <- mixes currencies, shown for reference only`);
  console.log(`\nWrote ${path.relative(ROOT, OUT)}`);
})().catch(e => { console.error('FAILED:', e.message); process.exit(1); });
