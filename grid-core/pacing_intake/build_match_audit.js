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
// Queried at DAY grain so spend can be clamped to each campaign's flight
// window: pacing compares spend against a budget for a stated flight, and an
// all-time total put ResetData's always-on campaign at 237% of a monthly
// budget purely because it had been running longer than the window.
const FEEDS = {
  'Trade Desk': [
    ['raw_windsor.perf_the_trade_desk', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, advertiser_name acct, CAST(metric_date AS STRING) day, ROUND(SUM(cost),2) spend FROM \`bidbrain-analytics.raw_windsor.perf_the_trade_desk\` GROUP BY 1,2,3,4`],
    ['raw_snowflake.tradedesk_apac_all', `SELECT CAST(NULL AS STRING) id, CAMPAIGN_NAME nm, ADVERTISER_NAME acct, CAST(DAY AS STRING) day, ROUND(SUM(COSTS),2) spend FROM \`bidbrain-analytics.raw_snowflake.tradedesk_apac_all\` GROUP BY 1,2,3,4`],
  ],
  Meta: [
    ['raw_windsor.perf_meta', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, CAST(metric_date AS STRING) day, ROUND(SUM(cost),2) spend FROM \`bidbrain-analytics.raw_windsor.perf_meta\` GROUP BY 1,2,3,4`],
  ],
  LinkedIn: [
    ['raw_snowflake.linkedin_ads_apac', `SELECT CAST(NULL AS STRING) id, CAMPAIGN_GROUP_NAME nm, ACCOUNT_NAME acct, CAST(DAY AS STRING) day, ROUND(SUM(COSTS),2) spend FROM \`bidbrain-analytics.raw_snowflake.linkedin_ads_apac\` GROUP BY 1,2,3,4`],
    ['raw_windsor.perf_linkedin', `SELECT CAST(NULL AS STRING) id, campaign_group_name nm, account_name acct, CAST(metric_date AS STRING) day, ROUND(SUM(spend),2) spend FROM \`bidbrain-analytics.raw_windsor.perf_linkedin\` GROUP BY 1,2,3,4`],
  ],
  'Google Ads': [
    ['raw_google_ads.perf_google_ads', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, CAST(metric_date AS STRING) day, ROUND(SUM(spend),2) spend FROM \`bidbrain-analytics.raw_google_ads.perf_google_ads\` GROUP BY 1,2,3,4`],
    ['raw_snowflake.google_ads_apac', `SELECT CAST(CAMPAIGN_ID AS STRING) id, CAMPAIGN_NAME nm, ACCOUNT_NAME acct, CAST(DAY AS STRING) day, ROUND(SUM(COSTS),2) spend FROM \`bidbrain-analytics.raw_snowflake.google_ads_apac\` GROUP BY 1,2,3,4`],
  ],
  Reddit: [
    ['raw_windsor.perf_reddit', `SELECT CAST(campaign_id AS STRING) id, campaign_name nm, account_name acct, CAST(metric_date AS STRING) day, ROUND(SUM(spend),2) spend FROM \`bidbrain-analytics.raw_windsor.perf_reddit\` GROUP BY 1,2,3,4`],
  ],
};

/** Collapse day rows into one object per campaign, keeping the daily series so
 *  spend can later be summed over an arbitrary flight window. */
function foldToCampaigns(dayRows) {
  const by = new Map();
  for (const r of dayRows) {
    const k = `${r.id || ''}|${r.nm}|${r.acct}`;
    if (!by.has(k)) by.set(k, { id: r.id, nm: r.nm, acct: r.acct, spend: 0, first_day: r.day, last_day: r.day, days: new Map() });
    const g = by.get(k);
    g.spend = Math.round((g.spend + Number(r.spend || 0)) * 100) / 100;
    g.days.set(r.day, Math.round(((g.days.get(r.day) || 0) + Number(r.spend || 0)) * 100) / 100);
    if (r.day && r.day < g.first_day) g.first_day = r.day;
    if (r.day && r.day > g.last_day) g.last_day = r.day;
  }
  return [...by.values()];
}

/** Spend for one campaign inside [from, to]. Either bound may be absent, in
 *  which case that side is open. */
