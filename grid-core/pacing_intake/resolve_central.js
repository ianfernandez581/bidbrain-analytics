// Resolve reviewed intake campaigns to Central rows. Shared by
// import_campaigns.js (writes plan fields) and pacing_sync.js (writes metrics)
// so the two can never disagree about which row a campaign is - two copies of
// this rule would drift, and the failure mode is silent: spend landing on the
// wrong row still looks like a number.
//
// Rules, in order:
//   0. campaign_aliases.json wins outright. Central names campaigns short
//      ("Airset", "EBA", "46113") where the intake names them by media-plan line
//      ("2223_SE_Airset SM_ANZ_display_AWR"), which scores far below any safe
//      similarity threshold. Without this file the importer calls those NEW and
//      creates duplicate rows beside live campaigns already carrying the spend.
//      An entry marked `create: true` means genuinely new; an entry with no
//      decision blocks the row entirely rather than letting it fall through to
//      guessing.
//   1. client and channel must agree. A name never pulls a match across a
//      client boundary or onto another platform.
//   2. exact name (separator-insensitive), else bigram similarity >= 0.6.
//   3. Where Central holds SEVERAL rows under one name - "Software First
//      EcoStruxure" exists three times on LinkedIn, one per media-plan line,
//      distinguished only by budget - assign ONE-TO-ONE by matching budget,
//      then flight end date. Without this, every line claims the first row and
//      their budgets get summed onto it, double-counting what already sits on
//      the siblings.
'use strict';

const norm = (s) => String(s == null ? '' : s).trim().toLowerCase();
const tok = (s) => norm(s).replace(/[^a-z0-9]+/g, '');
const chan = (s) => tok(s).replace(/^ttd$/, 'tradedesk');

function similarity(a, b) {
  const grams = (s) => { const g = new Set(); const t = tok(s); for (let i = 0; i < t.length - 1; i++) g.add(t.slice(i, i + 2)); return g; };
  const A = grams(a); const B = grams(b);
  if (!A.size || !B.size) return 0;
  let hit = 0; A.forEach((g) => { if (B.has(g)) hit++; });
  return (2 * hit) / (A.size + B.size);
}

function findExisting(c, campaigns) {
  const pool = campaigns.filter((x) => !x.archivedAt
    && norm(x.client) === norm(c.client) && chan(x.channel) === chan(c.platform));
  if (!pool.length) return { row: null, score: 0, pool: 0 };
  const exact = pool.find((x) => tok(x.name) === tok(c.campaign));
  if (exact) return { row: exact, score: 1, pool: pool.length };
  let best = null; let bestScore = 0;
  pool.forEach((x) => { const s = similarity(x.name, c.campaign); if (s > bestScore) { bestScore = s; best = x; } });
  return { row: bestScore >= 0.6 ? best : null, score: bestScore, pool: pool.length, near: best };
}

/** Returns [{ c, row, score, pool, near }] plus the reassignments made, so a
 *  caller can print what rule 3 moved. */
function loadAliases() {
  try {
    const p = require('path').join(__dirname, 'campaign_aliases.json');
    return (JSON.parse(require('fs').readFileSync(p, 'utf8')).aliases) || {};
  } catch (e) { return {}; }   // absent file = name matching only, as before
}

function resolveAll(configCampaigns, campaigns) {
  const aliases = loadAliases();
  const resolved = configCampaigns.map((c) => {
    const a = aliases[`${c.client}|${c.platform}|${c.campaign}`];
    if (a && a.rowId) {
      const row = campaigns.find((x) => x.id === a.rowId && !x.archivedAt);
      if (row) return { c, row, score: 1, pool: 1, alias: a };
      // A recorded alias pointing at a row that no longer exists must NOT fall
      // back to name matching - that is how a duplicate gets created quietly.
      return { c, row: null, score: 0, pool: 0, blocked: `alias ${a.rowId} is not a live Central row` };
    }
    if (a && a.create) {
      // "Approved as new" is only true until the import actually creates it.
      // After that the row exists and must be found, or the sync writes metrics
      // to nothing and the campaign sits at zero spend forever.
      const made = findExisting(c, campaigns);
      if (made.row) return Object.assign({ c }, made, { approvedCreate: false });
      return { c, row: null, score: 0, pool: 0, approvedCreate: true };
    }
    const hit = findExisting(c, campaigns);
    // Unmatched AND undecided: block it. Everything Central cannot find by name
    // has to be ruled on in campaign_aliases.json first.
    if (!hit.row) return Object.assign({ c, blocked: 'no name match and no recorded alias/create decision' }, hit);
    return Object.assign({ c }, hit);
  });
  const keyOf = (r) => [norm(r.client), chan(r.channel), tok(r.name)].join('|');

  const groups = new Map();
  resolved.filter((r) => r.row).forEach((r) => {
    const k = keyOf(r.row);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  });

  const reassigned = [];
  for (const [k, lines] of groups) {
    if (lines.length < 2) continue;
    const siblings = campaigns.filter((x) => !x.archivedAt && keyOf(x) === k);
    if (siblings.length < 2) continue;   // one row genuinely serving many lines
    const taken = new Set();
    for (const r of lines) {
      const want = Number(r.c.budget);
      let pick = siblings.find((s) => !taken.has(s.id) && Number.isFinite(want) && Number(s.totalBudget) === want)
        || siblings.find((s) => !taken.has(s.id) && r.c.flightEnd && s.endDate === r.c.flightEnd)
        || siblings.find((s) => !taken.has(s.id));
      if (!pick) continue;
      taken.add(pick.id);
      if (pick.id !== r.row.id) reassigned.push({ line: r.c.campaign, from: r.row.id, to: pick.id, budget: want });
      r.row = pick;
    }
  }
  return { resolved, reassigned };
}

module.exports = { resolveAll, findExisting, similarity, norm, tok, chan };
