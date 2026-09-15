/* kb_ask.js - the Ask panel: a floating assistant with voice, settings and a feedback loop.
 *
 * Shaped after Sentinel's assistant panel, because that shape is already trusted: a bubble, a card
 * that opens over the page, a draggable header, drawers for history and settings, a voice bar.
 *
 * 🔴 THE CITATIONS ARRIVE BEFORE THE ANSWER DOES. The `retrieval` event is sent before the model is
 * called, so the reader watches the answer written against sources already on screen. Appending
 * references afterwards produces the same pixels and a different claim.
 *
 * 🔴 NOTHING IS EVER SENT BY THE MICROPHONE OR BY A PAUSE. Dictation is reviewable text: it lands
 * in the box, you edit it, you press Send. Voice only decides whether the ANSWER is read aloud.
 *
 * 🔴 A VOICE THAT GOES SILENT READS AS BROKEN. Every way a browser can drop an utterance is handled
 * (priming inside the click, sentence-sized chunks, a start timeout), and any failure is SAID in
 * the log with the real reason and a pointer to Listen, rather than nothing happening.
 *
 * 🔴 NOTHING TYPED IS EVER THROWN AWAY: the question on an auth failure, the correction on a save
 * failure. The session is a hard 12 hour cap, so being signed out arrives as a button failing.
 */
