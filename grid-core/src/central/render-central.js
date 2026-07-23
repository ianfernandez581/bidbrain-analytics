/*
 * src/central/render-central.js — the Central tab view (MERGED with Register, Phase 2).
 * ----------------------------------------------------------------------------
 * Renders THE one campaign table: every DERIVED cell computed fresh by
 * src/central/calc.js (never stored, never editable). Owns its own filter/sort
 * state (does not touch the pulse `F`).
 *
 * Phase 2 (2026-07-22) absorbed the Register tab: the column-group filter bar
 * (Core locked / Pacing / Budget / Margin / Performance / Links), the
 * Group: advertiser vs Flat toggle, search, a Manager filter, per-campaign
 * expandable detail rows, header hover hints, the pacing mini-bar and the
 * Register-only columns (Budget Gross, Ad-Serving rate+cost, Impressions,
 * Link, Next Report). Register's tab/section in the-grid.html is DELETED.
 *
 * CONFIG edits (Managed By / Channel / Status dropdowns) and plan-reader commits
 * persist to central_rows via the server; here we layer those overrides over the
 * seed at render time and tag each field's source.
 *
 * UMD: browser -> window.CentralView. Reads window.CentralCalc / window.CentralSeed
 * / window.CentralPlan / window.toast at CALL time (all load before this runs).
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.CentralView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var DASH = '<span class="ct-muted">—</span>';
  // Freshness thresholds live in ONE place — src/central/staleness.js (Phase 4 item 4).
  // Resolved at call time (browser global or Node require), same pattern as getCalc().
  function getStale() {
    if (typeof window !== 'undefined' && window.CentralStaleness) return window.CentralStaleness;
    if (typeof module !== 'undefined' && module.exports) { try { return require('./staleness'); } catch (e) { /* absent */ } }
    return null;
  }
  var MANAGERS = ['Mel', 'Zhen', 'Sophia'];
  // Real sheet vocabulary + app-only Draft. "Not Active" is a real status (never coerced).
  var STATUSES = ['Active', 'Paused', 'Not Active', 'Ended', 'Draft'];
  var AGENCY_LABEL = { '100% Digital': '100% DIGITAL', 'Transmission': 'TRANSMISSION' };

  // ---- per-channel colour (real brand hues; 2-letter code is the backup cue) ----
  // Distinct, high-contrast per-channel palette (2-letter code) — instantly distinguishable.
  var CHANNEL_COLORS = {
    'Trade Desk': { bg: '#dbeafe', fg: '#1d4ed8', code: 'TD' },
    'LinkedIn': { bg: '#e0e7ff', fg: '#4338ca', code: 'LI' },
    'Google Ads': { bg: '#fef3c7', fg: '#92400e', code: 'GA' },
    'Meta': { bg: '#fce7f3', fg: '#be185d', code: 'ME' },
    'Reddit': { bg: '#fff7ed', fg: '#c2410c', code: 'RD' },
    'DV360': { bg: '#ccfbf1', fg: '#0f766e', code: 'DV' },
    'DOOH': { bg: '#f3e8ff', fg: '#6b21a8', code: 'DO' },
    'LINE': { bg: '#dcfce7', fg: '#166534', code: 'LN' }
  };
  var CHANNEL_OTHER = { bg: '#F1EFE8', fg: '#444441', code: '—' };
  // normalized lookup so the sheet's "TradeDesk"/"Linkedin" (no space / different case) and
  // "facebook" all resolve to the right chip instead of falling through to gray.
  var CHANNEL_NORM = (function () { var m = {}; Object.keys(CHANNEL_COLORS).forEach(function (k) { m[k.toLowerCase().replace(/[^a-z0-9]/g, '')] = CHANNEL_COLORS[k]; }); m.facebook = CHANNEL_COLORS.Meta; return m; })();
  function chanTheme(ch) { if (!ch) return CHANNEL_OTHER; return CHANNEL_NORM[String(ch).toLowerCase().replace(/[^a-z0-9]/g, '')] || CHANNEL_OTHER; }
  // Channel chip — distinct per-channel colour (bg + fg) + 2-letter code badge, for instant
  // at-a-glance distinction across the table.
  function channelChip(ch) {
    if (!ch) return DASH;
    var t = chanTheme(ch);
    return '<span class="ct-chan" style="background:' + t.bg + ';color:' + t.fg + '">' +
      '<span class="ct-chan-code" style="background:' + t.fg + '">' + esc(t.code) + '</span>' + esc(ch) + '</span>';
  }
  // compact cluster of unique channel code-badges (client summary row)
  function channelCluster(rows) {
    var seen = {}, out = [];
    rows.forEach(function (r) { var ch = r.channel; if (ch && !seen[ch]) { seen[ch] = 1; var t = chanTheme(ch); out.push('<span class="ct-chan-code" style="background:' + t.fg + '" title="' + esc(ch) + '">' + esc(t.code) + '</span>'); } });
    return out.length ? '<span class="ct-chancluster">' + out.join('') + '</span>' : DASH;
  }

  // ---- formatters (Task 3 rules) ----
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function money(n) { if (n == null) return DASH; var a = Math.abs(n); if (a >= 1000) return '$' + (n / 1000).toFixed(1) + 'K'; return '$' + Math.round(n).toLocaleString(); }
  function moneyPlain(n) { if (n == null) return ''; var a = Math.abs(n); if (a >= 1000) return '$' + (n / 1000).toFixed(1) + 'K'; return '$' + Math.round(n); }
  function pct1(n) { return n == null ? DASH : (n * 100).toFixed(1) + '%'; }
  function pct1Plain(n) { return n == null ? '' : (n * 100).toFixed(1) + '%'; }
  function dateDMY(v) { if (!v) return DASH; var d = new Date(v); if (isNaN(d)) return DASH; return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }); }

  // ============================ state ============================
  var CS = {
    client: 'all', statusView: 'live', health: 'all',   // live-first default
    sortKey: null, sortDir: 1,           // null = natural order; sorting stays INSIDE groups when grouped
    q: '', qRaw: '', mgr: 'all',         // search + Manager filter (ported from Register, Phase 2)
    group: 'advertiser',                 // 'advertiser' (agency sections + client accordion) | 'flat' (ported)
    // column-group toggles (ported from Register). Core is always on (locked chip).
    // ALL groups default ON so the merged Central first paints with today's full column set.
    colGroups: { pacing: true, budget: true, margin: true, perf: true, links: true },
    openDetails: {},                     // per-campaign expanded detail rows (ported from Register)
    campaigns: null, overrides: null, lastSynced: null, highlightMissing: null,
    openClients: {}                       // client-accordion: which client groups are expanded (default: none)
  };
  var LIVE_STATUSES = ['Active', 'Paused', 'Draft'];   // "Live" = day-to-day working set
  // calc engine: browser global when loaded as a classic script, require() under Node tests
  function getCalc() {
    if (typeof window !== 'undefined' && window.CentralCalc) return window.CentralCalc;
    try { return require('./calc'); } catch (e) { return null; }
  }

  // SINGLE NAME-TRANSLATION POINT — the ONLY place grid (build_grid_data.py) field
  // names are converted to calc.js names. Seed rows are already calc-shaped (pass
  // through). Do not translate field names anywhere else.
  function mapGridRowToCentral(row) {
    if (row == null) return row;
    var isGridShaped = ('advertiser' in row) || ('clientSpent' in row) || ('forecastCPM' in row) || ('keyKPI' in row);
    if (!isGridShaped) return row; // seed / already-calc-shaped
    var M = {
      advertiser: 'client', campaign: 'name', start: 'startDate', end: 'endDate',
      clientSpent: 'clientSpend', forecastCPM: 'forecastCpm', keyKPI: 'keyKpi',
      adservingCost: 'adServingCost', kpiPerf: 'kpiPerformance'
    };
    var out = {};
    for (var k in row) if (Object.prototype.hasOwnProperty.call(row, k)) out[M[k] || k] = row[k];
    return out;
  }

  // keep in sync with plan-reader.js centralRowId() — join key is (client,name)
  function centralRowId(client, name) {
    var n = function (s) { return String(s == null ? '' : s).trim().toLowerCase().replace(/\s+/g, ' '); };
    return n(client) + '::' + n(name);
  }

  // Manual-entry [CONFIG] fields — the ones a trader fills by hand. Empty ones get the
  // needs-input tint + inline edit; the row's missing count is over this set. NEVER
  // includes [DERIVED] (their — is correct output) or [API] (that is the sync's job).
  var NEEDS_INPUT = ['managedBy', 'channel', 'status', 'platformMargin', 'jobNumber', 'forecastCpm',
    'keyKpi', 'totalBudget', 'budgetGross', 'startDate', 'endDate', 'adServingCost', 'notes', 'spendMult',
    'name'];   // Phase 3: unnamed-but-real rows repairable inline (fill-empty in the Campaign cell)
  function isEmpty(v) { return v == null || v === ''; }
  function needsInput(field, value) { return NEEDS_INPUT.indexOf(field) >= 0 && isEmpty(value); }

  // Central's SOURCE OF TRUTH is the DB (GET /api/central/campaigns). The sheet parse
  // was a ONE-TIME import, not a pipeline — Central never reads the baked DATA literal.
  // Falls back to the seed FIXTURE only when the API is unavailable (Node smoke tests).
  function getSourceRows() {
    if (Array.isArray(CS.campaigns) && CS.campaigns.length) return CS.campaigns;
    return (window.CentralSeed && window.CentralSeed.CAMPAIGNS) || [];
  }

  // Build render rows: campaigns -> map (single name-translation, passthrough) -> attach
  // per-field provenance (central_rows) -> compute derived FRESH (never stored). The
  // campaign row IS the value truth; overrides supply only the source/filename/cellRef.
  function buildRows() {
    var src = getSourceRows();
    var calc = window.CentralCalc;
    var ov = CS.overrides || {};
    // Pacing "as of" = the DB's newest lastSyncedAt (falling back to now), the SAME
    // anchor Pulse/Register use — so all tabs agree to the digit (Phase 1).
    var asOf = (calc && calc.latestSyncAsOf && calc.latestSyncAsOf(src)) || new Date();
    return src.map(function (raw) {
      var r = Object.assign({}, mapGridRowToCentral(raw));
      // datetime-in-campaign-name sheet quirk → always a clean string, never a Date/serial
      if (r.name instanceof Date) r.name = r.name.toISOString().slice(0, 10);
      else if (typeof r.name === 'string') r.name = r.name.replace(/\s00:00:00$/, '');
      r.section = r.section || r.agency;                 // DB uses 'section'; seed uses 'agency'
      var id = r.id || centralRowId(r.client, r.name);    // campaign id (seed fixture: client::name)
      r._id = id; r._src = {};
      var o = ov[id] || {};
      for (var f in o) if (Object.prototype.hasOwnProperty.call(o, f)) r._src[f] = o[f];   // provenance only
      r._d = calc ? calc.computeRow(r, asOf) : {};
      r._missing = NEEDS_INPUT.filter(function (f) { return isEmpty(r[f]); });
      // unbilled-basis: spend present but no per-channel billing multiplier to certify the
      // client-spend basis. Fires widely BY DESIGN until spendMult is populated per channel.
      r._unbilled = (r.mediaSpend != null || r.clientSpend != null) && (r.spendMult == null || Number(r.spendMult) === 1);
      r._archived = !!r.archivedAt;
      return r;
    });
  }

  // ============================ columns ============================
  // type: 'config' | 'api' | 'derived'. get() = sort key (numbers or lowercased strings).
  // g = column GROUP (ported from Register): 'core' is always shown; the other five
  // toggle from the Columns bar. Columns are ordered group-contiguous (core → pacing →
  // budget → margin → perf → links) so a toggled group appears/disappears as one block.
  var COL_GROUPS = [['pacing', 'Pacing'], ['budget', 'Budget'], ['margin', 'Margin'], ['perf', 'Performance'], ['links', 'Links']];
  var GROUP_LABEL = { core: 'Core', pacing: 'Pacing', budget: 'Budget', margin: 'Margin', perf: 'Performance', links: 'Links & Notes' };
  function srcIcon(r, field) {
    var s = r._src[field];
    if (!s || s.source !== 'plan') return '';
    var ref = [s.filename, s.cellRef].filter(Boolean).join(' · ');
    return '<span class="ct-srcdoc" title="From media plan: ' + esc(ref) + '">' +
      '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></span>';
  }
  function marginTip(r) {
    var cm = r._d.campaignMargin, pm = r.platformMargin;
    if (cm == null && pm == null) return '';
    return 'realized ' + (cm == null ? '—' : Math.round(cm * 100) + '%') + ' vs set ' + (pm == null ? '—' : Math.round(pm * 100) + '%');
  }
  var HEALTH_LABEL = { winner: 'Winner', watch: 'Watch', steady: 'Steady' };

  var COLS = [
    // ---- CORE (always shown; the locked chip) ----
    {
      id: 'campaign', label: 'Campaign', type: 'config', g: 'core', sticky: 1, hint: 'Campaign name and its goal', get: function (r) { return (r.name || '').toLowerCase(); },
      cell: function (r, grouped) {
        var client = grouped ? '' : '<div class="ct-cl">' + esc(r.client || '') + '</div>';
        var badges = '';
        if (!r.jobNumber) badges += '<span class="ct-badge ct-badge-warn" title="No job number set">no job #</span>';
        if (r._unbilled) { var utip = isLive(r) ? 'Media spend is live; client spend awaits spendMult (still the sheet-imported value).' : 'No spendMult recorded for this channel — the client-spend billing basis cannot be verified. Expected until spendMult is populated.'; badges += '<span class="ct-badge ct-badge-bad" title="' + esc(utip) + '">unbilled basis</span>'; }
        if (r._missing.length) badges += '<button class="ct-badge ct-badge-miss" data-missing="' + esc(r._id) + '" title="' + r._missing.length + ' CONFIG fields empty: ' + esc(r._missing.join(', ')) + '">' + r._missing.length + ' fields missing</button>';
        // archive is a soft delete (row action); archived rows show a muted tag instead
        var act = r._archived
          ? '<span class="ct-arch-tag">archived</span>'
          : '<button class="ct-arch" data-archive="' + esc(r._id) + '" title="Archive (keeps it as history under the Archived filter — never deleted)">archive</button>';
        // expand caret (ported from Register): toggles the full-detail row for this campaign
        var open = !!CS.openDetails[r._id];
        var caret = '<button class="ct-exp' + (open ? ' open' : '') + '" data-detail="' + esc(r._id) + '" aria-expanded="' + open + '" title="Show full detail for this campaign">&#9654;</button>';
        // unnamed-but-real row → fill-empty affordance (Phase 3): type the name in place
        var nm = isEmpty(r.name) ? editableEmptyCell(r, 'name', 'add name') : esc(r.name);
        return client + '<div class="ct-nm">' + caret + nm + act + '</div>' + (r.objective ? '<div class="ct-sub">' + esc(r.objective) + '</div>' : '') + (badges ? '<div class="ct-badges">' + badges + '</div>' : '');
      }
    },
    { id: 'channel', label: 'Channel', type: 'config', g: 'core', hint: 'Ad platform, e.g. Meta, Google, Trade Desk', get: function (r) { return (r.channel || '').toLowerCase(); }, editable: 'channel', cell: function (r) { return channelChip(r.channel) + srcIcon(r, 'channel'); } },
    { id: 'managedBy', label: 'Managed By', type: 'config', g: 'core', hint: 'Team member managing it', get: function (r) { return (r.managedBy || '').toLowerCase(); }, editable: 'managedBy', cell: function (r) { return (r.managedBy ? '<span class="ct-mgr">' + esc(r.managedBy) + '</span>' : DASH) + srcIcon(r, 'managedBy'); } },
    { id: 'status', label: 'Status', type: 'config', g: 'core', hint: 'Active, Paused, Not Active, Ended or Draft', get: function (r) { return (r.status || '').toLowerCase(); }, editable: 'status', cell: function (r) { return '<span class="ct-pill ct-st-' + statusCls(r.status) + '">' + esc(r.status || '—') + '</span>'; } },
    { id: 'startDate', label: 'Start', type: 'config', g: 'core', hint: 'Campaign start date', get: function (r) { return r.startDate || ''; }, cell: function (r) { return dateDMY(r.startDate); } },
    { id: 'endDate', label: 'End', type: 'config', g: 'core', hint: 'Campaign end date', get: function (r) { return r.endDate || ''; }, cell: function (r) { return dateDMY(r.endDate); } },
    // ---- PACING ----
    { id: 'pctBudgetSpent', label: '% Spent', type: 'derived', num: 1, g: 'pacing', hint: 'Share of the budget spent so far', get: function (r) { return r._d.pctBudgetSpent; }, cell: function (r) { return pct1(r._d.pctBudgetSpent); } },
    { id: 'pctFlightElapsed', label: '% Elapsed', type: 'derived', num: 1, g: 'pacing', hint: 'Share of the campaign run that has passed', get: function (r) { return r._d.pctFlightElapsed; }, cell: function (r) { return pct1(r._d.pctFlightElapsed); } },
    {
      id: 'pacingStatus', label: 'Pacing', type: 'derived', g: 'pacing', hint: 'Is spend on schedule, too fast or too slow. Early = under 15% of flight elapsed, deliberately not judged', get: function (r) { return r._d.pacingStatus || ''; },
      // pill + mini pace bar (bar ported from Register): fill = % spent, marker = % elapsed
      cell: function (r) {
        var p = r._d.pacingStatus;
        if (!p || p === '-') return DASH;
        var lc = p.toLowerCase();
        var sp = r._d.pctBudgetSpent != null ? Math.min(100, r._d.pctBudgetSpent * 100) : 0;
        var el = r._d.pctFlightElapsed != null ? Math.min(100, r._d.pctFlightElapsed * 100) : null;
        return '<span class="ct-pacecell"><span class="ct-pill ct-pace-' + lc + '">' + p + '</span>' +
          '<span class="ct-pacebar"><i class="ct-pb-' + lc + '" style="width:' + sp + '%"></i>' + (el != null ? '<u style="left:' + el + '%"></u>' : '') + '</span></span>';
      }
    },
    { id: 'health', label: 'Health', type: 'derived', g: 'pacing', hint: 'Portfolio health from margin + pacing + CPM', get: function (r) { return ({ watch: 0, steady: 1, winner: 2 })[r._d.health]; }, cell: function (r) { var h = r._d.health; return h ? '<span class="ct-pill ct-h-' + h + '">' + HEALTH_LABEL[h] + '</span>' : DASH; } },
    // ---- BUDGET ----
    { id: 'mediaSpend', label: 'Media Spend', type: 'api', num: 1, g: 'budget', hint: 'Spend on the ads themselves (media cost)', get: function (r) { return r.mediaSpend; }, cell: function (r) { return '<span class="ct-api-cell">' + money(r.mediaSpend) + metricsTag(r) + '</span>'; } },
    { id: 'clientSpend', label: 'Client Spend', type: 'api', num: 1, g: 'budget', hint: 'Amount billed to the client so far', get: function (r) { return r.clientSpend; }, cell: function (r) { return '<span class="ct-api-cell">' + money(r.clientSpend) + '</span>'; } },
    { id: 'totalBudget', label: 'Total Budget', type: 'config', num: 1, g: 'budget', hint: 'Total budget the client is paying', get: function (r) { return r.totalBudget; }, cell: function (r) { return money(r.totalBudget) + srcIcon(r, 'totalBudget'); } },
    { id: 'budgetGross', label: 'Budget Gross', type: 'config', num: 1, g: 'budget', hint: 'Total budget including fees (gross) — the client-billed budget', get: function (r) { return r.budgetGross; }, cell: function (r) { return money(r.budgetGross) + srcIcon(r, 'budgetGross'); } },
    { id: 'budgetRemaining', label: 'Remaining', type: 'derived', num: 1, g: 'budget', hint: 'Budget left to spend', get: function (r) { return r._d.budgetRemaining; }, cell: function (r) { return money(r._d.budgetRemaining); } },
    // ---- MARGIN ----
    { id: 'platformMargin', label: 'Plat. Margin', type: 'config', num: 1, g: 'margin', hint: 'Profit margin set on the ad-platform spend (used for TTD/DV360 profit-at-risk)', get: function (r) { return r.platformMargin; }, cell: function (r) { return (r.platformMargin == null ? DASH : Math.round(r.platformMargin * 100) + '%') + srcIcon(r, 'platformMargin'); } },
    {
      id: 'campaignMargin', label: 'Camp. Margin', type: 'derived', num: 1, g: 'margin', hint: 'Realized profit margin on the whole campaign', get: function (r) { return r._d.campaignMargin; },
      cell: function (r) {
        var band = r._d.marginBand;
        var val = r._d.campaignMargin == null ? DASH : Math.round(r._d.campaignMargin * 100) + '%';
        // config-gap indicator: LIVE media spend but client spend is still sheet-era (no
        // spendMult) — the margin is real but reads low until the multiplier is set. Distinct
        // from the amber needs-input tint (a neutral info mark, not a "missing field").
        var info = (isLive(r) && r.spendBasis === 'sheet')
          ? '<span class="ct-basis-info" title="Margin uses sheet-era client spend - set the billing multiplier (spendMult) for a live margin.">i</span>' : '';
        return '<span class="ct-margin ' + (band ? 'ct-band-' + band : '') + '" title="' + esc(marginTip(r)) + '">' + val + '</span>' + info;
      }
    },
    {
      id: 'spendMult', label: 'Spend Mult', type: 'config', num: 1, g: 'margin',
      hint: 'Billing multiplier: on sync, client spend = media spend x this (1.00 = billed at cost). Check the feed cost basis before setting - a client-billed feed needs 1 (see PHASE3_CLOUDFLARE_REPORT.md)',
      get: function (r) { var n = parseFloat(r.spendMult); return isNaN(n) ? null : n; },
      cell: function (r) { return spendMultCell(r) + srcIcon(r, 'spendMult'); }
    },
    { id: 'adServing', label: 'Ad-Serv Rate', type: 'config', num: 1, g: 'margin', hint: 'Ad-serving rate ($ per 1,000 impressions)', get: function (r) { var n = parseFloat(r.adServing); return isNaN(n) ? null : n; }, cell: function (r) { return (r.adServing == null || r.adServing === '' ? DASH : '$' + esc(String(r.adServing))) + srcIcon(r, 'adServing'); } },
    { id: 'adServingCost', label: 'Ad-Serv Cost', type: 'derived', num: 1, g: 'margin', hint: 'Total ad-serving cost (rate × impressions), computed — the sheet cost column is discarded', get: function (r) { return r._d.adServingCost; }, cell: function (r) { return money(r._d.adServingCost); } },
    // ---- PERFORMANCE ----
    { id: 'cpmPerformance', label: 'CPM Perf', type: 'derived', num: 1, g: 'perf', hint: 'Actual cost per 1,000 impressions (media-cost basis, same basis as Forecast CPM)', get: function (r) { return r._d.cpmPerformance; }, cell: function (r) { return r._d.cpmPerformance == null ? DASH : '$' + r._d.cpmPerformance.toFixed(2); } },
    { id: 'forecastCpm', label: 'Forecast CPM', type: 'config', num: 1, g: 'perf', hint: 'Forecast cost per 1,000 impressions', get: function (r) { return r.forecastCpm; }, cell: function (r) { return (r.forecastCpm == null ? DASH : '$' + Number(r.forecastCpm).toFixed(2)) + srcIcon(r, 'forecastCpm'); } },
    { id: 'keyKpi', label: 'Key KPI', type: 'config', g: 'perf', hint: 'The main goal metric for this campaign', get: function (r) { return (r.keyKpi || '').toLowerCase(); }, cell: function (r) { return editableTextCell(r, 'keyKpi') + srcIcon(r, 'keyKpi'); } },
    { id: 'kpiPerformance', label: 'KPI Perf', type: 'config', g: 'perf', hint: 'Actual result vs the goal', get: function (r) { return (r.kpiPerformance || '').toLowerCase(); }, cell: function (r) { var v = kpiVerdict(r.keyKpi, r.kpiPerformance); return editableTextCell(r, 'kpiPerformance', v === 'beat' ? 'ct-kpi-beat' : v === 'miss' ? 'ct-kpi-miss' : '') + srcIcon(r, 'kpiPerformance'); } },
    { id: 'impressions', label: 'Impressions', type: 'api', num: 1, g: 'perf', hint: 'Number of times the ads were shown', get: function (r) { return r.impressions; }, cell: function (r) { return r.impressions == null ? DASH : Number(r.impressions).toLocaleString('en-US'); } },
    // ---- LINKS & NOTES ----
    { id: 'jobNumber', label: 'Job #', type: 'config', g: 'links', hint: 'Internal job number', get: function (r) { return (r.jobNumber || '').toLowerCase(); }, cell: function (r) { return (r.jobNumber ? esc(r.jobNumber) : DASH) + srcIcon(r, 'jobNumber'); } },
    { id: 'campaignLink', label: 'Link', type: 'config', g: 'links', hint: 'Link to the campaign in the ad platform', get: function (r) { return r.campaignLink ? 1 : 0; }, cell: function (r) { return r.campaignLink ? '<a class="ct-link" href="' + esc(r.campaignLink) + '" target="_blank" rel="noopener" title="Open in the ad platform"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/></svg></a>' : DASH; } },
    { id: 'nextReportingDue', label: 'Next Report', type: 'config', g: 'links', hint: 'Date of the next client report', get: function (r) { return r.nextReportingDue || ''; }, cell: function (r) { return dateDMY(r.nextReportingDue); } },
    { id: 'notes', label: 'Notes', type: 'config', g: 'links', hint: 'Notes on this campaign', get: function (r) { return (r.notes || '').toLowerCase(); }, cell: function (r) { return r.notes ? esc(r.notes) : DASH; } }
  ];
  // the visible column set = core + every toggled-on group (ported from Register)
  function activeCols() { return COLS.filter(function (c) { return c.g === 'core' || CS.colGroups[c.g]; }); }
  var EDIT_COLS = ['channel', 'managedBy', 'status'];  // columns rendered as dropdowns
  function statusCls(s) { s = (s || '').toLowerCase(); if (s.indexOf('not active') >= 0) return 'notactive'; return s.indexOf('active') >= 0 ? 'active' : s.indexOf('paus') >= 0 ? 'paused' : s.indexOf('end') >= 0 ? 'ended' : 'draft'; }
  function isLive(r) { return r.metricsSource === 'bq' || r.metricsSource === 'BQ'; }
  // is this a sheet-import row inside a client that OTHERWISE syncs? (the §9 mixed
  // state — those rows are silently excluded from every sync and must read as such)
  function inMixedClient(r) {
    var ss = CS._clientSync && CS._clientSync[r.client];
    return !!(ss && ss.mixed && !isLive(r));
  }
  function metricsTag(r) {
    var live = isLive(r);
    var mixed = inMixedClient(r);
    var t = live ? ('Live from BigQuery' + (r.lastSyncedAt ? ' · synced ' + new Date(r.lastSyncedAt).toLocaleString('en-GB') : ''))
      : mixed ? 'Sheet-import row in an otherwise-synced client — NOT covered by the sync (unmapped or unapproved pair); its numbers never refresh'
        : 'From the one-time sheet import (not yet synced)';
    return '<span class="ct-msrc ct-msrc-' + (live ? 'live' : 'sheet') + (mixed ? ' ct-msrc-mixed' : '') + '" title="' + esc(t) + '">' + (live ? 'LIVE' : 'SHEET') + '</span>';
  }
  // compact per-client sync chip for the group summary row: NO SYNC / N SHEET / stale age
  function clientSyncChip(ss) {
    if (!ss) return '';
    var stal = getStale();
    if (ss.live === 0) return '<span class="ct-csync ct-csync-never" title="No row of this client has ever synced — every number is the imported sheet snapshot">NO SYNC</span>';
    var out = '';
    if (ss.mixed) out += '<span class="ct-csync ct-csync-mixed" title="' + ss.sheet + ' of ' + ss.total + ' rows are still sheet-import — they are NOT covered by the sync and never refresh">' + ss.sheet + ' SHEET</span>';
    if (ss.state === 'warn' || ss.state === 'red') out += '<span class="ct-csync ct-csync-' + ss.state + '" title="Newest sync for this client is ' + (stal ? stal.agoLabel(ss.newest) : 'old') + ' (amber > 6h, red > 24h)">' + (stal ? stal.agoLabel(ss.newest) : 'stale') + '</span>';
    return out;
  }

  // ============================ filtering / sorting ============================
  // Composes: status view (live-first) + archived + client + health + manager + search
  // (manager + search ported from Register/the top bar, Phase 2).
  function filtered(rows) {
    return rows.filter(function (r) {
      var sv = CS.statusView;
      if (sv === 'archived') { if (!r._archived) return false; }
      else if (r._archived) return false;                     // archived hidden except its own chip
      if (sv === 'live') { if (LIVE_STATUSES.indexOf(r.status) < 0) return false; }
      else if (sv !== 'all' && sv !== 'archived') { if (r.status !== sv) return false; }
      if (CS.client !== 'all' && r.client !== CS.client) return false;
      if (CS.health !== 'all' && r._d.health !== CS.health) return false;
      if (CS.mgr !== 'all' && r.managedBy !== CS.mgr) return false;
      if (CS.q) {
        var hay = ((r.name || '') + ' ' + (r.client || '') + ' ' + (r.channel || '') + ' ' + (r.objective || '') + ' ' +
          (r.managedBy || '') + ' ' + (r.keyKpi || '') + ' ' + (r.jobNumber || '') + ' ' + (r.notes || '')).toLowerCase();
        if (hay.indexOf(CS.q) < 0) return false;
      }
      return true;
    });
  }
  function distinctClients() { var s = []; buildRows().forEach(function (r) { if (r.client && s.indexOf(r.client) < 0) s.push(r.client); }); return s.sort(); }
  function sortRows(rows) {
    var col = COLS.find(function (c) { return c.id === CS.sortKey; });
    if (!col) return rows;
    var dir = CS.sortDir;
    return rows.slice().sort(function (a, b) {
      var A = col.get(a), B = col.get(b);
      var an = A == null || A === '' || (typeof A === 'number' && isNaN(A));
      var bn = B == null || B === '' || (typeof B === 'number' && isNaN(B));
      if (an && bn) return 0;
      if (an) return 1;         // nulls ALWAYS last, both directions
      if (bn) return -1;
      if (typeof A === 'string' || typeof B === 'string') { A = ('' + A).toLowerCase(); B = ('' + B).toLowerCase(); return A < B ? -dir : A > B ? dir : 0; }
      return (A - B) * dir;
    });
  }

  // ============================ render ============================
  function healthCounts(rows) { var c = { winner: 0, watch: 0, steady: 0 }; rows.forEach(function (r) { if (c[r._d.health] != null) c[r._d.health]++; }); return c; }
  // Portfolio-health counts over the LIVE set ONLY (Active+Paused). Ended / Not Active /
  // Draft never colour the health summary — otherwise a wall of long-finished campaigns
  // dominates the tally (the "53 watch over 39 live rows" bug). Draft has null health anyway.
  var HEALTH_STATUSES = ['Active', 'Paused'];
  function healthCountsLive(rows) { return healthCounts(rows.filter(function (r) { return HEALTH_STATUSES.indexOf(r.status) >= 0; })); }

  // Summary cards (the boss view). Live count uses the client+health scope (status-agnostic
  // so "live vs total" is meaningful); budget/spend/health sum the DISPLAYED rows; coverage
  // is global config. Nulls are excluded from sums — never NaN.
  function summaryCardsHtml(rows, working) {
    var scoped = working.filter(function (r) {
      if (CS.client !== 'all' && r.client !== CS.client) return false;
      if (CS.health !== 'all' && r._d.health !== CS.health) return false;
      return true;
    });
    var liveN = scoped.filter(function (r) { return LIVE_STATUSES.indexOf(r.status) >= 0; }).length;
    var totalN = scoped.length;
    var bVals = rows.map(function (r) { return r.totalBudget; }).filter(function (v) { return v != null && v !== ''; });
    var bSum = bVals.reduce(function (a, b) { return a + Number(b); }, 0);
    var bMissing = rows.length - bVals.length;
    var mSum = rows.map(function (r) { return r.mediaSpend; }).filter(function (v) { return v != null && v !== ''; }).reduce(function (a, b) { return a + Number(b); }, 0);
    var liveRows = rows.filter(isLive).length, sheetRows = rows.length - liveRows;
    var hc = healthCountsLive(working);   // health summary counts Active+Paused only
    var card = function (eyebrow, big, sub) { return '<div class="ct-card"><div class="ct-card-e">' + eyebrow + '</div><div class="ct-card-b">' + big + '</div><div class="ct-card-s">' + sub + '</div></div>'; };
    var budgetHalfMissing = rows.length && bMissing > rows.length * 0.5;
    // 4 cards (BQ coverage removed — internal build metric, not useful to buyers)
    return '<div class="ct-cards">' +
      card('Live campaigns', liveN, 'of ' + totalN + ' total') +
      card('Total budget', budgetHalfMissing ? DASH : money(bSum), budgetHalfMissing ? (bMissing + ' of ' + rows.length + ' missing') : (bMissing ? bMissing + ' missing budget' : 'across ' + rows.length + ' shown')) +
      card('Total spend (media)', money(mSum), liveRows + ' live · ' + sheetRows + ' sheet') +
      card('Health', '<span class="ct-hc-winner">' + hc.winner + '</span> · <span class="ct-hc-watch">' + hc.watch + '</span> · <span class="ct-hc-steady">' + hc.steady + '</span>', 'winner · watch · steady') +
      '</div>';
  }

  function render(opts) {
    opts = opts || {};
    injectCss();
    var mount = document.getElementById('view-central');
    if (!mount) return;
    if (CS.campaigns == null || opts.reload) {
      if (CS.campaigns == null) mount.innerHTML = '<div class="ct-empty">Loading Central…</div>';
      loadData().then(function () { paint(mount); });
      return;
    }
    paint(mount);
  }

  // Central's SOURCE OF TRUTH is the DB: campaigns (values) + rows (per-field provenance).
  // The sheet parse was a ONE-TIME import, not a pipeline. Offline (file://) → seed fixture.
  function loadData() {
    return Promise.all([
      fetch('/api/central/campaigns').then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch('/api/central/rows').then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch('/api/central/sync/status').then(function (r) { return r.json(); }).catch(function () { return null; })
    ]).then(function (res) {
      CS.campaigns = (res[0] && Array.isArray(res[0].campaigns)) ? res[0].campaigns : [];
      CS.overrides = (res[1] && res[1].overrides) || {};
      CS.syncStatus = res[2] || null;
    });
  }

  function paint(mount) {
    var all = buildRows();
    var working = all.filter(function (r) { return !r._archived; });   // archived excluded from the working set
    var rows = filtered(all);
    var counts = healthCountsLive(working);   // chips reflect the live (Active+Paused) set only
    // stale guard derives from REAL per-row lastSyncedAt (most recent across rows);
    // thresholds come from the ONE config location (staleness.js): warn > 6h, red > 24h.
    var lastTs = null;
    all.forEach(function (r) { if (r.lastSyncedAt) { var t = Date.parse(r.lastSyncedAt); if (!isNaN(t) && (lastTs == null || t > lastTs)) lastTs = t; } });
    CS.lastSynced = lastTs;
    var stal = getStale();
    var staleLevel = stal ? stal.classify(lastTs) : (lastTs == null ? 'never' : 'fresh');
    var stale = staleLevel !== 'fresh';
    // per-client sync rollup (never / mixed / stale) for the group rows + row markers —
    // the §9 containment produced sheet-import rows inside an otherwise-synced client
    // and it was invisible; this map is what makes that state render.
    CS._clientSync = {};
    if (stal) {
      var scByClient = {};
      working.forEach(function (r) { if (r.client) (scByClient[r.client] = scByClient[r.client] || []).push(r); });
      Object.keys(scByClient).forEach(function (c) { CS._clientSync[c] = stal.clientSyncState(scByClient[c]); });
    }

    var clients = [];
    working.forEach(function (r) { if (r.client && clients.indexOf(r.client) < 0) clients.push(r.client); });
    clients.sort();
    var mgrs = [];
    working.forEach(function (r) { if (r.managedBy && mgrs.indexOf(r.managedBy) < 0) mgrs.push(r.managedBy); });
    mgrs.sort();

    // live-first counts
    var liveN = working.filter(function (r) { return LIVE_STATUSES.indexOf(r.status) >= 0; }).length;
    var totalN = working.length;
    var archivedN = all.length - working.length;
    var sCount = function (s) { return working.filter(function (r) { return r.status === s; }).length; };

    var html = '<div class="ct-wrap' + (stale ? ' ct-stale-on' : '') + (staleLevel === 'red' || staleLevel === 'never' ? ' ct-stale-red' : '') + '">';
    // toolbar — header reads "N live · M total"
    html += '<div class="ct-toolbar"><div class="ct-title"><h2>Central</h2>' +
      '<span class="ct-titsub"><b>' + liveN + '</b> live · ' + totalN + ' total</span></div>' +
      '<div class="ct-tools">' + lastSyncedHtml(staleLevel) +
      '<button class="ct-btn ct-btn-primary" id="ct-add"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>Add campaign</button>' +
      '<button class="ct-btn" id="ct-map" title="Map a client\'s BQ campaigns to Central (validation sitting)"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3-6-3z"/><path d="M9 3v15M15 6v15"/></svg>Map client</button>' +
      '<button class="ct-btn" id="ct-sync"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg><span>Sync now</span></button>' +
      '<button class="ct-btn" id="ct-export"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>Export CSV</button>' +
      '</div></div>';
    // summary cards (the boss view) — reactive to the current filters
    html += summaryCardsHtml(rows, working);
    // legend
    html += '<div class="ct-legend"><span class="ct-lg"><i class="ct-dot ct-oh-api"></i>synced (API)</span><span class="ct-lg"><i class="ct-dot ct-oh-config"></i>config</span><span class="ct-lg"><i class="ct-dot ct-oh-derived"></i>derived (locked)</span><span class="ct-lg-r">last synced: ' + (CS.lastSynced ? new Date(CS.lastSynced).toLocaleString('en-GB') : 'never') + '</span></div>';
    // summary health chips (portfolio, working set)
    html += '<div class="ct-summary">' +
      chip('winner', counts.winner + ' winner' + (counts.winner === 1 ? '' : 's'), 'winner') +
      chip('watch', counts.watch + ' watch', 'watch') +
      chip('steady', counts.steady + ' steady', 'steady') +
      '</div>';
    // status-view chips (LIVE-FIRST) with counts + client filter
    var svChips = [['live', 'Live', liveN], ['Active', 'Active', sCount('Active')], ['Paused', 'Paused', sCount('Paused')],
      ['Not Active', 'Not Active', sCount('Not Active')], ['Ended', 'Ended', sCount('Ended')], ['all', 'All', totalN], ['archived', 'Archived', archivedN]];
    html += '<div class="ct-filters">';
    html += '<div class="ct-chipset ct-statusview" id="ct-fstatus">' + svChips.map(function (c) { return '<button class="ct-chip' + (CS.statusView === c[0] ? ' on' : '') + '" data-v="' + esc(c[0]) + '">' + esc(c[1]) + ' <span class="ct-chipn">' + c[2] + '</span></button>'; }).join('') + '</div>';
    html += '<label class="ct-fld"><span>Client</span><select id="ct-fclient" class="ct-select"><option value="all"' + (CS.client === 'all' ? ' selected' : '') + '>All clients</option>' +
      clients.map(function (c) { return '<option value="' + esc(c) + '"' + (CS.client === c ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select></label>';
    // Manager filter + campaign search (ported from Register / the old top bar)
    html += '<label class="ct-fld"><span>Manager</span><select id="ct-fmgr" class="ct-select"><option value="all"' + (CS.mgr === 'all' ? ' selected' : '') + '>All mgrs</option>' +
      mgrs.map(function (m) { return '<option value="' + esc(m) + '"' + (CS.mgr === m ? ' selected' : '') + '>' + esc(m) + '</option>'; }).join('') + '</select></label>';
    html += '<span class="ct-search"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg><input id="ct-q" type="search" placeholder="Search campaigns" autocomplete="off" value="' + esc(CS.qRaw || '') + '"></span>';
    html += '</div>';
    // column-group bar + grouping toggle (ported from Register, Phase 2)
    html += '<div class="ct-colbar"><span class="ct-fld"><span>Columns</span></span>' +
      '<button class="ct-colchip locked" disabled title="Campaign, channel, manager, status and dates are always shown">Core</button>' +
      COL_GROUPS.map(function (g) { return '<button class="ct-colchip" data-colg="' + g[0] + '" aria-pressed="' + !!CS.colGroups[g[0]] + '">' + g[1] + '</button>'; }).join('') +
      '<div class="ct-chipset" id="ct-group" role="group" aria-label="Grouping" style="margin-left:10px">' +
      '<button class="ct-chip' + (CS.group === 'advertiser' ? ' on' : '') + '" data-v="advertiser" title="Agency sections with one collapsible summary row per client">Group: advertiser</button>' +
      '<button class="ct-chip' + (CS.group === 'flat' ? ' on' : '') + '" data-v="flat" title="One flat list of campaign rows, sortable across all clients">Flat</button></div></div>';
    // table — grouped is now the explicit Group toggle (was: implicit "no sort key");
    // sorting inside advertiser mode ranks rows WITHIN each client (Register behavior).
    var grouped = CS.group === 'advertiser';
    var cols = activeCols();
    var sortCol = COLS.find(function (c) { return c.id === CS.sortKey; });
    html += '<div class="card ct-tablecard"><div class="ct-scroll"><table class="ct-table"><thead><tr>' +
      cols.map(function (c) {
        var active = c.id === CS.sortKey;
        return '<th class="ct-oh-' + c.type + (c.num ? ' r' : '') + (c.sticky ? ' ct-sticky' : '') + '" data-k="' + c.id + '" data-active="' + active + '"' + (c.hint ? ' title="' + esc(c.hint) + '"' : '') + '>' + esc(c.label) + '<span class="ct-arr">' + (active ? (CS.sortDir > 0 ? '▲' : '▼') : '↕') + '</span></th>';
      }).join('') + '</tr></thead><tbody>' + bodyHtml(rows, grouped) + '</tbody></table></div>' +
      '<div class="ct-foot">' + rows.length + ' campaign' + (rows.length === 1 ? '' : 's') +
      (grouped ? ' · grouped by agency & client' : ' · flat') +
      (sortCol ? ' · sorted by ' + sortCol.label + (grouped ? ' (within each client)' : '') : '') + '</div></div>';
    // dropzone container (plan reader mounts here)
    html += '<div id="ct-dropzone-host"></div>';
    html += '</div>';

    mount.innerHTML = html;
    CS._rows = all;   // exposed for the plan panel's conflict detection
    wire(mount);
    mountDropzone();
    // typing in the search box repaints the whole tab — give the input its focus back
    if (CS._qFocus) {
      CS._qFocus = false;
      var qEl = mount.querySelector('#ct-q');
      if (qEl) { qEl.focus(); var L = qEl.value.length; try { qEl.setSelectionRange(L, L); } catch (e) { /* non-text input state */ } }
    }
  }

  // ---- client-accordion helpers ----
  function compactNum(n) { n = Number(n) || 0; var a = Math.abs(n); if (a >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (a >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return String(Math.round(n)); }
  // sum an additive column across a client's rows; null when NO row has a value (so a client
  // with no budgets shows "—", not "$0"). Non-additive columns (margin/CPM/pacing/dates) are
  // per-row and never summed — the summary shows "—" for them.
  function sumField(rows, field) { var any = false, s = 0; rows.forEach(function (r) { var v = r[field]; if (v != null && v !== '') { any = true; s += Number(v) || 0; } }); return any ? s : null; }
  function clientKey(ag, cl) { return String(ag == null ? '' : ag) + '::' + String(cl == null ? '' : cl); }
  var SUM_COLS = { mediaSpend: 1, clientSpend: 1 };   // additive API columns that aggregate
  // effective budget per row = budgetGross (client budget) else totalBudget — matches calc.js
  function effBudgetOf(r) { var g = r.budgetGross; if (g != null && g !== '') return Number(g); return (r.totalBudget != null && r.totalBudget !== '') ? Number(r.totalBudget) : null; }
  function sumEffBudget(rows) { var any = false, s = 0; rows.forEach(function (r) { var b = effBudgetOf(r); if (b != null) { any = true; s += b; } }); return any ? s : null; }

  // Collapsible per-client summary row: chevron + name + count (+ total impressions), and
  // aggregated totals in the additive columns; "—" everywhere aggregation is meaningless.
  // Phase 2 (ported from Register's advertiser roll-up): the pacing columns show the
  // client-level % spent (Σ client spend / Σ effective budget) and an aggregate pace dot.
  function clientSummaryRow(ag, cl, clientRows) {
    var key = clientKey(ag, cl), open = !!CS.openClients[key];
    var impTot = sumField(clientRows, 'impressions');
    var spTot = sumField(clientRows, 'clientSpend'), ebTot = sumEffBudget(clientRows);
    var deliv = (spTot != null && ebTot != null && ebTot !== 0) ? spTot / ebTot : null;
    var els = clientRows.map(function (r) { return r._d.pctFlightElapsed; }).filter(function (v) { return v != null; });
    var avgEl = els.length ? els.reduce(function (a, b) { return a + b; }, 0) / els.length : null;
    var calc = getCalc();
    var pace = calc ? calc.paceBucket(deliv, avgEl) : 'none';
    var tds = activeCols().map(function (c) {
      var cls = (c.num ? 'r ' : '') + (c.sticky ? 'ct-sticky ' : '');
      var inner;
      if (c.id === 'campaign') {
        inner = '<button class="ct-cgroup" data-clientkey="' + esc(key) + '" aria-expanded="' + open + '" title="Show / hide this client\'s campaigns">' +
          '<span class="ct-chev' + (open ? ' open' : '') + '" aria-hidden="true">&#9654;</span>' +
          '<span class="ct-cgname">' + esc(cl || '—') + '</span>' +
          '<span class="ct-cgn">' + clientRows.length + ' campaign' + (clientRows.length === 1 ? '' : 's') + (impTot != null ? ' · ' + compactNum(impTot) + ' imp' : '') + '</span></button>' +
          clientSyncChip(CS._clientSync && CS._clientSync[cl]);
      } else if (c.id === 'channel') {
        inner = channelCluster(clientRows);         // all unique channels for this client
      } else if (c.id === 'totalBudget') {
        var eb = sumEffBudget(clientRows);           // Σ effective budget (budgetGross||totalBudget)
        inner = eb == null ? DASH : '<b class="ct-sumval">' + money(eb) + '</b>';
      } else if (c.id === 'pctBudgetSpent') {
        inner = deliv == null ? DASH : '<b class="ct-sumval">' + pct1(deliv) + '</b>';
      } else if (c.id === 'pacingStatus') {
        inner = '<span class="ct-pdot ct-pd-' + pace + '" title="Client aggregate pace: ' + esc(pace) + '"></span>';
      } else if (c.id === 'impressions') {
        inner = impTot == null ? DASH : '<b class="ct-sumval">' + compactNum(impTot) + '</b>';
      } else if (SUM_COLS[c.id]) {
        var s = sumField(clientRows, c.id);
        inner = s == null ? DASH : '<b class="ct-sumval">' + money(s) + '</b>';
      } else { inner = DASH; }
      return '<td class="' + cls.trim() + '">' + inner + '</td>';
    }).join('');
    return '<tr class="ct-sumrow" data-clientkey="' + esc(key) + '">' + tds + '</tr>';
  }

  function bodyHtml(rows, grouped) {
    var ncol = activeCols().length;
    if (!rows.length) return '<tr><td colspan="' + ncol + '"><div class="ct-empty">No campaigns match these filters.</div></td></tr>';
    // flat (the Register "Flat" toggle): one global list, sorted when a sort key is set
    if (!grouped) return sortRows(rows).map(function (r) { return rowHtml(r, false); }).join('');
    // grouped: agency sections (present agencies, preferred order, CASE-INSENSITIVE so
    // the real DATA's UPPERCASE agencies and the seed's Title-Case both group correctly)
    var pref = ['100% digital', 'transmission'];
    var present = [];
    rows.forEach(function (r) { if (present.indexOf(r.section) < 0) present.push(r.section); });
    present.sort(function (a, b) { var ia = pref.indexOf(String(a || '').toLowerCase()); var ib = pref.indexOf(String(b || '').toLowerCase()); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib); });
    var html = '';
    present.forEach(function (ag) {
      var inAg = rows.filter(function (r) { return r.section === ag; });
      if (!inAg.length) return;
      var activeN = inAg.filter(function (r) { return (r.status || '').toLowerCase() === 'active'; }).length;
      html += '<tr class="ct-section"><td colspan="' + ncol + '">' + esc(String(ag || '—').toUpperCase()) + ' <span class="ct-secn">' + activeN + ' active · ' + inAg.length + ' total</span></td></tr>';
      var byClient = {}; var clientOrder = [];
      inAg.forEach(function (r) { if (!byClient[r.client]) { byClient[r.client] = []; clientOrder.push(r.client); } byClient[r.client].push(r); });
      // collapsed BY DEFAULT: one summary row per client; the individual campaign-channel
      // rows are emitted as hidden children, revealed when the client is expanded.
      // A sort key ranks rows WITHIN each client (Register's grouped-sort behavior).
      clientOrder.forEach(function (cl) {
        var key = clientKey(ag, cl);
        html += clientSummaryRow(ag, cl, byClient[cl]);
        sortRows(byClient[cl]).forEach(function (r) { html += rowHtml(r, true, key); });
      });
    });
    return html;
  }

  function rowHtml(r, grouped, childKey) {
    var hlRow = CS.highlightMissing === r._id;
    var childCls = '', childAttr = '';
    if (childKey != null) { childCls = ' ct-childrow' + (CS.openClients[childKey] ? '' : ' ct-hidden'); childAttr = ' data-cchild="' + esc(childKey) + '"'; }
    var cols = activeCols();
    var tr = '<tr class="ct-row' + (r._archived ? ' ct-archived' : '') + (inMixedClient(r) ? ' ct-row-sheetmixed' : '') + childCls + '"' + childAttr + ' data-id="' + esc(r._id) + '">' + cols.map(function (c) {
      // empty manual [CONFIG] field → needs input. Guarded to CONFIG columns so a same-named
      // derived column (adServingCost) can never render as editable. The campaign column's
      // needs-state keys on 'name' (its cell renders the fill-empty affordance itself).
      var needs = c.type === 'config' && (c.id === 'campaign' ? needsInput('name', r.name) : needsInput(c.id, r[c.id]));
      var cls = (c.num ? 'r ' : '') + (c.sticky ? 'ct-sticky ' : '') + (c.type === 'api' ? 'ct-api-col ' : '');
      if (needs) cls += 'ct-needs ';                 // faint amber to-do tint (never on derived/api)
      if (hlRow && needs) cls += 'ct-needs-focus ';
      var inner;
      if (c.editable && EDIT_COLS.indexOf(c.editable) >= 0) inner = editSelect(r, c.editable);          // dropdown (empty shows —, tinted)
      else if (needs && c.id !== 'campaign') inner = editableEmptyCell(r, c.id);                         // inline-fill an empty manual cell
      else inner = (c.id === 'campaign') ? c.cell(r, grouped) : c.cell(r);
      return '<td class="' + cls.trim() + '"' + (needs ? ' title="needs input"' : '') + '>' + inner + '</td>';
    }).join('') + '</tr>';
    // persisted detail expansion (ported from Register): re-emit the open detail row on repaint
    if (CS.openDetails[r._id]) tr += detailRowHtml(r, cols.length, childKey);
    return tr;
  }

  // Full-detail row (ported from Register): every column across ALL groups — including the
  // ones toggled off — as a read-only field grid, grouped under the column-group headings.
  function detailVal(r, c) {
    switch (c.id) {
      case 'campaign': return esc(r.name || '—');
      case 'channel': return channelChip(r.channel);
      case 'managedBy': return r.managedBy ? esc(r.managedBy) : DASH;
      case 'status': return '<span class="ct-pill ct-st-' + statusCls(r.status) + '">' + esc(r.status || '—') + '</span>';
      case 'keyKpi': return (r.keyKpi == null || r.keyKpi === '') ? DASH : esc(String(r.keyKpi));
      case 'kpiPerformance': return (r.kpiPerformance == null || r.kpiPerformance === '' || isKpiError(r.kpiPerformance)) ? DASH : esc(String(r.kpiPerformance));
      case 'spendMult': { var sm = parseFloat(r.spendMult); return isNaN(sm) ? DASH : esc(sm.toFixed(2)); }
      default: return c.cell(r);   // remaining cells are already non-interactive renderings
    }
  }
  function detailRowHtml(r, ncol, childKey) {
    var childCls = '', childAttr = '';
    if (childKey != null) { childCls = ' ct-childrow' + (CS.openClients[childKey] ? '' : ' ct-hidden'); childAttr = ' data-cchild="' + esc(childKey) + '"'; }
    var inner = '<div class="ct-detail-inner">';
    var order = ['core', 'pacing', 'budget', 'margin', 'perf', 'links'];
    order.forEach(function (g) {
      var gc = COLS.filter(function (c) { return c.g === g && c.id !== 'campaign'; });
      if (!gc.length) return;
      inner += '<div class="ct-dgrp">' + esc(GROUP_LABEL[g]) + '</div>';
      if (g === 'core') inner += '<div class="ct-field"><div class="k">Objective</div><div class="v">' + (r.objective ? esc(r.objective) : DASH) + '</div></div>';
      gc.forEach(function (c) { inner += '<div class="ct-field"><div class="k">' + esc(c.label) + '</div><div class="v">' + detailVal(r, c) + '</div></div>'; });
    });
    inner += '</div>';
    return '<tr class="ct-detail' + childCls + '"' + childAttr + ' data-detailrow="' + esc(r._id) + '"><td colspan="' + ncol + '">' + inner + '</td></tr>';
  }
  // empty manual text/number cell → contenteditable (reuses brain-historical's pattern);
  // blur/Enter saves via the whitelisted field route. Placeholder shown while empty.
  function editableEmptyCell(r, field, ph) {
    return '<span class="ct-ce" contenteditable="true" role="textbox" data-id="' + esc(r._id) + '" data-field="' + field + '" data-ph="' + esc(ph || 'add') + '"></span>';
  }
  // always-editable free-text CONFIG cell (KPI columns): shows the value + edits inline.
  // A sheet error (#DIV/0! etc.) renders blank (→ the "—"/placeholder), still editable.
  function isKpiError(v) { return v != null && /#(div\/0|n\/a|ref|value|name|num)/i.test(String(v)); }
  function editableTextCell(r, field, cls) {
    var v = r[field]; var disp = (v == null || v === '' || isKpiError(v)) ? '' : esc(String(v));
    return '<span class="ct-ce ' + (cls || '') + '" contenteditable="true" role="textbox" data-id="' + esc(r._id) + '" data-field="' + field + '" data-allow-empty="1" data-ph="add">' + disp + '</span>';
  }
  // always-editable numeric CONFIG cell (Spend Mult): plain 2-dp decimal ("1.00" / "3.07"),
  // edits inline like the KPI text cells; clearing it saves null (multiplier unknown → the
  // unbilled-basis badge returns). Full precision is kept in the DB; 2 dp is display only.
  function spendMultCell(r) {
    var n = (r.spendMult == null || r.spendMult === '') ? null : Number(r.spendMult);
    var disp = (n == null || isNaN(n)) ? '' : n.toFixed(2);
    return '<span class="ct-ce" contenteditable="true" role="textbox" data-id="' + esc(r._id) + '" data-field="spendMult" data-allow-empty="1" data-ph="add">' + disp + '</span>';
  }
  // KPI parse + verdict (DISPLAY ONLY — never stored). "10 ROAS"→{10,ROAS}, "$150 CPL"→{150,CPL},
  // "0.51% CTR"→{0.51,CTR}. Same unit → green if perf meets/beats target, red if >30% off, else neutral.
  var KPI_LOWER_BETTER = ['CPL', 'CPA', 'CPR', 'CPM', 'CPC', 'CPV', 'CPI', 'CPE', 'COST'];
  function parseKpi(s) {
    if (s == null) return null; s = String(s).trim();
    if (s === '' || isKpiError(s)) return null;
    var nm = s.replace(/,/g, '').match(/-?\d+(?:\.\d+)?/); if (!nm) return null;
    var unit = s.replace(/[-\d.,%$\s]/g, '').toUpperCase();
    return { num: parseFloat(nm[0]), unit: unit };
  }
  function kpiVerdict(target, actual) {
    var t = parseKpi(target), a = parseKpi(actual);
    if (!t || !a || !t.unit || t.unit !== a.unit || t.num === 0) return null;   // diff/unparseable units → neutral
    if (KPI_LOWER_BETTER.indexOf(t.unit) >= 0) { if (a.num <= t.num) return 'beat'; return a.num > t.num * 1.3 ? 'miss' : 'neutral'; }
    if (a.num >= t.num) return 'beat'; return a.num < t.num * 0.7 ? 'miss' : 'neutral';
  }

  function editSelect(r, field) {
    var cur = r[field] || '';
    var opts, extra = '';
    if (field === 'managedBy') { opts = MANAGERS.slice(); if (cur && opts.indexOf(cur) < 0) opts.unshift(cur); }
    else if (field === 'status') { opts = STATUSES.slice(); }
    else { opts = Object.keys(CHANNEL_COLORS).concat(['Other']); if (cur && opts.indexOf(cur) < 0) opts.unshift(cur); }
    var chip = field === 'channel' ? channelChip(cur) : '';
    var sel = '<select class="ct-editsel" data-id="' + esc(r._id) + '" data-field="' + field + '"><option value=""' + (cur ? '' : ' selected') + '>—</option>' +
      opts.map(function (o) { return '<option value="' + esc(o) + '"' + (o === cur ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('');
    if (field === 'managedBy') sel += '<option value="__other__">Other…</option>';
    sel += '</select>';
    return (field === 'channel' ? chip : '') + sel + srcIcon(r, field);
  }

  function chip(kind, label, healthVal) { return '<button class="ct-hchip ct-hc-' + kind + (CS.health === healthVal ? ' on' : '') + '" data-health="' + healthVal + '">' + esc(label) + '</button>'; }

  // level: 'fresh' | 'warn' (> 6h, amber) | 'red' (> 24h) | 'never' — thresholds in staleness.js.
  function lastSyncedHtml(level) {
    var stal = getStale();
    var t = CS.lastSynced ? new Date(CS.lastSynced).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : 'never synced';
    var ago = (stal && CS.lastSynced) ? ' (' + stal.agoLabel(CS.lastSynced) + ')' : '';
    var autoMin = CS.syncStatus && CS.syncStatus.autosyncMin;
    var auto = autoMin > 0 ? ' <span class="ct-auto" title="Auto-sync runs on the server every ' + autoMin + ' min">· auto every ' + autoMin + 'm</span>' : '';
    var cls = level === 'fresh' ? '' : (level === 'warn' ? ' stale' : ' stale red');
    var title = level === 'fresh' ? 'API columns are fresh'
      : level === 'never' ? 'No BigQuery sync has ever run — every number is the imported sheet snapshot'
        : 'API columns are stale (amber > 6h, red > 24h — thresholds in src/central/staleness.js)';
    return '<span class="ct-lastsync' + cls + '" title="' + esc(title) + '">' + (level === 'fresh' ? '' : '⚠ ') + 'last synced: ' + t + ago + '</span>' + auto;
  }

  // ============================ wiring ============================
  function wire(mount) {
    // sort headers, tri-state: default direction -> flipped -> off (natural order).
    // Register's first-click default ported: numeric columns start DESC, text ASC.
    mount.querySelectorAll('th[data-k]').forEach(function (th) {
      th.addEventListener('click', function () {
        var k = th.dataset.k;
        var col = COLS.find(function (c) { return c.id === k; });
        var first = (col && col.num) ? -1 : 1;
        if (CS.sortKey !== k) { CS.sortKey = k; CS.sortDir = first; }
        else if (CS.sortDir === first) CS.sortDir = -first;
        else { CS.sortKey = null; CS.sortDir = 1; }
        paint(mount);
      });
    });
    // column-group chips + grouping toggle (ported from Register)
    mount.querySelectorAll('.ct-colchip[data-colg]').forEach(function (b) {
      b.addEventListener('click', function () { var g = b.dataset.colg; CS.colGroups[g] = !CS.colGroups[g]; paint(mount); });
    });
    mount.querySelectorAll('#ct-group .ct-chip').forEach(function (b) {
      b.addEventListener('click', function () { CS.group = b.dataset.v; paint(mount); });
    });
    // manager filter + search (ported from Register / the old top bar)
    var fm = mount.querySelector('#ct-fmgr'); if (fm) fm.addEventListener('change', function () { CS.mgr = fm.value; paint(mount); });
    var qEl = mount.querySelector('#ct-q'); if (qEl) qEl.addEventListener('input', function () {
      CS.qRaw = qEl.value; CS.q = qEl.value.toLowerCase().trim(); CS._qFocus = true; paint(mount);
    });
    // per-campaign detail expansion (ported from Register): toggle IN PLACE (no repaint,
    // so scroll position and other open rows are preserved); bodyHtml re-emits open
    // detail rows on the next full repaint from CS.openDetails.
    mount.querySelectorAll('[data-detail]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = btn.dataset.detail, tr = btn.closest('tr'), open = !CS.openDetails[id];
        if (open) {
          CS.openDetails[id] = true;
          var row = (CS._rows || []).find(function (r) { return r._id === id; });
          if (row && tr) tr.insertAdjacentHTML('afterend', detailRowHtml(row, activeCols().length, tr.getAttribute('data-cchild')));
        } else {
          delete CS.openDetails[id];
          var nx = tr && tr.nextElementSibling;
          if (nx && nx.classList.contains('ct-detail')) nx.remove();
        }
        btn.classList.toggle('open', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });
    // client accordion: expand/collapse a client group (toggle child-row visibility +
    // chevron in place — no re-paint, so scroll + other open groups are preserved).
    mount.querySelectorAll('.ct-cgroup').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var key = btn.dataset.clientkey, open = !CS.openClients[key];
        if (open) CS.openClients[key] = true; else delete CS.openClients[key];
        mount.querySelectorAll('tr[data-cchild="' + cssEsc(key) + '"]').forEach(function (tr) { tr.classList.toggle('ct-hidden', !open); });
        var chev = btn.querySelector('.ct-chev'); if (chev) chev.classList.toggle('open', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });
    // client filter
    var fc = mount.querySelector('#ct-fclient'); if (fc) fc.addEventListener('change', function () { CS.client = fc.value; paint(mount); });
    // status-view chips (live-first)
    mount.querySelectorAll('#ct-fstatus .ct-chip').forEach(function (b) { b.addEventListener('click', function () { CS.statusView = b.dataset.v; paint(mount); }); });
    // health chips (click active clears)
    mount.querySelectorAll('.ct-hchip').forEach(function (b) { b.addEventListener('click', function () { var h = b.dataset.health; CS.health = (CS.health === h) ? 'all' : h; paint(mount); }); });
    // Add campaign
    var add = mount.querySelector('#ct-add'); if (add) add.addEventListener('click', function () {
      if (window.CentralPlan && window.CentralPlan.openAdd) window.CentralPlan.openAdd({ clients: distinctClients(), onCreated: function () { render({ reload: true }); } });
      else toastErr('Add panel unavailable (plan-panel.js not loaded).');
    });
    // Map client (reconcile) — suggestions only, human approves
    var mapb = mount.querySelector('#ct-map'); if (mapb) mapb.addEventListener('click', function () {
      var cov = CS.syncStatus && CS.syncStatus.coverage;
      var clientList = cov && cov.clients && cov.clients.length ? cov.clients.map(function (c) { return c.client; }) : distinctClients();
      if (window.CentralPlan && window.CentralPlan.openReconcile) window.CentralPlan.openReconcile({ clients: clientList, coverage: cov, onApproved: function () { render({ reload: true }); } });
      else toastErr('Reconcile panel unavailable (plan-panel.js not loaded).');
    });
    // archive (soft delete)
    mount.querySelectorAll('[data-archive]').forEach(function (b) { b.addEventListener('click', function (e) { e.stopPropagation(); onArchive(b.dataset.archive, mount); }); });
    // editable dropdowns (managedBy / channel / status)
    mount.querySelectorAll('.ct-editsel').forEach(function (sel) { sel.addEventListener('change', function () { onEdit(sel, mount); }); });
    // inline-editable empty manual cells (text / number CONFIG) — blur/Enter saves
    mount.querySelectorAll('.ct-ce').forEach(function (ce) {
      ce.addEventListener('blur', function () { onInlineEdit(ce, mount); });
      ce.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); ce.blur(); } else if (e.key === 'Escape') { ce.textContent = ''; ce.blur(); } });
    });
    // missing-config badge -> scroll to the row + focus its FIRST needs-input cell
    mount.querySelectorAll('[data-missing]').forEach(function (b) { b.addEventListener('click', function (e) { e.stopPropagation(); var id = b.dataset.missing; CS.highlightMissing = (CS.highlightMissing === id) ? null : id; paint(mount); var tr = mount.querySelector('tr[data-id="' + cssEsc(id) + '"]'); if (tr) { tr.scrollIntoView({ block: 'center', behavior: 'smooth' }); var f = tr.querySelector('td.ct-needs .ct-ce, td.ct-needs .ct-editsel'); if (f && f.focus) f.focus(); } }); });
    // sync (stub) + export
    var sync = mount.querySelector('#ct-sync'); if (sync) sync.addEventListener('click', function () { doSync(sync); });
    var exp = mount.querySelector('#ct-export'); if (exp) exp.addEventListener('click', function () { exportCsv(); });
  }
  function cssEsc(s) { return String(s).replace(/["\\]/g, '\\$&'); }

  function onEdit(sel, mount) {
    var id = sel.dataset.id, field = sel.dataset.field, value = sel.value;
    if (field === 'managedBy' && value === '__other__') {
      var typed = window.prompt('Managed by (name):', '');
      if (typed == null || typed.trim() === '') { paint(mount); return; }
      value = typed.trim();
    }
    postField(id, field, value === '' ? null : value, mount);
  }
  function onInlineEdit(ce, mount) {
    var raw = (ce.textContent || '').trim();
    var allowEmpty = ce.dataset.allowEmpty === '1';     // KPI free-text cells may be cleared to null
    if (raw === '' && !allowEmpty) return;              // "fill empty" cells: nothing typed → stays tinted
    postField(ce.dataset.id, ce.dataset.field, raw === '' ? null : coerceEdit(ce.dataset.field, raw), mount);
  }
  // light client-side coercion so inline-typed values land in the same shape as the seed
  // (percent → 0-1, "$20k" → 20000); text + dates pass through untouched.
  function coerceEdit(field, raw) {
    if (field === 'platformMargin') { var p = parseFloat(String(raw).replace(/[%\s]/g, '')); if (isNaN(p)) return raw; return (String(raw).indexOf('%') >= 0 || p > 1) ? p / 100 : p; }
    if (['forecastCpm', 'totalBudget', 'budgetGross', 'adServingCost', 'spendMult'].indexOf(field) >= 0) {
      var s = String(raw).replace(/[$,\s]/g, ''), mult = 1; if (/[kK]$/.test(s)) { mult = 1000; s = s.slice(0, -1); }
      var n = parseFloat(s); return isNaN(n) ? raw : n * mult;
    }
    return raw;
  }
  function postField(id, field, value, mount) {
    fetch('/api/central/row/' + encodeURIComponent(id) + '/field', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ field: field, value: value })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) { toastErr((x.d && x.d.error) || 'Could not save'); paint(mount); return; }
        // splice the server-returned campaign back in (the row IS the value truth) + provenance
        if (x.d && x.d.campaign && Array.isArray(CS.campaigns)) { for (var i = 0; i < CS.campaigns.length; i++) if (CS.campaigns[i].id === id) { CS.campaigns[i] = x.d.campaign; break; } }
        CS.overrides[id] = CS.overrides[id] || {};
        CS.overrides[id][field] = { value: value, source: 'manual' };
        toastOk('Saved ' + field);
        paint(mount);       // tint clears (now populated) + missing-config badge recalculates
      }).catch(function () { toastErr('Save failed (is the server running?)'); paint(mount); });
  }
  function onArchive(id, mount) {
    if (!window.confirm('Archive this campaign? It stays as history under the Archived filter — it is never deleted.')) return;
    fetch('/api/central/campaigns/' + encodeURIComponent(id) + '/archive', { method: 'POST' })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) { if (!x.ok) { toastErr((x.d && x.d.error) || 'Archive failed'); return; } toastOk('Archived'); render({ reload: true }); })
      .catch(function () { toastErr('Archive failed (server offline?)'); });
  }

  function doSync(btn) {
    btn.classList.add('ct-spin'); btn.disabled = true;
    fetch('/api/central/sync', { method: 'POST' }).then(function (r) { return r.json().then(function (d) { return { s: r.status, d: d }; }); })
      .then(function (x) {
        var d = x.d || {};
        if (x.s === 409) { toastErr('A sync is already running — try again in a moment.'); return; }
        if (x.s === 502) { toastErr('Sync failed: ' + (d.error || 'BQ fetcher error')); return; }
        if (x.s >= 300) { toastErr(d.error || 'Sync failed'); return; }
        if (Array.isArray(d.rows)) CS.campaigns = d.rows;   // refreshed rows → no second fetch
        var msg = (d.updated || 0) + ' row' + (d.updated === 1 ? '' : 's') + ' updated';
        if (d.unmatched && d.unmatched.length) msg += ' · ' + d.unmatched.length + ' unmatched';
        var notMapped = (d.skippedClients || []).length;
        if (notMapped) msg += ' · ' + notMapped + ' client' + (notMapped === 1 ? '' : 's') + ' not yet mapped';
        toastOk(msg);
        if (d.errors && d.errors.length) { console.warn('[Central sync] warnings:', d.errors); toastErr(d.errors.length + ' sync warning(s) — see console'); }
      })
      .catch(function () { toastErr('Sync failed — is the server running?'); })
      .then(function () { btn.classList.remove('ct-spin'); btn.disabled = false; render(); });
  }

  // CSV = the union of Central's old export and Register's (Phase 2): all raw CONFIG/API
  // fields + every derived column INCLUDING the Register/Pulse projection + risk math
  // (needs-per-day, projected landing, effective margin, profit at risk). Respects the
  // current filters (status view / client / health / manager / search) like both did.
  function exportCsv() {
    var rows = CS.sortKey ? sortRows(filtered(buildRows())) : filtered(buildRows());
    var cols = [
      ['Agency', function (r) { return r.section; }], ['Client', function (r) { return r.client; }], ['Campaign', function (r) { return r.name; }],
      ['Objective', function (r) { return r.objective; }], ['Channel', function (r) { return r.channel; }], ['Managed By', function (r) { return r.managedBy; }],
      ['Status', function (r) { return r.status; }], ['Job #', function (r) { return r.jobNumber; }],
      ['Start', function (r) { return r.startDate; }], ['End', function (r) { return r.endDate; }],
      ['Media Spend', function (r) { return r.mediaSpend; }], ['Client Spend', function (r) { return r.clientSpend; }],
      ['Total Budget', function (r) { return r.totalBudget; }], ['Budget Gross', function (r) { return r.budgetGross; }],
      ['Impressions', function (r) { return r.impressions; }],
      ['Forecast CPM', function (r) { return r.forecastCpm; }],
      ['Platform Margin', function (r) { return r.platformMargin; }], ['Spend Mult', function (r) { return r.spendMult; }], ['Ad-Serving Rate', function (r) { return r.adServing; }],
      ['Key KPI', function (r) { return r.keyKpi; }], ['KPI Performance', function (r) { return r.kpiPerformance; }],
      ['Campaign Link', function (r) { return r.campaignLink; }], ['Next Report', function (r) { return r.nextReportingDue; }],
      ['Notes', function (r) { return r.notes; }],
      // derived
      ['Campaign Margin', function (r) { return r._d.campaignMargin; }], ['Margin Band', function (r) { return r._d.marginBand; }],
      ['Ad-Serving Cost', function (r) { return r._d.adServingCost; }],
      ['CPM Performance', function (r) { return r._d.cpmPerformance; }], ['Budget Remaining', function (r) { return r._d.budgetRemaining; }],
      ['% Spent', function (r) { return r._d.pctBudgetSpent; }], ['% Elapsed', function (r) { return r._d.pctFlightElapsed; }],
      ['Pacing', function (r) { return r._d.pacingStatus; }], ['Health', function (r) { return r._d.health; }],
      // ported from the Register/Pulse export: projection + money-at-risk math
      ['Needs Per Day', function (r) { return r._d.reqDaily != null ? Math.round(r._d.reqDaily) : ''; }],
      ['Projected Total', function (r) { return r._d.projTotal != null ? Math.round(r._d.projTotal) : ''; }],
      ['Projected Vs Budget', function (r) { return r._d.projVar != null ? Math.round(r._d.projVar) : ''; }],
      ['Effective Margin', function (r) { return r._d.effectiveMargin; }],
      ['Margin At Risk', function (r) { return r._d.profitAtRisk != null ? Math.round(r._d.profitAtRisk) : ''; }],
      ['Margin Estimated', function (r) { return r._d.effectiveMarginSource === 'assumed' ? 'yes' : ''; }]
    ];
    var esc2 = function (v) { return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"'; };
    var NL = String.fromCharCode(10);
    var head = cols.map(function (c) { return esc2(c[0]); }).join(',');
    var body = rows.map(function (r) { return cols.map(function (c) { return esc2(c[1](r)); }).join(','); }).join(NL);
    var blob = new Blob([head + NL + body], { type: 'text/csv;charset=utf-8;' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    var asOf = (CS.lastSynced ? new Date(CS.lastSynced) : new Date()).toISOString().slice(0, 10);
    a.download = 'central_' + (CS.client === 'all' ? 'all' : CS.client.replace(/[^a-z0-9]+/gi, '-').toLowerCase()) + '_' + asOf + '.csv';
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 1500);
    toastOk('Exported ' + rows.length + ' rows');
  }

  function mountDropzone() {
    var host = document.getElementById('ct-dropzone-host'); if (!host) return;
    if (window.CentralPlan && window.CentralPlan.mount) {
      window.CentralPlan.mount(host, { getRows: function () { return CS._rows || []; }, onCommitted: function () { render({ reload: true }); } });
    } else {
      host.innerHTML = '<div class="ct-dz ct-dz-off">Media-plan reader unavailable (plan-panel.js not loaded).</div>';
    }
  }

  // ---- toast (reuse the app's if present) ----
  function toastOk(m) { if (window.toast) window.toast.success(m); }
  function toastErr(m) { if (window.toast) window.toast.error(m); }
  function toastInfo(m) { if (window.toast) (window.toast.info || window.toast.success)(m); }

  // ============================ CSS (injected once) ============================
  function injectCss() {
    if (document.getElementById('ct-css')) return;
    var s = document.createElement('style'); s.id = 'ct-css';
    s.textContent = [
      '.ct-wrap{padding-top:16px}',
      '.ct-toolbar{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;flex-wrap:wrap;padding:6px 0 10px}',
      '.ct-title h2{font-family:"Space Grotesk";font-size:22px;font-weight:600;margin:0;letter-spacing:-.5px}.ct-titsub{font-size:12px;color:var(--ink-2)}',
      '.ct-tools{display:flex;align-items:center;gap:9px;flex-wrap:wrap}',
      '.ct-btn{appearance:none;font-family:inherit;cursor:pointer;font-size:12px;font-weight:600;color:var(--ink-2);background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 12px;display:inline-flex;align-items:center;gap:6px;box-shadow:var(--shadow);transition:all .15s}',
      '.ct-btn:hover{color:var(--brand-ink);border-color:var(--brand)}.ct-btn:disabled{opacity:.55;cursor:default}',
      '.ct-btn.ct-spin svg{animation:ct-rot .8s linear infinite}@keyframes ct-rot{to{transform:rotate(360deg)}}',
      '.ct-lastsync{font-size:11px;color:var(--ink-3);font-weight:600}.ct-lastsync.stale{color:var(--warn)}.ct-lastsync.stale.red{color:var(--bad)}',
      '.ct-auto{font-size:10.5px;color:var(--ink-3);font-weight:600}',
      // summary cards (boss view)
      '.ct-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:11px;padding:4px 0 12px}',
      '.ct-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);padding:13px 15px}',
      '.ct-card-e{font-size:9.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3)}',
      '.ct-card-b{font-family:"Space Grotesk";font-size:23px;font-weight:600;letter-spacing:-.5px;margin:5px 0 2px;line-height:1}',
      '.ct-card-s{font-size:10.5px;color:var(--ink-2)}',
      '.ct-legend{display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--ink-2);padding:2px 2px 10px}',
      '.ct-lg{display:inline-flex;align-items:center;gap:6px}.ct-lg-r{margin-left:auto;color:var(--ink-3)}',
      '.ct-dot{width:9px;height:9px;border-radius:50%;display:inline-block;background:currentColor}',
      '.ct-oh-api{color:#4C8DFF}.ct-oh-config{color:var(--ink-3)}.ct-oh-derived{color:var(--brand)}',
      'th.ct-oh-api{color:#4C8DFF}th.ct-oh-config{color:var(--ink-3)}th.ct-oh-derived{color:var(--brand)}',
      '.ct-summary{display:flex;gap:9px;flex-wrap:wrap;padding:2px 0 12px}',
      '.ct-hchip{appearance:none;cursor:pointer;font-family:inherit;font-size:12px;font-weight:600;padding:6px 13px;border-radius:20px;border:1px solid var(--line);background:var(--panel);color:var(--ink-2);transition:all .15s}',
      '.ct-hchip.on{box-shadow:0 0 0 2px currentColor inset}',
      '.ct-hc-winner{color:var(--ok)}.ct-hc-watch{color:var(--bad)}.ct-hc-steady{color:var(--ink-3)}',
      '.ct-filters{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:0 0 12px}',
      '.ct-fld{display:inline-flex;align-items:center;gap:7px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3)}',
      '.ct-select,.ct-editsel{font-family:inherit;font-size:12px;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 9px;outline:none;text-transform:none;font-weight:500;letter-spacing:0}',
      '.ct-select:focus,.ct-editsel:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}',
      '.ct-editsel{padding:3px 6px;font-size:11px}',
      '.ct-chipset{display:inline-flex;gap:6px;flex-wrap:wrap}',
      '.ct-chip{appearance:none;cursor:pointer;font-family:inherit;font-size:11.5px;font-weight:500;padding:6px 12px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink-2);transition:all .15s}',
      '.ct-chip:hover{color:var(--ink)}.ct-chip.on{background:var(--pill-bg);color:var(--pill-fg);border-color:var(--pill-bg)}',
      '.ct-tablecard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow)}',
      '.ct-scroll{overflow:auto;max-height:68vh}',
      '.ct-table{border-collapse:separate;border-spacing:0;width:100%;font-size:12px;white-space:nowrap}',
      '.ct-table thead th{position:sticky;top:0;z-index:20;background:var(--panel);text-align:left;font-weight:700;font-size:10px;letter-spacing:.04em;text-transform:uppercase;padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none}',
      '.ct-table th.r{text-align:right}.ct-table th .ct-arr{opacity:.35;font-size:9px;margin-left:3px}',
      '.ct-table th[data-active="true"] .ct-arr{opacity:1}',
      '.ct-table th.ct-sticky,.ct-table td.ct-sticky{position:sticky;left:0;z-index:10;background:var(--panel);box-shadow:1px 0 0 var(--line-2);min-width:230px;white-space:normal}',
      '.ct-table thead th.ct-sticky{z-index:30}',
      '.ct-table tbody td{padding:9px 12px;border-bottom:1px solid var(--line-2);vertical-align:middle}',
      '.ct-table td.r{text-align:right;font-variant-numeric:tabular-nums}',
      '.ct-row:hover td{background:var(--panel-2)}.ct-row:hover td.ct-sticky{background:var(--panel-2)}',
      '.ct-cl{font-size:10px;color:var(--ink-3);font-weight:600;text-transform:uppercase;letter-spacing:.03em}',
      '.ct-nm{font-weight:600;color:var(--ink)}.ct-sub{font-size:10.5px;color:var(--ink-3)}',
      '.ct-badges{display:flex;gap:5px;flex-wrap:wrap;margin-top:4px}',
      '.ct-badge{font-size:9px;font-weight:700;letter-spacing:.03em;padding:2px 6px;border-radius:6px;border:0;font-family:inherit}',
      '.ct-badge-warn{background:var(--warn-soft);color:var(--warn)}.ct-badge-bad{background:var(--bad-soft);color:var(--bad)}',
      '.ct-badge-miss{background:var(--line-2);color:var(--ink-2);cursor:pointer}.ct-badge-miss:hover{color:var(--ink)}',
      // needs-input to-do cue: faint amber tint (derived from the warning token), quiet
      '.ct-needs{background:color-mix(in srgb, var(--warn) 10%, transparent)}',
      '.ct-needs:hover{background:color-mix(in srgb, var(--warn) 20%, transparent)}',
      '.ct-needs-focus{box-shadow:inset 0 0 0 2px var(--warn)}',
      '.ct-ce{display:inline-block;min-width:46px;min-height:15px;padding:1px 4px;border-radius:4px;cursor:text;outline:none;color:var(--ink)}',
      '.ct-ce:empty::before{content:attr(data-ph);color:var(--ink-3);opacity:.6}',
      '.ct-ce:focus{box-shadow:inset 0 0 0 2px var(--brand);background:var(--panel)}',
      '.ct-kpi-beat{color:var(--ok);font-weight:600}.ct-kpi-miss{color:var(--bad);font-weight:600}',
      '.ct-basis-info{display:inline-block;margin-left:5px;width:13px;height:13px;line-height:13px;text-align:center;border-radius:50%;background:var(--tx-soft);color:var(--tx-ink);font-size:9px;font-weight:800;cursor:help;vertical-align:middle}',
      '.ct-chan{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;padding:2px 9px 2px 3px;border-radius:20px}',
      '.ct-chancluster{display:inline-flex;gap:3px;flex-wrap:wrap}',
      '.ct-chan-code{display:inline-grid;place-items:center;min-width:17px;height:17px;padding:0 3px;border-radius:20px;color:#fff;font-size:8.5px;font-weight:800;letter-spacing:.02em}',
      '.ct-mgr{display:inline-block;font-weight:600}',
      '.ct-pill{display:inline-flex;align-items:center;font-size:10px;font-weight:700;padding:2px 9px;border-radius:20px}',
      '.ct-st-active{background:var(--ok-soft);color:var(--ok)}.ct-st-paused{background:var(--warn-soft);color:var(--warn)}.ct-st-ended{background:var(--line-2);color:var(--ink-3)}.ct-st-notactive{background:var(--line-2);color:var(--ink-2)}.ct-st-draft{background:var(--tx-soft);color:var(--tx-ink)}',
      '.ct-chipn{font-size:9px;font-weight:800;opacity:.7;margin-left:2px}.ct-chip.on .ct-chipn{opacity:.9}',
      '.ct-btn-primary{background:var(--pill-bg);color:var(--pill-fg);border-color:var(--pill-bg)}.ct-btn-primary:hover{background:var(--brand-strong);color:var(--pill-fg);border-color:var(--brand-strong)}',
      '.ct-arch{appearance:none;border:0;background:transparent;color:var(--ink-3);font-family:inherit;font-size:9.5px;font-weight:600;cursor:pointer;margin-left:8px;opacity:0;transition:opacity .12s;text-decoration:underline}',
      '.ct-row:hover .ct-arch{opacity:.75}.ct-arch:hover{color:var(--bad);opacity:1}',
      '.ct-arch-tag{font-size:9px;font-weight:700;color:var(--ink-3);background:var(--line-2);padding:1px 6px;border-radius:5px;margin-left:8px;text-transform:uppercase;letter-spacing:.03em}',
      '.ct-archived td{opacity:.55}.ct-archived:hover td{opacity:.8}',
      '.ct-pace-on{background:var(--ok-soft);color:var(--ok)}.ct-pace-over{background:var(--bad-soft);color:var(--bad)}.ct-pace-under{background:var(--warn-soft);color:var(--warn)}.ct-pace-early{background:var(--line-2);color:#7E93AD}',
      '.ct-h-winner{background:var(--ok-soft);color:var(--ok)}.ct-h-watch{background:var(--bad-soft);color:var(--bad)}.ct-h-steady{background:var(--line-2);color:var(--ink-3)}',
      '.ct-margin{display:inline-block;padding:2px 8px;border-radius:6px;font-weight:600}',
      '.ct-band-above{background:var(--ok-soft);color:var(--ok)}.ct-band-near{background:var(--warn-soft);color:var(--warn)}.ct-band-below{background:var(--bad-soft);color:var(--bad)}',
      '.ct-msrc{font-size:8px;font-weight:800;padding:1px 4px;border-radius:4px;margin-left:6px;vertical-align:middle}',
      '.ct-msrc-live{background:var(--ok-soft);color:var(--ok)}.ct-msrc-sheet{background:var(--line-2);color:var(--ink-3)}',
      // mixed state (§9): a sheet row inside an otherwise-synced client — amber, not grey
      '.ct-msrc-mixed{background:var(--warn-soft);color:var(--warn)}',
      '.ct-row-sheetmixed td:first-child{box-shadow:inset 3px 0 0 var(--warn)}',
      '.ct-csync{font-size:8.5px;font-weight:800;letter-spacing:.04em;padding:1.5px 6px;border-radius:4px;margin-left:8px;vertical-align:middle}',
      '.ct-csync-never{background:var(--line-2);color:var(--ink-3);border:1px dashed var(--ink-3)}',
      '.ct-csync-mixed,.ct-csync-warn{background:var(--warn-soft);color:var(--warn)}',
      '.ct-csync-red{background:var(--bad-soft);color:var(--bad)}',
      '.ct-srcdoc{display:inline-flex;color:var(--brand);margin-left:5px;vertical-align:middle;cursor:help}',
      '.ct-section td{background:var(--grp);border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-family:"Space Grotesk";font-weight:700;font-size:11px;letter-spacing:.08em;color:var(--ink-2);padding:8px 12px}',
      '.ct-section .ct-secn{font-weight:500;letter-spacing:0;color:var(--ink-3);font-family:"Inter";text-transform:none;margin-left:8px}',
      '.ct-clientrow td{background:var(--panel-2);padding:6px 12px}.ct-clientname{font-weight:600;font-size:12px}.ct-clientn{font-size:10.5px;color:var(--ink-3);margin-left:6px}',
      // client accordion: collapsible summary row + hidden child rows
      '.ct-sumrow td{background:var(--panel-2);border-bottom:1px solid var(--line);padding:9px 12px}',
      '.ct-sumrow:hover td{background:var(--grp)}.ct-sumrow:hover td.ct-sticky{background:var(--grp)}',
      '.ct-sumrow td.ct-sticky{background:var(--panel-2)}',
      '.ct-cgroup{appearance:none;border:0;background:transparent;cursor:pointer;font-family:inherit;font-size:12.5px;color:var(--ink);display:inline-flex;align-items:center;gap:8px;padding:0;text-align:left;width:100%}',
      '.ct-chev{display:inline-block;font-size:9px;color:var(--ink-3);transition:transform .15s;flex:0 0 auto}',
      '.ct-chev.open{transform:rotate(90deg)}',
      '.ct-cgname{font-weight:700;color:var(--ink)}',
      '.ct-cgn{font-size:10.5px;font-weight:500;color:var(--ink-3)}',
      '.ct-sumval{font-weight:700;color:var(--ink)}',
      '.ct-childrow.ct-hidden{display:none}',
      '.ct-childrow td.ct-sticky{padding-left:28px;border-left:2px solid var(--line-2)}',
      '.ct-stale-on .ct-api-col{opacity:.5;filter:grayscale(.4)}',
      '.ct-foot{padding:10px 16px;color:var(--ink-3);font-size:11px;border-top:1px solid var(--line-2)}',
      '.ct-muted{color:var(--ink-3)}.ct-empty{padding:36px 18px;text-align:center;color:var(--ink-3);font-size:13px}',
      // ---- Phase 2 (merged Register) ----
      // column-group bar
      '.ct-colbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:0 0 12px}',
      '.ct-colchip{appearance:none;font-family:inherit;cursor:pointer;font-size:11.5px;font-weight:500;padding:5px 11px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink-2);transition:all .15s}',
      '.ct-colchip:hover{color:var(--ink);border-color:var(--ink-3)}',
      '.ct-colchip[aria-pressed="true"]{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-ink);font-weight:600}',
      '.ct-colchip.locked{opacity:.55;cursor:default;background:var(--line-2);border-color:var(--line-2);color:var(--ink-3)}',
      // search
      '.ct-search{position:relative;display:inline-flex;align-items:center}',
      '.ct-search svg{position:absolute;left:9px;color:var(--ink-3);pointer-events:none}',
      '.ct-search input{font-family:inherit;font-size:12px;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:7px 10px 7px 28px;width:190px;outline:none;transition:border .15s,box-shadow .15s}',
      '.ct-search input:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}',
      // pacing mini-bar (pill + bar)
      '.ct-pacecell{display:inline-flex;align-items:center;gap:8px}',
      '.ct-pacebar{width:56px;height:5px;border-radius:3px;background:var(--line-2);position:relative;overflow:hidden;flex:0 0 auto;display:inline-block}',
      '.ct-pacebar i{position:absolute;left:0;top:0;bottom:0;border-radius:3px}',
      '.ct-pacebar u{position:absolute;top:-2px;bottom:-2px;width:1.5px;background:var(--ink);opacity:.55}',
      '.ct-pb-on{background:var(--ok)}.ct-pb-over{background:var(--bad)}.ct-pb-under{background:var(--warn)}.ct-pb-early{background:#7E93AD}',
      // client-summary aggregate pace dot
      '.ct-pdot{display:inline-block;width:9px;height:9px;border-radius:50%}',
      '.ct-pd-ok{background:var(--ok)}.ct-pd-over{background:var(--bad)}.ct-pd-under{background:var(--warn)}.ct-pd-early{background:#7E93AD}.ct-pd-none{background:var(--ink-3)}',
      // detail expansion caret + detail row
      '.ct-exp{appearance:none;border:0;background:transparent;cursor:pointer;color:var(--ink-3);font-size:9px;padding:0 4px 0 0;transition:transform .15s;display:inline-block}',
      '.ct-exp:hover{color:var(--brand)}.ct-exp.open{transform:rotate(90deg)}',
      '.ct-detail td{padding:0;background:var(--panel-2);border-bottom:1px solid var(--line)}',
      '.ct-detail-inner{padding:14px 20px 16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px 24px}',
      '.ct-dgrp{grid-column:1/-1;font-family:"Space Grotesk";font-size:10.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--brand);margin-top:4px;border-bottom:1px solid var(--line-2);padding-bottom:4px}',
      '.ct-dgrp:first-child{margin-top:0}',
      '.ct-field .k{font-size:9.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3);margin-bottom:2px}',
      '.ct-field .v{font-size:12px;color:var(--ink);font-weight:500}',
      // external campaign link button
      '.ct-link{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:7px;border:1px solid var(--line);color:var(--ink-2);text-decoration:none}',
      '.ct-link:hover{border-color:var(--brand);color:var(--brand)}',
      // dropzone
      '.ct-dz{margin-top:14px;border:1.5px dashed var(--line);border-radius:var(--r);padding:22px;text-align:center;color:var(--ink-2);background:var(--panel);transition:all .15s;cursor:pointer}',
      '.ct-dz:hover,.ct-dz.drag{border-color:var(--brand);background:var(--brand-soft);color:var(--brand-ink)}',
      '.ct-dz-off{opacity:.6;cursor:default}',
      '.ct-dz h4{font-family:"Space Grotesk";margin:0 0 4px;font-size:14px;color:var(--ink)}.ct-dz p{margin:0;font-size:12px}',
      '.ct-dzicon{color:var(--brand);margin-bottom:6px}',
      '.ct-progress{height:6px;border-radius:4px;background:var(--line-2);overflow:hidden;margin-top:12px}.ct-progress i{display:block;height:100%;background:var(--brand);width:0;transition:width .2s}',
      '.ct-dzerr{margin-top:10px;font-size:12px;color:var(--bad)}.ct-dzerr a{color:var(--brand-ink);cursor:pointer;text-decoration:underline}'
    ].join('\n');
    document.head.appendChild(s);
  }

  return { render: render, _mapGridRowToCentral: mapGridRowToCentral, _centralRowId: centralRowId, _buildRows: buildRows, _filtered: filtered, _needsInput: needsInput, _getSourceRows: getSourceRows, _coerceEdit: coerceEdit, _statusCls: statusCls, _parseKpi: parseKpi, _kpiVerdict: kpiVerdict, _chanTheme: chanTheme, _isKpiError: isKpiError, _healthCounts: healthCounts, _healthCountsLive: healthCountsLive, _bodyHtml: bodyHtml, _clientKey: clientKey, _sumField: sumField, _activeCols: activeCols, _detailRowHtml: detailRowHtml, COLS: COLS, NEEDS_INPUT: NEEDS_INPUT, LIVE_STATUSES: LIVE_STATUSES, HEALTH_STATUSES: HEALTH_STATUSES, CS: CS };
});
