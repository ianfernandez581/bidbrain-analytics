<script>
/* BB MOTION KIT v1 - bootstrap. Presentation only; canonical source scripts/motion_kit/.
   Runs before anything else on the page and does exactly two things.

   1. Marks <html> so the scroll-reveal CSS (which starts surfaces at opacity 0) can only ever
      apply on a page where JS is alive - and REMOVES that mark again if the engine at the end of
      the body never reports in, or if the page throws at all. Hiding content until an observer
      says so means a missed callback hides DATA, so the failsafes here are the whole reason the
      reveal is safe to ship on 17 dashboards at once: losing the animation is always cheaper
      than losing a number.
   2. One motion vocabulary for Chart.js, set BEFORE any chart is built. Deliberately only the
      timing and geometry keys - every colour, font and per-chart option the dashboard sets later
      still wins, because this runs first. */
(function(){
  var d = document.documentElement;
  function drop(){ d.className = (' ' + d.className + ' ').replace(' bb-motion ', ' ').trim(); }
  try{
    if (!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)){
      d.className = (d.className ? d.className + ' ' : '') + 'bb-motion';
    }
  }catch(e){}
  /* failsafe 1: the engine never ran - a page error above it, a blocked script, an old cached
     shell. Un-hide everything unconditionally. */
  setTimeout(function(){ if (!window.bbMotion) drop(); }, 3500);
  /* failsafe 2: ANY uncaught error on the page stops us hiding content, immediately. */
  window.addEventListener('error', drop);
  try{
    if (window.Chart && Chart.defaults){
      var C = Chart.defaults;
      C.animation.duration = 760;                    /* matches the CSS reveal, so a card and the
                                                        chart inside it settle together */
      C.animation.easing = 'easeOutQuart';
      C.transitions.active.animation.duration = 170; /* hover / legend toggle stays immediate */
      C.hover.animationDuration = 170;
      C.elements.point.hoverRadius = 6;              /* a point that grows under the cursor ... */
      C.elements.point.hitRadius = 8;                /* ... and is easier to actually hit */
      C.plugins.tooltip.cornerRadius = 9;
      C.plugins.tooltip.padding = 10;
      C.plugins.tooltip.caretPadding = 6;
      /* Line TENSION is deliberately left alone: curving between points implies values that were
         never measured, and these are reporting dashboards. Bar borderRadius too - it rounds
         every segment of a stacked bar, which reads as a gap that is not in the data. */
    }
  }catch(e){}
})();
</script>
