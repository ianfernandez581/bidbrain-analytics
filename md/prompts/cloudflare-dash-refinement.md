# Cloudflare dashboard — design refinement prompt

Paste-ready prompt for Claude Code. Run from the repo root.
Companion design brief (mockups, token deltas, retention ledger): published artifact
"Cloudflare Dashboard Refinement", 2026-09-07.

Audit baseline: `clients/client_cloudflare/dash/dashboard.html` at 8,741 lines
(CSS 19–1034, body 1054–2121, JS 2122–end). **Line numbers drift as soon as Phase 1
lands — after the first commit, re-locate by selector, not by number.**

---

You are refining the visual design of a production client dashboard. It is already live and a
client uses it weekly. Your job is polish and responsive behaviour — **not** a redesign, and above
all not a reduction.

## FILE

`clients/client_cloudflare/dash/dashboard.html` — single file, 8,741 lines.
CSS lines 19–1034. Body 1054–2121. JS 2122–end.
Read `md/AGENTS.md` first. Use the **impeccable** and **ui-ux-pro-max** skills for the design
decisions.

## THE HARD CONSTRAINT — READ TWICE

Every number, label, note, hint, caption, table column, chart, KPI, chip, filter, select, footer
and dev-only block currently on this page is there because a client needs it. You may restyle
anything. You may not remove, merge, collapse, hide, truncate, summarise, "simplify" or
move-to-a-tooltip **any** piece of information.

Before you start, run and save a baseline:

- count of elements matching every selector in the ledger below
- full text content of each of the 7 panels
- list of all canvas ids

After each phase, re-run and diff. If any count drops or any text string disappears, revert that
phase and report why. Do not proceed with a regression outstanding.

## WHAT MUST SURVIVE (7 tabs, 28 chart canvases, 13 tables)