function spendInWindow(hit, from, to) {
  if (!from && !to) return Number(hit.spend || 0);
  let t = 0;
  for (const [d, v] of hit.days || []) {
    if (from && d < from) continue;
    if (to && d > to) continue;
    t += v;
  }
  return Math.round(t * 100) / 100;
}

/** Excel dates arrive as serials or strings; normalise to YYYY-MM-DD. */
function isoDate(v) {
  if (v == null || v === '') return '';
  if (typeof v === 'number') return new Date(Date.UTC(1899, 11, 30 + v)).toISOString().slice(0, 10);
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  const s = String(v).trim();
  const m = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/.exec(s);
  return m ? `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}` : s;
}

// Fold the dash family: the intake uses en dashes where the platforms use
// hyphens ("SE AirSeT 2026 - Retargeting"), which would otherwise miss.
const norm = (s) => String(s == null ? '' : s).replace(/[\u2010-\u2015\u2212]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const tok = (s) => norm(s).replace(/[^a-z0-9]+/g, '');
const words = (s) => norm(s).split(/[^a-z0-9]+/).filter((w) => w.length >= 3);
const money = (n) => Math.round(Number(n || 0) * 100) / 100;

function editDistance(a, b) {
  const m = a.length; const n = b.length;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[n];
}

/** Advertisers get renamed on-platform and the feed keeps BOTH spellings: the
 *  Trade Desk mirror holds this account as "PopTrack" AND "PropTrack", where
 *  the new spelling carries a 0.00 row and the old one carries all the money.
 *  A strict account filter therefore silently selects the empty twin, so treat
 *  near-identical account names as the same account. */
function sameAccount(intakeAcct, feedAcct) {
  const a = norm(intakeAcct); const b = norm(feedAcct);
  if (!a || !b) return false;
  if (a === b || a.includes(b) || b.includes(a)) return true;
  return Math.min(a.length, b.length) >= 6 && editDistance(a, b) <= 2;
}

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

/** "|" is both a separator and a legal character inside a name, so a short BQ
 *  name can look pipe-bounded inside a LONGER name that also matched ("QLD+WA"
 *  sits inside "Caltex Star Card | QLD+WA | Jul-Oct 2026"). Keep only maximal
 *  names: drop any hit whose name is a proper substring of another hit's name.
 *  Returns what was dropped so the audit says so out loud rather than quietly
 *  deciding for the reviewer. */
function dropSubsumed(hits) {
  const kept = hits.filter((a) => !hits.some((b) => b !== a
    && norm(b.nm).length > norm(a.nm).length && norm(b.nm).includes(norm(a.nm))));
  return { kept, dropped: hits.filter((h) => !kept.includes(h)).map((h) => h.nm) };
}

/** Abbreviated intake names ("2193_..._ANZ") are machine-generated and carry no
 *  internal pipes, so splitting them on "|" is safe. Returns head/tail token
 *  pairs that a real name must both start and end with. */
function abbrevPatterns(cell) {
  const s = String(cell || '');
  if (!s.includes('...')) return [];
  return s.split('|').map((p) => p.trim()).filter((p) => p.includes('...'))
    .map((p) => p.split('...').flatMap((seg) => words(seg)))
    .filter((w) => w.length);
}

/** An abbreviated name matches when its words all appear IN ORDER in the real
 *  name. "2265_..._IDE_INDIA" has to reach across the elided middle of
 *  "2265_MONGODB_2026-Q2_IDE_APJ_DEMAND-GENERATION_INDIA", so the tail cannot
 *  be required to be contiguous - but the ORDER still separates the IDE
 *  campaigns from the IDC ones. */
function wordsInOrder(pattern, name) {
  const hay = words(name);
  let i = 0;
  for (const w of pattern) {
    i = hay.indexOf(w, i);
    if (i === -1) return false;
    i += 1;
  }
  return true;
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

/** Match one intake row against ONE feed. Feeds are never summed together.
 *
 *  Ids and full names are globally distinctive, so they are matched across the
 *  WHOLE platform pool and the account is then used as a CHECK, not a filter -
 *  filtering first is what made PropTrack select its empty renamed twin. The
 *  weak signals (abbreviations, rule patterns) still need the account to scope
 *  them, since a token like "2193" is not distinctive on its own. */
function matchInFeed(row, feedRows, rules) {
  const ids = String(row['Campaign IDs'] || '').split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
  const namesCell = String(row['Platform Campaign Names'] || '');
  const acctName = row['Account Name'];
  const inAcct = feedRows.filter((x) => sameAccount(acctName, x.acct));
  const scoped = inAcct.length ? inAcct : feedRows;
  const done = (raw, method, conf, note) => {
    // Pull in the other naming vintage of anything matched. The abbreviation
    // patterns key on the brief number, so "2265_MONGODB_..._IDC_ANZ" matches
    // while the identical un-prefixed "MONGODB_..._IDC_ANZ" does not - and that
    // twin is the same campaign carrying real spend. Without this the audit
    // reports less than the sync, which is worse than either being wrong.
    const keys = new Set(raw.map((h) => bare(h.nm)));
    const withTwins = feedRows.filter((x) => keys.has(bare(x.nm)));
    const hits = mergeByName(withTwins.length >= raw.length ? withTwins : raw);
    return {
      hits, method, conf, note,
      acctScoped: !acctName || hits.every((h) => (h.accts || [h.acct]).some((a) => sameAccount(acctName, a))),
    };
  };

  // 1. exact campaign id (globally unique - no account scoping)
  let hits = ids.length ? feedRows.filter((x) => x.id && ids.includes(x.id)) : [];
  if (hits.length) return done(hits, 'campaign_id', 'EXACT', '');

  // 2. campaign id truncated by Excel float64, repaired by unique prefix
  if (ids.length) {
    hits = feedRows.filter((x) => x.id && ids.some((i) => i.length >= 12 && x.id.startsWith(i)));
    if (hits.length) return done(hits, 'campaign_id', 'EXACT', 'intake id was truncated by Excel float64; repaired by unique prefix');
  }

  // 3. full name present in the intake cell, matched as a whole segment.
  //    Compared with and without the brief-number prefix, since the intake and
  //    the feed can each be carrying either vintage of the same name.
  //    Separators are not meaningful in campaign names - LinkedIn shows
  //    "2040 SE_Microgrid_Awareness_July2026-AU" where the tracker writes
  //    "2040_SE_Microgrid_Awareness_july2026_AU" - so a name also matches when
  //    it is identical once every non-alphanumeric character is stripped. That
  //    loses the pipe boundaries, so it requires a long name to collide.
  const bareCell = String(namesCell).replace(/(^|\|)\s*\d+[_\s-]+/g, '$1');
  //    The tracker name is a name source too: MicroGrid's "Platform Campaign
  //    Names" cell only says "MicroGrid", while its TRACKER name tokenises
  //    exactly to the live group "2040 SE_Microgrid_Awareness_July2026-AU".
  const tokCell = tok(namesCell) + '|' + tok(row['Tracker Campaign Name']);
  const tokLoose = (x) => tok(x.nm).length >= 12 && tokCell.includes(tok(x.nm));
  hits = feedRows.filter((x) => x.nm && (boundedIn(x.nm, namesCell)
    || boundedIn(bare(x.nm), bareCell) || tokLoose(x)));
  if (hits.length) {
    const { kept, dropped } = dropSubsumed(hits);
    const isLI = String(row.Platform).trim() === 'LinkedIn';
    return done(kept, isLI ? 'group_name' : 'name', 'HIGH',
      dropped.length ? `ignored ${dropped.length} shorter name(s) contained inside a longer match: ${dropped.join(', ')}` : '');
  }

  // 4. abbreviated "..." names: head + tail tokens (account-scoped - weak signal)
  const pats = abbrevPatterns(namesCell);
  if (pats.length) {
    // Every word of the abbreviation is required, the brief number included:
    // it is the only discriminating token these patterns have. Dropping it so
    // the unprefixed vintage could match reduced "2479_..._ANZ" to "anz" and
    // swept in every Cloudflare campaign in the account.
    hits = scoped.filter((x) => x.nm && pats.some((p) => wordsInOrder(p, x.nm)));
    if (hits.length) return done(hits, 'name_pattern', 'PARTIAL', 'intake name is abbreviated with "..."; matched on its words in order');
  }

  // 5. approved campaignMatch rules from central-clients.json. A rule is
  //    relevant when one of its distinctive words appears in this row - token
  //    words, not the whole string, so "Key Growth Accounts IDC" still reaches
  //    the "IDC_APJ_DEMAND-GENERATION" rule.
  const rs = rules[norm(row.Client) + '|' + norm(row.Platform)] || [];
  const named = rs.filter((r) => r.value);
  // Relevance requires the rule's WHOLE value to appear in this row. Matching
  // on any shared word swept every NEL campaign into a Software First row:
  // "anz" is unique among the Schneider rules yet appears in nearly every
  // Schneider campaign, so rule-level rarity says nothing about the data. A
  // row that no rule claims outright belongs on the confirm list, not in a
  // guess.
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
      return done(hits, 'name_pattern', 'PARTIAL',
        'matched via approved campaignMatch rule(s): ' + relevant.map((r) => `${r.mode} "${r.value}"`).join(', '));
    }
  }

  // 6. a rule with an empty value means the WHOLE account rolls up
  if (rs.some((r) => !r.value) && inAcct.length) {
    return done(inAcct.slice(), 'account_rollup', 'PARTIAL',
      'approved rule has no campaign filter, so the entire account rolls up to this row');
  }

  // 7. Nothing in the feed, but the intake names real campaign ids. These are
  //    campaigns confirmed to exist on-platform that carry no rows yet: newly
  //    launched, paused, or a PMax campaign that standard campaign-level
  //    reports omit. They are NOT unresolved - they belong in the config so the
  //    sync starts counting them the moment data lands, with no second pass.
  if (ids.length) {
    return { hits: [], method: 'campaign_id (pending)', conf: 'EXACT', acctScoped: true,
      note: 'confirmed on-platform but no rows in the feed yet; carried so spend is picked up automatically' };
  }

  return { hits: [], method: 'UNRESOLVED', conf: '', acctScoped: false, note: '' };
}