(function () {
  'use strict';

  var LS = 'bb.kb.';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function el(t, c, x) { var n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; }
  function esc(s) { return String(s == null ? '' : s); }
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  var ICONS = {
    spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="3.2"/></svg>',
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H19v15H5.5A1.5 1.5 0 0 0 4 20.5z"/><path d="M4 17.5A1.5 1.5 0 0 1 5.5 16H19"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 5l-7 7 7 7"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    sound: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 9v6h3l5 4V5L7 9z"/><path d="M16 9a4 4 0 0 1 0 6"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13"/></svg>'
  };

  var A = {
    open: false, convId: '', busy: false, ctrl: null,
    scope: [], client: null,       // client: null = whole library, "" = agency-wide, "geocon" = one
    clients: [], settings: null, lastRetrieval: null, speakThis: false
  };
  try { A.scope = JSON.parse(localStorage.getItem(LS + 'scope') || '[]'); } catch (e) { A.scope = []; }
  try { var sc = localStorage.getItem(LS + 'client'); A.client = sc === null ? null : JSON.parse(sc); } catch (e) { A.client = null; }

  function panel() { return $('#kbPanel'); }
  function log() { return $('#kbLog'); }

  // --- open / close / drag / resize ---------------------------------------------------------
  function openPanel(prefill, client) {
    A.open = true;
    panel().hidden = false;
    $('#kbFab').classList.add('is-open');
    if (client !== undefined) { A.client = client; saveScope(); }
    restoreBox();
    renderScopeChip();
    if (!log().childElementCount) greet();
    loadSettings();
    var i = $('#kbInput');
    i.focus();
    if (prefill) { i.value = prefill; autosize(i); }
    localStorage.setItem(LS + 'panelOpen', '1');
  }
  function closePanel() {
    A.open = false;
    panel().hidden = true;
    $('#kbFab').classList.remove('is-open');
    stopSpeaking();
    stopRecording();
    localStorage.setItem(LS + 'panelOpen', '0');
  }

  function floats() { return window.innerWidth > 560; }
  function restoreBox() {
    if (!floats()) return;
    try {
      var b = JSON.parse(localStorage.getItem(LS + 'box') || 'null');
      if (!b) return;
      var p = panel();
      p.style.width = Math.max(340, Math.min(b.w, innerWidth - 24)) + 'px';
      p.style.height = Math.max(380, Math.min(b.h, innerHeight - 24)) + 'px';
      if (b.r != null) p.style.right = Math.max(8, Math.min(b.r, innerWidth - 340)) + 'px';
      if (b.b != null) p.style.bottom = Math.max(8, Math.min(b.b, innerHeight - 380)) + 'px';
    } catch (e) { /* a corrupt box is not worth failing the panel over */ }
  }
  function saveBox() {
    if (!floats()) return;
    var p = panel(), r = p.getBoundingClientRect();
    localStorage.setItem(LS + 'box', JSON.stringify({
      w: Math.round(r.width), h: Math.round(r.height),
      r: Math.round(innerWidth - r.right), b: Math.round(innerHeight - r.bottom)
    }));
  }

  function wireDrag() {
    var p = panel(), head = $('#kbHead'), grip = $('#kbGrip');
    var mode = null, sx = 0, sy = 0, base = null;
    function start(m, e) {
      if (!floats()) return;
      if (e.target.closest('button')) return;
      mode = m; sx = e.clientX; sy = e.clientY;
      var r = p.getBoundingClientRect();
      base = { w: r.width, h: r.height, r: innerWidth - r.right, b: innerHeight - r.bottom };
      p.classList.add('is-dragging');
      e.preventDefault();
    }
    head.addEventListener('mousedown', function (e) { start('move', e); });
    grip.addEventListener('mousedown', function (e) { start('size', e); });
    document.addEventListener('mousemove', function (e) {
      if (!mode) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (mode === 'move') {
        p.style.right = Math.max(8, Math.min(base.r - dx, innerWidth - 340)) + 'px';
        p.style.bottom = Math.max(8, Math.min(base.b - dy, innerHeight - 200)) + 'px';
      } else {
        p.style.width = Math.max(340, Math.min(base.w - dx, innerWidth - 24)) + 'px';
        p.style.height = Math.max(380, Math.min(base.h - dy, innerHeight - 24)) + 'px';
      }
    });
    document.addEventListener('mouseup', function () {
      if (!mode) return;
      mode = null; p.classList.remove('is-dragging'); saveBox();
    });
    head.addEventListener('dblclick', function (e) {
      if (e.target.closest('button')) return;
      p.style.width = p.style.height = p.style.right = p.style.bottom = '';
      localStorage.removeItem(LS + 'box');
    });
  }

  function greet() {
    var d = el('div', 'kbp-empty');
    d.appendChild(el('b', null, 'Ask the library'));
    d.appendChild(document.createTextNode(
      'Plans, briefs, meetings, the playbook. Every answer cites the passages it came from, and if '
      + 'one is wrong you can say so here and the next person gets your correction.'));
    log().appendChild(d);
  }

  // --- settings -------------------------------------------------------------------------------
  function loadSettings() {
    if (A.settings) return Promise.resolve(A.settings);
    return window.kbApi('/settings').then(function (j) {
      A.settings = j.settings;
      renderSpeakSwitch();
      renderSubtitle();
      return A.settings;
    }).catch(function () { return null; });
  }
  function saveSettings(patch) {
    A.settings = Object.assign({}, A.settings, patch);
    renderSpeakSwitch();
    renderSubtitle();
    return window.kbApi('/settings', { method: 'POST', body: patch }).then(function (j) {
      A.settings = j.settings;
      renderSpeakSwitch();
      renderSubtitle();
      if (!$('#kbSettings').hidden) paintSettings();
      return A.settings;
    }).catch(function (e) { if (!e.auth) window.kbToast(e.message, true); });
  }
  function speakOn() { return !!(A.settings && A.settings.speak_replies); }
  function ttsEngine() { return (A.settings && A.settings.voice_engine) || 'browser'; }
  function ttsVoice() { return (A.settings && A.settings.voice_name) || 'Aoede'; }

  function renderSpeakSwitch() {
    var b = $('#kbSpeak');
    if (!b) return;
    b.setAttribute('aria-checked', speakOn() ? 'true' : 'false');
    b.disabled = !speakSupported();
    b.title = speakSupported() ? 'Read answers aloud'
      : 'This browser cannot speak. Use Chrome, Edge or Safari.';
  }
  function speakSupported() { return !!window.speechSynthesis || ttsEngine() !== 'browser'; }

  function renderSubtitle() {
    var s = $('#kbSub');
    if (!s) return;
    var bits = [];
    var m = A.settings && A.settings.model_effective;
    if (m) bits.push((A.settings.models.filter(function (x) { return x.id === m; })[0] || {}).label || m);
    bits.push(scopeWords());
    s.textContent = bits.join(' · ');
  }

  function paintSettings() {
    var body = $('#kbSettingsBody');
    body.innerHTML = '';
    var S = A.settings;
    if (!S) { body.appendChild(el('p', 'kbp-note', 'Loading…')); return; }

    var f = el('label', 'kbp-field');
    f.appendChild(el('b', null, 'Which model answers'));
    var sel = document.createElement('select');
    sel.className = '';
    var opts = [['', 'Automatic (' + ((S.models.filter(function (m) { return m.id === S.model_effective; })[0] || {}).label || 'none') + ')']];
    S.models.forEach(function (m) {
      opts.push([m.id, m.label + ' - ' + m.model + (m.configured ? '' : ' (no key on this deployment)')]);
    });
    sel.innerHTML = opts.map(function (o) {
      return '<option value="' + esc(o[0]) + '"' + (S.model === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
    }).join('');
    sel.onchange = function () { saveSettings({ model: sel.value }); };
    f.appendChild(sel);
    var note = el('span', null, S.model_note || 'Automatic uses whichever model this deployment '
      + 'puts first, and falls back to another if it cannot answer.');
    f.appendChild(note);
    body.appendChild(f);

    var sect = el('div', 'kbp-sect');
    sect.appendChild(el('b', null, 'Voice'));

    var row = el('div', 'kbp-switch-row');
    var l = el('div', 'l');
    l.appendChild(el('b', null, 'Read answers aloud'));
    l.appendChild(el('div', 'kbp-note', 'The microphone works either way. Dictation always lands in '
      + 'the box for you to edit; nothing is ever sent by the microphone or by a pause.'));
    row.appendChild(l);
    var sw = el('button', 'kbp-switch');
    sw.type = 'button';
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', S.speak_replies ? 'true' : 'false');
    sw.appendChild(el('span'));
    sw.onclick = function () { saveSettings({ speak_replies: !speakOn() }); };
    row.appendChild(sw);
    sect.appendChild(row);

    var vf = el('label', 'kbp-field');
    vf.appendChild(el('b', null, 'Voice engine'));
    var vsel = document.createElement('select');
    var engines = [['browser', "The browser's own voice - free, never leaves your computer"]];
    (S.tts.engines || []).forEach(function (e) { engines.push([e.id, e.label + ' - ' + e.note]); });
    vsel.innerHTML = engines.map(function (o) {
      return '<option value="' + esc(o[0]) + '"' + (S.voice_engine === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
    }).join('');
    vsel.onchange = function () { saveSettings({ voice_engine: vsel.value }); };
    vf.appendChild(vsel);
    sect.appendChild(vf);

    if (S.voice_engine !== 'browser') {
      var nf = el('label', 'kbp-field');
      nf.appendChild(el('b', null, 'Voice'));
      var nsel = document.createElement('select');
      nsel.innerHTML = (S.tts.voices || []).map(function (v) {
        return '<option value="' + esc(v) + '"' + (S.voice_name === v ? ' selected' : '') + '>' + esc(v) + '</option>';
      }).join('');
      nsel.onchange = function () { saveSettings({ voice_name: nsel.value }); };
      nf.appendChild(nsel);
      var hear = el('button', 'kbp-btn', 'Hear it');
      hear.style.alignSelf = 'flex-start';
      hear.onclick = function () {
        speak('This is the voice that will read your answers.', null, true);
      };
      nf.appendChild(hear);
      sect.appendChild(nf);
    }
    body.appendChild(sect);

    var who = el('div', 'kbp-sect');
    who.appendChild(el('b', null, 'This session'));
    who.appendChild(el('div', 'kbp-note', window.KB_SHARED_LOGIN
      ? 'You are signed in with a shared password, so these settings and your conversations are '
        + 'shared with everybody using it. Sign in with Google or Microsoft for your own.'
      : 'Signed in as ' + esc(window.KB_ACTOR || '') + '. These settings follow you to any browser.'));
    body.appendChild(who);
  }

  // --- the scope picker: CLIENT first, then that scope's folders --------------------------------
  function saveScope() {
    localStorage.setItem(LS + 'scope', JSON.stringify(A.scope));
    localStorage.setItem(LS + 'client', JSON.stringify(A.client));
  }
  function clientName(key) {
    if (key === null || key === undefined) return 'Everything';
    if (key === '') return 'Agency-wide';
    var c = A.clients.filter(function (x) { return x.key === key; })[0];
    return c ? c.name : key;
  }
  function scopeWords() {
    var base = clientName(A.client);
    if (!A.scope.length) return base;
    if (A.scope.length === 1) return base + ' · ' + (A.scope[0] === '/' ? 'no folder' : A.scope[0]);
    return base + ' · ' + A.scope.length + ' folders';
  }
  function renderScopeChip() {
    var b = $('#kbScopeLabel');
    if (b) b.textContent = scopeWords();
    renderSubtitle();
  }

  function toggleScope() {
    var m = $('#kbScope');
    if (!m.hidden) { m.hidden = true; return; }
    paintScope();
    m.hidden = false;
  }

  function paintScope() {
    var m = $('#kbScope');
    m.innerHTML = '';
    var head = el('div', 'kbp-scope-head');
    head.appendChild(el('b', null, 'What should I read?'));
    head.appendChild(el('span', null, 'Pick a client and I read their documents PLUS the agency-wide '
      + 'ones (the playbook, platform docs). I never read another client.'));
    m.appendChild(head);

    var list = el('div', 'kbp-scope-list');
    list.appendChild(el('div', 'kbp-scope-sect', 'Scope'));
    [[null, 'Everything', ''], ['', 'Agency-wide only', '']].forEach(function (o) {
      list.appendChild(scopeRadio(o[0], o[1], o[2]));
    });
    if (A.clients.length) {
      list.appendChild(el('div', 'kbp-scope-sect', 'Clients'));
      A.clients.forEach(function (c) {
        list.appendChild(scopeRadio(c.key, c.name, c.count ? String(c.count) : ''));
      });
    }
    m.appendChild(list);

    var foot = el('div', 'kbp-scope-foot');
    foot.appendChild(el('span', null, A.client === null
      ? 'Reading the whole library, every client included.'
      : A.client === ''
        ? 'Reading agency-wide documents only.'
        : 'Reading ' + clientName(A.client) + ' plus agency-wide documents.'));
    var done = el('button', 'kbp-btn gold', 'Done');
    done.onclick = function () { m.hidden = true; };
    foot.appendChild(done);
    m.appendChild(foot);
  }

  function scopeRadio(key, label, count) {
    var row = el('div', 'kbp-scope-row');
    var lab = el('label');
    var r = document.createElement('input');
    r.type = 'radio'; r.name = 'kbpscope';
    r.checked = A.client === key;
    r.onchange = function () {
      A.client = key;
      A.scope = [];                  // folders belong to a scope; carrying them across is nonsense
      saveScope(); renderScopeChip(); paintScope();
    };
    lab.appendChild(r);
    lab.appendChild(el('span', null, label));
    if (count) lab.appendChild(el('small', null, count));
    row.appendChild(lab);
    return row;
  }

  function loadClients() {
    return window.kbApi('/clients').then(function (j) {
      A.clients = j.clients || [];
      renderScopeChip();
    }).catch(function () { /* the picker still offers Everything and Agency-wide */ });
  }

  // --- asking ------------------------------------------------------------------------------------
  function send() {
    if (A.busy) return;
    var input = $('#kbInput');
    var q = input.value.trim();
    if (!q) return;
    primeSpeech();
    var empty = log().querySelector('.kbp-empty');
    if (empty) empty.remove();

    var mine = el('div', 'kbp-msg me');
    mine.appendChild(el('div', 'kbp-bubble', q));
    log().appendChild(mine);
    input.value = '';
    autosize(input);

    var turn = el('div', 'kbp-msg ai');
    var bubble = el('div', 'kbp-bubble');
    var meta = el('div', 'kbp-meta');
    meta.innerHTML = '<span class="kbp-dots">searching the library</span>';
    bubble.appendChild(meta);
    var cites = el('div', 'kbp-cites');
    bubble.appendChild(cites);
    var ans = el('div', 'ans');
    bubble.appendChild(ans);
    turn.appendChild(bubble);
    log().appendChild(turn);
    toBottom();

    A.busy = true;
    $('#kbSend').disabled = true;
    var ctrl = new AbortController();
    A.ctrl = ctrl;
    var willSpeak = speakOn();
    if (willSpeak) setPhase('thinking', 'thinking');

    var state = { retrieval: null, model: null, text: '', answerId: '' };

    fetch('/kb/ask', {
      method: 'POST', signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: q, folders: A.scope, conv_id: A.convId,
                             client: A.client, spoken: willSpeak })
    }).then(function (r) {
      if (r.status === 401) { input.value = q; throw Object.assign(new Error('auth'), { auth: true }); }
      if (!r.ok || !r.body) throw new Error('The assistant could not be reached (' + r.status + ')');
      return readStream(r.body.getReader(), function (ev, data) {
        if (ev === 'retrieval') {
          state.retrieval = data; A.lastRetrieval = data;
          renderCites(cites, data);
          meta.innerHTML = '<span class="kbp-dots">writing</span>';
        } else if (ev === 'model') {
          state.model = data;
          meta.innerHTML = '';
          meta.appendChild(modelBadge(data));
          if (state.retrieval && !state.retrieval.semantic) meta.appendChild(kwBadge(state.retrieval));
          if (state.retrieval && state.retrieval.client_name) {
            meta.appendChild(el('span', 'kbp-badge', state.retrieval.client_name));
          }
        } else if (ev === 'token') {
          state.text += data.t;
          ans.textContent = splitProposal(state.text).prose;
          toBottom();
        } else if (ev === 'done') {
          state.answerId = data.answer_id;
          A.convId = data.conv_id;
          meta.appendChild(el('span', null, Math.round(data.ms / 100) / 10 + 's'));
        } else if (ev === 'error') {
          var e = el('div', 'kbp-note bad', data.message);
          bubble.appendChild(e);
          if (!data.retrieval_ok) meta.innerHTML = '';
        }
      });
    }).then(function () {
      var split = splitProposal(state.text);
      var prop = parseProposal(split.raw, state.retrieval);
      state.text = split.prose;
      // 🔴 THE CARD IS RENDERED EVEN WITH NO PROSE. The model is asked to say what it is proposing
      // and why, and sometimes it just emits the block. Gating the card on prose meant that answer
      // rendered as an EMPTY BUBBLE: no text, no card, no feedback buttons, and the proposal lost.
      // Whichever half arrives is shown, and if neither does that is said rather than left blank.
      if (split.prose.trim()) ans.innerHTML = mdToHtml(split.prose, state.retrieval, cites);
      if (prop) {
        if (!split.prose.trim()) {
          ans.appendChild(el('div', 'kbp-note', 'Proposing this for the library:'));
        }
        bubble.appendChild(proposalCard(prop));
      }
      if (split.prose.trim() || prop) {
        if (split.prose.trim()) bubble.appendChild(listenButton(split.prose));
        bubble.appendChild(verdictBar(q, state));
      } else if (!bubble.querySelector('.kbp-note.bad')) {
        // No prose, no usable block, and no error already shown: say so rather than leave a blank.
        bubble.appendChild(el('div', 'kbp-note bad', 'The model returned nothing usable. The '
          + 'passages above are the real search result and are still correct.'));
      }
      if (willSpeak && split.prose.trim()) speak(split.prose, bubble);
      else setPhase('idle');
    }).catch(function (err) {
      setPhase('idle');
      if (err.name === 'AbortError') {
        meta.innerHTML = ''; meta.appendChild(el('span', null, 'stopped'));
        state.text = splitProposal(state.text).prose;
        if (state.text.trim()) bubble.appendChild(verdictBar(q, state));
        return;
      }
      meta.innerHTML = '';
      var e = el('div', 'kbp-note bad');
      if (err.auth) e.innerHTML = 'Your session has expired. <a href="/" style="color:var(--kbp-accent)">Sign in again</a>. Your question is back in the box.';
      else e.textContent = err.message;
      bubble.appendChild(e);
    }).then(function () {
      A.busy = false; A.ctrl = null;
      $('#kbSend').disabled = false;
      toBottom();
    });
  }

  function toBottom() { var l = log(); l.scrollTop = l.scrollHeight; }

  function readStream(reader, onEvent) {
    var dec = new TextDecoder(), buf = '';
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) { flush(true); return; }
        buf += dec.decode(r.value, { stream: true });
        flush(false);
        return pump();
      });
    }
    function flush(final) {
      var parts = buf.split('\n\n');
      buf = final ? '' : parts.pop();
      parts.forEach(function (block) {
        var ev = 'message', data = '';
        block.split('\n').forEach(function (line) {
          if (line.indexOf('event:') === 0) ev = line.slice(6).trim();
          else if (line.indexOf('data:') === 0) data += line.slice(5).trim();
        });
        if (!data) return;
        try { onEvent(ev, JSON.parse(data)); } catch (e) { /* a partial frame */ }
      });
    }
    return pump();
  }

  function modelBadge(m) {
    var b = el('span', 'kbp-badge model', m.label + (m.fallback ? ' (fallback)' : ''));
    b.title = m.model + (m.fallback ? ' - the first choice could not answer, so this one did.' : '');
    return b;
  }
  function kwBadge(r) {
    var b = el('span', 'kbp-badge kw', 'wording only');
    b.title = r.semantic_error || 'meaning search was unavailable';
    return b;
  }

  function renderCites(host, r) {
    host.innerHTML = '';
    if (!r.excerpts.length) {
      host.appendChild(el('div', 'kbp-note', r.documents_searched
        ? 'Nothing in ' + (r.scope.length || r.client !== null ? 'that scope' : 'the library') + ' matched this.'
        : 'That scope contains no documents.'));
      return;
    }
    r.excerpts.forEach(function (e, i) {
      var c = el('div', 'kbp-cite');
      c.appendChild(el('span', 'n', '[' + (i + 1) + ']'));
      c.appendChild(el('span', 't', e.title));
      if (e.trust === 'verified') c.appendChild(el('span', 'kbp-badge verified', 'CORRECTION'));
      c.appendChild(el('span', 'f', e.folder || 'no folder'));
      c.appendChild(foundBadge(e.found_by));
      c.title = e.passage.slice(0, 400);
      c.onclick = function () { if (window.kbOpenDoc) window.kbOpenDoc(e.document_id, e.ord); };
      host.appendChild(c);
    });
    if (!r.semantic) {
      host.appendChild(el('div', 'kbp-note warn', 'Meaning search was unavailable, so these were '
        + 'found by wording only (' + (r.semantic_error || 'reason not recorded') + '). Something '
        + 'relevant but differently worded could have been missed.'));
    }
  }
  function foundBadge(found) {
    var both = found.length > 1, label = both ? 'both' : (found[0] || '');
    var b = el('span', 'kbp-found ' + (both ? 'both' : label), label);
    b.title = both ? 'wording AND meaning search found this'
      : label === 'semantic' ? 'found by meaning, not by shared words' : 'found by shared words';
    return b;
  }

  function mdToHtml(text, retrieval, citesHost) {
    var html = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^\s*[-*]\s+(.*)$/gm, '• $1')
      .replace(/\[(\d{1,2})\]/g, function (m, n) {
        var i = +n - 1;
        if (!retrieval || !retrieval.excerpts[i]) return m;
        return '<a href="#" data-cite="' + i + '" style="color:var(--kbp-accent);text-decoration:none;font-weight:700">[' + n + ']</a>';
      });
    var wrap = document.createElement('div');
    wrap.innerHTML = html;
    wrap.querySelectorAll('[data-cite]').forEach(function (a) {
      a.onclick = function (e) {
        e.preventDefault();
        var node = citesHost.children[+a.dataset.cite];
        if (node) { node.scrollIntoView({ block: 'nearest' }); node.click(); }
      };
    });
    return wrap.innerHTML;
  }

  // --- proposed edits ---------------------------------------------------------------------------
  var FENCE = '```bb-edit';
  function splitProposal(text) {
    var i = text.indexOf(FENCE);
    if (i < 0) return { prose: text, raw: null };
    var rest = text.slice(i + FENCE.length), end = rest.indexOf('```');
    return { prose: text.slice(0, i).trimEnd(), raw: end < 0 ? null : rest.slice(0, end).trim() };
  }
  function parseProposal(raw, retrieval) {
    if (!raw) return null;
    var p;
    try { p = JSON.parse(raw); } catch (e) { return null; }
    if (!p || (p.action !== 'append' && p.action !== 'create')) return null;
    var text = String(p.text || '').trim();
    if (!text) return null;
    var out = { action: p.action, text: text,
                summary: String(p.summary || '').trim() || 'Write this into the library' };
    if (p.action === 'append') {
      var ex = (retrieval && retrieval.excerpts) || [], n = parseInt(p.passage, 10);
      if (!(n >= 1 && n <= ex.length)) return null;
      out.target = ex[n - 1];
      out.heading = String(p.heading || '').trim() || 'Update';
    } else {
      out.title = String(p.title || '').trim();
      out.folder = String(p.folder || '').trim();
      if (!out.title) return null;
    }
    return out;
  }
  function proposalCard(p) {
    var card = el('div', 'kbp-propose');
    var head = el('div', 'kbp-propose-h');
    head.appendChild(el('span', 'kbp-badge model', 'PROPOSED EDIT'));
    head.appendChild(el('span', null, p.summary));
    card.appendChild(head);
    card.appendChild(el('div', 'kbp-propose-where', p.action === 'append'
      ? 'Adds a dated section to the end of "' + p.target.title + '" in ' + (p.target.folder || 'no folder')
        + '. Nothing already in that document changes.'
      : 'Creates a new document "' + p.title + '" in ' + (p.folder || 'no folder') + '.'));
    if (p.action === 'append') card.appendChild(el('div', 'kbp-propose-head', '## ' + p.heading));
    card.appendChild(el('div', 'kbp-propose-body', p.text));

    var row = el('div', 'kbp-verdict');
    var ok = el('button', 'kbp-btn gold', p.action === 'create' ? 'Create it' : 'Add it');
    var no = el('button', 'kbp-btn', 'Discard');
    row.appendChild(ok); row.appendChild(no);
    row.appendChild(el('span', 'kbp-note', 'Nothing has changed yet. Every version is kept.'));
    card.appendChild(row);

    no.onclick = function () { card.innerHTML = ''; card.appendChild(el('span', 'kbp-note', 'Discarded. Nothing was written.')); };
    ok.onclick = function () {
      ok.disabled = no.disabled = true; ok.textContent = 'Saving…';
      var req = p.action === 'append'
        ? window.kbApi('/docs/' + p.target.document_id + '/append', { method: 'POST', body: {
            heading: p.heading, text: p.text, note: p.summary, via: 'assistant' } })
        : window.kbApi('/docs', { method: 'POST', body: {
            title: p.title, folder: p.folder, body: p.text, kind: 'note', client: A.client || '' } });
      req.then(function (j) {
        card.innerHTML = '';
        var done = el('div', 'kbp-propose-h');
        done.appendChild(el('span', 'kbp-badge verified', 'WRITTEN'));
        done.appendChild(el('span', null, (p.action === 'create' ? 'Created "' : 'Added to "')
          + j.doc.title + '". The previous version is kept in its history.'));
        card.appendChild(done);
        var open = el('button', 'kbp-btn', 'Open it');
        open.onclick = function () { if (window.kbOpenDoc) window.kbOpenDoc(j.doc.id); };
        card.appendChild(open);
        if (window.kbRefresh) window.kbRefresh();
      }).catch(function (err) {
        ok.disabled = no.disabled = false;
        ok.textContent = p.action === 'create' ? 'Create it' : 'Add it';
        if (!err.auth) window.kbToast(err.message, true);
      });
    };
    return card;
  }

  // --- feedback: a verdict AND the reason -------------------------------------------------------
  function verdictBar(question, state) {
    var wrap = el('div');
    var bar = el('div', 'kbp-verdict');
    var box = el('div', 'kbp-correct');

    [['right', 'Right', 'ok'], ['elsewhere', 'Right, not here', ''], ['wrong', 'Wrong', 'danger']]
      .forEach(function (v) {
        var b = el('button', 'kbp-btn' + (v[2] ? ' ' + v[2] : ''), v[1]);
        b.title = {
          right: 'The answer is correct and so are its sources. Tell me why if you like.',
          elsewhere: 'Right answer, wrong sources. A retrieval problem, so it makes no correction '
            + 'unless you add one.',
          wrong: 'The answer is wrong. Write the rule and the next person gets your version.'
        }[v[0]];
        b.onclick = function () { openCorrection(v[0]); };
        bar.appendChild(b);
      });
    wrap.appendChild(bar);
    wrap.appendChild(box);

    function openCorrection(verdict) {
      box.classList.add('on');
      box.innerHTML = '';
      // 🔴 A CONTEXT BOX ON ALL THREE VERDICTS, including Right. "It is right" and "it is right
      // BECAUSE the Q3 plan supersedes the Q2 one" are worth very different amounts to the next
      // person, and a thumbs-up with nowhere to explain it throws the second one away.
      box.appendChild(el('div', 'kbp-note', {
        right: 'Why was it right? Optional, and worth a lot: what made this answer good is the part '
          + 'nobody can reconstruct later.',
        elsewhere: 'What SHOULD it have cited, or what does the library not say yet? Leave it blank '
          + 'to record only that the sources were wrong.',
        wrong: 'Write the rule in one line, as you would tell a colleague. It becomes a trusted '
          + 'note and the next person asking this gets it first.'
      }[verdict]));

      var rule = document.createElement('input');
      rule.className = 'kbp-input';
      rule.placeholder = verdict === 'right'
        ? 'What made it right? (optional)'
        : 'The rule, in one line. For example: the margin floor is fifty per cent from Q3.';
      box.appendChild(rule);

      var more = document.createElement('textarea');
      more.className = 'kbp-input';
      more.placeholder = 'More context: why, since when, who decided it (optional).';
      more.style.marginTop = '7px';
      box.appendChild(more);

      // Dictate the context too. Same rule as the composer: it lands as text you can edit.
      if (SR) {
        var dictate = el('button', 'kbp-btn', 'Dictate');
        dictate.style.marginTop = '7px';
        dictate.onclick = function () { dictateInto(more, dictate); };
        box.appendChild(dictate);
      }

      var ticks = [];
      var ex = (state.retrieval && state.retrieval.excerpts) || [];
      if (verdict !== 'right' && ex.length) {
        box.appendChild(el('div', 'kbp-note', 'Which of these was wrong? A ticked passage is pushed '
          + 'below your correction next time. The document itself is never edited.'));
        ex.forEach(function (e, i) {
          var row = el('label', 'kbp-tick');
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = (i === 0 && verdict === 'wrong');
          cb.value = e.passage_id;
          ticks.push(cb);
          row.appendChild(cb);
          row.appendChild(el('span', null, '[' + (i + 1) + '] ' + e.title));
          box.appendChild(row);
        });
      }

      var row2 = el('div', 'kbp-verdict');
      var save = el('button', 'kbp-btn gold', verdict === 'right' ? 'Send' : 'Save the correction');
      var cancel = el('button', 'kbp-btn', 'Cancel');
      cancel.onclick = function () { box.classList.remove('on'); box.innerHTML = ''; };
      row2.appendChild(save); row2.appendChild(cancel);
      box.appendChild(row2);
      rule.focus();

      save.onclick = function () {
        save.disabled = true; save.textContent = 'Saving…';
        window.kbApi('/feedback', { method: 'POST', body: {
          question: question, answer: state.text, verdict: verdict,
          rule: rule.value, correction: more.value,
          cited: ex.map(function (e) {
            return { passage_id: e.passage_id, document_id: e.document_id, title: e.title,
                     folder: e.folder, trust: e.trust };
          }),
          superseded: ticks.filter(function (c) { return c.checked; }).map(function (c) { return c.value; }),
          model: (state.model || {}).model || '', conv_id: A.convId, answer_id: state.answerId,
          scope: (state.retrieval || {}).scope || [], client: A.client,
          semantic: !!(state.retrieval || {}).semantic
        } }).then(function (j) {
          box.classList.remove('on'); box.innerHTML = ''; bar.innerHTML = '';
          var done = el('span', 'kbp-done');
          if (j.feedback.doc_id) {
            done.textContent = 'Saved as a trusted note. The next person asking this gets it first.';
            bar.appendChild(done);
            var open = el('button', 'kbp-btn', 'Open it');
            open.onclick = function () { if (window.kbOpenDoc) window.kbOpenDoc(j.feedback.doc_id); };
            bar.appendChild(open);
          } else {
            done.textContent = 'Recorded. Thank you.';
            bar.appendChild(done);
          }
          var undo = el('button', 'kbp-btn', 'Withdraw');
          undo.onclick = function () {
            window.kbApi('/feedback/' + j.feedback.id + '/withdraw', { method: 'POST' })
              .then(function () {
                bar.innerHTML = '';
                bar.appendChild(el('span', 'kbp-done', 'Withdrawn. Any note it made is archived.'));
                if (window.kbRefresh) window.kbRefresh();
              }).catch(function (e) { if (!e.auth) window.kbToast(e.message, true); });
          };
          bar.appendChild(undo);
          if (window.kbRefresh) window.kbRefresh();
        }).catch(function (err) {
          // The typed words stay in the box. A save that loses what somebody wrote is how people
          // stop writing corrections at all.
          save.disabled = false;
          save.textContent = verdict === 'right' ? 'Send' : 'Save the correction';
          if (!err.auth) window.kbToast(err.message, true);
        });
      };
    }
    return wrap;
  }

  // --- voice OUT ----------------------------------------------------------------------------------
  var tts = { audio: null, url: '', abort: null, seq: 0, el: null, primed: false, synthPrimed: false,
              utters: [], failNoted: '' };
  var SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=';

  function setPhase(phase, text) {
    var bar = $('#kbConvo');
    if (!bar) return;
    bar.classList.remove('is-recording', 'is-thinking', 'is-speaking');
    if (phase === 'idle') { bar.hidden = true; return; }
    bar.classList.add('is-' + phase);
    $('#kbConvoText').textContent = text || phase;
    bar.hidden = false;
  }

  /* Called INSIDE the Send / mic click. Some browsers only let audio start from a gesture and the
   * answer arrives seconds later: a silent utterance and a silent clip played now keep the door
   * open for the real reply. Harmless where it is not needed. */
  function primeSpeech() {
    if (!speakOn()) return;
    var synth = window.speechSynthesis;
    if (synth && !tts.synthPrimed && !synth.speaking && !synth.pending) {
      try {
        var u = new SpeechSynthesisUtterance(' ');
        u.volume = 0; synth.speak(u); tts.synthPrimed = true;
      } catch (e) { /* the real speak reports its own failure */ }
    }
    if (ttsEngine() !== 'browser' && !tts.primed) {
      try {
        tts.el = tts.el || new Audio();
        tts.el.src = SILENT_WAV;
        var p = tts.el.play();
        if (p && p.then) p.then(function () { tts.primed = true; }, function () {});
      } catch (e) { /* */ }
    }
  }

  function plainForSpeech(t) {
    return String(t)
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/\[(\d{1,2})\]/g, '')          // citation brackets are noise to the ear
      .replace(/`([^`]*)`/g, '$1')
      .replace(/(\*\*|__)(.*?)\1/g, '$2').replace(/(\*|_)(.*?)\1/g, '$2')
      .replace(/^#+\s*/gm, '')
      .replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '. ').replace(/\.\s*\.\s*/g, '. ')
      // Removing "[1]" leaves " ." behind, and a voice reads that as an extra beat before the
      // full stop. Close the gap before any punctuation, not just the period.
      .replace(/\s+([.,;:!?])/g, '$1')
      .replace(/\s+/g, ' ').trim();
  }

  /* Sentence-sized chunks, the first one small, so a long answer starts speaking in about a second
   * instead of after the whole reply is synthesized. Chunks talked over are never synthesized, so
   * never billed. */
  function speechChunks(text, first, rest) {
    var f = first || 90, r = rest || 260;
    var sentences = String(text).trim().split(/(?<=[.!?])\s+/).filter(Boolean);
    var out = [], buf = '';
    sentences.forEach(function (sn) {
      var cap = out.length ? r : f;
      if (buf && (buf.length + 1 + sn.length) > cap) { out.push(buf); buf = ''; }
      buf = buf ? buf + ' ' + sn : sn;
    });
    if (buf) out.push(buf);
    return out.length ? out : [String(text).trim()];
  }

  function stopSpeaking() {
    tts.seq++;
    if (tts.abort) { try { tts.abort.abort(); } catch (e) {} tts.abort = null; }
    if (tts.audio) { try { tts.audio.pause(); } catch (e) {} }
    if (tts.url) { try { URL.revokeObjectURL(tts.url); } catch (e) {} tts.url = ''; }
    tts.audio = null;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    tts.utters = [];
    document.querySelectorAll('.kbp-listen.on').forEach(function (b) { b.classList.remove('on'); });
    setPhase('idle');
  }

  function speak(text, bubble, isSample) {
    var said = plainForSpeech(text);
    if (!said) { setPhase('idle'); return; }
    stopSpeaking();
    var mySeq = ++tts.seq;
    setPhase('speaking', 'speaking');
    var chunks = speechChunks(said);
    var engine = ttsEngine();

    function done() { if (mySeq === tts.seq) setPhase('idle'); }

    if (engine === 'browser') { speakBrowser(chunks, mySeq, done, bubble); return; }
    // Cloud voice, chunk by chunk, so the first words start quickly.
    var i = 0;
    function next() {
      if (mySeq !== tts.seq) return;
      if (i >= chunks.length) { done(); return; }
      var chunk = chunks[i++];
      tts.abort = new AbortController();
      fetch('/kb/speak', {
        method: 'POST', signal: tts.abort.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: chunk, engine: engine, voice: ttsVoice() })
      }).then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || ('voice failed (' + r.status + ')'));
        });
        return r.blob();
      }).then(function (blob) {
        if (mySeq !== tts.seq) return;
        tts.url = URL.createObjectURL(blob);
        var a = tts.el || new Audio();
        tts.el = a; tts.audio = a;
        a.src = tts.url;
        a.onended = function () { next(); };
        a.onerror = function () { next(); };
        var pr = a.play();
        if (pr && pr.catch) pr.catch(function () { next(); });
      }).catch(function (err) {
        if (mySeq !== tts.seq || err.name === 'AbortError') return;
        // 🔴 SAID OUT LOUD IN THE LOG, once. A cloud voice that fails silently is indistinguishable
        // from a broken feature; falling back to the browser voice and saying so is not.
        if (tts.failNoted !== engine) {
          tts.failNoted = engine;
          var n = el('div', 'kbp-sysnote', 'The cloud voice failed (' + err.message
            + '). Falling back to the browser voice.');
          log().appendChild(n); toBottom();
        }
        speakBrowser(chunks.slice(i - 1), mySeq, done, bubble);
      });
    }
    next();
  }

  function speakBrowser(chunks, mySeq, done, bubble) {
    var synth = window.speechSynthesis;
    if (!synth) {
      var n = el('div', 'kbp-sysnote', 'This browser cannot speak. Use the Listen button in Chrome, '
        + 'Edge or Safari.');
      log().appendChild(n); done(); return;
    }
    var i = 0;
    function next() {
      if (mySeq !== tts.seq) return;
      if (i >= chunks.length) { done(); return; }
      var u = new SpeechSynthesisUtterance(chunks[i++]);
      tts.utters.push(u);              // a collected utterance never fires its events
      u.onend = next;
      u.onerror = next;
      try { synth.speak(u); } catch (e) { done(); }
    }
    next();
  }

  function listenButton(text) {
    var b = el('button', 'kbp-listen');
    b.innerHTML = ICONS.sound + '<span>Listen</span>';
    b.onclick = function () {
      if (b.classList.contains('on')) { stopSpeaking(); return; }
      document.querySelectorAll('.kbp-listen.on').forEach(function (x) { x.classList.remove('on'); });
      b.classList.add('on');
      primeSpeechForce();
      speak(text, null);
    };
    return b;
  }
  function primeSpeechForce() {
    var was = A.settings && A.settings.speak_replies;
    if (A.settings) A.settings.speak_replies = true;
    primeSpeech();
    if (A.settings) A.settings.speak_replies = was;
  }

  // --- voice IN -------------------------------------------------------------------------------
  var rec = { on: false, r: null, base: '', target: null, btn: null };

  function dictateInto(target, btn) {
    if (rec.on) { stopRecording(); return; }
    if (!SR) { window.kbToast('This browser has no speech recognition. Use Chrome, Edge or Safari.', true); return; }
    var r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = 'en-AU';
    rec = { on: true, r: r, base: target.value, target: target, btn: btn };
    if (btn) btn.classList.add('on');
    setPhase('recording', 'listening - press the microphone again to stop');
    primeSpeechForce();
    r.onresult = function (e) {
      var said = '';
      for (var i = e.resultIndex; i < e.results.length; i++) said += e.results[i][0].transcript;
      // 🔴 IT LANDS IN THE BOX AND STAYS THERE. Nothing is sent by the microphone or by a pause:
      // dictation is reviewable text that you edit, add to, and then send yourself.
      var joined = (rec.base ? rec.base.replace(/\s*$/, '') + ' ' : '') + said.trim();
      target.value = joined;
      if (target.tagName === 'TEXTAREA') autosize(target);
    };
    r.onerror = function (e) {
      stopRecording();
      if (e && e.error === 'not-allowed') {
        window.kbToast('The microphone is blocked for this site. Allow it in the address bar.', true);
      }
    };
    r.onend = function () { if (rec.on) stopRecording(); };
    try { r.start(); } catch (e) { stopRecording(); }
  }

  function stopRecording() {
    if (rec.btn) rec.btn.classList.remove('on');
    if (rec.r) { try { rec.r.stop(); } catch (e) {} }
    rec = { on: false, r: null, base: '', target: null, btn: null };
    var bar = $('#kbConvo');
    if (bar && bar.classList.contains('is-recording')) setPhase('idle');
  }

  // --- history ---------------------------------------------------------------------------------
  function openHistory() {
    var d = $('#kbHistory'), body = $('#kbHistoryBody');
    d.hidden = false;
    body.innerHTML = '<p class="kbp-note">Loading…</p>';
    window.kbApi('/chats').then(function (j) {
      body.innerHTML = '';
      if (!j.chats.length) {
        body.appendChild(el('p', 'kbp-note', 'No past conversations yet.'));
        return;
      }
      if (j.shared) {
        body.appendChild(el('p', 'kbp-note', 'You are on a shared password, so these conversations '
          + 'are shared with everybody using it.'));
      }
      j.chats.forEach(function (c) {
        var row = el('div', 'kbp-hist-row');
        var open = el('button', 'kbp-hist-open');
        open.appendChild(el('span', 'kbp-hist-title', c.title));
        open.appendChild(el('span', 'kbp-hist-meta', new Date(c.updated_at * 1000).toLocaleString()
          + ' · ' + c.turns + ' messages'));
        open.onclick = function () { loadChat(c.id); d.hidden = true; };
        row.appendChild(open);
        var del = el('button', 'kbp-icon');
        del.innerHTML = ICONS.trash;
        del.title = 'Delete this conversation';
        del.onclick = function () {
          window.kbApi('/chats/' + c.id, { method: 'DELETE' }).then(function () { openHistory(); })
            .catch(function (e) { if (!e.auth) window.kbToast(e.message, true); });
        };
        row.appendChild(del);
        body.appendChild(row);
      });
    }).catch(function (e) {
      body.innerHTML = '';
      body.appendChild(el('p', 'kbp-note bad', e.message));
    });
  }

  function loadChat(id) {
    window.kbApi('/chats/' + id).then(function (j) {
      A.convId = j.chat.id;
      log().innerHTML = '';
      (j.chat.messages || []).forEach(function (m) {
        var turn = el('div', 'kbp-msg ' + (m.role === 'assistant' ? 'ai' : 'me'));
        var bubble = el('div', 'kbp-bubble');
        if (m.role === 'assistant') {
          var meta = el('div', 'kbp-meta');
          if (m.model) meta.appendChild(el('span', 'kbp-badge model', m.model));
          if (m.proposed_edit) meta.appendChild(el('span', 'kbp-badge', 'proposed an edit'));
          bubble.appendChild(meta);
          var a = el('div', 'ans');
          if ((m.content || '').trim()) {
            a.innerHTML = mdToHtml(m.content, null, el('div'));
            bubble.appendChild(a);
            bubble.appendChild(listenButton(m.content));
          } else {
            // Its text was only a proposal block, which is stripped before storing. Say what it
            // was rather than replaying an empty bubble; the card itself is not re-offered,
            // because a proposal is a moment in a conversation, not a standing offer.
            bubble.appendChild(el('div', 'kbp-note', m.proposed_edit
              ? 'Proposed an edit here. Open the document to see whether it was approved.'
              : 'This reply was empty.'));
          }
        } else {
          bubble.textContent = m.content || '';
        }
        turn.appendChild(bubble);
        log().appendChild(turn);
      });
      toBottom();
    }).catch(function (e) { if (!e.auth) window.kbToast(e.message, true); });
  }

  function autosize(t) { t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 160) + 'px'; }

  // --- boot ---------------------------------------------------------------------------------------
  function boot() {
    if (!panel()) return;
    $('#kbFab').onclick = function () { openPanel(); };
    $('#kbClose').onclick = closePanel;
    $('#kbNewChat').onclick = function () {
      A.convId = ''; log().innerHTML = ''; greet(); $('#kbInput').focus();
    };
    $('#kbHistoryBtn').onclick = openHistory;
    $('#kbHistoryClose').onclick = function () { $('#kbHistory').hidden = true; };
    $('#kbSettingsBtn').onclick = function () { $('#kbSettings').hidden = false; paintSettings(); };
    $('#kbSettingsClose').onclick = function () { $('#kbSettings').hidden = true; };
    $('#kbScopeBtn').onclick = function (e) { e.stopPropagation(); toggleScope(); };
    $('#kbSend').onclick = send;
    $('#kbMic').onclick = function () { dictateInto($('#kbInput'), $('#kbMic')); };
    $('#kbConvoStop').onclick = function () { stopSpeaking(); stopRecording(); if (A.ctrl) A.ctrl.abort(); };
    $('#kbSpeak').onclick = function () { saveSettings({ speak_replies: !speakOn() }); };

    document.addEventListener('click', function (e) {
      var m = $('#kbScope');
      if (m && !m.hidden && !e.target.closest('#kbScope') && !e.target.closest('#kbScopeBtn')) m.hidden = true;
    });

    var input = $('#kbInput');
    input.addEventListener('input', function () { autosize(this); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && A.open && $('#kbScope').hidden && $('#kbSettings').hidden
          && $('#kbHistory').hidden && !$('.kb-ovl')) closePanel();
    });
    if (!SR) $('#kbMic').hidden = true;

    wireDrag();
    loadClients();
    loadSettings();
    // 🔴 `panelOpen`, NOT `open`. kb.js keeps the Explorer's expanded tree nodes under
    // `bb.kb.open` as an OBJECT; writing '1' there turned it into a number and every
    // click on a tree twisty then threw "Cannot create property on number".
    if (localStorage.getItem(LS + 'panelOpen') === '1' || location.hash === '#ask') openPanel();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.kbAsk = { open: openPanel, close: closePanel };
})();
