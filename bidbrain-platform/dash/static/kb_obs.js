/* kb_obs.js - the Observability page.
 *
 * 🔴 EVERY CLAIM ON THIS PAGE MAPS TO A NAMED CODE PATH, and nothing is illustrative. The settings
 * panel prints the constants the retriever is running with, read from the server rather than typed
 * here, so this page cannot describe a system that is not the one deployed. The probe box calls the
 * SAME `kb_index.search` the assistant calls.
 *
 * 🔴 A RATE IS PRINTED WITH ITS DENOMINATOR. "40% of answers had no meaning search" over five
 * questions is a number two people will read completely differently, so the count is always beside
 * the percentage.
 */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function el(t, c, x) { var n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; }
  var D = null;

  function api(path, opts) {
    opts = opts || {};
    if (opts.body) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(opts.body);
    }
    return fetch('/kb' + path, opts).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'Server error ' + r.status }; })
        .then(function (j) {
          if (r.status === 401) throw Object.assign(new Error('Your session has expired. Sign in again.'), { auth: true });
          if (!r.ok || j.ok === false) throw new Error(j.error || 'Server error ' + r.status);
          return j;
        });
    });
  }

  function kpi(value, label, sub, dot) {
    var k = el('div', 'kb-kpi');
    var v = el('div', 'v');
    if (dot) { var d = el('span', 'kb-dot ' + dot); v.appendChild(d); }
    v.appendChild(document.createTextNode(value));
    k.appendChild(v);
    k.appendChild(el('div', 'l', label));
    if (sub) k.appendChild(el('div', 's', sub));
    return k;
  }

  function pct(n, d) {
    if (!d) return '-';
    return Math.round(n / d * 100) + '% (' + n + ' of ' + d + ')';
  }

  // --- reachability --------------------------------------------------------------------------
  function renderReach(probes) {
    var host = $('#obsReach');
    host.innerHTML = '';
    var cfg = D || {};
    var rows = [
      ['vertex', 'Vertex embeddings',
        (cfg.embeddings || {}).model + ' in ' + (cfg.embeddings || {}).region,
        (cfg.embeddings || {}).enabled],
      ['kimi', 'Kimi', ((cfg.models || {}).kimi || {}).model + ' at ' + ((cfg.models || {}).kimi || {}).base,
        ((cfg.models || {}).kimi || {}).configured],
      ['gemini', 'Gemini (fallback)', ((cfg.models || {}).gemini || {}).model,
        ((cfg.models || {}).gemini || {}).configured]
    ];
    rows.forEach(function (r) {
      var p = (probes || {})[r[0]];
      var dot = !r[3] ? 'off' : p ? (p.ok ? 'ok' : 'bad') : 'warn';
      var val = !r[3] ? 'not configured'
        : p ? (p.ok ? 'reachable' : 'FAILED') : 'not checked';
      var sub = r[2];
      if (p && p.ok && p.ms) sub += ' · ' + p.ms + ' ms';
      if (p && !p.ok) sub = (p.detail || '') + (p.body ? ' · ' + p.body : '');
      var card = kpi(val, r[1], sub, dot);
      card.querySelector('.v').style.fontSize = '15px';
      host.appendChild(card);
    });
    if (!(D.embeddings || {}).enabled) {
      var n = el('div', 'kb-hint');
      n.style.marginTop = '10px';
      n.textContent = 'Meaning search is switched off, so every answer is found by wording only '
        + 'and every one of them says so on screen. Nothing is broken; it is declared.';
      host.parentNode.insertBefore(n, host.nextSibling);
    }
  }

  // --- library ---------------------------------------------------------------------------------
  function renderLibrary() {
    var L = D.library, I = D.index;
    var host = $('#obsLibrary');
    host.innerHTML = '';
    host.appendChild(kpi(L.documents, 'documents indexed'));
    host.appendChild(kpi(L.chunks, 'passages'));
    host.appendChild(kpi(pct(L.embedded, L.chunks), 'with meaning search',
      L.chunks === L.embedded ? 'every passage has a vector' : 'the rest are wording only'));
    host.appendChild(kpi(L.verified, 'verified corrections',
      'from the feedback loop, ranked above raw source material'));
    host.appendChild(kpi((I.build_ms || 0) + ' ms', 'last index rebuild',
      'fetched ' + (I.fetched || 0) + ' changed document(s); the signature check took '
      + (I.sig_ms || 0) + ' ms'));
    host.appendChild(kpi(D.guide_loaded ? 'loaded' : 'MISSING', 'self-knowledge document',
      D.guide_loaded ? 'shipped inside the prompt on every turn'
        : 'dash/kb/HOW-BIDBRAIN-KB-WORKS.md did not load, so the assistant is answering without '
        + 'its own documentation', D.guide_loaded ? 'ok' : 'bad'));

    var p = $('#obsPending');
    p.innerHTML = '';
    if (L.pending && L.pending.length) {
      var h = el('div', 'kb-hint');
      h.style.marginTop = '12px';
      h.textContent = 'Still building meaning search for: '
        + L.pending.map(function (d) { return d.title; }).join(', ');
      p.appendChild(h);
    }
  }

  // --- the probe box -------------------------------------------------------------------------
  function runProbe() {
    var q = $('#obsQ').value.trim();
    if (!q) return;
    var host = $('#obsResult');
    host.innerHTML = '<p class="kb-hint">searching…</p>';
    api('/obs/probe', { method: 'POST', body: { q: q } }).then(function (j) {
      var r = j.result;
      host.innerHTML = '';
      var head = el('p', 'kb-hint');
      head.innerHTML = '<b>' + r.outcome + '</b> · ' + r.documents_searched + ' document(s) in '
        + 'scope · ' + r.ms + ' ms total (' + r.index_ms + ' ms index, ' + r.embed_ms
        + ' ms embedding the question)'
        + (r.semantic ? '' : ' · <b style="color:var(--warn)">wording only: ' + r.semantic_error + '</b>');
      host.appendChild(head);
      if (!r.excerpts.length) return;

      var without = {};
      (j.without_trust || []).forEach(function (e, i) { without[e.passage_id] = i + 1; });

      var t = el('table', 'kb-tbl');
      t.innerHTML = '<thead><tr><th>#</th><th>Found by</th><th>Document</th>'
        + '<th class="n">kw rank</th><th class="n">sem rank</th><th class="n">cosine</th>'
        + '<th class="n">fused</th><th class="n">without trust</th><th>Passage</th></tr></thead>';
      var tb = el('tbody');
      r.excerpts.forEach(function (e, i) {
        var tr = el('tr');
        tr.appendChild(el('td', 'n', String(i + 1)));
        var f = el('td');
        var both = e.found_by.length > 1;
        f.appendChild(el('span', 'kb-found ' + (both ? 'both' : e.found_by[0]),
          both ? 'both' : e.found_by[0]));
        tr.appendChild(f);
        var dc = el('td');
        dc.appendChild(el('span', null, e.title));
        if (e.trust === 'verified') dc.appendChild(el('span', 'kb-trust', 'VERIFIED'));
        dc.appendChild(el('div', null, (e.folder || 'no folder') + ' · passage ' + (e.ord + 1)))
          .style.color = 'var(--muted-2)';
        tr.appendChild(dc);
        tr.appendChild(el('td', 'n', e.keyword_rank == null ? '-' : e.keyword_rank));
        tr.appendChild(el('td', 'n', e.semantic_rank == null ? '-' : e.semantic_rank));
        tr.appendChild(el('td', 'n', e.semantic_score == null ? '-' : e.semantic_score));
        tr.appendChild(el('td', 'n', e.score));
        var w = without[e.passage_id];
        var wc = el('td', 'n', w ? ('#' + w) : 'dropped');
        // 🔴 The only honest way to show what trust did: the SAME query re-run with the nudge and
        // the supersede penalty off. A label claiming "promoted" would be an assertion.
        if (w && w !== i + 1) wc.style.color = w > i + 1 ? 'var(--active)' : 'var(--warn)';
        tr.appendChild(wc);
        var p = el('td', null, e.passage.slice(0, 160) + (e.passage.length > 160 ? '…' : ''));
        p.style.whiteSpace = 'normal';
        p.style.maxWidth = '340px';
        tr.appendChild(p);
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      var wrap = el('div');
      wrap.style.overflowX = 'auto';
      wrap.appendChild(t);
      host.appendChild(wrap);

      var note = el('p', 'kb-hint');
      note.textContent = '"without trust" is this same query re-ranked with the verified nudge and '
        + 'the supersede penalty switched off. A row that moved up is what the feedback loop '
        + 'actually did to this question.';
      host.appendChild(note);
    }).catch(function (e) {
      host.innerHTML = '';
      var p = el('p', 'kb-hint', e.message);
      p.style.color = 'var(--danger)';
      host.appendChild(p);
    });
  }

  // --- questions ---------------------------------------------------------------------------------
  function renderQuestions() {
    var host = $('#obsQuestions');
    host.innerHTML = '';
    if (!D.questions.length) {
      host.appendChild(el('p', 'kb-hint', 'Nothing has been asked yet.'));
      return;
    }
    var t = el('table', 'kb-tbl');
    t.innerHTML = '<thead><tr><th>When</th><th>Question</th><th>Scope</th><th class="n">Passages</th>'
      + '<th>Search</th><th>Model</th><th class="n">ms</th><th>Documents it used</th></tr></thead>';
    var tb = el('tbody');
    D.questions.forEach(function (e) {
      var tr = el('tr');
      tr.appendChild(el('td', null, new Date((e.at || 0) * 1000).toLocaleString()));
      var q = el('td', null, e.query || '');
      q.style.whiteSpace = 'normal'; q.style.maxWidth = '260px';
      tr.appendChild(q);
      tr.appendChild(el('td', null, (e.scope && e.scope.length) ? e.scope.join(', ') : 'everything'));
      tr.appendChild(el('td', 'n', e.passages == null ? '-' : e.passages));
      var s = el('td');
      s.appendChild(el('span', 'kb-found ' + (e.semantic ? 'both' : 'keyword'),
        e.semantic ? 'hybrid' : 'wording only'));
      tr.appendChild(s);
      tr.appendChild(el('td', null, (e.model || '-') + (e.fallback ? ' (fallback)' : '')));
      tr.appendChild(el('td', 'n', e.ms == null ? '-' : e.ms));
      var docs = el('td', null, (e.docs || []).map(function (id) {
        return (D.titles[id] || {}).title || id;
      }).join(', ') || '-');
      docs.style.whiteSpace = 'normal'; docs.style.maxWidth = '300px';
      tr.appendChild(docs);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    var wrap = el('div'); wrap.style.overflowX = 'auto'; wrap.appendChild(t);
    host.appendChild(wrap);
  }

  // --- meetings -------------------------------------------------------------------------------
  // Its own panel, hidden until a meeting has actually been decided: a row of zeros reads as a
  // feature that is failing rather than one nobody has used yet.
  function renderMeetings() {
    var M = D.meetings, panel = $('#obsMeetingsPanel'), host = $('#obsMeetings');
    if (!panel || !host) return;
    if (!M || !M.total) { panel.hidden = true; return; }
    panel.hidden = false;
    host.innerHTML = '';
    host.appendChild(kpi(M.filed, 'filed themselves',
      M.auto_rate == null ? '' : Math.round(M.auto_rate * 100) + '% of meetings that arrived'));
    host.appendChild(kpi(M.waited, 'waited for a person',
      M.waited ? 'the system was not sure enough' : ''));
    host.appendChild(kpi(M.confirmed, 'confirmed by a person',
      M.overruled ? M.overruled + ' overruled the guess' : (M.confirmed ? 'all agreed with the guess' : '')));
    host.appendChild(kpi(M.ignored, 'kept out of the library'));
    if (M.rebuilt) host.appendChild(kpi(M.rebuilt, 'documents rebuilt'));
  }

  // --- activity -----------------------------------------------------------------------------------
  function renderActivity() {
    var A = D.activity, F = D.feedback;
    var host = $('#obsActivity');
    host.innerHTML = '';
    host.appendChild(kpi(A.questions, 'questions asked', 'in the last two months'));
    host.appendChild(kpi(A.median_ms == null ? '-' : A.median_ms + ' ms', 'median answer',
      A.p90_ms ? 'p90 ' + A.p90_ms + ' ms' : ''));
    host.appendChild(kpi(A.keyword_only_rate == null ? '-' : pct(A.keyword_only, A.questions),
      'answered without meaning search',
      A.keyword_only ? 'each of those said so on screen' : 'meaning search has been available'));
    host.appendChild(kpi(A.feedback_rate == null ? '-' : pct(A.feedback, A.answers),
      'answers given feedback'));
    host.appendChild(kpi(F.promoted, 'corrections in the library',
      F.superseding + ' of them push a passage down' + (F.withdrawn ? ' · ' + F.withdrawn + ' withdrawn' : '')));
    host.appendChild(kpi(A.documents_added, 'documents added',
      A.documents_edited + ' edited'));

    renderMeetings();

    var weeks = $('#obsWeeks');
    weeks.innerHTML = '';
    if (A.by_week.length) {
      weeks.appendChild(el('h3', null, 'Questions per week'));
      var max = Math.max.apply(null, A.by_week.map(function (w) { return w.count; }));
      var bars = el('div', 'kb-bars');
      var labels = el('div', 'kb-barlabels');
      A.by_week.forEach(function (w) {
        var b = el('div', 'b');
        b.style.height = Math.max(2, w.count / max * 78) + 'px';
        b.appendChild(el('span', null, String(w.count)));
        bars.appendChild(b);
        labels.appendChild(el('div', null, w.week.replace(/^\d{4}-/, '')));
      });
      weeks.appendChild(bars);
      weeks.appendChild(labels);
    }

    var docs = $('#obsDocs');
    docs.innerHTML = '';
    var a = el('div');
    a.appendChild(el('h3', null, 'Retrieved most often'));
    if (A.top_documents.length) {
      var t1 = el('table', 'kb-tbl');
      var b1 = el('tbody');
      A.top_documents.slice(0, 10).forEach(function (r) {
        var tr = el('tr');
        tr.appendChild(el('td', null, (D.titles[r.id] || {}).title || r.id));
        tr.appendChild(el('td', 'n', String(r.count)));
        b1.appendChild(tr);
      });
      t1.appendChild(b1); a.appendChild(t1);
    } else { a.appendChild(el('p', 'kb-hint', 'Nothing retrieved yet.')); }
    docs.appendChild(a);

    var b = el('div');
    b.appendChild(el('h3', null, 'Never retrieved once'));
    var never = (A.never_retrieved || []).filter(function (id) { return D.titles[id]; });
    if (never.length) {
      var t2 = el('table', 'kb-tbl');
      var b2 = el('tbody');
      never.slice(0, 12).forEach(function (id) {
        var tr = el('tr');
        tr.appendChild(el('td', null, (D.titles[id] || {}).title || id));
        tr.appendChild(el('td', null, (D.titles[id] || {}).folder || 'no folder'));
        b2.appendChild(tr);
      });
      t2.appendChild(b2); b.appendChild(t2);
      b.appendChild(el('p', 'kb-hint', 'Dead weight worth reviewing, not necessarily worth '
        + 'deleting: a document nobody has needed yet is not the same as one nobody will.'));
    } else { b.appendChild(el('p', 'kb-hint', 'Every document has been retrieved at least once.')); }
    docs.appendChild(b);
  }

  function renderSettings() {
    var R = D.retrieval;
    var host = $('#obsSettings');
    var t = el('table', 'kb-tbl');
    var tb = el('tbody');
    [
      ['Passage size', R.chunk_words[0] + ' words, ' + R.chunk_words[1] + ' of overlap',
        'packed on structure: whole paragraphs and bullets, and only an oversized block is cut'],
      ['Candidates per retriever', R.candidates,
        'wider than the eight returned, so fusion has something to promote'],
      ['Fusion', 'RRF, k = ' + R.rrf_k, 'by rank, never by score'],
      ['Passages returned', R.limit, 'at most ' + R.max_per_doc + ' from any one document'],
      ['Relevance floor', 'cosine ' + R.semantic_floor,
        'below this a semantic candidate is dropped rather than ranked'],
      ['Verified nudge', '+' + R.trust_nudge,
        'about 12 to 15 ranks: enough to surface a correction, not enough to beat a passage both '
        + 'retrievers ranked highly'],
      ['Supersede penalty', '-' + R.superseded_penalty,
        'applied ONLY to the passages a retrieved correction names, never to a whole document'],
      ['Storage', D.storage.bucket + '/' + D.storage.prefix + '/', 'no database, no vector store']
    ].forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', null, r[0]));
      tr.appendChild(el('td', null, String(r[1])));
      var n = el('td', null, r[2]);
      n.style.color = 'var(--muted)'; n.style.whiteSpace = 'normal';
      tr.appendChild(n);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    host.innerHTML = '';
    host.appendChild(t);
  }

  function renderTracing() {
    var T = D.tracing;
    var host = $('#obsTracing');
    host.innerHTML = '';
    var k = kpi(T.enabled ? 'on' : 'off', 'Phoenix span export', T.reason,
      T.enabled ? 'ok' : 'off');
    k.querySelector('.v').style.fontSize = '15px';
    var grid = el('div', 'kb-kpis');
    grid.appendChild(k);
    host.appendChild(grid);
    var p = el('p', 'kb-hint');
    p.style.marginTop = '12px';
    p.textContent = T.enabled
      ? 'Spans carry the passages they returned, which is internal company writing. Whatever '
        + 'Phoenix this points at must be access controlled like the platform itself. Set '
        + 'KB_TRACE_CONTENT=off to stop capturing passage text.'
      : T.how + ' Everything on this page works without it: the question record above is read from '
        + 'the bucket, so "why did it say that?" is answerable with tracing switched off.';
    host.appendChild(p);
    if (T.enabled && T.endpoint) {
      var f = document.createElement('iframe');
      f.src = T.endpoint;
      f.style.cssText = 'width:100%;height:520px;border:1px solid var(--border);border-radius:10px;margin-top:12px';
      host.appendChild(f);
    }
  }

  // --- boot -------------------------------------------------------------------------------------
  function load() {
    return api('/obs/data').then(function (j) {
      D = j;
      renderReach(null);
      renderLibrary();
      renderQuestions();
      renderActivity();
      renderSettings();
      renderTracing();
    }).catch(function (e) {
      document.querySelector('.kb-wrap').insertAdjacentHTML('afterbegin',
        '<div class="kb-panel" style="border-color:rgba(248,113,113,.4)"><h3>Could not load</h3>'
        + '<p class="note">' + e.message + '</p></div>');
    });
  }

  function boot() {
    $('#obsRun').onclick = runProbe;
    $('#obsQ').onkeydown = function (e) { if (e.key === 'Enter') runProbe(); };
    $('#obsProbeAll').onclick = function () {
      var b = $('#obsProbeAll');
      b.disabled = true; b.textContent = 'Checking…';
      api('/obs/reach', { method: 'POST', body: { which: 'all' } }).then(function (j) {
        renderReach(j.probes);
      }).catch(function (e) { alert(e.message); }).then(function () {
        b.disabled = false; b.textContent = 'Check all three';
      });
    };
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
