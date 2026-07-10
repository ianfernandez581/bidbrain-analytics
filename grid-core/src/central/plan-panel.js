/*
 * src/central/plan-panel.js — media-plan dropzone + review/commit panel.
 * ----------------------------------------------------------------------------
 * mount(host, api) paints the dropzone into `host` (below the Central table).
 * A dropped/selected file is uploaded (base64 JSON, same as Brain), then the
 * extraction opens a slide-in review panel: pick a matching campaign (or "create
 * new"), review/edit every CONFIG field (pre-filled from the plan, provenance
 * shown, low-confidence flagged), resolve any conflicts (keep/replace, default
 * KEEP), and commit the USER-CONFIRMED values. Manual typing is always available
 * (null fields are just empty inputs; "enter manually" opens the panel with no
 * file). Extraction NEVER writes a row — commit does, and only what's confirmed.
 *
 * UMD: browser -> window.CentralPlan.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.CentralPlan = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var OK_EXT = ['xlsx', 'xls', 'csv', 'pdf', 'docx', 'pptx'];
  var MAX = 15 * 1024 * 1024;
  var FIELD_LABELS = {
    jobNumber: 'Job Number', client: 'Client', name: 'Campaign', objective: 'Objective', channel: 'Channel',
    managedBy: 'Managed By', startDate: 'Start Date', endDate: 'End Date', platformMargin: 'Platform Margin',
    adServingCost: 'Ad-Serving Cost', forecastCpm: 'Forecast CPM', keyKpi: 'Key KPI', kpiTarget: 'KPI Target',
    budgetGross: 'Budget Gross', totalBudget: 'Total Budget', spendMult: 'Spend Multiplier', notes: 'Notes'
  };
  var ORDER = ['jobNumber', 'client', 'name', 'objective', 'channel', 'managedBy', 'startDate', 'endDate',
    'platformMargin', 'spendMult', 'adServingCost', 'forecastCpm', 'budgetGross', 'totalBudget', 'keyKpi', 'kpiTarget', 'notes'];

  var _api = null;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function toastOk(m) { if (window.toast) window.toast.success(m); }
  function toastErr(m) { if (window.toast) window.toast.error(m); }

  // ---------------------------------------------------------------- dropzone
  function mount(host, api) {
    _api = api;
    host.innerHTML =
      '<div class="ct-dz" id="ct-dz" tabindex="0" role="button" aria-label="Upload a media plan">' +
      '<div class="ct-dzicon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></svg></div>' +
      '<h4>Drop a media plan to auto-fill campaign details</h4>' +
      '<p>Excel, PDF, Word, or CSV · or <a id="ct-dz-browse">browse</a> · or <a id="ct-dz-manual">enter details manually</a></p>' +
      '<div class="ct-progress" id="ct-dz-prog" style="display:none"><i></i></div>' +
      '<div class="ct-dzerr" id="ct-dz-err" style="display:none"></div>' +
      '<input type="file" id="ct-dz-input" accept=".xlsx,.xls,.csv,.pdf,.docx,.pptx" style="display:none">' +
      '</div>';
    var dz = host.querySelector('#ct-dz'), input = host.querySelector('#ct-dz-input');
    var browse = host.querySelector('#ct-dz-browse'), manual = host.querySelector('#ct-dz-manual');
    browse.addEventListener('click', function (e) { e.stopPropagation(); input.click(); });
    manual.addEventListener('click', function (e) { e.stopPropagation(); openManual(); });
    dz.addEventListener('click', function () { input.click(); });
    dz.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    input.addEventListener('change', function () { if (input.files && input.files[0]) handleFile(input.files[0]); input.value = ''; });
    ['dragenter', 'dragover'].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add('drag'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); if (ev === 'dragleave' && dz.contains(e.relatedTarget)) return; dz.classList.remove('drag'); }); });
    dz.addEventListener('drop', function (e) { var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) handleFile(f); });
  }

  function dzErr(msg, offerManual) {
    var el = document.getElementById('ct-dz-err'); if (!el) return;
    el.style.display = ''; el.innerHTML = esc(msg) + (offerManual !== false ? ' <a id="ct-dz-err-manual">enter details manually</a>' : '');
    var m = document.getElementById('ct-dz-err-manual'); if (m) m.addEventListener('click', function (e) { e.stopPropagation(); openManual(); });
    var p = document.getElementById('ct-dz-prog'); if (p) p.style.display = 'none';
  }

  function handleFile(file) {
    var errEl = document.getElementById('ct-dz-err'); if (errEl) errEl.style.display = 'none';
    var ext = (file.name.split('.').pop() || '').toLowerCase();
    if (OK_EXT.indexOf(ext) < 0) return dzErr('Unsupported file type ".' + ext + '". Allowed: Excel, PDF, Word, CSV.');
    if (file.size > MAX) return dzErr('That file is ' + (file.size / 1048576).toFixed(1) + 'MB — the limit is 15MB.');
    var prog = document.getElementById('ct-dz-prog'); var bar = prog && prog.querySelector('i');
    if (prog) { prog.style.display = ''; bar.style.width = '15%'; }
    var reader = new FileReader();
    reader.onprogress = function (e) { if (bar && e.lengthComputable) bar.style.width = (10 + (e.loaded / e.total) * 40) + '%'; };
    reader.onerror = function () { dzErr('Could not read that file.'); };
    reader.onload = function () {
      if (bar) bar.style.width = '60%';
      fetch('/api/central/plan/upload', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, mime: file.type || undefined, data_base64: String(reader.result).replace(/^data:[^,]+,/, '') })
      }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (x) {
          if (bar) bar.style.width = '100%';
          setTimeout(function () { if (prog) prog.style.display = 'none'; if (bar) bar.style.width = '0'; }, 300);
          if (!x.ok) return dzErr((x.d && x.d.error) || 'Upload failed.');
          openPanel(x.d);
        }).catch(function () { dzErr('Upload failed — is the server running?'); });
    };
    reader.readAsDataURL(file);
  }

  function openManual() {
    // empty extraction → the same panel, all blanks, for hand entry
    var fields = {}; ['jobNumber', 'client', 'name', 'objective', 'channel', 'managedBy', 'startDate', 'endDate',
      'platformMargin', 'adServingCost', 'forecastCpm', 'keyKpi', 'kpiTarget', 'budgetGross', 'totalBudget', 'spendMult', 'notes']
      .forEach(function (f) { fields[f] = { value: null, confidence: null }; });
    openPanel({ id: null, filename: null, mode: 'manual', fields: fields, candidates: [] });
  }

  // ---------------------------------------------------------------- review panel
  var _state = null;
  function openPanel(result) {
    injectCss();
    close(); // any prior
    _state = { id: result.id, filename: result.filename, fields: result.fields || {}, candidates: result.candidates || [], choice: null, keep: {} };

    var back = document.createElement('div'); back.className = 'ct-pnl-back'; back.id = 'ct-pnl-back';
    var pnl = document.createElement('aside'); pnl.className = 'ct-pnl'; pnl.id = 'ct-pnl';
    pnl.innerHTML = panelHtml();
    back.appendChild(pnl);
    document.body.appendChild(back);
    requestAnimationFrame(function () { back.classList.add('in'); });
    wirePanel(pnl, back);
    renderFields(pnl);
  }
  function close() { var b = document.getElementById('ct-pnl-back'); if (b && b.parentNode) b.parentNode.removeChild(b); }

  function panelHtml() {
    var s = _state;
    var src = s.filename ? ('Extracted from <b>' + esc(s.filename) + '</b>' + (_state && s.mode ? '' : '')) : 'Manual entry — type the details below';
    var cands = s.candidates.map(function (c, i) {
      return '<label class="ct-cand"><input type="radio" name="ct-match" value="' + esc(c.rowId) + '"><span class="ct-cand-main"><b>' + esc(c.client) + '</b> · ' + esc(c.name) + '</span>' +
        '<span class="ct-cand-score">' + esc(c.reason) + ' ' + Math.round(c.score * 100) + '%</span></label>';
    }).join('');
    return '<div class="ct-pnl-h"><div><h3>Review media plan</h3><div class="ct-pnl-src">' + src + '</div></div><button class="ct-pnl-x" id="ct-pnl-x" aria-label="Close">✕</button></div>' +
      '<div class="ct-pnl-body">' +
      '<div class="ct-pnl-sec">Match to a campaign</div>' +
      '<div class="ct-cands">' + cands +
      '<label class="ct-cand ct-cand-new"><input type="radio" name="ct-match" value="__new__"><span class="ct-cand-main"><b>+ Create new campaign row</b></span></label>' +
      '</div>' +
      '<div class="ct-pnl-sec">Fields</div><div class="ct-fields" id="ct-fields"></div>' +
      '</div>' +
      '<div class="ct-pnl-foot"><button class="ct-btn" id="ct-pnl-cancel">Discard</button><button class="ct-btn ct-btn-primary" id="ct-pnl-commit" disabled>Commit</button></div>';
  }

  function currentRowFor(rowId) {
    var rows = (_api && _api.getRows && _api.getRows()) || [];
    return rows.find(function (r) { return r._id === rowId; }) || null;
  }

  function renderFields(pnl) {
    var s = _state;
    var matched = (s.choice && s.choice !== '__new__') ? currentRowFor(s.choice) : null;
    var host = pnl.querySelector('#ct-fields'); var html = '';
    ORDER.forEach(function (f) {
      var fo = s.fields[f] || { value: null };
      var val = fo.value;
      var prov = fo.cellRef ? (esc((fo.sheet ? fo.sheet + '!' : '') + fo.cellRef)) : (fo.page != null ? ('p' + fo.page) : '');
      var low = fo.confidence === 'low';
      var lowDot = low ? '<span class="ct-lowdot" title="low confidence — please verify">●</span>' : '';
      var cur = matched ? matched[f] : undefined;
      var conflict = matched && cur != null && !eq(cur, val) && f !== 'client' && f !== 'name';
      var inputVal = val == null ? '' : val;
      var row = '<div class="ct-field" data-f="' + f + '">' +
        '<div class="ct-field-l">' + esc(FIELD_LABELS[f] || f) + lowDot + (prov ? '<span class="ct-prov" title="source">' + prov + '</span>' : '') + '</div>';
      if (conflict) {
        row += '<div class="ct-conflict"><span class="ct-cf-old">current: <b>' + esc(cur) + '</b></span> → <span class="ct-cf-new">plan: <b>' + esc(val) + '</b></span>' +
          '<span class="ct-cf-toggle"><button class="ct-cf-btn on" data-keep="' + f + '">Keep</button><button class="ct-cf-btn" data-replace="' + f + '">Replace</button></span>' +
          '<input class="ct-input" data-field="' + f + '" value="' + esc(inputVal) + '" disabled></div>';
      } else {
        row += '<input class="ct-input" data-field="' + f + '" value="' + esc(inputVal) + '" placeholder="—">';
      }
      row += '</div>';
      html += row;
    });
    host.innerHTML = html;
    // conflict keep/replace toggles
    host.querySelectorAll('[data-keep]').forEach(function (b) { b.addEventListener('click', function () { setKeep(b.dataset.keep, true, host); }); });
    host.querySelectorAll('[data-replace]').forEach(function (b) { b.addEventListener('click', function () { setKeep(b.dataset.replace, false, host); }); });
    // default all conflicts to KEEP (safe)
    ORDER.forEach(function (f) { var matchedRow = matched; var fo = s.fields[f] || {}; if (matchedRow && matchedRow[f] != null && !eq(matchedRow[f], fo.value) && f !== 'client' && f !== 'name') { if (s.keep[f] === undefined) s.keep[f] = true; } });
  }

  function setKeep(field, keep, host) {
    _state.keep[field] = keep;
    var wrap = host.querySelector('.ct-field[data-f="' + field + '"]');
    if (!wrap) return;
    wrap.querySelector('[data-keep]').classList.toggle('on', keep);
    wrap.querySelector('[data-replace]').classList.toggle('on', !keep);
    var inp = wrap.querySelector('.ct-input'); if (inp) inp.disabled = keep;
  }

  function wirePanel(pnl, back) {
    pnl.querySelector('#ct-pnl-x').addEventListener('click', discardClose);
    pnl.querySelector('#ct-pnl-cancel').addEventListener('click', discardClose);
    back.addEventListener('click', function (e) { if (e.target === back) discardClose(); });
    pnl.querySelectorAll('input[name="ct-match"]').forEach(function (radio) {
      radio.addEventListener('change', function () { _state.choice = radio.value; _state.keep = {}; renderFields(pnl); pnl.querySelector('#ct-pnl-commit').disabled = false; });
    });
    pnl.querySelector('#ct-pnl-commit').addEventListener('click', function () { commit(pnl); });
  }

  function discardClose() {
    if (_state && _state.id) { fetch('/api/central/plan/' + _state.id + '/discard', { method: 'POST' }).catch(function () { }); }
    close();
  }

  function commit(pnl) {
    var s = _state;
    if (!s.choice) return;
    var createNew = s.choice === '__new__';
    var matched = createNew ? null : currentRowFor(s.choice);
    var fields = {}, ack = [];
    pnl.querySelectorAll('.ct-input').forEach(function (inp) {
      var f = inp.dataset.field;
      var raw = inp.value.trim();
      var val = raw === '' ? null : coerceLike(f, raw, s.fields[f]);
      if (createNew) { if (val != null) fields[f] = val; return; }
      var cur = matched ? matched[f] : null;
      var isConflict = cur != null && !eq(cur, (s.fields[f] || {}).value) && f !== 'client' && f !== 'name';
      if (isConflict) {
        if (s.keep[f] === false) { fields[f] = val; ack.push(f); }   // REPLACE
        // KEEP → do not send (leave existing untouched)
      } else if (val != null && !eq(cur, val)) {
        fields[f] = val;                                            // new / changed non-conflict
      }
    });
    if (createNew && (!fields.client || !fields.name)) { toastErr('A new campaign needs a client and a campaign name.'); return; }
    if (!createNew && Object.keys(fields).length === 0) { toastOk('Nothing to change.'); close(); return; }

    var btn = pnl.querySelector('#ct-pnl-commit'); btn.disabled = true; btn.textContent = 'Committing…';
    var body = createNew ? { createNew: true, fields: fields } : { rowId: s.choice, fields: fields, acknowledgeConflicts: ack };
    fetch('/api/central/plan/' + (s.id || 'manual') + '/commit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) { toastErr((x.d && x.d.error) || 'Commit failed'); btn.disabled = false; btn.textContent = 'Commit'; return; }
        toastOk((x.d.fieldsWritten || Object.keys(fields).length) + ' field' + ((x.d.fieldsWritten || 1) === 1 ? '' : 's') + ' updated' + (s.filename ? ' from ' + s.filename : ''));
        close();
        if (_api && _api.onCommitted) _api.onCommitted();
      }).catch(function () { toastErr('Commit failed — server offline?'); btn.disabled = false; btn.textContent = 'Commit'; });
  }

  // manual-entry commit has no extraction id; POST to a synthetic id fails the draft
  // lookup, so for manual we always use createNew (id path is only for real drafts).
  function eq(a, b) {
    if (a == null && b == null) return true;
    if (a == null || b == null) return false;
    var na = Number(a), nb = Number(b);
    if (!isNaN(na) && !isNaN(nb) && String(a).trim() !== '' && String(b).trim() !== '') return na === nb;
    return String(a).trim() === String(b).trim();
  }
  // send numbers as numbers when the extracted value was numeric (keeps parity with seed types)
  function coerceLike(field, raw, fo) {
    var wasNum = fo && typeof fo.value === 'number';
    if (wasNum) { var n = Number(raw); if (!isNaN(n)) return n; }
    return raw;
  }

  // ---------------------------------------------------------------- add campaign
  // Create a thin campaign row (Task 3.3). section+client+name required; the rest
  // optional (fill later / via a plan). POSTs /api/central/campaigns.
  function openAdd(api) {
    injectCss(); close();
    var clients = (api && api.clients) || [];
    var back = document.createElement('div'); back.className = 'ct-pnl-back'; back.id = 'ct-pnl-back';
    var pnl = document.createElement('aside'); pnl.className = 'ct-pnl'; pnl.id = 'ct-pnl';
    var dl = '<datalist id="ct-add-clients">' + clients.map(function (c) { return '<option value="' + esc(c) + '">'; }).join('') + '</datalist>';
    var fld = function (label, field, attrs) { return '<div class="ct-field"><div class="ct-field-l">' + esc(label) + '</div><input class="ct-input" data-field="' + field + '" ' + (attrs || '') + '></div>'; };
    pnl.innerHTML =
      '<div class="ct-pnl-h"><div><h3>Add campaign</h3><div class="ct-pnl-src">Create a thin row now, fill the details in later (by hand or from a media plan). Only Section, Client and Campaign are required.</div></div><button class="ct-pnl-x" id="ct-pnl-x" aria-label="Close">✕</button></div>' +
      '<div class="ct-pnl-body">' + dl + '<div class="ct-fields">' +
      '<div class="ct-field"><div class="ct-field-l">Section *</div><select class="ct-input" data-field="section"><option value="100% Digital">100% Digital</option><option value="Transmission">Transmission</option></select></div>' +
      '<div class="ct-field"><div class="ct-field-l">Client *</div><input class="ct-input" data-field="client" list="ct-add-clients" placeholder="client name"></div>' +
      fld('Campaign *', 'name', 'placeholder="campaign name"') +
      fld('Objective', 'objective') + fld('Channel', 'channel', 'placeholder="Trade Desk / LinkedIn / …"') + fld('Managed By', 'managedBy') +
      '<div class="ct-field"><div class="ct-field-l">Status</div><select class="ct-input" data-field="status"><option value="Draft" selected>Draft</option><option>Active</option><option>Paused</option><option>Not Active</option><option>Ended</option></select></div>' +
      fld('Platform Margin', 'platformMargin', 'placeholder="0.2 or 20%"') + fld('Forecast CPM', 'forecastCpm') +
      fld('Budget Gross', 'budgetGross') + fld('Total Budget', 'totalBudget') +
      fld('Start Date', 'startDate', 'placeholder="YYYY-MM-DD"') + fld('End Date', 'endDate', 'placeholder="YYYY-MM-DD"') +
      fld('Key KPI', 'keyKpi', 'placeholder="e.g. 300 opt-ins"') + fld('Notes', 'notes') +
      '</div></div>' +
      '<div class="ct-pnl-foot"><button class="ct-btn" id="ct-pnl-cancel">Cancel</button><button class="ct-btn ct-btn-primary" id="ct-add-submit">Create</button></div>';
    back.appendChild(pnl); document.body.appendChild(back);
    requestAnimationFrame(function () { back.classList.add('in'); });
    pnl.querySelector('#ct-pnl-x').addEventListener('click', close);
    pnl.querySelector('#ct-pnl-cancel').addEventListener('click', close);
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    pnl.querySelector('#ct-add-submit').addEventListener('click', function () { submitAdd(pnl, api); });
  }
  function numish(field, raw) {
    if (raw === '') return undefined;
    if (field === 'platformMargin') { var p = parseFloat(String(raw).replace(/[%\s]/g, '')); if (isNaN(p)) return raw; return (String(raw).indexOf('%') >= 0 || p > 1) ? p / 100 : p; }
    if (['forecastCpm', 'budgetGross', 'totalBudget', 'spendMult', 'adServingCost'].indexOf(field) >= 0) { var s = String(raw).replace(/[$,\s]/g, ''), m = 1; if (/[kK]$/.test(s)) { m = 1000; s = s.slice(0, -1); } var n = parseFloat(s); return isNaN(n) ? raw : n * m; }
    return raw;
  }
  function submitAdd(pnl, api) {
    var body = {};
    pnl.querySelectorAll('[data-field]').forEach(function (el) { var v = (el.value || '').trim(); if (v !== '') { var c = numish(el.dataset.field, v); if (c !== undefined) body[el.dataset.field] = c; } });
    if (!body.section || !body.client || !body.name) { toastErr('Section, Client and Campaign are required.'); return; }
    var btn = pnl.querySelector('#ct-add-submit'); btn.disabled = true; btn.textContent = 'Creating…';
    fetch('/api/central/campaigns', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) { if (!x.ok) { toastErr((x.d && x.d.error) || 'Create failed'); btn.disabled = false; btn.textContent = 'Create'; return; } toastOk('Campaign added'); close(); if (api && api.onCreated) api.onCreated(); })
      .catch(function () { toastErr('Create failed — server offline?'); btn.disabled = false; btn.textContent = 'Create'; });
  }

  // ---------------------------------------------------------------- reconcile / map client
  // Suggestions ONLY (fuzzy) — a human ticks the pairs to approve; approved pairs are
  // written to central-clients.json (validated:true). Nothing is auto-mapped.
  function openReconcile(api) {
    injectCss(); close();
    var clients = (api && api.clients) || [];
    var back = document.createElement('div'); back.className = 'ct-pnl-back'; back.id = 'ct-pnl-back';
    var pnl = document.createElement('aside'); pnl.className = 'ct-pnl'; pnl.id = 'ct-pnl';
    var cov = (api && api.coverage && api.coverage.clients) || [];
    var covBy = {}; cov.forEach(function (c) { covBy[c.client] = c; });
    var statusFor = function (name) {
      var c = covBy[name]; if (!c) return '';
      if (c.source === 'none') return '<span class="ct-rc-stat ct-rc-none">no BQ data</span>';
      if (c.validated) return '<span class="ct-rc-stat ct-rc-ok">✓ mapped (' + c.mapped + ')</span>';
      return '<span class="ct-rc-stat ct-rc-todo">' + c.mapped + ' mapped · not validated</span>';
    };
    pnl.innerHTML =
      '<div class="ct-pnl-h"><div><h3>Map a client</h3><div class="ct-pnl-src">Fetch a client\'s BQ campaign names, then approve the pairs to make it live. Suggestions are fuzzy — you confirm each one.</div></div><button class="ct-pnl-x" id="ct-pnl-x" aria-label="Close">✕</button></div>' +
      '<div class="ct-pnl-body">' +
      '<div class="ct-filters"><label class="ct-fld"><span>Client</span><select id="ct-rc-client" class="ct-select">' +
      clients.map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('') +
      '</select></label><span id="ct-rc-status">' + statusFor(clients[0]) + '</span><button class="ct-btn" id="ct-rc-load">Load BQ names</button></div>' +
      '<div id="ct-rc-results"><div class="ct-pnl-src" style="padding:10px 0">Pick a client and load its BQ names.</div></div>' +
      '</div>' +
      '<div class="ct-pnl-foot"><button class="ct-btn" id="ct-pnl-cancel">Close</button><button class="ct-btn ct-btn-primary" id="ct-rc-approve" disabled>Approve selected</button></div>';
    back.appendChild(pnl); document.body.appendChild(back);
    requestAnimationFrame(function () { back.classList.add('in'); });
    pnl.querySelector('#ct-pnl-x').addEventListener('click', close);
    pnl.querySelector('#ct-pnl-cancel').addEventListener('click', close);
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    var csel = pnl.querySelector('#ct-rc-client');
    csel.addEventListener('change', function () { var st = pnl.querySelector('#ct-rc-status'); if (st) st.innerHTML = statusFor(csel.value); });
    pnl.querySelector('#ct-rc-load').addEventListener('click', function () { loadReconcile(pnl); });
    pnl.querySelector('#ct-rc-approve').addEventListener('click', function () { approveReconcile(pnl, api); });
  }
  function loadReconcile(pnl) {
    var client = pnl.querySelector('#ct-rc-client').value;
    var host = pnl.querySelector('#ct-rc-results');
    host.innerHTML = '<div class="ct-pnl-src" style="padding:10px 0">Loading…</div>';
    fetch('/api/central/reconcile/' + encodeURIComponent(client)).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        pnl.dataset.client = client;
        if (!x.ok) { host.innerHTML = '<div class="ct-dzerr">' + esc((x.d && x.d.error) || 'Failed to load BQ names') + '</div>'; return; }
        var d = x.d;
        var camps = d.centralCampaigns || [];
        if (d.error) host.innerHTML = '<div class="ct-dzerr">BQ: ' + esc(d.error) + '</div>';
        else host.innerHTML = '';
        if (!(d.bqNames || []).length) { host.innerHTML += '<div class="ct-pnl-src" style="padding:8px 0">No BQ campaign names returned for ' + esc(client) + '. (' + camps.length + ' Central campaigns.)</div>'; return; }
        var opts = camps.map(function (c) { return { v: c.id, t: c.name + (c.channel ? ' · ' + c.channel : '') }; });
        host.innerHTML += '<div class="ct-pnl-sec">BQ names → Central (' + d.bqNames.length + ' BQ · ' + camps.length + ' Central)</div>';
        host.innerHTML += (d.suggestions || []).map(function (s, i) {
          var sel = '<select class="ct-input ct-rc-camp" data-i="' + i + '">' +
            '<option value="">— (skip) —</option>' +
            opts.map(function (o) { return '<option value="' + esc(o.v) + '"' + (o.v === s.campaignId ? ' selected' : '') + '>' + esc(o.t) + '</option>'; }).join('') + '</select>';
          var mode = '<select class="ct-input ct-rc-mode" data-i="' + i + '"><option value="exact">exact</option><option value="contains">contains</option><option value="rollup">rollup</option></select>';
          return '<div class="ct-field ct-rc-row"><label class="ct-rc-lbl"><input type="checkbox" class="ct-rc-ck" data-i="' + i + '" data-bq="' + esc(s.bqName) + '" data-channel="' + esc(s.channel || '') + '" data-adv="' + esc(s.advertiserName || '') + '"> <b>' + esc(s.bqName) + '</b> <span class="ct-prov">' + (s.channel ? esc(s.channel) + ' · ' : '') + Math.round((s.score || 0) * 100) + '%</span></label>' + sel + mode + '</div>';
        }).join('');
        pnl.querySelector('#ct-rc-approve').disabled = false;
      }).catch(function () { host.innerHTML = '<div class="ct-dzerr">Reconcile failed — server offline?</div>'; });
  }
  function approveReconcile(pnl, api) {
    var client = pnl.dataset.client;
    var pairs = [];
    pnl.querySelectorAll('.ct-rc-ck').forEach(function (ck) {
      if (!ck.checked) return;
      var i = ck.dataset.i;
      var sel = pnl.querySelector('.ct-rc-camp[data-i="' + i + '"]');
      var modeSel = pnl.querySelector('.ct-rc-mode[data-i="' + i + '"]');
      var cid = sel ? sel.value : '';
      // per-row match schema: channel + advertiserName + campaignMatch{mode,value}
      if (cid) pairs.push({ campaignId: cid, channel: ck.dataset.channel || null, advertiserName: ck.dataset.adv || null, value: ck.dataset.bq, mode: modeSel ? modeSel.value : 'exact' });
    });
    if (!pairs.length) { toastErr('Tick at least one pair (with a Central campaign) to approve.'); return; }
    var btn = pnl.querySelector('#ct-rc-approve'); btn.disabled = true; btn.textContent = 'Approving…';
    fetch('/api/central/reconcile/' + encodeURIComponent(client) + '/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pairs: pairs }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) { if (!x.ok) { toastErr((x.d && x.d.error) || 'Approve failed'); btn.disabled = false; btn.textContent = 'Approve selected'; return; } toastOk(x.d.added + ' mapping(s) approved · ' + client + ' now ' + (x.d.validated ? 'validated' : 'unvalidated')); close(); if (api && api.onApproved) api.onApproved(); })
      .catch(function () { toastErr('Approve failed — server offline?'); btn.disabled = false; btn.textContent = 'Approve selected'; });
  }

  // ---------------------------------------------------------------- css
  function injectCss() {
    if (document.getElementById('ct-pnl-css')) return;
    var s = document.createElement('style'); s.id = 'ct-pnl-css';
    s.textContent = [
      '.ct-pnl-back{position:fixed;inset:0;z-index:120;background:rgba(0,0,0,.34);opacity:0;transition:opacity .18s}.ct-pnl-back.in{opacity:1}',
      '.ct-pnl{position:absolute;top:0;right:0;height:100%;width:min(520px,94vw);background:var(--panel);border-left:1px solid var(--line);box-shadow:-16px 0 40px -20px rgba(0,0,0,.5);display:flex;flex-direction:column;transform:translateX(100%);transition:transform .2s}.ct-pnl-back.in .ct-pnl{transform:translateX(0)}',
      '.ct-pnl-h{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:18px 20px 12px;border-bottom:1px solid var(--line)}',
      '.ct-pnl-h h3{font-family:"Space Grotesk";margin:0;font-size:17px;font-weight:600}.ct-pnl-src{font-size:11.5px;color:var(--ink-2);margin-top:3px}',
      '.ct-pnl-x{appearance:none;border:0;background:transparent;color:var(--ink-3);font-size:16px;cursor:pointer;padding:4px 8px;border-radius:6px}.ct-pnl-x:hover{color:var(--ink);background:var(--line-2)}',
      '.ct-pnl-body{flex:1 1 auto;overflow-y:auto;padding:14px 20px}',
      '.ct-pnl-sec{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin:8px 0 8px}',
      '.ct-cands{display:flex;flex-direction:column;gap:7px;margin-bottom:8px}',
      '.ct-cand{display:flex;align-items:center;gap:9px;padding:9px 11px;border:1px solid var(--line);border-radius:9px;cursor:pointer;font-size:12.5px}',
      '.ct-cand:hover{border-color:var(--brand)}.ct-cand input{accent-color:var(--brand)}.ct-cand-main{flex:1 1 auto}.ct-cand-score{font-size:10.5px;color:var(--ink-3)}',
      '.ct-cand-new{border-style:dashed}',
      '.ct-fields{display:flex;flex-direction:column;gap:9px}',
      '.ct-field{display:flex;flex-direction:column;gap:4px}',
      '.ct-field-l{font-size:10.5px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--ink-3);display:flex;align-items:center;gap:7px}',
      '.ct-lowdot{color:var(--warn);font-size:9px}.ct-prov{margin-left:auto;font-size:10px;color:var(--ink-3);font-weight:500;text-transform:none;letter-spacing:0;background:var(--line-2);padding:1px 6px;border-radius:5px}',
      '.ct-input{font-family:inherit;font-size:13px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:7px 10px;outline:none}',
      '.ct-input:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}.ct-input:disabled{opacity:.55}',
      '.ct-conflict{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11.5px;background:var(--warn-soft);border:1px solid var(--warn);border-radius:8px;padding:7px 9px}',
      '.ct-cf-old{color:var(--ink-2)}.ct-cf-new{color:var(--warn)}.ct-cf-toggle{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}',
      '.ct-cf-btn{appearance:none;border:0;background:var(--panel);color:var(--ink-2);font-family:inherit;font-size:11px;font-weight:600;padding:3px 9px;cursor:pointer}.ct-cf-btn.on{background:var(--brand);color:var(--pill-fg)}',
      '.ct-conflict .ct-input{flex:1 1 100%}',
      '.ct-pnl-foot{display:flex;justify-content:flex-end;gap:9px;padding:13px 20px;border-top:1px solid var(--line)}',
      '.ct-btn{appearance:none;font-family:inherit;cursor:pointer;font-size:12.5px;font-weight:600;color:var(--ink-2);background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:9px 15px;transition:all .15s}.ct-btn:hover{color:var(--ink);border-color:var(--ink-3)}',
      '.ct-btn-primary{background:var(--pill-bg);color:var(--pill-fg);border-color:var(--pill-bg)}.ct-btn-primary:hover{background:var(--brand-strong);color:var(--pill-fg)}.ct-btn-primary:disabled{opacity:.45;cursor:default}',
      '.ct-rc-stat{font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px}',
      '.ct-rc-ok{background:var(--ok-soft);color:var(--ok)}.ct-rc-todo{background:var(--warn-soft);color:var(--warn)}.ct-rc-none{background:var(--line-2);color:var(--ink-3)}',
      '.ct-rc-row{flex-direction:row;align-items:center;gap:10px;flex-wrap:wrap}.ct-rc-lbl{display:flex;align-items:center;gap:7px;font-size:12.5px;min-width:200px}.ct-rc-ck{accent-color:var(--brand)}.ct-rc-camp{flex:1 1 180px}'
    ].join('\n');
    document.head.appendChild(s);
  }

  return { mount: mount, openAdd: openAdd, openReconcile: openReconcile, _openPanel: openPanel };
});