/** Transmission is progressively prefixing campaign names with the brief number
 *  ("2265_MONGODB_..."), and BOTH vintages of the same campaign sit in the feed
 *  until the old one ages out. The repo-wide rule is to strip the prefix once
 *  and key off the remainder, so that is the identity used here. */
const bare = (s) => norm(s).replace(/^\d+[_\s-]+/, '');

/** Collapse hits that are the same campaign wearing a different label: the two
 *  brief-number vintages above, or the two advertiser spellings a rename leaves
 *  behind (PopTrack / PropTrack). Spend is summed, and every label that fed the
 *  merge is kept so the audit can show its working. */
function mergeByName(hits) {
  const by = new Map();
  for (const h of hits) {
    const k = bare(h.nm);
    if (!by.has(k)) { by.set(k, Object.assign({}, h, { accts: [h.acct], labels: [h.nm], days: new Map(h.days) })); continue; }
    const g = by.get(k);
    g.spend = money(Number(g.spend || 0) + Number(h.spend || 0));
    for (const [d, v] of h.days || []) g.days.set(d, money((g.days.get(d) || 0) + v));
    g.accts.push(h.acct);
    if (!g.labels.includes(h.nm)) g.labels.push(h.nm);
    if (String(h.nm).length > String(g.nm).length) g.nm = h.nm;
    if (h.first_day && (!g.first_day || h.first_day < g.first_day)) g.first_day = h.first_day;
    if (h.last_day && (!g.last_day || h.last_day > g.last_day)) g.last_day = h.last_day;
  }
  return [...by.values()];
}

