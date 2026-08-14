// Resolve reviewed intake campaigns to Central rows. Shared by
// import_campaigns.js (writes plan fields) and pacing_sync.js (writes metrics)
// so the two can never disagree about which row a campaign is - two copies of
// this rule would drift, and the failure mode is silent: spend landing on the
// wrong row still looks like a number.
//
// Rules, in order:
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
function resolveAll(configCampaigns, campaigns) {
  const resolved = configCampaigns.map((c) => Object.assign({ c }, findExisting(c, campaigns)));
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
