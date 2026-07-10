/*
 * src/central/readiness.js — the live-coverage READINESS table builder (Section 9 item 6).
 * ----------------------------------------------------------------------------------------
 * Pure + dependency-free (Node + browser; reuses src/central/match.js). Produces ONE
 * readiness row per live campaign-channel across the LIVE set, each with its BQ source, a
 * PRE-SEEDED match rule (mode + value + advertiserName) and a read-only BQ preview count
 * (campaigns matched · impressions · mediaSpend). This is the pre-validation view Zhen uses
 * to confirm each client's mapping.
 *
 * Inputs (all read-only):
 *   campaigns : db.getCampaigns() — Central's source of truth (status/archived live here).
 *   config    : parsed config/central-clients.json ({clients:[...]}).
 *   fetched   : central_sync.py --readiness output .clients — { <client>: { rows:[...],
 *               source, validated, errors } }. raw rows are tagged {bqName, advertiserName,
 *               channel, dataset, table, impressions, mediaSpend}; view rows {bqName,
 *               impressions, mediaSpend}.
 *
 * LIVE SET (auto-derived — NO hardcoded dead-list): a client is live iff config source is
 * not 'none' AND it has >=1 non-archived Active|Paused campaign in the DB. That naturally
 * drops dead clients (City Perfume / QTopia — Ended only) and no-BQ clients (Gateway et al.
 * — source 'none'), exactly as the task requires, without naming them.
 *
 * RULE SEEDING (Design A, one shape — see match.js):
 *   - Mapped Mode A (Schneider, pm_delivery view): one row per map entry; preview = that
 *     program's row. Marked validated/done (the view already rolls up the currency triplets).
 *   - Mapped Mode B (HireRight): one row per map entry; preview via match.matchCampaign.
 *   - Unmapped raw: one row per channel. Seed the rule over the advertiser spelling(s) that
 *     actually carry data (impressions|spend > 0 = "active"): >1 active spelling OR a known
 *     multi-spelling client (STT / ResetData / Schneider) => rollup (sum across spellings,
 *     dedupe by campaign name); else contains. This is what makes MongoDB pick ADVERTISER_ID
 *     '9c1w83i' (3.48M imps) over the 0-impression 'MongoDB' NAME row — no special-casing.
 *
 * needsManualRule (red) iff the preview matched 0 BQ campaigns — a rollup-to-build for Zhen,
 * surfaced, never silently dropped.
 */
