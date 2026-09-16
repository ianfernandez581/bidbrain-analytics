/* kb.js - the Documents explorer.
 *
 * It behaves like Windows File Explorer on purpose. A media buyer already knows how to use that:
 * folder tree, breadcrumb address bar, double-click to open, drag onto a folder to move,
 * right-click for actions, F2 to rename, Delete to delete, Backspace to go up. Nobody has to be
 * taught a bespoke interaction to file a media plan.
 *
 * 🔴 A FOLDER IS A PATH CONVENTION, NOT A RECORD. `Media plans/Q4` is `Q4` inside `Media plans`,
 * and the tree is DERIVED from the folder strings in use. So a folder with nothing in it does not
 * exist on the server: one you have just created lives in this browser only, is drawn faintly, and
 * the UI says so rather than pretending it was saved.
 *
 * 🔴 AN AUTH FAILURE IS NEVER REPORTED AS "TRY AGAIN". The session is a hard 12 hour cap, so the
 * first thing somebody learns about being signed out is usually a button failing. `api()` branches
 * on 401 and offers the sign-in link, and nothing that was typed is thrown away.
 */
(function () {
  'use strict';

  var API = '/kb';
  var LS = 'bb.kb.';

  /* WHERE YOU ARE is two things, not one: WHICH CLIENT (or the agency-wide root), and which
   * FOLDER inside it. `view` names the three levels the rail and the breadcrumb both read:
   *
   *   'root'    the agency-wide shelves: Playbook, Platform docs, Media buyer knowledge
   *   'clients' the list of clients, reached by opening the Clients folder
   *   'client'  one client's own shelves: Media plans, Briefs, Meetings
   *
   * A client's work lives INSIDE that client, never as a top-level folder shared by everyone,
   * which is what makes "whose plan is this?" answerable from the document rather than from
   * whoever remembered to put the name in the title.
   */
  var S = {
    // 🔴 `level`, NOT `view`. `S.view` already means the details/icons list toggle, and the
    // first version of this used `view` for both: the toggle overwrote the navigation level
    // and back, so opening Clients silently did nothing and the list never showed clients.
    level: 'root',           // root | clients | client
    client: '',              // the registry key when view === 'client', else ''
    clients: [],             // [{key, name, count}] from the registry
    clientFolders: [],       // the shelves every client offers, server-driven
    cwd: '',                 // current folder path, '' = root, '/' handled as "no folder"
    view: localStorage.getItem(LS + 'view') || 'details',
    sortKey: localStorage.getItem(LS + 'sortKey') || 'title',
    sortDir: +(localStorage.getItem(LS + 'sortDir') || 1),
    open: {},                // expanded tree nodes
    ghosts: [],              // folders created in this browser that hold nothing yet
    folders: [], rootCount: 0, total: 0, archivedCount: 0, empty: false,
    docs: [], sel: [], anchor: null, q: '', archived: false,
    pollTimer: null,
    treeSig: ''         // what the rail was last built from; see renderTree
  };
  /* 🔴 A STORED VALUE IS UNTRUSTED INPUT, even our own. An earlier build wrote the Ask panel's
   * open flag ('1') to this same key, so this parsed to the NUMBER 1 and every click on a tree
   * twisty threw "Cannot create property on number". A try/catch does not catch that, because
   * JSON.parse("1") succeeds. Anything that is not a plain object is discarded, so a browser that
   * loaded the broken build heals itself on the next visit instead of having a dead tree. */
  try {
    var savedOpen = JSON.parse(localStorage.getItem(LS + 'open') || '{}');
    S.open = (savedOpen && typeof savedOpen === 'object' && !Array.isArray(savedOpen)) ? savedOpen : {};
  } catch (e) { S.open = {}; }

  // --- tiny helpers -----------------------------------------------------------------------
  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function esc(s) { return String(s == null ? '' : s); }

  /* An actor is an email only for a Google or Microsoft sign-in. A typed admin password and the
   * shared agency password have no person behind them, so `_kb_actor` records the TIER, and this
   * says that in words rather than printing `shared:superadmin` at somebody. */
  function who(a) {
    a = String(a || '');
    if (a.indexOf('shared:') === 0) return a.slice(7) + ' (shared login)';
    if (a.indexOf('agency:') === 0) return a.slice(7) + ' (shared login)';
    return a;
  }

  function fmtBytes(n) {
    n = +n || 0;
    if (!n) return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }
  function fmtDate(ts) {
    if (!ts) return '';
    var d = new Date(ts * 1000), now = new Date();
    var same = d.toDateString() === now.toDateString();
    var t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return same ? 'Today ' + t : d.toLocaleDateString([], { day: '2-digit', month: 'short', year: 'numeric' }) + ' ' + t;
  }
  var ICON = {
    folder: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f3c969" stroke-width="1.7"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    doc: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9a93a6" stroke-width="1.7"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
    pdf: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="1.7"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
    fb: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f3c969" stroke-width="1.7"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-4.1A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z"/></svg>',
    clients: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#8ab4ff" stroke-width="1.7"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="2"/><path d="M8.5 17a3.5 3.5 0 0 1 7 0"/></svg>',
    client: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#8ab4ff" stroke-width="1.7"><circle cx="12" cy="8" r="3.2"/><path d="M5 20a7 7 0 0 1 14 0"/></svg>',
    bigClient: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#8ab4ff" stroke-width="1.3"><circle cx="12" cy="8" r="3.2"/><path d="M5 20a7 7 0 0 1 14 0"/></svg>',
    bigFolder: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#f3c969" stroke-width="1.4"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    bigDoc: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#9a93a6" stroke-width="1.4"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>'
  };
  function iconFor(d, big) {
    if (d.kind === 'feedback') return ICON.fb;
    if ((d.mime || '').indexOf('pdf') >= 0 || /\.pdf$/i.test(d.filename || '')) {
      return big ? ICON.bigDoc : ICON.pdf;
    }
    return big ? ICON.bigDoc : ICON.doc;
  }

  // --- toasts, and the one place an auth failure is explained ------------------------------
  var toastTimer = null;
  function toast(msg, isErr, html) {
    var old = $('.kb-toast'); if (old) old.remove();
    clearTimeout(toastTimer);
    var t = el('div', 'kb-toast' + (isErr ? ' err' : ''));
    if (html) t.innerHTML = msg; else t.textContent = msg;
    document.body.appendChild(t);
    toastTimer = setTimeout(function () { t.remove(); }, isErr ? 9000 : 3200);
  }
  window.kbToast = toast;

  function api(path, opts) {
    opts = opts || {};
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'Server error ' + r.status }; })
        .then(function (j) {
          if (r.status === 401) {
            // 🔴 Retrying can never fix this, so never suggest it.
            toast('Your session has expired. <a href="/">Sign in again</a> and your work here is '
              + 'still in the library.', true, true);
            var e = new Error('auth'); e.auth = true; e.payload = j; throw e;
          }
          if (!r.ok || j.ok === false) {
            var err = new Error(j.error || ('Server error ' + r.status));
            err.payload = j; err.status = r.status; throw err;
          }
          return j;
        });
    });
  }
  window.kbApi = api;

  // --- folder maths -------------------------------------------------------------------------
  function parentOf(p) { var i = p.lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i); }
  function nameOf(p) { var i = p.lastIndexOf('/'); return i < 0 ? p : p.slice(i + 1); }

  function allFolderPaths() {
    var seen = {}, out = [];
    S.folders.forEach(function (f) { seen[f.path] = f; out.push(f); });
    S.ghosts.forEach(function (p) {
      if (!seen[p]) { seen[p] = 1; out.push({ path: p, name: nameOf(p), depth: p.split('/').length - 1, count: 0, ghost: true }); }
    });
    out.sort(function (a, b) { return a.path.toLowerCase() < b.path.toLowerCase() ? -1 : 1; });
    return out;
  }
  function childrenOf(path) {
    return allFolderPaths().filter(function (f) { return parentOf(f.path) === path; });
  }

  // --- load ---------------------------------------------------------------------------------
  function scopeQ() { return '&client=' + encodeURIComponent(S.level === 'client' ? S.client : ''); }

  function loadClients() {
    return api('/clients').then(function (j) {
      S.clients = j.clients || [];
      S.agencyCount = j.agency_count || 0;
    }).catch(function () { S.clients = []; });
  }

  function loadTree() {
    return api('/tree?x=1' + scopeQ()).then(function (j) {
      S.clientFolders = j.client_folders || [];
      S.folders = j.folders || [];
      S.rootCount = j.root_count || 0;
      S.total = j.total || 0;
      S.archivedCount = j.archived || 0;
      S.empty = !!j.empty;
      // A ghost that now holds something is a real folder; stop drawing it as pending.
      var real = {}; S.folders.forEach(function (f) { real[f.path] = 1; });
      S.ghosts = S.ghosts.filter(function (p) { return !real[p]; });
      renderTree();
      // 🔴 The list draws FOLDER rows too, and folders come from this call. `refresh()` fires both
      // requests in parallel, so whichever order they land in, the list has to be repainted here:
      // when /docs resolved first (which it usually did on a cold load) the main pane showed the
      // documents and NO folders at all, and nothing later put them back.
      renderList();
    });
  }

  function loadList() {
    // 🔴 THE LIST IS SCOPED TOO, not just the tree. Without the client the file list shows every
    // document in the library from inside a client, so Geocon's folder showed the agency playbook
    // and every other client's work. Browsing a client must show what that CLIENT holds.
    // 🔴 `deep` IS NOT AN OPTIMISATION, IT IS WHAT THESE TWO VIEWS ARE. A folder - the
    // root included - lists its own direct children, so anything that draws no folder rows has
    // to ask for the whole subtree or it silently shows only what happens to be unfiled. That is
    // a search, and it is the Archived shelf, which is one flat list of everything put away.
    var qs = '?folder=' + encodeURIComponent(S.cwd || '') + scopeQ()
           + (S.archived ? '&archived=1&deep=1' : '');
    if (S.q) qs += '&q=' + encodeURIComponent(S.q) + '&deep=1';
    return api('/docs' + qs).then(function (j) {
      S.docs = j.docs || [];
      S.sel = S.sel.filter(function (id) { return S.docs.some(function (d) { return d.id === id; }); });
      renderList();
      scheduleIndexPoll();
    });
  }

  function refresh() { return Promise.all([loadClients().then(loadTree), loadList()]); }
  window.kbRefresh = refresh;

  // 🔴 A row that says "indexing" has to stop saying it without a page reload, or the state reads
  // as stuck rather than as in progress. Poll only while at least one row is mid-index.
  function scheduleIndexPoll() {
    clearTimeout(S.pollTimer);
    if (!S.docs.some(function (d) { return d.state === 'indexing'; })) return;
    S.pollTimer = setTimeout(function () { loadList().catch(function () {}); }, 2500);
  }

  // --- render: tree -------------------------------------------------------------------------
  /* 🔴 A CLICK IS LOST IF THE NODE UNDER THE CURSOR IS REPLACED BETWEEN MOUSEDOWN AND MOUSEUP.
   * The browser emits no click at all in that case: nothing throws, nothing logs, the click simply
   * does not happen, which is exactly what "the button doesn't always work" feels like. Every
   * navigation ran a refresh whose reply rebuilt this whole rail a second later, so any click made
   * in that window could land on a node that was about to be thrown away.
   *
   * So the rail is only rebuilt when it would actually come out different. The signature covers
   * everything the markup depends on; anything else is a no-op and the DOM, and your click, stay
   * put. (The second half of the fix is acting on mousedown: see `navOn` below.) */
  function treeSignature() {
    return JSON.stringify([
      S.level, S.client, S.cwd, S.archived, S.total, S.rootCount, S.archivedCount,
      S.clients.map(function (c) { return [c.key, c.name, c.count]; }),
      allFolderPaths().map(function (f) { return [f.path, f.count, !!f.ghost]; }),
      Object.keys(S.open).filter(function (k) { return S.open[k]; }).sort()
    ]);
  }

  function renderTree(force) {
    var wrap = $('#kbTree');
    var sig = treeSignature();
    if (!force && sig === S.treeSig && wrap.childElementCount) return;
    S.treeSig = sig;
    wrap.innerHTML = '';
    wrap.appendChild(el('h4', null, 'Knowledge base'));

    // The agency-wide root, and its shelves.
    wrap.appendChild(node({ path: '', name: 'All documents', count: S.total }, 0, true));
    if (S.level !== 'client') {
      // There is no "No folder" node any more: since the root lists what sits directly in it,
      // that node showed the same documents under a second name, and two places saying one
      // thing is how they start disagreeing. The '/' path still works (the Ask panel scopes
      // with it, and it is what an old bookmark holds), it just is not offered twice.
      (function walk(parent, depth) {
        childrenOf(parent).forEach(function (f) {
          var kids = childrenOf(f.path);
          wrap.appendChild(node(f, depth, kids.length > 0));
          if (kids.length && S.open[f.path]) walk(f.path, depth + 1);
        });
      })('', 1);
    }

    // Clients, as a real branch of the tree. Open it to see the clients; open a client to see
    // their shelves. Drawn from the REGISTRY, so a client with nothing yet is still there to file
    // into rather than appearing only once somebody has remembered to tag something.
    wrap.appendChild(clientsNode());
    if (S.open['@clients'] || S.level !== 'root') {
      S.clients.forEach(function (c) {
        wrap.appendChild(clientNode(c));
        if (S.level === 'client' && S.client === c.key) {
          childrenOf('').forEach(function (f) {
            wrap.appendChild(node(f, 3, childrenOf(f.path).length > 0));
          });
        }
      });
    }

    if (S.archivedCount) {
      var a = el('div', 'kb-node' + (S.archived ? ' on' : ''));
      a.style.marginTop = '10px';
      a.innerHTML = '<span class="tw leaf"></span><span class="ico">'
        + '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6b6478" stroke-width="1.7">'
        + '<path d="M3 7h18v3H3z"/><path d="M5 10v9h14v-9"/><path d="M10 14h4"/></svg></span>'
        + '<span class="nm">Archived</span><span class="ct">' + S.archivedCount + '</span>';
      navOn(a, function () {
        S.archived = true; S.cwd = ''; S.sel = [];
        renderTree(true); loadList();
      });
      wrap.appendChild(a);
    }

    function clientsNode() {
      var n = el('div', 'kb-node' + (S.level === 'clients' ? ' on' : ''));
      n.style.paddingLeft = '19px';
      var tw = el('span', 'tw' + (S.open['@clients'] || S.level !== 'root' ? ' open' : ''), '\u25B6');
      tw.onmousedown = function (e) {
        e.stopPropagation();
        e.preventDefault();
        S.open['@clients'] = !(S.open['@clients'] || S.level !== 'root');
        localStorage.setItem(LS + 'open', JSON.stringify(S.open));
        renderTree(true);
      };
      tw.onclick = function (e) { e.stopPropagation(); };
      n.appendChild(tw);
      var ic = el('span', 'ico'); ic.innerHTML = ICON.clients; n.appendChild(ic);
      n.appendChild(el('span', 'nm', 'Clients'));
      n.appendChild(el('span', 'ct', S.clients.length ? String(S.clients.length) : ''));
      navOn(n, goClients);
      return n;
    }

    function clientNode(c) {
      var n = el('div', 'kb-node' + (S.level === 'client' && S.client === c.key ? ' on' : ''));
      n.style.paddingLeft = '32px';
      var kids = S.level === 'client' && S.client === c.key;
      n.appendChild(el('span', 'tw' + (kids ? ' open' : ''), '\u25B6'));
      var ic = el('span', 'ico'); ic.innerHTML = ICON.client; n.appendChild(ic);
      n.appendChild(el('span', 'nm', c.name));
      n.appendChild(el('span', 'ct', c.count ? String(c.count) : ''));
      navOn(n, function () { goClient(c.key); });
      wireClientDrop(n, c.key);
      return n;
    }

    function node(f, depth, hasKids, isRoot) {
      var n = el('div', 'kb-node' + (!S.archived && S.cwd === f.path ? ' on' : '')
        + (f.ghost ? ' ghost' : ''));
      n.style.paddingLeft = (6 + depth * 13) + 'px';
      n.dataset.folder = f.path;
      var tw = el('span', 'tw' + (hasKids ? (S.open[f.path] ? ' open' : '') : ' leaf'), '▶');
      tw.onmousedown = function (e) {
        e.stopPropagation();
        e.preventDefault();
        S.open[f.path] = !S.open[f.path];
        localStorage.setItem(LS + 'open', JSON.stringify(S.open));
        renderTree(true);
      };
      tw.onclick = function (e) { e.stopPropagation(); };
      n.appendChild(tw);
      var ic = el('span', 'ico'); ic.innerHTML = isRoot ? ICON.doc : ICON.folder; n.appendChild(ic);
      var nm = el('span', 'nm', f.name);
      if (f.ghost) { nm.style.opacity = '.55'; nm.title = 'Created here, but empty. It exists once a document is in it.'; }
      n.appendChild(nm);
      n.appendChild(el('span', 'ct', f.count ? String(f.count) : ''));
      navOn(n, function () { go(f.path); });
      if (f.path !== '/' ) {
        n.oncontextmenu = function (e) { e.preventDefault(); folderMenu(e, f); };
        wireFolderDrop(n, f.path);
      }
      return n;
    }
  }

  /* Navigation fires on MOUSEDOWN, not click. A file explorer selects on mouse-down anyway, and
   * it means an in-flight re-render can never swallow the action: by the time anything could
   * replace the node, the navigation has already happened. Left button only, so a right-click
   * still opens the context menu instead of navigating. */
  function navOn(node, fn) {
    node.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      e.preventDefault();
      fn();
    });
  }

  function go(path) {
    S.archived = false; S.cwd = path; S.sel = []; S.anchor = null;
    clearSearch();
    renderTree(true); renderCrumbs(); loadList();
  }
  function goClients() {
    S.archived = false; S.level = 'clients'; S.client = ''; S.cwd = ''; S.sel = [];
    S.open['@clients'] = true;
    clearSearch();
    renderTree(true); renderCrumbs(); renderList(); renderStatusLine(S.clients.length, 0);
  }
  function goClient(key) {
    S.archived = false; S.level = 'client'; S.client = key; S.cwd = ''; S.sel = [];
    clearSearch();
    renderCrumbs();
    refresh();
  }
  function goRoot() {
    S.archived = false; S.level = 'root'; S.client = ''; S.cwd = ''; S.sel = [];
    clearSearch();
    renderCrumbs();
    refresh();
  }
  function clearSearch() {
    var s = $('#kbSearch');
    if (s && S.q) { S.q = ''; s.value = ''; }
  }
  function currentClientName() {
    var c = S.clients.filter(function (x) { return x.key === S.client; })[0];
    return c ? c.name : S.client;
  }
  window.kbGo = go;

  function renderCrumbs() {
    var c = $('#kbCrumbs'); c.innerHTML = '';
    function add(label, path, last) {
      var b = el('span', 'cr', label);
      b.onclick = function () { go(path); };
      c.appendChild(b);
      if (!last) c.appendChild(el('span', 'sep', '›'));
    }
    function addRoot(last) {
      var b = el('span', 'cr', 'All documents');
      b.onclick = goRoot;
      c.appendChild(b);
      if (!last) c.appendChild(el('span', 'sep', '\u203A'));
    }
    if (S.archived) { addRoot(false); c.appendChild(el('span', 'cr', 'Archived')); return; }
    if (S.level === 'clients') {
      addRoot(false);
      c.appendChild(el('span', 'cr', 'Clients'));
      return;
    }
    var parts = S.cwd && S.cwd !== '/' ? S.cwd.split('/') : [];
    if (S.level === 'client') {
      addRoot(false);
      var cl = el('span', 'cr', 'Clients');
      cl.onclick = goClients;
      c.appendChild(cl);
      c.appendChild(el('span', 'sep', '\u203A'));
      if (!parts.length) { c.appendChild(el('span', 'cr', currentClientName())); return; }
      var me = el('span', 'cr', currentClientName());
      me.onclick = function () { go(''); };
      c.appendChild(me);
      c.appendChild(el('span', 'sep', '\u203A'));
    } else {
      if (S.cwd === '/') { addRoot(false); add('No folder', '/', true); return; }
      addRoot(parts.length === 0);
    }
    var acc = '';
    parts.forEach(function (p, i) {
      acc = acc ? acc + '/' + p : p;
      add(p, acc, i === parts.length - 1);
    });
  }

  // --- render: file list ----------------------------------------------------------------------
  var COLS = [
    { key: 'title', label: 'Name', w: '' },
    { key: 'updated_at', label: 'Date modified', w: '170px' },
    { key: 'kind', label: 'Type', w: '110px' },
    { key: 'chars', label: 'Size', w: '90px' },
    { key: 'state', label: 'Search', w: '120px' },
    { key: 'owner', label: 'Added by', w: '170px' },
    { key: 'updated_by', label: 'Modified by', w: '170px' }
  ];

  function sortedFolders() {
    // '/' is the "documents in no folder" view, which by definition has no subfolders. A search
    // is deep, so listing folders under it would be a second, contradicting answer.
    if (S.archived || S.q || S.cwd === '/') return [];
    var out = childrenOf(S.cwd);
    if (S.level === 'client' && !S.cwd) {
      // 🔴 THE STANDARD SHELVES ARE OFFERED, NOT SEEDED. A folder exists because something is in
      // it, so a new client would otherwise open on nothing at all and leave somebody guessing
      // where a media plan goes. These are drawn faint until the first document lands in them,
      // exactly like a folder you have just created.
      var have = {};
      out.forEach(function (f) { have[f.name] = 1; });
      S.clientFolders.forEach(function (cf) {
        if (!have[cf.name]) {
          out.push({ path: cf.name, name: cf.name, depth: 0, count: 0, ghost: true, note: cf.note });
        }
      });
      out.sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
    }
    return out;
  }

  function sortedDocs() {
    var k = S.sortKey, dir = S.sortDir;
    return S.docs.slice().sort(function (a, b) {
      var x = a[k], y = b[k];
      if (k === 'chars' || k === 'updated_at') { x = +x || 0; y = +y || 0; }
      else { x = String(x || '').toLowerCase(); y = String(y || '').toLowerCase(); }
      return x < y ? -dir : x > y ? dir : 0;
    });
  }

  function renderList() {
    var host = $('#kbList');
    host.innerHTML = '';
    // The Clients level lists CLIENTS, not documents: it is a folder of folders.
    if (S.level === 'clients') {
      host.appendChild(clientsView());
      renderStatusLine(S.clients.length, 0);
      return;
    }
    var folders = sortedFolders(), docs = sortedDocs();

    if (!folders.length && !docs.length) { host.appendChild(emptyState()); return; }
    if (S.view === 'icons') { host.appendChild(iconsView(folders, docs)); }
    else { host.appendChild(detailsView(folders, docs)); }
    renderStatusLine(folders.length, docs.length);
  }

  function clientsView() {
    // The clients level is always tiles: they are places, not files, so the details/icons
    var g = el('div', 'kb-icons');
    if (!S.clients.length) {
      var e = el('div', 'kb-empty');
      e.appendChild(el('h3', null, 'No clients on this account'));
      e.appendChild(el('p', null, 'The client list comes from the platform registry. A dashboard '
        + 'you can open is a client you can file against.'));
      return e;
    }
    S.clients.forEach(function (c) {
      var t = el('div', 'kb-tile');
      var i = el('div'); i.innerHTML = ICON.bigClient; t.appendChild(i);
      t.appendChild(el('div', 'nm', c.name));
      var sub = el('span', 'kb-state ' + (c.count ? 'searchable' : 'empty'),
        c.count ? c.count + (c.count === 1 ? ' document' : ' documents') : 'nothing yet');
      t.appendChild(sub);
      t.ondblclick = function () { goClient(c.key); };
      t.onclick = function () { goClient(c.key); };
      wireClientDrop(t, c.key);
      g.appendChild(t);
    });
    return g;
  }

  function emptyState() {
    var e = el('div', 'kb-empty');
    if (S.q) {
      e.appendChild(el('h3', null, 'Nothing matches "' + S.q + '"'));
      e.appendChild(el('p', null, 'This box filters by file name. To search what is INSIDE the '
        + 'documents, use Ask: it reads the text, not the titles.'));
      var b = el('button', 'btn gold', 'Ask instead');
      b.onclick = function () { if (window.kbAsk) window.kbAsk.open(S.q); };
      e.appendChild(b);
      return e;
    }
    if (S.archived) {
      e.appendChild(el('h3', null, 'Nothing archived'));
      e.appendChild(el('p', null, 'A withdrawn correction ends up here. Archived documents are out '
        + 'of search but not deleted.'));
      return e;
    }
    if (S.empty) {
      e.appendChild(el('h3', null, 'The library is empty'));
      e.appendChild(el('p', null, 'Start it with six folders: media plans, briefs, meetings, '
        + 'platform docs, the playbook, and what buyers have corrected. Each gets a one line note '
        + 'saying what belongs in it. You can rename or delete them afterwards.'));
      var b = el('button', 'btn gold', 'Create the starting folders');
      b.onclick = function () {
        b.disabled = true;
        api('/tree?seed=1').then(function () { return refresh(); })
          .then(function () { toast('Starting folders created.'); })
          .catch(function (err) { if (!err.auth) toast(err.message, true); b.disabled = false; });
      };
      e.appendChild(b);
      return e;
    }
    if (S.level === 'client' && !S.cwd) {
      e.appendChild(el('h3', null, 'Nothing filed for ' + currentClientName() + ' yet'));
      e.appendChild(el('p', null, 'Their media plans, briefs and meetings go in here. Drop files '
        + 'anywhere on this list, or use New document. Anything filed here is read when somebody '
        + 'asks about ' + currentClientName() + ', alongside the agency-wide playbook, and is '
        + 'never read for another client.'));
      return e;
    }
    e.appendChild(el('h3', null, 'This folder is empty'));
    e.appendChild(el('p', null, 'Drop files anywhere on this list to add them, or use New document '
      + 'to paste text in. A file becomes searchable within seconds of landing.'));
    return e;
  }

  function detailsView(folders, docs) {
    var t = el('table', 'kb-files');
    var thead = el('thead'), tr = el('tr');
    COLS.forEach(function (c) {
      var th = el('th', null, c.label);
      if (c.w) th.style.width = c.w;
      if (S.sortKey === c.key) th.innerHTML = c.label + '<span class="ar">' + (S.sortDir > 0 ? '▲' : '▼') + '</span>';
      th.onclick = function () {
        if (S.sortKey === c.key) S.sortDir = -S.sortDir; else { S.sortKey = c.key; S.sortDir = 1; }
        localStorage.setItem(LS + 'sortKey', S.sortKey);
        localStorage.setItem(LS + 'sortDir', String(S.sortDir));
        renderList();
      };
      tr.appendChild(th);
    });
    thead.appendChild(tr); t.appendChild(thead);
    var tb = el('tbody');
    folders.forEach(function (f) { tb.appendChild(folderRow(f)); });
    docs.forEach(function (d) { tb.appendChild(docRow(d)); });
    t.appendChild(tb);
    return t;
  }

  function folderRow(f) {
    var tr = el('tr', 'kb-item');
    tr.dataset.folder = f.path;
    var td = el('td');
    var nm = el('div', 'kb-name');
    var ic = el('span', 'ico'); ic.innerHTML = ICON.folder; nm.appendChild(ic);
    var t = el('span', 't', f.name);
    if (f.ghost) { t.style.opacity = '.55'; }
    nm.appendChild(t);
    if (f.ghost) nm.appendChild(el('span', 'kb-state empty', 'not saved yet'));
    td.appendChild(nm); tr.appendChild(td);
    tr.appendChild(el('td', 'kb-num', ''));
    tr.appendChild(el('td', null, 'Folder'));
    tr.appendChild(el('td', 'kb-num', f.count ? f.count + ' item' + (f.count === 1 ? '' : 's') : ''));
    tr.appendChild(el('td'));
    tr.appendChild(el('td'));
    tr.appendChild(el('td'));
    tr.ondblclick = function () { go(f.path); };
    tr.onclick = function () { S.sel = []; paintSel(); };
    tr.oncontextmenu = function (e) { e.preventDefault(); folderMenu(e, f); };
    wireFolderDrop(tr, f.path);
    return tr;
  }

  function docRow(d) {
    var tr = el('tr', 'kb-item' + (S.sel.indexOf(d.id) >= 0 ? ' sel' : ''));
    tr.dataset.id = d.id;
    var td = el('td');
    var nm = el('div', 'kb-name');
    var ic = el('span', 'ico'); ic.innerHTML = iconFor(d); nm.appendChild(ic);
    nm.appendChild(el('span', 't', d.title));
    if (d.trust === 'verified') nm.appendChild(el('span', 'kb-trust', 'VERIFIED'));
    td.appendChild(nm); td.title = d.title; tr.appendChild(td);
    tr.appendChild(el('td', 'kb-num', fmtDate(d.updated_at)));
    tr.appendChild(el('td', null, d.source === 'upload' ? (d.filename || '').split('.').pop().toUpperCase() + ' upload'
      : d.kind === 'feedback' ? 'Correction' : (d.kind || 'note')));
    tr.appendChild(el('td', 'kb-num', d.bytes ? fmtBytes(d.bytes) : fmtBytes(d.chars)));
    var st = el('td');
    var b = el('span', 'kb-state ' + d.state, {
      searchable: 'searchable', indexing: 'indexing', keyword: 'keyword only', empty: 'no text'
    }[d.state] || d.state);
    if (d.state_note) b.title = d.state_note;
    st.appendChild(b); tr.appendChild(st);
    tr.appendChild(el('td', 'kb-num', who(d.owner)));
    var mod = el('td', 'kb-num', who(d.updated_by) || who(d.owner));
    mod.title = 'last edited ' + fmtDate(d.updated_at)
      + (d.revisions ? ' · ' + d.revisions + ' earlier version' + (d.revisions === 1 ? '' : 's') : '');
    tr.appendChild(mod);
    wireItem(tr, d);
    return tr;
  }

  function iconsView(folders, docs) {
    var g = el('div', 'kb-icons');
    folders.forEach(function (f) {
      var c = el('div', 'kb-tile');
      var i = el('div'); i.innerHTML = ICON.bigFolder; c.appendChild(i);
      c.appendChild(el('div', 'nm', f.name));
      c.ondblclick = function () { go(f.path); };
      c.oncontextmenu = function (e) { e.preventDefault(); folderMenu(e, f); };
      wireFolderDrop(c, f.path);
      g.appendChild(c);
    });
    docs.forEach(function (d) {
      var c = el('div', 'kb-tile' + (S.sel.indexOf(d.id) >= 0 ? ' sel' : ''));
      c.dataset.id = d.id;
      var i = el('div'); i.innerHTML = iconFor(d, true); c.appendChild(i);
      c.appendChild(el('div', 'nm', d.title));
      if (d.state !== 'searchable') c.appendChild(el('span', 'kb-state ' + d.state, d.state));
      wireItem(c, d);
      g.appendChild(c);
    });
    return g;
  }

  function renderStatusLine(nf, nd) {
    var s = $('#kbStatus');
    var bits = [];
    if (nf) bits.push(nf + ' folder' + (nf === 1 ? '' : 's'));
    bits.push(nd + ' document' + (nd === 1 ? '' : 's'));
    if (S.sel.length) bits.push(S.sel.length + ' selected');
    s.textContent = bits.join(' · ');
  }

  // --- selection --------------------------------------------------------------------------------
  function paintSel() {
    document.querySelectorAll('[data-id]').forEach(function (n) {
      n.classList.toggle('sel', S.sel.indexOf(n.dataset.id) >= 0);
    });
    renderStatusLine(sortedFolders().length, S.docs.length);
  }

  function wireItem(node, d) {
    node.draggable = true;
    node.onclick = function (e) {
      var ids = sortedDocs().map(function (x) { return x.id; });
      if (e.shiftKey && S.anchor) {
        var a = ids.indexOf(S.anchor), b = ids.indexOf(d.id);
        if (a > b) { var t = a; a = b; b = t; }
        S.sel = ids.slice(a, b + 1);
      } else if (e.ctrlKey || e.metaKey) {
        var i = S.sel.indexOf(d.id);
        if (i >= 0) S.sel.splice(i, 1); else S.sel.push(d.id);
        S.anchor = d.id;
      } else {
        S.sel = [d.id]; S.anchor = d.id;
      }
      paintSel();
    };
    node.ondblclick = function () { openDoc(d.id); };
    node.oncontextmenu = function (e) {
      e.preventDefault();
      if (S.sel.indexOf(d.id) < 0) { S.sel = [d.id]; S.anchor = d.id; paintSel(); }
      itemMenu(e, d);
    };
    node.ondragstart = function (e) {
      if (S.sel.indexOf(d.id) < 0) { S.sel = [d.id]; paintSel(); }
      e.dataTransfer.setData('text/bb-docs', JSON.stringify(S.sel));
      e.dataTransfer.effectAllowed = 'move';
    };
  }

  function wireFolderDrop(node, path) {
    node.addEventListener('dragover', function (e) {
      if (!(e.dataTransfer.types || []).some(function (t) { return t === 'text/bb-docs'; })) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      node.classList.add('drop');
    });
    node.addEventListener('dragleave', function () { node.classList.remove('drop'); });
    node.addEventListener('drop', function (e) {
      node.classList.remove('drop');
      var raw = e.dataTransfer.getData('text/bb-docs');
      if (!raw) return;
      e.preventDefault(); e.stopPropagation();
      moveDocs(JSON.parse(raw), path === '/' ? '' : path);
    });
  }

  /* Dropping a document onto a CLIENT re-files it against that client, keeping its folder. The
   * same gesture as dropping onto a folder, because "this plan belongs to Geocon" is the same kind
   * of correction as "this plan belongs in Media plans". */
  function wireClientDrop(node, key) {
    node.addEventListener('dragover', function (e) {
      if (!(e.dataTransfer.types || []).some(function (t) { return t === 'text/bb-docs'; })) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      node.classList.add('drop');
    });
    node.addEventListener('dragleave', function () { node.classList.remove('drop'); });
    node.addEventListener('drop', function (e) {
      node.classList.remove('drop');
      var raw = e.dataTransfer.getData('text/bb-docs');
      if (!raw) return;
      e.preventDefault(); e.stopPropagation();
      var ids = JSON.parse(raw);
      Promise.all(ids.map(function (id) {
        return api('/docs/' + id + '/move', { method: 'POST', body: { client: key } });
      })).then(function () {
        toast(ids.length + ' moved to ' + (S.clients.filter(function (c) { return c.key === key; })[0] || {}).name);
        S.sel = []; return refresh();
      }).catch(function (err) { if (!err.auth) toast(err.message, true); });
    });
  }

  function moveDocs(ids, folder) {
    Promise.all(ids.map(function (id) {
      return api('/docs/' + id + '/move', { method: 'POST',
        body: { folder: folder, client: S.level === 'client' ? S.client : '' } });
    })).then(function () {
      toast(ids.length + ' moved to ' + (folder || 'no folder'));
      S.sel = []; return refresh();
    }).catch(function (err) { if (!err.auth) toast(err.message, true); });
  }

  // --- context menus ------------------------------------------------------------------------
  function closeMenu() { var m = $('.kb-menu'); if (m) m.remove(); }
  document.addEventListener('click', closeMenu);
  document.addEventListener('scroll', closeMenu, true);

  function menu(e, items) {
    closeMenu();
    var m = el('div', 'kb-menu');
    items.forEach(function (it) {
      if (it === '-') { m.appendChild(el('div', 'sp')); return; }
      var b = el('button', it.danger ? 'danger' : null);
      b.appendChild(el('span', null, it.label));
      if (it.kbd) b.appendChild(el('span', 'kbd', it.kbd));
      b.disabled = !!it.disabled;
      b.onclick = function (ev) { ev.stopPropagation(); closeMenu(); it.run(); };
      m.appendChild(b);
    });
    document.body.appendChild(m);
    var w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.min(e.clientX, innerWidth - w - 8) + 'px';
    m.style.top = Math.min(e.clientY, innerHeight - h - 8) + 'px';
  }

  function itemMenu(e, d) {
    var many = S.sel.length > 1;
    menu(e, [
      { label: many ? 'Open ' + S.sel.length + ' documents' : 'Open', run: function () { S.sel.forEach(openDoc); } },
      { label: 'Ask about this', run: function () { if (window.kbAsk) window.kbAsk.open('', d.folder || null); } },
      '-',
      { label: 'Rename', kbd: 'F2', disabled: many, run: function () { renameDoc(d); } },
      { label: 'Move to…', run: function () { moveDialog(S.sel); } },
      { label: d.filename ? 'Download original' : 'Download original', disabled: !d.filename,
        run: function () { location.href = API + '/file/' + d.id; } },
      '-',
      { label: d.archived ? 'Restore from archive' : 'Archive', run: function () { setArchived(S.sel, !d.archived); } },
      { label: many ? 'Delete ' + S.sel.length + ' documents' : 'Delete', kbd: 'Del', danger: true,
        run: function () { deleteDocs(S.sel); } }
    ]);
  }

  function folderMenu(e, f) {
    menu(e, [
      { label: 'Open', run: function () { go(f.path); } },
      { label: 'New folder inside', run: function () { newFolder(f.path); } },
      '-',
      { label: 'Rename', kbd: 'F2', run: function () { renameFolder(f); } },
      { label: 'Delete', danger: true, run: function () { deleteFolder(f); } }
    ]);
  }

  // --- actions -------------------------------------------------------------------------------
  function deleteDocs(ids) {
    if (!ids.length) return;
    var what = ids.length === 1
      ? '"' + (S.docs.filter(function (d) { return d.id === ids[0]; })[0] || {}).title + '"'
      : ids.length + ' documents';
    if (!confirm('Delete ' + what + '? The original file goes too, and this cannot be undone.\n\n'
      + 'To take something out of search but keep it, use Archive instead.')) return;
    Promise.all(ids.map(function (id) { return api('/docs/' + id, { method: 'DELETE' }); }))
      .then(function () { S.sel = []; toast('Deleted.'); return refresh(); })
      .catch(function (err) { if (!err.auth) toast(err.message, true); });
  }

  function setArchived(ids, on) {
    Promise.all(ids.map(function (id) {
      return api('/docs/' + id, { method: 'PATCH', body: { archived: on } });
    })).then(function () {
      S.sel = []; toast(on ? 'Archived. It is out of search but not deleted.' : 'Restored.');
      return refresh();
    }).catch(function (err) { if (!err.auth) toast(err.message, true); });
  }

  function renameDoc(d) {
    prompt2('Rename document', d.title, function (name) {
      if (!name || name === d.title) return;
      api('/docs/' + d.id, { method: 'PATCH', body: { title: name } })
        .then(refresh).catch(function (err) { if (!err.auth) toast(err.message, true); });
    });
  }

  function renameFolder(f) {
    prompt2('Rename folder', f.name, function (name) {
      if (!name || name === f.name) return;
      var dst = parentOf(f.path) ? parentOf(f.path) + '/' + name : name;
      if (f.ghost) {
        S.ghosts = S.ghosts.map(function (p) { return p === f.path ? dst : p; });
        if (S.cwd === f.path) S.cwd = dst;
        renderTree(); renderCrumbs(); renderList();
        return;
      }
      api('/folder/rename', { method: 'POST', body: { from: f.path, to: dst } })
        .then(function (j) {
          if (S.cwd === f.path || S.cwd.indexOf(f.path + '/') === 0) S.cwd = dst + S.cwd.slice(f.path.length);
          toast(j.moved + ' document' + (j.moved === 1 ? '' : 's') + ' moved.');
          renderCrumbs(); return refresh();
        })
        .catch(function (err) { if (!err.auth) toast(err.message, true); });
    });
  }

  function deleteFolder(f) {
    if (f.ghost) {
      S.ghosts = S.ghosts.filter(function (p) { return p !== f.path; });
      if (S.cwd === f.path) S.cwd = parentOf(f.path);
      renderTree(); renderCrumbs(); renderList();
      return;
    }
    api('/folder/delete', { method: 'POST', body: { path: f.path } })
      .then(function () { if (S.cwd === f.path) S.cwd = parentOf(f.path); return refresh(); })
      .then(function () { renderCrumbs(); })
      .catch(function (err) {
        if (err.auth) return;
        // 🔴 A folder here is not a container that can be emptied by deleting it: it exists
        // BECAUSE documents are in it. Saying so beats a generic failure.
        toast(err.message, true);
      });
  }

  function newFolder(parent) {
    prompt2('New folder', '', function (name) {
      if (!name) return;
      var path = parent ? parent + '/' + name : name;
      if (S.ghosts.indexOf(path) < 0) S.ghosts.push(path);
      S.open[parent || ''] = true;
      go(path);
      toast('Folder created here. It exists for everyone once a document is in it.');
    });
  }

  function moveDialog(ids) {
    var opts = [{ path: '', label: 'No folder (top level)' }].concat(
      allFolderPaths().map(function (f) { return { path: f.path, label: f.path }; }));
    modal({
      title: 'Move ' + ids.length + ' document' + (ids.length === 1 ? '' : 's'),
      bodyHtml: '<div class="kb-field"><label>Destination folder</label>'
        + '<select class="kb-input" id="kbMoveTo">'
        + opts.map(function (o) { return '<option value="' + o.path + '">' + o.label + '</option>'; }).join('')
        + '</select></div>',
      confirm: 'Move',
      onConfirm: function (root, close) { moveDocs(ids, $('#kbMoveTo', root).value); close(); }
    });
  }

  // --- document viewer ------------------------------------------------------------------------
  function openDoc(id, highlightOrd) {
    api('/docs/' + id).then(function (j) {
      var d = j.doc, tab = 'text';
      var m = modal({
        title: d.title,
        headExtra: d.filename
          ? '<a class="btn sm" href="' + API + '/file/' + d.id + '">Download original</a>' : '',
        bodyHtml: '<div class="kb-tabs"><button data-t="text" class="on">Text</button>'
          + '<button data-t="passages">Passages (' + (j.passages || []).length + ')</button>'
          + '<button data-t="history">History (' + d.revisions + ')</button></div>'
          + '<div id="kbDocBody"></div>',
        confirm: 'Save changes',
        onConfirm: function (root, close) {
          var ta = $('#kbDocText', root);
          if (!ta) { close(); return; }
          api('/docs/' + d.id, { method: 'PATCH',
            body: { body: ta.value, generation: d.generation, note: 'Edited in the library' } })
            .then(function () { close(); toast('Saved. It is re-indexed already.'); return refresh(); })
            .catch(function (err) {
              if (err.auth) return;
              // 🔴 The typed text is NOT thrown away on a conflict: the modal stays open with it.
              toast(err.message, true);
            });
        }
      });
      var body = $('#kbDocBody', m.root);
      function paint() {
        body.innerHTML = '';
        if (tab === 'text') {
          var meta = el('p', 'meta');
          // 🔴 WHO last changed it, not only when. "updated 14 Sep" answers half the question
          // somebody is actually asking when they find a document that disagrees with them.
          meta.innerHTML = '<b>' + (d.folder || 'No folder') + '</b> · ' + d.chunks + ' passage'
            + (d.chunks === 1 ? '' : 's') + ' · ' + d.embedded + ' with meaning search'
            + '<br>added by <b>' + esc(who(d.owner) || 'unknown') + '</b> on ' + fmtDate(d.created_at)
            + ' · last edited by <b>' + esc(who(d.updated_by) || who(d.owner) || 'unknown')
            + '</b> on ' + fmtDate(d.updated_at)
            + ' · ' + d.revisions + ' earlier version' + (d.revisions === 1 ? '' : 's')
            + (d.state_note ? ' · <b>' + d.state_note + '</b>' : '');
          body.appendChild(meta);
          var ta = el('textarea', 'kb-input'); ta.id = 'kbDocText'; ta.value = d.body || '';
          ta.style.minHeight = '46vh';
          body.appendChild(ta);
        } else if (tab === 'passages') {
          body.appendChild(hint('These are the passages the retriever ranks: what an answer can '
            + 'actually quote. A passage with no vector is findable by wording only.'));
          (j.passages || []).forEach(function (p) {
            var box = el('div', 'kb-passage' + (highlightOrd === p.ord ? ' hit' : ''));
            box.appendChild(el('span', 'pn', 'Passage ' + (p.ord + 1)
              + (p.embedded ? '' : ' · wording only')));
            box.appendChild(document.createTextNode(p.text));
            body.appendChild(box);
            if (highlightOrd === p.ord) setTimeout(function () { box.scrollIntoView({ block: 'center' }); }, 30);
          });
        } else {
          body.appendChild(hint('Every version is kept. Restoring one is itself an edit, so the '
            + 'version you are replacing is kept too.'));
          var ul = el('ul', 'kb-revs');
          (d.revision_list || []).forEach(function (r, i) {
            var li = el('li');
            // An assistant edit names BOTH: the AI drafted it, a person approved it and it ran
            // as their change. Recording only one of those would misrepresent who is answerable.
            li.innerHTML = '<b>' + fmtDate(r.at) + '</b> · '
              + (r.via === 'assistant'
                 ? 'drafted by the assistant, approved by <b>' + esc(who(r.by) || 'unknown') + '</b>'
                 : 'edited by <b>' + esc(who(r.by) || 'unknown') + '</b>')
              + (r.note ? ' · ' + esc(r.note) : '');
            var b = el('button', 'btn sm', 'Restore this version');
            b.style.marginLeft = '8px';
            b.onclick = function () {
              api('/docs/' + d.id + '/restore', { method: 'POST', body: { index: i } })
                .then(function () { m.close(); toast('Restored.'); return refresh(); })
                .catch(function (err) { if (!err.auth) toast(err.message, true); });
            };
            li.appendChild(b);
            ul.appendChild(li);
          });
          if (!(d.revision_list || []).length) ul.appendChild(el('li', null, 'No edits yet.'));
          body.appendChild(ul);
        }
        m.root.querySelectorAll('.kb-tabs button').forEach(function (b) {
          b.classList.toggle('on', b.dataset.t === tab);
        });
      }
      m.root.querySelectorAll('.kb-tabs button').forEach(function (b) {
        b.onclick = function () { tab = b.dataset.t; paint(); };
      });
      if (highlightOrd != null) tab = 'passages';
      paint();
    }).catch(function (err) { if (!err.auth) toast(err.message, true); });
  }
  window.kbOpenDoc = openDoc;

  function hint(text) { var p = el('p', 'kb-hint', text); return p; }

  // --- modal plumbing --------------------------------------------------------------------------
  function modal(opts) {
    var ovl = el('div', 'kb-ovl');
    var box = el('div', 'kb-modal');
    var head = el('header');
    head.appendChild(el('h3', null, opts.title));
    if (opts.headExtra) { var x = el('span'); x.innerHTML = opts.headExtra; head.appendChild(x); }
    var close = el('button', 'btn sm', '✕');
    head.appendChild(close);
    box.appendChild(head);
    var body = el('div', 'body');
    body.innerHTML = opts.bodyHtml || '';
    box.appendChild(body);
    var foot = el('footer');
    var cancel = el('button', 'btn', 'Cancel');
    foot.appendChild(cancel);
    if (opts.confirm) {
      var ok = el('button', 'btn gold', opts.confirm);
      ok.onclick = function () { opts.onConfirm(box, done); };
      foot.appendChild(ok);
    }
    box.appendChild(foot);
    ovl.appendChild(box);
    document.body.appendChild(ovl);
    function done() { ovl.remove(); document.removeEventListener('keydown', onKey, true); }
    function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); done(); } }
    document.addEventListener('keydown', onKey, true);
    close.onclick = done; cancel.onclick = done;
    ovl.onclick = function (e) { if (e.target === ovl) done(); };
    var first = box.querySelector('input,textarea,select');
    if (first) { first.focus(); if (first.select) first.select(); }
    return { root: box, close: done };
  }
  window.kbModal = modal;

  function prompt2(title, value, cb) {
    modal({
      title: title,
      bodyHtml: '<div class="kb-field"><input class="kb-input" id="kbP" value="'
        + esc(value).replace(/"/g, '&quot;') + '"></div>',
      confirm: 'OK',
      onConfirm: function (root, close) { var v = $('#kbP', root).value.trim(); close(); cb(v); }
    });
    var inp = $('#kbP');
    if (inp) inp.onkeydown = function (e) {
      if (e.key === 'Enter') { var v = inp.value.trim(); $('.kb-ovl').remove(); cb(v); }
    };
  }

  // --- new document ------------------------------------------------------------------------------
  function newDoc() {
    var kinds = (window.KB_KINDS || ['note']).map(function (k) {
      return '<option value="' + k + '"' + (k === 'note' ? ' selected' : '') + '>' + k + '</option>';
    }).join('');
    modal({
      title: 'New document',
      bodyHtml: '<div class="kb-row2">'
        + '<div class="kb-field"><label>Title</label><input class="kb-input" id="kbNT" placeholder="Rate card rationale"></div>'
        + '<div class="kb-field"><label>Type</label><select class="kb-input" id="kbNK">' + kinds + '</select></div>'
        + '</div>'
        + '<div class="kb-field"><label>Folder</label><input class="kb-input" id="kbNF" value="'
        + esc(S.cwd === '/' ? '' : S.cwd) + '" placeholder="Media plans/Q4"></div>'
        + '<div class="kb-field"><label>Text</label>'
        + '<textarea class="kb-input" id="kbNB" placeholder="Paste or write. Blank lines separate '
        + 'the passages the retriever ranks, so write in paragraphs."></textarea></div>',
      confirm: 'Add to the library',
      onConfirm: function (root, close) {
        var body = $('#kbNB', root).value;
        if (!body.trim() && !$('#kbNT', root).value.trim()) { toast('Give it a title or some text.', true); return; }
        api('/docs', { method: 'POST', body: {
          title: $('#kbNT', root).value, body: body,
          folder: $('#kbNF', root).value, kind: $('#kbNK', root).value,
          client: S.level === 'client' ? S.client : '' } })
          .then(function (j) {
            close();
            toast(j.index.semantic ? 'Added and searchable.'
              : 'Added. Searchable by wording; meaning search is still building.');
            return refresh();
          })
          .catch(function (err) { if (!err.auth) toast(err.message, true); });
      }
    });
  }

  // --- upload ---------------------------------------------------------------------------------
  function uploadFiles(files) {
    if (!files || !files.length) return;
    var host = $('#kbUploads');
    Array.prototype.slice.call(files).forEach(function (f) {
      var row = el('div', 'kb-up');
      row.appendChild(el('div', 'nm', f.name));
      var st = el('div', 'st', 'uploading…'); row.appendChild(st);
      var bar = el('div', 'bar'); var fill = el('i'); bar.appendChild(fill); row.appendChild(bar);
      host.appendChild(row);

      var fd = new FormData();
      fd.append('file', f);
      fd.append('folder', S.cwd === '/' ? '' : S.cwd);
      fd.append('client', S.level === 'client' ? S.client : '');
      var xhr = new XMLHttpRequest();
      xhr.open('POST', API + '/upload');
      xhr.upload.onprogress = function (e) {
        if (!e.lengthComputable) return;
        fill.style.width = Math.round(e.loaded / e.total * 100) + '%';
        if (e.loaded >= e.total) st.textContent = 'reading and indexing…';
      };
      xhr.onload = function () {
        fill.style.width = '100%';
        var j = {}; try { j = JSON.parse(xhr.responseText); } catch (e) {}
        if (xhr.status === 401) {
          st.className = 'st err';
          st.innerHTML = 'Signed out. <a href="/">Sign in again</a>, then drop it once more.';
          return;
        }
        if (!j.ok) {
          st.className = 'st err';
          st.textContent = (j.failed && j.failed[0] && j.failed[0].error) || j.error || 'Upload failed';
          return;
        }
        var d = j.docs[0] || {};
        st.textContent = d.import_note ? d.import_note
          : (d.state === 'searchable' ? 'searchable' : 'searchable by wording');
        setTimeout(function () { row.remove(); }, d.import_note ? 9000 : 2600);
        refresh();
      };
      xhr.onerror = function () { st.className = 'st err'; st.textContent = 'Upload failed'; };
      xhr.send(fd);
    });
  }

  // --- global keys + drag target ----------------------------------------------------------------
  document.addEventListener('keydown', function (e) {
    if ($('.kb-ovl') || /input|textarea|select/i.test((e.target.tagName || ''))) return;
    if (e.key === 'F2' && S.sel.length === 1) {
      var d = S.docs.filter(function (x) { return x.id === S.sel[0]; })[0];
      if (d) { e.preventDefault(); renameDoc(d); }
    } else if (e.key === 'Delete' && S.sel.length) {
      e.preventDefault(); deleteDocs(S.sel);
    } else if (e.key === 'Backspace' && !S.archived) {
      e.preventDefault();
      if (S.cwd) go(S.cwd === '/' ? '' : parentOf(S.cwd));
      else if (S.level === 'client') goClients();
      else if (S.level === 'clients') goRoot();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
      e.preventDefault(); S.sel = S.docs.map(function (d) { return d.id; }); paintSel();
    } else if (e.key === 'Escape') {
      S.sel = []; paintSel();
    } else if (e.key === '/') {
      e.preventDefault(); $('#kbSearch').focus();
    }
  });

  function wireDropZone() {
    var zone = $('#kbList'), ovl = $('#kbDrop'), depth = 0;
    ['dragenter', 'dragover'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        if (!(e.dataTransfer.types || []).some(function (t) { return t === 'Files'; })) return;
        e.preventDefault();
        if (ev === 'dragenter') depth++;
        ovl.classList.add('on');
      });
    });
    zone.addEventListener('dragleave', function () { if (--depth <= 0) { depth = 0; ovl.classList.remove('on'); } });
    zone.addEventListener('drop', function (e) {
      if (!e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault(); depth = 0; ovl.classList.remove('on');
      uploadFiles(e.dataTransfer.files);
    });
    // A drop anywhere else must not make the browser navigate to the file.
    ['dragover', 'drop'].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
        if ((e.dataTransfer.types || []).some(function (t) { return t === 'Files'; })) e.preventDefault();
      });
    });
    $('#kbList').addEventListener('click', function (e) {
      if (e.target === zone || e.target.classList.contains('kb-icons')) { S.sel = []; paintSel(); }
    });
  }

  // --- boot ---------------------------------------------------------------------------------------
  function boot() {
    $('#kbNew').onclick = newDoc;
    $('#kbNewFolder').onclick = function () { newFolder(S.cwd === '/' ? '' : S.cwd); };
    $('#kbUpload').onclick = function () { $('#kbFile').click(); };
    $('#kbFile').onchange = function () { uploadFiles(this.files); this.value = ''; };
    $('#kbSearch').oninput = function () {
      S.q = this.value.trim();
      clearTimeout(S.qt);
      S.qt = setTimeout(function () { loadList(); }, 220);
    };
    document.querySelectorAll('.kb-viewtog button').forEach(function (b) {
      b.classList.toggle('on', b.dataset.v === S.view);
      b.onclick = function () {
        S.view = b.dataset.v;
        localStorage.setItem(LS + 'view', S.view);
        document.querySelectorAll('.kb-viewtog button').forEach(function (x) {
          x.classList.toggle('on', x.dataset.v === S.view);
        });
        renderList();
      };
    });
    var ask = $('#kbAskBtn');
    // Guarded: the explorer must work whether or not the Ask panel's script loaded.
    if (ask) ask.onclick = function () { if (window.kbAsk) window.kbAsk.open(); };
    wireDropZone();
    renderCrumbs();
    refresh().catch(function (err) { if (!err.auth) toast(err.message, true); }).then(function () {
      // Deep link from a dashboard citation (kb_bridge): /kb/?doc=<id> opens that document.
      try {
        var want = new URLSearchParams(location.search).get('doc');
        if (want && /^[A-Za-z0-9_-]{3,64}$/.test(want)) openDoc(want);
      } catch (e) {}
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.kbState = S;
})();
