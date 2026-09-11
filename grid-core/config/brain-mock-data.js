/*
 * config/brain-mock-data.js  —  Brain V1 mock recommendations
 * ----------------------------------------------------------------------------
 * V1 is UI + mock data only. This file is the single in-memory store the Brain
 * tab reads from. V2 replaces it with a real recommendations engine querying
 * BigQuery; the exported shape (RECOMMENDATIONS + the three helpers) is the
 * contract the front-end depends on, so keep it stable.
 *
 * Loads in two worlds:
 *   - Node (tests / future server)  -> module.exports
 *   - Browser (<script src>)        -> window.BrainData
 * ...via the UMD guard at the bottom. No build step, no ES modules (The Grid is
 * a classic-script static app, so this must work over file:// too).
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.BrainData = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ---- deterministic PRNG so mock series are stable across reloads ----------
  function hashStr(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function mulberry32(a) { return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; var t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function round(n, d) { var p = Math.pow(10, d || 0); return Math.round(n * p) / p; }

  // Per-client facts VERIFIED against clients/client_<c>/ + ingest/ (2026-07-06).
  // `platforms` = the ad platforms the client ACTUALLY buys media on — a rec may only
  // use one of these (or 'Multi'); enforced by an assertion in rec(). `cur`/`fx` match
  // how each dashboard actually displays money.
  var CLIENT_META = {
    resetdata:  { name: 'ResetData',              cur: 'AUD', platforms: ['Google Ads', 'Meta', 'Trade Desk', 'Reddit'], fx: 'Google/Meta/Reddit AUD native; Trade Desk USD→AUD @1.50' },
    mongodb:    { name: 'MongoDB',                cur: 'USD', platforms: ['Trade Desk'], fx: 'USD throughout' },
    cloudflare: { name: 'Cloudflare',             cur: 'USD', platforms: ['LinkedIn', 'Trade Desk', 'Reddit', 'LINE'], fx: 'USD; LINE JPY→USD @155' },
    schneider:  { name: 'Schneider',              cur: 'AUD', platforms: ['DV360', 'Trade Desk', 'LinkedIn'], fx: 'AUD; USD→AUD @1.50, SGD→AUD @1.15' },
    vmch:       { name: 'VMCH',                   cur: 'AUD', platforms: ['Trade Desk'], fx: 'AUD native' },
    tlm:        { name: 'The Little Marionette',  cur: 'AUD', platforms: ['Google Ads', 'Trade Desk'], fx: 'AUD native' },
    proptrack:  { name: 'PropTrack',              cur: 'AUD', platforms: ['LinkedIn', 'Trade Desk'], fx: 'AUD native' },
    hireright:  { name: 'HireRight',              cur: 'USD', platforms: ['DV360', 'Trade Desk', 'LinkedIn'], fx: 'USD; Trade Desk AUD→USD @0.65' }
  };

  // Real BigQuery raw tables each platform's delivery lands in (from ingest/). Used as the
  // `data_source` a V2 engine would query. See ingest/ + CLAUDE.md ingest section.
  var PLATFORM_SOURCE = {
    'Trade Desk': ['raw_snowflake.tradedesk_apac_all'],
    'Meta':       ['raw_windsor.perf_meta'],
    'LinkedIn':   ['raw_snowflake.linkedin_ads_apac'],
    'Google Ads': ['raw_google_ads.perf_google_ads'],
    'DV360':      ['raw_snowflake.dv360_apac'],
    'Reddit':     ['raw_windsor.perf_reddit'],
    'LINE':       ['manual LINE Ad Manager export (no raw table yet)'],
    'Multi':      ['raw_snowflake.tradedesk_apac_all', 'raw_snowflake.dv360_apac']
  };
  var ASSIGNEES = ['Zen', 'Priya', 'Marcus', 'Aisha'];
  var BASE_DATE = new Date('2026-07-05T14:00:00+10:00'); // "now" for created_at spread

  // ---- 21-day time series generated from the headline metrics ---------------
  // Keeps evidence.metrics_21d and the chart internally consistent: the isolated
  // series hovers around cvr_pct, the channel average around cvr_pct / multiple,
  // with one clear peak day.
  function makeSeries(seed, cvrPct, mult, peakDay) {
    var rnd = mulberry32(hashStr(seed + ':series'));
    var avg = mult > 0 ? cvrPct / mult : cvrPct;
    var out = [];
    for (var d = 1; d <= 21; d++) {
      var a = avg * (0.82 + rnd() * 0.36);
      var p = cvrPct * (0.7 + rnd() * 0.5);
      if (d === peakDay) p = cvrPct * (1.18 + rnd() * 0.12); // guaranteed visible peak
      out.push({ day: d, placement_cvr_pct: round(p, 4), avg_cvr_pct: round(a, 4) });
    }
    return out;
  }

  // ---- type-aware defaults for the rich nested fields -----------------------
  function typeVerb(type) {
    return ({
      placement: 'Isolate placement', audience: 'Shift audience', budget_shift: 'Reallocate budget',
      bid_strategy: 'Swap bid strategy', creative: 'Refresh creative', site_quality: 'Blacklist low-quality inventory',
      negative_keywords: 'Add negative keywords', frequency_cap: 'Adjust frequency cap'
    })[type] || 'Optimize';
  }

  function defaultConfig(r, rnd) {
    var abbr = { 'Trade Desk': 'TDD', 'Meta': 'MET', 'LinkedIn': 'LNK', 'Google Ads': 'GAD', 'DV360': 'DV3', 'Reddit': 'RDT', 'Multi': 'MUL' }[r.platform] || 'XXX';
    var cid = r.client_id.slice(0, 2).toUpperCase();
    var start = '2026-07-' + String(10 + Math.floor(rnd() * 8)).padStart(2, '0');
    var end = '2026-08-' + String(8 + Math.floor(rnd() * 12)).padStart(2, '0');
    var common = { flight_start: start, flight_end: end };
    switch (r.type) {
      case 'placement': return Object.assign({ line_item_name: cid + '_' + abbr + '_Iso_Jul26', placement_targeting: 'allowlist · isolated domain', daily_budget_aud: 120 + Math.floor(rnd() * 120), max_cpm_aud: round(9 + rnd() * 7, 2), audience: 'Same as parent line · retargeting excluded', frequency_cap: '3 / user / 7 days', parent_adjustment: 'Reduce parent daily budget by the isolated spend' }, common);
      case 'audience': return Object.assign({ audience_name: cid + '_' + abbr + '_ICP_Interest', from_targeting: 'Broad lookalike 3%', to_targeting: 'Interest + job-title stack (ICP)', daily_budget_aud: 90 + Math.floor(rnd() * 90), bid: 'Keep current', exclusions: 'Existing customers · converters 90d' }, common);
      case 'budget_shift': return Object.assign({ move_from: 'Underpacing channel', move_to: r.platform + ' top line item', shift_amount_aud_per_day: 80 + Math.floor(rnd() * 140), guardrail: 'Cap shift at 20% of daily budget', review_after: '14 days' }, common);
      case 'bid_strategy': return Object.assign({ line_item: cid + '_' + abbr + '_Core', from_strategy: 'Maximise clicks', to_strategy: 'Target CPA', target_cpa_aud: 40 + Math.floor(rnd() * 120), ramp: 'Hold budget flat for first 7 days' }, common);
      case 'creative': return Object.assign({ action: 'Rotate in fresh creative · pause fatigued set', fatigued_set: cid + '_' + abbr + '_Set_A', frequency_at_fatigue: round(6 + rnd() * 4, 1), new_variants: 3, keep_running: 'Top variant by CVR' }, common);
      case 'site_quality': return Object.assign({ action: 'Add to shared blacklist (all platforms)', domains: 'MFA / made-for-advertising cluster', domains_count: 8 + Math.floor(rnd() * 20), applies_to: 'Trade Desk · DV360 · Google Ads (GDN)', expected_waste_removed: 'per impact estimate' }, common);
      case 'negative_keywords': return Object.assign({ campaign: cid + '_Search_Core', add_negatives: 'Irrelevant / job-seeker / free-tier terms', negatives_count: 12 + Math.floor(rnd() * 30), match_type: 'Phrase + exact', review_after: '14 days' }, common);
      case 'frequency_cap': return Object.assign({ line_item: cid + '_' + abbr + '_Prospecting', from_cap: 'Uncapped', to_cap: (2 + Math.floor(rnd() * 3)) + ' / user / 7 days', expected_reach_change: 'Flat reach, lower waste', review_after: '10 days' }, common);
      default: return common;
    }
  }

  function defaultRisks(r) {
    var g = [
      { title: 'Cannibalization', body: 'Some of the lift may have happened anyway through the parent setup. The impact estimate discounts by ~30% for cannibalization based on prior precedents.' },
      { title: 'Inventory / reach ceiling', body: 'Available volume was checked against the last quarter — the projected spend sits comfortably under the ceiling, so the uplift comes from efficiency, not just more volume.' },
      { title: 'Measurement window', body: 'Give it a full flight before judging. Early days can look noisy; the baseline comparison needs ~14 days to stabilise.' }
    ];
    if (r.type === 'site_quality') g.unshift({ title: 'Over-blocking', body: 'Blacklist is scoped to the MFA cluster only. Legitimate long-tail domains are unaffected; the list is reversible per domain.' });
    if (r.type === 'audience') g.unshift({ title: 'Audience mismatch', body: 'Target stack was cross-checked against the client ICP filter and GA4 landing-page behaviour. Low mismatch risk, but worth a spot-check after week one.' });
    return g.slice(0, 3);
  }

  function defaultHistory(r) {
    return [
      { name: typeVerb(r.type) + ' · ' + r.client_name, date: 'Mar 2025', outcome_aud: 6000 + (hashStr(r.id) % 9000), result: 'win', note: 'Held for several months before saturation' },
      { name: typeVerb(r.type) + ' · Cloudflare', date: 'Aug 2024', outcome_aud: 4000 + (hashStr(r.id + 'b') % 6000), result: 'win', note: 'Still active' },
      { name: typeVerb(r.type) + ' · MongoDB', date: 'Jan 2025', outcome_aud: -(2000 + (hashStr(r.id + 'c') % 3000)), result: 'loss', note: 'Rolled back — did not clear baseline' }
    ];
  }

  // ---- factory: fill every field so the drill-down never hits an undefined --
  function rec(o) {
    var meta = CLIENT_META[o.client_id];
    // Correctness guard: a rec can only use a platform its client actually runs ('Multi' = cross-platform).
    if (meta && meta.platforms && o.platform !== 'Multi' && meta.platforms.indexOf(o.platform) < 0) {
      throw new Error('brain-mock-data: ' + o.id + ' assigns platform "' + o.platform + '" to ' + o.client_id + ', which does not run it (runs: ' + meta.platforms.join(', ') + ')');
    }
    var rnd = mulberry32(hashStr(o.id));
    var created = new Date(BASE_DATE.getTime() - (o.daysAgo || 0) * 86400000);
    // Placement-isolation & site-quality need a per-domain/per-placement breakdown that the
    // current pipeline does NOT ingest (TTD stops at ad_group×creative, Meta at ad×date) — flag it.
    var readiness = o.data_readiness || ((o.type === 'placement' || o.type === 'site_quality') ? 'needs_ingest' : 'live');
    var dataSource = o.data_source || PLATFORM_SOURCE[o.platform] || [];

    // headline metrics (internally consistent) unless explicitly provided
    var m = o.metrics_21d;
    if (!m) {
      var imp = 60000 + Math.floor(rnd() * 260000);
      var cpm = 6 + rnd() * 10;
      var conv = Math.max(6, Math.round(imp * (0.00008 + rnd() * 0.0004)));
      var cvr = round(conv / imp * 100, 4);
      var mult = round(1.8 + rnd() * 2.0, 1);
      m = { impressions: imp, spend_aud: Math.round(imp / 1000 * cpm), conversions: conv, cvr_pct: cvr, cvr_vs_avg_multiple: mult };
    }
    var peakDay = 6 + Math.floor(rnd() * 12);
    var series = o.time_series || makeSeries(o.id, m.cvr_pct, m.cvr_vs_avg_multiple, peakDay);
    var outDays = o.outperformance_days || ((15 + Math.floor(rnd() * 7)) + ' of 21');
    var fraud = o.fraud_check || (o.type === 'site_quality'
      ? 'Flagged as made-for-advertising: high ad density, low dwell time, bot-like refresh patterns.'
      : 'No suspicious traffic patterns detected.');
    var detail = o.detail_paragraph || ('Over the last 21 days, this signal ran at ' + m.cvr_pct + '% versus the ' + r_platformAvg(o.platform) + ' average of ' + round(m.cvr_pct / m.cvr_vs_avg_multiple, 4) + '% — about ' + m.cvr_vs_avg_multiple + '× the channel norm across ' + outDays.split(' ')[0] + ' of the last 21 days.');

    var assignee = o.assignee || ASSIGNEES[hashStr(o.id) % ASSIGNEES.length];
    var due = o.due_date || fmtDate(new Date(BASE_DATE.getTime() + (2 + (hashStr(o.id) % 6)) * 86400000));
    var preview = o.clickup_task_preview || {
      title: '[' + o.client_name + '] ' + o.platform + ' · ' + o.title,
      description: o.short_description + ' Full config, evidence, and rollback plan in the linked Brain page. Once implemented, click Confirm done so we can start tracking performance against baseline.',
      priority: o.confidence >= 0.85 ? 'high' : (o.confidence >= 0.72 ? 'normal' : 'low'),
      assignee: assignee, project: 'Bidbrain Optimizations', due_date: due, links_to_r_id: o.id
    };

    return {
      id: o.id, client_id: o.client_id, client_name: o.client_name, currency: meta.cur,
      platform: o.platform, type: o.type, title: o.title, short_description: o.short_description,
      evidence: { metrics_21d: m, detail_paragraph: detail, outperformance_days: outDays, fraud_check: fraud, time_series: series },
      historical_pattern: o.historical_pattern || defaultHistory(o),
      proposed_config: o.proposed_config || defaultConfig(o, rnd),
      risks: o.risks || defaultRisks(o),
      clickup_task_preview: preview,
      confidence: o.confidence, estimated_impact_aud_monthly: o.estimated_impact_aud_monthly,
      status: o.status, created_at: created.toISOString(),
      data_source: dataSource, data_readiness: readiness
    };
  }
  function r_platformAvg(p) { return p === 'Multi' ? 'cross-platform' : (p + ' Run of Network'); }
  function fmtDate(d) { return d.toISOString().slice(0, 10); }

  // helper to keep the seed list terse
  function C(client_id) { return { id: client_id, name: CLIENT_META[client_id].name }; }

  // ---- the 30 seed recommendations -----------------------------------------
  var SEED = [
    // ResetData (6)
    { id: 'R-2847', c: 'resetdata', platform: 'Trade Desk', type: 'placement', conf: 0.87, impact: 18000, status: 'review', daysAgo: 0,
      title: 'Add line item targeting tech.slashdot.org placement',
      short: 'Isolate a high-performing placement currently bundled inside Run of Network.',
      metrics_21d: { impressions: 241000, spend_aud: 2024, conversions: 47, cvr_pct: 0.0195, cvr_vs_avg_multiple: 3.2 },
      detail_paragraph: 'Over the last 21 days, tech.slashdot.org converted at 0.0195% versus the Trade Desk Run of Network average of 0.0061%. This placement is not currently isolated — it sits inside a broader ROP line item at an average $8.40 CPM.',
      outperformance_days: '19 of 21', fraud_check: 'No suspicious traffic patterns detected.',
      historical_pattern: [
        { name: 'techcrunch.com isolation · ResetData', date: 'Mar 2025', outcome_aud: 14000, result: 'win', note: 'Line item ran 4 months before saturation' },
        { name: 'arstechnica.com isolation · Cloudflare', date: 'Aug 2024', outcome_aud: 9000, result: 'win', note: 'Still active' },
        { name: 'theregister.com isolation · MongoDB', date: 'Jan 2025', outcome_aud: -3000, result: 'loss', note: 'Rolled back after 6 weeks — audience mismatch' }
      ],
      proposed_config: { line_item_name: 'RD_TDD_Slashdot_Iso_Jul26', placement_targeting: 'tech.slashdot.org (allowlist)', daily_budget_aud: 180, max_cpm_aud: 14.00, audience: 'Same as parent ROP · retargeting excluded', frequency_cap: '3 / user / 7 days', flight_start: '2026-07-14', flight_end: '2026-08-14', parent_rop_adjustment: 'Reduce daily budget by $180 · exclude slashdot.org' },
      risks: [
        { title: 'Inventory ceiling', body: 'Placement served ~340k impressions/month in the last quarter. At $14 CPM cap, spend maxes around $4.7k/mo — well under the $18k impact estimate. The uplift comes from CVR, not volume, so headroom is fine.' },
        { title: 'Cannibalization', body: 'Some of the isolated conversions may have happened anyway via ROP. Impact estimate already discounts by 30% for cannibalization based on the techcrunch precedent.' },
        { title: 'Audience mismatch check (added post-MongoDB)', body: 'Slashdot audience skews developer/sysadmin, which aligns with ResetData ICP (verified via GA4 landing-page behaviour). Low mismatch risk.' }
      ],
      clickup_task_preview: { title: '[ResetData] Add Trade Desk line item · tech.slashdot.org isolation', description: 'Isolate the tech.slashdot.org placement into its own line item. Full config, evidence, and rollback plan in the linked Brain page. Once implemented, click Confirm done so we can start tracking performance against baseline.', priority: 'high', assignee: 'Zen', project: 'Bidbrain Optimizations', due_date: '2026-07-08', links_to_r_id: 'R-2847' } },
    { id: 'R-2831', c: 'resetdata', platform: 'Reddit', type: 'frequency_cap', conf: 0.74, impact: 4000, status: 'in_clickup', daysAgo: 12,
      title: 'Cap frequency on r/devops prospecting', short: 'Uncapped prospecting is over-serving the same users — tighten to protect efficiency.' },
    { id: 'R-2838', c: 'resetdata', platform: 'Meta', type: 'audience', conf: 0.79, impact: 9000, status: 'in_clickup', daysAgo: 8,
      title: 'Shift lookalike 3% to ICP interest stack', short: 'Broad lookalike is drifting off-ICP; an interest + job-title stack matches better.' },
    { id: 'R-2842', c: 'resetdata', platform: 'Google Ads', type: 'negative_keywords', conf: 0.83, impact: 6000, status: 'review', daysAgo: 5,
      title: 'Add negative keywords for free-tier search terms', short: 'Search spend is leaking on "free" and job-seeker queries that never convert.' },
    { id: 'R-2849', c: 'resetdata', platform: 'Meta', type: 'creative', conf: 0.68, impact: 5000, status: 'review', daysAgo: 3,
      title: 'Rotate fatigued prospecting creative', short: 'Frequency on the lead creative set has climbed past the fatigue threshold.' },
    { id: 'R-2835', c: 'resetdata', platform: 'Multi', type: 'site_quality', conf: 0.95, impact: 12000, status: 'review', daysAgo: 10,
      title: 'Blacklist MFA cluster across programmatic', short: 'A made-for-advertising domain cluster is absorbing spend with near-zero real engagement.' },

    // MongoDB (4)
    { id: 'R-2833', c: 'mongodb', platform: 'Trade Desk', type: 'placement', conf: 0.9, impact: 21000, status: 'won', daysAgo: 13,
      title: 'Isolate bloomberg.com placement', short: 'Bloomberg is outperforming inside ROP — carve it into its own line item.' },
    { id: 'R-2840', c: 'mongodb', platform: 'Trade Desk', type: 'budget_shift', conf: 0.81, impact: 11000, status: 'review', daysAgo: 6,
      title: 'Reallocate Trade Desk delivery to DNB IDE Business & Ops Leaders', short: 'That programme is pacing best on delivered CS leads — move impressions off the softer Single Touch line.',
      src: ['raw_snowflake.salesforce_cs_apac_all', 'raw_snowflake.tradedesk_apac_all'] },
    { id: 'R-2845', c: 'mongodb', platform: 'Trade Desk', type: 'creative', conf: 0.76, impact: 8000, status: 'in_clickup', daysAgo: 9,
      title: 'Rotate the fatigued DNB IDE display creative', short: 'Frequency on the DNB display set has climbed while its content-LP view rate is softening.' },
    { id: 'R-2830', c: 'mongodb', platform: 'Multi', type: 'site_quality', conf: 0.98, impact: 22000, status: 'review', daysAgo: 11,
      title: 'Blacklist made-for-advertising domains', short: 'High-density MFA domains detected across the display buy — recommend a shared blacklist.' },

    // Cloudflare (5)
    { id: 'R-2836', c: 'cloudflare', platform: 'LinkedIn', type: 'creative', conf: 0.72, impact: 7000, status: 'measuring', daysAgo: 7,
      title: 'Enable document ads format', short: 'Document ads tend to lift engaged sessions for technical audiences — worth a test.' },
    { id: 'R-2843', c: 'cloudflare', platform: 'Reddit', type: 'audience', conf: 0.7, impact: 5000, status: 'review', daysAgo: 4,
      title: 'Expand to adjacent security subreddits', short: 'Engagement in r/netsec suggests nearby communities are worth adding.' },
    { id: 'R-2848', c: 'cloudflare', platform: 'Trade Desk', type: 'budget_shift', conf: 0.84, impact: 13000, status: 'review', daysAgo: 2,
      title: 'Reallocate budget from LINE to Trade Desk', short: 'LINE is underpacing this flight; Trade Desk has efficient headroom.' },
    { id: 'R-2851', c: 'cloudflare', platform: 'LINE', type: 'budget_shift', conf: 0.86, impact: 15000, status: 'measuring', daysAgo: 6,
      title: 'Rebalance LINE spend into LinkedIn as JP CPL climbs', short: 'JP cost-per-lead on LINE is drifting above target — shift a slice into the LinkedIn Roverpath line.' },
    { id: 'R-2837', c: 'cloudflare', platform: 'Trade Desk', type: 'frequency_cap', conf: 0.73, impact: 4500, status: 'review', daysAgo: 1,
      title: 'Cap frequency on Roverpath prospecting', short: 'Prospecting frequency is climbing with no reach gain — cap to cut waste.' },

    // Schneider (4)
    { id: 'R-2839', c: 'schneider', platform: 'DV360', type: 'placement', conf: 0.85, impact: 12000, status: 'review', daysAgo: 5,
      title: 'Isolate the trade-publication placement on Water & Environment', short: 'A trade-publication placement is outperforming the ROP average for the Water & Environment program.' },
    { id: 'R-2844', c: 'schneider', platform: 'LinkedIn', type: 'audience', conf: 0.8, impact: 10000, status: 'measuring', daysAgo: 8,
      title: 'Expand seniority band on EBA program', short: 'Director-level engagement is strong; widen one seniority band to scale MQLs.' },
    { id: 'R-2846', c: 'schneider', platform: 'Trade Desk', type: 'bid_strategy', conf: 0.77, impact: 9000, status: 'in_clickup', daysAgo: 9,
      title: 'Swap heavy-industries line to target CPA', short: 'Max-clicks is buying cheap but low-intent clicks; target CPA should tighten quality.' },
    { id: 'R-2852', c: 'schneider', platform: 'DV360', type: 'budget_shift', conf: 0.82, impact: 6000, status: 'review', daysAgo: 3,
      title: 'Shift DV360 budget from Global Rebrand to EBA', short: 'EcoStruxure Building Activate is pacing to target while Global Rebrand lags — rebalance the DV360 line.',
      src: ['raw_snowflake.dv360_apac', 'raw_snowflake.salesforce_cs_apac_all'] },

    // VMCH (3)
    { id: 'R-2834', c: 'vmch', platform: 'Trade Desk', type: 'creative', conf: 0.69, impact: 3000, status: 'review', daysAgo: 12,
      title: 'Rotate fatigued RAC service-line creative', short: 'Residential aged-care creative frequency is high with softening click-through.' },
    { id: 'R-2850', c: 'vmch', platform: 'Trade Desk', type: 'frequency_cap', conf: 0.71, impact: 2500, status: 'review', daysAgo: 6,
      title: 'Tighten the frequency cap on the Disability service line', short: 'The Disability campaign is over-serving a narrow audience; cap to extend reach at the same spend.' },
    { id: 'R-2853', c: 'vmch', platform: 'Trade Desk', type: 'bid_strategy', conf: 0.65, impact: 2000, status: 'rolled_back', daysAgo: 10,
      title: 'Daypart SAH line to business hours', short: 'Enquiry events cluster in daytime; concentrate delivery there.' },

    // TLM (3)
    { id: 'R-2841', c: 'tlm', platform: 'Google Ads', type: 'bid_strategy', conf: 0.78, impact: 5000, status: 'measuring', daysAgo: 7,
      title: 'Swap shopping campaign to target ROAS', short: 'Manual bidding is leaving efficient shopping demand on the table.' },
    { id: 'R-2854', c: 'tlm', platform: 'Google Ads', type: 'negative_keywords', conf: 0.8, impact: 3500, status: 'review', daysAgo: 4,
      title: 'Add negatives for wholesale coffee terms', short: 'Wholesale and cafe-equipment queries are not the DTC buyer — exclude them.' },
    { id: 'R-2855', c: 'tlm', platform: 'Google Ads', type: 'negative_keywords', conf: 0.72, impact: 4000, status: 'review', daysAgo: 2,
      title: 'Exclude barista-course & job-seeker search terms', short: 'Search and PMax are matching "barista course" / jobs queries that never purchase — add them as negatives.' },

    // PropTrack (3)
    { id: 'R-2832', c: 'proptrack', platform: 'LinkedIn', type: 'audience', conf: 0.83, impact: 11000, status: 'review', daysAgo: 11,
      title: 'Add adjacent banking job functions to ABM set', short: 'Risk and lending functions engage but are outside the current target list.' },
    { id: 'R-2856', c: 'proptrack', platform: 'Trade Desk', type: 'placement', conf: 0.88, impact: 28000, status: 'review', daysAgo: 3,
      title: 'Isolate top finance-vertical placement', short: 'A finance publication is beating ROP — isolate it to protect the efficiency.' },
    { id: 'R-2857', c: 'proptrack', platform: 'Multi', type: 'site_quality', conf: 0.93, impact: 9000, status: 'in_clickup', daysAgo: 8,
      title: 'Blacklist low-quality finance-content farms', short: 'Content-farm domains are inflating impressions without qualified reach.' },

    // HireRight (2)
    { id: 'R-2858', c: 'hireright', platform: 'LinkedIn', type: 'creative', conf: 0.67, impact: 3000, status: 'review', daysAgo: 5,
      title: 'Refresh fatigued lead-gen creative', short: 'The lead-gen carousel has run long enough that engagement is decaying.' },
    { id: 'R-2859', c: 'hireright', platform: 'DV360', type: 'budget_shift', conf: 0.75, impact: 7000, status: 'in_clickup', daysAgo: 9,
      title: 'Shift budget to the efficient APAC line', short: 'The APAC line is pacing efficiently while another underdelivers — rebalance.' }
  ];

  var RECOMMENDATIONS = SEED.map(function (s) {
    return rec({
      id: s.id, client_id: s.c, client_name: CLIENT_META[s.c].name, platform: s.platform, type: s.type,
      title: s.title, short_description: s.short, confidence: s.conf, estimated_impact_aud_monthly: s.impact,
      status: s.status, daysAgo: s.daysAgo,
      metrics_21d: s.metrics_21d, detail_paragraph: s.detail_paragraph, outperformance_days: s.outperformance_days,
      fraud_check: s.fraud_check, historical_pattern: s.historical_pattern, proposed_config: s.proposed_config,
      risks: s.risks, clickup_task_preview: s.clickup_task_preview,
      data_source: s.src, data_readiness: s.ready
    });
  });

  // ---- helpers (the front-end + future server contract) ---------------------
  function normId(id) { return String(id).toUpperCase().replace(/^(?!R-)/, function (m, off, s) { return /^\d/.test(s) ? 'R-' : ''; }); }
  function getRecommendationById(id) {
    if (id == null) return null;
    var key = String(id).toUpperCase();
    if (!/^R-/.test(key)) key = 'R-' + key.replace(/^R/, '');
    for (var i = 0; i < RECOMMENDATIONS.length; i++) if (RECOMMENDATIONS[i].id.toUpperCase() === key) return RECOMMENDATIONS[i];
    return null;
  }
  function getFilteredRecommendations(f) {
    f = f || {};
    return RECOMMENDATIONS.filter(function (r) {
      if (f.client_id && f.client_id !== 'all' && r.client_id !== f.client_id) return false;
      if (f.platform && f.platform !== 'all' && r.platform !== f.platform) return false;
      if (f.type && f.type !== 'all' && r.type !== f.type) return false;
      if (f.status && f.status !== 'all' && r.status !== f.status) return false;
      if (f.min_confidence != null && r.confidence < f.min_confidence) return false;
      return true;
    });
  }
  function updateStatus(id, newStatus) {
    var r = getRecommendationById(id);
    if (!r) return null;
    r.status = newStatus;
    return r;
  }

  return {
    RECOMMENDATIONS: RECOMMENDATIONS,
    CLIENT_META: CLIENT_META,
    getRecommendationById: getRecommendationById,
    getFilteredRecommendations: getFilteredRecommendations,
    updateStatus: updateStatus
  };
});
