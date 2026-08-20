
  /* ==========================================================================
     BB MOTION KIT v1 - PURE PRESENTATION, NO DATA PATH.
     Canonical source: scripts/motion_kit/ (re-apply with scripts/apply_motion_kit.py).
     Do NOT hand-edit this block in a dashboard - edit the template and re-run, or the
     next run overwrites you.

     Four things live here and nothing else:
       1. the ambient wash  - slow brand-tinted light drifting behind the page
       2. one interaction vocabulary - hover / press / keyboard-focus for everything clickable
       3. surfaces - cards lift and pick up the brand glow under the cursor
       4. the scroll-reveal system - surfaces fade up, CSS bars extend from zero, KPI figures
          count up, charts replay their entry animation (driven by the engine at the end of the page)

     It is deliberately the LAST block in the stylesheet so it wins the cascade over the rules
     it re-times. Every animation is switched off wholesale under prefers-reduced-motion at the
     bottom, and the reveal state is scoped to `html.bb-motion` - a class the head bootstrap adds
     and REMOVES again if the engine never boots, so a JS failure can never leave data invisible.

     GEOMETRY USES `translate` / `scale`, NEVER the `transform` shorthand. Several dashboards
     already set a transform on a chip, a close button or a caret, and the shorthand would
     replace it and make the element jump. The individual properties compose with an existing
     transform instead, which is what makes this block safe to drop on any theme unseen.
     ========================================================================== */
  /* The reveal offset and the hover lift are composed inside ONE `translate` (see part 3), which
     means both have to be NON-INHERITING or a hovered card drags every nested surface up with it -
     the cursor sits on the card's own padding and the inner tile visibly detaches. `@property`
     with inherits:false is exactly the tool for that; where it is unsupported the properties
     inherit again and the only consequence is that cosmetic drift, never a broken layout. */
  @property --bb-rev{syntax:"<length>";inherits:false;initial-value:0px}
  @property --bb-hov{syntax:"<length>";inherits:false;initial-value:0px}
  :root{
    /* one easing vocabulary - premium motion is mostly ONE curve used everywhere */
    --bb-ease:cubic-bezier(.22,1,.36,1);          /* out-quint: fast out, long settle */
    --bb-ease-soft:cubic-bezier(.4,0,.2,1);
    --bb-accent:$ACCENT;
    --bb-glow:$GLOW;
    --bb-lift:$LIFT;
  }
  html{scroll-behavior:smooth}

  /* ---------- 1. THE AMBIENT WASH ----------
     Three big soft brand-coloured orbs drifting on their own slow cycles. CSS only: no canvas,
     no requestAnimationFrame, transform-only keyframes, and NO filter:blur() - a radial gradient
     that fades to transparent is already soft, and a full-viewport blur is re-applied every frame
     the layer paints (measured at -58fps on a machine without GPU acceleration).
     It sits at z-index:-1 so not one line of the page's own stacking has to be touched. That
     needs `html` to stop painting: with html transparent the BODY background propagates to the
     canvas (CSS backgrounds spec) and is painted first, leaving this layer between the page
     colour and the content. Every dashboard in the estate carries its background on body. */
  html{background:transparent}
  .bb-fx{position:fixed;inset:0;z-index:-1;pointer-events:none;overflow:hidden}
  .bb-fx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-fx .o1{width:58vw;height:50vh;top:-12%;left:-8%;animation:bbOrb1 $D1 ease-in-out infinite;
    background:radial-gradient(circle,rgba($ORB1) 0%,transparent 68%)}
  .bb-fx .o2{width:50vw;height:44vh;top:4%;right:-10%;animation:bbOrb2 $D2 ease-in-out infinite;
    background:radial-gradient(circle,rgba($ORB2) 0%,transparent 68%)}
  .bb-fx .o3{width:54vw;height:50vh;bottom:-16%;left:12%;animation:bbOrb3 $D3 ease-in-out infinite;
    background:radial-gradient(circle,rgba($ORB3) 0%,transparent 66%)}
  @keyframes bbOrb1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(76px,58px) scale(1.09)}}
  @keyframes bbOrb2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-70px,52px) scale(1.08)}}
  @keyframes bbOrb3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(62px,-72px) scale(1.07)}}

  /* ---------- 2. ONE INTERACTION VOCABULARY ----------
     Everything clickable: a 1px rise on hover, a real press on :active (nothing feels cheaper
     than a button that does not depress), and a visible ring for keyboards. The blanket
     `button`/`select` entries carry the TRANSITION only - never geometry - because a button can
     be anything, including something already positioned with a transform. */
  .tab,.chip,.chips button,.seg button,.pill,.btn,.tag,.qtr-chip,.dp-btn,.dp-nav,.dp-day,
  .dp-presets a,.dp-actions button,.dp-apply,.dp-cancel,.export-btn,.chip-action,.campaign-btn,
  .cl-item,.cl-group-toggle,.drillback,.cdrop,.basis-toggle,.dash-select,.compare-select,
  button,select,summary{
    transition:background-color .2s var(--bb-ease-soft),color .2s var(--bb-ease-soft),
               border-color .2s var(--bb-ease-soft),box-shadow .26s var(--bb-ease),
               opacity .2s var(--bb-ease-soft),filter .2s var(--bb-ease-soft),
               translate .16s var(--bb-ease),scale .12s var(--bb-ease)}
  .tab:hover,.chip:hover,.chips button:hover,.pill:hover,.btn:hover,.tag:hover,.qtr-chip:hover,
  .seg button:not(.on):hover,.dp-btn:hover,.export-btn:hover,.campaign-btn:hover,
  .chip-action:hover,.drillback:hover,.cdrop:hover,.basis-toggle:hover,.dash-select:hover,
  .dp-nav:hover:not(:disabled){translate:0 -1px}
  .tab:active,.chip:active,.chips button:active,.pill:active,.btn:active,.tag:active,
  .qtr-chip:active,.seg button:active,.dp-btn:active,.dp-day:active,.dp-presets a:active,
  .dp-actions button:active,.export-btn:active,.campaign-btn:active,.chip-action:active,
  .drillback:active,.cdrop:active,.basis-toggle:active{translate:0 0;scale:.97}
  .btn:hover,.dp-apply:hover,.export-btn:hover,.chip.on:hover,.seg button.on:hover{
    box-shadow:0 8px 20px -12px var(--bb-glow);filter:brightness(1.05)}
  .chip:not(.on):hover,.tag:hover{box-shadow:0 6px 16px -12px var(--bb-glow)}
  .dp-presets a{transition:background-color .18s var(--bb-ease-soft),color .18s,padding-left .18s var(--bb-ease)}
  .dp-presets a:hover{padding-left:15px}
  /* disabled things must not pretend to be pressable */
  [disabled]:hover,[aria-disabled="true"]:hover,.disabled:hover{translate:none;filter:none;box-shadow:none}
  /* keyboard focus is a first-class state, not an afterthought. No border-radius here on
     purpose - `outline` already follows the element's own corners. */
  a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible,
  summary:focus-visible,[tabindex]:focus-visible,.tab:focus-visible,.chip:focus-visible,
  .pill:focus-visible,.dp-day:focus-visible,.dp-presets a:focus-visible{
    outline:2px solid var(--bb-accent);outline-offset:2px}

  /* ---------- 3. SURFACES ----------
     The reveal offset and the hover lift are composed through TWO VARIABLES inside one `translate`,
     never by two rules fighting over the same declaration. They would always be an unfair fight:
     the reveal rule has to be scoped to `html.bb-motion` (see part 4), which outranks a plain
     `.card:hover`, so a hover lift written as `translate:0 -2px` silently lost to
     `translate:none` on every revealed card and the lift simply never happened. */
  .card,.kpi,.panel-box,.chartbox,.stat-card,.stat,.ccard,.icon-tile,.tablewrap{
    translate:0 calc(var(--bb-rev,0px) + var(--bb-hov,0px));
    transition:translate .32s var(--bb-ease),box-shadow .32s var(--bb-ease),
               border-color .32s var(--bb-ease-soft)}
  .card:hover,.kpi:hover,.panel-box:hover,.stat-card:hover,.ccard:hover,.icon-tile:hover{
    --bb-hov:-2px;box-shadow:var(--bb-lift);
    border-color:color-mix(in srgb,var(--bb-accent) 30%,$LINE)}
  /* Figures that count up are tabular, or the digits change width mid-animation and the whole
     row twitches. Applies to the resting state too, so columns of numbers line up. */
  .kpi .value,.stat .v,.stat-card .v,.stat-card .sv,.stat .cnt{font-variant-numeric:tabular-nums}

  /* Tables: the hovered row tints and its label cell picks up an accent edge. The tint is on the
     ROW, never on the cells - a cell that paints its own background (a heat table, a coloured
     delta) has to keep it. */
  tbody tr{transition:background-color .16s var(--bb-ease-soft)}
  tbody tr:hover{background:$ROWHOVER}
  tbody tr:hover td:first-child{box-shadow:inset 3px 0 0 var(--bb-accent)}

  /* The masthead sinks a shadow in once the page has scrolled under it (class from the engine). */
  .topbar{transition:box-shadow .3s var(--bb-ease)}
  body.bb-scrolled .topbar{box-shadow:$BARSHADOW}

  /* ---------- 4. SCROLL REVEAL ----------
     The engine tags surfaces with [data-bb-reveal] and adds .bb-in on first intersection. The
     hidden half is scoped to html.bb-motion: drop that class and every surface is visible again,
     which is exactly what the head bootstrap does if the engine never reports in. */
  html.bb-motion [data-bb-reveal]{--bb-rev:14px;opacity:0;
    translate:0 calc(var(--bb-rev,0px) + var(--bb-hov,0px));
    transition:opacity .55s var(--bb-ease),translate .42s var(--bb-ease),
               box-shadow .32s var(--bb-ease),border-color .32s var(--bb-ease-soft)}
  html.bb-motion [data-bb-reveal].bb-in{--bb-rev:0px;opacity:1}
  /* Bars extend to their width instead of appearing at it. The engine stashes the inline width,
     paints 0%, and restores the SAME string one frame later - no arithmetic, so a bar can never
     land anywhere but where the render function put it. */
  .bb-bar{transition:width .95s var(--bb-ease)}

  /* Scroll rail: a 2px brand line across the very top that fills as you read. Long dashboards
     hide how much is left; this is the cheapest possible answer and it never covers content. */
  #bbProgress{position:fixed;top:0;left:0;height:2px;width:100%;z-index:80;transform-origin:0 50%;
    transform:scaleX(0);pointer-events:none;background:linear-gradient(90deg,$RAIL)}

  /* Thin themed scrollbars - the default chrome ones are the last un-themed surface. */
  *::-webkit-scrollbar{width:10px;height:10px}
  *::-webkit-scrollbar-track{background:$SBTRACK}
  *::-webkit-scrollbar-thumb{background:$SBTHUMB;border-radius:8px;
    border:2px solid transparent;background-clip:padding-box}
  *::-webkit-scrollbar-thumb:hover{background:$SBTHUMBH;background-clip:padding-box}

  /* ---------- PRINT: nothing may be invisible on paper ----------
     Printing uses the styles computed RIGHT NOW - it does not re-run the observer - so without
     this a card that had not been scrolled to would print as a blank box. These dashboards do get
     printed and PDF'd, which makes this the one place the reveal could destroy a deliverable.
     The wash and the rail come off the page too: ink on white, not a brand glow. */
  @media print{
    .bb-fx,#bbProgress{display:none !important}
    [data-bb-reveal],[data-bb-reveal].bb-in{--bb-rev:0px !important;--bb-hov:0px !important;
      opacity:1 !important;transition:none !important}
    .bb-bar,.card,.kpi,.panel-box,.chartbox,.stat-card,.stat,.ccard,.icon-tile,.tablewrap{
      transition:none !important}
  }

  /* ---------- Reduced motion: stop ALL of it ----------
     The head bootstrap never adds `bb-motion` here, so nothing is hidden in the first place;
     these rules kill the drifting light and the hover geometry as well. */
  @media (prefers-reduced-motion: reduce){
    .bb-fx span{animation:none !important}
    /* zero the two offset variables rather than the `translate` property: that keeps any
       transform a client rule already put on the element, and un-hides every surface */
    :root,[data-bb-reveal],[data-bb-reveal].bb-in,.card:hover,.kpi:hover,.panel-box:hover,
    .stat-card:hover,.ccard:hover,.icon-tile:hover{--bb-rev:0px !important;--bb-hov:0px !important}
    [data-bb-reveal]{opacity:1 !important;transition:none !important}
    .bb-bar{transition:none !important}
    .card,.kpi,.panel-box,.chartbox,.stat-card,.stat,.ccard,.icon-tile,.tablewrap,
    .tab,.chip,.pill,.btn,.seg button,.dp-btn,button,select{transition:none !important}
    .tab:hover,.chip:hover,.pill:hover,.btn:hover,.dp-btn:hover,.export-btn:hover,
    .campaign-btn:hover,.chip-action:hover,.drillback:hover,.cdrop:hover,.basis-toggle:hover,
    .dash-select:hover,.tag:hover,.qtr-chip:hover,.chips button:hover,
    .seg button:not(.on):hover,.dp-nav:hover:not(:disabled){translate:none !important}
    .tab:active,.chip:active,.pill:active,.btn:active,.seg button:active,.dp-btn:active,
    .dp-day:active,.export-btn:active,.campaign-btn:active{scale:none !important}
  }
  /* BB MOTION KIT v1 ends */
