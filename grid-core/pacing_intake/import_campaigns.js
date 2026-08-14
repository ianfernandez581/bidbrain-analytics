// Import the reviewed pacing intake into Central. DRY RUN BY DEFAULT.
//
//   node pacing_intake/import_campaigns.js            # show the plan, write nothing
//   node pacing_intake/import_campaigns.js --apply    # execute it
//
// Reads campaign_match_config.json (the reviewed output of build_match_audit.js)
// and reconciles it against the campaigns already in Central. Central holds 89
// rows today, so this MATCHES first and creates only what is genuinely new -
// importing blind would duplicate most of the book.
//
// What it writes, and what it deliberately does not:
//   - Plan fields (totalBudget, startDate, endDate, currency, spendMult,
//     status, managedBy) come from the intake, which is the agreed source of
//     truth for them. An existing value that DIFFERS is reported and only
//     overwritten with --apply, never silently.
//   - Metric columns (mediaSpend, clientSpend, impressions) are never touched
//     here. Those belong to pacing_sync.js and to db.syncCampaignMetrics, which
//     owns the spendMult rule.
//   - Pacing itself is never written. pctBudgetSpent / pacingStatus and the
//     rest are DERIVED in calc.js and rejected by db.js if written.
'use strict';

const fs = require('fs');
const path = require('path');
const db = require(path.join(__dirname, '..', 'src', 'brain', 'db.js'));

const APPLY = process.argv.includes('--apply');
const OVERWRITE = process.argv.includes('--overwrite');
const CONFIG = path.join(__dirname, 'campaign_match_config.json');

const norm = (s) => String(s == null ? '' : s).trim().toLowerCase();
const tok = (s) => norm(s).replace(/[^a-z0-9]+/g, '');
// "TradeDesk" / "Trade Desk" / "TTD" are the same channel; Central holds all three.
const chan = (s) => tok(s).replace(/^ttd$/, 'tradedesk');

/** Dice coefficient on character bigrams - the same shape the reconcile route
 *  uses, so a name here scores the way a name there does. */
function similarity(a, b) {
  const grams = (s) => { const g = new Set(); const t = tok(s); for (let i = 0; i < t.length - 1; i++) g.add(t.slice(i, i + 2)); return g; };
  const A = grams(a); const B = grams(b);
  if (!A.size || !B.size) return 0;
  let hit = 0;
  A.forEach((g) => { if (B.has(g)) hit++; });
  return (2 * hit) / (A.size + B.size);
}

/** Find the Central row this config campaign already is, if any. Client and
 *  channel must agree - a name is never allowed to pull a match across a
 *  client boundary or onto the wrong platform. */
function findExisting(cfgCamp, campaigns) {
  const pool = campaigns.filter((c) => !c.archivedAt
    && norm(c.client) === norm(cfgCamp.client)
    && chan(c.channel) === chan(cfgCamp.platform));
  if (!pool.length) return { row: null, score: 0, pool: 0 };
  const exact = pool.find((c) => tok(c.name) === tok(cfgCamp.campaign));
  if (exact) return { row: exact, score: 1, pool: pool.length };
  let best = null; let bestScore = 0;
  for (const c of pool) {
    const s = similarity(c.name, cfgCamp.campaign);
    if (s > bestScore) { bestScore = s; best = c; }
  }
  return { row: bestScore >= 0.6 ? best : null, score: bestScore, pool: pool.length, near: best };
}

// Budgets Central owns and the intake must never rewrite. These rows carry a
// WHOLE-PROGRAMME budget while the intake carries a single media-plan line, so
// the intake figure is not smaller, it is a different quantity. Reconciled
// with the trader out of band; remove an entry once its row is split per line.
const PROTECT_BUDGET = [
  { client: 'Schneider', channel: 'Trade Desk', name: 'Water and Environment' },
  { client: 'Schneider', channel: 'LinkedIn', name: 'LiquidAI' },
];
const budgetProtected = (row) => PROTECT_BUDGET.some((p) => norm(p.client) === norm(row.client)
  && chan(p.channel) === chan(row.channel) && tok(p.name) === tok(row.name));

