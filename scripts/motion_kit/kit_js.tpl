<script>
/* ===================== BB MOTION KIT v1 - engine (presentation only) =====================
   Canonical source: scripts/motion_kit/ (re-apply with scripts/apply_motion_kit.py).
   Everything below is aesthetics. It reads the DOM the render functions produced and re-times how
   it ARRIVES; it never computes, formats or alters a value. The two places it touches rendered
   output both restore the exact original string / inline style:
     - bar reveal : stashes the inline width, sets 0%, puts the SAME string back next frame
     - count-up   : animates a parsed copy, and the final frame writes the ORIGINAL text back
   If either mechanism is switched off the dashboard is unchanged, which is the test to apply to
   anything added here. Self-contained: one IIFE, one global (window.bbMotion).                */
(function(){
  var doc = document, root = doc.documentElement;
  /* Claim the flag FIRST. The head bootstrap gives the page 3.5s to reach this line and un-hides
     every surface if it never does, so this assignment is what proves the engine is alive. */
  var api = {};
  window.bbMotion = api;

  var REDUCED = false;
  try { REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch(e){}

  /* ---- 1. count-up on figures ----------------------------------------------------------
     STRICTLY conservative: only a leaf element whose WHOLE text is one number with optional
     affixes ("$12,480", "1.8%", "-4.2pp") is animated, and the last frame writes the original
     string back verbatim - so whatever the render function produced is what ends up on screen,
     character for character. Anything it cannot parse is left completely alone. */
  var NUM_RE = /^([^0-9-]*)(-?[0-9][0-9,]*(?:\.[0-9]+)?)([^0-9]*)$/;
  function countUp(el){
    if (REDUCED || el.dataset.bbCount || el.children.length) return;
    var raw = el.textContent;
    if (!raw || raw.length > 26) return;
    var m = raw.trim().match(NUM_RE);
    if (!m) return;
    var target = parseFloat(m[2].replace(/,/g, ''));
    if (!isFinite(target) || Math.abs(target) > 1e12) return;
    el.dataset.bbCount = '1';
    var dec = (m[2].split('.')[1] || '').length;
    var grouped = m[2].indexOf(',') >= 0;
    function fmt(v){
      var s = Math.abs(v).toFixed(dec);
      if (grouped){ var p = s.split('.'); p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); s = p.join('.'); }
      return m[1] + (v < 0 ? '-' : '') + s + m[3];
    }
    var dur = 700, t0 = performance.now();
    (function step(now){
      var p = Math.min(1, (now - t0) / dur);
      var e = 1 - Math.pow(1 - p, 4);                 /* out-quart, matches the CSS easing */
      if (p < 1){ el.textContent = fmt(target * e); requestAnimationFrame(step); }
      else { el.textContent = raw; }                  /* the exact original string, always */
    })(t0);
  }
  var COUNT_SEL = '.kpi .value,.stat .v,.stat-card .v,.stat-card .sv,.stat .cnt';

  /* ---- 2. bars extend from zero -------------------------------------------------------
     No per-client selector list: a bar is recognised STRUCTURALLY - an inline percentage width,
     on a span/div, whose own class says "fill" or whose parent is a bar/track/meter/gauge. The
     page chrome (topbar, control-bar, toolbar) is excluded by name because those also contain
     "bar". Worst case for a false positive is a 1s animation to the identical value. */
  function isBar(el){
    var t = el.tagName;
    if (t !== 'SPAN' && t !== 'DIV' && t !== 'I' && t !== 'B') return false;
    var w = el.style && el.style.width;
    if (!w || w.indexOf('%') < 0) return false;
    var cls = '' + (el.className || '');
    var p = el.parentNode;
    var pc = '' + ((p && p.className) || '');
    if (/topbar|toolbar|navbar|control-bar|sidebar|tabbar/i.test(pc)) return false;
    return /fill/i.test(cls) || /bar|track|meter|gauge/i.test(pc);
  }
  function growBars(scope, pending){
    if (REDUCED) return;
    var n = 0;
    var all = scope.querySelectorAll('span[style*="width"],div[style*="width"],i[style*="width"],b[style*="width"]');
    for (var i = 0; i < all.length; i++){
      var el = all[i];
      if (el.dataset.bbBar || !isBar(el)) continue;
      /* a document-wide sweep must not touch a bar whose surface has not been revealed yet -
         that one belongs to reveal(), so it grows when the card is actually seen */
      if (pending && el.closest('[data-bb-reveal]:not(.bb-in)')) continue;
      var w = el.style.width;
      el.dataset.bbBar = '1';
      el.classList.add('bb-bar');
      el.style.transitionDelay = Math.min(n * 35, 260) + 'ms';
      el.style.width = '0%';
      n++;
      (function(node, width){
        requestAnimationFrame(function(){ requestAnimationFrame(function(){ node.style.width = width; }); });
      })(el, w);
    }
  }

  /* ---- 3. Chart.js replays its entry animation when scrolled to -----------------------
     Charts are built when their tab renders, which for anything below the fold means the
     animation finished before it was ever seen. reset()+update() replays it once, the first time
     that canvas is actually on screen. A canvas that is not a Chart.js chart is left alone. */
  function replayChart(cv){
    if (cv.dataset.bbPlayed || REDUCED) return;
    if (typeof Chart === 'undefined' || !Chart.getChart) return;
    var c;
    try { c = Chart.getChart(cv); } catch(e){ return; }
    if (!c) return;                                   /* not built yet - a later scan gets it */
    cv.dataset.bbPlayed = '1';
    try { c.reset(); c.update(); } catch(e){}
  }

  /* ---- 4. the observer that drives all of it ------------------------------------------ */
  var REVEAL_SEL = '.card,.kpi,.panel-box,.chartbox,.stat-card,.stat,.ccard,.icon-tile,' +
                   '.tablewrap,.crm-callout,.ai-note,.info-note,.compare-strip';
  var io = null;
  function reveal(el){
    el.classList.add('bb-in');
    if (io) io.unobserve(el);
    growBars(el);
    var f = el.querySelectorAll(COUNT_SEL); for (var i = 0; i < f.length; i++) countUp(f[i]);
    var cs = el.querySelectorAll('canvas');  for (var j = 0; j < cs.length; j++) replayChart(cs[j]);
  }
  function onIntersect(entries){
    for (var i = 0; i < entries.length; i++) if (entries[i].isIntersecting) reveal(entries[i].target);
  }
  function tag(el, i){
    if (el.dataset.bbReveal) return;
    el.dataset.bbReveal = '1';
    /* stagger within the parent row, capped so a long list never crawls in */
    el.style.transitionDelay = Math.min(i * 40, 200) + 'ms';
    if (!io){ reveal(el); return; }
    io.observe(el);
  }
  function isNear(el){
    var r = el.getBoundingClientRect();
    return r.bottom > -80 && r.top < (window.innerHeight + 80) && r.width > 0;
  }
  var sweepT = null, queued = false;
  function scan(){
    queued = false;
    var seen = new Map(), els = doc.querySelectorAll(REVEAL_SEL);
    for (var i = 0; i < els.length; i++){
      var el = els[i], k = el.parentNode, n = seen.get(k) || 0;
      seen.set(k, n + 1);
      tag(el, n);
    }
    /* charts and figures that live OUTSIDE a tagged surface still get their moment */
    var cs = doc.querySelectorAll('canvas');
    for (var j = 0; j < cs.length; j++) if (!cs[j].closest('[data-bb-reveal]') && isNear(cs[j])) replayChart(cs[j]);
    /* Bars a filter change just re-rendered INSIDE an already-revealed surface: that surface will
       never intersect again, so pick them up here. ONE document-wide query, not one per surface -
       on a 1,000-row table the per-surface version walked the same subtree dozens of times.
       `dataset.bbBar` makes it a no-op for everything already handled. */
    growBars(doc, true);
    clearTimeout(sweepT); sweepT = setTimeout(sweep, 1000);
  }
  function schedule(){ if (!queued){ queued = true; requestAnimationFrame(scan); } }

  /* WATCHDOG - the safety net for the reveal idea. A second after any scan, anything still
     unrevealed but sitting in the viewport is shown unconditionally. If this ever fires it is
     papering over a bug, and the dashboard still reads. */
  function sweep(){
    var st = doc.querySelectorAll('[data-bb-reveal]:not(.bb-in)');
    for (var i = 0; i < st.length; i++){
      var el = st[i];
      if (el.offsetParent === null) continue;          /* in a hidden tab - genuinely off screen */
      if (!isNear(el)) continue;
      reveal(el);
    }
  }

  /* ---- 5. one scroll handler: masthead state + the top rail ---------------------------
     rAF-coalesced, and it only writes a class and a transform - no layout reads beyond
     scrollY/scrollHeight, so it cannot make scrolling janky on the long tabs. */
  function scrollFx(){
    var raf = false, rail = doc.getElementById('bbProgress'), sweepQ = false;
    function onScroll(){
      if (raf) return; raf = true;
      requestAnimationFrame(function(){
        raf = false;
        var y = window.scrollY || 0;
        if (doc.body) doc.body.classList.toggle('bb-scrolled', y > 24);
        if (rail){
          var max = Math.max(1, root.scrollHeight - window.innerHeight);
          rail.style.transform = 'scaleX(' + Math.min(1, y / max) + ')';
        }
        /* scrolling is also when a straggler becomes visible, so re-arm the watchdog */
        if (!sweepQ){ sweepQ = true; setTimeout(function(){ sweepQ = false; sweep(); }, 120); }
      });
    }
    window.addEventListener('scroll', onScroll, {passive:true});
    window.addEventListener('resize', onScroll, {passive:true});
    onScroll();
  }

  function init(){
    scrollFx();
    if ('IntersectionObserver' in window){
      /* threshold 0, NOT a fraction: threshold is the share of the ELEMENT that is visible, so a
         card taller than the viewport (a 1,000-row table) can never reach 6% and would sit at
         opacity 0 forever. Any intersecting pixel is the correct trigger. */
      io = new IntersectionObserver(onIntersect, {rootMargin:'0px 0px -3% 0px', threshold:0});
    }
    scan();
    /* These dashboards re-render whole sections on every filter change, so re-scan on DOM change
       rather than editing dozens of render functions. childList only + one rAF coalesce: the
       tables are large and this must never turn into per-row work. */
    if ('MutationObserver' in window && doc.body){
      new MutationObserver(schedule).observe(doc.body, {childList:true, subtree:true});
    }
    window.addEventListener('load', schedule);
  }
  api.scan = schedule;
  api.sweep = sweep;
  try{
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init); else init();
  }catch(e){
    /* if the engine itself cannot start, make sure nothing stays hidden */
    root.className = (' ' + root.className + ' ').replace(' bb-motion ', ' ').trim();
  }
})();
</script>
