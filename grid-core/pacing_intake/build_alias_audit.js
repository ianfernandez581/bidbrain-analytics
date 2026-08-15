// Decide, for every intake campaign that name-matching does NOT find in Central,
// whether it is an ALIAS of a live row or a genuinely NEW campaign. READ ONLY:
// writes an audit workbook and campaign_aliases.json, and creates nothing.
//
// Why this file exists: Central names campaigns short ("Airset", "EBA", "46113")
// while the intake names them by media-plan line
// ("2223_SE_Airset SM_ANZ_display_AWR"). Bigram similarity scores those below
// threshold, so the importer called 16 of 17 "new" and would have created
// duplicate rows beside live campaigns already carrying the same spend.
//
// Three sources of truth, strongest first, each recorded per row so the sheet
// shows WHY a decision was made:
//   1. rule  - the Central row's campaignMatch rule matches one of the real BQ
//              campaign names the intake resolved. Both sides point at the same
//              BigQuery campaign, so this is a verifiable join, not a guess.
//   2. human - a decision recorded in DECISIONS below, from the review.
//   3. none  - no evidence either way; left UNRESOLVED and imported as nothing.
'use strict';

const fs = require('fs');
const path = require('path');
const GRID = path.join(__dirname, '..');
const X = require(path.join(GRID, 'node_modules', 'xlsx'));
const db = require(path.join(GRID, 'src', 'brain', 'db.js'));
// findExisting, NOT resolveAll: resolveAll consults campaign_aliases.json, which
// is this file's OUTPUT. Using it would mean every regeneration saw the aliased
// rows as already-matched, dropped them, and rewrote the file with only the
// creates - erasing the decisions it exists to record. Raw name matching keeps
// the full set of undecided campaigns in view every run.
const { findExisting, similarity, norm, chan } = require(path.join(__dirname, 'resolve_central.js'));

const CONFIG = path.join(__dirname, 'campaign_match_config.json');

// Reviewed decisions. `new` = create it; a row id = alias of that Central row;
// `null` = still undecided, nothing is imported for it.
// Keyed client|platform|campaign, exactly as the config spells them.
const DECISIONS = {
  'Schneider|LinkedIn|2040_SE_Microgrid_Awareness_july2026_AU': { verdict: 'new', why: 'confirmed: not in Central yet' },
  'Schneider|LinkedIn|Ecoconsult AWR': { verdict: 'new', why: 'confirmed: never in Central' },
  'Schneider|LinkedIn|Ecoconsult CNS': { verdict: 'new', why: 'confirmed: never in Central' },
  'Schneider|LinkedIn|Ecoconsult CVS': { verdict: 'new', why: 'confirmed: never in Central' },
  'Schneider|LinkedIn|MCSet Awareness': { verdict: 'new', why: 'confirmed: just launched' },
  'Schneider|Google Ads|MCSet Awareness': { verdict: 'new', why: 'confirmed: just launched' },
  'Schneider|Trade Desk|2463_SE_Industrial Edge Wave3_ANZ_display_AWR': { alias: 'cmp-73f509149be8', why: 'confirmed alias of "Industrial Edge Wave 3 Prefab Unprotected" (TradeDesk)' },
  'Schneider|Google Ads|2061_SE_Advancing Energy Technology_ANZ_keywords_CNV': { alias: 'cmp-1aaf944e0084', why: 'confirmed alias of "Advancing Energy T" (Google Ads)' },
  'ResetData|Reddit|Always On': { alias: 'cmp-74790bdcf864', why: 'confirmed alias of ResetData "46113" (Reddit)' },
  // Heavy Industries: Central holds TWO rows of that name, both blank-channel,
  // Not Active, no budget and no spend - placeholders that were never wired up.
  // Nothing says which is the Trade Desk lane and which is LinkedIn, so rather
  // than guess, both intake lines come in as clean new rows and the inert pair
  // is left alone (archive them in the UI if you want them out of the way).
  'Schneider|Trade Desk|2281_SE_Heavy Industries_ANZ_display_P1_AWR': { verdict: 'new', why: 'confirmed new: the two blank-channel "Heavy Industries" rows are inert placeholders, not this lane' },
  'Schneider|LinkedIn|2281_SE_Heavy Industries_ANZ_leadgen_P2_CNV': { verdict: 'new', why: 'confirmed new: the two blank-channel "Heavy Industries" rows are inert placeholders, not this lane' },
};