(function (root, factory) {
  var api = factory(typeof require === 'function' ? require('./match') : (root.CentralMatch));
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.CentralReadiness = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (match) {
  'use strict';

  var LIVE_STATUSES = ['Active', 'Paused'];
  // Clients whose advertiser identity is spread across spellings / currency triplets: their
  // pre-seed uses rollup even where a single channel currently shows one spelling (task rule).
  var KNOWN_ROLLUP = ['STT', 'ResetData', 'Schneider'];

  function sourceOf(spec) { return spec.source || (spec.bq ? 'view' : 'none'); }
  function num(v) { return Number(v) || 0; }

  // representative live status of a client's DB campaigns (Active wins over Paused)
  function clientLiveStatus(campaigns, client) {
    var live = campaigns.filter(function (c) { return c.client === client && !c.archivedAt && LIVE_STATUSES.indexOf(c.status) >= 0; });
    if (live.some(function (c) { return c.status === 'Active'; })) return 'Active';
    return live.length ? 'Paused' : null;
  }
  function statusForCampaignName(campaigns, client, name) {
    var hit = campaigns.find(function (c) { return c.client === client && c.name === name && !c.archivedAt; });
    return hit ? hit.status : null;
  }

  // distinct "dataset.table" sources for a channel, restricted to the chosen advertisers
  function bqSourceFor(rows, channel, advSet) {
    var seen = {}, out = [];
    rows.forEach(function (r) {
      if (r.channel !== channel) return;
      if (advSet && advSet.indexOf(r.advertiserName) < 0) return;
      if (r.dataset && r.table) { var k = r.dataset + '.' + r.table; if (!seen[k]) { seen[k] = 1; out.push(k); } }
    });
    return out.join(', ');
  }

  function mkRow(o) {
    return {
      client: o.client, campaign: o.campaign, channel: o.channel, status: o.status || null,
      bqSource: o.bqSource || '', validated: !!o.validated, seededFrom: o.seededFrom,
      rule: { mode: o.mode, value: o.value == null ? '' : o.value, advertiserName: o.advertiserName == null ? '' : o.advertiserName },
      preview: { campaigns: o.campaigns || 0, impressions: o.impressions || 0, mediaSpend: o.mediaSpend || 0 },
      needsManualRule: (o.campaigns || 0) === 0
    };
  }

  // ---- per-client builders ----------------------------------------------------------------
  function buildViewClient(spec, fetched, campaigns) {
    // Mode A: map entries are program bqNames (no campaignMatch). Preview = the pm_delivery row.
    var rows = (fetched.rows) || [];
    var byBq = {}; rows.forEach(function (r) { byBq[r.bqName] = r; });
    var ds = (spec.bq && spec.bq.dataset) || '', tbl = (spec.bq && spec.bq.table) || '';
    return (spec.map || []).map(function (e) {
      var hit = byBq[e.bqName];
      return mkRow({
        client: spec.client, campaign: e.campaignName || e.bqName, channel: 'All (view)',
        status: statusForCampaignName(campaigns, spec.client, e.campaignName) || clientLiveStatus(campaigns, spec.client),
        bqSource: ds && tbl ? ds + '.' + tbl : '', validated: spec.validated, seededFrom: 'view',
        mode: 'view', value: e.bqName, advertiserName: '',
        campaigns: hit ? 1 : 0, impressions: hit ? num(hit.impressions) : 0, mediaSpend: hit ? num(hit.mediaSpend) : 0
      });
    });
  }

  function buildMappedRawClient(spec, fetched, campaigns) {
    var rows = (fetched.rows) || [];
    return (spec.map || []).filter(function (e) { return e.campaignMatch; }).map(function (e) {
      var met = match.matchCampaign(rows, e);
      return mkRow({
        client: spec.client, campaign: e.campaignName || ('(all ' + (e.channel || '') + ')'), channel: e.channel || '',
        status: statusForCampaignName(campaigns, spec.client, e.campaignName) || clientLiveStatus(campaigns, spec.client),
        bqSource: bqSourceFor(rows, e.channel, [e.advertiserName]), validated: spec.validated, seededFrom: 'map',
        mode: e.campaignMatch.mode, value: e.campaignMatch.value, advertiserName: e.advertiserName,
        campaigns: met.matched, impressions: met.impressions, mediaSpend: met.mediaSpend
      });
    });
  }

  function buildUnmappedRawClient(spec, fetched, campaigns) {
    var rows = (fetched.rows) || [];
    var status = clientLiveStatus(campaigns, spec.client);
    var channels = [];
    rows.forEach(function (r) { if (r.channel && channels.indexOf(r.channel) < 0) channels.push(r.channel); });
    channels.sort();
    return channels.map(function (channel) {
      var chanRows = rows.filter(function (r) { return r.channel === channel; });
      var totals = {}, order = [];
      chanRows.forEach(function (r) {
        var a = r.advertiserName;
        if (!totals[a]) { totals[a] = { imp: 0, spend: 0 }; order.push(a); }
        totals[a].imp += num(r.impressions); totals[a].spend += num(r.mediaSpend);
      });
      // IMPRESSIONS are the delivery signal: prefer spellings that actually served
      // (imp > 0); else fall back to spend > 0; else all. This is what makes MongoDB pick
      // ADVERTISER_ID '9c1w83i' (3.48M imps) ALONE and drop the legacy 'MongoDB' NAME row
      // (0 imps, spend only) instead of rolling them together.
      var withImp = order.filter(function (a) { return totals[a].imp > 0; });
      var withSpend = order.filter(function (a) { return totals[a].spend > 0; });
      var use = withImp.length ? withImp : (withSpend.length ? withSpend : order);
      var rollup = use.length > 1 || KNOWN_ROLLUP.indexOf(spec.client) >= 0;
      var mode = rollup ? 'rollup' : 'contains';
      // preview over ONLY the chosen spellings (so a rollup never re-includes a 0-data spelling)
      var previewRows = chanRows.filter(function (r) { return use.indexOf(r.advertiserName) >= 0; });
      var mapRow = { channel: channel, advertiserName: rollup ? null : use[0], campaignMatch: { mode: mode, value: '' } };
      var met = match.matchCampaign(previewRows, mapRow);
      return mkRow({
        client: spec.client, campaign: '(all ' + channel + ' campaigns)', channel: channel,
        status: status, bqSource: bqSourceFor(rows, channel, use), validated: spec.validated, seededFrom: 'preseed',
        mode: mode, value: '', advertiserName: use.join(' | '),
        campaigns: met.matched, impressions: met.impressions, mediaSpend: met.mediaSpend
      });
    });
  }

  // ---- top-level -------------------------------------------------------------------------
  function buildReadiness(input) {
    input = input || {};
    var campaigns = input.campaigns || [];
    var config = input.config || { clients: [] };
    var fetched = input.fetched || {};
    var out = [];
    (config.clients || []).forEach(function (spec) {
      var src = sourceOf(spec);
      if (src === 'none') return;                                            // no BQ presence
      if (clientLiveStatus(campaigns, spec.client) == null) return;          // not in the live set
      var fc = fetched[spec.client] || { rows: [], errors: [] };
      var mapped = (spec.map || []).length > 0;
      if (src === 'view') out = out.concat(buildViewClient(spec, fc, campaigns));
      else if (mapped) out = out.concat(buildMappedRawClient(spec, fc, campaigns));
      else out = out.concat(buildUnmappedRawClient(spec, fc, campaigns));
    });
    // Order: validated (done) clients first, then by client, then channel.
    out.sort(function (a, b) {
      if (a.validated !== b.validated) return a.validated ? -1 : 1;
      if (a.client !== b.client) return a.client < b.client ? -1 : 1;
      return (a.channel || '') < (b.channel || '') ? -1 : (a.channel || '') > (b.channel || '') ? 1 : 0;
    });
    return out;
  }

  return { buildReadiness: buildReadiness, LIVE_STATUSES: LIVE_STATUSES, KNOWN_ROLLUP: KNOWN_ROLLUP };
});
