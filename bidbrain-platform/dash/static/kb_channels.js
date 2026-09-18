/* kb_channels.js - the Channels page (Slack). Talks only to /kb/api/slack/*; the platform decides
   everything (who may see it, which clients exist, whether Slack is connected). A sibling of
   kb_meetings.js with the same rules: a poll never closes what a person has opened, assigning a
   card removes that card only, mapping a channel never re-files anything by itself. */
(function () {
  'use strict';
  var C = window.KB_CHANNELS || {clients: [], connected: false};
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
  var when = function (s) {
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
  var clientOpts = function (sel) {
    return '<option value=""' + (sel === '' ? ' selected' : '') + '>Agency-wide (no single client)</option>' +
      C.clients.map(function (c) { return '<option value="' + esc(c.key) + '"' + (sel === c.key ? ' selected' : '') + '>' + esc(c.name) + '</option>'; }).join('');
  };

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

  // ---- status strip ----
  var indexed = 0;
  function renderState(j) {
    var st = j.state || {}, lc = st.last_counts || {}, team = j.team || {};
    indexed = j.indexed || 0;
    $('chStrip').innerHTML =
      (team.team ? '<b>' + esc(team.team) + '</b><i>·</i>' : '') +
      '<b class="n">' + indexed + '</b> filed<i>·</i>last sync <b>' + esc(ago(st.last_sync_at)) + '</b>' +
      (st.by && st.last_sync_at ? ' by ' + esc(st.by) : '') +
      (st.sync_in_progress ? '<i>·</i><b>syncing…</b>' : '') +
      (st.last_error ? '<i>·</i><span class="err">last sync hit an error</span>' : '');
    $('chState').innerHTML =
      (st.last_error ? '<b>Last error</b><span style="color:var(--danger)">' + esc(st.last_error) + '</span>' : '') +
      '<b>Workspace</b><span>' + (team.team ? esc(team.team) : '-') + '</span>' +
      '<b>Filed conversations</b><span class="n">' + indexed + '</span>' +
      '<b>Last sync</b><span>' + (st.last_sync_at ? esc(when(st.last_sync_at)) + (st.by ? ' by ' + esc(st.by) : '') : 'never') + '</span>' +
      '<b>Last result</b><span class="n">' + (st.last_counts ? esc(lc.channels + ' channels · ' + lc.seen + ' conversations · ' + lc.filed + ' filed · ' + lc.queued + ' queued · ' + lc.rebuilt + ' refreshed · ' + lc.errors + ' errors' + (lc.skipped_private ? ' · ' + lc.skipped_private + ' private skipped' : '')) : '-') + '</span>' +
      '<b>AI guess files</b><span>' + (j.auto_assign > 1 ? 'never' : 'at confidence ≥ ' + pct(j.auto_assign) + '%') + '</span>';
    if (st.sync_in_progress) setTimeout(loadStatus, 5000);
  }

  // ---- channels the bot is in ----
  // 🔴 ONE LINE PER CHANNEL, editor on demand. The first real workspace had 17 channels and this
  // table was 2,521px - 148px a row - because every row carried an open mapping editor: 17 selects
  // x 20 options rendered up front, 17 Save buttons, and "unmapped - each conversation is judged on
  // its own" seventeen times. Reading the list is the common case; editing one is the exception.
  function channelRow(c) {
    var mapped = c.mapped;
    var skipped = c.is_private && c.readable === false;
    var meta = [c.is_private ? 'private' : 'public', c.members ? c.members + ' members' : '',
                c.last_synced ? 'synced ' + ago(c.last_synced) : 'never synced',
                skipped ? '<span class="fm-over" title="Private channels are not read until SLACK_ALLOW_PRIVATE is on and a membership filter exists">not read</span>' : '',
                c.is_limited ? '<span class="fm-over" title="Slack withheld older history (free-plan window)">history limited</span>' : ''].filter(Boolean).join(' · ');
    var files = mapped ? '<b>' + esc(clientName(c.client)) + '</b>'
                       : '<span class="ch-unmapped">judged per conversation</span>';
    return '<tr class="ch-row" data-cid="' + esc(c.id) + '" data-name="' + esc(c.name) + '" data-client="' + (mapped ? esc(c.client) : '') +
           '" data-mapped="' + (mapped ? '1' : '') + '" data-by="' + esc(c.mapped_by || '') + '" data-skipped="' + (skipped ? '1' : '') + '">' +
      '<td class="ch-c-name"><span class="ch-name">#' + esc(c.name) + '</span>' +
        '<span class="ch-note">' + meta + '</span></td>' +
      '<td class="ch-c-files">' + files + '</td>' +
      '<td class="ch-c-act"><button class="btn sm ch-edit" type="button"' +
        (skipped ? ' disabled title="Private channels are not read yet"' : '') + '>' +
        (mapped ? 'Change' : 'Set client') + '</button></td>' +
      '</tr>';
  }

  // The editor, inserted UNDER its channel when the button is pressed. Built here rather than in
  // channelRow so the page never renders selects nobody opened - and so it always reflects the
  // row's current mapping instead of whatever the last poll drew.
  function editorRow(tr) {
    var mapped = tr.getAttribute('data-mapped') === '1';
    var client = tr.getAttribute('data-client');
    var name = tr.getAttribute('data-name');
    var by = tr.getAttribute('data-by');
    return '<tr class="ch-editor" data-for="' + esc(tr.getAttribute('data-cid')) + '"><td colspan="3">' +
      '<div class="ch-map">' +
        '<select class="kb-input ch-sel" aria-label="Client for #' + esc(name) + '">' +
          '<option value="__none"' + (mapped ? '' : ' selected') + '>' + (mapped ? 'Clear mapping' : 'Not mapped - decide per conversation') + '</option>' +
          clientOpts(mapped ? client : null) + '</select>' +
        '<button class="btn sm gold ch-save" type="button">Save</button>' +
        (mapped ? '<button class="btn sm ch-refile" type="button" title="Move every conversation already filed from this channel to ' + esc(clientName(client)) + '">Re-file existing</button>' : '') +
        '<button class="btn sm ch-cancel" type="button">Cancel</button>' +
      '</div>' +
      (mapped && by ? '<div class="ch-note">set by ' + esc(by) + '</div>' : '') +
      '</td></tr>';
  }
  // The filter only appears once the list is long enough to need one - a search box over three
  // channels is furniture. FILTER_FROM is the threshold, not a magic number in two places.
  var FILTER_FROM = 8;
  var chFilter = {q: '', unmappedOnly: false};
  var chOpen = '';                 // the channel id whose editor is open; a poll must not close it

  function chVisible(c) {
    if (chFilter.unmappedOnly && c.mapped) return false;
    var q = chFilter.q.trim().toLowerCase();
    if (!q) return true;
    return ('#' + (c.name || '')).toLowerCase().indexOf(q) >= 0 ||
           clientName(c.client).toLowerCase().indexOf(q) >= 0;
  }

  function chFilterBar(chans) {
    if (chans.length < FILTER_FROM) return '';
    var unmapped = chans.filter(function (c) { return !c.mapped; }).length;
    return '<div class="ch-filter">' +
      '<input class="kb-input ch-q" type="search" placeholder="Find a channel or client" ' +
        'aria-label="Find a channel" value="' + esc(chFilter.q) + '">' +
      '<label class="ch-only"><input type="checkbox" class="ch-unmapped-only"' +
        (chFilter.unmappedOnly ? ' checked' : '') + '> Unmapped only (' + unmapped + ')</label>' +
      '<span class="ch-shown" aria-live="polite"></span></div>';
  }

  // The fold's summary has to answer "is anything wrong in there?" without being opened, so it
  // carries the counts that would otherwise make someone open it.
  function renderFoldSummary(chans) {
    var el = $('chFoldSum'); if (!el) return;
    if (!chans.length) { el.innerHTML = '<span class="n">0</span> channels'; return; }
    var mapped = chans.filter(function (c) { return c.mapped; }).length;
    var skipped = chans.filter(function (c) { return c.is_private && c.readable === false; }).length;
    var bits = ['<span class="n">' + chans.length + '</span> channel' + (chans.length === 1 ? '' : 's')];
    bits.push(mapped ? '<span class="n">' + mapped + '</span> mapped' : 'none mapped');
    if (skipped) bits.push('<span class="warn"><span class="n">' + skipped + '</span> not read</span>');
    el.innerHTML = bits.join(' · ');
  }

  function renderChannels(j) {
    var chans = j.channels || [];
    renderFoldSummary(chans);
    if (j.channels_error) { $('chChannels').innerHTML = '<div class="fm-empty">' + esc(j.channels_error) + '</div>'; return; }
    if (!chans.length) {
      $('chChannels').innerHTML = '<div class="kb-empty"><h3>No channels yet</h3><p>' +
        (C.connected ? 'In Slack, open a channel and type <code>/invite @Bidbrain Knowledge</code>. It appears here on the next load.' : 'Connect Slack first.') + '</p></div>';
      return;
    }
    // Mapped first: a channel someone has already decided about is the one they come back to.
    var shown = chans.filter(chVisible).sort(function (a, b) {
      if (!!a.mapped !== !!b.mapped) return a.mapped ? -1 : 1;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
    var body = shown.length ? shown.map(channelRow).join('')
                            : '<tr><td colspan="3" class="fm-empty">No channel matches that.</td></tr>';
    $('chChannels').innerHTML = chFilterBar(chans) +
      '<table class="ch-table"><tbody>' + body + '</tbody></table>';
    var note = $('chChannels').querySelector('.ch-shown');
    if (note) note.textContent = shown.length === chans.length ? '' : shown.length + ' of ' + chans.length;
    if (chOpen) openEditor($('chChannels').querySelector('tr.ch-row[data-cid="' + chOpen + '"]'));
  }

  function closeEditor() {
    var ed = $('chChannels').querySelector('tr.ch-editor');
    if (ed) ed.parentNode.removeChild(ed);
    var open = $('chChannels').querySelector('tr.ch-row.open');
    if (open) open.classList.remove('open');
    chOpen = '';
  }
  function openEditor(tr) {
    if (!tr || tr.getAttribute('data-skipped') === '1') return;
    closeEditor();
    tr.classList.add('open');
    tr.insertAdjacentHTML('afterend', editorRow(tr));
    chOpen = tr.getAttribute('data-cid');
    var sel = tr.nextSibling && tr.nextSibling.querySelector ? tr.nextSibling.querySelector('.ch-sel') : null;
    if (sel) sel.focus();
  }

  $('chChannels').addEventListener('input', function (e) {
    if (e.target.classList.contains('ch-q')) { chFilter.q = e.target.value; refilter(); }
  });
  $('chChannels').addEventListener('change', function (e) {
    if (e.target.classList.contains('ch-unmapped-only')) { chFilter.unmappedOnly = e.target.checked; refilter(); }
  });
  $('chChannels').addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var row = b.closest('tr'); if (!row) return;
    // The editor is its own row, so resolve back to the channel it belongs to.
    var tr = row.classList.contains('ch-editor')
      ? $('chChannels').querySelector('tr.ch-row[data-cid="' + row.getAttribute('data-for') + '"]') : row;
    if (!tr) return;
    var cid = tr.getAttribute('data-cid'), name = tr.getAttribute('data-name');
    if (b.classList.contains('ch-edit')) {
      if (tr.classList.contains('open')) closeEditor(); else openEditor(tr);
      return;
    }
    if (b.classList.contains('ch-cancel')) { closeEditor(); return; }
    if (b.classList.contains('ch-save')) {
      // The select lives in the editor row, not the channel row.
      var sel = b.closest('tr').querySelector('.ch-sel');
      if (!sel) return;
      var v = sel.value;
      b.disabled = true;
      api('/kb/api/slack/map', {channel_id: cid, name: name, client_key: v === '__none' ? null : v}).then(function (j) {
        b.disabled = false;
        if (!j.ok) { toast(j.error || 'Could not save.', true); return; }
        toast(v === '__none' ? '#' + name + ' unmapped - conversations are judged one by one again.' :
              '#' + name + ' now files under ' + clientName(v) + '. Already-filed conversations stay put until you re-file them.');
        closeEditor();                       // the answer is now on the row itself
        loadStatus();
      }).catch(function () { b.disabled = false; toast('Could not reach the platform.', true); });
      return;
    }
    if (b.classList.contains('ch-refile')) {
      if (!b.classList.contains('confirm')) {
        b.classList.add('confirm'); b.textContent = 'Move them all?';
        setTimeout(function () { b.classList.remove('confirm'); b.textContent = 'Re-file existing'; }, 5000);
        return;
      }
      b.disabled = true; b.textContent = 'Moving…';
      api('/kb/api/slack/refile', {channel_id: cid}).then(function (j) {
        b.disabled = false; b.classList.remove('confirm'); b.textContent = 'Re-file existing';
        if (!j.ok) { toast(j.error || 'Could not re-file.', true); return; }
        toast(j.moved + ' conversation' + (j.moved === 1 ? '' : 's') + ' moved to ' + clientName(j.client) + '.');
        loadLog();
      }).catch(function () { b.disabled = false; toast('Could not reach the platform.', true); });
    }
  });

  // ---- the queue ----
  var lastStatus = null;            // so typing in the filter re-renders instead of re-fetching
  function loadStatus() {
    api('/kb/api/slack/status').then(function (j) {
      if (!j.ok) { failed(j.error || 'Could not load.'); return; }
      lastStatus = j;
      renderState(j);
      renderChannels(j);
      renderQueue(j.unassigned || []);
    }).catch(function () { failed('Could not reach the platform.'); });
  }
  // A keystroke in the filter must not hit the network - and must not lose the caret, so the box
  // is re-focused at the same position after the table is rebuilt.
  function refilter() {
    if (!lastStatus) return;
    var box = $('chChannels').querySelector('.ch-q');
    var pos = box ? box.selectionStart : null;
    renderChannels(lastStatus);
    var again = $('chChannels').querySelector('.ch-q');
    if (again && box === document.activeElement || (again && pos !== null)) {
      again.focus();
      try { again.setSelectionRange(pos, pos); } catch (_) {}
    }
  }
  function failed(msg) {
    $('chCount').textContent = '!';
    $('chQueue').innerHTML = '<div class="kb-empty"><h3>' + esc(msg) + '</h3><p>The rest of the knowledge base is unaffected.</p>' +
      '<button class="btn sm" id="chRetry">Retry</button></div>';
    $('chRetry').addEventListener('click', function () { $('chQueue').innerHTML = '<div class="fm-empty">Loading…</div>'; loadStatus(); });
  }
  function setCount(n) { var el = $('chCount'); el.textContent = n; el.classList.toggle('zero', !n); }
  function emptyState() {
    $('chQueue').innerHTML = '<div class="kb-empty"><h3>Nothing waiting</h3><p>Every conversation that arrived has been filed. ' +
      (C.connected ? 'Map a channel above and its conversations file themselves; anything the system is unsure about lands here.' : 'Connect Slack to start receiving conversations.') + '</p></div>';
  }

  function cardHtml(m) {
    var p = m.proposal || {}, ev = p.evidence || [];
    var hasProp = p.client_key !== undefined && p.client_key !== null;
    var chips = '<span class="fm-chip">#' + esc((m.channel || {}).name || '') + '</span>' +
      '<span class="fm-chip" title="' + esc(m.started || '') + '">' + esc(m.kind === 'thread' ? 'thread' : 'day') + ' · ' + esc(m.day || '') + '</span>' +
      '<span class="fm-chip">' + (m.messages || 0) + ' message' + (m.messages === 1 ? '' : 's') + '</span>';
    var why = (p.why ? esc(p.why) : '') +
      (ev.length ? '<ul>' + ev.slice(0, 4).map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul>' : '');
    var guess = '<div class="fm-guess"><div class="fm-guess-head"><span class="lbl">System\'s guess</span>' +
      (hasProp ? '<span class="who">' + esc(clientName(p.client_key)) + '</span>' +
        (p.confidence != null ? '<span class="kb-state ' + confClass(p.confidence) + '">' + pct(p.confidence) + '% sure</span>' : '')
        : '<span class="kb-state empty">none - pick a client</span>') +
      (why ? '<button class="fm-why-btn" type="button" aria-expanded="false">Why?</button>' : '') + '</div>' +
      (why ? '<div class="fm-why" hidden>' + why + '</div>' : '') + '</div>';
    var preview = (m.preview || []).length ? '<div class="ch-preview">' + m.preview.map(esc).join('\n') + '</div>' : '';
    var wl = m.will_learn || {};
    var teach = [].concat((wl.people || []).map(function (e) { return {k: e, t: e}; }),
                          (wl.domains || []).map(function (d) { return {k: d, t: '@' + d}; }));
    var teachHtml = teach.length
      ? '<div class="fm-teach"><span class="lbl">Will remember</span>' + teach.map(function (x) {
          return '<label><input type="checkbox" checked data-skip="' + esc(x.k) + '">' + esc(x.t) + '</label>';
        }).join('') + '</div>'
      : '';
    return '<article class="fm-row" data-rid="' + esc(m.key) + '" data-prop="' + (hasProp ? esc(p.client_key) : '') + '"' + (hasProp ? ' data-hasprop="1"' : '') + '>' +
      '<button class="fm-tog" type="button" aria-expanded="false" aria-label="Show details">&#9656;</button>' +
      '<div class="fm-main"><div class="fm-line1"><span class="fm-title">' + esc(m.title) + '</span><span class="fm-chips">' + chips + '</span></div>' + guess +
      '<div class="fm-detail" hidden>' + preview + teachHtml + '</div></div>' +
      '<div class="fm-act"><select class="kb-input fm-sel" aria-label="File under client">' + clientOpts(null) + '</select>' +
      '<button class="btn sm gold fm-assign">Assign</button>' +
      '<button class="btn sm fm-ignore" title="Drop this conversation without indexing it">Ignore</button></div></article>';
  }

  function openState() {
    var open = {why: {}, row: {}};
    Array.prototype.forEach.call($('chQueue').querySelectorAll('.fm-row'), function (row) {
      var rid = row.getAttribute('data-rid'); if (!rid) return;
      var d = row.querySelector('.fm-detail'); if (d && !d.hidden) open.row[rid] = 1;
      var w = row.querySelector('.fm-why'); if (w && !w.hidden) open.why[rid] = 1;
    });
    return open;
  }
  function restoreOpen(open) {
    Array.prototype.forEach.call($('chQueue').querySelectorAll('.fm-row'), function (row) {
      var rid = row.getAttribute('data-rid'); if (!rid) return;
      if (open.row[rid]) toggleRow(row, true);
      if (open.why[rid]) {
        var w = row.querySelector('.fm-why'), b = row.querySelector('.fm-why-btn');
        if (w && b) { w.hidden = false; b.textContent = 'Hide'; b.setAttribute('aria-expanded', 'true'); }
      }
    });
  }
  function renderQueue(items) {
    var open = openState();
    setCount(items.length);
    if (!items.length) { emptyState(); return; }
    $('chQueue').innerHTML = items.map(cardHtml).join('');
    Array.prototype.forEach.call($('chQueue').querySelectorAll('.fm-row'), function (row) {
      if (row.hasAttribute('data-hasprop')) row.querySelector('.fm-sel').value = row.getAttribute('data-prop');
      reflectChoice(row);
    });
    restoreOpen(open);
  }
  function toggleRow(row, open) {
    var d = row.querySelector('.fm-detail'), t = row.querySelector('.fm-tog');
    if (open === undefined) open = d.hidden;
    d.hidden = !open; row.classList.toggle('open', open);
    t.setAttribute('aria-expanded', open ? 'true' : 'false'); t.setAttribute('aria-label', open ? 'Hide details' : 'Show details');
  }
  function reflectChoice(row) {
    var sel = row.querySelector('.fm-sel'), btn = row.querySelector('.fm-assign');
    var override = sel.value !== row.getAttribute('data-prop');
    btn.textContent = override ? 'Assign to ' + clientName(sel.value) : 'Assign';
    btn.classList.toggle('override', override);
    var teach = row.querySelector('.fm-teach'); if (teach) teach.classList.toggle('hidden', sel.value === '');   // agency-wide teaches nothing
  }
  function skipsOf(row) {
    return Array.prototype.map.call(row.querySelectorAll('.fm-teach input:not(:checked)'), function (i) { return i.getAttribute('data-skip'); });
  }
  $('chQueue').addEventListener('change', function (e) {
    if (e.target.classList.contains('fm-sel')) reflectChoice(e.target.closest('.fm-row'));
    if (e.target.matches('.fm-teach input')) e.target.closest('label').classList.toggle('off', !e.target.checked);
  });
  var ignoreTimers = {};
  $('chQueue').addEventListener('click', function (e) {
    var t = e.target.closest('.fm-title');
    if (t) { toggleRow(t.closest('.fm-row')); return; }
    var b = e.target.closest('button'); if (!b) return;
    if (b.classList.contains('fm-tog')) { toggleRow(b.closest('.fm-row')); return; }
    if (b.classList.contains('fm-why-btn')) {
      var w = b.closest('.fm-guess').querySelector('.fm-why'), shown = w.hidden;
      w.hidden = !shown; b.textContent = shown ? 'Hide' : 'Why?'; b.setAttribute('aria-expanded', shown ? 'true' : 'false');
      return;
    }
    var row = b.closest('.fm-row'); if (!row) return;
    var rid = row.getAttribute('data-rid');
    if (b.classList.contains('fm-ignore')) {
      if (!b.classList.contains('confirm')) {
        b.classList.add('confirm'); b.textContent = 'Drop it?';
        ignoreTimers[rid] = setTimeout(function () { b.classList.remove('confirm'); b.textContent = 'Ignore'; }, 5000);
        return;
      }
      clearTimeout(ignoreTimers[rid]);
      act(row, 'ignore', []);
      return;
    }
    if (b.classList.contains('fm-assign')) act(row, row.querySelector('.fm-sel').value, skipsOf(row));
  });
  function act(row, ck, skip) {
    var rid = row.getAttribute('data-rid');
    row.classList.add('busy');
    return api('/kb/api/slack/assign', {key: rid, client_key: ck, skip: skip || []}).then(function (j) {
      if (!j.ok) { row.classList.remove('busy'); toast(j.error || 'That did not work - try again.', true); return false; }
      row.remove();
      var left = $('chQueue').querySelectorAll('.fm-row').length;
      setCount(left);
      if (!left) emptyState();
      if (ck !== 'ignore') { indexed += 1; var b = $('chStrip').querySelector('b.n'); if (b) b.textContent = indexed; }
      toast(ck === 'ignore' ? 'Conversation dropped - nothing was indexed.' : 'Filed under ' + clientName(ck) + '.');
      loadLog();
      return true;
    }).catch(function () { row.classList.remove('busy'); toast('Could not reach the platform.', true); return false; });
  }

  $('chSync').addEventListener('click', function () {
    var b = $('chSync'); b.disabled = true; $('chSyncStatus').textContent = 'Starting…';
    api('/kb/api/slack/sync', {since_days: parseInt($('chSince').value, 10) || 30}).then(function (j) {
      b.disabled = false;
      if (!j.ok) { $('chSyncStatus').textContent = ''; toast(j.error || 'Sync failed.', true); return; }
      $('chSyncStatus').textContent = 'Sync started (last ' + j.since_days + ' days); this page updates as it runs.';
      toast('Sync started - conversations appear as they are checked.');
      loadStatus();
    }).catch(function () { b.disabled = false; $('chSyncStatus').textContent = ''; toast('Sync failed.', true); });
  });

  // ---- what landed (Slack kinds only; the filter is server-side) ----
  var LOG_LABELS = {
    slack_filed:    ['Filed itself', 'a mapped channel or the system placed it'],
    slack_queued:   ['Waited',       'not sure enough, so it went to the queue'],
    slack_assigned: ['Confirmed',    'a person chose the client from the queue'],
    slack_ignored:  ['Ignored',      'a person kept it out of the library'],
    slack_moved:    ['Moved',        'already filed, then re-filed after a mapping change'],
    slack_mapped:   ['Mapped',       'a person declared which client a channel belongs to'],
    slack_purged:   ['Purged',       'the app was removed from Slack; everything deleted'],
    slack_channel:  ['Channel',      'renamed, archived, deleted, or the bot was removed']
  };
  var logKind = '';
  function logRow(e) {
    var lab = (LOG_LABELS[e.kind] || [e.kind, ''])[0];
    var who = e.actor === 'slack' ? 'automatic' : esc(e.actor || 'someone');
    var bits = [];
    if (e.kind === 'slack_filed') { bits.push('to <b>' + esc(clientName(e.client)) + '</b>'); bits.push('by ' + esc(e.by || '?')); if (e.confidence && e.by !== 'channel') bits.push(pct(e.confidence) + '% sure'); }
    else if (e.kind === 'slack_queued') { bits.push(e.guess || e.guess === '' ? 'best guess <b>' + esc(clientName(e.guess)) + '</b>' : 'no guess'); if (e.confidence) bits.push(pct(e.confidence) + '% sure'); }
    else if (e.kind === 'slack_assigned') { bits.push('to <b>' + esc(clientName(e.client)) + '</b>'); if (e.agreed === false) bits.push('<span class="fm-over">overruled the guess of ' + esc(clientName(e.guess)) + '</span>'); else if (e.agreed === true) bits.push('agreed with the guess'); }
    else if (e.kind === 'slack_ignored') { if (e.guess || e.guess === '') bits.push('had guessed ' + esc(clientName(e.guess))); }
    else if (e.kind === 'slack_moved') { bits.push('from <b>' + esc(clientName(e.guess)) + '</b> to <b>' + esc(clientName(e.client)) + '</b>'); }
    else if (e.kind === 'slack_mapped') { bits.push(e.client === null || e.client === undefined ? 'cleared' : 'to <b>' + esc(clientName(e.client)) + '</b>'); if (e.guess !== undefined && e.guess !== null && e.guess !== e.client) bits.push('was ' + esc(clientName(e.guess))); }
    else if (e.kind === 'slack_channel') { bits.push(esc((e.note || '').replace(/_/g, ' '))); }
    else if (e.kind === 'slack_purged') { bits.push((e.docs || 0) + ' documents · ' + (e.objects || 0) + ' objects deleted'); }
    if (e.note) bits.push('<span class="fm-over">' + esc(e.note) + '</span>');
    var pill = {slack_filed: 'lg-filed', slack_queued: 'lg-queued', slack_assigned: 'lg-assigned', slack_ignored: 'lg-ignored', slack_moved: 'lg-queued', slack_mapped: 'lg-assigned', slack_purged: 'lg-ignored', slack_channel: 'lg-ignored'}[e.kind] || '';
    // The title of a Slack row already begins "#channel - date", so the chip beside it printed the
    // channel twice on every line. Show the chip only when it adds something.
    var title = String(e.title || e.recording_id || '(untitled)');
    var dupChip = e.channel && title.toLowerCase().indexOf('#' + String(e.channel).toLowerCase()) === 0;
    return '<div class="fm-logrow">' +
      '<span class="fm-pill ' + pill + '">' + esc(lab) + '</span>' +
      '<span class="fm-logtitle">' + (e.channel && !dupChip ? '<span class="fm-chip">#' + esc(e.channel) + '</span> ' : '') + esc(title) + '</span>' +
      '<span class="fm-logbits">' + bits.join(' · ') + '</span>' +
      '<span class="fm-logwho">' + who + '</span>' +
      '<span class="fm-logwhen" title="' + esc(e.at ? new Date(e.at * 1000).toISOString() : '') + '">' + esc(e.at ? ago(new Date(e.at * 1000).toISOString()) : '') + '</span>' +
      // The model's reasoning runs to four or five lines and is the least-read thing on the row, so
      // it is clamped to two and opens on click. Clamped, never hidden: it is the audit trail.
      (e.why ? '<div class="fm-logwhy" role="button" tabindex="0" title="Show the full reason">' + esc(e.why) + '</div>' : '') + '</div>';
  }
  function renderFilters(counts, kinds) {
    var total = 0; kinds.forEach(function (k) { total += counts[k] || 0; });
    var html = ['<button class="fm-lchip' + (logKind ? '' : ' on') + '" data-kind="">All <span class="fm-lchipn">' + total + '</span></button>'];
    kinds.forEach(function (k) {
      if (!counts[k]) return;
      html.push('<button class="fm-lchip' + (logKind === k ? ' on' : '') + '" data-kind="' + esc(k) + '" title="' + esc((LOG_LABELS[k] || ['', ''])[1]) + '">' +
                esc((LOG_LABELS[k] || [k])[0]) + ' <span class="fm-lchipn">' + counts[k] + '</span></button>');
    });
    $('chLogFilters').innerHTML = html.join('');
  }
  // 🔴 THE SERVER PAGES THIS. The page used to ask for the whole record and slice it, which shipped
  // every event a workspace had ever produced to draw a screenful. `logOffset` is reset by anything
  // that changes WHAT is being listed (a kind filter, a re-sync); it survives a plain refresh.
  var logOffset = 0;
  function renderPager(j) {
    var el = $('chLogPager'); if (!el) return;
    var total = j.total || 0, from = total ? j.offset + 1 : 0, to = j.offset + (j.events || []).length;
    if (total <= (j.limit || 25) && !j.offset) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    el.innerHTML = '<span class="lg-range">' + from + '–' + to + ' of ' + total + '</span>' +
      '<span class="spacer"></span>' +
      '<button class="btn sm" data-page="prev"' + (j.offset ? '' : ' disabled') + '>Newer</button>' +
      '<button class="btn sm" data-page="next"' + (j.has_more ? '' : ' disabled') + '>Older</button>';
  }
  function loadLog() {
    var q = [];
    if (logKind) q.push('kind=' + encodeURIComponent(logKind));
    if (logOffset) q.push('offset=' + logOffset);
    api('/kb/api/slack/log' + (q.length ? '?' + q.join('&') : '')).then(function (j) {
      if (!j || !j.ok) { $('chLog').innerHTML = '<div class="fm-empty">' + esc((j && j.error) || 'Could not read the record.') + '</div>'; return; }
      renderFilters(j.counts || {}, j.kinds || []);
      logOffset = j.offset || 0;             // the server clamps a stale offset; follow it
      var n = j.total || 0, c = $('chLogCount'); c.textContent = n; c.className = 'fm-pill count' + (n ? '' : ' zero');
      $('chLog').innerHTML = j.events.length ? j.events.map(logRow).join('') : '<div class="fm-empty">Nothing yet. Decisions appear here as conversations arrive.</div>';
      renderPager(j);
    }).catch(function () { $('chLog').innerHTML = '<div class="fm-empty">Could not reach the platform.</div>'; });
  }
  $('chLogPager').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-page]'); if (!b || b.disabled) return;
    var step = 25;                            // matches kb_activity.PAGE_DEFAULT
    logOffset = b.getAttribute('data-page') === 'next' ? logOffset + step : Math.max(0, logOffset - step);
    loadLog();
    $('chLogH').scrollIntoView({block: 'start', behavior: 'smooth'});
  });
  // Clamped reasoning opens on click or Enter/Space. Delegated, so it survives every re-render.
  $('chLog').addEventListener('click', function (e) {
    var w = e.target.closest('.fm-logwhy'); if (w) w.classList.toggle('open');
  });
  $('chLog').addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var w = e.target.closest('.fm-logwhy'); if (!w) return;
    e.preventDefault(); w.classList.toggle('open');
  });

  $('chLogFilters').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-kind]'); if (!b) return;
    logKind = b.getAttribute('data-kind');
    logOffset = 0;                            // a new filter is a new list - start at the top
    loadLog();
  });

  loadStatus();
  loadLog();
})();
