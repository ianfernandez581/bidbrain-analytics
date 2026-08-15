// Batched pacing sync: BigQuery -> Central metric columns. DRY RUN BY DEFAULT.
//
//   node pacing_intake/pacing_sync.js            # show what would be written
//   node pacing_intake/pacing_sync.js --apply    # write it
//
// ONE query per platform table, never one per campaign: eight queries cover the
// whole book regardless of how many campaigns are in it, so adding a client
// costs no extra round trips.
//
// It writes ONLY metric columns, through db.syncCampaignMetrics, which owns the
// spendMult rule (billed = media x mult) and refuses to overwrite a clientSpend
// that already holds a different sheet figure. Budgets, dates and every other
// CONFIG field belong to import_campaigns.js. Pacing itself is never written
// anywhere - pctBudgetSpent, pacingStatus and the rest are DERIVED in calc.js
// from budget + flight + spend, and db.js rejects any attempt to set them.
//
// Spend is summed only BETWEEN each campaign's flight dates. Pacing compares
// spend against a budget for a stated flight, so an always-on campaign that
// predates its window must not bring its earlier spend along.
'use strict';

const fs = require('fs');
const path = require('path');
const GRID = path.join(__dirname, '..');
const db = require(path.join(GRID, 'src', 'brain', 'db.js'));
const { BigQuery } = require(path.join(GRID, 'node_modules', '@google-cloud', 'bigquery'));
const { resolveAll } = require(path.join(__dirname, 'resolve_central.js'));
const persist = require(path.join(GRID, 'src', 'brain', 'persist.js'));

/** Push the DB back to GCS. The CLI has no shutdown hook and persist.saveSoon()
 *  is debounced, so a script that exits immediately would write the local file
 *  and never upload - the whole run would silently not reach production. A
 *  generation conflict means another instance wrote first; the upload is
 *  refused rather than clobbering it, and that is reported as a failure. */
async function flushState() {
  if (!persist.enabled()) { console.log('\nstate: local file only (GRID_STATE_BUCKET unset) - nothing uploaded'); return true; }
  const r = await persist.save();
  if (r.ok) { console.log(`\nstate: uploaded to gs://${persist.bucket}/${persist.object} (generation ${r.generation})`); return true; }
  console.error(`\nSTATE NOT UPLOADED: ${r.reason}`);
  if (r.reason === 'generation-conflict') console.error('another process wrote the state file first. Nothing was published; re-run once it is idle.');
  return false;
}


const APPLY = process.argv.includes('--apply');
const INCLUDE_ENDED = process.argv.includes('--includeEnded');
const CONFIG = path.join(__dirname, 'campaign_match_config.json');
const bq = new BigQuery({ projectId: 'bidbrain-analytics' });
const P = 'bidbrain-analytics.';

// One batched query per table. Columns are aliased identically so the caller
// never has to know which feed a row came from - the per-feed column names
// differ (spend vs cost vs COSTS, IMPRESSION vs IMPRESSIONS) and an unaliased
// query silently returns f0_/f1_, which is how an earlier build lost every id.
const TABLES = {
  'raw_windsor.perf_the_trade_desk': `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, CAST(metric_date AS STRING) day, SUM(cost) spend, SUM(impressions) imps FROM \`${P}raw_windsor.perf_the_trade_desk\` GROUP BY 1,2,3`,
  // COALESCE both spellings: this table carries IMPRESSIONS and IMPRESSION, and
  // the populated one varies by advertiser (PropTrack's counts live in the
  // singular column). Reading only IMPRESSIONS reported 0 impressions against
  // real spend for every Snowflake Trade Desk campaign.
  'raw_snowflake.tradedesk_apac_all': `SELECT CAST(NULL AS STRING) id, CAMPAIGN_NAME nm, CAST(DAY AS STRING) day, SUM(COSTS) spend, SUM(COALESCE(IMPRESSIONS, 0) + COALESCE(IMPRESSION, 0)) imps FROM \`${P}raw_snowflake.tradedesk_apac_all\` GROUP BY 1,2,3`,
  'raw_windsor.perf_meta': `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, CAST(metric_date AS STRING) day, SUM(cost) spend, SUM(impressions) imps FROM \`${P}raw_windsor.perf_meta\` GROUP BY 1,2,3`,
  'raw_snowflake.linkedin_ads_apac': `SELECT CAST(NULL AS STRING) id, CAMPAIGN_GROUP_NAME nm, CAST(DAY AS STRING) day, SUM(COSTS) spend, SUM(IMPRESSIONS) imps FROM \`${P}raw_snowflake.linkedin_ads_apac\` GROUP BY 1,2,3`,
  'raw_windsor.perf_linkedin': `SELECT CAST(NULL AS STRING) id, campaign_group_name nm, CAST(metric_date AS STRING) day, SUM(spend) spend, SUM(impressions) imps FROM \`${P}raw_windsor.perf_linkedin\` GROUP BY 1,2,3`,
  'raw_google_ads.perf_google_ads': `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, CAST(metric_date AS STRING) day, SUM(spend) spend, SUM(impressions) imps FROM \`${P}raw_google_ads.perf_google_ads\` GROUP BY 1,2,3`,
  'raw_snowflake.google_ads_apac': `SELECT CAST(CAMPAIGN_ID AS STRING) id, CAMPAIGN_NAME nm, CAST(DAY AS STRING) day, SUM(COSTS) spend, SUM(IMPRESSIONS) imps FROM \`${P}raw_snowflake.google_ads_apac\` GROUP BY 1,2,3`,
  'raw_windsor.perf_reddit': `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, CAST(metric_date AS STRING) day, SUM(spend) spend, SUM(impressions) imps FROM \`${P}raw_windsor.perf_reddit\` GROUP BY 1,2,3`,
};