| Panel | Must retain |
|---|---|
| `#panel-paid` | 10 charts, 5 KPIs, channel + market chips, 6 tables, pacing rows, GA video funnel, GA PMax, LCE, LI funnel |
| `#panel-main` | 11 charts incl. 5 donuts, KPI strip, `#cspdSection` in full (book/vendor picks, totals, week chips, vendor table's 10 columns, reason breakdown), region grid |
| `#panel-compare` | mirrored A/B panels, 4 charts, 8 KPIs, empty states |
| `#panel-qoq` | 2 heat grids, 7 market groups, QTD note, heat scale |
| `#panel-enriched` | 4 KPIs, 2 sortable tables, campaign select |
| `#panel-txdata` | dev-only: notes mount, ids table, pacing table |
| `#view-campaign` | CF1: both sub-tabs, 10 KPIs, 3 charts, 2 tables |
| global | topbar + 6-lane `#dashSelect`, datepicker with presets and custom range, view toggle, `#laneNote`, `#dateScopeNote`, 8 grain segments, aurora, scroll progress, reveal system, PptxGenJS slide export |
| dev gating | `#txDataTab`, `#viewToggle`, `#devCtrls`, `#kpi_unprocessed_stat`, `#leadDetailCard`, `#cspdStale`, `#cspdUnresolved` — must stay hidden from clients |

## WHAT YOU MUST NOT RENAME OR RESTRUCTURE

- **Any id.** There are 300+ and all are `getElementById` targets. The `A_`/`B_` prefixes and the
  `#panel-*` names are string-concatenated in JS (`switchTab` 3085–3090, `switchCmpTab` 8212,
  5858/5871/5892/5913).
- **Any class emitted from a JS `innerHTML` template:** `progress-row, pbar, fill, surplus, gray,
  prog-tgt, prog-badge, reg-row, reg-fill, pace-row, pfill, pace-marker, pace-risk, qoq-heat, hh,
  rlbl, qoq-cell, qd, dev-table, stat, k, v, cnt, kpi, label, value, delta, stripe, delta-pm, pill,
  num, bench, chip, cchip, c-ttd, c-li, c-rd, c-ln, c-ga, dl-chip, fold, cspd-note, rk, rv,
  lce-key, lce-sub, lce-empty, cr-name, seg, wk, svc, total`.
- Any selector in `REVEAL_SEL` / `COUNT_SEL` (8646–8649).
- `.total` — the sort engine reads it as data (8007).
- Bar fills stay **width-based**; `growBars` (8600–8605) writes `el.style.width`. Do not convert to
  `transform`.
- CSS custom properties read from JS via `cssTok`: `--pending`, `--target-gray`, `--purple`,
  `--chan-*`.
- The 21 inline `display:none` attributes — they are JS-managed state.

## PHASE 1 — DE-INLINE (no visual change)

Body 1054–2121 has 103 inline `style` attributes. Move 82 of them to classes; leave the 21
`display:none` ones alone.

Priority, because they block everything else:

1. **Make failure visible before you change anything else.** `html.bb-motion` is applied before
   paint, so every card starts at `opacity:0` until an IntersectionObserver fires, with a 1s sweep
   and a 3.5s boot fallback. Change the resting state to visible and animate up from there. Do this
   **first**: while it stands, any mistake in the phases below *hides* client data; after it, the
   same mistake shows data unstyled. Failing visible beats failing invisible on a client-facing
   page.
2. **Five inline `grid-template-columns` that beat `@media` by specificity:**
   `#enrKpis` 1259 `repeat(4,1fr)`; `#gaVideoKpis` 1825 `repeat(4,1fr)`; `#gaPmaxKpis` 1842
   `repeat(3,1fr)`; `.grid` 2060 `2fr 1fr`; `.grid` 2098 `1fr 1fr`
   → `.kpis-4` / `.kpis-3` / `.grid-2-1` / `.grid-1-1`, all with media rules.
3. **Twelve table wrappers** using inline `overflow:auto` (1273, 1289, 1529, 1785, 1920, 1939,
   1949, 1997, 2010, 2074, 2111) → one `.table-scroll` class, and give each table a `min-width`
   so the wrapper actually triggers instead of crushing columns.
4. Eleven repeats of `margin-top:var(--gap-lg)` → a `--rhythm` rule.
5. `#laneNote` 1218 and `#dateScopeNote` 1220 are identical 9-property banners duplicating
   `.qoq-note` (550) → one `.note-banner` class.
6. `#paid-loading` 1730 and `#paid-error` 1735 duplicate `#loading` (162) and `#error` (167)
   inline, with a white spinner and a hardcoded `#FFD8B8` → delete the inline copies, reuse the
   real classes.
7. Three identical footer recipes (2023, 2076, 2113) → the existing `footer` rule at 462.

Commit as its own change. Verify the page is pixel-identical except where (6) intentionally
corrects the spinner colour.

## PHASE 2 — SCALE DISCIPLINE

`font-size` is already 100% tokenised (93/93) — leave the ladder alone. Fix the three roles it
doesn't cover:

- **Big figures:** 26px (`.kpi .value` 495), 22px (`.cs-snap .stat .v` 260, `.qoq-stats` 554,
  `.compare-kpi` 443) and 18px (`.pace-risk .amt` 421) all serve one role. Collapse to
  `--t-stat`, and reserve `--t-hero` for one lead metric per tab.
- **Titles:** section `h2` is 16px (485) while card `h3` is 14px (266) and `.compare-header h2` is
  18px (430). Make section titles `--t-xl`.
- **Padding:** seven recipes for one card tier (`--pad-card`, `var(--pad-card) 18px`,
  `14px 16px` ×2, `12px 14px` ×2, `11px 12px`) → `--pad-card` everywhere. Table cells: four
  densities → `--pad-cell` (9px 12px) and `--pad-cell-tight` (7px 10px) for `.dev-table`.
- **Gaps:** 38 raw declarations across 12 values → `--s-1…--s-6` plus `--gap`/`--gap-lg`.
  `--s-5` and `--s-6` are already declared and unused.
- **Shadows:** 33 declarations, 21 distinct, 14 bespoke → `--shadow-card`, `--shadow-pop`,
  `--shadow-bar`, `--shadow-glow` (currently declared and never used).
- **Third text tier:** `--muted` (8.08:1 on `--surface`) and `--muted-2` (6.38:1) are only 1.27×
  apart, so the tier does nothing. Move `--muted-2` to about `#9B8878` (~5.1:1) — still AA at
  11px+.
- `--target-gray` is 3.90:1 on `--surface`. Keep it as a bar fill; where it appears as legend
  text, use `--muted-2` with the swatch beside it.
- **Delete only these dead tokens:** `--brand-accent-2`, `--cf-orange-soft`, `--cf-orange-deep`,
  `--chan-purple`, `--li-blue-soft`. Keep every JS-read one.

## PHASE 3 — RESPONSIVE

There are 8 `@media` blocks and only one below 900px (a 560px datepicker rule). Nothing is tuned
for a phone. Add:

- **≤1100px** — `.chart-wrap` heights 240/300/364 → 220/260/300.
- **≤900px** — `.cs-snap .pair` and `.pair.triple` → 1 col (they currently stay 2/3-up inside a
  1-col strip); `.compare-kpis` → 1 col; `.grid-3` → 1 col; `.qoq-heat` →
  `84px 1fr 1fr 60px`; remove the `#bbAurora` canvas and drop `background-attachment:fixed`.
- **≤640px — NEW.** `.topbar .inner` / `.control-tabs` / `.control-right` / `.tabs` currently
  `flex-wrap:wrap` — six tabs wrap to ~4 rows inside a `position:sticky` bar, eating 200px+ of a
  667px viewport. Convert `.tabs` to a `nowrap` `overflow-x:auto` rail with scroll-snap and hidden
  scrollbar. Also: `.kpis` → 2 col; `.progress-row` / `.reg-row` / `.pace-row` →
  `minmax(52px,74px) 1fr auto` (currently 110/96/150px + a 70–150px right column, which leaves
  ~75px of bar); `.chart-wrap` → 200/240/260; container padding 24 → 14px.
- **≤560px** — `.dp-pop` gets `max-height:calc(100dvh - 120px)` and `overflow-y:auto`;
  `.dp-actions` sticky to its bottom. Stacked, it currently runs ~520px tall and Apply falls below
  the fold.
- **print** — add `.panel.hidden{display:block}`; right now only the active tab prints, 6 of 7 are
  silently dropped. Reset `body`'s four-layer near-black gradient to white with dark ink; add
  `@page{margin:14mm}`; `break-inside:avoid` on `.card` and `.kpi`; unclip every `.table-scroll`;
  reset chart heights.

## PHASE 4 — INTERACTION AND CHARTS

- There is **no `:active` state anywhere** in the file against 40+ hover rules. Add one
  `--press: translateY(1px)` vocabulary for `.chip`, `.tab`, `.seg button`, `.cchip`, `.dp-day`,
  `.chip-action`, `.dp-apply`, `.dp-cancel`.
- **Restore focus** where it was killed: `.dash-select:focus` (111), `.compare-select` (435, 450),
  `.dp-custom input:focus` (239) all set `outline:none` with no `:focus-visible` replacement. Also
  `.dp-day` is a `div` with no `tabindex`, so the whole calendar grid is keyboard-unreachable —
  make the days focusable and arrow-navigable.
- Deduplicate the hover rules declared twice (`.chip:not(.on):hover` at 177 and 743;
  `.dp-btn:hover` at 196 and 750; `.dp-day:hover` at 221 and 754).
- **Chart.js global block, 2691–2723** — per-chart options stay untouched, so all 21 construction
  sites inherit:
  - `font.size` 10, `font.weight` 500 (currently unset, so every tick renders at Chart.js's 12px
    default — larger than the 10–11px UI around it)
  - `scale.ticks.padding` 6
  - `scale.ticks.maxRotation` 0 — **but** Chart.js pairs no-rotation with auto-skip, so on the
    vertical-bar charts with long category labels (market and creative names) whole categories can
    be *dropped from the axis* rather than tilted. Add a `ticks.callback` that truncates the label
    to ~14 characters with an ellipsis, so every category still renders. Verify on
    `#marketBar`, `#marketStack`, `#cspdMarketChart` and the creative charts before moving on.
  - `scale.border.color` `var(--line-2)`; grid stays `var(--line)`; `grid.tickLength` 0
  - `tooltip.titleFont`/`bodyFont` 11px Inter; `usePointStyle` true
  - `interaction.mode` `'index'` — set this **per-chart on the bar and line charts only**, not
    globally. Index mode is a cartesian concept and misbehaves on the five doughnut charts
    (`#solChart`, `#countryChart`, `#jfChart`, `#jlChart`, `#jtChart`), which should keep the
    default `nearest`.
  - `layout.padding` `{top:4,right:6}`
  - Read `PALETTE` (2683) from the `--chan-*` tokens via `cssTok` instead of 12 duplicated hexes.
  - Replace `DIM='#5C7187'` in the legend wrapper (2727–2757) and `'#E8EEF6'` in `bbDonutCenter`
    (2764–2795) with `var(--muted-2)` and `var(--ink)` — both are cool blue-greys on a base whose
    own comment says a cool hue reads as a bug.
  - The legend wrapper injects "Click a label to show or hide it" above every legend, 20+ times per
    page. Show it once per tab.
- **Unify states:** 3 empty-state languages (`.compare-empty` 437, `.lce-empty` 612,
  `.cmp-empty-note` 460) → one `.empty-state`, and give the ~20 tables and charts that have none a
  real one. Add sticky headers to `#enrDetailTbl` (it scrolls at `max-height:560px` with a
  non-sticky head).
- Stop `.panel`'s `bbPane` fade (856) replaying on returns to an already-seen tab.
  (The `bb-motion` resting-state fix has moved to Phase 1 — see item 1 there.)

## PHASE 5 — THE ELEVATED VARIANT (optional, behind a flag)

Add a second skin selected by `data-skin="elevate"` on `<html>`, so both ship in one file:

- one off-centre bloom instead of four gradient layers; aurora amplitude reduced
- card shadows → hairlines; `--shadow-card` survives only on the sticky bar and popovers
- radius becomes semantic: `--r-sm` on interactive elements, `2px` on containers
- figures set in a mono face at 500 weight
- orange restricted to action, the primary series and the lead metric; everything else neutral or
  semantic
- a severity rail (`border-left`) on cards needing attention; 1.8% zebra on tables wider than 6
  columns

Do not change the default skin's appearance.

## VERIFY BEFORE YOU REPORT DONE

1. Re-run the baseline diff. Element counts and panel text identical.
2. Screenshot all 7 tabs at 1440, 1024, 768 and 375px. No horizontal body scroll at any width;
   every table either fits or scrolls; no clipped text; no overlapping labels.
3. Confirm all 28 chart canvases render and every chart's axis labels are readable at 375px.
4. Tab through the whole page: visible focus everywhere, calendar reachable.
5. Print preview: all 7 panels present, no near-black background.
6. `prefers-reduced-motion`: no animation, all content visible.
7. Confirm dev-only blocks are still gated.

Report as a table: phase, files touched, what changed visually, what the baseline diff said.
