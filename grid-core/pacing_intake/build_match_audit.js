// Pacing intake -> BigQuery MATCH AUDIT. READ ONLY. Wires nothing into Central.
//
// Produces campaign_match_audit.xlsx: one row per intake row showing exactly
// which BigQuery campaigns it resolves to, by which method, at what confidence,
// with every multi-match and every count mismatch flagged for a human to sign
// off. Nothing is imported until a person approves this file - a mismatched
// campaign silently corrupts pacing and would not surface until a client
// meeting.
//
// Join strategy is PER ROW, because no single key works across the feeds
// (verified 2026-08-11):
//   campaign_id  - Windsor TTD, Meta, Google Ads, Reddit (feeds carrying ids).
//                  EXACT. Meta ids in the intake lost their trailing digits to
//                  Excel float64 precision, so a >=12-char unique prefix
//                  repairs them (still EXACT - the prefix resolves to one row).
//   name         - full campaign name present in the intake. HIGH.
//   group_name   - LinkedIn: the intake holds campaign GROUP ids while the
//                  feeds store child CAMPAIGN ids plus the group NAME, so
//                  LinkedIn joins on the group name. HIGH.
//   name_pattern - Snowflake TTD (Cloudflare / MongoDB / Schneider / PropTrack)
//                  has NO campaign_id column at all, and some intake names are
//                  abbreviated with "...". Falls back to the campaignMatch
//                  rules already committed in config/central-clients.json.
//                  PARTIAL - always review these.
//
// Two traps this file deliberately handles:
//   1. "|" is NOT a safe delimiter. It separates multiple campaigns AND appears
//      inside single names ("Caltex Star Card | QLD+WA | Jul-Oct 2026",
//      "PMax Combined | All Inventory"). Splitting on it shreds real names, so
//      full names are matched by DELIMITER-BOUNDED CONTAINMENT against the raw
//      cell instead. Only the machine-abbreviated "..." forms are split.
//   2. Feeds OVERLAP (Snowflake TTD vs Windsor TTD, Snowflake vs DTS Google
//      Ads, Snowflake vs Windsor LinkedIn). Spend is NEVER summed across feeds
//      - one feed is primary, the other is reported alongside for comparison.
'use strict';

const fs = require('fs');
const path = require('path');
const GRID = path.join(__dirname, '..');
const X = require(path.join(GRID, 'node_modules', 'xlsx'));
const { BigQuery } = require(path.join(GRID, 'node_modules', '@google-cloud', 'bigquery'));

const INTAKE = process.argv[2] || 'C:/Users/DELL/Downloads/pacing_intake_FINAL.xlsx';
const bq = new BigQuery({ projectId: 'bidbrain-analytics' });
const q = async (sql) => (await bq.query({ query: sql, location: 'australia-southeast1' }))[0];

// One entry per feed. `nm` is the name at the grain we match on (campaign for
// most, campaign GROUP for LinkedIn). `id` is NULL where the feed has none.
const FEEDS = {
  'Trade Desk': [
    ['raw_windsor.perf_the_trade_desk', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, advertiser_name acct, ROUND(SUM(cost),2) spend, CAST(MIN(metric_date) AS STRING) first_day, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_the_trade_desk\` GROUP BY 1,2,3`],
    ['raw_snowflake.tradedesk_apac_all', `SELECT CAST(NULL AS STRING) id, CAMPAIGN_NAME nm, ADVERTISER_NAME acct, ROUND(SUM(COSTS),2) spend, CAST(MIN(DAY) AS STRING) first_day, CAST(MAX(DAY) AS STRING) last_day FROM \`bidbrain-analytics.raw_snowflake.tradedesk_apac_all\` GROUP BY 1,2,3`],
  ],
  Meta: [
    ['raw_windsor.perf_meta', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, ROUND(SUM(cost),2) spend, CAST(MIN(metric_date) AS STRING) first_day, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_meta\` GROUP BY 1,2,3`],
  ],
  LinkedIn: [
    ['raw_snowflake.linkedin_ads_apac', `SELECT CAST(NULL AS STRING) id, CAMPAIGN_GROUP_NAME nm, ACCOUNT_NAME acct, ROUND(SUM(COSTS),2) spend, CAST(MIN(DAY) AS STRING) first_day, CAST(MAX(DAY) AS STRING) last_day FROM \`bidbrain-analytics.raw_snowflake.linkedin_ads_apac\` GROUP BY 1,2,3`],
    ['raw_windsor.perf_linkedin', `SELECT CAST(NULL AS STRING) id, campaign_group_name nm, account_name acct, ROUND(SUM(spend),2) spend, CAST(MIN(metric_date) AS STRING) first_day, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_linkedin\` GROUP BY 1,2,3`],
  ],
  'Google Ads': [
    ['raw_google_ads.perf_google_ads', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, ROUND(SUM(spend),2) spend, CAST(MIN(metric_date) AS STRING) first_day, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_google_ads.perf_google_ads\` GROUP BY 1,2,3`],
    ['raw_snowflake.google_ads_apac', `SELECT CAST(CAMPAIGN_ID AS STRING) id, CAMPAIGN_NAME nm, ACCOUNT_NAME acct, ROUND(SUM(COSTS),2) spend, CAST(MIN(DAY) AS STRING) first_day, CAST(MAX(DAY) AS STRING) last_day FROM \`bidbrain-analytics.raw_snowflake.google_ads_apac\` GROUP BY 1,2,3`],
  ],
  Reddit: [
    ['raw_windsor.perf_reddit', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, ROUND(SUM(spend),2) spend, CAST(MIN(metric_date) AS STRING) first_day, CAST(MAX(metric_date) AS STRING) last_day FROM \`bidbrain-analytics.raw_windsor.perf_reddit\` GROUP BY 1,2,3`],
  ],
};

