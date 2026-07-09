/*
 * src/brain/brain-landing.js  —  Brain cross-client landing page
 * ----------------------------------------------------------------------------
 * BrainLanding.render(mount, ctx) paints the whole landing view into `mount`.
 *
 * ctx (provided by the-grid.html) is the seam to the host app:
 *   data      : window.BrainData  (RECOMMENDATIONS + helpers)
 *   colors    : window.BrainColors
 *   toast     : window.toast
 *   theme     : 'dark' | 'light'
 *   filters   : { client, platform, type, min_conf, sort }
 *   setFilters(patch) : merge into hash-backed filter state + re-render + write URL
 *   open(recId)       : navigate to the drill-down (adds a history entry)
 *
 * UMD: browser -> window.BrainLanding.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.BrainLanding = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var _loaded = false; // gate the one-time skeleton pass

  // ---- small formatters -----------------------------------------------------
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function k(n) { return '$' + Math.round(n / 1000) + 'k'; }
  function prettyType(t) { return (t || '').replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); }); }
  var STATUS_LABEL = { review: 'Review', in_clickup: 'In ClickUp', measuring: 'Measuring', won: 'Won', rolled_back: 'Rolled back', dismissed: 'Dismissed' };
  function statusPill(s) { return '<span class="bt-pill bt-st-' + s + '">' + (STATUS_LABEL[s] || s) + '</span>'; }

  var ICON = {
    brain: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 0 7 4.5v.5a3 3 0 0 0-2 5.6V12a3 3 0 0 0 1 5.6V19a2.5 2.5 0 0 0 4.5 1.5V4.5A2.5 2.5 0 0 0 9.5 2Z"/><path d="M14.5 2A2.5 2.5 0 0 1 17 4.5v.5a3 3 0 0 1 2 5.6V12a3 3 0 0 1-1 5.6V19a2.5 2.5 0 0 1-4.5 1.5"/></svg>',
    scan: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/></svg>',
    log: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>'
  };

  // ---- KPI cards ------------------------------------------------------------
  function kpiCards(data) {
    var all = data.RECOMMENDATIONS;
    var review = all.filter(function (r) { return r.status === 'review'; });
    var reviewClients = {}; review.forEach(function (r) { reviewClients[r.client_id] = 1; });
    var pipeline = all.filter(function (r) { return r.status === 'review' || r.status === 'in_clickup'; });
    var totalImpact = pipeline.reduce(function (a, r) { return a + r.estimated_impact_aud_monthly; }, 0);
    var awaiting = all.filter(function (r) { return r.status === 'in_clickup'; }).length;
    var card = function (eyebrow, big, sub, cls) {
      return '<div class="kpi bt-kpi ' + (cls || '') + '"><div class="eyebrow">' + eyebrow + '</div><div class="big">' + big + '</div><div class="bt-kpi-sub">' + sub + '</div></div>';
    };
    return '<section class="kpis bt-kpis">' +
      card('Open suggestions', review.length, 'waiting for review, across ' + Object.keys(reviewClients).length + ' clients', '') +
      card('Total est. impact', '<span class="bt-green">+' + k(totalImpact) + '/mo</span>', 'extra value per month if all are approved', '') +
      card('Waiting on the team', '<span class="bt-amber">' + awaiting + '</span>', 'approved and sent, not yet actioned', '') +
      card('Track record (90 days)', '73%', 'of shipped suggestions improved results', '') +
      '</section>';
  }

  // ---- filter row -----------------------------------------------------------
  function sel(id, label, current, options) {
    var opts = options.map(function (o) {
      return '<option value="' + esc(o.v) + '"' + (String(o.v) === String(current) ? ' selected' : '') + '>' + esc(o.t) + '</option>';
    }).join('');
    return '<label class="bt-fld"><span>' + label + '</span><select id="' + id + '" class="bt-select">' + opts + '</select></label>';
  }
  function filterRow(data, f) {
    var clients = Object.keys(data.CLIENT_META);
    var clientOpts = [{ v: 'all', t: 'All clients (' + clients.length + ')' }].concat(clients.map(function (c) { return { v: c, t: data.CLIENT_META[c].name }; }));
    var platforms = uniq(data.RECOMMENDATIONS.map(function (r) { return r.platform; }));
    var platOpts = [{ v: 'all', t: 'All platforms' }].concat(platforms.map(function (p) { return { v: p, t: p }; }));
    var types = uniq(data.RECOMMENDATIONS.map(function (r) { return r.type; }));
    var typeOpts = [{ v: 'all', t: 'All types' }].concat(types.map(function (t) { return { v: t, t: prettyType(t) }; }));
    var confOpts = [{ v: '0.6', t: '≥ 60%' }, { v: '0.75', t: '≥ 75%' }, { v: '0.9', t: '≥ 90%' }];
    var sortOpts = [{ v: 'impact', t: 'Impact ($)' }, { v: 'confidence', t: 'Confidence' }, { v: 'newest', t: 'Newest' }, { v: 'client', t: 'Client' }];
    return '<div class="bt-filterrow">' +
      '<div class="bt-filters-l">' +
      sel('bt-f-client', 'Client', f.client, clientOpts) +
      sel('bt-f-platform', 'Platform', f.platform, platOpts) +
      sel('bt-f-type', 'Type', f.type, typeOpts) +
      sel('bt-f-conf', 'Confidence', String(f.min_conf), confOpts) +
      '</div>' +
      '<div class="bt-filters-r">' + sel('bt-f-sort', 'Sort by', f.sort, sortOpts) + '</div>' +
      '</div>';
  }
  function uniq(a) { var s = {}, o = []; a.forEach(function (x) { if (!s[x]) { s[x] = 1; o.push(x); } }); return o; }

  // ---- table ----------------------------------------------------------------
  function sortRecs(rows, sort) {
    var r = rows.slice();
    if (sort === 'confidence') r.sort(function (a, b) { return b.confidence - a.confidence; });
    else if (sort === 'newest') r.sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); });
    else if (sort === 'client') r.sort(function (a, b) { return a.client_name.localeCompare(b.client_name) || b.estimated_impact_aud_monthly - a.estimated_impact_aud_monthly; });
    else r.sort(function (a, b) { return b.estimated_impact_aud_monthly - a.estimated_impact_aud_monthly; });
    return r;
  }
  function skeletonRows(n) {
    var row = '<tr class="bt-skel-row">' + Array(6).join('0').split('0').map(function () { return '<td><span class="bt-skel"></span></td>'; }).join('') + '</tr>';
    var out = ''; for (var i = 0; i < n; i++) out += row; return out;
  }
  function badge(colors, r, theme) {
    var c = colors.getClientColor(r.client_id, theme);
    return '<span class="bt-cbadge" style="background:' + c.bg + ';color:' + c.fg + ';border-color:' + c.border + '">' + esc(r.client_name) + '</span>';
  }
  function tableBody(rows, colors, theme) {
    if (!rows.length) return '<tr><td colspan="6"><div class="empty">No recommendations match these filters. Try clearing the filter row.</div></td></tr>';
    return rows.map(function (r) {
      return '<tr class="bt-row" data-rid="' + esc(r.id) + '" tabindex="0" role="button">' +
        '<td>' + badge(colors, r, theme) + '</td>' +
        '<td class="bt-plat">' + esc(r.platform) + '</td>' +
        '<td class="bt-recol"><div class="bt-rtitle">' + esc(r.title) + '</div><div class="bt-rsub">' + esc(r.short_description) + ' <span class="bt-rid">' + esc(r.id) + '</span></div></td>' +
        '<td class="bt-num bt-green">+' + k(r.estimated_impact_aud_monthly) + '</td>' +
        '<td class="bt-num bt-conf">' + Math.round(r.confidence * 100) + '%</td>' +
        '<td class="bt-stcell">' + statusPill(r.status) + '</td>' +
        '</tr>';
    }).join('');
  }

  // ---- side cards -----------------------------------------------------------
  function scorePill(n) { var cls = n >= 7 ? 'ok' : (n >= 4 ? 'warn' : 'bad'); return '<span class="bt-score bt-score-' + cls + '">' + n + '/10</span>'; }
  function siteQualityCard() {
    var rows = [['bloomberg.com', 10], ['tech.slashdot.org', 9], ['theverge.com', 8], ['news-blog-xyz.info', 4], ['crazygames-mobile.co', 1], ['streamz-free-live.tv', 1]];
    return '<div class="card bt-card"><div class="card-h"><h3>Site quality index</h3></div>' +
      '<div class="card-sub">Websites where the ads appeared, scored for quality. Low scores are flagged as candidates to block.</div>' +
      '<div class="bt-sqi">' + rows.map(function (r) { return '<div class="bt-sqi-row"><span class="bt-sqi-dom">' + esc(r[0]) + '</span>' + scorePill(r[1]) + '</div>'; }).join('') + '</div>' +
      '<div class="bt-cardfoot">Blocked sites: 147 domains · <button class="bt-link" data-act="manage-list">manage list</button></div></div>';
  }
  function optLogCard() {
    var items = [
      ['3 Jul', 'Trade Desk', 'Added Bloomberg placement line item', 'ok', '▲ +14% CVR over 3 days · keep'],
      ['28 Jun', 'Meta', 'Paused underperforming lookalike audiences', 'ok', '▲ CPA -22% · keep'],
      ['21 Jun', 'Google Ads', 'Broadened match types on brand keywords', 'bad', '▼ +18% waste · rolled back'],
      ['15 Jun', 'LinkedIn', 'Enabled document ads format', 'grey', '◇ measuring · 5 days in']
    ];
    return '<div class="card bt-card"><div class="card-h"><h3>Optimization log</h3></div>' +
      '<div class="card-sub">Changes we have already made, and how each one performed.</div>' +
      '<div class="bt-oplog">' + items.map(function (it) {
        return '<div class="bt-op bt-op-' + it[3] + '"><div class="bt-op-h"><span class="bt-op-date">' + it[0] + ' · ' + it[1] + '</span></div>' +
          '<div class="bt-op-title">' + esc(it[2]) + '</div><div class="bt-op-res bt-op-res-' + it[3] + '">' + it[4] + '</div></div>';
      }).join('') + '</div></div>';
  }

  // ---- footer ---------------------------------------------------------------
  function scanFooter(shown, total) {
    var now = new Date();
    var mins = 3 + (now.getMinutes() % 9);
    var next = new Date(now.getTime() + (11 - (now.getMinutes() % 11)) * 60000);
    var hh = String(next.getHours()).padStart(2, '0'), mm = String(next.getMinutes()).padStart(2, '0');
    return '<div class="bt-tblfoot"><span>Showing ' + shown + ' of ' + total + ' · <button class="bt-link" data-act="show-all">show all</button></span>' +
      '<span>Last scan: ' + mins + ' min ago · next auto-scan ' + hh + ':' + mm + ' AEST</span></div>';
  }

  // ---- shell ----------------------------------------------------------------
  function shell(ctx, skeleton) {
    var data = ctx.data, f = ctx.filters;
    var filtered = sortRecs(data.getFilteredRecommendations({ client_id: f.client, platform: f.platform, type: f.type, min_confidence: parseFloat(f.min_conf) }), f.sort);
    var head =
      '<div class="bt-breadcrumb">The Grid <span>›</span> Brain</div>' +
      '<div class="bt-header"><div><h2 class="bt-h2">' + ICON.brain + ' Brain · all clients</h2>' +
      '<div class="bt-subtitle">Automatic suggestions for improving campaigns, highest-value ideas first. Covers every client.</div></div>' +
      '<div class="bt-header-btns"><button class="ibtn" data-act="historical">' + ICON.scan + 'Historical data</button>' +
      '<button class="ibtn" data-act="rescan">' + ICON.scan + 'Rescan now</button>' +
      '<button class="ibtn" data-act="log">' + ICON.log + 'Log</button></div></div>';
    var table =
      '<section class="card tbl-wrap bt-tblcard"><div class="tableScroll"><table class="bt-table"><thead><tr>' +
      '<th>Client</th><th>Platform</th><th>Recommendation</th><th class="bt-num">Impact</th><th class="bt-num">Confidence</th><th class="bt-num">Status</th>' +
      '</tr></thead><tbody id="bt-tbody">' + (skeleton ? skeletonRows(6) : tableBody(filtered, ctx.colors, ctx.theme)) + '</tbody></table></div>' +
      (skeleton ? '' : scanFooter(filtered.length, data.RECOMMENDATIONS.length)) + '</section>';
    var sideCards = '<section class="bt-sidecards">' + siteQualityCard() + optLogCard() + '</section>';
    return '<div class="bt-wrap">' + head + kpiCards(data) + filterRow(data, f) + table + sideCards + '</div>';
  }

  // ---- wiring ---------------------------------------------------------------
  function wire(mount, ctx) {
    function on(id, ev, fn) { var el = mount.querySelector('#' + id); if (el) el.addEventListener(ev, fn); }
    on('bt-f-client', 'change', function (e) { ctx.setFilters({ client: e.target.value }); });
    on('bt-f-platform', 'change', function (e) { ctx.setFilters({ platform: e.target.value }); });
    on('bt-f-type', 'change', function (e) { ctx.setFilters({ type: e.target.value }); });
    on('bt-f-conf', 'change', function (e) { ctx.setFilters({ min_conf: e.target.value }); });
    on('bt-f-sort', 'change', function (e) { ctx.setFilters({ sort: e.target.value }); });
    mount.querySelectorAll('.bt-row').forEach(function (tr) {
      tr.addEventListener('click', function () { ctx.open(tr.getAttribute('data-rid')); });
      tr.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ctx.open(tr.getAttribute('data-rid')); } });
    });
    mount.querySelectorAll('[data-act]').forEach(function (b) {
      b.addEventListener('click', function () {
        var act = b.getAttribute('data-act');
        if (act === 'historical') { if (ctx.openHistorical) ctx.openHistorical(ctx.filters && ctx.filters.client !== 'all' ? ctx.filters.client : 'resetdata'); }
        else if (act === 'rescan') { ctx.toast && ctx.toast.success('Rescan queued · V1 uses cached mock data'); }
        else if (act === 'log') { var c = mount.querySelector('.bt-sidecards'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
        else if (act === 'show-all') { ctx.setFilters({ client: 'all', platform: 'all', type: 'all', min_conf: '0.6' }); }
        else if (act === 'manage-list') { ctx.toast && ctx.toast.success('Block-list management ships in V2'); }
      });
    });
  }

  function render(mount, ctx) {
    if (!_loaded) { mount.innerHTML = shell(ctx, true); _loaded = true; setTimeout(function () { render(mount, ctx); }, 150); return; }
    mount.innerHTML = shell(ctx, false);
    wire(mount, ctx);
  }

  return { render: render };
});