// When several intake lines resolve to ONE Central row they describe one
// campaign between them, so they are merged rather than fought over: budgets
// SUM, the flight is the earliest start to the latest end, and the liveliest
// status wins. Blocking them instead would leave real campaigns unpaced.
const STATUS_RANK = ['ended', 'draft', 'not launched', 'not active', 'paused', 'active'];
function mergeConfigs(group) {
  const live = (s) => STATUS_RANK.indexOf(norm(s));
  const budgets = group.map((c) => Number(c.budget)).filter((n) => Number.isFinite(n) && n > 0);
  const starts = group.map((c) => c.flightStart).filter(Boolean).sort();
  const ends = group.map((c) => c.flightEnd).filter(Boolean).sort();
  return Object.assign({}, group[0], {
    campaign: group[0].campaign,
    budget: budgets.length ? budgets.reduce((a, b) => a + b, 0) : null,
    flightStart: starts[0] || null,
    flightEnd: ends.length ? ends[ends.length - 1] : null,
    status: group.slice().sort((a, b) => live(b.status) - live(a.status))[0].status,
    currency: (group.find((c) => c.currency) || {}).currency || null,
    manager: (group.find((c) => c.manager) || {}).manager || null,
    mergedFrom: group.map((c) => c.campaign),
  });
}

// `channel` is deliberately ABSENT. Central already spells these "TradeDesk"
// and "Linkedin" while the intake writes "Trade Desk" and "LinkedIn"; rewriting
// them would fragment the channel vocabulary that central-clients.json keys its
// campaignMatch rules on, for no gain. Channel is matched case- and
// space-insensitively instead.
// scope: which governance whitelist the field sits on in db.js. 'plan' is
// CENTRAL_PLAN_FIELDS, 'edit' is CENTRAL_EDIT_FIELDS - status and currency are
// only on the latter. Nothing is create-only any more; keep the list so a future
// field that IS create-only reports itself rather than failing silently.
const CREATE_ONLY = [];
const PLAN_FIELDS = [
  ['totalBudget', (c) => (c.budget == null ? null : Number(c.budget)), 'plan'],
  ['currency', (c) => c.currency || null, 'edit'],
  ['startDate', (c) => c.flightStart || null, 'plan'],
  ['endDate', (c) => c.flightEnd || null, 'plan'],
  ['spendMult', (c) => (c.spendMult && c.spendMult !== 1 ? Number(c.spendMult) : null), 'plan'],
  ['status', (c) => c.status || null, 'edit'],
  ['managedBy', (c) => c.manager || null, 'plan'],
];
const scopeOf = (f) => (PLAN_FIELDS.find((x) => x[0] === f) || [])[2] || 'plan';