// Fold the dash family: the intake uses en dashes where the platforms use
// hyphens ("SE AirSeT 2026 - Retargeting"), which would otherwise miss.
const norm = (s) => String(s == null ? '' : s).replace(/[\u2010-\u2015\u2212]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const tok = (s) => norm(s).replace(/[^a-z0-9]+/g, '');
const money = (n) => Math.round(Number(n || 0) * 100) / 100;

/** True when `name` sits in `haystack` as a whole segment, not as a fragment of
 *  a longer name. Lets "PMax" match its own segment without also matching
 *  inside "PMax Combined", and lets a name that CONTAINS pipes match whole. */
function boundedIn(name, haystack) {
  const n = norm(name);
  const h = norm(haystack);
  if (n.length < 6 || !h) return false;
  let i = h.indexOf(n);
  while (i !== -1) {
    const pre = h.slice(0, i).replace(/\s+$/, '');
    const post = h.slice(i + n.length).replace(/^\s+/, '');
    if ((pre === '' || /[|,;]$/.test(pre)) && (post === '' || /^[|,;]/.test(post))) return true;
    i = h.indexOf(n, i + 1);
  }
  return false;
}

/** Abbreviated intake names ("2193_..._ANZ") are machine-generated and carry no
 *  internal pipes, so splitting them on "|" is safe. Returns head/tail token
 *  pairs that a real name must both start and end with. */
function abbrevPatterns(cell) {
  const s = String(cell || '');
  if (!s.includes('...')) return [];
  return s.split('|').map((p) => p.trim()).filter((p) => p.includes('...'))
    .map((p) => p.split('...').map((x) => norm(x).replace(/^[_\s-]+|[_\s-]+$/g, '')))
    .filter((p) => p[0] || p[1]);
}

/** campaignMatch rules already reviewed and committed in central-clients.json,
 *  keyed client|channel. Reused verbatim so the audit cannot invent a rule. */
function loadApprovedRules() {
  const cfg = JSON.parse(fs.readFileSync(path.join(GRID, 'config', 'central-clients.json'), 'utf8'));
  const out = {};
  for (const c of cfg.clients || []) {
    for (const m of c.map || []) {
      if (!m.campaignMatch) continue;
      const k = norm(c.client) + '|' + norm(m.channel);
      (out[k] = out[k] || []).push({ mode: m.campaignMatch.mode, value: m.campaignMatch.value || '' });
    }
  }
  return out;
}

/** Match one intake row against ONE feed. Feeds are never summed together. */
function matchInFeed(row, feedRows, rules) {
  const ids = String(row['Campaign IDs'] || '').split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
  const namesCell = String(row['Platform Campaign Names'] || '');
  const acctName = norm(row['Account Name']);

  const inAcct = feedRows.filter((x) => !acctName || norm(x.acct) === acctName
    || norm(x.acct).includes(acctName) || acctName.includes(norm(x.acct)));
  const scoped = inAcct.length ? inAcct : feedRows;
  const acctScoped = inAcct.length > 0;

  // 1. exact campaign id
  let hits = ids.length ? scoped.filter((x) => x.id && ids.includes(x.id)) : [];
  if (hits.length) return { hits, method: 'campaign_id', conf: 'EXACT', acctScoped, note: '' };

  // 2. campaign id truncated by Excel float64, repaired by unique prefix
  if (ids.length) {
    hits = scoped.filter((x) => x.id && ids.some((i) => i.length >= 12 && x.id.startsWith(i)));
    if (hits.length) {
      return { hits, method: 'campaign_id', conf: 'EXACT', acctScoped,
        note: 'intake id was truncated by Excel float64; repaired by unique prefix' };
    }
  }

  // 3. full name present in the intake cell, matched as a whole segment
  hits = scoped.filter((x) => x.nm && boundedIn(x.nm, namesCell));
  if (hits.length) {
    const isLI = String(row.Platform).trim() === 'LinkedIn';
    return { hits, method: isLI ? 'group_name' : 'name', conf: 'HIGH', acctScoped, note: '' };
  }

  // 4. abbreviated "..." names: head + tail tokens
  const pats = abbrevPatterns(namesCell);
  if (pats.length) {
    hits = scoped.filter((x) => x.nm && pats.some(([h, t]) => {
      const n = norm(x.nm);
      return (!h || n.includes(h)) && (!t || n.endsWith(t) || n.includes(t));
    }));
    if (hits.length) {
      return { hits, method: 'name_pattern', conf: 'PARTIAL', acctScoped,
        note: 'intake name is abbreviated with "..."; matched on its head and tail tokens' };
    }
  }

  // 5. approved campaignMatch rules from central-clients.json
  const rs = rules[norm(row.Client) + '|' + norm(row.Platform)] || [];
  const named = rs.filter((r) => r.value);
  const relevant = named.filter((r) => tok(namesCell).includes(tok(r.value))
    || tok(row['Tracker Campaign Name']).includes(tok(r.value)));
  if (relevant.length) {
    const seen = new Set();
    hits = [];
    for (const r of relevant) {
      const v = norm(r.value);
      for (const x of scoped) {
        const n = norm(x.nm);
        const ok = r.mode === 'exact' ? n === v : n.includes(v);
        if (ok && !seen.has(x.nm)) { seen.add(x.nm); hits.push(x); }
      }
    }
    if (hits.length) {
      return { hits, method: 'name_pattern', conf: 'PARTIAL', acctScoped,
        note: 'matched via approved campaignMatch rule(s): ' + relevant.map((r) => `${r.mode} "${r.value}"`).join(', ') };
    }
  }

  // 6. a rule with an empty value means the WHOLE account rolls up
  if (rs.some((r) => !r.value) && acctScoped) {
    return { hits: inAcct.slice(), method: 'account_rollup', conf: 'PARTIAL', acctScoped,
      note: 'approved rule has no campaign filter, so the entire account rolls up to this row' };
  }

  return { hits: [], method: 'UNRESOLVED', conf: '', acctScoped, note: '' };
}

async function main() {
  const wb = X.readFile(INTAKE);
  const rows = X.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '' });
  const rules = loadApprovedRules();

  const pools = {};
  for (const [plat, feeds] of Object.entries(FEEDS)) {
    pools[plat] = [];
    for (const [key, sql] of feeds) {
      const res = await q(sql);
      pools[plat].push({ feed: key, rows: res });
      console.error(`  loaded ${key}: ${res.length} campaigns`);
    }
  }

  const audit = [];
  for (const r of rows) {
    const plat = String(r.Platform || '').trim();
    const feeds = pools[plat] || [];

    // Match INDEPENDENTLY per feed, then pick one primary. Never sum across
    // feeds: the same campaign lives in both Snowflake and Windsor mirrors.
    const results = feeds.map((f) => Object.assign({ feed: f.feed }, matchInFeed(r, f.rows, rules)))
      .filter((x) => x.hits.length);
    const RANK = { EXACT: 3, HIGH: 2, PARTIAL: 1 };
    const sum = (hs) => money(hs.reduce((s, h) => s + Number(h.spend || 0), 0));
    results.sort((a, b) => (RANK[b.conf] || 0) - (RANK[a.conf] || 0)
      || b.hits.length - a.hits.length || sum(b.hits) - sum(a.hits));

    const primary = results[0] || { hits: [], method: 'UNRESOLVED', conf: '', note: '', feed: '', acctScoped: false };
    const alt = results[1] || null;
    const hits = primary.hits;
    const spend = sum(hits);
    const altSpend = alt ? sum(alt.hits) : '';

    const budget = Number(String(r['Budget (Total Budget)']).replace(/[^0-9.\-]/g, '')) || null;
    const expectedN = Number(r['# Campaigns']) || null;

    const flags = [];
    if (primary.method === 'UNRESOLVED') flags.push('NO MATCH - this row will be skipped, no pacing');
    if (hits.length > 1) flags.push(`MULTI-MATCH: ${hits.length} campaigns roll into this row - confirm they all belong`);
    if (expectedN && hits.length && hits.length !== expectedN) flags.push(`COUNT MISMATCH: intake says ${expectedN}, matched ${hits.length}`);
    if (primary.conf === 'PARTIAL') flags.push('PATTERN MATCH - read the matched names before approving');
    if (hits.length && !primary.acctScoped) flags.push('ACCOUNT NOT MATCHED: searched the whole platform, not just this account');
    if (alt && Math.abs(altSpend - spend) > Math.max(1, spend * 0.01)) flags.push(`FEED DISAGREEMENT: ${primary.feed}=${spend} vs ${alt.feed}=${altSpend}`);
    if (!budget) flags.push('NO BUDGET - cannot compute a pacing ratio');
    if (hits.length && spend === 0) flags.push('MATCHED BUT ZERO SPEND - check the campaign actually delivered');

    audit.push({
      REVIEW_OK: '',
      client: r.Client, platform: plat,
      tracker_campaign_name: r['Tracker Campaign Name'],
      join_method: primary.method,
      confidence: primary.conf || '-',
      matched_count: hits.length,
      expected_count: expectedN || '',
      matched_bq_names: hits.map((h) => h.nm).join('\n'),
      matched_bq_ids: hits.map((h) => h.id || '(feed carries no id)').join('\n'),
      bq_table: primary.feed,
      spend_to_date: spend,
      budget: budget || '',
      pct_budget: budget ? Math.round((spend / budget) * 1000) / 10 + '%' : '',
      other_feed: alt ? alt.feed : '',
      other_feed_spend: altSpend,
      first_data_day: hits.map((h) => h.first_day).filter(Boolean).sort()[0] || '',
      last_data_day: hits.map((h) => h.last_day).filter(Boolean).sort().pop() || '',
      flight_start: r['Flight Start'], flight_end: r['Flight End'],
      status: r.Status, currency: r.Currency, budget_basis: r['Budget Basis'],
      spend_mult: r['Spend Mult'], manager: r.Manager,
      account_name: r['Account Name'],
      intake_campaign_ids: String(r['Campaign IDs'] || ''),
      intake_platform_names: String(r['Platform Campaign Names'] || ''),
      review_notes: [primary.note].concat(flags).filter(Boolean).join(' | '),
    });
  }

  const tally = (k) => audit.reduce((a, r) => { a[r[k]] = (a[r[k]] || 0) + 1; return a; }, {});
  const show = (label, k) => {
    console.log(`\n=== ${label} ===`);
    Object.entries(tally(k)).sort((a, b) => b[1] - a[1]).forEach(([v, n]) => console.log(`  ${String(n).padStart(3)}  ${v}`));
  };
  show('JOIN METHOD', 'join_method');
  show('CONFIDENCE', 'confidence');
  const resolved = audit.filter((r) => r.join_method !== 'UNRESOLVED');
  console.log(`\nresolved ${resolved.length} of ${audit.length}   with real spend: ${audit.filter((r) => r.spend_to_date > 0).length}   flagged for review: ${audit.filter((r) => r.review_notes).length}`);

  console.log('\n=== UNRESOLVED (will be skipped) ===');
  audit.filter((r) => r.join_method === 'UNRESOLVED')
    .forEach((r) => console.log(`  ${r.client} | ${r.platform} | ${r.tracker_campaign_name}`));

  const cal = audit.find((r) => /caltex/i.test(r.client));
  if (cal) {
    console.log('\n=== CALTEX END-TO-END CHECK ===');
    console.log(`  matched : ${cal.matched_bq_names}  (${cal.bq_table})`);
    console.log(`  method  : ${cal.join_method} / ${cal.confidence}`);
    console.log(`  spend   : ${cal.spend_to_date} of ${cal.budget} ${cal.currency} = ${cal.pct_budget}`);
    console.log(`  window  : ${cal.flight_start} to ${cal.flight_end}, data through ${cal.last_data_day}`);
  }

  const head = Object.keys(audit[0]);
  const width = (h) => (/matched_bq_names|review_notes|intake_platform_names/.test(h) ? 58
    : /tracker|matched_bq_ids|bq_table|other_feed|account_name|intake_campaign_ids/.test(h) ? 28 : 13);
  const sheet = (data) => {
    const ws = X.utils.aoa_to_sheet([head, ...data.map((r) => head.map((h) => r[h]))]);
    ws['!cols'] = head.map((h) => ({ wch: width(h) }));
    ws['!autofilter'] = { ref: X.utils.encode_range({ s: { c: 0, r: 0 }, e: { c: head.length - 1, r: data.length } }) };
    ws['!freeze'] = { xSplit: 0, ySplit: 1 };
    return ws;
  };
  const wb2 = X.utils.book_new();
  X.utils.book_append_sheet(wb2, sheet(audit.filter((r) => r.review_notes)), 'Needs review');
  X.utils.book_append_sheet(wb2, sheet(audit), 'All rows');

  const outX = path.join(__dirname, 'campaign_match_audit.xlsx');
  X.writeFile(wb2, outX);
  fs.writeFileSync(path.join(__dirname, 'campaign_match_audit.json'), JSON.stringify(audit, null, 2));
  console.log(`\nwrote ${outX}`);
  console.log(`wrote ${path.join(__dirname, 'campaign_match_audit.json')}  (the import will read this file, once approved)`);
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
