/*
 * src/central/match.js — the ONE per-row BQ→Central match rule (Design A: one row per
 * campaign-per-channel). Used by the sync path for exact | contains | rollup — a single
 * shape, no separate rollup code path.
 *
 * Given the BQ campaign rows fetched for a client (each tagged {bqName, advertiserName,
 * channel, impressions, mediaSpend}) and one Central map row
 * {channel, advertiserName, campaignMatch:{mode,value}}, return the summed metrics:
 *   - filter to the row's channel;
 *   - advertiser scope: exact/contains stay on the row's advertiserName; ROLLUP spans all
 *     advertiser-name spellings for that channel (that is the "Always On" case);
 *   - name predicate: exact → name === value; contains/rollup → name contains value;
 *   - dedupe then sum: rollup dedupes by campaign name (so the same campaign under two
 *     advertiser spellings counts once); exact/contains dedupe by advertiserName+campaign.
 *
 * Pure + dependency-free (Node + browser). NEVER decides clientSpend — that stays the
 * spendMult rule in db.syncCampaignMetrics.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.CentralMatch = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function nameMatch(cm, name) {
    if (!cm || cm.value == null) return false;
    name = String(name == null ? '' : name);
    if (cm.mode === 'exact') return name === cm.value;
    return name.indexOf(cm.value) >= 0;   // contains + rollup
  }

  function matchCampaign(fetched, mapRow) {
    var cm = (mapRow && mapRow.campaignMatch) || {};
    var rollup = cm.mode === 'rollup';
    var seen = {}, impressions = 0, mediaSpend = 0, matched = 0;
    var rows = fetched || [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r.channel !== mapRow.channel) continue;
      if (!rollup && r.advertiserName !== mapRow.advertiserName) continue;  // rollup spans spellings
      if (!nameMatch(cm, r.bqName)) continue;
      var key = rollup ? String(r.bqName || '') : ((r.advertiserName || '') + '|' + (r.bqName || ''));
      if (seen[key]) continue;
      seen[key] = 1; matched++;
      impressions += Number(r.impressions) || 0;
      mediaSpend += Number(r.mediaSpend) || 0;
    }
    return { impressions: impressions, mediaSpend: Math.round(mediaSpend * 100) / 100, matched: matched };
  }

  return { matchCampaign: matchCampaign, nameMatch: nameMatch };
});