function loadRules(campaigns) {
  const clients = JSON.parse(fs.readFileSync(path.join(GRID, 'config', 'central-clients.json'), 'utf8'));
  const byRow = new Map();
  (clients.clients || []).forEach((spec) => (spec.map || []).forEach((m) => {
    if (!m.campaignMatch || !m.campaignMatch.value) return;
    const row = m.campaignId ? campaigns.find((p) => p.id === m.campaignId)
      : campaigns.find((p) => p.client === spec.client && p.name === m.campaignName);
    if (!row) return;
    if (!byRow.has(row.id)) byRow.set(row.id, []);
    byRow.get(row.id).push({ mode: m.campaignMatch.mode, value: m.campaignMatch.value });
  }));
  return byRow;
}

/** Central rows whose campaignMatch rule claims one of the BQ campaigns this
 *  intake entry resolved to. Same client and channel required. */
function ruleLinks(c, campaigns, rulesByRow) {
  const names = (c.matchNames || []).map(norm);
  if (!names.length) return [];
  const out = [];
  for (const [rowId, rules] of rulesByRow) {
    const row = campaigns.find((p) => p.id === rowId);
    if (!row || norm(row.client) !== norm(c.client) || chan(row.channel) !== chan(c.platform)) continue;
    const hit = rules.find((r) => {
      const v = norm(r.value);
      return names.some((n) => (r.mode === 'exact' ? n === v : n.includes(v)));
    });
    if (hit) out.push({ row, rule: `${hit.mode} "${hit.value}"` });
  }
  return out;
}

