/*
 * src/brain/brain-historical.js — Brain V3 historical-upload page.
 * BrainHistorical.render(mount, ctx) — ctx: { data (BrainData), toast, theme,
 * clientId, back() }. Talks to the same-origin V3 API (needs `npm run serve`;
 * does not work over file://). UMD -> window.BrainHistorical.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.BrainHistorical = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function money(n) { return n == null ? '—' : '$' + Number(n).toLocaleString('en-AU'); }
  function num(n) { return n == null ? '—' : Number(n).toLocaleString('en-AU'); }
  var CHANNELS = ['Auto-detect', 'TV', 'Print', 'OOH', 'Radio', 'Digital', 'Other'];
  var STATUS = { uploaded: ['Uploaded', 'review'], parsing: ['Parsing', 'review'], needs_review: ['Needs review', 'in_clickup'], ready: ['Parsed', 'measuring'], committed: ['Committed', 'won'], failed: ['Failed', 'rolled_back'] };

  var ICON = {
    up: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 13V3m0 0-4 4m4-4 4 4"/><path d="M20 16.5A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9"/></svg>',
    file: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>'
  };

  var state = { clientId: 'resetdata', channelHint: 'Auto-detect', selected: null, polling: {} };

  function clientName(ctx, id) { return (ctx.data && ctx.data.CLIENT_META[id]) ? ctx.data.CLIENT_META[id].name : id; }

  // ---- shell ----
  function render(mount, ctx) {
    state.clientId = ctx.clientId || state.clientId;
    var clients = ctx.data ? Object.keys(ctx.data.CLIENT_META) : ['resetdata'];
    var clientOpts = clients.map(function (c) { return '<option value="' + c + '"' + (c === state.clientId ? ' selected' : '') + '>' + esc(clientName(ctx, c)) + '</option>'; }).join('');
    var chanOpts = CHANNELS.map(function (c) { return '<option value="' + c + '"' + (c === state.channelHint ? ' selected' : '') + '>' + c + '</option>'; }).join('');

    mount.innerHTML =
      '<div class="bt-wrap">' +
      '<div class="bt-breadcrumb"><button class="bt-crumblink" data-act="home">The Grid</button> <span>›</span> <button class="bt-crumblink" data-act="brain">Brain</button> <span>›</span> ' + esc(clientName(ctx, state.clientId)) + ' <span>›</span> Historical data</div>' +
      '<div class="bt-header"><div><h2 class="bt-h2">Ingest historical campaign data</h2>' +
      '<div class="bt-subtitle">Drop PDFs, PowerPoints, or Excel from off-platform campaigns. Brain parses, maps to timeframes, and feeds the MMM.</div></div></div>' +
      '<div class="bt-hist-controls">' +
      '<label class="bt-fld"><span>Client</span><select id="bh-client" class="bt-select">' + clientOpts + '</select></label>' +
      '<label class="bt-fld"><span>Channel hint</span><select id="bh-chan" class="bt-select">' + chanOpts + '</select></label></div>' +
      '<div class="bt-drop" id="bh-drop" tabindex="0" role="button" aria-label="Upload files">' +
      '<div class="bt-drop-i">' + ICON.up + '</div>' +
      '<div class="bt-drop-t">Drop files here, or click to browse</div>' +
      '<div class="bt-drop-s">PDF · PPTX · XLSX · CSV · up to 50MB per file</div>' +
      '<div class="bt-drop-pills"><span class="bt-tag bt-tag-type">LlamaParse</span><span class="bt-tag bt-tag-type">Claude verification</span><span class="bt-tag bt-tag-type">Dual-LLM consensus</span></div>' +
      '<input type="file" id="bh-input" multiple accept=".pdf,.pptx,.docx,.xlsx,.xls,.csv" style="display:none"></div>' +
      '<div id="bh-progress"></div>' +
      '<section class="card bt-card"><div class="card-h"><h3>Recent uploads</h3></div>' +
      '<div class="card-sub">Files uploaded and their extraction status. Click any file to review the parsed data.</div>' +
      '<div id="bh-uploads" class="bt-uploads"></div></section>' +
      '<div id="bh-detail"></div></div>';

    wire(mount, ctx);
    loadUploads(mount, ctx);
  }

  function wire(mount, ctx) {
    mount.querySelector('[data-act="home"]').addEventListener('click', ctx.back);
    mount.querySelector('[data-act="brain"]').addEventListener('click', ctx.back);
    mount.querySelector('#bh-client').addEventListener('change', function (e) { state.clientId = e.target.value; state.selected = null; try { location.hash = '#view=historical&hc=' + state.clientId; } catch (x) { } render(mount, ctx); });
    mount.querySelector('#bh-chan').addEventListener('change', function (e) { state.channelHint = e.target.value; });
    var drop = mount.querySelector('#bh-drop'), input = mount.querySelector('#bh-input');
    drop.addEventListener('click', function () { input.click(); });
    drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    input.addEventListener('change', function () { handleFiles(mount, ctx, [].slice.call(input.files)); input.value = ''; });
    ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('drag'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('drag'); }); });
    drop.addEventListener('drop', function (e) { handleFiles(mount, ctx, [].slice.call(e.dataTransfer.files)); });
  }

  // ---- upload ----
  function readAsBase64(file) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result).replace(/^data:[^,]+,/, '')); };
      r.onerror = reject; r.readAsDataURL(file);
    });
  }
  async function handleFiles(mount, ctx, files) {
    if (!files.length) return;
    if (files.length > 10) { ctx.toast && ctx.toast.error('Max 10 files at once.'); return; }
    var ok = ['pdf', 'pptx', 'docx', 'xlsx', 'xls', 'csv'];
    for (var i = 0; i < files.length; i++) {
      var ext = files[i].name.split('.').pop().toLowerCase();
      if (ok.indexOf(ext) < 0) { ctx.toast && ctx.toast.error('Unsupported: .' + ext + ' (PDF/PPTX/XLSX/CSV only)'); return; }
      if (files[i].size > 50 * 1024 * 1024) { ctx.toast && ctx.toast.error(files[i].name + ' is over 50MB.'); return; }
    }
    var prog = mount.querySelector('#bh-progress');
    var payloadFiles = [];
    for (var j = 0; j < files.length; j++) {
      prog.insertAdjacentHTML('beforeend', '<div class="bt-progcard" id="bh-pc-' + j + '"><div class="bt-prog-name">' + ICON.file + ' ' + esc(files[j].name) + '</div><div class="bt-prog-bar"><i style="width:5%"></i></div><div class="bt-prog-st">Uploading…</div></div>');
      payloadFiles.push({ filename: files[j].name, data_base64: await readAsBase64(files[j]) });
    }
    var res;
    try {
      res = await (await fetch('/api/brain/historical/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_id: state.clientId, channel_hint: state.channelHint === 'Auto-detect' ? null : state.channelHint, files: payloadFiles }) })).json();
    } catch (e) { ctx.toast && ctx.toast.error('Upload failed — is the server running? (npm run serve)'); prog.innerHTML = ''; return; }
    if (res.error) { ctx.toast && ctx.toast.error(res.error); prog.innerHTML = ''; return; }
    ctx.toast && ctx.toast.success('Uploaded ' + res.files.length + ' file(s) · parsing…');
    res.files.forEach(function (f, idx) { pollJob(mount, ctx, f, idx); });
  }

  function pollJob(mount, ctx, f, idx) {
    var card = mount.querySelector('#bh-pc-' + idx);
    var tries = 0;
    var iv = setInterval(async function () {
      var job;
      try { job = await (await fetch('/api/brain/historical/jobs/' + f.job_id)).json(); } catch (e) { return; }
      if (card) {
        var label = { queued: 'Queued…', parsing: 'Parsing with LlamaParse…', extracting: 'Extracting with Claude…', verifying: 'Verifying (challenger)…', complete: 'Complete', failed: 'Failed' }[job.status] || job.status;
        card.querySelector('.bt-prog-bar i').style.width = job.progress_pct + '%';
        card.querySelector('.bt-prog-st').textContent = label + ' · ' + job.progress_pct + '%';
      }
      if (job.status === 'complete' || job.status === 'failed' || ++tries > 200) {
        clearInterval(iv);
        if (card) card.remove();
        if (job.status === 'failed') ctx.toast && ctx.toast.error(f.filename + ' failed: ' + (job.error_message || 'parse error'));
        else ctx.toast && ctx.toast.success(f.filename + ' parsed · ' + job.row_count + ' rows');
        loadUploads(mount, ctx);
      }
    }, 2000);
  }

  // ---- recent uploads ----
  async function loadUploads(mount, ctx) {
    var box = mount.querySelector('#bh-uploads'); if (!box) return;
    var data;
    try { data = await (await fetch('/api/brain/historical/files?client_id=' + encodeURIComponent(state.clientId))).json(); }
    catch (e) { box.innerHTML = '<div class="empty">Server not reachable. Start it with <code>npm run serve</code>.</div>'; return; }
    var files = data.files || [];
    if (!files.length) { box.innerHTML = '<div class="empty">No uploads yet. Drop a file above to get started.</div>'; return; }
    box.innerHTML = files.map(function (f) {
      var st = STATUS[f.status] || [f.status, 'review'];
      var conf = f.confidence != null ? ' · ' + Math.round(f.confidence * 100) + '%' : '';
      var range = f.date_range ? f.date_range.start + ' → ' + f.date_range.end : '—';
      var action = f.status === 'needs_review' ? 'Fix →' : (f.status === 'failed' ? 'Failed' : 'Review →');
      return '<div class="bt-uprow" data-fid="' + f.id + '"><span class="bt-up-ic">' + ICON.file + '</span>' +
        '<span class="bt-up-name">' + esc(f.filename) + '</span>' +
        '<span class="bt-up-meta">' + (f.channels.join(', ') || '—') + ' · ' + range + ' · ' + (f.row_count || 0) + ' rows</span>' +
        '<span class="bt-pill bt-st-' + st[1] + '">' + st[0] + conf + '</span>' +
        '<span class="bt-up-act">' + action + '</span></div>';
    }).join('');
    box.querySelectorAll('.bt-uprow').forEach(function (r) { r.addEventListener('click', function () { state.selected = r.getAttribute('data-fid'); loadDetail(mount, ctx); }); });
    if (state.selected) loadDetail(mount, ctx);
  }

  // ---- detail table ----
  async function loadDetail(mount, ctx) {
    var box = mount.querySelector('#bh-detail'); if (!box) return;
    var data;
    try { data = await (await fetch('/api/brain/historical/files/' + state.selected + '/rows')).json(); } catch (e) { return; }
    if (data.error) { box.innerHTML = ''; return; }
    var file = data.file, rows = data.rows || [], verif = data.verification;
    if (!rows.length) {
      box.innerHTML = '<section class="card bt-card bt-sec"><div class="bt-sec-h"><h3>Extracted timeline · ' + esc(file.filename) + '</h3></div>' +
        '<div class="empty">No rows extracted.' + (file.file_type === 'pdf' || file.file_type === 'pptx' ? ' PDF/PPTX parsing needs <code>LLAMA_CLOUD_API_KEY</code> in <code>.env</code> — XLSX/CSV parse without it.' : '') + '</div></section>';
      return;
    }
    var months = {}; rows.forEach(function (r) { months[r.period_start && r.period_start.slice(0, 7)] = 1; });
    var totalSpend = rows.reduce(function (a, r) { return a + (r.spend_aud || 0); }, 0);
    var rowsHtml = rows.map(function (r) {
      var flag = r.flagged_for_review ? ' bt-flagged' : '';
      var cell = function (field, val, disp) { return '<td class="bt-ed' + flag + '" contenteditable="true" data-rid="' + r.id + '" data-field="' + field + '">' + esc(disp != null ? disp : (val == null ? '' : val)) + '</td>'; };
      return '<tr>' +
        cell('campaign_name', r.campaign_name) +
        '<td>' + esc(r.channel) + (r.sub_channel ? ' · ' + esc(r.sub_channel) : '') + '</td>' +
        '<td class="bt-flight">' + esc(r.period_start) + ' → ' + esc(r.period_end) + '</td>' +
        cell('spend_aud', r.spend_aud, r.spend_aud == null ? '' : r.spend_aud) +
        '<td>' + (r.reach != null ? num(r.reach) : (r.impressions != null ? num(r.impressions) + ' imp' : '—')) + '</td>' +
        '<td class="bt-src">' + esc(r.source_citation || '—') + '</td>' +
        '<td class="bt-num"><span class="bt-conf">' + Math.round(r.confidence * 100) + '%</span></td></tr>';
    }).join('');

    var checks = (verif && verif.checks) ? verif.checks : [];
    var checksHtml = checks.length ? checks.map(function (c) { return '<div class="bt-check ' + (c.pass ? 'ok' : 'bad') + '">' + (c.pass ? '✓' : '✕') + ' ' + esc(c.label) + ' <span>' + esc(c.detail || '') + '</span></div>'; }).join('')
      : '<div class="bt-check ok">✓ Verification ran (' + (verif && verif._mode === 'rule' ? 'rule-based' : 'Claude challenger') + ')</div>';
    var committed = file.status === 'committed';

    box.innerHTML =
      '<section class="card bt-card bt-sec"><div class="bt-sec-h"><h3>Extracted timeline · ' + esc(file.filename) + '</h3></div>' +
      '<div class="bt-sec-sub">Brain parsed ' + rows.length + ' campaign flights across ' + Object.keys(months).length + ' month(s). Edit any value inline before committing to warehouse.</div>' +
      '<div class="tableScroll"><table class="bt-table"><thead><tr><th>Campaign</th><th>Channel</th><th>Flight</th><th>Spend</th><th>Reach</th><th>Source in file</th><th class="bt-num">Conf.</th></tr></thead><tbody>' + rowsHtml + '</tbody></table></div></section>' +
      '<section class="bt-sidecards"><div class="card bt-card"><div class="card-h"><h3>Time-period mapping</h3></div>' +
      '<div class="seg bt-grain" role="group"><button aria-pressed="false" data-g="day">Day</button><button aria-pressed="true" data-g="week">Week</button><button aria-pressed="false" data-g="month">Month</button></div>' +
      '<div class="bt-grain-note" id="bh-grain-note"></div>' +
      '<p class="bt-detail" style="margin-top:10px">Weekly is the default grain — it balances signal and noise for MMM, and matches how most media plans flight. Day and month amortization arrive in V3.5.</p></div>' +
      '<div class="card bt-card"><div class="card-h"><h3>Verification checks</h3></div><div class="card-sub">Dual-LLM consensus (or rule-based fallback) results.</div><div class="bt-checks">' + checksHtml + '</div></div></section>' +
      '<section class="card bt-card bt-bottombar"><div class="bt-bottombar-txt">Committing will add ' + rows.length + ' campaigns · ' + money(Math.round(totalSpend)) + ' spend · ' + Object.keys(months).length + ' months to ' + esc(clientName(ctx, file.client_id)) + '’s historical warehouse. Feeds into MMM on next model rebuild.</div>' +
      (committed ? '<button class="bt-btn bt-btn-done" disabled>Committed ✓</button>' : '<button class="bt-btn bt-btn-primary" id="bh-commit">Commit to warehouse</button>') + '</section>';

    // inline edit
    box.querySelectorAll('.bt-ed').forEach(function (td) {
      td.addEventListener('blur', async function () {
        var field = td.getAttribute('data-field'), rid = td.getAttribute('data-rid');
        var v = td.textContent.trim();
        var patch = {}; patch[field] = (field === 'spend_aud') ? (v === '' ? null : Number(v.replace(/[^0-9.\-]/g, ''))) : v;
        try { await fetch('/api/brain/historical/rows/' + rid, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }); ctx.toast && ctx.toast.info('Saved'); }
        catch (e) { ctx.toast && ctx.toast.error('Save failed'); }
      });
    });
    box.querySelectorAll('.bt-grain button').forEach(function (b) {
      b.addEventListener('click', function () {
        box.querySelectorAll('.bt-grain button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        var g = b.getAttribute('data-g'), n = box.querySelector('#bh-grain-note');
        if (n) n.textContent = g === 'week' ? '' : (g[0].toUpperCase() + g.slice(1) + ' grain coming in V3.5 — currently weekly.');
      });
    });
    var cb = box.querySelector('#bh-commit');
    if (cb) cb.addEventListener('click', async function () {
      cb.disabled = true; cb.textContent = 'Committing…';
      try {
        var r = await (await fetch('/api/brain/historical/files/' + state.selected + '/commit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ committed_by: 'grid-user' }) })).json();
        if (r.error) throw new Error(r.error);
        ctx.toast && ctx.toast.success('Committed ' + r.snapshot.row_count + ' rows → ' + r.snapshot.target_bq_dataset);
        loadUploads(mount, ctx);
      } catch (e) { cb.disabled = false; cb.textContent = 'Commit to warehouse'; ctx.toast && ctx.toast.error('Commit failed: ' + e.message); }
    });
  }

  return { render: render };
});
