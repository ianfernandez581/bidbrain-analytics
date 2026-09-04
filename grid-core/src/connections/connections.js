/* Connections tab - Windsor connector health, per client and per account.
 *
 * Classic script, same pattern as Greenlight / the Brain modules: attaches
 * window.Connections with render(mount) and renders into #view-connections
 * inside the-grid.html on the Grid's own CSS variables. Talks to
 * api/connections (RELATIVE path, so it works behind the platform proxy at
 * /d/central/).
 *
 * The data is windsor_connections.json, written hourly by the
 * windsor-connections-probe Cloud Run job (ingest/windsor_data_pull/connections/).
 * This file renders; it never classifies. Every verdict on screen (ok / frozen /
 * not granted / error / idle) was decided by the probe, so the tab and the
 * alert emails can never disagree about an account's state.
 *
 * Why it exists: a lapsed Windsor grant does not fail anything. The loader
 * exits green while at least one account still resolves, the raw table keeps a
 * fresh last_modified from the surviving accounts, and every dashboard on the
 * dead accounts silently serves last week's numbers. The first person to
 * notice was a client. This tab is the per-ACCOUNT view nothing else had. */
(function () {
  'use strict';

  var API = 'api/connections';

  var S = {
    doc: null,          // the JSON as served
    loading: false,
    err: null,
    fetchedAt: null,
    filter: { state: null, ds: null, q: '', showIdle: false },
    expanded: {},       // 'ds:group' -> true when a collapsed group row has been opened
    probing: false,
    mounted: false,
    timer: null
  };

  var STATE = {
    ok:          { lbl: 'Healthy',      c: 'var(--ok)',    soft: 'var(--ok-soft)',   d: 'granted and delivering' },
    frozen:      { lbl: 'Frozen',       c: 'var(--warn)',  soft: 'var(--warn-soft)', d: 'Windsor has rows our loader is not landing' },
    quiet:       { lbl: 'Quiet',        c: '#7E93AD',      soft: 'rgba(126,147,173,.16)', d: 'granted, but the platform reports no delivery' },
    not_granted: { lbl: 'Not granted',  c: 'var(--bad)',   soft: 'var(--bad-soft)',  d: 'Windsor no longer holds this account' },
    error:       { lbl: 'Error',        c: 'var(--tx)',    soft: 'var(--tx-soft)',   d: 'the connector answered with an error' },
    idle:        { lbl: 'Idle',         c: 'var(--ink-3)', soft: 'var(--line-2)',    d: 'expected to be quiet - campaign ended or retired' }
  };
  var SEV = { not_granted: 0, error: 1, frozen: 2, quiet: 3, ok: 4, idle: 5 };

  var CSS = [
    '#view-connections{padding:2px 0 44px}',
    '#view-connections .cx-hero{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap;padding:4px 0 8px}',
    '#view-connections .cx-eyebrow{font-family:"Space Grotesk";font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--brand)}',
    '#view-connections .cx-hero h2{font-family:"Space Grotesk";font-size:23px;font-weight:600;letter-spacing:-.5px;margin:6px 0 4px;color:var(--ink)}',
    '#view-connections .cx-hero p{margin:0;font-size:12.5px;color:var(--ink-2);max-width:78ch;line-height:1.5}',
    '#view-connections .cx-right{margin-left:auto;display:flex;align-items:center;gap:9px;flex-wrap:wrap;padding-bottom:6px}',
    '#view-connections .cx-probed{font-size:11px;color:var(--ink-3);white-space:nowrap;text-align:right;line-height:1.4}',
    '#view-connections .cx-probed b{color:var(--ink-2);font-weight:600}',
    '#view-connections .cx-sync{appearance:none;cursor:pointer;font-family:inherit;font-size:12px;font-weight:700;display:inline-flex;align-items:center;gap:7px;color:var(--pill-fg);background:var(--brand);border:1px solid var(--brand);border-radius:9px;padding:8px 15px;box-shadow:var(--shadow);transition:filter .13s}',
    '#view-connections .cx-sync:hover{filter:brightness(1.05)}#view-connections .cx-sync:disabled{cursor:default;opacity:.85}',
    '#view-connections .cx-sync .sp{display:none;width:12px;height:12px;border-radius:50%;border:2px solid rgba(0,0,0,.28);border-top-color:currentColor}',
    '#view-connections .cx-sync.busy .sp{display:inline-block;animation:cx-spin .7s linear infinite}',
    '@keyframes cx-spin{to{transform:rotate(360deg)}}',
    '#view-connections .cx-mail{display:inline-flex;align-items:center;gap:7px;font-size:11.5px;color:var(--ink-2);background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:7px 11px;box-shadow:var(--shadow)}',
    '#view-connections .cx-mail .md{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px var(--ok-soft);flex:none}',
    '#view-connections .cx-mail.off .md{background:var(--ink-3);box-shadow:0 0 0 3px var(--line-2)}',
    '#view-connections .cx-mail b{color:var(--ink);font-weight:600}',
    /* summary tiles */
    '#view-connections .cx-summary{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:12px 0 4px}',
    '@media(max-width:1100px){#view-connections .cx-summary{grid-template-columns:repeat(3,1fr)}}',
    '@media(max-width:720px){#view-connections .cx-summary{grid-template-columns:1fr 1fr}}',
    '#view-connections .cx-scard{appearance:none;text-align:left;cursor:pointer;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px 13px;position:relative;overflow:hidden;box-shadow:var(--shadow);transition:transform .13s,border-color .13s;color:inherit;font-family:inherit}',
    '#view-connections .cx-scard:hover{transform:translateY(-1px)}',
    '#view-connections .cx-scard[aria-pressed="true"]{border-color:var(--ink-3)}',
    '#view-connections .cx-scard .base{position:absolute;left:0;right:0;bottom:0;height:3px}',
    '#view-connections .cx-scard[aria-pressed="true"] .base{height:4px}',
    '#view-connections .cx-scard .n{font-family:"Space Grotesk";font-size:26px;font-weight:600;letter-spacing:-.6px;line-height:1;color:var(--ink)}',
    '#view-connections .cx-scard .l{font-size:11.5px;color:var(--ink-2);margin-top:6px;display:flex;align-items:center;gap:7px;font-weight:600}',
    '#view-connections .cx-scard .s{font-size:10.5px;color:var(--ink-3);margin-top:3px}',
    '#view-connections .cx-scard.static{cursor:default}#view-connections .cx-scard.static:hover{transform:none}',
    '#view-connections .cx-dot{width:9px;height:9px;border-radius:50%;flex:none}',
    /* filter bar */
    '#view-connections .cx-fbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0 6px}',
    '#view-connections .cx-flabel{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3)}',
    '#view-connections .cx-pill{appearance:none;cursor:pointer;font-family:inherit;font-size:12px;font-weight:600;color:var(--ink-2);background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:6px 13px;transition:all .13s}',
    '#view-connections .cx-pill:hover{color:var(--ink);border-color:var(--brand)}',
    '#view-connections .cx-pill.on{color:var(--pill-fg);background:var(--pill-bg);border-color:var(--pill-bg)}',
    '#view-connections .cx-search{position:relative;margin-left:auto}',
    '#view-connections .cx-search input{font-family:inherit;font-size:12px;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px 8px 31px;width:210px;box-shadow:var(--shadow);outline:none;transition:border .15s,box-shadow .15s}',
    '#view-connections .cx-search input:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}',
    '#view-connections .cx-search svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--ink-3)}',
    '#view-connections .cx-count{font-size:12px;color:var(--ink-3)}#view-connections .cx-count b{color:var(--ink);font-family:"Space Grotesk";font-weight:600}',
    '#view-connections .cx-clear{appearance:none;cursor:pointer;font-family:inherit;font-size:11.5px;font-weight:600;color:var(--ink-2);background:transparent;border:0;padding:4px 6px;border-radius:6px}',
    '#view-connections .cx-clear:hover{color:var(--bad)}',
    /* horizon (grant timeline) */
    '#view-connections .cx-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);margin-top:13px}',
    '#view-connections .cx-card-h{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:16px 18px 0;flex-wrap:wrap}',
    '#view-connections .cx-card-h h3{font-family:"Space Grotesk";font-size:14px;font-weight:600;margin:0;letter-spacing:-.1px}',
    '#view-connections .cx-card-h .meta{font-size:11px;color:var(--ink-2)}',
    '#view-connections .cx-card-sub{padding:2px 18px 0;font-size:11px;color:var(--ink-2);line-height:1.5}',
    '#view-connections .cx-hz{padding:12px 18px 16px;display:grid;grid-template-columns:170px 1fr 150px;gap:10px 14px;align-items:center}',
    '#view-connections .cx-hz .nm{font-weight:600;font-size:12.5px;display:flex;align-items:center;gap:8px;min-width:0}',
    '#view-connections .cx-hz .nm small{color:var(--ink-3);font-weight:500;font-size:10.5px}',
    '#view-connections .cx-hz .tr{position:relative;height:10px;border-radius:6px;background:var(--line-2);overflow:visible}',
    '#view-connections .cx-hz .tr .fl{position:absolute;left:0;top:0;bottom:0;border-radius:6px}',
    '#view-connections .cx-hz .tr .now{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--ink);opacity:.6;border-radius:2px}',
    '#view-connections .cx-hz .tr .tk{position:absolute;top:13px;font-size:9.5px;color:var(--ink-3);transform:translateX(-50%);white-space:nowrap}',
    '#view-connections .cx-hz .rem{text-align:right;font-size:11.5px;color:var(--ink-2);white-space:nowrap}',
    '#view-connections .cx-hz .rem b{color:var(--ink);font-family:"Space Grotesk";font-weight:600}',
    '#view-connections .cx-hz .rem.soon b{color:var(--bad)}#view-connections .cx-hz .rem.wk b{color:var(--warn)}',
    '#view-connections .cx-hz-row{display:contents}',
    '#view-connections .cx-hz-row.pad>*{padding-bottom:12px}',
    '@media(max-width:820px){#view-connections .cx-hz{grid-template-columns:1fr}#view-connections .cx-hz .rem{text-align:left}}',
    /* datasource sections */
    '#view-connections .cx-sec{margin-top:18px}',
    '#view-connections .cx-ds{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);overflow:hidden}',
    '#view-connections .cx-ds-h{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid var(--line-2);flex-wrap:wrap}',
    '#view-connections .cx-mono{width:34px;height:34px;flex:none;border-radius:9px;display:grid;place-items:center;font-family:"Space Grotesk";font-weight:700;font-size:12px;background:var(--grp);border:1px solid var(--line);color:var(--ink-2)}',
    '#view-connections .cx-ds-nm{font-family:"Space Grotesk";font-weight:600;font-size:14.5px;color:var(--ink);line-height:1.1}',
    '#view-connections .cx-ds-sub{font-size:10.5px;color:var(--ink-3);margin-top:3px;display:flex;gap:10px;flex-wrap:wrap}',
    '#view-connections .cx-ds-sub b{color:var(--ink-2);font-weight:600}',
    '#view-connections .cx-ds-r{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap}',
    '#view-connections .cx-verd{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:700;padding:4px 9px;border-radius:999px;white-space:nowrap}',
    '#view-connections .cx-link{font-size:11.5px;font-weight:600;color:var(--brand-ink);text-decoration:none;white-space:nowrap}',
    '#view-connections .cx-link:hover{text-decoration:underline}',
    '#view-connections table.cx{border-collapse:separate;border-spacing:0;width:100%;font-size:12px;white-space:nowrap}',
    '#view-connections table.cx thead th{position:static;background:var(--panel);text-align:left;font-weight:600;font-size:10px;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3);padding:9px 14px;border-bottom:1px solid var(--line);cursor:default}',
    '#view-connections table.cx thead th.r,#view-connections table.cx td.r{text-align:right}',
    '#view-connections table.cx tbody td{padding:10px 14px;border-bottom:1px solid var(--line-2);vertical-align:middle}',
    '#view-connections table.cx tbody tr:last-child td{border-bottom:0}',
    '#view-connections table.cx tbody tr:hover td{background:var(--panel-2)}',
    '#view-connections table.cx tr.s-not_granted td:first-child{box-shadow:inset 3px 0 0 var(--bad)}',
    '#view-connections table.cx tr.s-error td:first-child{box-shadow:inset 3px 0 0 var(--tx)}',
    '#view-connections table.cx tr.s-frozen td:first-child{box-shadow:inset 3px 0 0 var(--warn)}',
    '#view-connections table.cx tr.s-idle td{color:var(--ink-3)}',
    '#view-connections .cx-cl{font-weight:600;color:var(--ink);display:flex;align-items:center;gap:8px}',
    '#view-connections .cx-cl .cd{width:8px;height:8px;border-radius:50%;flex:none}',
    '#view-connections .cx-acct{color:var(--ink-2)}#view-connections .cx-acct code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;color:var(--ink-3);margin-left:6px}',
    '#view-connections .cx-day{font-variant-numeric:tabular-nums}',
    '#view-connections .cx-behind{font-family:"Space Grotesk";font-weight:600}',
    '#view-connections .cx-behind.b0{color:var(--ok)}#view-connections .cx-behind.b1{color:var(--warn)}#view-connections .cx-behind.b2{color:var(--bad)}',
    '#view-connections .cx-fix{color:var(--ink-2);white-space:normal;max-width:360px;line-height:1.45}',
    '#view-connections .cx-fix b{color:var(--ink);font-weight:600}',
    '#view-connections .cx-tbl-wrap{overflow-x:auto}',
    /* alert log */
    '#view-connections .cx-log{padding:6px 10px 12px}',
    '#view-connections .cx-lrow{display:grid;grid-template-columns:150px 1fr auto;gap:14px;align-items:center;padding:10px 10px;border-radius:10px}',
    '#view-connections .cx-lrow + .cx-lrow{border-top:1px solid var(--line-2)}',
    '#view-connections .cx-lrow .when{font-size:11.5px;color:var(--ink-3);font-variant-numeric:tabular-nums}',
    '#view-connections .cx-lrow .subj{font-size:12.5px;font-weight:600;color:var(--ink);white-space:normal}',
    '#view-connections .cx-lrow .to{font-size:11px;color:var(--ink-3);white-space:nowrap}',
    '#view-connections .cx-empty{padding:40px 18px;text-align:center;color:var(--ink-3);font-size:13px}',
    '#view-connections .cx-never{padding:34px 22px;text-align:center}',
    '#view-connections .cx-never h3{font-family:"Space Grotesk";font-size:16px;margin:0 0 8px;color:var(--ink)}',
    '#view-connections .cx-never p{margin:0 auto;max-width:62ch;font-size:12.5px;color:var(--ink-2);line-height:1.55}',
    '#view-connections .cx-never code{display:inline-block;margin-top:12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 12px;color:var(--ink)}',
    '#view-connections .cx-note{display:flex;gap:8px;align-items:flex-start;font-size:11.5px;color:var(--ink-2);line-height:1.5;padding:0 18px 14px}',
    '#view-connections .cx-note .nb{flex:none;width:14px;height:2px;border-radius:2px;background:var(--brand);margin-top:8px}',
    '#view-connections .cx-est{font-size:9.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);border:1px solid var(--line);border-radius:6px;padding:1px 6px;margin-left:6px;vertical-align:middle}',
    '@media(prefers-reduced-motion:reduce){#view-connections .cx-sync.busy .sp{animation:none}}'
  ].join('\n');

  /* ---------------- helpers ---------------- */
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmtDay(d) { if (!d) return '-'; var t = new Date(d + 'T00:00:00Z'); if (isNaN(t)) return esc(d); return t.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', timeZone: 'UTC' }); }
  function fmtWhen(iso) { if (!iso) return '-'; var t = new Date(iso); if (isNaN(t)) return esc(iso); return t.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
  function ago(iso) {
    if (!iso) return null; var ms = Date.now() - new Date(iso).getTime(); if (isNaN(ms)) return null;
    var m = Math.round(ms / 60000); if (m < 1) return 'just now'; if (m < 60) return m + ' min ago';
    var h = Math.round(m / 60); if (h < 36) return h + ' h ago'; return Math.round(h / 24) + ' d ago';
  }
  function daysUntil(day) { if (!day) return null; var t = new Date(day + 'T00:00:00Z'); if (isNaN(t)) return null; return Math.round((t - Date.now()) / 86400000); }
  function mono(label) { var w = String(label || '?').replace(/[^A-Za-z0-9 ]/g, ' ').trim().split(/\s+/); return (w.length > 1 ? w[0][0] + w[1][0] : (w[0] || '?').slice(0, 2)).toUpperCase(); }
  // the Grid's shared per-client hue (src/brain/client-colors.js) so a client is the same colour here as on Brain
  function clientColor(name) { try { if (name && window.BrainColors && window.BrainColors.getClientColor) return window.BrainColors.getClientColor(String(name).toLowerCase()).fg; } catch (e) { } return 'var(--ink-3)'; }
  function stateOf(s) { return STATE[s] || STATE.error; }
  function isIdle(a) { return a.state === 'idle'; }

  function accounts(doc) {
    var out = [];
    ((doc && doc.datasources) || []).forEach(function (ds) { (ds.accounts || []).forEach(function (a) { out.push({ ds: ds, a: a }); }); });
    return out;
  }
  function counts(doc) {
    var c = { ok: 0, frozen: 0, quiet: 0, not_granted: 0, error: 0, idle: 0 };
    accounts(doc).forEach(function (x) { c[x.a.state] = (c[x.a.state] || 0) + 1; });
    return c;
  }
  // Red count for the nav button: only states that page us, only accounts that can
  // (alerts:true) - a standby LinkedIn account nobody reads must not light the tab.
  function redCount(doc) {
    return accounts(doc).filter(function (x) { return x.a.alerts && (x.a.state === 'not_granted' || x.a.state === 'frozen' || x.a.state === 'error'); }).length;
  }
  function paintNavBadge(doc) {
    var b = document.getElementById('navConnBadge'); if (!b) return;
    var n = doc && !doc.never_run ? redCount(doc) : 0;
    b.textContent = n; b.style.display = n ? '' : 'none';
    b.title = n ? n + ' account' + (n === 1 ? '' : 's') + ' on a client path need attention' : '';
  }
  function passes(ds, a) {
    var f = S.filter;
    if (f.state && a.state !== f.state) return false;
    if (!f.state && !f.showIdle && a.state === 'idle') return false;
    if (f.ds && ds.ds !== f.ds) return false;
    if (f.q) {
      var hay = [a.client_label, a.client, a.name, a.id, ds.label, a.state].join(' ').toLowerCase();
      if (hay.indexOf(f.q) < 0) return false;
    }
    return true;
  }

  /* ---------------- render pieces ---------------- */
  function hero(doc) {
    var probed = doc && doc.generated_at;
    var alerts = (doc && doc.alerts) || {};
    var mailOn = !!alerts.enabled;
    var to = (alerts.recipients || []).join(', ');
    return '<div class="cx-hero"><div>'
      + '<div class="cx-eyebrow">Connections</div>'
      + '<h2>Windsor connections</h2>'
      + '<p>Every Windsor account we ingest, probed hourly against the connector itself and against the newest day it landed in BigQuery. A grant that lapses never fails a job - the loader stays green while one account survives - so this is the per-account view. Red and amber here email ' + (to ? esc(to) : 'the team') + ' the moment a state changes.</p>'
      + '</div><div class="cx-right">'
      + '<span class="cx-mail' + (mailOn ? '' : ' off') + '" title="' + (mailOn ? 'State changes are emailed to ' + esc(to) : 'Email alerts are not configured - the probe logs alerts but cannot send them yet') + '"><span class="md"></span>Email alerts <b>' + (mailOn ? 'on' : 'off') + '</b></span>'
      + '<div class="cx-probed">' + (probed ? 'Last probe <b>' + esc(ago(probed)) + '</b><br>' + esc(fmtWhen(probed)) + ' · hourly' : 'Never probed') + '</div>'
      + '<button class="cx-sync" id="cxProbe"' + (S.probing ? ' disabled' : '') + '><span class="sp"></span><span class="sl">' + (S.probing ? 'Probing' : 'Probe now') + '</span></button>'
      + '</div></div>';
  }

  function summary(doc) {
    var c = counts(doc);
    var h = '<div class="cx-summary">';
    ['not_granted', 'frozen', 'quiet', 'ok'].forEach(function (k) {
      var v = STATE[k];
      var n = k === 'ok' ? c.ok : c[k];
      var sub = v.d;
      if (k === 'not_granted' && c.error) sub = v.d + ' · plus ' + c.error + ' error' + (c.error === 1 ? '' : 's');
      h += '<button class="cx-scard" data-state="' + k + '" aria-pressed="' + (S.filter.state === k) + '"><div class="base" style="background:' + v.c + '"></div><div class="n">' + n + '</div><div class="l"><span class="cx-dot" style="background:' + v.c + '"></span>' + v.lbl + '</div><div class="s">' + esc(sub) + '</div></button>';
    });
    // next estimated expiry - the "when will it time out" tile
    var next = nextExpiry(doc);
    if (next) {
      var d = next.days; var col = d <= 7 ? 'var(--bad)' : d <= 21 ? 'var(--warn)' : 'var(--brand)';
      h += '<div class="cx-scard static"><div class="base" style="background:' + col + '"></div><div class="n">' + (d < 0 ? 'overdue' : d + '<span style="font-size:14px;color:var(--ink-3);font-weight:500"> days</span>') + '</div><div class="l"><span class="cx-dot" style="background:' + col + '"></span>Next grant likely to expire<span class="cx-est" title="Windsor exposes no expiry date. This is the platform\'s typical token lifetime counted from the last re-authorisation we recorded.">est.</span></div><div class="s">' + esc(next.label) + ' · re-authed ' + fmtDay(next.last_reauth) + '</div></div>';
    } else {
      h += '<div class="cx-scard static"><div class="base" style="background:var(--line)"></div><div class="n" style="color:var(--ink-3)">-</div><div class="l"><span class="cx-dot" style="background:var(--ink-3)"></span>Next grant likely to expire<span class="cx-est">est.</span></div><div class="s">no re-authorisation dates recorded yet</div></div>';
    }
    return h + '</div>';
  }

  function nextExpiry(doc) {
    var best = null;
    ((doc && doc.datasources) || []).forEach(function (ds) {
      var g = ds.grant || {};
      if (!g.expiry_estimate) return;
      var d = daysUntil(g.expiry_estimate);
      if (d == null) return;
      if (!best || d < best.days) best = { days: d, label: ds.label, last_reauth: g.effective_reauth || g.last_reauth, ds: ds.ds };
    });
    return best;
  }

  function filterBar(doc, shownN, totalN) {
    var dss = (doc && doc.datasources) || [];
    var f = S.filter; var active = (f.state ? 1 : 0) + (f.ds ? 1 : 0) + (f.q ? 1 : 0) + (f.showIdle ? 1 : 0);
    var h = '<div class="cx-fbar"><span class="cx-flabel">Source</span><button class="cx-pill' + (f.ds ? '' : ' on') + '" data-ds="">All</button>';
    dss.forEach(function (ds) { h += '<button class="cx-pill' + (f.ds === ds.ds ? ' on' : '') + '" data-ds="' + esc(ds.ds) + '">' + esc(ds.label) + '</button>'; });
    h += '<button class="cx-pill' + (f.showIdle ? ' on' : '') + '" id="cxIdle" title="Idle accounts are ones we expect to be quiet: a finished flight or a retired account. Hidden by default so the list is only things that can be acted on.">Show idle</button>';
    h += '<span class="cx-count">' + (active ? 'Showing <b>' + shownN + '</b> of ' + totalN : '<b>' + totalN + '</b> accounts') + '</span>';
    if (active) h += '<button class="cx-clear" id="cxClear">Clear</button>';
    h += '<div class="cx-search"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg><input id="cxQ" type="search" placeholder="Find client or account" autocomplete="off" value="' + esc(f.q) + '"></div></div>';
    return h;
  }

  function horizon(doc) {
    var dss = ((doc && doc.datasources) || []).filter(function (d) { return d.grant && (d.grant.effective_reauth || d.grant.last_reauth || d.grant.expiry_estimate); });
    if (!dss.length) return '';
    var h = '<div class="cx-card"><div class="cx-card-h"><h3>Grant horizon</h3><span class="meta">estimated - Windsor publishes no expiry</span></div>'
      + '<div class="cx-card-sub">Each bar runs from the day a connector was last re-authorised to the day its platform token typically expires. The dark marker is today. The re-authorisation date is OBSERVED by the probe - the hour Windsor starts holding accounts it did not hold before, the bar resets on its own - with the hand-recorded date in the probe config as the fallback. The lifetime is the platform\'s typical one; Windsor itself publishes no expiry.</div>'
      + '<div class="cx-hz">';
    dss.sort(function (a, b) { return (daysUntil(a.grant.expiry_estimate) == null ? 9e9 : daysUntil(a.grant.expiry_estimate)) - (daysUntil(b.grant.expiry_estimate) == null ? 9e9 : daysUntil(b.grant.expiry_estimate)); });
    dss.forEach(function (ds) {
      var g = ds.grant; var ra = g.effective_reauth || g.last_reauth; var obsv = g.effective_reauth_source === 'observed';
      var start = ra ? new Date(ra + 'T00:00:00Z') : null; var end = g.expiry_estimate ? new Date(g.expiry_estimate + 'T00:00:00Z') : null;
      var pct = 0, rem = daysUntil(g.expiry_estimate);
      if (start && end && end > start) pct = Math.max(0, Math.min(100, (Date.now() - start) / (end - start) * 100));
      var col = rem == null ? 'var(--ink-3)' : rem <= 7 ? 'var(--bad)' : rem <= 21 ? 'var(--warn)' : 'var(--brand)';
      var cls = rem == null ? '' : rem <= 7 ? ' soon' : rem <= 21 ? ' wk' : '';
      var remTxt = rem == null ? '<b>-</b> ' + esc(g.token_lifetime_days ? 'no lifetime known' : (g.note && /not expire|no published/i.test(g.note) ? 'does not expire while in use' : 'no published lifetime')) : rem < 0 ? '<b>' + (-rem) + ' d</b> past estimate' : '<b>' + rem + ' d</b> left of ~' + (g.token_lifetime_days || '?') + ' d';
      var who = obsv ? ' <span class="cx-est" title="' + esc((g.observed || {}).reauth_evidence || 'seen by the probe') + '">observed</span>' : (g.reauth_by ? ' by ' + esc(g.reauth_by) : '');
      h += '<div class="cx-hz-row pad"><div class="nm"><span class="cx-mono" style="width:26px;height:26px;font-size:10px;border-radius:7px">' + esc(mono(ds.label)) + '</span><span>' + esc(ds.label) + '<br><small>re-authed ' + fmtDay(ra) + who + '</small></span></div>'
        + '<div class="tr"><div class="fl" style="width:' + pct.toFixed(1) + '%;background:' + col + ';opacity:.85"></div><div class="now" style="left:' + pct.toFixed(1) + '%"></div><span class="tk" style="left:0;transform:none">' + fmtDay(ra) + '</span><span class="tk" style="left:100%;transform:translateX(-100%)">' + (g.expiry_estimate ? '~' + fmtDay(g.expiry_estimate) : '') + '</span></div>'
        + '<div class="rem' + cls + '">' + remTxt + '</div></div>';
    });
    return h + '</div></div>';
  }

  // Rows that are individually uninteresting collapse into ONE line per group: the LinkedIn
  // "Transmission accounts we hold no mapping for" (23 of them) and the GA4 "granted in Windsor
  // but not pulled by the scheduled loader" list (20). They stay in the data - a grant change
  // in either group is still visible in the group line - they just stop burying the client rows.
  function collapseGroups(ds, rows) {
    var out = [], groups = {};
    rows.forEach(function (a) {
      var g = a.extra ? 'extra' : (a.expected === 'unconfigured' ? 'unconfigured' : null);
      if (!g || S.expanded[ds.ds + ':' + g]) { out.push(a); return; }
      (groups[g] = groups[g] || []).push(a);
    });
    Object.keys(groups).forEach(function (g) {
      var list = groups[g]; var st = {}; list.forEach(function (a) { st[a.state] = (st[a.state] || 0) + 1; });
      var worst = Object.keys(st).sort(function (x, y) { return SEV[x] - SEV[y]; })[0];
      var parts = Object.keys(st).sort(function (x, y) { return SEV[x] - SEV[y]; }).map(function (k) { return st[k] + ' ' + stateOf(k).lbl.toLowerCase(); });
      out.push({
        _group: g, _n: list.length, id: '', state: worst === 'not_granted' ? 'idle' : worst,
        client_label: g === 'extra' ? list.length + ' Transmission accounts we hold no client mapping for' : list.length + ' accounts granted in Windsor that the scheduled loader does not pull',
        name: parts.join(', '), since: null,
        data: {}, fix: g === 'extra'
          ? 'Configured on the loader, mapped to no client. None feeds a dashboard. Click to expand - a change here matters only when one of them becomes ours.'
          : 'The loader is pinned to a shortlist on purpose (GA4_ACCOUNTS). These are the laptop-list properties. Click to expand.'
      });
    });
    return out;
  }

  function dsSection(ds) {
    var rows = (ds.accounts || []).filter(function (a) { return passes(ds, a); }).sort(function (a, b) { return (SEV[a.state] - SEV[b.state]) || String(a.client_label || a.client).localeCompare(String(b.client_label || b.client)); });
    rows = collapseGroups(ds, rows);
    if (!rows.length) return '';
    var st = ds.connector || {};
    var cs = st.state || 'ok'; var v = cs === 'ok' ? STATE.ok : cs === 'denied' ? STATE.not_granted : STATE.error;
    // granted = Windsor actually answered for it (or holds it unconfigured) - NOT "not red", which
    // would count an offboarded client's dead grant as granted because its row is idle
    var granted = (ds.accounts || []).filter(function (a) { return (a.probe && a.probe.verdict === 'granted') || a.expected === 'unconfigured'; }).length;
    var reauthUrl = ds.reauth_url || ('https://onboard.windsor.ai?datasource=' + encodeURIComponent(ds.ds));
    var h = '<div class="cx-sec"><div class="cx-ds"><div class="cx-ds-h">'
      + '<div class="cx-mono">' + esc(mono(ds.label)) + '</div>'
      + '<div><div class="cx-ds-nm">' + esc(ds.label) + '</div><div class="cx-ds-sub">'
      + '<span><b>' + granted + '</b> of ' + (ds.accounts || []).length + ' accounts granted</span>'
      + (ds.loader_job ? '<span>loader <b>' + esc(ds.loader_job) + '</b>' + (ds.schedule ? ' · ' + esc(ds.schedule) : '') + '</span>' : '')
      + (st.latency_ms != null ? '<span>connector answered in <b>' + (st.latency_ms / 1000).toFixed(1) + ' s</b></span>' : '')
      + (ds.table ? '<span>lands in <b>' + esc(ds.table) + '</b></span>' : '')
      + '</div></div>'
      + '<div class="cx-ds-r"><span class="cx-verd" style="background:' + v.soft + ';color:' + v.c + '"><span class="cx-dot" style="background:' + v.c + ';width:7px;height:7px"></span>' + (cs === 'ok' ? 'Connector up' : cs === 'denied' ? 'Connector denied' : 'Connector error') + '</span>'
      + '<a class="cx-link" href="' + esc(reauthUrl) + '" target="_blank" rel="noopener">Re-grant in Windsor ↗</a></div>'
      + '</div>';
    if (st.note && cs !== 'ok') h += '<div class="cx-note" style="padding-top:12px"><span class="nb" style="background:' + v.c + '"></span><span>' + esc(st.note) + '</span></div>';
    h += '<div class="cx-tbl-wrap"><table class="cx"><thead><tr><th>Client</th><th>Account</th><th>State</th><th class="r">Newest data</th><th class="r">Behind</th><th>Since</th><th>What to do</th></tr></thead><tbody>';
    rows.forEach(function (a) {
      var sv = stateOf(a.state); var d = a.data || {};
      if (a._group) {
        h += '<tr class="s-idle cx-grp" data-grp="' + esc(ds.ds + ':' + a._group) + '" style="cursor:pointer" title="Expand">'
          + '<td><div class="cx-cl" style="color:var(--ink-2)"><span class="cd" style="background:var(--ink-3)"></span>' + esc(a.client_label) + '</div></td>'
          + '<td class="cx-acct">' + esc(a.name) + '</td>'
          + '<td><span class="cx-verd" style="background:' + sv.soft + ';color:' + sv.c + '"><span class="cx-dot" style="background:' + sv.c + ';width:7px;height:7px"></span>' + (a.state === 'idle' ? 'Collapsed' : sv.lbl) + '</span></td>'
          + '<td class="r">-</td><td class="r">-</td><td>-</td><td class="cx-fix">' + esc(a.fix) + '</td></tr>';
        return;
      }
      var behind = d.days_behind; var bcls = behind == null ? '' : behind <= 1 ? ' b0' : behind <= 3 ? ' b1' : ' b2';
      h += '<tr class="s-' + esc(a.state) + '">'
        + '<td><div class="cx-cl"><span class="cd" style="background:' + clientColor(a.client_label || a.client) + '"></span>' + esc(a.client_label || a.client || 'unmapped') + '</div></td>'
        + '<td class="cx-acct">' + esc(a.name || '') + (a.id ? '<code>' + esc(a.id) + '</code>' : '') + '</td>'
        + '<td><span class="cx-verd" style="background:' + sv.soft + ';color:' + sv.c + '"><span class="cx-dot" style="background:' + sv.c + ';width:7px;height:7px"></span>' + sv.lbl + '</span></td>'
        + '<td class="r cx-day">' + fmtDay(d.newest_day) + (d.sibling_newest_day && d.sibling_newest_day !== d.newest_day ? '<div style="font-size:10.5px;color:var(--ink-3)">others on this connector: ' + fmtDay(d.sibling_newest_day) + '</div>' : '') + '</td>'
        + '<td class="r"><span class="cx-behind' + bcls + '">' + (behind == null ? '-' : behind === 0 ? 'current' : behind + ' d') + '</span></td>'
        + '<td class="cx-day">' + (a.since ? fmtDay(a.since) + (a.since_days != null ? '<div style="font-size:10.5px;color:var(--ink-3)">' + a.since_days + ' d in this state</div>' : '') : '-') + '</td>'
        + '<td class="cx-fix">' + (a.fix ? esc(a.fix) : sv.d) + '</td>'
        + '</tr>';
    });
    return h + '</tbody></table></div></div></div>';
  }

  function alertLog(doc) {
    var al = (doc && doc.alerts) || {}; var hist = al.history || [];
    var h = '<div class="cx-card"><div class="cx-card-h"><h3>Alerts sent</h3><span class="meta">' + (al.enabled ? 'to ' + esc((al.recipients || []).join(', ')) : 'email not configured - alerts are logged only') + '</span></div>'
      + '<div class="cx-card-sub">One email per state change (an account going frozen, not granted or back to healthy), plus a morning digest while anything is still red. Never one per probe, so a long outage is one email and one reminder a day, not twenty-four.</div>';
    if (!hist.length) h += '<div class="cx-empty">No alerts have been sent yet.</div>';
    else {
      h += '<div class="cx-log">';
      hist.slice().reverse().slice(0, 12).forEach(function (e) {
        h += '<div class="cx-lrow"><span class="when">' + esc(fmtWhen(e.sent_at)) + '</span><span class="subj">' + esc(e.subject) + (e.sent === false ? ' <span class="cx-est" style="color:var(--warn);border-color:var(--warn)">not sent</span>' : '') + '</span><span class="to">' + esc((e.to || []).join(', ')) + '</span></div>';
      });
      h += '</div>';
    }
    return h + '</div>';
  }

  function never(mount) {
    mount.innerHTML = hero(null) + '<div class="cx-card cx-never"><h3>The probe has never run</h3><p>windsor_connections.json is not in the status bucket yet. Deploy and run the probe job once and this tab fills itself in; from then on it refreshes hourly.</p><code>ingest\\windsor_data_pull\\connections\\deploy_job_connections.ps1 -Run</code></div>';
    wire(mount);
  }

  function render(mount) {
    if (!S.mounted) { var st = document.createElement('style'); st.id = 'connections-css'; st.textContent = CSS; document.head.appendChild(st); S.mounted = true; }
    if (!S.doc && !S.err) {
      // first paint (or a warm() still in flight from boot): wait on the ONE load, then repaint
      (S.pending || load()).then(function () { render(mount); });
      mount.innerHTML = hero(null) + '<div class="cx-empty">Loading connector health…</div>';
      return;
    }
    if (S.err && !S.doc) { mount.innerHTML = hero(null) + '<div class="cx-card cx-never"><h3>Could not load connector health</h3><p>' + esc(S.err) + '</p></div>'; wire(mount); return; }
    var doc = S.doc;
    if (!doc || doc.never_run) return never(mount);
    var all = accounts(doc); var shown = all.filter(function (x) { return passes(x.ds, x.a); });
    var h = hero(doc) + summary(doc) + filterBar(doc, shown.length, all.length) + horizon(doc);
    var secs = (doc.datasources || []).map(dsSection).join('');
    h += secs || '<div class="cx-card"><div class="cx-empty">No accounts match the current filters.</div></div>';
    h += alertLog(doc);
    if (doc.notes && doc.notes.length) { h += '<div class="cx-card" style="padding-top:6px">' + doc.notes.map(function (n) { return '<div class="cx-note" style="padding-top:10px"><span class="nb"></span><span>' + esc(n) + '</span></div>'; }).join('') + '</div>'; }
    mount.innerHTML = h;
    wire(mount);
  }

  function wire(mount) {
    var pb = mount.querySelector('#cxProbe'); if (pb) pb.addEventListener('click', function () { probe(mount, pb); });
    mount.querySelectorAll('.cx-scard[data-state]').forEach(function (b) { b.addEventListener('click', function () { S.filter.state = S.filter.state === b.dataset.state ? null : b.dataset.state; render(mount); }); });
    mount.querySelectorAll('.cx-pill[data-ds]').forEach(function (b) { b.addEventListener('click', function () { S.filter.ds = b.dataset.ds || null; render(mount); }); });
    var idle = mount.querySelector('#cxIdle'); if (idle) idle.addEventListener('click', function () { S.filter.showIdle = !S.filter.showIdle; render(mount); });
    var cl = mount.querySelector('#cxClear'); if (cl) cl.addEventListener('click', function () { S.filter = { state: null, ds: null, q: '', showIdle: false }; S.expanded = {}; render(mount); });
    mount.querySelectorAll('tr.cx-grp').forEach(function (r) { r.addEventListener('click', function () { S.expanded[r.dataset.grp] = true; render(mount); }); });
    var q = mount.querySelector('#cxQ'); if (q) {
      q.addEventListener('input', function () { S.filter.q = q.value.toLowerCase().trim(); var pos = q.selectionStart; render(mount); var nq = mount.querySelector('#cxQ'); if (nq) { nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { } } });
    }
  }

  function load() {
    if (S.pending) return S.pending;
    S.loading = true; S.err = null;
    S.pending = fetch(API, { headers: { 'Accept': 'application/json' }, cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) { S.doc = j; S.fetchedAt = Date.now(); paintNavBadge(j); })
      .catch(function (e) { S.err = e.message || String(e); })
      .then(function () { S.loading = false; S.pending = null; });
    return S.pending;
  }

  function probe(mount, btn) {
    if (S.probing) return;
    S.probing = true; btn.disabled = true; btn.classList.add('busy'); btn.querySelector('.sl').textContent = 'Probing';
    var before = S.doc && S.doc.generated_at;
    fetch(API + '/probe', { method: 'POST', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        if (!x.ok) throw new Error((x.j && x.j.error) || 'probe request failed');
        toast('Probe started - results land in about a minute', 'success');
        // poll until generated_at moves (max ~3 min), then re-render
        var tries = 0; (function poll() {
          setTimeout(function () {
            load().then(function () {
              if (S.doc && S.doc.generated_at !== before) { S.probing = false; render(mount); toast('Connector health refreshed', 'success'); }
              else if (++tries < 18) poll();
              else { S.probing = false; render(mount); toast('Probe is taking longer than usual - the tab will pick it up on its next refresh', 'error'); }
            });
          }, 10000);
        })();
      })
      .catch(function (e) { S.probing = false; render(mount); toast('Could not start the probe: ' + e.message, 'error'); });
  }

  function toast(msg, kind) { try { if (window.BrainToast && window.BrainToast.show) return window.BrainToast.show(msg, kind); } catch (e) { } try { console.log('[connections] ' + msg); } catch (e) { } }

  // background refresh while the tab is open (the probe is hourly; 5 min keeps "last probe" honest)
  function startTimer(mount) { if (S.timer) return; S.timer = setInterval(function () { if (document.getElementById('view-connections') && document.getElementById('view-connections').style.display !== 'none') load().then(function () { render(mount); }); }, 5 * 60000); if (S.timer.unref) S.timer.unref(); }

  window.Connections = {
    render: function (mount) { startTimer(mount); render(mount); },
    reload: function (mount) { S.doc = null; render(mount); },
    // called at boot by the-grid.html so the nav badge is right before the tab is ever opened
    warm: function () { if (!S.doc && !S.loading) load(); },
    _state: S
  };
})();
