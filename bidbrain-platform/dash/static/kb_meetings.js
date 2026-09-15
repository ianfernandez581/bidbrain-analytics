/* kb_meetings.js - the Meetings page. Talks only to /kb/api/fathom/*; the platform decides
   everything (who may see it, which clients exist, whether Fathom is connected). */
(function () {
  'use strict';
  var C = window.KB_MEETINGS || {clients: [], connected: false};
  var byKey = {};
  C.clients.forEach(function (c) { byKey[c.key] = c.name; });
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch];
    });
  };
  var api = function (path, body) {
    var opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'},
                                          body: JSON.stringify(body)};
    return fetch(path, opt).then(function (r) { return r.json().then(function (j) { j._status = r.status; return j; }); });
  };
  var clientName = function (k) { return k === '' || k == null ? 'Agency-wide' : (byKey[k] || k); };
  var when = function (s) { return s ? String(s).replace('T', ' ').slice(0, 16) + ' UTC' : ''; };

  // ---- status + queue ----
  function loadStatus() {
    api('/kb/api/fathom/status').then(function (j) {
      if (!j.ok) { $('fmQueue').innerHTML = '<div class="fm-empty">' + esc(j.error || 'Could not load.') + '</div>'; return; }
      var st = j.state || {}, lc = st.last_counts || {};
      $('fmState').innerHTML =
        '<b>Filed meetings</b><span>' + j.indexed + '</span>' +
        '<b>Last sync</b><span>' + (st.last_sync_at ? esc(when(st.last_sync_at)) + (st.by ? ' by ' + esc(st.by) : '') : 'never') + '</span>' +
        '<b>Last result</b><span>' + (st.last_counts ? esc(lc.seen + ' seen · ' + lc.assigned + ' filed · ' + lc.queued + ' queued · ' + lc.exists + ' already · ' + lc.errors + ' errors') : '-') + '</span>' +
        '<b>Auto-assign</b><span>' + (j.auto_assign > 1 ? 'never (pilot) - a person confirms every proposal' : 'at confidence ≥ ' + j.auto_assign) + '</span>';
      renderQueue(j.unassigned || []);
    }).catch(function () { $('fmQueue').innerHTML = '<div class="fm-empty">Could not reach the platform.</div>'; });
  }

  function renderQueue(items) {
    $('fmCount').textContent = items.length;
    if (!items.length) { $('fmQueue').innerHTML = '<div class="fm-empty">Nothing waiting.</div>'; return; }
    var opts = '<option value="">Agency-wide (no single client)</option>' +
      C.clients.map(function (c) { return '<option value="' + esc(c.key) + '">' + esc(c.name) + '</option>'; }).join('');
    $('fmQueue').innerHTML = items.map(function (m) {
      var p = m.proposal || {}, ev = p.evidence || [];
      var inv = (m.invitees || []).filter(function (i) { return i.external !== false && i.email; })
        .map(function (i) { return esc(i.email); }).join(', ');
      var prop = p.client_key !== undefined && p.client_key !== null
        ? '<div class="fm-ev">Proposal: <b>' + esc(clientName(p.client_key)) + '</b>' +
          (p.confidence != null ? ' (confidence ' + Math.round(p.confidence * 100) + '%)' : '') +
          (p.why ? ' - ' + esc(p.why) : '') + '</div>' : '';
      var evl = ev.length ? '<ul class="fm-ev">' + ev.slice(0, 6).map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul>' : '';
      return '<div class="fm-row" data-rid="' + esc(m.recording_id) + '">' +
        '<div class="fm-main"><div class="fm-title">' + esc(m.title) + '</div>' +
        '<div class="fm-meta">' + esc(when(m.created_at)) + (m.duration_min ? ' · ' + m.duration_min + ' min' : '') +
        (inv ? ' · ' + inv : ' · no external invitees') + '</div>' +
        (m.summary ? '<div class="fm-sum">' + esc(m.summary) + '</div>' : '') + prop + evl + '</div>' +
        '<div class="fm-act"><select class="kb-input fm-sel">' + opts + '</select>' +
        '<button class="btn sm gold fm-assign">Assign</button><button class="btn sm fm-ignore" title="Drop without indexing">Ignore</button></div></div>';
    }).join('');
    // pre-select the proposal
    items.forEach(function (m) {
      var p = m.proposal || {};
      var row = $('fmQueue').querySelector('[data-rid="' + m.recording_id.replace(/"/g, '\\"') + '"]');
      if (row && p.client_key !== undefined && p.client_key !== null) row.querySelector('.fm-sel').value = p.client_key;
    });
  }

  $('fmQueue').addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var row = b.closest('.fm-row'), rid = row.getAttribute('data-rid');
    var ck = b.classList.contains('fm-ignore') ? 'ignore' : row.querySelector('.fm-sel').value;
    if (ck === 'ignore' && !confirm('Drop this recording without indexing it?')) return;
    row.style.opacity = '.5';
    api('/kb/api/fathom/assign', {recording_id: rid, client_key: ck}).then(function (j) {
      if (!j.ok) { row.style.opacity = ''; alert(j.error || 'Failed'); return; }
      loadStatus();
    });
  });

  $('fmSync').addEventListener('click', function () {
    var b = $('fmSync'); b.disabled = true; $('fmSyncNote').textContent = 'Syncing…';
    api('/kb/api/fathom/sync', {}).then(function (j) {
      b.disabled = false;
      if (!j.ok) { $('fmSyncNote').textContent = j.error || 'Sync failed.'; return; }
      var c = j.counts || {};
      $('fmSyncNote').textContent = c.seen + ' seen · ' + c.assigned + ' filed · ' + c.queued + ' queued · ' + c.exists + ' already filed';
      loadStatus();
    }).catch(function () { b.disabled = false; $('fmSyncNote').textContent = 'Sync failed.'; });
  });

  // ---- domains ----
  function loadDomains() {
    var ck = $('fmDomClient').value;
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck)).then(function (j) {
      if (!j.ok) { $('fmDomNote').textContent = j.error || ''; return; }
      $('fmDomains').value = (j.memory.client_domains || []).join(', ');
      $('fmDomNote').textContent = (j.memory.client_domains || []).length ? '' : 'No domains declared yet for ' + clientName(ck) + '.';
    });
  }
  $('fmDomClient').addEventListener('change', loadDomains);
  $('fmDomSave').addEventListener('click', function () {
    var ck = $('fmDomClient').value;
    var doms = $('fmDomains').value.split(/[\s,]+/).filter(Boolean);
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck), {domains: doms}).then(function (j) {
      $('fmDomNote').textContent = j.ok ? 'Saved: ' + (j.memory.client_domains || []).join(', ') : (j.error || 'Failed');
      if (j.ok && $('fmMemClient').value === ck) loadMemory();
    });
  });

  // ---- memory ----
  function tagList(kind, obj, mem) {
    var keys = Object.keys(obj || {});
    if (!keys.length) return '<div class="fm-empty">none yet</div>';
    keys.sort(function (a, b) { return (obj[b].n || 0) - (obj[a].n || 0); });
    return '<div class="fm-tags">' + keys.slice(0, 60).map(function (k) {
      return '<span class="fm-tag">' + esc(k) + '<small>×' + (obj[k].n || 1) + '</small>' +
        '<button data-kind="' + kind + '" data-key="' + esc(k) + '" title="Remove">✕</button></span>';
    }).join('') + '</div>';
  }
  function loadMemory() {
    var ck = $('fmMemClient').value;
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck)).then(function (j) {
      if (!j.ok) { $('fmMemory').innerHTML = '<div class="fm-empty">' + esc(j.error || 'Could not load.') + '</div>'; return; }
      var m = j.memory;
      var facts = (m.facts || []).length
        ? '<div class="fm-tags">' + m.facts.map(function (f) {
            return '<span class="fm-tag">' + esc(f) + '<button data-kind="facts" data-key="' + esc(f) + '" title="Remove">✕</button></span>';
          }).join('') + '</div>'
        : '<div class="fm-empty">No facts yet.</div>';
      $('fmMemory').innerHTML =
        '<div class="fm-kv"><b>Facts</b><div>' + facts + '</div>' +
        '<b>People</b><div>' + tagList('people', m.people) + '</div>' +
        '<b>Recurring titles</b><div>' + tagList('titles', m.titles) + '</div>' +
        '<b>Domains seen</b><div>' + tagList('domains', m.domains) + '</div>' +
        '<b>Campaign patterns</b><div>' + tagList('patterns', m.patterns) + '</div>' +
        '<b>Updated</b><span>' + esc(when(m.updated_at) || 'never') + '</span></div>';
    });
  }
  $('fmMemClient').addEventListener('change', loadMemory);
  $('fmFactAdd').addEventListener('click', function () {
    var ck = $('fmMemClient').value, text = $('fmFact').value.trim();
    if (!text) return;
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck), {fact: text}).then(function (j) {
      if (!j.ok) { alert(j.error || 'Failed'); return; }
      $('fmFact').value = ''; loadMemory();
    });
  });
  $('fmMemory').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-kind]'); if (!b) return;
    var ck = $('fmMemClient').value;
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck), {forget: {kind: b.getAttribute('data-kind'), key: b.getAttribute('data-key')}})
      .then(function (j) { if (!j.ok) alert(j.error || 'Failed'); loadMemory(); });
  });

  loadStatus();
  if (C.clients.length) { loadDomains(); loadMemory(); }
})();
