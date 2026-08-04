#!/usr/bin/env node
/*
 * scripts/backfill_currency.js — fill campaigns.currency, which is NULL on every row.
 *
 *   node scripts/backfill_currency.js            # dry run, writes nothing
 *   node scripts/backfill_currency.js --apply    # write
 *
 * WHY NOT central-clients.json: it has no currency field. Its 24 keys are advertiser/
 * campaign/cost/date column names, flight windows and free-text notes; currency appears
 * only inside those notes, and two of them are WRONG (HireRight "presumed USD
 * (unverified)" -> BigQuery says AUD; Ad Assembly BuyerX "Possible USD" -> AUD). So the
 * source of truth is config/currency-map.json, measured read-only from BigQuery, where
 * all 35 (table, advertiserValue) pairs resolve to exactly one currency.
 *
 * RESOLUTION: for each campaign, take its client's spec, keep the tables whose channel
 * matches the campaign's channel (normalised through pacing/pacing.js normPlatform, the
 * one canonical normaliser - 'TradeDesk'/'Trade Desk' -> ttd, 'facebook' -> meta), look
 * each up in the map, and accept the currency ONLY when the matching tables agree.
 *
 * Leaves NULL rather than guessing when: the client has no spec, no table matches the
 * channel, the table has no currency column (LinkedIn and Reddit - an account-name
 * suffix like _AUD is NOT parsed, that would be inference), or matching tables disagree.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const db = require(path.join(ROOT, 'src', 'brain', 'db'));
const { normPlatform } = require(path.join(ROOT, 'pacing', 'pacing'));

const APPLY = process.argv.includes('--apply');
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'central-clients.json'), 'utf8'));
const map = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'currency-map.json'), 'utf8'));

// same table -> channel defaulting as scripts/central_sync.py TABLE_CHANNEL
const TABLE_CHANNEL = {
  tradedesk_apac_all: 'Trade Desk', perf_the_trade_desk: 'Trade Desk',
  linkedin_ads_apac: 'LinkedIn', google_ads_apac: 'Google Ads', perf_google_ads: 'Google Ads',
  perf_meta: 'Meta', reddit_ads_apac_all: 'Reddit', perf_reddit: 'Reddit', dv360_apac: 'DV360'
};
const channelOf = t => t.channel || TABLE_CHANNEL[t.table] || t.table;

const specByClient = {};
for (const c of cfg.clients || []) specByClient[c.client] = c;

function resolve(campaign) {
  const spec = specByClient[campaign.client];
  if (!spec) return { currency: null, why: 'client not in central-clients.json' };
  const want = normPlatform(campaign.channel);
  if (!want) return { currency: null, why: 'campaign has no channel' };

  let matches = (spec.tables || []).filter(t => normPlatform(channelOf(t)) === want);
  if (!matches.length) return { currency: null, why: 'no table configured for this channel' };

  // A client can run several advertisers on ONE channel (Ad Assembly's TradeDesk seat
  // holds ACRS in AUD, Altech in USD and WEHI in AUD), so "all tables for this channel"
  // is ambiguous. The approved map entry for this campaign names its advertiser - when
  // there is one, narrow to it before reading the currency.
  const entry = (spec.map || []).find(m =>
    (m.campaignId && m.campaignId === campaign.id) ||
    (m.campaignName && m.campaignName === campaign.name && normPlatform(m.channel) === want));
  if (entry && entry.advertiserName) {
    const narrowed = matches.filter(t => t.advertiserValue === entry.advertiserName);
    if (narrowed.length) matches = narrowed;
  }

  const found = [], missing = [];
  for (const t of matches) {
    const hit = map.pairs[t.dataset + '.' + t.table + '||' + t.advertiserValue];
    if (hit) found.push(hit.currency);
    else missing.push(t.dataset + '.' + t.table);
  }
  const distinct = [...new Set(found)];
  if (!distinct.length) {
    const noCol = missing.some(m => map.noCurrencyColumn.includes(m));
    return { currency: null, why: noCol ? 'source table has no currency column' : 'advertiser not present in the currency map' };
  }
  if (distinct.length > 1) return { currency: null, why: 'matching tables disagree: ' + distinct.join('/') };
  return { currency: distinct[0], why: null };
}

const rows = db.getCampaigns().filter(c => !c.archivedAt);
const plan = [], skipped = [];
for (const c of rows) {
  const r = resolve(c);
  if (r.currency && r.currency !== c.currency) plan.push({ c, currency: r.currency });
  else if (!r.currency) skipped.push({ c, why: r.why });
}

console.log(`\ncurrency backfill  ·  ${rows.length} live campaigns  ·  ${APPLY ? 'APPLY' : 'DRY RUN'}`);
console.log(`resolved ${plan.length}   ·   left NULL ${skipped.length}\n`);

const byCur = {};
plan.forEach(p => { byCur[p.currency] = (byCur[p.currency] || 0) + 1; });
console.log('resolved by currency:', JSON.stringify(byCur));
const byChan = {};
plan.forEach(p => { const k = (p.c.channel || '?') + ' -> ' + p.currency; byChan[k] = (byChan[k] || 0) + 1; });
Object.keys(byChan).sort().forEach(k => console.log('   ' + k.padEnd(28) + byChan[k]));

console.log('\nleft NULL, by reason:');
const byWhy = {};
skipped.forEach(s => { byWhy[s.why] = (byWhy[s.why] || 0) + 1; });
Object.keys(byWhy).sort().forEach(w => console.log('   ' + String(byWhy[w]).padStart(3) + '  ' + w));
console.log('\n   the rows left NULL:');
skipped.forEach(s => console.log(`      ${String(s.c.client || '').slice(0, 16).padEnd(17)}${String(s.c.name || '').slice(0, 30).padEnd(31)}${String(s.c.channel || '-').padEnd(11)}${s.why}`));

if (APPLY) {
  const stmt = db.db.prepare('UPDATE campaigns SET currency=@currency, updatedAt=@t WHERE id=@id');
  const t = new Date().toISOString();
  db.db.transaction(() => plan.forEach(p => stmt.run({ currency: p.currency, t, id: p.c.id })))();
  console.log(`\nWROTE ${plan.length} rows.`);
} else {
  console.log('\nNothing written. Re-run with --apply.');
}
