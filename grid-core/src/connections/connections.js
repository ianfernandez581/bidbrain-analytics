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
    openFeed: {},       // 'f:<ds>' -> true when a feed row is expanded
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
    // ===== page shell: the mockup's measure, centred, with real side padding =====
    // The tab mounts into #connectionsMount, which is the ONLY child of #view-connections.
    // Putting the column layout on the outer div gave the gap one child to space, so no gap
    // ever appeared between the sections. The measure lives outside, the stacking inside.
    '#view-connections{max-width:1340px;margin:0 auto;padding:22px 30px 72px}',
    '#connectionsMount{display:flex;flex-direction:column;gap:16px}',
    '@media(max-width:900px){#view-connections{padding:18px 16px 60px}}',
    '#view-connections .cx-num{font-variant-numeric:tabular-nums}',
    // ===== header =====
    '#view-connections .cx-head{display:flex;gap:18px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap}',
    '#view-connections .cx-eyebrow{font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3)}',
    '#view-connections .cx-head h2{font-family:"Space Grotesk";font-size:24px;font-weight:600;letter-spacing:-.2px;margin:3px 0 0;color:var(--ink)}',
    '#view-connections .cx-dek{font-size:12.5px;color:var(--ink-2);max-width:70ch;margin-top:6px;line-height:1.5}',
    '#view-connections .cx-probebar{display:flex;align-items:center;gap:11px;flex-wrap:wrap}',
    '#view-connections .cx-mail{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;padding:4px 10px;border-radius:20px;background:var(--ok-soft);color:var(--ok)}',
    '#view-connections .cx-mail.off{background:var(--warn-soft);color:var(--warn)}',
    '#view-connections .cx-mail .md{width:7px;height:7px;border-radius:50%;background:currentColor}',
    '#view-connections .cx-probed{font-size:11px;color:var(--ink-3);text-align:right;line-height:1.4}',
    '#view-connections .cx-sync{appearance:none;font:inherit;font-size:12px;font-weight:600;cursor:pointer;padding:8px 15px;border-radius:9px;border:1px solid var(--brand);background:var(--brand);color:var(--pill-fg);display:inline-flex;align-items:center;gap:7px}',
    '#view-connections .cx-sync[disabled]{opacity:.6;cursor:default}',
    '#view-connections .cx-sync .sp{display:none;width:11px;height:11px;border-radius:50%;border:2px solid currentColor;border-top-color:transparent;animation:cxspin .7s linear infinite}',
    '#view-connections .cx-sync[disabled] .sp{display:inline-block}',
    '@keyframes cxspin{to{transform:rotate(360deg)}}',
    // ===== tiles =====
    '#view-connections .cx-tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:13px}',
    '#view-connections .cx-scard{position:relative;text-align:left;font:inherit;cursor:pointer;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:15px 16px 17px;overflow:hidden}',
    '#view-connections .cx-scard.static{cursor:default}',
    '#view-connections .cx-scard .base{position:absolute;left:0;right:0;bottom:0;height:3px;opacity:.9}',
    '#view-connections .cx-scard .n{font-family:"Space Grotesk";font-size:27px;font-weight:600;line-height:1.02;font-variant-numeric:tabular-nums;color:var(--ink)}',
    '#view-connections .cx-scard .l{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600;margin-top:4px}',
    '#view-connections .cx-scard .s{font-size:10.5px;color:var(--ink-3);line-height:1.4;margin-top:4px}',
    '#view-connections .cx-scard.zero .n{color:var(--ink-3)}',
    '#view-connections .cx-scard.zero .base{opacity:.35}',
    '#view-connections .cx-scard[aria-pressed="true"]{border-color:var(--brand)}',
    '#view-connections .cx-est{font-size:8.5px;font-weight:700;letter-spacing:.07em;padding:2px 5px;border-radius:4px;background:var(--grp);color:var(--ink-3);margin-left:5px}',
    '#view-connections .cx-tilefoot{display:flex;flex-wrap:wrap;gap:4px 20px;font-size:11.5px;color:var(--ink-3);padding:0 3px;margin-top:-7px}',
    '#view-connections .cx-tilefoot b{color:var(--ink-2);font-weight:600;font-variant-numeric:tabular-nums}',
    '@media(max-width:1100px){#view-connections .cx-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}',
    '@media(max-width:560px){#view-connections .cx-tiles{grid-template-columns:1fr}}',
    // ===== problem cards =====
    '#view-connections .cx-prob{display:grid;grid-template-columns:4px 1fr;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}',
    '#view-connections .cx-prob .pstripe{background:var(--bad)}',
    '#view-connections .cx-prob.muted .pstripe{background:var(--ink-3)}',
    '#view-connections .cx-prob .pin{min-width:0}',
    '#view-connections .cx-prob .ph{padding:15px 20px 0}',
    '#view-connections .cx-prob .pk{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}',
    '#view-connections .cx-prob .pmute{font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);background:var(--line-2);padding:3px 8px;border-radius:5px}',
    '#view-connections .cx-prob .plede{font-family:"Space Grotesk";font-size:16.5px;font-weight:600;line-height:1.3;letter-spacing:-.2px;color:var(--ink);text-wrap:balance}',
    '#view-connections .cx-prob.muted .plede{color:var(--ink-2)}',
    '#view-connections .cx-prob .psub{font-size:11.5px;color:var(--ink-3);margin-top:4px}',
    '#view-connections .cx-prob .pstrip{display:flex;flex-wrap:wrap;gap:0 24px;padding:13px 20px 0}',
    '#view-connections .cx-prob .pm{display:flex;flex-direction:column;gap:1px;padding:2px 0}',
    '#view-connections .cx-prob .pl{font-size:9.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3)}',
    '#view-connections .cx-prob .pv{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--ink)}',
    '#view-connections .cx-prob .pv.dim{font-weight:500;font-size:12.5px;color:var(--ink-3)}',
    '#view-connections .cx-prob .ptbl{padding:12px 20px 0;display:flex;flex-direction:column;gap:3px}',
    '#view-connections .cx-prob .ptbl code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:var(--ink-2);background:var(--grp);border-radius:5px;padding:3px 7px;align-self:flex-start;overflow-wrap:anywhere}',
    '#view-connections .cx-prob .ptodo{margin-top:14px;padding:14px 20px;border-top:1px solid var(--line-2);background:var(--panel-2)}',
    '#view-connections .cx-prob .pl2{font-family:"Space Grotesk";font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-2);margin-bottom:5px}',
    '#view-connections .cx-prob .ptodo p{margin:0;font-size:12.5px;color:var(--ink-2);line-height:1.55}',
    '#view-connections .cx-prob .pgo{display:inline-block;margin-top:10px;font-size:12px;font-weight:600;color:var(--brand-ink);text-decoration:none;border-bottom:1px solid var(--brand);padding-bottom:1px}',
    '#view-connections .cx-prob .pgo:hover{color:var(--ink);border-bottom-color:var(--ink)}',
    '@media(min-width:1080px){#view-connections .cx-prob .pin{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,35%);grid-template-areas:"h t" "s t" "b t";align-content:start}#view-connections .cx-prob .ph{grid-area:h}#view-connections .cx-prob .pstrip{grid-area:s}#view-connections .cx-prob .ptbl{grid-area:b;padding-bottom:17px}#view-connections .cx-prob .ptodo{grid-area:t;margin-top:0;border-top:0;border-left:1px solid var(--line-2);display:flex;flex-direction:column;justify-content:center;padding:18px 22px}#view-connections .cx-prob .plede{max-width:33ch}#view-connections .cx-prob .ptodo p{max-width:44ch}}',
    // ===== cards, chips =====
    '#view-connections .cx-card{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}',
    '#view-connections .cx-card-h{padding:15px 18px 0;display:flex;align-items:baseline;justify-content:space-between;gap:12px}',
    '#view-connections .cx-card-h h3{font-family:"Space Grotesk";font-size:15px;font-weight:600;margin:0;color:var(--ink)}',
    '#view-connections .cx-card-h .hint{font-size:11px;color:var(--ink-3)}',
    '#view-connections .cx-card-sub{padding:4px 18px 0;font-size:12px;color:var(--ink-2);max-width:84ch;line-height:1.5}',
    '#view-connections .cx-foot{padding:11px 18px;color:var(--ink-3);font-size:11px;border-top:1px solid var(--line-2)}',
    '#view-connections .cx-chipbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:12px 18px 0}',
    '#view-connections .cx-pill{appearance:none;font:inherit;font-size:11.5px;font-weight:600;cursor:pointer;padding:5px 11px;border-radius:20px;border:1px solid var(--line);background:var(--panel-2);color:var(--ink-2)}',
    '#view-connections .cx-pill:hover{color:var(--ink);border-color:var(--brand);background:var(--panel)}',
    '#view-connections .cx-pill[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);color:var(--pill-fg)}',
    '#view-connections .cx-chipbar .sep{flex:1 1 auto}',
    '#view-connections .cx-q{position:relative}',
    '#view-connections .cx-q input{font:inherit;font-size:12px;color:var(--ink);background:var(--panel-2);border:1px solid var(--line);border-radius:9px;padding:6px 10px 6px 28px;width:212px}',
    '#view-connections .cx-q input:focus{border-color:var(--brand);outline:none;box-shadow:0 0 0 3px var(--brand-soft)}',
    '#view-connections .cx-q svg{position:absolute;left:9px;top:8px;color:var(--ink-3)}',
    // ===== feed rollup =====
    '#view-connections .cx-tbl-wrap{overflow-x:auto;margin-top:10px}',
    '#view-connections table.cx{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px}',
    '#view-connections table.cx thead th{text-align:left;font-weight:600;font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);padding:8px 14px;border-bottom:1px solid var(--line);white-space:nowrap}',
    '#view-connections table.cx thead th.r{text-align:right}',
    '#view-connections table.cx tbody td{padding:10px 14px;border-bottom:1px solid var(--line-2);vertical-align:middle}',
    '#view-connections table.cx tbody td.r{text-align:right}',
    '#view-connections tr.cx-frow{cursor:pointer}',
    '#view-connections tr.cx-frow:hover td{background:var(--panel-2)}',
    '#view-connections tr.cx-frow:focus-visible{outline:2px solid var(--brand);outline-offset:-2px}',
    '#view-connections tr.cx-frow .fn{display:flex;align-items:center;gap:9px;font-weight:600;color:var(--ink)}',
    '#view-connections tr.cx-frow .fcar{color:var(--ink-3);font-size:9px;width:9px;display:inline-block;transition:transform .13s ease,color .13s ease}',
    '#view-connections tr.cx-frow.open .fcar{transform:rotate(90deg)}',
    '#view-connections tr.cx-frow:hover .fcar{color:var(--brand)}',
    '#view-connections .cx-av{width:24px;height:24px;border-radius:7px;background:var(--grp);color:var(--ink-2);font-family:"Space Grotesk";font-size:9.5px;font-weight:700;display:grid;place-items:center;flex:0 0 auto;transition:background .13s ease,color .13s ease}',
    '#view-connections tr.cx-frow:hover .cx-av{background:var(--brand-soft);color:var(--brand-ink)}',
    '#view-connections tr.cx-frow .fsub{display:block;margin-left:42px;font-size:10.5px;color:var(--ink-3);font-weight:500}',
    '#view-connections .fh{display:flex;align-items:center;gap:9px;min-width:148px;max-width:210px}',
    '#view-connections .fbar{flex:1;height:6px;border-radius:3px;background:var(--grp);overflow:hidden;min-width:66px}',
    '#view-connections .fbar i{display:block;height:100%;border-radius:3px;background:var(--ok)}',
    '#view-connections .fbar.bad i{background:var(--bad)}',
    '#view-connections .ft{font-size:11px;color:var(--ink-3);font-variant-numeric:tabular-nums;white-space:nowrap}',
    '#view-connections .fdim{font-size:11px;color:var(--ink-3)}',
    '#view-connections .fsub2{display:block;font-size:10.5px;color:var(--ink-3);font-variant-numeric:tabular-nums}',
    // ===== expanded feed: loader line + account table =====
    '#view-connections tr.cx-fdet>td{padding:0;background:var(--panel-2);border-bottom:1px solid var(--line)}',
    '#view-connections .cx-dmeta{display:flex;flex-wrap:wrap;gap:5px 20px;font-size:11.5px;color:var(--ink-2);padding:11px 16px 11px 47px;border-bottom:1px solid var(--line-2);align-items:center}',
    '#view-connections .cx-dmeta b{color:var(--ink);font-weight:600}',
    '#view-connections .cx-verd{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:600;padding:2.5px 9px;border-radius:20px;white-space:nowrap}',
    '#view-connections .cx-dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto}',
    '#view-connections .cx-link{font-size:11.5px;font-weight:600;color:var(--brand-ink);text-decoration:none;border-bottom:1px solid transparent}',
    '#view-connections .cx-link:hover{border-bottom-color:var(--brand)}',
    '#view-connections table.atbl{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}',
    '#view-connections table.atbl thead th{font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);padding:8px 14px;border-bottom:1px solid var(--line-2);background:var(--panel-2);text-align:left;white-space:nowrap}',
    '#view-connections table.atbl thead th.r{text-align:right}',
    '#view-connections table.atbl tbody td{padding:10px 14px;border-bottom:1px solid var(--line-2);vertical-align:top;background:var(--panel);transition:background .12s ease}',
    '#view-connections table.atbl tbody tr:last-child td{border-bottom:0}',
    '#view-connections table.atbl tbody tr:hover td{background:var(--panel-2)}',
    '#view-connections table.atbl tbody td.r{text-align:right}',
    '#view-connections table.atbl tbody tr td:first-child{box-shadow:inset 3px 0 0 var(--rt,transparent);padding-left:20px}',
    '#view-connections table.atbl tr.s-not_granted{--rt:var(--bad)}',
    '#view-connections table.atbl tr.s-frozen{--rt:var(--warn)}',
    '#view-connections table.atbl tr.s-error{--rt:var(--tx)}',
    '#view-connections table.atbl tr.s-quiet{--rt:#7E93AD}',
    '#view-connections table.atbl tr.s-ok{--rt:var(--ok)}',
    '#view-connections table.atbl tr.s-idle{--rt:var(--line)}',
    '#view-connections .acl{display:flex;align-items:center;gap:8px;font-weight:600;color:var(--ink);white-space:nowrap}',
    '#view-connections .acl .cd{width:8px;height:8px;border-radius:50%;flex:0 0 auto}',
    '#view-connections .an{color:var(--ink);font-weight:500}',
    '#view-connections .aid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10.5px;color:var(--ink-3);margin-left:5px}',
    '#view-connections .asub{font-size:10.5px;color:var(--ink-3);margin-top:2px}',
    '#view-connections .aval{font-variant-numeric:tabular-nums;white-space:nowrap}',
    '#view-connections .acur{color:var(--ok);font-weight:600}',
    '#view-connections .adim{color:var(--ink-3)}',
    '#view-connections .afix{color:var(--ink-2);line-height:1.45;min-width:230px;white-space:normal}',
    '#view-connections .afix.plain{color:var(--ink-3)}',
    '#view-connections .cx-silent{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3)}',
    // ===== grant horizon =====
    '#view-connections .cx-hzwrap{padding:13px 18px 6px;display:flex;flex-direction:column;gap:15px}',
    '#view-connections .cx-hz{display:grid;grid-template-columns:210px 1fr 128px;gap:16px;align-items:center;padding:7px 10px;margin:-7px -10px;border-radius:10px;transition:background .13s ease}',
    '#view-connections .cx-hz:hover{background:var(--panel-2)}',
    '#view-connections .cx-hz .nm{display:flex;align-items:center;gap:9px;min-width:0}',
    '#view-connections .cx-hz .nm .t{min-width:0}',
    '#view-connections .cx-hz .nm b{font-size:12.5px;font-weight:600;display:block;color:var(--ink)}',
    '#view-connections .cx-hz .nm small{font-size:10.5px;color:var(--ink-3)}',
    '#view-connections .cx-hz .trk{position:relative}',
    '#view-connections .cx-hz .bar{position:relative;height:9px;border-radius:5px;background:var(--grp);overflow:hidden;transition:box-shadow .13s ease}',
    '#view-connections .cx-hz:hover .bar{box-shadow:0 0 0 1px color-mix(in oklab,var(--brand) 25%,transparent)}',
    '#view-connections .cx-hz .bar i{position:absolute;inset:0 auto 0 0;border-radius:5px;background:var(--brand)}',
    '#view-connections .cx-hz .now{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink);opacity:.55}',
    '#view-connections .cx-hz .ends{display:flex;justify-content:space-between;font-size:10px;color:var(--ink-3);margin-top:4px;font-variant-numeric:tabular-nums}',
    '#view-connections .cx-hz .rem{font-size:12px;text-align:right;font-variant-numeric:tabular-nums;color:var(--ink-2)}',
    '#view-connections .cx-hz .rem b{font-family:"Space Grotesk";font-size:14px;font-weight:600;color:var(--ink);display:block}',
    '#view-connections .cx-hz .none{font-size:11.5px;color:var(--ink-3)}',
    '@media(max-width:900px){#view-connections .cx-hz{grid-template-columns:1fr;gap:6px}#view-connections .cx-hz .rem{text-align:left}}',
    // ===== states / empty =====
    '#view-connections .cx-empty{padding:26px 18px;text-align:center;color:var(--ink-3);font-size:12.5px}',
    '#view-connections .cx-never{padding:26px 22px;text-align:center}',
    '#view-connections .cx-never h3{font-family:"Space Grotesk";font-size:16px;font-weight:600;margin:0 0 6px;color:var(--ink)}',
    '#view-connections .cx-never p{margin:0 auto;max-width:62ch;font-size:12.5px;color:var(--ink-2);line-height:1.55}',
    '#view-connections .cx-never code{display:inline-block;margin-top:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;background:var(--grp);color:var(--ink-2);padding:5px 9px;border-radius:6px}',
    // ===== hover: geometry via translate only. The caret and chevrons already use
    // transform:rotate(), and the transform shorthand would replace it (md/AGENTS.md).
    '#view-connections .cx-scard,#view-connections .cx-prob{transition:translate .14s ease,box-shadow .14s ease,border-color .14s ease}',
    '#view-connections .cx-scard:hover{translate:0 -1px}',
    '#view-connections .cx-prob:hover{translate:0 -1px;box-shadow:0 2px 4px rgba(0,0,0,.05),0 16px 34px -20px rgba(0,0,0,.35)}',
    '#view-connections .cx-sync{transition:translate .14s ease,filter .13s ease,box-shadow .14s ease}',
    '#view-connections .cx-sync:hover:not([disabled]){translate:0 -1px;filter:brightness(1.06)}',
    '#view-connections .cx-sync:active:not([disabled]){translate:0 0}',
    '#view-connections .cx-pill,#view-connections .cx-link,#view-connections .cx-q input{transition:color .13s ease,background .13s ease,border-color .13s ease,box-shadow .13s ease}',
    '#view-connections .cx-prob .ptbl code{transition:background .13s ease,color .13s ease}',
    '#view-connections .cx-prob .ptbl code:hover{background:color-mix(in oklab,var(--brand) 12%,var(--grp));color:var(--ink)}',
    '#view-connections .cx-pill:focus-visible,#view-connections .cx-scard:focus-visible,#view-connections .cx-sync:focus-visible,#view-connections .cx-prob .pgo:focus-visible{outline:2px solid var(--brand);outline-offset:2px}',
    '@media(prefers-reduced-motion:reduce){#view-connections *{transition:none!important;animation:none!important}#view-connections .cx-scard:hover,#view-connections .cx-prob:hover,#view-connections .cx-sync:hover{translate:none!important}}'
  ].join('\n');

  var RED = { not_granted: 1, frozen: 1, error: 1 };

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmtDay(d) { if (!d) return '-'; var t = new Date(d + 'T00:00:00Z'); if (isNaN(t)) return esc(d); return t.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }); }
  function fmtDayY(d) { if (!d) return '-'; var t = new Date(d + 'T00:00:00Z'); if (isNaN(t)) return esc(d); return t.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }); }
  function fmtWhen(iso) { if (!iso) return '-'; var t = new Date(iso); if (isNaN(t)) return esc(iso); return t.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
  function ago(iso) {
    if (!iso) return 'never';
    var m = Math.round((Date.now() - new Date(iso)) / 60000);
    if (isNaN(m)) return 'unknown';
    if (m < 1) return 'just now';
    if (m < 60) return m + ' min ago';
    var h = Math.round(m / 60); if (h < 24) return h + ' h ago';
    return Math.round(h / 24) + ' d ago';
  }
  function daysUntil(day) { if (!day) return null; var t = new Date(day + 'T00:00:00Z'); if (isNaN(t)) return null; return Math.round((t - Date.now()) / 86400000); }
  function mono(label) { var w = String(label || '?').replace(/[^A-Za-z0-9 ]/g, ' ').trim().split(/\s+/); return (w.length > 1 ? w[0][0] + w[1][0] : (w[0] || '?').slice(0, 2)).toUpperCase(); }
  function clientColor(name) { try { if (name && window.BrainColors && window.BrainColors.getClientColor) return window.BrainColors.getClientColor(String(name).toLowerCase()).fg; } catch (e) { } return 'var(--ink-3)'; }
  function stateOf(s) { return STATE[s] || STATE.error; }

  function allAccounts(doc) {
    var out = [];
    ((doc && doc.datasources) || []).forEach(function (ds) {
      (ds.accounts || []).forEach(function (a) { out.push({ ds: ds, a: a }); });
    });
    return out;
  }
  function counts(doc) {
    var c = { ok: 0, frozen: 0, quiet: 0, not_granted: 0, error: 0, idle: 0, total: 0 };
    allAccounts(doc).forEach(function (x) { c[x.a.state] = (c[x.a.state] || 0) + 1; c.total++; });
    return c;
  }
  function passes(ds, a) {
    var f = S.filter;
    if (!f.showIdle && a.state === 'idle') return false;
    if (f.state && a.state !== f.state) return false;
    if (f.ds && ds.label !== f.ds) return false;
    if (f.q) {
      var hay = ((a.name || '') + ' ' + (a.id || '') + ' ' + (a.client_label || a.client || '') + ' ' + ds.label).toLowerCase();
      if (hay.indexOf(f.q) < 0) return false;
    }
    return true;
  }
  function redCount(doc) {
    return allAccounts(doc).filter(function (x) { return RED[x.a.state] && x.a.alerts; }).length;
  }
  function paintNavBadge(doc) {
    var b = document.getElementById('navConnBadge'); if (!b) return;
    var n = redCount(doc);
    b.textContent = n || ''; b.style.display = n ? '' : 'none';
  }
  function nextExpiry(doc) {
    var best = null;
    ((doc && doc.datasources) || []).forEach(function (ds) {
      var g = ds.grant || {}; if (!g.expiry_estimate) return;
      var d = daysUntil(g.expiry_estimate); if (d == null) return;
      if (!best || d < best.days) best = { days: d, label: ds.label, last_reauth: g.effective_reauth || g.last_reauth, by: g.reauth_by };
    });
    return best;
  }

  // ---------- header ----------
  function hero(doc) {
    var probed = doc && doc.generated_at;
    var alerts = (doc && doc.alerts) || {};
    var on = !!alerts.enabled;
    var to = (alerts.recipients || []).join(', ');
    return '<div class="cx-head"><div>'
      + '<div class="cx-eyebrow">Connections</div>'
      + '<h2>Windsor connections</h2>'
      + '<div class="cx-dek">Every account we ingest, checked hourly. A lapsed grant never fails a job, so each is watched on its own.</div>'
      + '</div><div class="cx-probebar">'
      + '<span class="cx-mail' + (on ? '' : ' off') + '" title="' + (on ? 'State changes are emailed to ' + esc(to) : 'Email alerts are not configured yet') + '"><span class="md"></span>Email alerts <b>' + (on ? 'on' : 'off') + '</b></span>'
      + '<div class="cx-probed">' + (probed ? 'Last probe <b>' + esc(ago(probed)) + '</b><br>' + esc(fmtWhen(probed)) + ' &middot; hourly' : 'Never probed')
      + (to ? '<br>' + esc(to) : '') + '</div>'
      + '<button class="cx-sync" id="cxProbe"' + (S.probing ? ' disabled' : '') + '><span class="sp"></span><span class="sl">' + (S.probing ? 'Probing' : 'Probe now') + '</span></button>'
      + '</div></div>';
  }

  // ---------- tiles ----------
  function tiles(doc) {
    var c = counts(doc);
    var h = '<div class="cx-tiles">';
    [['not_granted', c.not_granted], ['frozen', c.frozen], ['quiet', c.quiet], ['ok', c.ok]].forEach(function (p) {
      var k = p[0], n = p[1], v = STATE[k];
      var sub = v.d;
      if (k === 'not_granted') {
        var who = allAccounts(doc).filter(function (x) { return RED[x.a.state] && x.a.alerts; })
          .map(function (x) { return x.a.client_label || x.a.client; }).filter(Boolean);
        var uniq = who.filter(function (w, i) { return who.indexOf(w) === i; });
        sub = (uniq.length ? esc(uniq.join(', ')) + '. ' : '') + v.d
          + (c.error ? ' &middot; plus ' + c.error + ' error' + (c.error === 1 ? '' : 's') : '');
      }
      h += '<button class="cx-scard' + (n ? '' : ' zero') + '" data-state="' + k + '" aria-pressed="' + (S.filter.state === k) + '">'
        + '<div class="base" style="background:' + v.c + '"></div>'
        + '<div class="n">' + n + '</div>'
        + '<div class="l" style="color:' + (n ? v.c : 'var(--ink-3)') + '"><span class="cx-dot" style="background:' + (n ? v.c : 'var(--ink-3)') + '"></span>' + v.lbl + '</div>'
        + '<div class="s">' + sub + '</div></button>';
    });
    var next = nextExpiry(doc);
    if (next) {
      var col = next.days <= 7 ? 'var(--bad)' : next.days <= 21 ? 'var(--warn)' : 'var(--brand)';
      h += '<div class="cx-scard static"><div class="base" style="background:' + col + '"></div>'
        + '<div class="n">' + (next.days < 0 ? 'overdue' : next.days + '<span style="font-size:12.5px;color:var(--ink-3);font-weight:500"> days</span>') + '</div>'
        + '<div class="l" style="color:' + col + '"><span class="cx-dot" style="background:' + col + '"></span>Next grant likely to expire<span class="cx-est" title="Windsor exposes no expiry date. This is the platform\'s typical token lifetime counted from the last re-authorisation recorded.">EST.</span></div>'
        + '<div class="s">' + esc(next.label) + ' &middot; re-authed ' + fmtDay(next.last_reauth) + (next.by ? ' by ' + esc(next.by) : '') + '</div></div>';
    } else {
      h += '<div class="cx-scard static zero"><div class="base" style="background:var(--line)"></div>'
        + '<div class="n">-</div><div class="l" style="color:var(--ink-3)"><span class="cx-dot" style="background:var(--ink-3)"></span>No expiry clock</div>'
        + '<div class="s">no re-authorisation dates recorded yet</div></div>';
    }
    h += '</div>';
    var muted = allAccounts(doc).filter(function (x) { return RED[x.a.state] && !x.a.alerts; }).length;
    h += '<div class="cx-tilefoot"><span><b>' + c.idle + '</b> idle by design</span>'
      + (muted ? '<span><b>' + muted + '</b> known and muted</span>' : '')
      + '<span><b>' + c.total + '</b> accounts watched across ' + ((doc.datasources || []).length) + ' feeds</span></div>';
    return h;
  }

  // ---------- problem cards ----------
  function ledeFor(ds, a) {
    var who = a.client_label || a.client || 'An unmapped account';
    var feed = String(ds.label || '').replace(/ \(.*\)$/, '');
    if (a.state === 'not_granted' && ds.source === 'dts') return who + "'s " + feed + ' has never delivered any data';
    if (a.state === 'not_granted') return 'Windsor no longer holds ' + who + "'s " + ds.label + ' account';
    if (a.state === 'frozen') return ds.label + ' is answering, but ' + who + "'s data has stopped arriving";
    if (a.state === 'error') return 'Windsor keeps erroring on ' + who + "'s " + ds.label + ' account';
    return who + ' needs attention on ' + ds.label;
  }
  function destFor(ds, a) {
    if (ds.source === 'dts') return { href: 'https://console.cloud.google.com/bigquery/transfers?project=bidbrain-analytics', text: 'Open BigQuery Data Transfers' };
    if (a.state === 'not_granted') return { href: ds.reauth_url || 'https://onboard.windsor.ai', text: 'Re-grant in Windsor' };
    return null;
  }
  function problems(doc) {
    var hits = allAccounts(doc).filter(function (x) { return RED[x.a.state]; });
    if (!hits.length) return '';
    hits.sort(function (x, y) { return (y.a.alerts - x.a.alerts) || (SEV[x.a.state] - SEV[y.a.state]); });
    return hits.map(function (it) {
      var ds = it.ds, a = it.a, act = !!a.alerts, go = destFor(ds, a), d = a.data || {};
      var age = d.days_behind == null ? null
        : (d.days_behind >= 14 ? Math.floor(d.days_behind / 7) + ' weeks' : d.days_behind + ' days');
      var sv = stateOf(a.state);
      return '<article class="cx-prob' + (act ? '' : ' muted') + '"><div class="pstripe"></div><div class="pin">'
        + '<div class="ph"><div class="pk"><span class="cx-verd" style="background:' + sv.soft + ';color:' + sv.c + '"><span class="cx-dot" style="background:' + sv.c + '"></span>' + sv.lbl + '</span>'
        + (act ? '' : '<span class="pmute">Known &middot; not alerting</span>') + '</div>'
        + '<div class="plede">' + esc(ledeFor(ds, a)) + '</div>'
        + '<div class="psub">' + esc(ds.label) + ' &middot; ' + esc(a.name || a.id) + '</div></div>'
        + '<div class="pstrip">'
        + '<div class="pm"><span class="pl">Newest data</span><span class="pv' + (d.newest_day ? '' : ' dim') + '">' + (d.newest_day ? esc(fmtDay(d.newest_day)) : 'none, ever') + '</span></div>'
        + '<div class="pm"><span class="pl">Behind</span><span class="pv' + (age ? '' : ' dim') + '">' + (age ? esc(age) : 'nothing to measure') + '</span></div>'
        + '<div class="pm"><span class="pl">Emails</span><span class="pv' + (act ? '' : ' dim') + '">' + (act ? 'on' : 'muted in config') + '</span></div>'
        + '</div>'
        + (d.table ? '<div class="ptbl"><span class="pl">Table measured</span><code>' + esc(d.table) + '</code></div>' : '')
        + '<div class="ptodo"><div class="pl2">What to do</div><p>' + esc(a.fix || a.why || '') + '</p>'
        + (go ? '<a class="pgo" href="' + esc(go.href) + '" target="_blank" rel="noopener">' + esc(go.text) + ' &rarr;</a>' : '')
        + '</div></div></article>';
    }).join('');
  }

  // ---------- account table inside an expanded feed ----------
  function acctRow(a) {
    var sv = stateOf(a.state), d = a.data || {};
    var newest = d.newest_day
      ? '<span class="aval">' + fmtDay(d.newest_day) + '</span>'
      : '<span class="aval adim">-</span>'
        + (d.sibling_newest_day ? '<div class="asub">others on this connector: ' + fmtDay(d.sibling_newest_day) + '</div>' : '');
    var behind = d.days_behind == null ? '<span class="aval adim">-</span>'
      : (d.days_behind <= 0 ? '<span class="aval acur">current</span>' : '<span class="aval">' + d.days_behind + ' d</span>');
    var fix = a.fix || a.why || (a.state === 'ok' ? 'granted and delivering' : '');
    return '<tr class="s-' + esc(a.state) + '">'
      + '<td><span class="acl"><span class="cd" style="background:' + clientColor(a.client_label || a.client) + '"></span>' + esc(a.client_label || a.client || 'Unmapped') + '</span></td>'
      + '<td><span class="an">' + esc(a.name || '') + '</span>' + (a.id ? '<span class="aid">' + esc(a.id) + '</span>' : '')
      + (a.alerts ? '' : '<div class="asub"><span class="cx-silent">silent</span></div>') + '</td>'
      + '<td><span class="cx-verd" style="background:' + sv.soft + ';color:' + sv.c + '"><span class="cx-dot" style="background:' + sv.c + '"></span>' + sv.lbl + '</span></td>'
      + '<td class="r">' + newest + '</td>'
      + '<td class="r">' + behind + '</td>'
      + '<td><span class="aval">' + (a.since ? fmtDay(a.since) : '-') + '</span>'
      + (a.since_days != null ? '<div class="asub">' + a.since_days + ' d in this state</div>' : '') + '</td>'
      + '<td class="afix' + (a.fix ? '' : ' plain') + '">' + esc(fix) + '</td></tr>';
  }

  // ---------- feed rollup ----------
  function feedRow(ds) {
    var accs = ds.accounts || [];
    var shown = accs.filter(function (a) { return passes(ds, a); });
    if (!shown.length && (S.filter.q || S.filter.state || S.filter.ds)) return '';
    var worst = 'idle';
    accs.forEach(function (a) { if (SEV[a.state] < SEV[worst]) worst = a.state; });
    var live = accs.filter(function (a) { return a.state === 'ok'; }).length;
    var watched = accs.filter(function (a) { return a.state !== 'idle'; }).length;
    // Idle accounts are SUPPOSED to be stale - an offboarded client or a retired seat sits
    // months behind by design, and counting them made a healthy feed report 125 d behind.
    var behinds = accs.filter(function (a) { return a.state !== 'idle'; })
      .map(function (a) { return (a.data || {}).days_behind; })
      .filter(function (v) { return v != null; });
    var wb = behinds.length ? Math.max.apply(null, behinds) : null;
    var pct = watched ? Math.round(live / watched * 100) : 100;
    var g = ds.grant || {}, due = g.expiry_estimate, dueD = due ? daysUntil(due) : null;
    var sv = stateOf(worst);
    var hasRed = accs.some(function (a) { return RED[a.state] && a.alerts; });
    var key = 'f:' + ds.ds;
    if (S.openFeed[key] == null && hasRed) S.openFeed[key] = true;
    var open = !!S.openFeed[key];
    var h = '<tr class="cx-frow' + (open ? ' open' : '') + '" data-feed="' + esc(key) + '" tabindex="0" aria-expanded="' + open + '">'
      + '<td><span class="fn"><span class="fcar">&#9654;</span><span class="cx-av">' + esc(mono(ds.label)) + '</span>' + esc(ds.label) + '</span>'
      + '<span class="fsub">' + (ds.source === 'dts' ? 'native BigQuery transfer' : 'Windsor connector') + ' &middot; ' + accs.length + ' accounts</span></td>'
      + '<td><span class="cx-verd" style="background:' + sv.soft + ';color:' + sv.c + '"><span class="cx-dot" style="background:' + sv.c + '"></span>' + sv.lbl + '</span></td>'
      + '<td><span class="fh"><span class="fbar' + (pct < 100 ? ' bad' : '') + '"><i style="width:' + pct + '%"></i></span><span class="ft">' + live + '/' + watched + '</span></span></td>'
      + '<td class="r">' + (wb == null ? '<span class="fdim">no data</span>' : '<span class="aval">' + wb + ' d</span>') + '</td>'
      + '<td>' + (due ? '<span class="aval">' + fmtDay(due) + '</span><span class="fsub2">' + (dueD != null ? (dueD < 0 ? 'overdue' : 'in ' + dueD + ' d') : '') + '</span>' : '<span class="fdim">no clock</span>') + '</td></tr>';
    if (open) {
      var st = ds.connector || {};
      var cs = st.state || 'ok';
      var cv = cs === 'ok' ? STATE.ok : cs === 'denied' ? STATE.not_granted : STATE.error;
      var reauthUrl = ds.reauth_url || ('https://onboard.windsor.ai?datasource=' + encodeURIComponent(ds.ds));
      var rows = shown.slice().sort(function (x, y) {
        return (SEV[x.state] - SEV[y.state]) || String(x.client_label || x.client).localeCompare(String(y.client_label || y.client));
      });
      var body = '<div class="cx-dmeta">'
        + (ds.loader_job ? '<span>loader <b>' + esc(ds.loader_job) + '</b>' + (ds.schedule ? ' &middot; ' + esc(ds.schedule) : '') + '</span>' : '<span>Google runs this transfer</span>')
        + (st.latency_ms != null ? '<span>connector answered in <b>' + (st.latency_ms / 1000).toFixed(1) + ' s</b></span>' : '')
        + (ds.table ? '<span>lands in <b>' + esc(ds.table) + '</b></span>' : '')
        + '<span class="cx-verd" style="background:' + cv.soft + ';color:' + cv.c + '"><span class="cx-dot" style="background:' + cv.c + '"></span>'
        + (cs === 'ok' ? 'Connector up' : cs === 'denied' ? 'Connector denied' : 'Connector error') + '</span>'
        + (ds.source === 'dts' ? '' : '<a class="cx-link" href="' + esc(reauthUrl) + '" target="_blank" rel="noopener">Re-grant in Windsor &#8599;</a>')
        + '</div>';
      body += rows.length
        ? '<table class="atbl"><thead><tr><th>Client</th><th>Account</th><th>State</th><th class="r">Newest data</th><th class="r">Behind</th><th>Since</th><th>What to do</th></tr></thead><tbody>'
          + rows.map(acctRow).join('') + '</tbody></table>'
        : '<div class="cx-empty">No accounts match that search.</div>';
      h += '<tr class="cx-fdet"><td colspan="5">' + body + '</td></tr>';
    }
    return h;
  }

  function feedCard(doc) {
    var dss = (doc && doc.datasources) || [];
    var rows = dss.map(feedRow).join('');
    var all = allAccounts(doc), shown = all.filter(function (x) { return passes(x.ds, x.a); });
    var chips = '<button class="cx-pill" data-ds="" aria-pressed="' + (!S.filter.ds) + '">All</button>'
      + dss.map(function (d) { return '<button class="cx-pill" data-ds="' + esc(d.label) + '" aria-pressed="' + (S.filter.ds === d.label) + '">' + esc(d.label) + '</button>'; }).join('')
      + '<button class="cx-pill" id="cxIdle" aria-pressed="' + S.filter.showIdle + '">Show idle</button>'
      + (S.filter.state || S.filter.ds || S.filter.q || S.filter.showIdle ? '<button class="cx-pill" id="cxClear">Clear filters</button>' : '')
      + '<span class="sep"></span><span class="cx-q">'
      + '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>'
      + '<input id="cxQ" type="search" placeholder="Find client or account" aria-label="Find client or account" value="' + esc(S.filter.q) + '"></span>';
    return '<div class="cx-card"><div class="cx-card-h"><h3>All feeds</h3>'
      + '<span class="hint">click a feed for its accounts and loader</span></div>'
      + '<div class="cx-card-sub">One row per feed. Freshness is measured on the table each dashboard reads.</div>'
      + '<div class="cx-chipbar">' + chips + '</div>'
      + '<div class="cx-tbl-wrap"><table class="cx"><thead><tr><th>Feed</th><th>Worst state</th><th>Accounts live</th><th class="r">Furthest behind</th><th>Re-auth due</th></tr></thead>'
      + '<tbody>' + (rows || '<tr><td colspan="5"><div class="cx-empty">Nothing matches that search.</div></td></tr>') + '</tbody></table></div>'
      + '<div class="cx-foot">Showing <b>' + shown.length + '</b> of ' + all.length + ' accounts. Accounts marked '
      + '<span class="cx-silent">silent</span> show here but never email; nothing on a client dashboard reads them.</div></div>';
  }

  // ---------- grant horizon ----------
  function horizon(doc) {
    var dss = (doc && doc.datasources) || [];
    var none = dss.filter(function (d) { return !(d.grant || {}).expiry_estimate; });
    var rows = dss.map(function (ds) {
      var g = ds.grant || {};
      var last = g.effective_reauth || g.last_reauth;
      var nm = '<div class="nm"><span class="cx-av">' + esc(mono(ds.label)) + '</span><div class="t"><b>' + esc(ds.label) + '</b>'
        + '<small>' + (last ? 're-authed ' + fmtDay(last) + (g.reauth_by ? ' by ' + esc(g.reauth_by) : '') : 'no re-auth date') + '</small></div></div>';
      if (!g.expiry_estimate) {
        return '<div class="cx-hz">' + nm + '<div class="none">'
          + (ds.source === 'dts' ? 'Native transfer, breaks on lost access rather than a date' : 'Does not expire while in use')
          + '</div><div></div></div>';
      }
      var start = new Date(last + 'T00:00:00Z'), end = new Date(g.expiry_estimate + 'T00:00:00Z');
      var total = Math.round((end - start) / 86400000);
      var gone = Math.round((Date.now() - start) / 86400000);
      var left = total - gone, pct = Math.max(0, Math.min(100, gone / total * 100));
      return '<div class="cx-hz">' + nm
        + '<div class="trk"><div class="bar"><i style="width:' + pct.toFixed(1) + '%;background:' + (left <= 14 ? 'var(--warn)' : 'var(--brand)') + '"></i>'
        + '<span class="now" style="left:' + pct.toFixed(1) + '%"></span></div>'
        + '<div class="ends"><span>' + fmtDay(last) + '</span><span>' + fmtDayY(g.expiry_estimate) + '</span></div></div>'
        + '<div class="rem"><b>' + left + ' d</b>left of about ' + total + '</div></div>';
    }).join('');
    return '<div class="cx-card"><div class="cx-card-h"><h3>Grant horizon</h3><span class="hint">estimated</span></div>'
      + '<div class="cx-card-sub">Counted from the last re-auth, because Windsor publishes no expiry date. The marker is today.</div>'
      + '<div class="cx-hzwrap">' + rows + '</div>'
      + (none.length ? '<div class="cx-foot">No clock, so watched for staleness instead: '
          + none.map(function (d) { return esc(d.label); }).join(', ') + '.</div>' : '')
      + '</div>';
  }

  function never(mount) {
    mount.innerHTML = hero(null) + '<div class="cx-card cx-never"><h3>The probe has never run</h3>'
      + '<p>windsor_connections.json is not in the status bucket yet. Deploy and run the probe job once and this tab fills itself in; from then on it refreshes hourly.</p>'
      + '<code>ingest\\windsor_data_pull\\connections\\deploy_job_connections.ps1 -Run</code></div>';
    wire(mount);
  }

  function render(mount) {
    if (!S.mounted) { var st = document.createElement('style'); st.id = 'connections-css'; st.textContent = CSS; document.head.appendChild(st); S.mounted = true; }
    if (!S.doc && !S.err) {
      (S.pending || load()).then(function () { render(mount); });
      mount.innerHTML = hero(null) + '<div class="cx-card"><div class="cx-empty">Loading connector health...</div></div>';
      return;
    }
    if (S.err && !S.doc) {
      mount.innerHTML = hero(null) + '<div class="cx-card cx-never"><h3>Could not load connector health</h3><p>' + esc(S.err) + '</p></div>';
      wire(mount); return;
    }
    var doc = S.doc;
    if (!doc || doc.never_run) return never(mount);
    paintNavBadge(doc);
    mount.innerHTML = hero(doc) + tiles(doc) + problems(doc) + feedCard(doc) + horizon(doc);
    wire(mount);
  }

  function wire(mount) {
    var pb = mount.querySelector('#cxProbe');
    if (pb) pb.addEventListener('click', function () { probe(mount, pb); });
    mount.querySelectorAll('.cx-scard[data-state]').forEach(function (b) {
      b.addEventListener('click', function () { S.filter.state = S.filter.state === b.dataset.state ? null : b.dataset.state; render(mount); });
    });
    mount.querySelectorAll('.cx-pill[data-ds]').forEach(function (b) {
      b.addEventListener('click', function () { S.filter.ds = b.dataset.ds || null; render(mount); });
    });
    var idle = mount.querySelector('#cxIdle');
    if (idle) idle.addEventListener('click', function () { S.filter.showIdle = !S.filter.showIdle; render(mount); });
    var cl = mount.querySelector('#cxClear');
    if (cl) cl.addEventListener('click', function () { S.filter = { state: null, ds: null, q: '', showIdle: false }; S.openFeed = {}; render(mount); });
    mount.querySelectorAll('tr.cx-frow').forEach(function (r) {
      function tog() { S.openFeed[r.dataset.feed] = !(r.getAttribute('aria-expanded') === 'true'); render(mount); }
      r.addEventListener('click', function (e) { if (!e.target.closest('a')) tog(); });
      r.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tog(); } });
    });
    var q = mount.querySelector('#cxQ');
    if (q) q.addEventListener('input', function () {
      S.filter.q = q.value.toLowerCase().trim();
      var pos = q.selectionStart; render(mount);
      var nq = mount.querySelector('#cxQ');
      if (nq) { nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { } }
    });
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