const norm = (s) => String(s == null ? '' : s).replace(/[‐-―−]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const tok = (s) => norm(s).replace(/[^a-z0-9]+/g, '');
const bare = (s) => norm(s).replace(/^\d+[_\s-]+/, '');
const chan = (s) => tok(s).replace(/^ttd$/, 'tradedesk');
const money = (n) => Math.round(Number(n || 0) * 100) / 100;


/** Core, callable from the CLI below and from server.js. `quiet` suppresses the
 *  per-campaign listing so a scheduled tick logs one line, not forty. */
async function runPacingSync(opts) {
  opts = opts || {};
  const apply = !!opts.apply;
  const quiet = !!opts.quiet;
  const say = (...a) => { if (!quiet) console.log(...a); };
  if (!fs.existsSync(CONFIG)) throw new Error(`missing ${path.basename(CONFIG)} - run build_match_audit.js first`);
  const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'));
  const campaigns = db.getCampaigns();

  // Only query the tables this config actually references.
  const needed = [...new Set(cfg.campaigns.map((c) => c.table).filter((t) => TABLES[t]))];
  const rowsByTable = {};
  for (const t of needed) {
    const [rows] = await bq.query({ query: TABLES[t], location: 'australia-southeast1' });
    rowsByTable[t] = rows;
    say(`  ${t}: ${rows.length} campaign-days`);
  }
  say(`\n${needed.length} queries for ${cfg.campaigns.length} campaigns\n`);

  // ONE resolution pass, shared with the import, so both write to the same row.
  const { resolved, reassigned } = resolveAll(cfg.campaigns, campaigns);
  if (reassigned.length) {
    say(`resolved ${reassigned.length} duplicate-name campaign(s) one-to-one by budget:`);
    reassigned.forEach((x) => say(`  "${x.line}" (budget ${x.budget}) -> ${x.to}`));
    say('');
  }
  const rowFor = new Map(resolved.map((r) => [r.c, r.row]));

  const out = [];
  for (const c of cfg.campaigns) {
    const rows = rowsByTable[c.table] || [];
    const ids = new Set(c.matchIds || []);
    const pending = new Set(c.pendingIds || []);
    const names = new Set((c.matchNameKeys || []).map(bare));
    const pendingNames = new Set((c.pendingNames || []).map(bare));
    let spend = 0; let imps = 0; let last = '';
    for (const r of rows) {
      const idHit = r.id && (ids.has(String(r.id)) || pending.has(String(r.id)));
      const nameHit = r.nm && (names.has(bare(r.nm)) || pendingNames.has(bare(r.nm)));
      if (!idHit && !nameHit) continue;
      if (c.flightStart && r.day < c.flightStart) continue;
      if (c.flightEnd && r.day > c.flightEnd) continue;
      spend += Number(r.spend || 0);
      imps += Number(r.imps || 0);
      if (r.day > last) last = r.day;
    }
    const row = rowFor.get(c) || null;
    out.push({ c, row, spend: money(spend), imps: Math.round(imps), last });
  }

  const hits = out.filter((o) => o.row);
  const missing = out.filter((o) => !o.row);
  say(apply ? '=== WRITING ===' : '=== WOULD WRITE ===');
  hits.sort((a, b) => b.spend - a.spend).forEach((o) => {
    const pct = o.c.budget ? Math.round((o.spend / o.c.budget) * 1000) / 10 + '%' : '-';
    say(`  ${(o.c.client + ' | ' + o.c.campaign).padEnd(44).slice(0, 44)} spend ${String(o.spend).padStart(10)}  imps ${String(o.imps).padStart(9)}  of ${String(o.c.budget || '-').padStart(8)} = ${pct.padStart(7)}  -> ${o.row.id}`);
  });
  if (missing.length) {
    say(`\n=== NO CENTRAL ROW (${missing.length}) - run import_campaigns.js --apply first ===`);
    missing.forEach((o) => say(`  ${o.c.client} | ${o.c.platform} | ${o.c.campaign}  (spend ${o.spend} would be written)`));
  }
  const zero = hits.filter((o) => o.spend === 0);
  if (zero.length) say(`\n${zero.length} campaign(s) resolve to zero in-flight spend (pending or not yet delivering): ${zero.map((o) => o.c.campaign).join(', ')}`);

  const summary = {
    syncedAt: new Date().toISOString(), applied: apply, queries: needed.length,
    campaigns: cfg.campaigns.length, matched: hits.length, unmatched: missing.length,
    updated: 0, skipped: [],
  };
  if (!apply) { say('\nDRY RUN - nothing was written. Re-run with --apply.'); return summary; }

  for (const o of hits) {
    const r = db.syncCampaignMetrics(o.row.id, o.imps || null, o.spend, { includeEnded: !!opts.includeEnded });
    if (r.ok) summary.updated++; else summary.skipped.push(`${o.c.client}/${o.c.campaign}: ${r.reason}`);
  }
  db.setMeta('pacingLastSync', { at: summary.syncedAt, updated: summary.updated, campaigns: cfg.campaigns.length });
  say(`\nAPPLIED: ${summary.updated} campaigns updated.`);
  if (summary.skipped.length && !quiet) { console.log('skipped:'); summary.skipped.forEach((s) => console.log('  ' + s)); }
  return summary;
}

module.exports = { runPacingSync };

// CLI entry point. Guarded so requiring this from server.js never triggers a
// sync as a side effect of the import.
if (require.main === module) {
  runPacingSync({ apply: APPLY, includeEnded: INCLUDE_ENDED })
    .then(async (r) => { if (r && r.applied && !(await flushState())) process.exitCode = 1; })
    .catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
}
