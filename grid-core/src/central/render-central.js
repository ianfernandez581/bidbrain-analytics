/*
 * src/central/render-central.js — the Central tab view.
 * ----------------------------------------------------------------------------
 * Renders the live-campaigns table from config/central-seed.js, with every
 * DERIVED cell computed fresh by src/central/calc.js (never stored, never
 * editable). Clones the Register table pattern (declarative COLS) from
 * the-grid.html. Owns its own filter/sort state (does not touch the pulse `F`).
 *
 * CONFIG edits (Managed By / Channel / Status dropdowns) and plan-reader commits
 * persist to central_rows via the server; here we layer those overrides over the
 * seed at render time and tag each field's source. Sync is stubbed (server 501).
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
  var STALE_MS = 4 * 60 * 60 * 1000;
  var MANAGERS = ['Mel', 'Zhen', 'Sophia'];
  // Real sheet vocabulary + app-only Draft. "Not Active" is a real status (never coerced).
  var STATUSES = ['Active', 'Paused', 'Not Active', 'Ended', 'Draft'];
  var AGENCY_LABEL = { '100% Digital': '100% DIGITAL', 'Transmission': 'TRANSMISSION' };

  // ---- per-channel colour (real brand hues; 2-letter code is the backup cue) ----
  var CHANNEL_COLORS = {
    'Trade Desk': { bg: '#E6F4FB', fg: '#0A5A80', code: 'TD' },
    'LinkedIn': { bg: '#DCEAFB', fg: '#004182', code: 'LI' },
    'Google Ads': { bg: '#E8F0FE', fg: '#174EA6', code: 'GA' },
    'Meta': { bg: '#E0EBFC', fg: '#05308A', code: 'FB' },
    'DV360': { bg: '#E1F5EE', fg: '#0F6E56', code: 'DV' }
  };
  var CHANNEL_OTHER = { bg: '#F1EFE8', fg: '#444441', code: '—' };
  function chanTheme(ch) { return CHANNEL_COLORS[ch] || CHANNEL_OTHER; }
  function channelChip(ch) {
    if (!ch) return DASH;
    var t = chanTheme(ch);
    return '<span class="ct-chan" style="background:' + t.bg + ';color:' + t.fg + '">' +
      '<span class="ct-chan-code" style="background:' + t.fg + '">' + esc(t.code) + '</span>' + esc(ch) + '</span>';
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
    sortKey: null, sortDir: 1,           // null = grouped; else flat global ranking
    campaigns: null, overrides: null, lastSynced: null, highlightMissing: null
  };
  var LIVE_STATUSES = ['Active', 'Paused', 'Draft'];   // "Live" = day-to-day working set

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
    'keyKpi', 'totalBudget', 'budgetGross', 'startDate', 'endDate', 'adServingCost', 'notes', 'spendMult'];
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
      r._d = calc ? calc.computeRow(r, new Date()) : {};
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
    {
      id: 'campaign', label: 'Campaign', type: 'config', sticky: 1, get: function (r) { return (r.name || '').toLowerCase(); },
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
        return client + '<div class="ct-nm">' + esc(r.name || '—') + act + '</div>' + (r.objective ? '<div class="ct-sub">' + esc(r.objective) + '</div>' : '') + (badges ? '<div class="ct-badges">' + badges + '</div>' : '');
      }
    },
    { id: 'channel', label: 'Channel', type: 'config', get: function (r) { return (r.channel || '').toLowerCase(); }, editable: 'channel', cell: function (r) { return channelChip(r.channel) + srcIcon(r, 'channel'); } },
    { id: 'managedBy', label: 'Managed By', type: 'config', get: function (r) { return (r.managedBy || '').toLowerCase(); }, editable: 'managedBy', cell: function (r) { return (r.managedBy ? '<span class="ct-mgr">' + esc(r.managedBy) + '</span>' : DASH) + srcIcon(r, 'managedBy'); } },
    { id: 'status', label: 'Status', type: 'config', get: function (r) { return (r.status || '').toLowerCase(); }, editable: 'status', cell: function (r) { return '<span class="ct-pill ct-st-' + statusCls(r.status) + '">' + esc(r.status || '—') + '</span>'; } },
    { id: 'mediaSpend', label: 'Media Spend', type: 'api', num: 1, get: function (r) { return r.mediaSpend; }, cell: function (r) { return '<span class="ct-api-cell">' + money(r.mediaSpend) + metricsTag(r) + '</span>'; } },
    { id: 'clientSpend', label: 'Client Spend', type: 'api', num: 1, get: function (r) { return r.clientSpend; }, cell: function (r) { return '<span class="ct-api-cell">' + money(r.clientSpend) + '</span>'; } },
    { id: 'platformMargin', label: 'Plat. Margin', type: 'config', num: 1, get: function (r) { return r.platformMargin; }, cell: function (r) { return (r.platformMargin == null ? DASH : Math.round(r.platformMargin * 100) + '%') + srcIcon(r, 'platformMargin'); } },
    {
      id: 'campaignMargin', label: 'Camp. Margin', type: 'derived', num: 1, get: function (r) { return r._d.campaignMargin; },
      cell: function (r) {
        var band = r._d.marginBand;
        var val = r._d.campaignMargin == null ? DASH : Math.round(r._d.campaignMargin * 100) + '%';
        return '<span class="ct-margin ' + (band ? 'ct-band-' + band : '') + '" title="' + esc(marginTip(r)) + '">' + val + '</span>';
      }
    },
    { id: 'cpmPerformance', label: 'CPM Perf', type: 'derived', num: 1, get: function (r) { return r._d.cpmPerformance; }, cell: function (r) { return r._d.cpmPerformance == null ? DASH : '$' + r._d.cpmPerformance.toFixed(2); } },
    { id: 'forecastCpm', label: 'Forecast CPM', type: 'config', num: 1, get: function (r) { return r.forecastCpm; }, cell: function (r) { return (r.forecastCpm == null ? DASH : '$' + Number(r.forecastCpm).toFixed(2)) + srcIcon(r, 'forecastCpm'); } },
    { id: 'pctBudgetSpent', label: '% Spent', type: 'derived', num: 1, get: function (r) { return r._d.pctBudgetSpent; }, cell: function (r) { return pct1(r._d.pctBudgetSpent); } },
    { id: 'pctFlightElapsed', label: '% Elapsed', type: 'derived', num: 1, get: function (r) { return r._d.pctFlightElapsed; }, cell: function (r) { return pct1(r._d.pctFlightElapsed); } },
    { id: 'pacingStatus', label: 'Pacing', type: 'derived', get: function (r) { return r._d.pacingStatus || ''; }, cell: function (r) { var p = r._d.pacingStatus; return p && p !== '-' ? '<span class="ct-pill ct-pace-' + p.toLowerCase() + '">' + p + '</span>' : DASH; } },
    { id: 'health', label: 'Health', type: 'derived', get: function (r) { return ({ watch: 0, steady: 1, winner: 2 })[r._d.health]; }, cell: function (r) { var h = r._d.health; return h ? '<span class="ct-pill ct-h-' + h + '">' + HEALTH_LABEL[h] + '</span>' : DASH; } },
    // ---- overflow columns (horizontal scroll reveals the fuller set) ----
    { id: 'jobNumber', label: 'Job #', type: 'config', get: function (r) { return (r.jobNumber || '').toLowerCase(); }, cell: function (r) { return (r.jobNumber ? esc(r.jobNumber) : DASH) + srcIcon(r, 'jobNumber'); } },
    { id: 'totalBudget', label: 'Total Budget', type: 'config', num: 1, get: function (r) { return r.totalBudget; }, cell: function (r) { return money(r.totalBudget) + srcIcon(r, 'totalBudget'); } },
    { id: 'budgetRemaining', label: 'Remaining', type: 'derived', num: 1, get: function (r) { return r._d.budgetRemaining; }, cell: function (r) { return money(r._d.budgetRemaining); } },
    { id: 'startDate', label: 'Start', type: 'config', get: function (r) { return r.startDate || ''; }, cell: function (r) { return dateDMY(r.startDate); } },
    { id: 'endDate', label: 'End', type: 'config', get: function (r) { return r.endDate || ''; }, cell: function (r) { return dateDMY(r.endDate); } },
    { id: 'keyKpi', label: 'Key KPI', type: 'config', get: function (r) { return (r.keyKpi || '').toLowerCase(); }, cell: function (r) { return (r.keyKpi ? esc(r.keyKpi) : DASH) + srcIcon(r, 'keyKpi'); } },
    { id: 'notes', label: 'Notes', type: 'config', get: function (r) { return (r.notes || '').toLowerCase(); }, cell: function (r) { return r.notes ? esc(r.notes) : DASH; } }
  ];
  var EDIT_COLS = ['channel', 'managedBy', 'status'];  // columns rendered as dropdowns
  function statusCls(s) { s = (s || '').toLowerCase(); if (s.indexOf('not active') >= 0) return 'notactive'; return s.indexOf('active') >= 0 ? 'active' : s.indexOf('paus') >= 0 ? 'paused' : s.indexOf('end') >= 0 ? 'ended' : 'draft'; }
  function isLive(r) { return r.metricsSource === 'bq' || r.metricsSource === 'BQ'; }
  function metricsTag(r) {
    var live = isLive(r);
    var t = live ? ('Live from BigQuery' + (r.lastSyncedAt ? ' · synced ' + new Date(r.lastSyncedAt).toLocaleString('en-GB') : '')) : 'From the one-time sheet import (not yet synced)';
    return '<span class="ct-msrc ct-msrc-' + (live ? 'live' : 'sheet') + '" title="' + esc(t) + '">' + (live ? 'LIVE' : 'SHEET') + '</span>';
  }

  // ============================ filtering / sorting ============================
  // Composes: status view (live-first) + archived + client + health.
  function filtered(rows) {
    return rows.filter(function (r) {
      var sv = CS.statusView;
      if (sv === 'archived') { if (!r._archived) return false; }
      else if (r._archived) return false;                     // archived hidden except its own chip
      if (sv === 'live') { if (LIVE_STATUSES.indexOf(r.status) < 0) return false; }
      else if (sv !== 'all' && sv !== 'archived') { if (r.status !== sv) return false; }
      if (CS.client !== 'all' && r.client !== CS.client) return false;
      if (CS.health !== 'all' && r._d.health !== CS.health) return false;
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
    var counts = healthCounts(working);
    // stale guard derives from REAL per-row lastSyncedAt (most recent across rows)
    var lastTs = null;
    all.forEach(function (r) { if (r.lastSyncedAt) { var t = Date.parse(r.lastSyncedAt); if (!isNaN(t) && (lastTs == null || t > lastTs)) lastTs = t; } });
    CS.lastSynced = lastTs;
    var stale = lastTs == null || (Date.now() - lastTs) > STALE_MS;

    var clients = [];
    working.forEach(function (r) { if (r.client && clients.indexOf(r.client) < 0) clients.push(r.client); });
    clients.sort();

    // live-first counts
    var liveN = working.filter(function (r) { return LIVE_STATUSES.indexOf(r.status) >= 0; }).length;
    var totalN = working.length;
    var archivedN = all.length - working.length;
    var sCount = function (s) { return working.filter(function (r) { return r.status === s; }).length; };

    var html = '<div class="ct-wrap' + (stale ? ' ct-stale-on' : '') + '">';
    // toolbar — header reads "N live · M total"
    html += '<div class="ct-toolbar"><div class="ct-title"><h2>Central</h2>' +
      '<span class="ct-titsub"><b>' + liveN + '</b> live · ' + totalN + ' total</span></div>' +
      '<div class="ct-tools">' + lastSyncedHtml(stale) +
      '<button class="ct-btn ct-btn-primary" id="ct-add"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>Add campaign</button>' +
      '<button class="ct-btn" id="ct-map" title="Map a client\'s BQ campaigns to Central (validation sitting)"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3-6-3z"/><path d="M9 3v15M15 6v15"/></svg>Map client</button>' +
      '<button class="ct-btn" id="ct-sync"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg><span>Sync now</span></button>' +
      '<button class="ct-btn" id="ct-export"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>Export CSV</button>' +
      '</div></div>';
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
    html += '</div>';
    // table
    var grouped = !CS.sortKey;
    html += '<div class="card ct-tablecard"><div class="ct-scroll"><table class="ct-table"><thead><tr>' +
      COLS.map(function (c) {
        var active = c.id === CS.sortKey;
        return '<th class="ct-oh-' + c.type + (c.num ? ' r' : '') + (c.sticky ? ' ct-sticky' : '') + '" data-k="' + c.id + '" data-active="' + active + '">' + esc(c.label) + '<span class="ct-arr">' + (active ? (CS.sortDir > 0 ? '▲' : '▼') : '↕') + '</span></th>';
      }).join('') + '</tr></thead><tbody>' + bodyHtml(rows, grouped) + '</tbody></table></div>' +
      '<div class="ct-foot">' + rows.length + ' campaign' + (rows.length === 1 ? '' : 's') + (grouped ? ' · grouped by agency & client' : ' · sorted by ' + (COLS.find(function (c) { return c.id === CS.sortKey; }) || {}).label) + '</div></div>';
    // dropzone container (plan reader mounts here)
    html += '<div id="ct-dropzone-host"></div>';
    html += '</div>';

    mount.innerHTML = html;
    CS._rows = all;   // exposed for the plan panel's conflict detection
    wire(mount);
    mountDropzone();
  }

  function bodyHtml(rows, grouped) {
    if (!rows.length) return '<tr><td colspan="' + COLS.length + '"><div class="ct-empty">No campaigns match these filters.</div></td></tr>';
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
      html += '<tr class="ct-section"><td colspan="' + COLS.length + '">' + esc(String(ag || '—').toUpperCase()) + ' <span class="ct-secn">' + activeN + ' active · ' + inAg.length + ' total</span></td></tr>';
      var byClient = {}; var clientOrder = [];
      inAg.forEach(function (r) { if (!byClient[r.client]) { byClient[r.client] = []; clientOrder.push(r.client); } byClient[r.client].push(r); });
      clientOrder.forEach(function (cl) {
        html += '<tr class="ct-clientrow"><td colspan="' + COLS.length + '"><span class="ct-clientname">' + esc(cl || '—') + '</span> <span class="ct-clientn">' + byClient[cl].length + '</span></td></tr>';
        byClient[cl].forEach(function (r) { html += rowHtml(r, true); });
      });
    });
    return html;
  }

  function rowHtml(r, grouped) {
    var hlRow = CS.highlightMissing === r._id;
    return '<tr class="ct-row' + (r._archived ? ' ct-archived' : '') + '" data-id="' + esc(r._id) + '">' + COLS.map(function (c) {
      var needs = needsInput(c.id, r[c.id]);        // empty manual [CONFIG] field → needs input
      var cls = (c.num ? 'r ' : '') + (c.sticky ? 'ct-sticky ' : '') + (c.type === 'api' ? 'ct-api-col ' : '');
      if (needs) cls += 'ct-needs ';                 // faint amber to-do tint (never on derived/api)
      if (hlRow && needs) cls += 'ct-needs-focus ';
      var inner;
      if (c.editable && EDIT_COLS.indexOf(c.editable) >= 0) inner = editSelect(r, c.editable);          // dropdown (empty shows —, tinted)
      else if (needs) inner = editableEmptyCell(r, c.id);                                                // inline-fill an empty manual cell
      else inner = (c.id === 'campaign') ? c.cell(r, grouped) : c.cell(r);
      return '<td class="' + cls.trim() + '"' + (needs ? ' title="needs input"' : '') + '>' + inner + '</td>';
    }).join('') + '</tr>';
  }
  // empty manual text/number cell → contenteditable (reuses brain-historical's pattern);
  // blur/Enter saves via the whitelisted field route. Placeholder shown while empty.
  function editableEmptyCell(r, field) {
    return '<span class="ct-ce" contenteditable="true" role="textbox" data-id="' + esc(r._id) + '" data-field="' + field + '" data-ph="add"></span>';
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

  function lastSyncedHtml(stale) {
    var t = CS.lastSynced ? new Date(CS.lastSynced).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : 'never synced';
    var autoMin = CS.syncStatus && CS.syncStatus.autosyncMin;
    var auto = autoMin > 0 ? ' <span class="ct-auto" title="Auto-sync runs on the server every ' + autoMin + ' min">· auto every ' + autoMin + 'm</span>' : '';
    return '<span class="ct-lastsync' + (stale ? ' stale' : '') + '" title="API columns are ' + (stale ? 'possibly stale' : 'fresh') + '">' + (stale ? '⚠ ' : '') + 'last synced: ' + t + (stale && CS.lastSynced ? ' (stale)' : '') + '</span>' + auto;
  }

  // ============================ wiring ============================
  function wire(mount) {
    // sort headers: asc -> desc -> off
    mount.querySelectorAll('th[data-k]').forEach(function (th) {
      th.addEventListener('click', function () {
        var k = th.dataset.k;
        if (CS.sortKey !== k) { CS.sortKey = k; CS.sortDir = 1; }
        else if (CS.sortDir === 1) CS.sortDir = -1;
        else { CS.sortKey = null; CS.sortDir = 1; }
        paint(mount);
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
      if (window.CentralPlan && window.CentralPlan.openReconcile) window.CentralPlan.openReconcile({ clients: distinctClients(), onApproved: function () { render({ reload: true }); } });
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
    if (raw === '') return;                              // nothing typed → stays empty/tinted
    postField(ce.dataset.id, ce.dataset.field, coerceEdit(ce.dataset.field, raw), mount);
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

  function exportCsv() {
    var rows = CS.sortKey ? sortRows(filtered(buildRows())) : filtered(buildRows());
    var cols = [
      ['Agency', function (r) { return r.agency; }], ['Client', function (r) { return r.client; }], ['Campaign', function (r) { return r.name; }],
      ['Objective', function (r) { return r.objective; }], ['Channel', function (r) { return r.channel; }], ['Managed By', function (r) { return r.managedBy; }],
      ['Status', function (r) { return r.status; }], ['Job #', function (r) { return r.jobNumber; }],
      ['Start', function (r) { return r.startDate; }], ['End', function (r) { return r.endDate; }],
      ['Media Spend', function (r) { return r.mediaSpend; }], ['Client Spend', function (r) { return r.clientSpend; }],
      ['Total Budget', function (r) { return r.totalBudget; }], ['Forecast CPM', function (r) { return r.forecastCpm; }],
      ['Platform Margin', function (r) { return r.platformMargin; }], ['Key KPI', function (r) { return r.keyKpi; }],
      // derived
      ['Campaign Margin', function (r) { return r._d.campaignMargin; }], ['Margin Band', function (r) { return r._d.marginBand; }],
      ['CPM Performance', function (r) { return r._d.cpmPerformance; }], ['Budget Remaining', function (r) { return r._d.budgetRemaining; }],
      ['% Spent', function (r) { return r._d.pctBudgetSpent; }], ['% Elapsed', function (r) { return r._d.pctFlightElapsed; }],
      ['Pacing', function (r) { return r._d.pacingStatus; }], ['Health', function (r) { return r._d.health; }]
    ];
    var esc2 = function (v) { return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"'; };
    var NL = String.fromCharCode(10);
    var head = cols.map(function (c) { return esc2(c[0]); }).join(',');
    var body = rows.map(function (r) { return cols.map(function (c) { return esc2(c[1](r)); }).join(','); }).join(NL);
    var blob = new Blob([head + NL + body], { type: 'text/csv;charset=utf-8;' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'central_' + (CS.client === 'all' ? 'all' : CS.client.replace(/[^a-z0-9]+/gi, '-').toLowerCase()) + '.csv';
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
      '.ct-lastsync{font-size:11px;color:var(--ink-3);font-weight:600}.ct-lastsync.stale{color:var(--warn)}',
      '.ct-auto{font-size:10.5px;color:var(--ink-3);font-weight:600}',
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
      '.ct-chan{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;padding:2px 9px 2px 3px;border-radius:20px}',
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
      '.ct-pace-on{background:var(--ok-soft);color:var(--ok)}.ct-pace-over{background:var(--bad-soft);color:var(--bad)}.ct-pace-under{background:var(--warn-soft);color:var(--warn)}',
      '.ct-h-winner{background:var(--ok-soft);color:var(--ok)}.ct-h-watch{background:var(--bad-soft);color:var(--bad)}.ct-h-steady{background:var(--line-2);color:var(--ink-3)}',
      '.ct-margin{display:inline-block;padding:2px 8px;border-radius:6px;font-weight:600}',
      '.ct-band-above{background:var(--ok-soft);color:var(--ok)}.ct-band-near{background:var(--warn-soft);color:var(--warn)}.ct-band-below{background:var(--bad-soft);color:var(--bad)}',
      '.ct-msrc{font-size:8px;font-weight:800;padding:1px 4px;border-radius:4px;margin-left:6px;vertical-align:middle}',
      '.ct-msrc-live{background:var(--ok-soft);color:var(--ok)}.ct-msrc-sheet{background:var(--line-2);color:var(--ink-3)}',
      '.ct-srcdoc{display:inline-flex;color:var(--brand);margin-left:5px;vertical-align:middle;cursor:help}',
      '.ct-section td{background:var(--grp);border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-family:"Space Grotesk";font-weight:700;font-size:11px;letter-spacing:.08em;color:var(--ink-2);padding:8px 12px}',
      '.ct-section .ct-secn{font-weight:500;letter-spacing:0;color:var(--ink-3);font-family:"Inter";text-transform:none;margin-left:8px}',
      '.ct-clientrow td{background:var(--panel-2);padding:6px 12px}.ct-clientname{font-weight:600;font-size:12px}.ct-clientn{font-size:10.5px;color:var(--ink-3);margin-left:6px}',
      '.ct-stale-on .ct-api-col{opacity:.5;filter:grayscale(.4)}',
      '.ct-foot{padding:10px 16px;color:var(--ink-3);font-size:11px;border-top:1px solid var(--line-2)}',
      '.ct-muted{color:var(--ink-3)}.ct-empty{padding:36px 18px;text-align:center;color:var(--ink-3);font-size:13px}',
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

  return { render: render, _mapGridRowToCentral: mapGridRowToCentral, _centralRowId: centralRowId, _buildRows: buildRows, _filtered: filtered, _needsInput: needsInput, _getSourceRows: getSourceRows, _coerceEdit: coerceEdit, _statusCls: statusCls, NEEDS_INPUT: NEEDS_INPUT, LIVE_STATUSES: LIVE_STATUSES, CS: CS };
});