function main() {
  if (!fs.existsSync(CONFIG)) {
    console.error(`missing ${CONFIG} - run build_match_audit.js first`);
    process.exitCode = 1; return;
  }
  const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'));
  const campaigns = db.getCampaigns();
  console.log(`config: ${cfg.campaigns.length} campaigns (generated ${cfg.generatedAt})`);
  console.log(`central: ${campaigns.length} rows\n`);

  const creates = []; const updates = []; const unchanged = []; const ambiguous = []; const protectedSkips = []; const createOnlySkips = [];

  // Resolve every config campaign first, then MERGE the ones that landed on the
  // same Central row before diffing - diffing per line would produce competing
  // writes to one row.
  const resolved = cfg.campaigns.map((c) => Object.assign({ c }, findExisting(c, campaigns)));

  // Central can hold SEVERAL rows under one name - "Software First EcoStruxure"
  // exists three times on LinkedIn, one per plan line, distinguished only by
  // budget. Name matching alone hands all three intake lines to whichever row
  // came first, and merging them then double-counts budget that already sits on
  // the siblings. So where a name is not unique, assign ONE-TO-ONE: claim the
  // sibling whose budget the intake line agrees with, then fall back to flight
  // dates, and leave anything still ambiguous to the merge path.
  const nameGroups = new Map();
  resolved.filter((r) => r.row).forEach((r) => {
    const k = [norm(r.row.client), chan(r.row.channel), tok(r.row.name)].join('|');
    if (!nameGroups.has(k)) nameGroups.set(k, []);
    nameGroups.get(k).push(r);
  });
  const reassigned = [];
  for (const [k, lines] of nameGroups) {
    if (lines.length < 2) continue;
    const siblings = campaigns.filter((x) => !x.archivedAt
      && [norm(x.client), chan(x.channel), tok(x.name)].join('|') === k);
    if (siblings.length < 2) continue;               // genuinely one row: merge path handles it
    const taken = new Set();
    for (const r of lines) {
      const want = Number(r.c.budget);
      let pick = siblings.find((s) => !taken.has(s.id) && Number.isFinite(want) && Number(s.totalBudget) === want);
      if (!pick) pick = siblings.find((s) => !taken.has(s.id) && r.c.flightEnd && s.endDate === r.c.flightEnd);
      if (!pick) pick = siblings.find((s) => !taken.has(s.id));
      if (!pick) continue;
      taken.add(pick.id);
      if (pick.id !== r.row.id) reassigned.push({ line: r.c.campaign, from: r.row.id, to: pick.id, budget: want });
      r.row = pick;
    }
  }
  if (reassigned.length) {
    console.log(`=== ONE-TO-ONE REASSIGNMENT (${reassigned.length}) - duplicate Central names split by budget ===`);
    reassigned.forEach((x) => console.log(`  "${x.line}" (budget ${x.budget}) -> ${x.to}  (was heading for ${x.from})`));
    console.log('');
  }

  const groups = new Map();
  resolved.filter((r) => r.row).forEach((r) => {
    if (!groups.has(r.row.id)) groups.set(r.row.id, []);
    groups.get(r.row.id).push(r);
  });
  const merges = [];
  const targets = [];
  for (const [, g] of groups) {
    if (g.length === 1) { targets.push({ c: g[0].c, row: g[0].row, score: g[0].score }); continue; }
    const merged = mergeConfigs(g.map((x) => x.c));
    merges.push({ row: g[0].row, merged });
    targets.push({ c: merged, row: g[0].row, score: Math.min(...g.map((x) => x.score)) });
  }

  resolved.filter((r) => !r.row).forEach(({ c, score, pool, near }) => {
    creates.push({ c, note: pool ? `no name match among ${pool} ${c.client}/${c.platform} row(s)` + (near ? `; closest "${near.name}" at ${score.toFixed(2)}` : '') : `no existing ${c.client}/${c.platform} row` });
  });

  for (const { c, row, score } of targets) {
    const diffs = []; const conflicts = [];
    for (const [field, get] of PLAN_FIELDS) {
      const want = get(c);
      if (want == null || want === '') continue;
      const have = row[field];
      const same = String(have == null ? '' : have).trim() === String(want).trim()
        || (typeof want === 'number' && Number(have) === want);
      if (same) continue;
      const empty = have == null || have === '';
      if (CREATE_ONLY.includes(field)) { if (!empty) continue; createOnlySkips.push({ row, field, to: want }); continue; }
      // Filling a blank is safe. CHANGING a value a trader already typed is
      // not, so it needs --overwrite: Central carries whole-programme budgets
      // (Water and Environment 106,800) where the intake carries one plan line
      // (12,192), and clobbering that silently would rewrite the book.
      if (field === 'totalBudget' && !empty && budgetProtected(row)) {
        protectedSkips.push({ row, field, from: have, to: want });
        continue;
      }
      if (empty) diffs.push({ field, from: have, to: want });
      else conflicts.push({ field, from: have, to: want });
    }
    if (score < 1) ambiguous.push({ c, row, score });
    if (diffs.length || conflicts.length) updates.push({ c, row, diffs, conflicts, score });
    else unchanged.push({ c, row });
  }

  // Several intake rows can land on ONE Central row - the media-plan-line grain
  // again. Where they disagree on a value there is no safe answer, so those
  // rows are blocked rather than resolved by whichever happened to be last.
  const byTarget = new Map();
  updates.forEach((u) => {
    if (!byTarget.has(u.row.id)) byTarget.set(u.row.id, []);
    byTarget.get(u.row.id).push(u);
  });
  // Nothing is blocked any more: colliding lines are merged above, so each
  // Central row is written from exactly one merged intake record.
  const collisions = [...byTarget.entries()].filter(([, v]) => v.length > 1);
  const blocked = new Set();

  const money = (v) => (v == null || v === '' ? '(empty)' : v);
  if (merges.length) {
    console.log(`=== MERGED INTAKE LINES (${merges.length}) - several plan lines describe one campaign ===`);
    merges.forEach(({ row, merged }) => {
      console.log(`  ${row.client} | ${row.name}  (${row.id})  <- ${merged.mergedFrom.length} lines`);
      merged.mergedFrom.forEach((n) => console.log(`      ${n}`));
      console.log(`      budget summed to ${merged.budget}, flight ${merged.flightStart || '?'} to ${merged.flightEnd || '?'}, status ${merged.status || '?'}`);
    });
    console.log('');
  }
  if (createOnlySkips.length) {
    console.log(`=== NOT WRITABLE AFTER CREATE (${createOnlySkips.length}) - '${CREATE_ONLY.join("', '")}' is on no governance whitelist ===`);
    createOnlySkips.forEach((p) => console.log(`  ${p.row.client} | ${p.row.name}: ${p.field} would be ${p.to}; set it in the Grid UI if it matters`));
    console.log('');
  }
  if (protectedSkips.length) {
    console.log(`=== BUDGET PROTECTED (${protectedSkips.length}) - whole-programme figures, left as-is ===`);
    protectedSkips.forEach((p) => console.log(`  ${p.row.client} | ${p.row.name}: keeping ${p.from}, NOT writing ${p.to}`));
    console.log('');
  }
  if (creates.length) {
    console.log(`=== CREATE (${creates.length}) - not in Central today ===`);
    creates.forEach(({ c, note }) => console.log(`  ${c.client} | ${c.platform} | ${c.campaign}\n      budget ${money(c.budget)} ${c.currency || ''}  flight ${c.flightStart || '?'} to ${c.flightEnd || '?'}\n      ${note}`));
    console.log('');
  }
  if (ambiguous.length) {
    console.log(`=== FUZZY NAME MATCHES (${ambiguous.length}) - check these before --apply ===`);
    ambiguous.forEach(({ c, row, score }) => console.log(`  ${score.toFixed(2)}  intake "${c.campaign}"  ->  central "${row.name}"  (${c.client} / ${c.platform}, ${row.id})`));
    console.log('');
  }
  const fillable = updates.filter((u) => u.diffs.length && !blocked.has(u.row.id));
  if (fillable.length) {
    console.log(`=== FILL EMPTY FIELDS (${fillable.length}) - safe, applied by default ===`);
    fillable.forEach(({ c, row, diffs }) => {
      console.log(`  ${c.client} | ${c.platform} | ${row.name}  (${row.id})`);
      diffs.forEach((d) => console.log(`      ${d.field}: (empty)  ->  ${d.to}`));
    });
    console.log('');
  }
  const conflicted = updates.filter((u) => u.conflicts.length && !blocked.has(u.row.id));
  if (conflicted.length) {
    console.log(`=== VALUE CONFLICTS (${conflicted.length}) - Central already holds a different value, needs --overwrite ===`);
    conflicted.forEach(({ c, row, conflicts }) => {
      console.log(`  ${c.client} | ${c.platform} | ${row.name}  (${row.id})`);
      conflicts.forEach((d) => console.log(`      ${d.field}: ${money(d.from)}  ->  ${d.to}`));
    });
    console.log('');
  }
  if (blocked.size) {
    console.log(`=== BLOCKED (${blocked.size}) - several intake rows target one Central row with DIFFERENT values ===`);
    collisions.filter(([id]) => blocked.has(id)).forEach(([id, group]) => {
      console.log(`  ${group[0].row.client} | ${group[0].row.name}  (${id})  <- ${group.length} intake rows`);
      group.forEach((u) => {
        const all = u.diffs.concat(u.conflicts).map((d) => `${d.field}=${d.to}`).join(', ');
        console.log(`      "${u.c.campaign}" wants ${all}`);
      });
      console.log('      Nothing written. Split the Central row, or merge these intake lines into one.');
    });
    console.log('');
  }
  console.log('=== SUMMARY ===');
  console.log(`  create ${creates.length}   fill-empty ${fillable.length}   conflicts ${conflicted.length}   blocked ${blocked.size}   already correct ${unchanged.length}   fuzzy ${ambiguous.length}`);

  if (!APPLY) {
    console.log('\nDRY RUN - nothing was written. Re-run with --apply to create rows and fill empty fields.');
    console.log('Add --overwrite as well to also change values Central already holds.');
    return;
  }

  let made = 0; let changed = 0; const errors = [];
  for (const { c } of creates) {
    const input = { section: 'TRANSMISSION', client: c.client, name: c.campaign, channel: c.platform };
    PLAN_FIELDS.forEach(([field, get]) => { const v = get(c); if (v != null && v !== '') input[field] = v; });
    const r = db.createCampaign(input, 'pacing-intake');
    if (r.ok) made++; else errors.push(`create ${c.client}/${c.campaign}: ${r.error}`);
  }
  for (const u of updates) {
    if (blocked.has(u.row.id)) continue;
    const todo = u.diffs.concat(OVERWRITE ? u.conflicts : []);
    for (const d of todo) {
      const r = db.updateCampaignField(u.row.id, d.field, d.to, scopeOf(d.field), { source: 'pacing-intake' });
      if (r.ok) changed++; else errors.push(`${u.row.id}.${d.field}: ${r.error}`);
    }
  }
  console.log(`\nAPPLIED: ${made} campaigns created, ${changed} fields written${OVERWRITE ? ' (including overwrites)' : ''}.`);
  if (blocked.size) console.log(`${blocked.size} row(s) left untouched - see BLOCKED above.`);
  if (errors.length) { console.log('errors:'); errors.forEach((e) => console.log('  ' + e)); process.exitCode = 1; }
}

main();
