/* kb_meetings.js - the Meetings page. Talks only to /kb/api/fathom/*; the platform decides
   everything (who may see it, which clients exist, whether Fathom is connected).

   2026-09-15 polish (from an /impeccable critique):
   - Assigning a card removes THAT card only. The old code rebuilt the whole queue from /status, which
     silently reverted any dropdown a person had already corrected on another card - a wrong filing
     that then teaches memory. Now the queue is rebuilt only on load, Sync, and Retry.
   - Confidence is a coloured pill (kb.css's .kb-state colours), the override is visible before the
     click ("Assign to Geocon"), and the card says what Assign WILL remember, with tick boxes.
   - No alert()/confirm(): kb.css's .kb-toast, and a two-step Ignore. */
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
  var when = function (s) {                       // the viewer's local time, short; UTC only as a tooltip
    if (!s) return '';
    var d = new Date(s);
    if (isNaN(d)) return String(s).replace('T', ' ').slice(0, 16) + ' UTC';
    return d.toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
  };
  var ago = function (s) {
    if (!s) return 'never';
    var ms = Date.now() - new Date(s).getTime();
    if (isNaN(ms)) return String(s);
    var m = Math.round(ms / 60000);
    if (m < 2) return 'just now';
    if (m < 60) return m + ' min ago';
    if (m < 48 * 60) return Math.round(m / 60) + ' h ago';
    return Math.round(m / 1440) + ' days ago';
  };
  var pct = function (c) { return Math.round((c || 0) * 100); };
  var confClass = function (c) { return c == null ? 'empty' : c >= 0.9 ? 'searchable' : c >= 0.6 ? 'indexing' : 'keyword'; };

  // ---- toast (kb.css .kb-toast) ----
  var toastTimer;
  function toast(msg, isErr) {
    var old = document.querySelector('.kb-toast'); if (old) old.remove();
    var t = document.createElement('div');
    t.className = 'kb-toast' + (isErr ? ' err' : '');
    t.setAttribute('role', 'status');
    t.textContent = msg;
    document.body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.remove(); }, isErr ? 6000 : 3200);
  }

  // ---- status strip + queue ----
  var indexed = 0;
  function renderState(j) {
    var st = j.state || {}, lc = st.last_counts || {};
    indexed = j.indexed || 0;
    $('fmStrip').innerHTML =
      '<b class="n">' + indexed + '</b> filed<i>·</i>last sync <b>' + esc(ago(st.last_sync_at)) + '</b>' +
      (st.by && st.last_sync_at ? ' by ' + esc(st.by) : '') +
      (st.sync_in_progress ? '<i>·</i><b>syncing…</b>' : '') +
      (st.last_error ? '<i>·</i><span class="err">last sync hit an error</span>' : '');
    $('fmState').innerHTML =
      (st.last_error ? '<b>Last error</b><span style="color:var(--danger)">' + esc(st.last_error) + '</span>' : '') +
      '<b>Filed meetings</b><span class="n">' + indexed + '</span>' +
      '<b>Last sync</b><span>' + (st.last_sync_at ? esc(when(st.last_sync_at)) + (st.by ? ' by ' + esc(st.by) : '') : 'never') + '</span>' +
      '<b>Last result</b><span class="n">' + (st.last_counts ? esc(lc.seen + ' seen · ' + lc.assigned + ' filed · ' + lc.queued + ' queued · ' + lc.exists + ' already filed · ' + lc.errors + ' errors') : '-') + '</span>' +
      '<b>Auto-assign</b><span>' + (j.auto_assign > 1 ? 'never (pilot) - a person confirms every proposal' : 'at confidence ≥ ' + pct(j.auto_assign) + '%') + '</span>';
    if (st.sync_in_progress) setTimeout(loadStatus, 5000);      // poll until the background sync finishes
  }
  function loadStatus() {
    api('/kb/api/fathom/status').then(function (j) {
      if (!j.ok) { failed(j.error || 'Could not load the queue.'); return; }
      renderState(j);
      renderQueue(j.unassigned || []);
    }).catch(function () { failed('Could not reach the platform.'); });
  }
  function failed(msg) {
    $('fmCount').textContent = '!';
    $('fmQueue').innerHTML = '<div class="kb-empty"><h3>' + esc(msg) + '</h3><p>The rest of the knowledge base is unaffected.</p>' +
      '<button class="btn sm" id="fmRetry">Retry</button></div>';
    $('fmRetry').addEventListener('click', function () { $('fmQueue').innerHTML = '<div class="fm-empty">Loading…</div>'; loadStatus(); });
  }
  function setCount(n) {
    var el = $('fmCount');
    el.textContent = n;
    el.classList.toggle('zero', !n);
  }
  function emptyState() {
    $('fmQueue').innerHTML = '<div class="kb-empty"><h3>Nothing waiting</h3><p>Every meeting that arrived has been filed. ' +
      (C.connected ? 'New recordings land here as they finish, or press Sync now to pull anything missed.' : 'Connect Fathom to start receiving recordings.') + '</p></div>';
  }

  var READY = 0.9;                                 // a guess at/above this sits in "Ready to confirm"
  function isReady(m) {
    var p = m.proposal || {};
    return p.client_key !== undefined && p.client_key !== null && p.confidence != null && p.confidence >= READY;
  }

  function cardHtml(m, opts) {
    var p = m.proposal || {}, ev = p.evidence || [], wl = m.will_learn || {};
    var hasProp = p.client_key !== undefined && p.client_key !== null;
    var inv = (m.invitees || []).filter(function (i) { return i.external !== false && i.email; })
      .map(function (i) { return esc(i.email); });
    var chips = '<span class="fm-chip" title="' + esc(m.created_at || '') + '">' + esc(when(m.created_at)) + '</span>' +
      (m.duration_min ? '<span class="fm-chip">' + m.duration_min + ' min</span>' : '') +
      (inv.length ? inv.map(function (e) { return '<span class="fm-chip">' + e + '</span>'; }).join('') : '<span class="fm-chip">no external invitees</span>');
    var why = (p.why ? esc(p.why) : '') +
      (ev.length ? '<ul>' + ev.slice(0, 4).map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul>' : '');
    var guess = '<div class="fm-guess"><div class="fm-guess-head"><span class="lbl">System\'s guess</span>' +
      (hasProp ? '<span class="who">' + esc(clientName(p.client_key)) + '</span>' +
        (p.confidence != null ? '<span class="kb-state ' + confClass(p.confidence) + '">' + pct(p.confidence) + '% sure</span>' : '')
        : '<span class="kb-state empty">none - pick a client</span>') +
      (why ? '<button class="fm-why-btn" type="button" aria-expanded="false">Why?</button>' : '') + '</div>' +
      (why ? '<div class="fm-why" hidden>' + why + '</div>' : '') + '</div>';
    var teach = [].concat(
      (wl.people || []).map(function (e) { return {k: e, t: e}; }),
      (wl.domains || []).map(function (d) { return {k: d, t: '@' + d}; }),
      wl.title ? [{k: wl.title, t: '\u201c' + wl.title + '\u201d'}] : []);
    var teachHtml = teach.length
      ? '<div class="fm-teach"><span class="lbl">Will remember</span>' + teach.map(function (x) {
          return '<label><input type="checkbox" checked data-skip="' + esc(x.k) + '">' + esc(x.t) + '</label>';
        }).join('') + '</div>'
      : '';
    var longSum = (m.summary || '').length > 180;             // clip ONLY when there is a Show more to release it
    var sum = m.summary ? '<div class="fm-sum' + (longSum ? ' clip' : '') + '">' + esc(m.summary) + '</div>' +
      (longSum ? '<button class="fm-more-btn" type="button" aria-expanded="false">Show more</button>' : '') : '';
    // Compact by default: title + chips + the guess. Summary and "Will remember" open on the chevron
    // or the title (2026-09-15, Jerome on a 13-card queue: "overwhelming in the eyes").
    return '<article class="fm-row" data-rid="' + esc(m.recording_id) + '" data-prop="' + (hasProp ? esc(p.client_key) : '') + '"' +
      (hasProp ? ' data-hasprop="1"' : '') + '>' +
      '<button class="fm-tog" type="button" aria-expanded="false" aria-label="Show details">&#9656;</button>' +
      '<div class="fm-main"><div class="fm-line1"><span class="fm-title">' + esc(m.title) + '</span>' +
      '<span class="fm-chips">' + chips + '</span></div>' + guess +
      '<div class="fm-detail" hidden>' + sum + teachHtml + '</div></div>' +
      '<div class="fm-act"><select class="kb-input fm-sel" aria-label="File under client">' + opts + '</select>' +
      '<button class="btn sm gold fm-assign">Assign</button>' +
      '<button class="btn sm fm-ignore" title="Drop the recording without indexing it">Ignore</button></div></article>';
  }

  function groupHtml(key, title, sub, items, opts, extra) {
    if (!items.length) return '';
    return '<section class="fm-group" data-group="' + key + '"><div class="fm-group-head">' +
      '<h3 class="fm-group-h">' + title + ' <span class="fm-pill count fm-gcount">' + items.length + '</span></h3>' +
      '<span class="fm-group-sub">' + sub + '</span>' + (extra || '') + '</div>' +
      items.map(function (m) { return cardHtml(m, opts); }).join('') + '</section>';
  }

  function renderQueue(items) {
    setCount(items.length);
    if (!items.length) { emptyState(); return; }
    var opts = '<option value="">Agency-wide (no single client)</option>' +
      C.clients.map(function (c) { return '<option value="' + esc(c.key) + '">' + esc(c.name) + '</option>'; }).join('');
    var look = items.filter(function (m) { return !isReady(m); }), ready = items.filter(isReady);
    // The doubtful ones FIRST: a wrong 95% is easier to catch when the eye is already reading.
    $('fmQueue').innerHTML =
      groupHtml('look', 'Needs a look', 'unsure, or no guess - read these', look, opts) +
      groupHtml('ready', 'Ready to confirm', 'guessed at ' + Math.round(READY * 100) + '% or more - check the client, then confirm', ready, opts,
        '<button class="btn sm gold" id="fmConfirmAll" type="button">Confirm all ' + ready.length + ' as guessed</button>');
    Array.prototype.forEach.call($('fmQueue').querySelectorAll('.fm-row'), function (row) {
      if (row.hasAttribute('data-hasprop')) row.querySelector('.fm-sel').value = row.getAttribute('data-prop');
      reflectChoice(row);
    });
  }

  function refreshGroups() {
    var total = 0;
    Array.prototype.forEach.call($('fmQueue').querySelectorAll('.fm-group'), function (g) {
      var n = g.querySelectorAll('.fm-row').length;
      total += n;
      if (!n) { g.remove(); return; }
      g.querySelector('.fm-gcount').textContent = n;
      var b = g.querySelector('#fmConfirmAll'); if (b) b.textContent = 'Confirm all ' + n + ' as guessed';
    });
    setCount(total);
    if (!total) emptyState();
    return total;
  }

  function skipsOf(row) {
    return Array.prototype.map.call(row.querySelectorAll('.fm-teach input:not(:checked)'), function (i) { return i.getAttribute('data-skip'); });
  }

  function toggleRow(row, open) {
    var d = row.querySelector('.fm-detail'), t = row.querySelector('.fm-tog');
    if (open === undefined) open = d.hidden;
    d.hidden = !open; row.classList.toggle('open', open);
    t.setAttribute('aria-expanded', open ? 'true' : 'false'); t.setAttribute('aria-label', open ? 'Hide details' : 'Show details');
  }

  function confirmAll() {
    var rows = Array.prototype.slice.call($('fmQueue').querySelectorAll('[data-group="ready"] .fm-row'));
    var btn = $('fmConfirmAll');
    if (!rows.length || !btn) return;
    var total = rows.length, done = 0, failed = 0;
    btn.disabled = true;
    (function next() {
      var row = rows.shift();
      if (!row) {
        toast(done + ' filed as guessed' + (failed ? ' - ' + failed + ' failed and stay in the list' : '') + '.', !!failed);
        var b = $('fmConfirmAll'); if (b) { b.disabled = false; }
        refreshGroups();
        return;
      }
      btn.textContent = 'Confirming ' + (done + failed + 1) + ' of ' + total + '…';
      act(row, row.querySelector('.fm-sel').value, skipsOf(row), true).then(function (ok) { if (ok) done++; else failed++; next(); });
    })();
  }

  function reflectChoice(row) {
    var sel = row.querySelector('.fm-sel'), btn = row.querySelector('.fm-assign'), teach = row.querySelector('.fm-teach');
    var prop = row.getAttribute('data-prop'), v = sel.value;
    var override = v !== prop;
    btn.textContent = override ? 'Assign to ' + clientName(v) : 'Assign';
    btn.classList.toggle('override', override);
    if (teach) teach.classList.toggle('hidden', v === '');          // agency-wide teaches nothing
  }

  $('fmQueue').addEventListener('change', function (e) {
    if (e.target.classList.contains('fm-sel')) reflectChoice(e.target.closest('.fm-row'));
    if (e.target.matches('.fm-teach input')) e.target.closest('label').classList.toggle('off', !e.target.checked);
  });

  var ignoreTimers = {};
  $('fmQueue').addEventListener('click', function (e) {
    var t = e.target.closest('.fm-title');
    if (t) { toggleRow(t.closest('.fm-row')); return; }
    var b = e.target.closest('button'); if (!b) return;
    if (b.id === 'fmConfirmAll') { confirmAll(); return; }
    if (b.classList.contains('fm-tog')) { toggleRow(b.closest('.fm-row')); return; }
    if (b.classList.contains('fm-why-btn')) {
      var w = b.closest('.fm-guess').querySelector('.fm-why'), shown = w.hidden;
      w.hidden = !shown; b.textContent = shown ? 'Hide' : 'Why?'; b.setAttribute('aria-expanded', shown ? 'true' : 'false');
      return;
    }
    if (b.classList.contains('fm-more-btn')) {
      var s = b.previousElementSibling, open = s.classList.toggle('clip');
      b.textContent = open ? 'Show more' : 'Show less';
      b.setAttribute('aria-expanded', open ? 'false' : 'true');
      return;
    }
    var row = b.closest('.fm-row'); if (!row) return;
    var rid = row.getAttribute('data-rid');
    if (b.classList.contains('fm-ignore')) {
      if (!b.classList.contains('confirm')) {                       // two-step, no confirm() dialog
        b.classList.add('confirm'); b.textContent = 'Drop it?';
        ignoreTimers[rid] = setTimeout(function () { b.classList.remove('confirm'); b.textContent = 'Ignore'; }, 5000);
        return;
      }
      clearTimeout(ignoreTimers[rid]);
      act(row, 'ignore', []);
      return;
    }
    if (b.classList.contains('fm-assign')) {
      act(row, row.querySelector('.fm-sel').value, skipsOf(row));
    }
  });

  function act(row, ck, skip, quiet) {
    var rid = row.getAttribute('data-rid');
    row.classList.add('busy');
    return api('/kb/api/fathom/assign', {recording_id: rid, client_key: ck, skip: skip}).then(function (j) {
      if (!j.ok) { row.classList.remove('busy'); if (!quiet) toast(j.error || 'That did not work - try again.', true); return false; }
      var next = row.nextElementSibling;
      if (!next || !next.classList.contains('fm-row')) next = row.previousElementSibling;
      row.remove();
      var left = refreshGroups();
      if (left && !quiet && next && next.querySelector && next.querySelector('.fm-sel')) next.querySelector('.fm-sel').focus();
      if (ck !== 'ignore') {
        indexed += 1;
        var b = $('fmStrip').querySelector('b.n'); if (b) b.textContent = indexed;
        if ($('fmClient').value === ck) loadClient();           // the memory panel shows the new lesson
      }
      if (!quiet) {
        if (ck === 'ignore') toast('Recording dropped - nothing was indexed.');
        else toast('Filed under ' + clientName(ck) + (ck !== '' && skip.length ? ' - ' + skip.length + ' item' + (skip.length > 1 ? 's' : '') + ' not remembered' : '') + '.');
      }
      return true;
    }).catch(function () { row.classList.remove('busy'); if (!quiet) toast('Could not reach the platform.', true); return false; });
  }

  $('fmSync').addEventListener('click', function () {
    var b = $('fmSync'); b.disabled = true; $('fmSyncStatus').textContent = 'Starting…';
    api('/kb/api/fathom/sync', {}).then(function (j) {
      b.disabled = false;
      if (!j.ok) { $('fmSyncStatus').textContent = ''; toast(j.error || 'Sync failed.', true); return; }
      $('fmSyncStatus').textContent = 'Sync started (meetings since ' + (j.since || '').slice(0, 10) + '); this page updates as it runs.';
      toast('Sync started - new meetings appear below as they are checked.');
      loadStatus();
    }).catch(function () { b.disabled = false; $('fmSyncStatus').textContent = ''; toast('Sync failed.', true); });
  });

  // ---- client memory: one client picker drives domains, facts and the learned lists ----
  function status(id, msg, kind) {
    var el = $(id); el.textContent = msg || ''; el.className = 'fm-status' + (kind ? ' ' + kind : '');
  }
  function tagList(kind, obj) {
    var keys = Object.keys(obj || {});
    if (!keys.length) return '<div class="fm-empty">none yet</div>';
    keys.sort(function (a, b) { return (obj[b].n || 0) - (obj[a].n || 0); });
    return '<div class="fm-tags">' + keys.slice(0, 60).map(function (k) {
      var n = obj[k].n || 1;
      return '<span class="fm-tag"><span class="t">' + esc(k) + '</span><small title="seen on ' + n + ' meeting' + (n > 1 ? 's' : '') + '">' + n + '×</small>' +
        '<button data-kind="' + kind + '" data-key="' + esc(k) + '" aria-label="Forget ' + esc(k) + '" title="Forget">✕</button></span>';
    }).join('') + '</div>';
  }
  function renderClient(m) {
    var ck = $('fmClient').value;
    $('fmDomains').value = (m.client_domains || []).join(', ');
    status('fmDomNote', (m.client_domains || []).length ? '' : 'None declared for ' + clientName(ck) + ' - the system learns domains from confirmed meetings anyway.');
    $('fmFacts').innerHTML = (m.facts || []).length
      ? '<div class="fm-tags">' + m.facts.map(function (f) {
          return '<span class="fm-tag"><span class="t" title="' + esc(f) + '">' + esc(f) + '</span><button data-kind="facts" data-key="' + esc(f) + '" aria-label="Remove fact" title="Remove">✕</button></span>';
        }).join('') + '</div>'
      : '<div class="fm-empty">No facts yet.</div>';
    $('fmMemory').innerHTML =
      '<div class="fm-kv"><b>People</b><div>' + tagList('people', m.people) + '</div>' +
      '<b>Recurring titles</b><div>' + tagList('titles', m.titles) + '</div>' +
      '<b>Domains seen</b><div>' + tagList('domains', m.domains) + '</div>' +
      '<b>Campaign patterns</b><div>' + tagList('patterns', m.patterns) + '</div>' +
      '<b>Updated</b><div>' + esc(m.updated_at ? when(m.updated_at) : 'never') + '</div></div>';
  }
  function loadClient() {
    var ck = $('fmClient').value;
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck)).then(function (j) {
      if (!j.ok) { $('fmMemory').innerHTML = '<div class="fm-empty">' + esc(j.error || 'Could not load.') + '</div>'; return; }
      renderClient(j.memory);
    }).catch(function () { $('fmMemory').innerHTML = '<div class="fm-empty">Could not reach the platform.</div>'; });
  }
  $('fmClient').addEventListener('change', loadClient);

  function saveDomains() {
    var ck = $('fmClient').value;
    var doms = $('fmDomains').value.split(/[\s,]+/).filter(Boolean);
    status('fmDomNote', 'Saving…');
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck), {domains: doms}).then(function (j) {
      if (!j.ok) { status('fmDomNote', j.error || 'Could not save.', 'err'); return; }
      renderClient(j.memory);
      status('fmDomNote', doms.length ? 'Saved - meetings with these domains now file under ' + clientName(ck) + ' automatically.' : 'Cleared.', 'ok');
    }).catch(function () { status('fmDomNote', 'Could not reach the platform.', 'err'); });
  }
  $('fmDomSave').addEventListener('click', saveDomains);
  $('fmDomains').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); saveDomains(); } });

  function addFact() {
    var ck = $('fmClient').value, text = $('fmFact').value.trim();
    if (!text) { $('fmFact').focus(); return; }
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck), {fact: text}).then(function (j) {
      if (!j.ok) { toast(j.error || 'Could not add the fact.', true); return; }
      $('fmFact').value = ''; renderClient(j.memory); toast('Fact added.');
    }).catch(function () { toast('Could not reach the platform.', true); });
  }
  $('fmFactAdd').addEventListener('click', addFact);
  $('fmFact').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); addFact(); } });

  function forget(e) {
    var b = e.target.closest('button[data-kind]'); if (!b) return;
    var ck = $('fmClient').value, kind = b.getAttribute('data-kind'), key = b.getAttribute('data-key');
    b.disabled = true;
    api('/kb/api/fathom/memory/' + encodeURIComponent(ck), {forget: {kind: kind, key: key}})
      .then(function (j) {
        if (!j.ok) { b.disabled = false; toast(j.error || 'Could not remove it.', true); return; }
        renderClient(j.memory); toast((kind === 'facts' ? 'Fact removed.' : 'Forgotten: ' + key));
      }).catch(function () { b.disabled = false; toast('Could not reach the platform.', true); });
  }
  $('fmMemory').addEventListener('click', forget);
  $('fmFacts').addEventListener('click', forget);

  loadStatus();
  if (C.clients.length) loadClient();
})();