/** For a row we could not resolve, offer the closest real campaign names so a
 *  human can confirm one instead of us guessing. Scored on shared words. */
function suggest(row, feedRows, n = 5) {
  const want = new Set(words(row['Tracker Campaign Name']).concat(words(row['Platform Campaign Names'])));
  if (!want.size) return [];
  return feedRows
    .map((x) => ({ nm: x.nm, acct: x.acct, spend: x.spend, score: words(x.nm).filter((w) => want.has(w)).length }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || Number(b.spend) - Number(a.spend))
    .slice(0, n);
}

async function main() {
  const wb = X.readFile(INTAKE);
  const rows = X.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '' });
  const rules = loadApprovedRules();

  const pools = {};
  for (const [plat, feeds] of Object.entries(FEEDS)) {
    pools[plat] = [];
    for (const [key, sql] of feeds) {
      const res = foldToCampaigns(await q(sql));
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
    const all = feeds.map((f) => Object.assign({ feed: f.feed }, matchInFeed(r, f.rows, rules)));
    // A pending result carries no rows by definition, so it only stands in when
    // no feed matched anything at all.
    const results = all.some((x) => x.hits.length) ? all.filter((x) => x.hits.length)
      : all.filter((x) => x.method === 'campaign_id (pending)').slice(0, 1);
    const RANK = { EXACT: 3, HIGH: 2, PARTIAL: 1 };
    const sum = (hs) => money(hs.reduce((s, h) => s + Number(h.spend || 0), 0));
    const fresh = (x) => x.hits.map((h) => h.last_day).filter(Boolean).sort().pop() || '';
    // FRESHNESS decides between overlapping mirrors. Windsor LinkedIn froze on
    // 2026-07-21 when the grant lapsed while Snowflake kept running, so the
    // later last_day is the more complete source - and this self-corrects if a
    // connector is re-authed, with no per-client list to maintain.
    results.sort((a, b) => (RANK[b.conf] || 0) - (RANK[a.conf] || 0)
      || fresh(b).localeCompare(fresh(a)) || b.hits.length - a.hits.length || sum(b.hits) - sum(a.hits));

    const primary = results[0] || { hits: [], method: 'UNRESOLVED', conf: '', note: '', feed: '', acctScoped: false };
    const hits = primary.hits;
    // Pacing compares spend against a budget for a STATED flight, so spend is
    // clamped to that window. All-time is kept alongside it, because a large
    // gap between the two means delivery outside the flight the intake declares.
    const fStart = isoDate(r['Flight Start']);
    const fEnd = isoDate(r['Flight End']);
    const spend = money(hits.reduce((a, h) => a + spendInWindow(h, fStart, fEnd), 0));
    const spendAll = sum(hits);
    // Only compare against another feed when it matched the SAME campaigns.
    // A feed that resolved a different set is not a second opinion on this
    // number, and reporting it as one produced nonsense like the same alt
    // figure appearing under three unrelated programs.
    const nameSet = (x) => x.hits.map((h) => norm(h.nm)).sort().join('~');
    const alt = results.slice(1).find((x) => nameSet(x) === nameSet(primary)) || null;
    const altSpend = alt ? sum(alt.hits) : '';

    const budget = Number(String(r['Budget (Total Budget)']).replace(/[^0-9.\-]/g, '')) || null;
    const expectedN = Number(r['# Campaigns']) || null;

    // Only flag what a human actually has to decide. A multi-match that hits
    // exactly the count the intake declared is a confirmation, not a warning.
    // Ids the intake declares that no feed row carries yet. Recorded per row so
    // the sync watches for them; a paused campaign that unpauses, or a new one
    // that syncs, is then picked up with no edit to the config.
    // An id is pending only when nothing represents that campaign yet. It is
    // NOT pending merely because the feed lacks an id column - Snowflake TTD
    // and LinkedIn carry no ids at all and are joined by name, so treating an
    // unseen id as pending there flagged almost every row. Where the feed does
    // carry ids, an id absent from the matched set is genuinely waiting.
    const idList = String(r['Campaign IDs'] || '').split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
    const feedHasIds = hits.length ? hits.some((h) => h.id)
      : feeds.some((f) => f.rows.some((x) => x.id));
    const matchedIds = new Set(hits.map((h) => String(h.id || '')).filter(Boolean));
    const pendingIds = !idList.length ? []
      : !hits.length ? idList
        : feedHasIds ? idList.filter((i) => !matchedIds.has(i)
          && ![...matchedIds].some((s) => i.length >= 12 && s.startsWith(i))) : [];

    // Feeds without ids can still be waiting on a campaign - a paused one the
    // intake names but that has never delivered. Detect those by name.
    const pendingNames = hits.length && !feedHasIds
      ? String(r['Platform Campaign Names'] || '').split('|').map((s) => s.trim())
        .filter((s) => s.length >= 6 && !s.includes('...')
          && !hits.some((h) => norm(h.nm) === norm(s) || bare(h.nm) === bare(s) || tok(h.nm) === tok(s)))
      : [];

    const flags = [];
    if (primary.method === 'UNRESOLVED') flags.push('NO MATCH - this row will be skipped, no pacing');
    if (/pending/.test(primary.method)) flags.push(`PENDING FEED: confirmed on-platform, no rows yet - ids ${pendingIds.join(', ')} are in the config and will start counting on the next sync`);
    else if (pendingIds.length && hits.length) flags.push(`PARTIALLY PENDING: ${pendingIds.length} declared id(s) carry no rows yet (${pendingIds.join(', ')}) - counted as 0 until they deliver`);
    if (pendingNames.length) flags.push(`PARTIALLY PENDING: ${pendingNames.length} named campaign(s) have never delivered (${pendingNames.join(', ')}) - counted as 0 until they do`);
    if (expectedN && hits.length && hits.length !== expectedN) {
      flags.push(`COUNT MISMATCH: intake says ${expectedN}, matched ${hits.length}`);
    } else if (hits.length > 1 && !expectedN) {
      flags.push(`MULTI-MATCH: ${hits.length} campaigns roll into this row - confirm they all belong`);
    }
    if (primary.conf === 'PARTIAL') flags.push('PATTERN MATCH - read the matched names before approving');
    if (hits.length && !primary.acctScoped) flags.push(`ACCOUNT DIFFERS: feed says "${[...new Set(hits.map((h) => h.acct))].join('", "')}"`);
    if (alt && Math.abs(altSpend - spend) > Math.max(1, spend * 0.01)) flags.push(`FEED DISAGREEMENT: ${primary.feed}=${spend} vs ${alt.feed}=${altSpend}`);
    if (!budget) flags.push('NO BUDGET - cannot compute a pacing ratio');
    if (hits.length && spend === 0 && spendAll === 0) flags.push('MATCHED BUT ZERO SPEND - check the campaign actually delivered');
    if (hits.length && spendAll > 0 && spend === 0) flags.push(`ALL SPEND IS OUTSIDE THE FLIGHT: ${spendAll} delivered, none between ${fStart || 'start'} and ${fEnd || 'end'} - check the flight dates`);
    else if (spendAll > spend * 1.05 && spend > 0) flags.push(`OUTSIDE FLIGHT: ${money(spendAll - spend)} of ${spendAll} delivered outside ${fStart || 'start'} to ${fEnd || 'end'} and is excluded`);

    // Say so when a campaign was counted under more than one label, so the
    // reviewer can see the brief-prefix and rename merges rather than wonder
    // why the count is lower than the list of names in the feed.
    const merged = hits.filter((h) => (h.labels || []).length > 1);
    if (merged.length) {
      flags.push(`MERGED LABELS: ${merged.length} campaign(s) appear in the feed under more than one name and were counted once - ${merged.map((h) => (h.labels || []).join(' = ')).join(' ; ')}`);
    }

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
      spend_in_flight: spend,
      spend_all_time: spendAll,
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
      pending_ids: pendingIds.join(', '),
      pending_names: pendingNames.join('\n'),
      intake_campaign_ids: String(r['Campaign IDs'] || ''),
      intake_platform_names: String(r['Platform Campaign Names'] || ''),
      review_notes: [primary.note].concat(flags).filter(Boolean).join(' | '),
      candidates: primary.method === 'UNRESOLVED'
        ? suggest(r, feeds.flatMap((f) => f.rows)).map((c) => `${c.nm}  [${c.acct}] ${c.spend}`).join('\n') : '',
    });
  }

  // The intake is at MEDIA PLAN LINE grain (format / phase / placement) while
  // the platforms report at CAMPAIGN grain, so several intake rows can name the
  // same platform campaigns. Importing each row as its own Central campaign
  // would count that spend once per row. The rollup is what actually gets
  // imported: one Central campaign per distinct campaign set, budgets summed.
  const rollup = [];
  const seenSet = new Map();
  for (const r of audit) {
    // A pending row has no matched names yet but is a real campaign, so it
    // earns its own Central row keyed on the ids it is waiting on.
    if (!r.matched_bq_names && !r.pending_ids) continue;
    const key = [r.client, r.platform, r.bq_table,
      r.matched_bq_names ? r.matched_bq_names.split('\n').sort().join('~') : `pending:${r.pending_ids}`].join('|');
    if (!seenSet.has(key)) {
      seenSet.set(key, {
        REVIEW_OK: '', client: r.client, platform: r.platform,
        campaign: r.tracker_campaign_name, intake_rows_merged: 0, intake_row_names: [],
        matched_bq_names: r.matched_bq_names, matched_bq_ids: r.matched_bq_ids,
        pending_ids: r.pending_ids, pending_names: r.pending_names, bq_table: r.bq_table,
        join_method: r.join_method, confidence: r.confidence,
        spend_in_flight: r.spend_in_flight, spend_all_time: r.spend_all_time, budget: 0,
        currency: r.currency, budget_basis: r.budget_basis, spend_mult: r.spend_mult,
        flight_start: r.flight_start, flight_end: r.flight_end,
        status: r.status, manager: r.manager, last_data_day: r.last_data_day,
      });
      rollup.push(seenSet.get(key));
    }
    const g = seenSet.get(key);
    g.intake_rows_merged += 1;
    g.intake_row_names.push(r.tracker_campaign_name);
    g.budget += Number(r.budget) || 0;
    if (r.flight_start && (!g.flight_start || String(r.flight_start) < String(g.flight_start))) g.flight_start = r.flight_start;
    if (r.flight_end && (!g.flight_end || String(r.flight_end) > String(g.flight_end))) g.flight_end = r.flight_end;
  }
  rollup.forEach((g) => {
    g.intake_row_names = [...new Set(g.intake_row_names)].join('\n');
    g.pct_budget = g.budget ? Math.round((g.spend_in_flight / g.budget) * 1000) / 10 + '%' : '';
  });

  const tally = (k) => audit.reduce((a, r) => { a[r[k]] = (a[r[k]] || 0) + 1; return a; }, {});
  const show = (label, k) => {
    console.log(`\n=== ${label} ===`);
    Object.entries(tally(k)).sort((a, b) => b[1] - a[1]).forEach(([v, n]) => console.log(`  ${String(n).padStart(3)}  ${v}`));
  };
  show('JOIN METHOD', 'join_method');
  show('CONFIDENCE', 'confidence');
  const resolved = audit.filter((r) => r.join_method !== 'UNRESOLVED');
  console.log(`\nresolved ${resolved.length} of ${audit.length}   with real spend: ${audit.filter((r) => r.spend_in_flight > 0 || r.spend_all_time > 0).length}   flagged for review: ${audit.filter((r) => r.review_notes).length}`);

  console.log('\n=== UNRESOLVED (will be skipped) ===');
  audit.filter((r) => r.join_method === 'UNRESOLVED')
    .forEach((r) => console.log(`  ${r.client} | ${r.platform} | ${r.tracker_campaign_name}`));

  const cal = audit.find((r) => /caltex/i.test(r.client));
  if (cal) {
    console.log('\n=== CALTEX END-TO-END CHECK ===');
    console.log(`  matched : ${cal.matched_bq_names}  (${cal.bq_table})`);
    console.log(`  method  : ${cal.join_method} / ${cal.confidence}`);
    console.log(`  spend   : ${cal.spend_in_flight} of ${cal.budget} ${cal.currency} = ${cal.pct_budget}   (all time ${cal.spend_all_time})`);
    console.log(`  window  : ${cal.flight_start} to ${cal.flight_end}, data through ${cal.last_data_day}`);
  }

  const width = (h) => (/matched_bq_names|review_notes|intake_platform_names|candidates|intake_row_names/.test(h) ? 58
    : /tracker|matched_bq_ids|bq_table|other_feed|account_name|intake_campaign_ids|campaign/.test(h) ? 28 : 13);
  const sheet = (data) => {
    const head = Object.keys(data[0]);
    const ws = X.utils.aoa_to_sheet([head, ...data.map((r) => head.map((h) => r[h]))]);
    ws['!cols'] = head.map((h) => ({ wch: width(h) }));
    ws['!autofilter'] = { ref: X.utils.encode_range({ s: { c: 0, r: 0 }, e: { c: head.length - 1, r: data.length } }) };
    ws['!freeze'] = { xSplit: 0, ySplit: 1 };
    return ws;
  };
  const wb2 = X.utils.book_new();
  const unresolved = audit.filter((r) => r.join_method === 'UNRESOLVED');
  const flagged = audit.filter((r) => r.review_notes && r.join_method !== 'UNRESOLVED');
  if (unresolved.length) X.utils.book_append_sheet(wb2, sheet(unresolved), 'Confirm these');
  if (flagged.length) X.utils.book_append_sheet(wb2, sheet(flagged), 'Needs review');
  X.utils.book_append_sheet(wb2, sheet(rollup), 'Rollup - goes to Central');
  X.utils.book_append_sheet(wb2, sheet(audit), 'All rows');

  const outX = path.join(__dirname, 'campaign_match_audit.xlsx');
  X.writeFile(wb2, outX);
  fs.writeFileSync(path.join(__dirname, 'campaign_match_audit.json'), JSON.stringify({ audit, rollup }, null, 2));

  // The match config is the reviewed output the sync reads: for each Central
  // campaign, which feed to read and which campaigns identify it. `pendingIds`
  // are confirmed on-platform but not yet in the feed - they are matched on
  // every sync, so a paused or newly launched campaign starts counting on its
  // own. Names are stored WITHOUT the brief-number prefix, since Transmission
  // adds those mid-flight and both vintages appear in the feed at once.
  const config = {
    generatedAt: new Date().toISOString().slice(0, 19) + 'Z',
    source: path.basename(INTAKE),
    note: 'Reviewed against platform screenshots and approved. Regenerate with build_match_audit.js; do not hand-edit.',
    campaigns: rollup.map((g) => ({
      client: g.client,
      platform: g.platform,
      campaign: g.campaign,
      table: g.bq_table,
      matchNames: g.matched_bq_names ? g.matched_bq_names.split('\n').filter(Boolean) : [],
      matchNameKeys: g.matched_bq_names ? [...new Set(g.matched_bq_names.split('\n').filter(Boolean).map(bare))] : [],
      matchIds: g.matched_bq_ids ? g.matched_bq_ids.split('\n').filter((s) => s && !s.startsWith('(')) : [],
      pendingIds: g.pending_ids ? g.pending_ids.split(', ').filter(Boolean) : [],
      pendingNames: g.pending_names ? g.pending_names.split('\n').filter(Boolean) : [],
      budget: g.budget || null,
      currency: g.currency || null,
      budgetBasis: g.budget_basis || null,
      spendMult: Number(g.spend_mult) || 1,
      flightStart: isoDate(g.flight_start) || null,
      flightEnd: isoDate(g.flight_end) || null,
      status: g.status || null,
      manager: g.manager || null,
      confidence: g.confidence,
      joinMethod: g.join_method,
      intakeRowsMerged: g.intake_rows_merged,
    })),
  };
  fs.writeFileSync(path.join(__dirname, 'campaign_match_config.json'), JSON.stringify(config, null, 2));

  const naive = audit.reduce((s, r) => s + (Number(r.spend_in_flight) || 0), 0);
  const rolled = rollup.reduce((s, r) => s + (Number(r.spend_in_flight) || 0), 0);
  console.log('\n=== GRAIN ===');
  console.log(`  ${audit.length} intake rows collapse to ${rollup.length} distinct platform campaign sets`);
  console.log(`  spend if every intake row were imported : ${Math.round(naive)}`);
  console.log(`  spend at campaign grain (the rollup)    : ${Math.round(rolled)}`);
  console.log(`  double counting avoided                 : ${Math.round(naive - rolled)}`);
  console.log(`\nwrote ${outX}`);
  console.log(`  sheet 1 "Confirm these"          ${unresolved.length} rows I could not match, each with candidate names`);
  console.log(`  sheet 2 "Needs review"           ${flagged.length} matched rows with something to check`);
  console.log(`  sheet 3 "Rollup - goes to Central" ${rollup.length} rows - this is what would actually be imported`);
  console.log(`  sheet 4 "All rows"               ${audit.length} rows, one per intake row`);
  console.log(`wrote ${path.join(__dirname, 'campaign_match_audit.json')}`);
  const pend = config.campaigns.filter((c) => c.pendingIds.length || c.pendingNames.length);
  console.log(`wrote ${path.join(__dirname, 'campaign_match_config.json')}  <- the sync reads this`);
  console.log(`  ${config.campaigns.length} Central campaigns, ${pend.length} waiting on ids that have not delivered yet:`);
  pend.forEach((c) => console.log(`    ${c.client} | ${c.campaign} -> ${c.pendingIds.concat(c.pendingNames).join(', ')}`));
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
