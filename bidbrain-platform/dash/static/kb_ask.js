/* kb_ask.js - the Ask panel: knowledge base picker, streamed answer, citations, feedback loop.
 *
 * 🔴 THE CITATIONS ARRIVE BEFORE THE ANSWER DOES. The `retrieval` event is sent before the model
 * is even called, so the reader watches the answer being written against sources already on
 * screen. Appending references afterwards produces the same pixels and a different claim: it looks
 * like the model chose them to justify what it had already said.
 *
 * 🔴 THE PANEL SAYS WHICH MODEL ANSWERED, INCLUDING WHEN IT FELL BACK. A silent fallback means
 * nobody ever learns the first choice is broken.
 *
 * 🔴 "SEARCHED BY WORDING ONLY" IS SHOWN, NOT SWALLOWED. A degraded search that looks identical to
 * a healthy one turns a gap into "there is nothing about that", which is a different and false
 * statement.
 *
 * 🔴 NOTHING TYPED IS EVER THROWN AWAY. The composer keeps its text until the answer starts; a
 * correction box keeps its text if the save fails; and the session can expire at any moment,
 * because it is a hard 12 hour cap rather than a sliding window.
 */
(function () {
  'use strict';

  var LS = 'bb.kb.';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function el(t, c, x) { var n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; }

  var A = {
    open: false, convId: '', busy: false, ctrl: null,
    scope: [],                 // [] = entire knowledge base
    lastRetrieval: null
  };
  try { A.scope = JSON.parse(localStorage.getItem(LS + 'scope') || '[]'); } catch (e) { A.scope = []; }

  function panel() { return $('#kbAskPanel'); }
  function thread() { return $('#kbThread'); }

  function openPanel(prefill, folder) {
    A.open = true;
    panel().hidden = false;
    $('#kbShell').classList.add('with-panel');
    if (folder) { A.scope = [folder]; saveScope(); }
    renderScopeButton();
    if (!thread().childElementCount) greet();
    var i = $('#kbInput');
    if (prefill) i.value = prefill;
    i.focus();
  }
  function closePanel() {
    A.open = false;
    panel().hidden = true;
    $('#kbShell').classList.remove('with-panel');
  }

  function greet() {
    var d = el('div', 'kb-turn ai');
    var p = el('div', 'ans');
    p.textContent = 'Ask about anything written down in the library: a plan, a brief, a decision, '
      + 'a rule. Every answer cites the passages it came from, and if one is wrong you can correct '
      + 'it here and the next person gets your correction.';
    d.appendChild(p);
    var note = el('div', 'kb-hint');
    note.textContent = 'This reads the WORDS, not the live campaign numbers. Delivery figures live '
      + 'on each client dashboard.';
    d.appendChild(note);
    thread().appendChild(d);
  }

  // --- the knowledge base picker ----------------------------------------------------------------
  function saveScope() { localStorage.setItem(LS + 'scope', JSON.stringify(A.scope)); }

  function renderScopeButton() {
    var b = $('#kbScopeBtn');
    if (!A.scope.length) { b.textContent = 'Entire knowledge base'; return; }
    if (A.scope.length === 1) { b.textContent = A.scope[0] === '/' ? 'No folder' : A.scope[0]; return; }
    b.textContent = A.scope.length + ' folders';
  }

  function toggleScopeMenu() {
    var m = $('#kbScopeMenu');
    if (!m.hidden) { m.hidden = true; return; }
    var S = window.kbState || { folders: [], rootCount: 0, total: 0 };
    m.innerHTML = '';
    m.appendChild(scopeRow({ path: '', name: 'Entire knowledge base', count: S.total, depth: 0 }, true));
    (S.folders || []).forEach(function (f) { m.appendChild(scopeRow(f, false)); });
    if (S.rootCount) {
      m.appendChild(scopeRow({ path: '/', name: 'Documents in no folder', count: S.rootCount, depth: 0 }, false));
    }
    var hint = el('div', 'kb-hint');
    hint.style.padding = '6px 8px 2px';
    hint.textContent = 'Ticking a folder includes everything inside it. When the scope is narrowed '
      + 'the answer says so instead of claiming the library is empty.';
    m.appendChild(hint);
    m.hidden = false;
  }

  function scopeRow(f, isAll) {
    var row = el('label', 'kb-scope-row');
    row.style.paddingLeft = (7 + (f.depth || 0) * 12) + 'px';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = isAll ? !A.scope.length : A.scope.indexOf(f.path) >= 0;
    cb.onchange = function () {
      if (isAll) { A.scope = []; }
      else {
        var i = A.scope.indexOf(f.path);
        if (i >= 0) A.scope.splice(i, 1); else A.scope.push(f.path);
      }
      saveScope(); renderScopeButton();
      $('#kbScopeMenu').hidden = true;
    };
    row.appendChild(cb);
    row.appendChild(el('span', null, f.name));
    row.appendChild(el('span', 'ct', f.count ? String(f.count) : ''));
    return row;
  }

  // --- asking ------------------------------------------------------------------------------------
  function send() {
    if (A.busy) return;
    var input = $('#kbInput');
    var q = input.value.trim();
    if (!q) return;

    var mine = el('div', 'kb-turn me', q);
    thread().appendChild(mine);
    // Cleared only now the question is on screen, and restored if the request never starts.
    input.value = '';
    autosize(input);

    var turn = el('div', 'kb-turn ai');
    var byline = el('div', 'kb-byline');
    byline.innerHTML = '<span class="kb-dots">searching the library</span>';
    turn.appendChild(byline);
    var cites = el('div', 'kb-cites');
    turn.appendChild(cites);
    var ans = el('div', 'ans');
    turn.appendChild(ans);
    thread().appendChild(turn);
    thread().scrollTop = thread().scrollHeight;

    A.busy = true;
    $('#kbSend').disabled = true;
    $('#kbStop').hidden = false;
    var ctrl = new AbortController();
    A.ctrl = ctrl;

    var state = { retrieval: null, model: null, text: '', answerId: '', convId: A.convId };

    fetch('/kb/ask', {
      method: 'POST', signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: q, folders: A.scope, conv_id: A.convId })
    }).then(function (r) {
      if (r.status === 401) {
        // 🔴 Retrying is the one thing that can never fix this, so the message never says to.
        input.value = q;
        throw Object.assign(new Error('auth'), { auth: true });
      }
      if (!r.ok || !r.body) throw new Error('The assistant could not be reached (' + r.status + ')');
      return readStream(r.body.getReader(), function (ev, data) {
        if (ev === 'retrieval') {
          state.retrieval = data;
          A.lastRetrieval = data;
          renderCites(cites, data);
          byline.innerHTML = '<span class="kb-dots">writing</span>';
        } else if (ev === 'model') {
          state.model = data;
          byline.innerHTML = '';
          byline.appendChild(modelBadge(data));
          if (state.retrieval && !state.retrieval.semantic) byline.appendChild(kwBadge(state.retrieval));
        } else if (ev === 'token') {
          state.text += data.t;
          // Stripped AS IT STREAMS. Rendering state.text raw would type the proposal's JSON
          // across the answer and then delete it, which reads as the thing glitching.
          ans.textContent = splitProposal(state.text).prose;
          thread().scrollTop = thread().scrollHeight;
        } else if (ev === 'done') {
          state.answerId = data.answer_id;
          A.convId = data.conv_id;
          byline.appendChild(el('span', null, Math.round(data.ms / 100) / 10 + 's'));
        } else if (ev === 'error') {
          var e = el('div', 'kb-hint');
          e.style.color = 'var(--danger)';
          e.textContent = data.message;
          turn.appendChild(e);
          if (!data.retrieval_ok) byline.innerHTML = '';
        }
      });
    }).then(function () {
      var split = splitProposal(state.text);
      state.text = split.prose;              // the feedback record keeps the PROSE, not the block
      if (split.prose.trim()) {
        ans.innerHTML = mdToHtml(split.prose, state.retrieval, cites);
        var prop = parseProposal(split.raw, state.retrieval);
        if (prop) turn.appendChild(proposalCard(prop, turn));
        turn.appendChild(verdictBar(q, state));
      }
    }).catch(function (err) {
      if (err.name === 'AbortError') {
        byline.innerHTML = '';
        byline.appendChild(el('span', null, 'stopped'));
        // A half-arrived proposal is never offered: the fence may not even have closed.
        state.text = splitProposal(state.text).prose;
        if (state.text.trim()) turn.appendChild(verdictBar(q, state));
        return;
      }
      byline.innerHTML = '';
      var e = el('div', 'kb-hint');
      e.style.color = 'var(--danger)';
      if (err.auth) {
        e.innerHTML = 'Your session has expired. <a href="/">Sign in again</a>. Your question is '
          + 'back in the box.';
      } else {
        e.textContent = err.message;
      }
      turn.appendChild(e);
    }).then(function () {
      A.busy = false;
      A.ctrl = null;
      $('#kbSend').disabled = false;
      $('#kbStop').hidden = true;
      thread().scrollTop = thread().scrollHeight;
    });
  }

  /* Server-sent events over fetch. `EventSource` cannot POST, and the question plus the scope have
   * no business in a URL. */
  function readStream(reader, onEvent) {
    var dec = new TextDecoder();
    var buf = '';
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
        try { onEvent(ev, JSON.parse(data)); } catch (e) { /* a partial frame; the next flush has it */ }
      });
    }
    return pump();
  }

  /* --- proposed edits -------------------------------------------------------------------------
   *
   * The model ends an answer with a ```bb-edit block when a conversation settles something the
   * library has wrong or missing. NOTHING happens until a person approves it.
   *
   * 🔴 THE BLOCK IS STRIPPED WHILE IT STREAMS, not at the end. Otherwise raw JSON visibly types
   * itself across the answer for a second and then disappears, which reads as the thing glitching.
   * `splitProposal` truncates at the opening fence even when the block is half-arrived.
   *
   * 🔴 THE MODEL NAMES A PASSAGE NUMBER, NEVER A DOCUMENT. The number is resolved against THIS
   * turn's retrieval, here, so an invented or out-of-range number resolves to nothing and the card
   * is not offered. A model that could name a document id could name one it was never shown.
   */
  var FENCE = '```bb-edit';

  function splitProposal(text) {
    var i = text.indexOf(FENCE);
    if (i < 0) return { prose: text, raw: null };
    var rest = text.slice(i + FENCE.length);
    var end = rest.indexOf('```');
    return { prose: text.slice(0, i).trimEnd(),
             raw: end < 0 ? null : rest.slice(0, end).trim() };
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
      var ex = (retrieval && retrieval.excerpts) || [];
      var n = parseInt(p.passage, 10);
      // Out of range, missing, or from a turn that retrieved nothing: no card, no silent guess.
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

  function proposalCard(p, turn) {
    var card = el('div', 'kb-propose');
    var head = el('div', 'kb-propose-h');
    head.appendChild(el('span', 'kb-badge model', 'PROPOSED EDIT'));
    head.appendChild(el('span', null, p.summary));
    card.appendChild(head);

    var where = el('div', 'kb-propose-where');
    if (p.action === 'append') {
      where.textContent = 'Adds a dated section to the end of "' + p.target.title + '" in '
        + (p.target.folder || 'no folder') + '. Nothing already in that document changes.';
    } else {
      where.textContent = 'Creates a new document "' + p.title + '" in '
        + (p.folder || 'no folder') + '.';
    }
    card.appendChild(where);

    if (p.action === 'append') {
      var h = el('div', 'kb-propose-head', '## ' + p.heading);
      card.appendChild(h);
    }
    var body = el('div', 'kb-propose-body', p.text);
    card.appendChild(body);

    var row = el('div', 'kb-verdict');
    var ok = el('button', 'btn sm gold', p.action === 'create' ? 'Create it' : 'Add it');
    var no = el('button', 'btn sm', 'Discard');
    row.appendChild(ok);
    row.appendChild(no);
    var note = el('span', 'kb-hint');
    note.style.margin = '0';
    note.textContent = 'Nothing has changed yet. Every version is kept, so this can be undone.';
    row.appendChild(note);
    card.appendChild(row);

    no.onclick = function () {
      card.innerHTML = '';
      card.appendChild(el('span', 'kb-hint', 'Discarded. Nothing was written.'));
    };
    ok.onclick = function () {
      ok.disabled = true; no.disabled = true;
      ok.textContent = 'Saving…';
      var req = p.action === 'append'
        ? window.kbApi('/docs/' + p.target.document_id + '/append', { method: 'POST', body: {
            heading: p.heading, text: p.text, note: p.summary, via: 'assistant' } })
        : window.kbApi('/docs', { method: 'POST', body: {
            title: p.title, folder: p.folder, body: p.text, kind: 'note' } });
      req.then(function (j) {
        var d = j.doc;
        card.innerHTML = '';
        var done = el('div', 'kb-propose-h');
        done.appendChild(el('span', 'kb-badge verified', 'WRITTEN'));
        done.appendChild(el('span', null, p.action === 'create'
          ? 'Created "' + d.title + '".'
          : 'Added to "' + d.title + '". The previous version is kept in its history.'));
        card.appendChild(done);
        var open = el('button', 'btn sm', 'Open it');
        open.onclick = function () { if (window.kbOpenDoc) window.kbOpenDoc(d.id); };
        card.appendChild(open);
        if (window.kbRefresh) window.kbRefresh();
      }).catch(function (err) {
        ok.disabled = false; no.disabled = false;
        ok.textContent = p.action === 'create' ? 'Create it' : 'Add it';
        if (!err.auth) window.kbToast(err.message, true);
      });
    };
    return card;
  }

  function modelBadge(m) {
    var b = el('span', 'kb-badge model', m.label + (m.fallback ? ' (fallback)' : ''));
    b.title = m.model + (m.fallback
      ? ' - the first choice could not answer, so this one did. The Observability page says why.'
      : '');
    return b;
  }
  function kwBadge(r) {
    var b = el('span', 'kb-badge kw', 'searched by wording only');
    b.title = r.semantic_error || 'meaning search was unavailable';
    return b;
  }

  function renderCites(host, r) {
    host.innerHTML = '';
    if (!r.excerpts.length) {
      var n = el('div', 'kb-hint');
      n.textContent = r.documents_searched
        ? 'Nothing in ' + (r.scope.length ? 'that scope' : 'the library') + ' matched this question.'
        : 'The scope you picked contains no documents.';
      host.appendChild(n);
      return;
    }
    r.excerpts.forEach(function (e, i) {
      var c = el('div', 'kb-cite');
      c.appendChild(el('span', 'n', '[' + (i + 1) + ']'));
      var t = el('span', 't', e.title);
      c.appendChild(t);
      if (e.trust === 'verified') c.appendChild(el('span', 'kb-badge verified', 'CORRECTION'));
      c.appendChild(el('span', 'f', (e.folder || 'no folder')));
      c.appendChild(foundBadge(e.found_by));
      c.title = e.passage.slice(0, 400);
      // Clicking a citation opens that document AT that passage. That is the difference between a
      // reference and a source you can check.
      c.onclick = function () { if (window.kbOpenDoc) window.kbOpenDoc(e.document_id, e.ord); };
      host.appendChild(c);
    });
    if (!r.semantic) {
      var w = el('div', 'kb-hint');
      w.style.color = 'var(--warn)';
      w.textContent = 'Meaning search was unavailable, so these were found by wording only ('
        + (r.semantic_error || 'reason not recorded') + '). Something relevant but differently '
        + 'worded could have been missed.';
      host.appendChild(w);
    } else if (r.unembedded_documents) {
      var u = el('div', 'kb-hint');
      u.textContent = r.unembedded_documents + ' document(s) in scope are still being indexed, so '
        + 'they could only be matched by wording.';
      host.appendChild(u);
    }
  }

  function foundBadge(found) {
    var both = found.length > 1;
    var label = both ? 'both' : (found[0] || '');
    var b = el('span', 'kb-found ' + (both ? 'both' : label), both ? 'both' : label);
    b.title = both ? 'wording AND meaning search found this'
      : label === 'semantic' ? 'found by meaning, not by shared words'
        : 'found by shared words';
    return b;
  }

  /* Minimal markdown: bold, inline code, bullets, and [n] turned into a link to the citation. Not
   * a parser - a full one would be a dependency, and the prompt asks for plain prose. */
  function mdToHtml(text, retrieval, citesHost) {
    var html = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^\s*[-*]\s+(.*)$/gm, '• $1')
      .replace(/\[(\d{1,2})\]/g, function (m, n) {
        var i = +n - 1;
        if (!retrieval || !retrieval.excerpts[i]) return m;
        return '<a href="#" data-cite="' + i + '" style="color:var(--gold);text-decoration:none;'
          + 'font-weight:700">[' + n + ']</a>';
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

  // --- the feedback loop --------------------------------------------------------------------------
  function verdictBar(question, state) {
    var wrap = el('div');
    var bar = el('div', 'kb-verdict');
    var box = el('div', 'kb-correct');

    ['right', 'elsewhere', 'wrong'].forEach(function (v) {
      var label = { right: 'Right', elsewhere: 'Right, not here', wrong: 'Wrong' }[v];
      var b = el('button', 'btn sm' + (v === 'wrong' ? ' danger' : ''), label);
      b.title = {
        right: 'The answer is correct and so are its sources.',
        elsewhere: 'The answer is right, but it did not come from the right place. That is a '
          + 'retrieval problem, so it does not create a correction unless you add one.',
        wrong: 'The answer is wrong. Write the rule and the next person gets your version.'
      }[v];
      b.onclick = function () { openCorrection(v); };
      bar.appendChild(b);
    });
    wrap.appendChild(bar);
    wrap.appendChild(box);

    function openCorrection(verdict) {
      box.classList.add('on');
      box.innerHTML = '';
      var lead = el('div', 'kb-hint');
      lead.textContent = verdict === 'right'
        ? 'Anything to add? Optional. Anything you write here becomes a trusted note other buyers '
          + 'will see.'
        : verdict === 'elsewhere'
          ? 'What SHOULD it have cited, or what does the library not say yet? Leave it blank to '
            + 'record only that the sources were wrong.'
          : 'Write the rule in one line, as you would tell a colleague. It becomes a trusted note '
            + 'and the next person asking this gets it first.';
      box.appendChild(lead);

      var rule = document.createElement('input');
      rule.className = 'kb-input';
      rule.placeholder = 'The rule, in one line. For example: the margin floor is fifty per cent from Q3.';
      box.appendChild(rule);

      var more = document.createElement('textarea');
      more.className = 'kb-input';
      more.placeholder = 'Any detail worth keeping (optional).';
      more.style.marginTop = '7px';
      box.appendChild(more);

      // Which cited passages were wrong. Pre-ticking the top one is a default, not a claim: it is
      // the passage an answer most likely leaned on, and it can be unticked.
      var ticks = [];
      var ex = (state.retrieval && state.retrieval.excerpts) || [];
      if (verdict !== 'right' && ex.length) {
        var h = el('div', 'kb-hint');
        h.style.marginTop = '9px';
        h.textContent = 'Which of these was wrong? A ticked passage is pushed below your '
          + 'correction next time. The document itself is never edited.';
        box.appendChild(h);
        ex.forEach(function (e, i) {
          // Its own class, not the scope picker's: they look alike and mean completely different
          // things, and a shared selector is how a later change moves the wrong checkboxes.
          var row = el('label', 'kb-scope-row kb-tick');
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

      var row = el('div', 'kb-verdict');
      var save = el('button', 'btn sm gold', verdict === 'right' ? 'Send' : 'Save the correction');
      var cancel = el('button', 'btn sm', 'Cancel');
      cancel.onclick = function () { box.classList.remove('on'); box.innerHTML = ''; };
      row.appendChild(save);
      row.appendChild(cancel);
      box.appendChild(row);
      rule.focus();

      save.onclick = function () {
        save.disabled = true;
        save.textContent = 'Saving…';
        window.kbApi('/feedback', { method: 'POST', body: {
          question: question, answer: state.text, verdict: verdict,
          rule: rule.value, correction: more.value,
          cited: ex.map(function (e) {
            return { passage_id: e.passage_id, document_id: e.document_id, title: e.title,
                     folder: e.folder, trust: e.trust };
          }),
          superseded: ticks.filter(function (c) { return c.checked; })
            .map(function (c) { return c.value; }),
          model: (state.model || {}).model || '', conv_id: A.convId,
          answer_id: state.answerId,
          scope: (state.retrieval || {}).scope || [],
          semantic: !!(state.retrieval || {}).semantic
        } }).then(function (j) {
          box.classList.remove('on');
          box.innerHTML = '';
          bar.innerHTML = '';
          var done = el('span', 'done');
          if (j.feedback.doc_id) {
            done.textContent = 'Saved as a trusted note. The next person asking this gets it first.';
            var open = el('button', 'btn sm', 'Open it');
            open.style.marginLeft = '8px';
            open.onclick = function () { if (window.kbOpenDoc) window.kbOpenDoc(j.feedback.doc_id); };
            bar.appendChild(done);
            bar.appendChild(open);
          } else {
            done.textContent = 'Recorded. Thank you.';
            bar.appendChild(done);
          }
          var undo = el('button', 'btn sm', 'Withdraw');
          undo.style.marginLeft = '8px';
          undo.onclick = function () {
            window.kbApi('/feedback/' + j.feedback.id + '/withdraw', { method: 'POST' })
              .then(function () {
                bar.innerHTML = '';
                bar.appendChild(el('span', 'done', 'Withdrawn. Any note it made is archived.'));
                if (window.kbRefresh) window.kbRefresh();
              })
              .catch(function (e) { if (!e.auth) window.kbToast(e.message, true); });
          };
          bar.appendChild(undo);
          if (window.kbRefresh) window.kbRefresh();
        }).catch(function (err) {
          // 🔴 The typed words stay in the box. A save that loses what somebody wrote is how
          // people stop writing corrections.
          save.disabled = false;
          save.textContent = verdict === 'right' ? 'Send' : 'Save the correction';
          if (!err.auth) window.kbToast(err.message, true);
        });
      };
    }
    return wrap;
  }

  // --- composer ------------------------------------------------------------------------------------
  function autosize(t) {
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 180) + 'px';
  }

  function boot() {
    if (!panel()) return;
    $('#kbSend').onclick = send;
    $('#kbStop').onclick = function () { if (A.ctrl) A.ctrl.abort(); };
    $('#kbAskClose').onclick = closePanel;
    $('#kbNewChat').onclick = function () {
      A.convId = '';
      thread().innerHTML = '';
      greet();
      $('#kbInput').focus();
    };
    $('#kbScopeBtn').onclick = function (e) { e.stopPropagation(); toggleScopeMenu(); };
    document.addEventListener('click', function (e) {
      var m = $('#kbScopeMenu');
      if (m && !m.hidden && !$('#kbScope').contains(e.target)) m.hidden = true;
    });
    var input = $('#kbInput');
    input.addEventListener('input', function () { autosize(this); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    if (window.KB_SHARED_LOGIN) {
      $('#kbAskNote').textContent = 'shared login: conversations here are shared with everyone '
        + 'using this password';
    }
    renderScopeButton();
    if (location.hash === '#ask') openPanel();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.kbAsk = { open: openPanel, close: closePanel };
})();
