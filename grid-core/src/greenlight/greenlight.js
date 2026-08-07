/* Greenlight tab - plan-side campaign checker (the Expected side of The Grid).
 * Classic script, same pattern as the Brain modules: attaches window.Greenlight
 * with render(mount). Renders into #view-greenlight inside the-grid.html on the
 * Grid's own CSS variables, and talks to /api/greenlight/* (expected/routes.js)
 * with RELATIVE paths so it works behind the platform proxy at /d/central/.
 *
 * Model: an ANALYSIS is a named workspace per campaign - its own isolated file
 * dump (persists across runs) plus a run history. New analysis = fresh empty
 * container, so campaigns' files never mix. Names optional; auto-named
 * analyses adopt the extracted client + job after the first run.
 * Violet (--tx) marks AI-authored content, per the Grid's Brain convention. */
(function () {
  'use strict';

  var API = 'api/greenlight';
  var MAX_UPLOAD = 15 * 1024 * 1024; // keep in sync with routes.js MAX_UPLOAD_BYTES

  var S = {
    mounted: false,
    analyses: [],
    current: null,     // {analysis, files, runs} detail for the open analysis
    uploads: [],       // in-flight upload rows {name, bytes, state, note}
    running: false,
    uploading: false,
  };

  var CSS = [
    '#view-greenlight .gl-wrap{max-width:1240px;margin:0 auto;padding:6px 0 60px}',
    '#view-greenlight .gl-head{display:flex;align-items:center;gap:12px;margin:8px 0 14px;flex-wrap:wrap}',
    '#view-greenlight .gl-head h2{font-family:"Space Grotesk";font-size:16px;font-weight:700;margin:0}',
    '#view-greenlight .gl-sub{color:var(--ink-3);font-size:11.5px}',
    '#view-greenlight .gl-right{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '#view-greenlight .gl-sel{appearance:none;font-family:inherit;font-size:12px;font-weight:600;color:var(--ink-2);background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:7px 11px;outline:none;cursor:pointer;max-width:280px}',
    '#view-greenlight .gl-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);padding:15px 17px;margin-bottom:14px}',
    '#view-greenlight .gl-card h3{font-family:"Space Grotesk";font-size:13.5px;font-weight:600;margin:0 0 3px;display:flex;align-items:center;gap:9px;flex-wrap:wrap}',
    '#view-greenlight .gl-desc{color:var(--ink-3);font-size:11.5px;margin-bottom:11px}',
    '#view-greenlight .gl-card.ai{border-left:3px solid var(--tx)}',
    '#view-greenlight .gl-aitag{font-size:9.5px;font-weight:700;letter-spacing:.07em;color:var(--tx-ink);background:var(--tx-soft);border-radius:6px;padding:2px 7px}',
    '#view-greenlight .gl-namebox{display:none;align-items:center;gap:8px;margin:2px 0 12px}',
    '#view-greenlight .gl-namebox input{font-family:inherit;font-size:12.5px;color:var(--ink);background:var(--panel-2);border:1px solid var(--line);border-radius:9px;padding:8px 12px;outline:none;width:300px}',
    '#view-greenlight .gl-namebox input:focus{border-color:var(--brand)}',
    '#view-greenlight .gl-aname{font-family:"Space Grotesk";font-size:14px;font-weight:700;color:var(--ink);cursor:text;border-bottom:1px dashed transparent}',
    '#view-greenlight .gl-aname:hover{border-bottom-color:var(--ink-3)}',
    '#view-greenlight .gl-ameta{color:var(--ink-3);font-size:11px}',
    '#view-greenlight .gl-drop{border:1.5px dashed var(--line);border-radius:var(--r);padding:20px 16px;text-align:center;cursor:pointer;background:var(--panel-2);transition:all .15s;color:var(--ink-2);font-size:12.5px}',
    '#view-greenlight .gl-drop:hover,#view-greenlight .gl-drop.over{border-color:var(--brand);background:var(--brand-soft)}',
    '#view-greenlight .gl-drop b{color:var(--ink)}',
    '#view-greenlight .gl-files{margin-top:11px;display:grid;grid-template-columns:1fr 1fr;gap:4px 18px;max-height:230px;overflow-y:auto}',
    '#view-greenlight .gl-file{display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:8px;font-size:12px;color:var(--ink-2)}',
    '#view-greenlight .gl-file:hover{background:var(--grp)}',
    '#view-greenlight .gl-fic{flex:0 0 auto;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:8.5px;font-weight:700;border-radius:5px;padding:2.5px 5px;min-width:30px;text-align:center}',
    '#view-greenlight .gl-fic.xls{background:var(--ok-soft);color:var(--ok)}',
    '#view-greenlight .gl-fic.pdf{background:var(--bad-soft);color:var(--bad)}',
    '#view-greenlight .gl-fic.img{background:var(--tx-soft);color:var(--tx-ink)}',
    '#view-greenlight .gl-fic.vid{background:var(--warn-soft);color:var(--warn)}',
    '#view-greenlight .gl-fic.doc{background:var(--brand-soft);color:var(--brand-ink)}',
    '#view-greenlight .gl-file .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '#view-greenlight .gl-file .sz{margin-left:auto;color:var(--ink-3);font-variant-numeric:tabular-nums;flex:0 0 auto}',
    '#view-greenlight .gl-file .rm{flex:0 0 auto;appearance:none;border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:13px;padding:0 3px;border-radius:5px}',
    '#view-greenlight .gl-file .rm:hover{color:var(--bad);background:var(--bad-soft)}',
    '#view-greenlight .gl-file .st{flex:0 0 auto;font-size:9px;font-weight:700;letter-spacing:.05em;border-radius:5px;padding:2px 5px}',
    '#view-greenlight .gl-file .st.skip{background:var(--warn-soft);color:var(--warn)}',
    '#view-greenlight .gl-file .st.fail{background:var(--bad-soft);color:var(--bad)}',
    '#view-greenlight .gl-skipped{display:none;margin-top:11px;border:1px solid var(--warn);border-radius:10px;background:var(--warn-soft);padding:9px 13px}',
    '#view-greenlight .gl-skiphead{font-size:12px;font-weight:600;color:var(--ink);margin-bottom:6px}',
    '#view-greenlight .gl-skiprow{display:flex;align-items:center;gap:10px;font-size:11.5px;color:var(--ink-2);padding:3px 0}',
    '#view-greenlight .gl-skiprow .nm{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px}',
    '#view-greenlight .gl-skiprow .rs{color:var(--ink-3)}',
    '#view-greenlight .gl-skiprow .sz{margin-left:auto;font-variant-numeric:tabular-nums}',
    '#view-greenlight .gl-foot{display:flex;align-items:center;gap:12px;margin-top:13px;flex-wrap:wrap}',
    '#view-greenlight .gl-btn{appearance:none;font-family:inherit;cursor:pointer;font-size:12.5px;font-weight:600;border-radius:999px;padding:8px 18px;border:1px solid var(--line);background:var(--panel);color:var(--ink-2);transition:all .15s}',
    '#view-greenlight .gl-btn:hover:not(:disabled){background:var(--grp)}',
    '#view-greenlight .gl-btn.primary{background:var(--pill-bg);color:var(--pill-fg);border-color:transparent}',
    '#view-greenlight .gl-btn.primary:hover:not(:disabled){background:var(--brand-strong)}',
    '#view-greenlight .gl-btn.danger{color:var(--bad)}',
    '#view-greenlight .gl-btn.danger:hover:not(:disabled){background:var(--bad-soft)}',
    '#view-greenlight .gl-btn.small{font-size:11px;padding:5px 12px}',
    '#view-greenlight .gl-btn:disabled{opacity:.45;cursor:default}',
    '#view-greenlight .gl-note{color:var(--ink-3);font-size:11.5px}',
    '#view-greenlight .gl-guardrow{display:none;align-items:center;gap:10px;margin-top:11px;padding:9px 13px;border:1px solid var(--warn);border-radius:10px;background:var(--warn-soft);font-size:12px;color:var(--ink)}',
    '#view-greenlight .gl-prog{display:none;margin-top:13px;border-top:1px solid var(--line-2);padding-top:11px}',
    '#view-greenlight .gl-step{display:flex;align-items:center;gap:10px;padding:4px 0;font-size:12.5px;color:var(--ink-3)}',
    '#view-greenlight .gl-step .ic{width:17px;height:17px;border-radius:50%;flex:0 0 auto;display:flex;align-items:center;justify-content:center;font-size:10px;border:1.5px solid var(--line);color:transparent}',
    '#view-greenlight .gl-step.active{color:var(--ink)}',
    '#view-greenlight .gl-step.active .ic{border-color:var(--brand);border-top-color:transparent;animation:glspin .8s linear infinite}',
    '#view-greenlight .gl-step.done{color:var(--ink-2)}',
    '#view-greenlight .gl-step.done .ic{border-color:var(--ok);background:var(--ok-soft);color:var(--ok)}',
    '#view-greenlight .gl-step.error .ic{border-color:var(--bad);background:var(--bad-soft);color:var(--bad)}',
    '@keyframes glspin{to{transform:rotate(360deg)}}',
    '#view-greenlight .gl-err{display:none;border-left:3px solid var(--bad)}',
    '#view-greenlight .gl-err h3{color:var(--bad)}',
    '#view-greenlight .gl-errmsg{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;color:var(--ink-2);background:var(--panel-2);border:1px solid var(--line-2);border-radius:8px;padding:9px 11px;white-space:pre-wrap}',
    '#view-greenlight .gl-guard{display:none;border-left:3px solid var(--bad)}',
    '#view-greenlight .gl-guard h3{color:var(--bad)}',
    '#view-greenlight .gl-results{display:none}',
    '#view-greenlight iframe{width:100%;border:1px solid var(--line-2);border-radius:10px;background:#fff}',
    '#view-greenlight .gl-chip{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;border-radius:6px;padding:3px 8px;white-space:nowrap}',
    '#view-greenlight .gl-chip.bad{background:var(--bad-soft);color:var(--bad)}',
    '#view-greenlight .gl-chip.warn{background:var(--warn-soft);color:var(--warn)}',
    '#view-greenlight .gl-chip.ok{background:var(--ok-soft);color:var(--ok)}',
    '#view-greenlight .gl-chip.dim{background:var(--grp);color:var(--ink-3)}',
    '#view-greenlight .gl-fsum{display:flex;gap:8px;margin-bottom:11px;flex-wrap:wrap}',
    '#view-greenlight .gl-fhead{display:grid;grid-template-columns:116px 160px 1fr 250px;gap:14px;padding:0 8px 7px;font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);font-weight:600}',
    '#view-greenlight .gl-frow{display:grid;grid-template-columns:116px 160px 1fr 250px;gap:14px;align-items:start;padding:9px 8px;border-top:1px solid var(--line-2);font-size:12.5px;border-left:3px solid transparent}',
    '#view-greenlight .gl-frow.ai{border-left:3px solid var(--tx);background:var(--tx-soft)}',
    '#view-greenlight .gl-frow:hover{background:var(--grp)}',
    '#view-greenlight .gl-frow .stage{color:var(--ink-3);font-size:11.5px;padding-top:2px}',
    '#view-greenlight .gl-frow .t{font-weight:600;color:var(--ink)}',
    '#view-greenlight .gl-frow .d{color:var(--ink-2);font-size:11.5px;margin-top:2px}',
    '#view-greenlight .gl-frow .src{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10px;color:var(--ink-3);word-break:break-word;padding-top:2px}',
    '#view-greenlight .gl-orig{font-size:8.5px;font-weight:700;letter-spacing:.06em;border-radius:5px;padding:2px 6px;vertical-align:middle;margin-left:7px}',
    '#view-greenlight .gl-orig.ai{color:var(--tx-ink);background:var(--tx-soft)}',
    '#view-greenlight .gl-orig.code{color:var(--ink-3);background:var(--grp)}',
    '#view-greenlight .gl-msg{background:var(--panel-2);border:1px solid var(--line-2);border-left:3px solid var(--tx);border-radius:10px;padding:12px 15px;margin-top:10px}',
    '#view-greenlight .gl-msg .mh{display:flex;align-items:center;gap:10px;margin-bottom:7px}',
    '#view-greenlight .gl-msg .mt{font-weight:600;font-size:12.5px;color:var(--ink)}',
    '#view-greenlight .gl-msg pre{margin:0;white-space:pre-wrap;font-family:inherit;font-size:12px;color:var(--ink-2);max-height:290px;overflow-y:auto}',
    '#view-greenlight .gl-copy{appearance:none;font-family:inherit;cursor:pointer;font-size:11px;font-weight:600;color:var(--tx-ink);background:var(--tx-soft);border:1px solid transparent;border-radius:7px;padding:4px 11px;margin-left:auto}',
    '#view-greenlight .gl-copy:hover{border-color:var(--tx)}',
    '#view-greenlight .gl-dl{display:inline-flex;align-items:center;gap:7px;text-decoration:none;font-size:12px;font-weight:600;color:var(--ink-2);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:7px 13px;margin:0 8px 8px 0}',
    '#view-greenlight .gl-dl:hover{background:var(--grp);color:var(--ink)}',
    '#view-greenlight .gl-empty{text-align:center;color:var(--ink-3);font-size:13px;padding:44px 16px}',
    // ---- run modal: what will be read, what will not, what it will cost ----
    '#glModal{position:fixed;inset:0;z-index:9000;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.45);backdrop-filter:blur(2px)}',
    '#glModal.on{display:flex}',
    '#glModal .mbox{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:0 18px 50px rgba(0,0,0,.35);width:min(860px,94vw);max-height:88vh;display:flex;flex-direction:column}',
    '#glModal .mhead{padding:16px 20px 12px;border-bottom:1px solid var(--line-2)}',
    '#glModal .mhead h3{font-family:"Space Grotesk";font-size:15px;font-weight:700;margin:0 0 3px;color:var(--ink)}',
    '#glModal .mhead .sub{font-size:11.5px;color:var(--ink-3)}',
    '#glModal .mbody{padding:14px 20px;overflow-y:auto;flex:1}',
    '#glModal .mfoot{padding:12px 20px 16px;border-top:1px solid var(--line-2);display:flex;align-items:center;gap:10px;flex-wrap:wrap}',
    '#glModal .mfoot .sp{margin-left:auto}',
    '#glModal .mstat{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}',
    '#glModal .mtok{border:1px solid var(--line-2);border-radius:10px;background:var(--panel-2);padding:10px 13px;margin-bottom:13px}',
    '#glModal .mtok .big{font-family:"Space Grotesk";font-size:19px;font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums}',
    '#glModal .mtok .cap{font-size:11px;color:var(--ink-3);margin-top:2px}',
    '#glModal .mwarn{border:1px solid var(--warn);background:var(--warn-soft);border-radius:10px;padding:9px 13px;margin-bottom:12px;font-size:12px;color:var(--ink)}',
    '#glModal .mbad{border:1px solid var(--bad);background:var(--bad-soft);border-radius:10px;padding:9px 13px;margin-bottom:12px;font-size:12px;color:var(--ink)}',
    '#glModal .mgrp{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin:12px 0 5px}',
    '#glModal .mrow{display:flex;align-items:center;gap:9px;padding:5px 8px;border-radius:8px;font-size:12px;color:var(--ink-2)}',
    '#glModal .mrow:hover{background:var(--grp)}',
    '#glModal .mrow .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px;flex:0 0 auto}',
    '#glModal .mrow .why{color:var(--ink-3);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '#glModal .mrow .sz{margin-left:auto;color:var(--ink-3);font-variant-numeric:tabular-nums;flex:0 0 auto}',
    '#glModal .mprog{display:none;border-top:1px solid var(--line-2);margin-top:12px;padding-top:11px}',
    '#glModal.running .mprog{display:block}',
    '#glModal.running .mpre{display:none}',
    '#glModal .mlog{margin-top:12px;border-top:1px solid var(--line-2);padding-top:10px}',
    '#glModal .mlogh{display:flex;align-items:center;gap:8px;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin-bottom:6px}',
    '#glModal .mlogh button{appearance:none;font-family:inherit;font-size:10px;font-weight:700;letter-spacing:.05em;cursor:pointer;color:var(--ink-3);background:transparent;border:1px solid var(--line);border-radius:6px;padding:2px 8px;margin-left:auto}',
    '#glModal .mlogh button:hover{color:var(--ink);background:var(--grp)}',
    '#glModal .mlogbox{display:none;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10.5px;line-height:1.55;color:var(--ink-2);background:var(--panel-2);border:1px solid var(--line-2);border-radius:8px;padding:9px 11px;max-height:210px;overflow-y:auto;white-space:pre-wrap;word-break:break-word}',
    '#glModal .mlogbox.on{display:block}',
    '#glModal .mlogbox .t{color:var(--ink-3)}',
    '#glModal .mlogbox .s-extract{color:var(--brand-ink)}',
    '#glModal .mlogbox .s-build{color:var(--tx-ink)}',
    '#glModal .mlogbox .s-system{color:var(--warn)}',
    '#glModal .mempty{color:var(--ink-3);font-style:italic}',
    // partial run: the stepper's last step stopped short on purpose, so it needs
    // its own state - without this it renders as an unstyled blank circle.
    '#view-greenlight .gl-step.warn{color:var(--ink-2)}',
    '#view-greenlight .gl-step.warn .ic{border-color:var(--warn);background:var(--warn-soft);color:var(--warn)}',
    // "files still needed" - the call to action on an incomplete dump. Deliberately
    // the loudest thing on the results panel: it is the only part the buyer can act on.
    '#view-greenlight .gl-needs{display:none;border-left:3px solid var(--warn)}',
    '#view-greenlight .gl-needs h3{color:var(--ink)}',
    '#view-greenlight .gl-need{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid var(--line-2);font-size:12.5px}',
    '#view-greenlight .gl-need .t{font-weight:600;color:var(--ink)}',
    '#view-greenlight .gl-need .d{color:var(--ink-2);font-size:11.5px;margin-top:3px;word-break:break-word}',
    '#view-greenlight .gl-partialbar{display:none;align-items:flex-start;gap:10px;margin-bottom:14px;padding:11px 14px;border:1px solid var(--warn);border-radius:10px;background:var(--warn-soft);font-size:12.5px;color:var(--ink)}',
    '#view-greenlight .gl-partialbar b{display:block;margin-bottom:2px}',
    '#view-greenlight .gl-partialbar .why{color:var(--ink-2);font-size:11.5px}',
    '#view-greenlight .gl-live{display:none;margin-top:9px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;color:var(--ink-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '#view-greenlight .gl-logbox{max-height:320px;overflow:auto;margin:0;padding:10px 12px;background:var(--panel-2);border:1px solid var(--line-2);border-radius:8px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;line-height:1.5;color:var(--ink-2);white-space:pre-wrap}',
    // severity chips double as filters once a real dump pushes findings past ~30
    '#view-greenlight .gl-fsum .gl-chip{cursor:pointer;user-select:none;border:1px solid transparent}',
    '#view-greenlight .gl-fsum .gl-chip.off{opacity:.35}',
    '#view-greenlight .gl-fsum .gl-chip:hover{border-color:currentColor}',
    '#view-greenlight .gl-fempty{color:var(--ink-3);font-size:12px;padding:14px 8px}',
  ].join('\n');

  var HTML = [
    '<div class="gl-wrap">',
    '  <div class="gl-head">',
    '    <div><h2>Greenlight</h2><div class="gl-sub">Plan-side campaign checker: one analysis per campaign, its own files, its own run history</div></div>',
    '    <div class="gl-right">',
    '      <select class="gl-sel" id="glASel" title="Analyses"><option value="">Analyses</option></select>',
    '      <button class="gl-btn primary" id="glNewBtn">New analysis</button>',
    '    </div>',
    '  </div>',
    '  <div class="gl-namebox" id="glNameBox">',
    '    <input id="glNameInput" placeholder="Campaign name (optional - auto-named from the plan after the first run)" maxlength="120">',
    '    <button class="gl-btn primary small" id="glNameCreate">Create</button>',
    '    <button class="gl-btn small" id="glNameCancel">Cancel</button>',
    '  </div>',
    '  <div class="gl-card gl-empty" id="glEmpty">No analysis open. Create a <b>New analysis</b> for a campaign, or pick one from the dropdown.</div>',
    '  <div id="glWorkspace" style="display:none">',
    '  <div class="gl-card">',
    '    <h3><span class="gl-aname" id="glAName" title="Click to rename"></span>',
    '      <span class="gl-ameta" id="glAMeta"></span>',
    '      <span style="margin-left:auto;display:flex;gap:6px">',
    '        <select class="gl-sel" id="glRunSel" title="Runs of this analysis" style="display:none"><option value="">Runs</option></select>',
    '        <button class="gl-btn small" id="glArchBtn">Archive</button>',
    '        <button class="gl-btn small danger" id="glDelBtn">Delete</button>',
    '      </span></h3>',
    '    <div class="gl-desc">Files below belong to THIS analysis only and persist across its runs. Add more as the media buyer sends them, then run again.</div>',
    '    <div class="gl-drop" id="glDrop">Drop files here, or <b>browse files</b> / <b>browse a folder</b> (15MB per file; larger files are skipped)',
    '      <input type="file" id="glPickFiles" multiple style="display:none">',
    '      <input type="file" id="glPickDir" webkitdirectory style="display:none">',
    '    </div>',
    '    <div class="gl-files" id="glFiles"></div>',
    '    <div class="gl-skipped" id="glSkipped"></div>',
    '    <div class="gl-foot">',
    '      <button class="gl-btn primary" id="glRunBtn">Run Analysis</button>',
    '      <span class="gl-note" id="glCount"></span>',
    '    </div>',
    '    <div class="gl-guardrow" id="glGuardRow"><span id="glGuardRowMsg"></span>',
    '      <button class="gl-btn small" id="glForceBtn">Run anyway</button>',
    '      <button class="gl-btn small" id="glGuardCancel">Cancel</button>',
    '    </div>',
    '    <div class="gl-prog" id="glProg">',
    '      <div class="gl-step" data-k="extract"><span class="ic">&#10003;</span>Extracting files</div>',
    '      <div class="gl-step" data-k="plan"><span class="ic">&#10003;</span>Reading plan</div>',
    '      <div class="gl-step" data-k="gaps"><span class="ic">&#10003;</span>Checking gaps</div>',
    '      <div class="gl-step" data-k="outputs"><span class="ic">&#10003;</span>Building outputs</div>',
    '      <div class="gl-live" id="glLive"></div>',
    '    </div>',
    '  </div>',
    '  <div class="gl-card gl-err" id="glErr"><h3>Run failed</h3><div class="gl-desc">The pipeline stopped and produced nothing. This is not the same as an incomplete dump - a dump that is merely missing files still returns a partial audit.</div><div class="gl-errmsg" id="glErrMsg"></div>',
    '    <div class="gl-foot" id="glRetryRow" style="display:none"><button class="gl-btn small" id="glRetryBtn">Retry failed step</button><span class="gl-note">Reuses this run\'s extraction - rebuilds the outputs only, no new AI call.</span></div>',
    '  </div>',
    '  <div class="gl-results" id="glResults">',
    '    <div class="gl-partialbar" id="glPartialBar"><span>&#9888;</span><span><b>Partial audit - no baseline was built</b>',
    '      <span class="why" id="glPartialWhy"></span>',
    '      <span class="why">Everything that could be checked, was. Add the files below and run again to complete it.</span></span></div>',
    '    <div class="gl-card gl-needs" id="glNeeds"><h3>Files still needed <span class="gl-chip warn" id="glNeedsCount"></span></h3>',
    '      <div class="gl-desc">What the documents expect but this analysis does not have. Upload them into this same analysis - your existing files stay - then run again.</div>',
    '      <div id="glNeedRows"></div>',
    '      <div class="gl-foot"><button class="gl-btn primary small" id="glNeedsAdd">Add the missing files</button></div>',
    '    </div>',
    '    <div class="gl-card gl-guard" id="glGuard"><h3>Multiple campaigns detected</h3><div class="gl-desc" id="glGuardMsg" style="margin-bottom:0"></div></div>',
    '    <div class="gl-card" id="glBaselineCard"><h3>Expected baseline <span class="gl-chip ok">COMPUTED IN CODE</span></h3><div class="gl-desc">One row per media-plan line: goals, window, spend/day and expected-to-date, with the source cell it came from. The daily curve lives in daily_kpi.xlsx / .json; actuals join later.</div><iframe id="glPacing" title="Expected baseline" height="440"></iframe></div>',
    '    <div class="gl-card" id="glFlowCard"><h3>Process flowchart <span class="gl-chip ok">COMPUTED IN CODE</span></h3><div class="gl-desc">Stage status from findings. Red means a blocker sits in that stage.</div><iframe id="glFlow" title="Readiness flowchart" height="460"></iframe></div>',
    '    <div class="gl-card"><h3>Findings</h3><div class="gl-desc" id="glFDesc"></div><div class="gl-fsum" id="glFSum"></div><div class="gl-fhead"><span>Status</span><span>Stage</span><span>Finding</span><span>Source</span></div><div id="glFRows"></div></div>',
    '    <div class="gl-card ai"><h3>Chase messages <span class="gl-aitag">AI-AUTHORED</span></h3><div class="gl-desc" id="glMDesc">Drafts only. A person reviews and sends.</div><div id="glMsgs"></div></div>',
    '    <div class="gl-card"><h3>Downloads</h3><div class="gl-desc">The artifacts this run produced. A partial run writes fewer - only what it could.</div><div id="glDls"></div></div>',
    '    <div class="gl-card"><h3>Run log</h3><div class="gl-desc">Everything this run did, in order, with token usage and the outcome. Useful on a run that succeeded, not just one that failed.</div><pre class="gl-logbox" id="glLog">loading...</pre></div>',
    '  </div>',
    '  </div>',
    '</div>',
    '<div id="glModal">',
    '  <div class="mbox">',
    '    <div class="mhead"><h3 id="glMTitle">Ready to run</h3><div class="sub" id="glMSub"></div></div>',
    '    <div class="mbody">',
    '      <div class="mpre" id="glMPre"></div>',
    '      <div class="mprog" id="glMProg">',
    '        <div class="gl-step" data-k="extract"><span class="ic">&#10003;</span>Extracting files</div>',
    '        <div class="gl-step" data-k="plan"><span class="ic">&#10003;</span>Reading plan</div>',
    '        <div class="gl-step" data-k="gaps"><span class="ic">&#10003;</span>Checking gaps</div>',
    '        <div class="gl-step" data-k="outputs"><span class="ic">&#10003;</span>Building outputs</div>',
    '        <div class="mlog">',
    '          <div class="mlogh"><span>Run log</span><button id="glLogToggle">Show</button></div>',
    '          <div class="mlogbox" id="glLogBox"></div>',
    '        </div>',
    '      </div>',
    '    </div>',
    '    <div class="mfoot">',
    '      <span class="gl-note" id="glMNote"></span>',
    '      <span class="sp"></span>',
    '      <button class="gl-btn" id="glMCancel">Cancel</button>',
    '      <button class="gl-btn primary" id="glMStart">Start run</button>',
    '    </div>',
    '  </div>',
    '</div>',
  ].join('\n');

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function el(id) { return document.getElementById(id); }
  function icFor(name) {
    var e = (String(name).split('.').pop() || '').toLowerCase();
    if (e === 'xlsx' || e === 'xlsm' || e === 'xls' || e === 'csv') return ['xls', e.slice(0, 3).toUpperCase()];
    if (e === 'pdf') return ['pdf', 'PDF'];
    if (['jpg', 'jpeg', 'png', 'gif', 'webp'].indexOf(e) > -1) return ['img', 'IMG'];
    if (e === 'mp4' || e === 'mov') return ['vid', 'MP4'];
    return ['doc', (e || 'FILE').slice(0, 4).toUpperCase()];
  }
  function fmtSize(b) {
    if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB';
    if (b >= 1024) return (b / 1024).toFixed(0) + ' KB';
    return b + ' B';
  }
  function chipClass(sev) {
    if (sev === 'blocker') return 'bad';
    if (sev === 'missing' || sev === 'gap' || sev === 'inconsistent') return 'warn';
    return 'dim';
  }
  function jfetch(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j && j.error || ('HTTP ' + r.status));
        return j;
      });
    });
  }

  // ---------------------------------------------------------------- analyses
  function loadAnalyses(selectId) {
    return jfetch(API + '/analyses').then(function (j) {
      S.analyses = j.analyses || [];
      var sel = el('glASel');
      sel.innerHTML = '';
      var ph = document.createElement('option');
      ph.value = '';
      ph.textContent = 'Analyses (' + S.analyses.filter(function (a) { return !a.archived_at; }).length + ')';
      sel.appendChild(ph);
      S.analyses.filter(function (a) { return !a.archived_at; }).forEach(function (a) {
        var o = document.createElement('option');
        o.value = a.id;
        o.textContent = a.name + ' · ' + a.runs + ' run' + (a.runs === 1 ? '' : 's');
        sel.appendChild(o);
      });
      var archived = S.analyses.filter(function (a) { return a.archived_at; });
      archived.forEach(function (a) {
        var o = document.createElement('option');
        o.value = a.id;
        o.textContent = a.name + ' (archived)';
        sel.appendChild(o);
      });
      sel.value = selectId && S.analyses.some(function (a) { return a.id === selectId; }) ? selectId : (S.current ? S.current.analysis.id : '');
    }).catch(function () {});
  }

  function openAnalysis(id, keepResults) {
    return jfetch(API + '/analyses/' + id).then(function (d) {
      S.current = d;
      S.uploads = [];
      el('glEmpty').style.display = 'none';
      el('glWorkspace').style.display = '';
      if (!keepResults) {
        el('glResults').style.display = 'none';
        el('glErr').style.display = 'none';
        el('glProg').style.display = 'none';
        el('glGuardRow').style.display = 'none';
      }
      el('glASel').value = id;
      renderAnalysisHead();
      renderFiles();
      // A run already in flight wins over showing old results: re-attach to it
      // rather than offering a Run button that would immediately 409.
      if (d.active_run && !S.running) { resumeRun(d.active_run); return; }
      // auto-open the latest run's results when there is one
      if (!keepResults && d.runs.length) loadRunResults(d.runs[0].id);
    }).catch(function (e) { showError(String(e.message || e)); });
  }

  function renderAnalysisHead() {
    var a = S.current.analysis;
    el('glAName').textContent = a.name;
    el('glAMeta').textContent = 'created ' + String(a.created_at).slice(0, 10) + (a.archived_at ? ' · ARCHIVED' : '') + (a.auto_named ? ' · auto-named' : '');
    el('glArchBtn').textContent = a.archived_at ? 'Unarchive' : 'Archive';
    var runSel = el('glRunSel');
    runSel.innerHTML = '';
    if (S.current.runs.length) {
      runSel.style.display = '';
      S.current.runs.forEach(function (r, i) {
        var o = document.createElement('option');
        o.value = r.id;
        // Mark partial runs in the picker: without it an incomplete audit is
        // indistinguishable from a complete one until you open it.
        o.textContent = 'Run ' + (S.current.runs.length - i) + ' · ' + (r.at ? r.at.replace('T', ' ').slice(0, 16) : r.id)
          + (r.partial ? ' · PARTIAL' + (r.needs_upload ? ' (' + r.needs_upload + ' to upload)' : '') : '');
        runSel.appendChild(o);
      });
    } else {
      runSel.style.display = 'none';
    }
  }

  function renderFiles() {
    var box = el('glFiles');
    box.innerHTML = '';
    var serverFiles = (S.current ? S.current.files : []);
    serverFiles.forEach(function (f) {
      var ic = icFor(f.name);
      var div = document.createElement('div');
      div.className = 'gl-file';
      div.innerHTML = '<span class="gl-fic ' + ic[0] + '">' + ic[1] + '</span><span class="nm" title="' + esc(f.name) + '">' + esc(f.name) + '</span><span class="sz">' + fmtSize(f.bytes) + '</span>';
      var rm = document.createElement('button');
      rm.className = 'rm';
      rm.title = 'Remove this file from the analysis';
      rm.textContent = '×';
      rm.addEventListener('click', function () {
        jfetch(API + '/analyses/' + S.current.analysis.id + '/files/remove', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: f.name }) })
          .then(function () { return openAnalysis(S.current.analysis.id, true); })
          .catch(function (e) { showError(String(e.message || e)); });
      });
      div.appendChild(rm);
      box.appendChild(div);
    });
    S.uploads.forEach(function (u) {
      if (u.state === 'uploaded') return; // now in the server listing
      var ic = icFor(u.name);
      var div = document.createElement('div');
      div.className = 'gl-file';
      var st = u.state === 'uploading' ? '<span class="st">...</span>'
        : u.state === 'skipped' ? '<span class="st skip" title="' + esc(u.note || '') + '">SKIPPED</span>'
        : '<span class="st fail" title="' + esc(u.note || '') + '">FAILED</span>';
      div.innerHTML = '<span class="gl-fic ' + ic[0] + '">' + ic[1] + '</span><span class="nm">' + esc(u.name) + '</span>' + st + '<span class="sz">' + fmtSize(u.bytes) + '</span>';
      box.appendChild(div);
    });
    el('glCount').textContent = serverFiles.length + ' file' + (serverFiles.length === 1 ? '' : 's') + ' in this analysis';
    renderSkipped();
  }

  // Tell the server about a file that never made it in. The old code only
  // flagged these in page memory, which openAnalysis() cleared as soon as the
  // batch finished - so the dump silently shrank. Recorded server-side the
  // warning survives the refresh and the reload. Never rejects: a failed
  // notification must not stall the upload queue.
  function noteSkipped(aid, name, bytes, reason) {
    return jfetch(API + '/analyses/' + aid + '/files/skipped', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: name, bytes: bytes, reason: reason }),
    }).catch(function () {});
  }

  function clearSkipped(name) {
    if (!S.current) return;
    jfetch(API + '/analyses/' + S.current.analysis.id + '/files/skipped/clear', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: name || null }),
    }).then(function () { return openAnalysis(S.current.analysis.id, true); })
      .catch(function (e) { showError(String(e.message || e)); });
  }

  // Persistent "these files are NOT in the analysis" banner, rendered from the
  // server record rather than from in-flight upload state.
  function renderSkipped() {
    var box = el('glSkipped');
    var list = (S.current && S.current.analysis.skipped) || [];
    if (!list.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    var h = '<div class="gl-skiphead">' + list.length + ' file' + (list.length === 1 ? '' : 's')
      + ' could not be added to this analysis. The run will NOT include ' + (list.length === 1 ? 'it' : 'them') + '.</div>';
    list.forEach(function (s) {
      h += '<div class="gl-skiprow"><span class="nm">' + esc(s.name) + '</span>'
        + '<span class="rs">' + esc(s.reason) + '</span>'
        + '<span class="sz">' + fmtSize(s.bytes) + '</span>'
        + '<button class="gl-btn small" data-clear="' + esc(s.name) + '">Dismiss</button></div>';
    });
    box.innerHTML = h;
    box.style.display = 'block';
    box.querySelectorAll('button[data-clear]').forEach(function (b) {
      b.addEventListener('click', function () { clearSkipped(b.getAttribute('data-clear')); });
    });
  }

  function uploadFiles(fileList) {
    if (!S.current) return;
    var files = Array.prototype.slice.call(fileList);
    if (!files.length || S.uploading) return;
    S.uploading = true;
    el('glRunBtn').disabled = true;
    var aid = S.current.analysis.id;
    var queue = files.slice();
    function next() {
      var f = queue.shift();
      if (!f) {
        S.uploading = false;
        el('glRunBtn').disabled = false;
        openAnalysis(aid, true);
        return;
      }
      var rel = f.webkitRelativePath || f.name;
      var entry = { name: rel, bytes: f.size, state: 'uploading' };
      S.uploads.push(entry);
      renderFiles();
      if (f.size > MAX_UPLOAD) {
        entry.state = 'skipped';
        entry.note = 'over the 15MB per-file limit';
        renderFiles();
        return noteSkipped(aid, rel, f.size, 'over the 15MB per-file limit').then(next);
      }
      var reader = new FileReader();
      reader.onload = function () {
        var b64 = String(reader.result).split(',')[1] || '';
        fetch(API + '/analyses/' + aid + '/files', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: rel, data_b64: b64 }) })
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (o) {
            entry.state = o.ok ? 'uploaded' : 'failed';
            if (o.ok) { renderFiles(); return next(); }
            entry.note = o.j && o.j.error || 'upload failed';
            renderFiles();
            return noteSkipped(aid, rel, f.size, entry.note).then(next);
          })
          .catch(function (e) { entry.state = 'failed'; entry.note = String(e); renderFiles(); noteSkipped(aid, rel, f.size, String(e)).then(next); });
      };
      reader.onerror = function () { entry.state = 'failed'; entry.note = 'could not read file'; renderFiles(); noteSkipped(aid, rel, f.size, 'could not read file').then(next); };
      reader.readAsDataURL(f);
    }
    next();
  }

  // ---------------------------------------------------------------- preflight modal
  // Stage 0 is deterministic and free, so the run can be previewed exactly:
  // which files get read, which are ignored and why, and what the model call
  // will cost in tokens. Nothing here spends anything.
  function fmtInt(n) { return n == null ? '?' : Number(n).toLocaleString(); }

  function openModal(pre) {
    var m = el('glModal');
    m.className = 'on';
    el('glMTitle').textContent = 'Ready to run';
    el('glMSub').textContent = 'Checked the dump in ' + pre.ms + 'ms. Nothing has been spent yet.';
    el('glMStart').style.display = '';
    el('glMCancel').textContent = 'Cancel';

    var read = pre.files.filter(function (f) { return f.read; });
    var notRead = pre.files.filter(function (f) { return !f.read; });
    var est = pre.estimate;
    var band = Math.round(est.input_tokens * est.accuracy);
    var h = '';

    if (pre.short_dump) h += '<div class="mbad"><b>Files are missing.</b> ' + esc(pre.short_dump) + '</div>';

    h += '<div class="mtok"><div class="big">~' + fmtInt(est.input_tokens) + ' input tokens</div>'
      + '<div class="cap">' + fmtInt(Math.max(0, est.input_tokens - band)) + ' to ' + fmtInt(est.input_tokens + band)
      + ', from ' + fmtInt(est.chars) + ' characters at ' + est.chars_per_token + ' chars/token'
      + (est.calibrated ? ' (measured over ' + est.samples + ' previous run' + (est.samples === 1 ? '' : 's') + ')' : ' (estimated - no run measured yet)')
      + '. Output is capped at ' + fmtInt(est.output_tokens_max) + ' tokens, shared between thinking and the record.</div></div>';

    h += '<div class="mstat">'
      + '<span class="gl-chip ok">' + read.length + ' READ</span>'
      + (notRead.length ? '<span class="gl-chip warn">' + notRead.length + ' NOT READ</span>' : '')
      + (pre.skipped.length ? '<span class="gl-chip bad">' + pre.skipped.length + ' NEVER UPLOADED</span>' : '')
      + (pre.intake.duplicates ? '<span class="gl-chip dim">' + pre.intake.duplicates + ' DUPLICATE</span>' : '')
      + '</div>';

    if (pre.skipped.length) {
      h += '<div class="mgrp">Never reached the analysis</div>';
      pre.skipped.forEach(function (s) {
        h += '<div class="mrow"><span class="gl-chip bad">MISSING</span><span class="nm">' + esc(s.name)
          + '</span><span class="why">' + esc(s.reason) + '</span><span class="sz">' + fmtSize(s.bytes) + '</span></div>';
      });
    }
    if (notRead.length) {
      h += '<div class="mgrp">In the dump, but their content will NOT be extracted</div>';
      notRead.forEach(function (f) {
        h += '<div class="mrow"><span class="gl-chip warn">' + esc(String(f.type).toUpperCase()) + '</span><span class="nm">' + esc(f.file)
          + '</span><span class="why">' + esc(f.reason || '') + '</span><span class="sz">' + fmtSize(f.bytes) + '</span></div>';
      });
    }
    h += '<div class="mgrp">Content going to the model</div>';
    read.forEach(function (f) {
      h += '<div class="mrow"><span class="gl-chip ok">' + esc(String(f.type).toUpperCase()) + '</span><span class="nm">' + esc(f.file)
        + '</span><span class="why">' + esc(f.reason || '') + '</span><span class="sz">' + fmtSize(f.bytes) + '</span></div>';
    });

    el('glMPre').innerHTML = h;
    el('glMNote').textContent = notRead.length || pre.skipped.length
      ? 'Anything listed above as not read will be absent from the baseline, and raised as a finding.'
      : 'Every file in this analysis will be read.';
  }

  function closeModal() { el('glModal').className = ''; }

  // Live pipeline output, so a run that looks stuck can be diagnosed from the
  // tab instead of from Cloud Run logs. Same lines the container prints.
  function renderLog(lines) {
    var box = el('glLogBox');
    if (!box) return;
    if (!lines || !lines.length) {
      box.innerHTML = '<span class="mempty">No output yet. The first stage prints as soon as it starts.</span>';
      return;
    }
    var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = lines.map(function (l) {
      return '<div><span class="t">' + esc(String(l.at).slice(11, 19)) + '</span> '
        + '<span class="s-' + esc(l.src) + '">' + esc(l.line) + '</span></div>';
    }).join('');
    if (atBottom) box.scrollTop = box.scrollHeight;   // follow, unless scrolled up
  }

  // Re-attach to a run already in flight (page reload, second tab, or a run
  // started before the instance we are talking to now).
  function resumeRun(active) {
    S.running = true;
    S.pendingForce = false;
    el('glRunBtn').disabled = true;
    el('glRunBtn').textContent = 'Running...';
    el('glErr').style.display = 'none';
    el('glProg').style.display = 'block';
    modalToRunning();
    el('glMSub').textContent = 'Re-attached to a run already in progress (started '
      + String(active.started_at).replace('T', ' ').slice(0, 19) + ' UTC).';
    (active.stages || []).forEach(function (s) { setStep(s.key, s.state); });
    poll(active.id);
  }

  // The modal stays open through the run and becomes the progress view, so the
  // intake breakdown is still on screen while the stages tick over.
  function modalToRunning() {
    el('glModal').className = 'on running';
    el('glMTitle').textContent = 'Running';
    el('glMSub').textContent = 'The model call takes about 5 to 7 minutes. You can close this and it keeps running.';
    el('glMStart').style.display = 'none';
    el('glMCancel').textContent = 'Close';
    el('glMNote').textContent = '';
  }

  function preflight(force) {
    if (!S.current || S.running) return;
    var btn = el('glRunBtn');
    btn.disabled = true;
    btn.textContent = 'Checking...';
    jfetch(API + '/analyses/' + S.current.analysis.id + '/preflight', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    }).then(function (pre) {
      btn.disabled = false;
      btn.textContent = S.current.runs.length ? 'Run Again' : 'Run Analysis';
      S.pendingForce = !!force;
      openModal(pre);
    }).catch(function (e) {
      btn.disabled = false;
      btn.textContent = 'Run Analysis';
      showError(String(e.message || e));
    });
  }

  // ---------------------------------------------------------------- runs
  function setStep(key, state) {
    var nodes = document.querySelectorAll('.gl-step[data-k="' + key + '"]');
    for (var i = 0; i < nodes.length; i++) nodes[i].className = 'gl-step ' + (state || '');
  }
  function showError(msg) {
    el('glErr').style.display = 'block';
    el('glErrMsg').textContent = msg;
  }
  // canRetry: the extraction succeeded and only the build step failed, so the
  // saved extraction can be reused - offer "retry failed step" (no model call).
  function finishError(msg, canRetry) {
    S.running = false;
    closeModal();
    el('glRunBtn').disabled = false;
    el('glRunBtn').textContent = 'Run Analysis';
    var active = document.querySelector('#view-greenlight .gl-step.active');
    if (active) active.className = 'gl-step error';
    el('glRetryRow').style.display = canRetry ? 'flex' : 'none';
    showError(msg);
  }

  function startRun(force) {
    if (!S.current) return;
    var aid = S.current.analysis.id;
    S.running = true;
    el('glRunBtn').disabled = true;
    el('glRunBtn').textContent = 'Running...';
    el('glErr').style.display = 'none';
    el('glRetryRow').style.display = 'none';
    el('glGuardRow').style.display = 'none';
    el('glProg').style.display = 'block';
    ['extract', 'plan', 'gaps', 'outputs'].forEach(function (k) { setStep(k, ''); });
    jfetch(API + '/analyses/' + aid + '/analyze', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ force: !!force }) })
      .then(function (j) {
        if (j.unchanged) {
          S.running = false;
          closeModal();
          el('glRunBtn').disabled = false;
          el('glRunBtn').textContent = 'Run Analysis';
          el('glProg').style.display = 'none';
          el('glGuardRowMsg').textContent = 'Files are identical to the last run (' + (j.last_run && j.last_run.at ? j.last_run.at.replace('T', ' ').slice(0, 16) : '') + '). Another run costs a model call.';
          el('glGuardRow').style.display = 'flex';
          return;
        }
        poll(j.runId);
      })
      .catch(function (e) { finishError(String(e.message || e)); });
  }

  // Retry the failed step: rebuild outputs from the saved extraction. The
  // model stages complete instantly server-side; only the build reruns.
  function startRebuild() {
    if (!S.current || S.running) return;
    var aid = S.current.analysis.id;
    S.running = true;
    el('glRunBtn').disabled = true;
    el('glRunBtn').textContent = 'Running...';
    el('glErr').style.display = 'none';
    el('glRetryRow').style.display = 'none';
    el('glGuardRow').style.display = 'none';
    el('glProg').style.display = 'block';
    ['extract', 'plan', 'gaps', 'outputs'].forEach(function (k) { setStep(k, ''); });
    jfetch(API + '/analyses/' + aid + '/rebuild', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' })
      .then(function (j) { poll(j.runId); })
      .catch(function (e) { finishError(String(e.message || e)); });
  }

  function poll(id) {
    fetch(API + '/runs/' + id, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('poll returned HTTP ' + r.status);
      return r.json();
    }).then(function (run) {
      (run.stages || []).forEach(function (s) { setStep(s.key, s.state); });
      renderLog(run.log);
      // The model call is minutes of silence otherwise. The server already
      // narrates into run.log; mirror its last line under the stepper so the
      // run looks alive even with the modal log collapsed. Entries are
      // {at, src, line} objects (routes.js logLine); tolerate legacy strings.
      var live = el('glLive');
      var lines = run.log || [];
      if (lines.length) {
        var last = lines[lines.length - 1];
        live.style.display = 'block';
        live.textContent = last && last.line != null ? last.line : String(last).replace(/^\S+\s/, '');
      }
      if (run.status === 'running') { setTimeout(function () { poll(id); }, 1500); return; }
      live.style.display = 'none';
      if (run.status === 'error') {
        var failed = (run.stages || []).filter(function (s) { return s.state === 'error'; })[0];
        finishError(run.error || 'unknown failure', !!(failed && failed.key === 'outputs'));
        return;
      }
      S.running = false;
      closeModal();
      el('glRunBtn').disabled = false;
      el('glRunBtn').textContent = 'Run Again';
      renderResults(run.results);
      loadAnalyses(run.results.run.analysis_id);
      openAnalysis(run.results.run.analysis_id, true).then(function () {
        if (S.current.runs.length) el('glRunSel').value = run.results.run.id;
      });
    }).catch(function (e) { finishError(String(e.message || e)); });
  }

  function loadRunResults(runId) {
    var aid = S.current.analysis.id;
    return jfetch(API + '/analyses/' + aid + '/runs/' + runId + '/results').then(function (res) {
      el('glErr').style.display = 'none';
      renderResults(res);
      el('glRunSel').value = runId;
    }).catch(function (e) { showError(String(e.message || e)); });
  }

  // A partial run (build_expected exit 3) writes plan/findings/messages but NO
  // baseline: no daily_kpi.*, no pacing.html, no flowchart.html, no report.md.
  // Rendering those anyway gave two broken iframes and three dead download
  // links on a run the UI still presented as complete.
  // report.md and flowchart.html need only findings.json, so build_expected
  // writes them before the baseline gate - a partial run has both.
  var FULL_ONLY = ['daily_kpi.xlsx', 'daily_kpi.json'];
  var ALWAYS = ['report.md', 'plan.json', 'findings.json', 'chase_messages.md', 'manifest.json', 'run.log'];
  var FILE_ICON = { 'daily_kpi.xlsx': ['xls', 'XLS'], 'run.log': ['doc', 'LOG'] };

  function renderDownloads(base, partial) {
    var box = el('glDls');
    box.innerHTML = '';
    var files = (partial ? [] : FULL_ONLY).concat(ALWAYS);
    files.forEach(function (name) {
      var ic = FILE_ICON[name] || icFor(name);
      var a = document.createElement('a');
      a.className = 'gl-dl';
      a.setAttribute('href', base + '/out/' + name);
      a.setAttribute('download', '');
      a.innerHTML = '<span class="gl-fic ' + ic[0] + '">' + ic[1] + '</span>' + esc(name);
      box.appendChild(a);
    });
  }

  function renderNeedsUpload(res) {
    var needs = res.needs_upload || [];
    var card = el('glNeeds');
    if (!needs.length) { card.style.display = 'none'; return; }
    card.style.display = 'block';
    el('glNeedsCount').textContent = needs.length + (needs.length === 1 ? ' ITEM' : ' ITEMS');
    var box = el('glNeedRows');
    box.innerHTML = '';
    needs.forEach(function (n) {
      var div = document.createElement('div');
      div.className = 'gl-need';
      div.innerHTML = '<span><span class="gl-chip warn">' + esc(n.chip) + '</span></span>'
        + '<span><div class="t">' + esc(n.title) + '</div><div class="d">' + esc(n.detail) + '</div></span>';
      box.appendChild(div);
    });
  }

  function renderRunLog(base) {
    var box = el('glLog');
    box.textContent = 'loading...';
    fetch(base + '/out/run.log', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (t) {
        // Runs archived before run.log existed simply have none - say so rather
        // than showing an empty box that reads like a failure.
        box.textContent = t && t.trim() ? t : 'No log recorded for this run (it predates run logging).';
      })
      .catch(function () { box.textContent = 'Log unavailable.'; });
  }

  function renderResults(res) {
    var base = API + '/analyses/' + res.run.analysis_id + '/runs/' + res.run.id;
    el('glResults').style.display = 'block';
    var partial = !!(res.run && res.run.partial);

    // Partial: say so up front, and hide the two panels whose source files were
    // never written rather than embedding a 404.
    el('glPartialBar').style.display = partial ? 'flex' : 'none';
    if (partial) el('glPartialWhy').textContent = res.run.blocked_reason || 'The dump does not resolve a flight window or any complete media-plan line.';
    // Only the baseline panel depends on files a partial run skipped; the
    // flowchart is findings-derived and is written either way.
    el('glBaselineCard').style.display = partial ? 'none' : 'block';

    renderNeedsUpload(res);
    renderDownloads(base, partial);
    renderRunLog(base);

    var guard = res.meta && res.meta.guard;
    el('glGuard').style.display = guard ? 'block' : 'none';
    if (guard) el('glGuardMsg').textContent = guard.message;

    // What the run actually cost. Duration always; tokens only when the
    // provider reported them - never an invented figure.
    var cost = '';
    if (res.run.duration_ms) {
      var s = Math.round(res.run.duration_ms / 1000);
      cost = ' · took ' + (s >= 60 ? Math.floor(s / 60) + 'm ' + (s % 60) + 's' : s + 's');
    }
    if (res.run.usage && res.run.usage.input_tokens) {
      cost += ' · ' + Number(res.run.usage.input_tokens).toLocaleString() + ' in'
        + (res.run.usage.output_tokens ? ' / ' + Number(res.run.usage.output_tokens).toLocaleString() + ' out' : '') + ' tokens';
    }
    el('glFDesc').textContent = 'Run ' + res.run.id + (partial ? ' (partial)' : '') + ' · extracted by ' + res.run.model + ' · finished ' + res.run.finished_at.replace('T', ' ').slice(0, 19) + ' UTC' + cost + '. Violet rows were authored by the model this run (' + res.origins.model + '); plain rows are deterministic rulebook checks computed in code (' + res.origins.code + ').';
    el('glMDesc').textContent = 'Drafted by ' + res.run.model + ' in run ' + res.run.id + '. A person reviews and sends. One message per recipient.';

    var bust = '?t=' + Date.now();
    el('glFlow').src = base + '/out/flowchart.html' + bust;
    // pacing.html exists only on a complete run - never point at a 404.
    if (partial) el('glPacing').removeAttribute('src');
    else el('glPacing').src = base + '/out/pacing.html' + bust;

    var order = { blocker: 0, missing: 1, gap: 2, inconsistent: 3, watch: 4, housekeeping: 5 };
    var fsSorted = res.findings.slice().sort(function (a, b) { return (order[a.severity] || 9) - (order[b.severity] || 9); });
    var counts = {};
    fsSorted.forEach(function (f) { counts[f.severity] = (counts[f.severity] || 0) + 1; });

    // Severity chips are filters. Everything starts visible; clicking a chip
    // hides that severity, so a 30-finding dump can be read one class at a time
    // without losing the totals - the counts stay on the chips.
    var hidden = {};
    function drawRows() {
      var box = el('glFRows');
      box.innerHTML = '';
      var shown = fsSorted.filter(function (f) { return !hidden[f.severity]; });
      if (!shown.length) {
        box.innerHTML = '<div class="gl-fempty">Every severity is filtered out. Click a chip above to bring findings back.</div>';
        return;
      }
      shown.forEach(function (f) {
        var isAi = f.origin === 'model';
        var div = document.createElement('div');
        div.className = 'gl-frow' + (isAi ? ' ai' : '');
        div.innerHTML = '<span><span class="gl-chip ' + chipClass(f.severity) + '">' + esc(f.chip) + '</span></span>'
          + '<span class="stage">' + esc(f.stage) + '</span>'
          + '<span><div class="t">' + esc(f.title) + '<span class="gl-orig ' + (isAi ? 'ai' : 'code') + '">' + (isAi ? 'AI' : 'CODE') + '</span></div><div class="d">' + esc(f.detail) + '</div></span>'
          + '<span class="src">' + esc(f.source) + '</span>';
        box.appendChild(div);
      });
    }

    var sum = el('glFSum');
    sum.innerHTML = '';
    Object.keys(order).forEach(function (sev) {
      if (!counts[sev]) return;
      var sp = document.createElement('span');
      sp.className = 'gl-chip ' + chipClass(sev);
      sp.textContent = counts[sev] + ' ' + sev.toUpperCase();
      sp.title = 'Click to show or hide ' + sev + ' findings';
      sp.addEventListener('click', function () {
        hidden[sev] = !hidden[sev];
        sp.className = 'gl-chip ' + chipClass(sev) + (hidden[sev] ? ' off' : '');
        drawRows();
      });
      sum.appendChild(sp);
    });
    drawRows();

    var ms = el('glMsgs');
    ms.innerHTML = '';
    (res.messages || []).forEach(function (m) {
      var div = document.createElement('div');
      div.className = 'gl-msg';
      var head = document.createElement('div');
      head.className = 'mh';
      head.innerHTML = '<span class="mt">' + esc(m.title) + (m.recipient ? ' <span style="color:var(--ink-3);font-weight:400">to ' + esc(m.recipient) + '</span>' : '') + '</span>';
      var btn = document.createElement('button');
      btn.className = 'gl-copy';
      btn.textContent = 'Copy';
      btn.addEventListener('click', function () {
        navigator.clipboard.writeText(m.body).then(function () {
          btn.textContent = 'Copied';
          setTimeout(function () { btn.textContent = 'Copy'; }, 1400);
        }).catch(function () { btn.textContent = 'Copy failed'; });
      });
      head.appendChild(btn);
      var pre = document.createElement('pre');
      pre.textContent = m.body;
      div.appendChild(head);
      div.appendChild(pre);
      ms.appendChild(div);
    });
  }

  // ---------------------------------------------------------------- wiring
  function wire() {
    el('glNewBtn').addEventListener('click', function () {
      el('glNameBox').style.display = 'flex';
      el('glNameInput').value = '';
      el('glNameInput').focus();
    });
    el('glNameCancel').addEventListener('click', function () { el('glNameBox').style.display = 'none'; });
    function createAnalysis() {
      var name = el('glNameInput').value;
      el('glNameBox').style.display = 'none';
      jfetch(API + '/analyses', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: name }) })
        .then(function (j) { return loadAnalyses(j.analysis.id).then(function () { return openAnalysis(j.analysis.id); }); })
        .catch(function (e) { showError(String(e.message || e)); });
    }
    el('glNameCreate').addEventListener('click', createAnalysis);
    el('glNameInput').addEventListener('keydown', function (e) { if (e.key === 'Enter') createAnalysis(); });

    el('glASel').addEventListener('change', function () {
      var id = el('glASel').value;
      if (id) openAnalysis(id);
    });

    el('glAName').addEventListener('click', function () {
      if (!S.current) return;
      var name = prompt('Rename analysis', S.current.analysis.name);
      if (name == null) return;
      jfetch(API + '/analyses/' + S.current.analysis.id + '/rename', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: name }) })
        .then(function () { return loadAnalyses(S.current.analysis.id); })
        .then(function () { return openAnalysis(S.current.analysis.id, true); })
        .catch(function (e) { showError(String(e.message || e)); });
    });

    el('glArchBtn').addEventListener('click', function () {
      if (!S.current) return;
      var arch = !S.current.analysis.archived_at;
      jfetch(API + '/analyses/' + S.current.analysis.id + '/archive', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ archived: arch }) })
        .then(function () { return loadAnalyses(S.current.analysis.id); })
        .then(function () { return openAnalysis(S.current.analysis.id, true); })
        .catch(function (e) { showError(String(e.message || e)); });
    });

    el('glDelBtn').addEventListener('click', function () {
      if (!S.current) return;
      if (!confirm('Delete "' + S.current.analysis.name + '" and all its files and runs? This cannot be undone.')) return;
      jfetch(API + '/analyses/' + S.current.analysis.id + '/delete', { method: 'POST' })
        .then(function () {
          S.current = null;
          el('glWorkspace').style.display = 'none';
          el('glEmpty').style.display = '';
          return loadAnalyses();
        })
        .catch(function (e) { showError(String(e.message || e)); });
    });

    var drop = el('glDrop');
    var pickFiles = el('glPickFiles');
    var pickDir = el('glPickDir');
    drop.addEventListener('click', function (e) {
      if (e.target && e.target.tagName === 'B' && /folder/i.test(e.target.textContent)) pickDir.click();
      else pickFiles.click();
    });
    pickFiles.addEventListener('change', function () { uploadFiles(pickFiles.files); pickFiles.value = ''; });
    pickDir.addEventListener('change', function () { uploadFiles(pickDir.files); pickDir.value = ''; });
    ['dragover', 'dragenter'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
    drop.addEventListener('drop', function (e) { if (e.dataTransfer && e.dataTransfer.files) uploadFiles(e.dataTransfer.files); });

    // The whole point of the needs-upload card is the next action, so put the
    // file picker one click away instead of making the user scroll back up.
    el('glNeedsAdd').addEventListener('click', function () {
      drop.scrollIntoView({ behavior: 'smooth', block: 'center' });
      pickFiles.click();
    });

    // Run always goes through the preflight modal: see what will be read and
    // what it will cost before anything is spent.
    el('glRunBtn').addEventListener('click', function () { if (!S.running && !S.uploading) preflight(false); });
    el('glForceBtn').addEventListener('click', function () { if (!S.running) preflight(true); });
    el('glMStart').addEventListener('click', function () {
      if (S.running) return;
      modalToRunning();
      startRun(S.pendingForce);
    });
    el('glMCancel').addEventListener('click', closeModal);
    el('glLogToggle').addEventListener('click', function () {
      var box = el('glLogBox');
      var on = box.className.indexOf('on') > -1;
      box.className = on ? 'mlogbox' : 'mlogbox on';
      el('glLogToggle').textContent = on ? 'Show' : 'Hide';
      if (!on) box.scrollTop = box.scrollHeight;
    });
    el('glModal').addEventListener('click', function (e) { if (e.target === el('glModal')) closeModal(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && el('glModal') && el('glModal').className.indexOf('on') > -1) closeModal();
    });
    el('glRetryBtn').addEventListener('click', function () { startRebuild(); });
    el('glGuardCancel').addEventListener('click', function () { el('glGuardRow').style.display = 'none'; });

    el('glRunSel').addEventListener('change', function () {
      var id = el('glRunSel').value;
      if (id) loadRunResults(id);
    });
  }

  window.Greenlight = {
    render: function (mount) {
      if (S.mounted) return;
      S.mounted = true;
      var style = document.createElement('style');
      style.id = 'greenlight-css';
      style.textContent = CSS;
      document.head.appendChild(style);
      mount.innerHTML = HTML;
      wire();
      loadAnalyses().then(function () {
        // open the most recent unarchived analysis so returning users land in context
        var first = S.analyses.filter(function (a) { return !a.archived_at; })[0];
        if (first) openAnalysis(first.id);
      });
    },
  };
})();
