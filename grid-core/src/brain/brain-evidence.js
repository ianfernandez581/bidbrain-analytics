/*
 * src/brain/brain-evidence.js  —  Brain evidence drill-down (6 sections)
 * ----------------------------------------------------------------------------
 * BrainEvidence.render(mount, ctx) paints the drill-down for ctx.recId.
 *
 * ctx (from the-grid.html):
 *   data, colors, toast, theme
 *   recId          : the recommendation id from the URL hash
 *   back()         : navigate to the Brain landing
 *   sendToClickup(recId) -> Promise<{ success, mock_task_id, updated_at }>
 *
 * The outperformance chart is hand-rolled SVG to match The Grid (which draws
 * its own SVG charts and does NOT bundle Chart.js). Two series + peak marker.
 *
 * UMD: browser -> window.BrainEvidence.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.BrainEvidence = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var _sentTaskId = {}; // recId -> CU-MOCK-... for this session (mock endpoint is stateless)

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function k(n) { return '$' + Math.round(n / 1000) + 'k'; }
  function money(n, cur) { return (cur || 'AUD') + ' $' + Number(n).toLocaleString('en-AU'); }
  function prettyType(t) { return (t || '').replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); }); }
  function labelKey(kk) { return kk.replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); }); }
  function hoursAgo(iso) { var h = Math.max(1, Math.round((Date.now() - new Date(iso)) / 3600000)); return h < 48 ? (h + 'h ago') : (Math.round(h / 24) + 'd ago'); }
  function dmy(iso) { var d = new Date(iso); return d.getDate() + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()]; }

  var IC = {
    search: ico('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>'),
    chart: ico('<path d="M3 3v18h18"/><path d="m7 14 4-4 3 3 5-6"/>'),
    history: ico('<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>'),
    settings: ico('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.82 1.17V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 8 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 8.4a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>'),
    alert: ico('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4M12 17h.01"/>'),
    check: ico('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>')
  };
  function ico(inner) { return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + '</svg>'; }

  // ---- 404 ------------------------------------------------------------------
  function notFound(mount, ctx, id) {
    mount.innerHTML = '<div class="bt-wrap"><div class="bt-breadcrumb">The Grid <span>›</span> Brain <span>›</span> ' + esc(id || '') + '</div>' +
      '<div class="empty bt-404"><div>Recommendation not found</div><button class="ibtn" data-act="back" style="margin-top:12px">← back to Brain</button></div></div>';
    var b = mount.querySelector('[data-act="back"]'); if (b) b.addEventListener('click', ctx.back);
  }

  // ---- hand-rolled SVG line chart ------------------------------------------
  function chartSVG(series, theme) {
    var W = 700, H = 250, padL = 52, padR = 18, padT = 18, padB = 30;
    var xs = series.map(function (p) { return p.day; });
    var maxV = 0; series.forEach(function (p) { maxV = Math.max(maxV, p.placement_cvr_pct, p.avg_cvr_pct); });
    maxV = maxV * 1.15 || 1;
    var minD = Math.min.apply(null, xs), maxD = Math.max.apply(null, xs);
    function X(d) { return padL + (maxD === minD ? 0 : (d - minD) / (maxD - minD)) * (W - padL - padR); }
    function Y(v) { return H - padB - (v / maxV) * (H - padT - padB); }
    function path(key) { return series.map(function (p, i) { return (i ? 'L' : 'M') + X(p.day).toFixed(1) + ' ' + Y(p[key]).toFixed(1); }).join(' '); }

    var grid = '', ticks = 4;
    for (var t = 0; t <= ticks; t++) {
      var v = maxV * t / ticks, y = Y(v);
      grid += '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) + '" class="bt-cgrid"/>' +
        '<text x="' + (padL - 8) + '" y="' + (y + 3).toFixed(1) + '" text-anchor="end" class="bt-cax">' + v.toFixed(3) + '%</text>';
    }
    var xlabels = '';
    [minD, Math.round((minD + maxD) / 2), maxD].forEach(function (d) {
      xlabels += '<text x="' + X(d).toFixed(1) + '" y="' + (H - padB + 18) + '" text-anchor="middle" class="bt-cax">day ' + d + '</text>';
    });

    // peak of the isolated series
    var peak = series[0]; series.forEach(function (p) { if (p.placement_cvr_pct > peak.placement_cvr_pct) peak = p; });
    var px = X(peak.day), py = Y(peak.placement_cvr_pct);
    var labelRight = px < W - 140;
    var peakMult = peak.avg_cvr_pct ? (peak.placement_cvr_pct / peak.avg_cvr_pct) : 0;
    var peakMark = '<circle cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="4.5" class="bt-cpeak"/>' +
      '<text x="' + (labelRight ? px + 9 : px - 9).toFixed(1) + '" y="' + (py - 8).toFixed(1) + '" text-anchor="' + (labelRight ? 'start' : 'end') + '" class="bt-cpeaklbl">Peak: ' + peak.placement_cvr_pct.toFixed(3) + '% (' + peakMult.toFixed(1) + '× avg)</text>';

    return '<svg class="bt-chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Outperformance over 21 days">' +
      grid + xlabels +
      '<path d="' + path('avg_cvr_pct') + '" class="bt-cavg" fill="none"/>' +
      '<path d="' + path('placement_cvr_pct') + '" class="bt-cplace" fill="none"/>' +
      peakMark + '</svg>';
  }

  function grainToggle() {
    return '<div class="seg bt-grain" role="group" aria-label="Grain">' +
      '<button data-grain="day" aria-pressed="false">Day</button>' +
      '<button data-grain="week" aria-pressed="true">Week</button>' +
      '<button data-grain="month" aria-pressed="false">Month</button></div>';
  }

  // ---- sections -------------------------------------------------------------
  function section(n, icon, title, subtitle, body) {
    return '<section class="card bt-card bt-sec"><div class="bt-sec-h">' + icon +
      '<div><h3>' + n + ' · ' + title + '</h3>' + (subtitle ? '<div class="bt-sec-sub">' + subtitle + '</div>' : '') + '</div></div>' + body + '</section>';
  }

  function metricsCards(m, cur) {
    var cards = [
      ['Impressions', Number(m.impressions).toLocaleString('en-AU')],
      ['Spend', money(m.spend_aud, cur)],
      ['Conversions', Number(m.conversions).toLocaleString('en-AU')],
      ['CVR', m.cvr_pct + '% <span class="bt-vs">' + m.cvr_vs_avg_multiple + '× vs avg</span>']
    ];
    return '<div class="bt-metrics">' + cards.map(function (c) {
      return '<div class="bt-metric"><div class="bt-metric-l">' + c[0] + '</div><div class="bt-metric-v">' + c[1] + '</div></div>';
    }).join('') + '</div>';
  }

  function historyBody(hist) {
    var wins = hist.filter(function (h) { return h.result === 'win'; }).length;
    var rows = hist.map(function (h) {
      var cls = h.result === 'win' ? 'bt-green' : 'bt-red';
      var sign = h.outcome_aud >= 0 ? '+' : '−';
      return '<div class="bt-hist-row"><div class="bt-hist-l"><div class="bt-hist-name">' + esc(h.name) + '</div><div class="bt-hist-note">' + esc(h.date) + ' · ' + esc(h.note) + '</div></div>' +
        '<div class="bt-hist-out ' + cls + '">' + sign + k(Math.abs(h.outcome_aud)) + '</div></div>';
    }).join('');
    return rows + '<div class="bt-callout">' + wins + ' of ' + hist.length + ' comparable plays won — the pattern favours shipping this, with the loss as a documented guardrail.</div>';
  }

  function configBody(cfg) {
    var rows = Object.keys(cfg).map(function (kk) {
      return '<tr><td class="bt-cfg-k">' + esc(labelKey(kk)) + '</td><td class="bt-cfg-v">' + esc(cfg[kk]) + '</td></tr>';
    }).join('');
    return '<table class="bt-cfg"><tbody>' + rows + '</tbody></table>';
  }

  function risksBody(risks) {
    return '<div class="bt-risks">' + risks.map(function (r) {
      return '<div class="bt-risk">' + IC.alert + '<div><div class="bt-risk-t">' + esc(r.title) + '</div><div class="bt-risk-b">' + esc(r.body) + '</div></div></div>';
    }).join('') + '</div>';
  }

  function previewBody(p, recId) {
    var top = '<div class="bt-cu-top"><span class="bt-tag bt-tag-type">Optimization</span>' +
      '<span class="bt-tag bt-cu-prio bt-cu-prio-' + esc(p.priority) + '">' + esc(p.priority) + '</span>' +
      '<span class="bt-cu-due">Due ' + esc(p.due_date) + '</span></div>';
    var foot = '<div class="bt-cu-foot"><span>Assignee: <b>' + esc(p.assignee) + '</b></span><span>Project: <b>' + esc(p.project) + '</b></span><span>Links back to ' + esc(p.links_to_r_id || recId) + '</span></div>';
    return '<div class="bt-cu">' + top +
      '<div class="bt-cu-title">' + esc(p.title) + '</div>' +
      '<div class="bt-cu-desc">' + esc(p.description) + '</div>' + foot + '</div>';
  }

  // ---- action buttons -------------------------------------------------------
  function actionRow(rec) {
    if (rec.status === 'review') {
      return '<div class="bt-actions">' +
        '<button class="bt-btn bt-btn-primary" data-act="send">Send to ClickUp</button>' +
        '<button class="bt-btn" data-act="snooze">Snooze 7 days</button>' +
        '<button class="bt-btn" data-act="dismiss">Dismiss with reason</button></div>';
    }
    var msg;
    if (rec.status === 'in_clickup') { var tid = _sentTaskId[rec.id]; msg = tid ? ('Sent to ClickUp ' + tid + ' on ' + dmy(new Date().toISOString())) : 'Sent to ClickUp · awaiting trader'; }
    else if (rec.status === 'measuring') msg = 'Live and measuring against baseline';
    else if (rec.status === 'won') msg = 'Won — moved to the optimization log';
    else if (rec.status === 'rolled_back') msg = 'Rolled back — did not clear baseline';
    else if (rec.status === 'dismissed') msg = 'Dismissed';
    else msg = rec.status;
    return '<div class="bt-actions"><button class="bt-btn bt-btn-done" disabled>' + (rec.status === 'in_clickup' ? 'Sent to ClickUp ✓' : msg) + '</button>' +
      (rec.status === 'in_clickup' ? '<span class="bt-actionmsg">' + esc(msg) + '</span>' : '') + '</div>';
  }

  // ---- shell ----------------------------------------------------------------
  function shell(ctx, rec) {
    var m = rec.evidence.metrics_21d, cur = rec.currency;
    var head =
      '<div class="bt-breadcrumb"><button class="bt-crumblink" data-act="home">The Grid</button> <span>›</span> <button class="bt-crumblink" data-act="back">Brain</button> <span>›</span> ' + esc(rec.client_name) + ' <span>›</span> Recommendation #' + esc(rec.id) + '</div>' +
      '<div class="bt-ev-head"><div class="bt-ev-head-l">' +
      '<h2 class="bt-ev-title">' + esc(rec.title) + '</h2>' +
      '<div class="bt-ev-tags"><span class="bt-tag bt-tag-plat">' + esc(rec.platform) + '</span><span class="bt-tag bt-tag-type">' + esc(prettyType(rec.type)) + '</span>' +
      '<span class="bt-ev-conf">Confidence ' + Math.round(rec.confidence * 100) + '% · generated ' + hoursAgo(rec.created_at) + '</span></div></div>' +
      '<div class="bt-ev-head-r"><div class="bt-ev-impact-l">Estimated monthly impact</div><div class="bt-ev-impact bt-green">+' + k(rec.estimated_impact_aud_monthly) + '<span>/mo</span></div>' +
      '<button class="bt-link" data-act="historical" style="margin-top:6px">Historical data →</button></div></div>';

    var lineage = lineageRow(rec);
    var actions = actionRow(rec);

    var s1 = section(1, IC.search, 'What we noticed', 'The signal that triggered this recommendation.',
      metricsCards(m, cur) + '<p class="bt-detail">' + esc(rec.evidence.detail_paragraph) + '</p>');
    var s2 = section(2, IC.chart, 'The outperformance, over time', 'Day-by-day rate for this recommendation vs the channel average — not one lucky day, a sustained pattern.',
      '<div class="bt-chart-h"><div class="bt-legend"><span class="bt-lg bt-lg-place">this recommendation</span><span class="bt-lg bt-lg-avg">channel average</span></div>' + grainToggle() + '</div>' +
      '<div class="bt-chart-wrap">' + chartSVG(rec.evidence.time_series, ctx.theme) + '</div>' +
      '<div class="bt-grain-note" id="bt-grain-note"></div>' +
      '<div class="bt-fraudbox">✓ Sustained, not spiky. Outperformed on ' + esc(rec.evidence.outperformance_days) + ' days. ' + esc(rec.evidence.fraud_check) + '</div>');
    var s3 = section(3, IC.history, 'Historical pattern', 'Similar plays we’ve made before, for this client or others.', historyBody(rec.historical_pattern));
    var hasCfg = rec.proposed_config && Object.keys(rec.proposed_config).length;
    var s4 = hasCfg ? section(4, IC.settings, 'Proposed ' + esc(rec.platform) + ' config', 'The exact change the trader will build. Editable before sending.', configBody(rec.proposed_config)) : '';
    var s5 = section(5, IC.alert, 'Risks and assumptions', 'What could go wrong. Read this before approving.', risksBody(rec.risks));
    var s6 = section(6, IC.check, 'ClickUp task preview', 'What gets created when you click Send to ClickUp.', previewBody(rec.clickup_task_preview, rec.id));

    var bottom = '<section class="card bt-card bt-bottombar"><div class="bt-bottombar-txt">After the trader confirms in ClickUp, this recommendation moves to the Optimization log on Brain and starts tracking measured impact against the +' + k(rec.estimated_impact_aud_monthly) + '/mo estimate.</div>' +
      (rec.status === 'review' ? '<button class="bt-btn bt-btn-primary" data-act="send">Send to ClickUp</button>' : '<button class="bt-btn bt-btn-done" disabled>' + (rec.status === 'in_clickup' ? 'Sent to ClickUp ✓' : 'Actioned') + '</button>') + '</section>';

    return '<div class="bt-wrap bt-evidence">' + head + lineage + actions + s1 + s2 + s3 + s4 + s5 + s6 + bottom + '</div>';
  }

  // Data lineage: the real BigQuery table(s) a V2 engine would read, plus an honest flag
  // for recs (placement / site-quality) the current pipeline can't derive yet.
  function lineageRow(rec) {
    var src = (rec.data_source || []).map(function (s) { return '<code class="bt-src">' + esc(s) + '</code>'; }).join(' ');
    var badge = rec.data_readiness === 'needs_ingest'
      ? '<span class="bt-ready bt-ready-warn" title="No per-placement / per-domain breakdown is ingested yet — needs a new ingest before this can run on live data.">needs placement-level ingest</span>'
      : '<span class="bt-ready bt-ready-ok">live data source</span>';
    return '<div class="bt-lineage">' + badge + '<span class="bt-lineage-src">Source: ' + (src || '—') + '</span></div>';
  }

  // ---- wiring ---------------------------------------------------------------
  function wire(mount, ctx, rec) {
    mount.querySelectorAll('[data-act="back"],[data-act="home"]').forEach(function (b) { b.addEventListener('click', ctx.back); });
    mount.querySelectorAll('[data-act="historical"]').forEach(function (b) { b.addEventListener('click', function () { if (ctx.openHistorical) ctx.openHistorical(rec.client_id); }); });
    mount.querySelectorAll('.bt-grain button').forEach(function (b) {
      b.addEventListener('click', function () {
        mount.querySelectorAll('.bt-grain button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        var g = b.getAttribute('data-grain'), note = mount.querySelector('#bt-grain-note');
        if (note) note.textContent = (g === 'week') ? '' : (g.charAt(0).toUpperCase() + g.slice(1) + ' view coming in V3 — currently showing week.');
      });
    });
    mount.querySelectorAll('[data-act="snooze"]').forEach(function (b) { b.addEventListener('click', function () { ctx.toast && ctx.toast.success('Snoozed 7 days · reappears then (V1: not persisted)'); }); });
    mount.querySelectorAll('[data-act="dismiss"]').forEach(function (b) { b.addEventListener('click', function () { ctx.toast && ctx.toast.success('Dismissed · reason capture ships in V2'); }); });

    var sendBtns = mount.querySelectorAll('[data-act="send"]');
    sendBtns.forEach(function (b) {
      b.addEventListener('click', function () {
        sendBtns.forEach(function (x) { x.disabled = true; x.textContent = 'Sending…'; });
        ctx.sendToClickup(rec.id).then(function (res) {
          if (res && res.success) {
            _sentTaskId[rec.id] = res.mock_task_id;
            ctx.toast && ctx.toast.success('Sent to ClickUp · ' + res.mock_task_id);
            render(mount, ctx); // status is now in_clickup in the store -> repaints "Sent ✓"
          } else { throw new Error('no success flag'); }
        }).catch(function (err) {
          sendBtns.forEach(function (x) { x.disabled = false; x.textContent = 'Send to ClickUp'; });
          ctx.toast && ctx.toast.error('Could not send to ClickUp · ' + (err && err.message ? err.message : 'try again'));
        });
      });
    });
  }

  function render(mount, ctx) {
    var rec = ctx.data.getRecommendationById(ctx.recId);
    if (!rec) { notFound(mount, ctx, ctx.recId); return; }
    mount.innerHTML = shell(ctx, rec);
    wire(mount, ctx, rec);
  }

  return { render: render };
});