function main() {
  const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'));
  const campaigns = db.getCampaigns().filter((x) => !x.archivedAt);
  const rulesByRow = loadRules(campaigns);
  const unmatched = cfg.campaigns.filter((c) => !findExisting(c, campaigns).row);

  const rows = [];
  const aliases = {};
  for (const c of unmatched) {
    const key = `${c.client}|${c.platform}|${c.campaign}`;
    const links = ruleLinks(c, campaigns, rulesByRow);
    const decision = DECISIONS[key];

    let verdict = 'UNRESOLVED'; let target = null; let basis = 'none'; let why = 'no rule link and no recorded decision';
    if (links.length === 1) { verdict = 'ALIAS'; target = links[0].row; basis = 'rule'; why = `BQ campaign shared via ${links[0].rule}`; }
    else if (links.length > 1) { verdict = 'UNRESOLVED'; basis = 'rule'; why = `${links.length} Central rows claim these BQ campaigns - ambiguous`; }

    if (decision) {
      if (decision.alias) {
        const row = campaigns.find((p) => p.id === decision.alias);
        // A human decision overrides a rule link, but a DISAGREEMENT is loud.
        if (target && row && target.id !== row.id) why = `CONFLICT: rule links to "${target.name}" (${target.id}) but the review says ${row.name}; review wins - ${decision.why}`;
        else why = decision.why;
        verdict = 'ALIAS'; target = row || null; basis = 'human';
        if (!row) { verdict = 'UNRESOLVED'; why = `recorded alias ${decision.alias} is not a live Central row`; }
      } else if (decision.verdict === 'new') {
        if (target) why = `CONFLICT: rule links to "${target.name}" (${target.id}) but the review says NEW; review wins - ${decision.why}`;
        else why = decision.why;
        verdict = 'CREATE'; target = null; basis = 'human';
      } else { verdict = 'UNRESOLVED'; basis = 'human'; why = decision.why; }
    }

    if (verdict === 'ALIAS' && target) aliases[key] = { rowId: target.id, rowName: target.name, basis, why };
    else if (verdict === 'CREATE') aliases[key] = { rowId: null, create: true, basis, why };

    // Closest name-similarity candidate, for context only - never decisive.
    const pool = campaigns.filter((x) => norm(x.client) === norm(c.client) && chan(x.channel) === chan(c.platform));
    const near = pool.map((x) => ({ x, s: similarity(x.name, c.campaign) })).sort((a, b) => b.s - a.s)[0];

    rows.push({
      CONFIRM_OK: '',
      verdict, basis,
      client: c.client, platform: c.platform, intake_campaign: c.campaign,
      central_row: target ? target.name : '', central_row_id: target ? target.id : '',
      central_status: target ? target.status : '', central_budget: target ? (target.totalBudget == null ? '' : target.totalBudget) : '',
      central_spend: target ? (target.mediaSpend == null ? '' : target.mediaSpend) : '',
      intake_budget: c.budget == null ? '' : c.budget,
      intake_flight: `${c.flightStart || '?'} to ${c.flightEnd || '?'}`,
      evidence: why,
      bq_campaigns: (c.matchNames || []).join('\n'),
      closest_by_name: near ? `${near.x.name} (${near.s.toFixed(2)})` : '',
    });
  }

  const tally = rows.reduce((a, r) => { a[r.verdict] = (a[r.verdict] || 0) + 1; return a; }, {});
  console.log(`Intake campaigns Central does not find by name: ${rows.length}\n`);
  ['ALIAS', 'CREATE', 'UNRESOLVED'].forEach((v) => {
    const set = rows.filter((r) => r.verdict === v);
    if (!set.length) return;
    console.log(`=== ${v} (${set.length}) ===`);
    set.forEach((r) => {
      console.log(`  [${r.basis}] ${r.client} | ${r.platform} | ${String(r.intake_campaign).slice(0, 44)}`);
      if (r.central_row) console.log(`      -> "${r.central_row}" (${r.central_row_id})  status=${r.central_status} budget=${r.central_budget} spend=${r.central_spend}`);
      console.log(`      ${r.evidence}`);
    });
    console.log('');
  });
  console.log('verdicts:', JSON.stringify(tally));

  const head = Object.keys(rows[0]);
  const ws = X.utils.aoa_to_sheet([head, ...rows.map((r) => head.map((h) => r[h]))]);
  ws['!cols'] = head.map((h) => ({ wch: /evidence|bq_campaigns|intake_campaign|closest/.test(h) ? 52 : 15 }));
  ws['!autofilter'] = { ref: X.utils.encode_range({ s: { c: 0, r: 0 }, e: { c: head.length - 1, r: rows.length } }) };
  ws['!freeze'] = { xSplit: 0, ySplit: 1 };
  const wb = X.utils.book_new();
  X.utils.book_append_sheet(wb, ws, 'Alias decisions');
  const outX = path.join(__dirname, 'campaign_alias_audit.xlsx');
  X.writeFile(wb, outX);
  fs.writeFileSync(path.join(__dirname, 'campaign_aliases.json'), JSON.stringify({
    generatedAt: new Date().toISOString().slice(0, 19) + 'Z',
    note: 'Reviewed alias/create decisions for intake campaigns Central does not match by name. resolve_central.js reads this BEFORE any name matching. Regenerate with build_alias_audit.js.',
    aliases,
  }, null, 2));
  console.log(`\nwrote ${outX}`);
  console.log(`wrote ${path.join(__dirname, 'campaign_aliases.json')}  (${Object.keys(aliases).length} decided, ${rows.filter((r) => r.verdict === 'UNRESOLVED').length} left undecided)`);
}

main();
