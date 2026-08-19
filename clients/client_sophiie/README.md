# client_sophiie — Sophiie AI (PREVIEW, no data)

Sophiie AI (sophiie.ai) is a **100% Digital** client: an AI receptionist and back-office product for
trades and service businesses — it answers their calls 24/7, books jobs, sends quotes and invoices,
schedules crews and follows up with customers. The paid-social offer is a **free trial** (secondary:
book a demo), so the campaign outcome is a trial start / demo booking.

**Status: PREVIEW.** Their Meta campaigns are still being **built**. There is **no
Windsor/Snowflake/BigQuery data for this client**, and this folder deliberately ships **no `sql/`, no
`job/`, no `create_views.py`, no `seed_static.py`, no `scheduler.ps1`, and no BigQuery dataset**. The
dashboard renders a baked-in sample payload behind a "Data coming soon" banner — the same play used
for Geyer Valmont, Bell Shakespeare and Next Smile Australia, and for Caltex before its Trade Desk
data landed.

Everywhere the data pipeline will eventually plug in is marked `TODO(sophiie)`.

Cloned from `client_geyervalmont` (itself the geocon Meta template), then **re-skinned onto the
aurora design**. The model, filters, charts and export paths are the shared Meta lead-gen ones; the
skin is unique in the estate.

## File map

| Path | What it is |
|---|---|
| `dash/dashboard.html` | The whole UI, one file. Overview · Paid Media · Creative tabs, plus **the three-layer aurora background**. |
| `dash/main.py` | Flask password gate + static server. Serves `/data.json`, `/logo.png`, `/bb_deck.js`, `/report`. Its `LOGIN_HTML` carries a CSS-only aurora (no canvas). |
| `dash/placeholder.json` | The SAMPLE payload (`meta.placeholder=true`). Generated — never hand-edit. |
| `dash/marble-*.jpg` | The three marble textures, baked into the image and served by `main.py` from a name whitelist. Referenced RELATIVELY in CSS so they resolve behind the proxy. |
| `dash/logo.png` | Sophiie's **supplied mark** (the headset) - a copy of `creatives/sophiie_logo.png`, baked into the image. |
| `dash/report.py` | AI deck generator, prompts re-templated for Sophiie's business. **Dormant** until `/report` is enabled. |
| `dash/platform_sso.py`, `dash/bb_deck.js` | Vendored, unchanged from the template. |
| `gen_placeholder.py` | Builds `dash/placeholder.json` from `targets/*.csv`. Deterministic (`random.seed(42)`). |
| `creatives/` | The **supplied artwork**, version-controlled: `sophiie_logo.png` (the client's mark) and `100digital_light.jpg` (the agency mark, mirrored from `bidbrain-platform/Creatives/`). Both are inlined as base64 into `dash/dashboard.html`. |
| `targets/targets.csv`, `targets/budget.csv` | Committed targets. **All `PENDING`** — no signed media plan yet. |
| `deploy_sophiie.ps1` | One-shot preview standup (service only — no dataset/job/scheduler). |
| `dash/deploy_dash_sophiie.ps1` | Redeploy just the service after a UI edit. |

## The skin: Chronicle - marble, over the aurora

Two layers of identity, applied in that order:

**Chronicle - marble** (2026-08-18) is an EDITORIAL PRINT treatment: a display serif for titles, a
monospace for every measured figure, and a very pale marble texture on a small number of surfaces.
It began as a hairline-divided slab; the client reversed that on the same day, so the panels are now
separated, rounded and lifted on shadow with no borders anywhere (see "The KPI tiles"). It replaced a skin that read
"competent but generic SaaS". **Applied to the Overview tab; Paid Media and Creative inherit the type
and tokens but have not had their own pass yet.**

**The aurora** underneath survives, TONED DOWN to roughly a third of its former intensity at the
client's request ("too overpowering"). It is still the client's signature and still animates.

### Type

**ONE face: Inter Variable (2026-08-19, client request).** The previous three-face Chronicle stack
(Fraunces italic display + Inter UI + IBM Plex Mono figures) was rejected, so the whole dashboard and
the login page are now set in a single family:

```css
font-family: 'Inter Variable', Inter, system-ui, sans-serif;
```

Loaded as one variable request carrying every weight and both italics:
`fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900`.

| Role | Where | Note |
|---|---|---|
| Display (`--f-display`) | Page + section + card titles, campaign and stage names, the ONE modelled KPI figure | `font-style:italic` was REMOVED with Fraunces - italic Inter on a heading reads as a mistake, not a choice |
| UI (`--f-ui`) | Labels, eyebrows, body copy, tabs, chips, table headers | unchanged |
| Figures (`--f-mono`) | Every number that represents a measurement | **`font-variant-numeric:tabular-nums` is now load-bearing** - alignment used to come free from a mono face, and Inter is proportional |

The three tokens are **REMAPPED onto the one stack, not renamed** (the house pattern - see the colour
tokens below), so all ~40 consumers changed with no per-rule edit and the roles stay legible if a
second face is ever reintroduced. Verified in a browser: 262 rendered elements, exactly ONE computed
family, 14 Inter faces loaded, no console errors.

**No weight above 500 anywhere** - hierarchy is size, face and colour. The old build ran to 800 and
that heaviness was most of why it read generic. A sweep pulled 24 stray `600/700/800` rules down to
500; adding one back re-introduces the thing this direction removed.

### Where the marble goes - and where it must not

Exactly **five surfaces** on Overview: the **masthead** (`marble-band.jpg`), the **sample-data
notice**, the **eight-cell KPI slab**, the **budget-pacing panel** and the **"on track to goal?"
panel** (all `marble-cell.jpg`). `marble-tile.jpg` is used only for the Creative tab's fallback tiles.

Two later additions, both deliberate extensions of the five:

- **Paid Media panel title bands.** `#tab-paid .card::before` paints a marble band across the
  TITLE area only, MASKED with a `linear-gradient` so it fades out completely before the table or
  the plot begins - the rule that texture must never sit behind dense data still holds, and the
  data still sits on clean paper. The white wash is baked in as a first background layer rather
  than a second pseudo-element, so it needs no extra DOM and cannot fight `.card.marble`'s
  `::after`. Different crop per panel, same reason the eight KPI tiles differ.
- **The login card** (`dash/main.py` `LOGIN_HTML`) uses `marble-cell.jpg` at a .42 wash, so the
  login reads as the dashboard's front door rather than a different product. It carries the full
  type stack too - since 2026-08-19 that means Inter Variable throughout, title and
  password field alike. The aurora there is CSS-only (orbs + bands, no
  canvas): a login page should render instantly and has no business running a rAF loop.

**It must NOT go behind** the funnel-stage table, the delivery-over-time chart, the funnel bar list,
the donut, the tab bar or the filter row. Texture behind dense data is where this design gets cheap -
that is the one failure mode to avoid, and `.card.marble` is opt-in precisely so it cannot creep.

**Two independent levers.** The ASSET controls how much vein exists (three exports of the same slab,
each amplified for the size it renders at - band least, tile most; one file for all three jobs makes
the small crops go flat). The CSS `--wash` controls how much you let through, and it is the volume
knob: **raise** the percentage to make the marble quieter. Never past ~55%, beyond which it stops
reading as stone and just looks like dirty white. Current washes: masthead .36, notice .46, KPI cells
.40 (the modelled cell .30), pacing .44, goal .50.

Each of the eight KPI cells gets a **different `background-position`** - repeating veins across a grid
is the tell that it is a texture file rather than a material.

### The control bar

Sticky, solid, rounded and lifted like every other surface, with a **marble band behind the TAB RAIL
only**, masked so it is gone before the filter row - the same discipline as the Paid Media title
bands. Controls need a calm field to read against, so the row carrying the date picker, the chips and
the search box stays clean paper.

It carries four pieces of state beyond the filters themselves:

- **`activeFilters()`** is the single source of truth for whether anything is filtered. Both the Reset
  button's visibility AND its count read from it, so the two can never disagree.
- **Reset** appears only when at least one filter is on, and shows how many. It clears the date range,
  the stage and the search in one go. It needs `DateRange.reset()` - the picker had no public setter,
  and re-running `init()` would re-bind every handler.
- **The scope readout** answers "what am I actually looking at?": the honest row count after all three
  filters, plus the span and the campaigns still in play. It is the cheapest guard against a filter
  being left on and a partial number being read as the whole account.
- **Keyboard**: `/` focuses the search from anywhere, `Escape` clears and blurs it. Both are guarded so
  they never fire while the user is typing into another field.

`renderControlState()` is in the `render()` list, so the readout and the Reset state can never drift
from the data on screen.

### The centred masthead

The OPENING block of every tab - eyebrow, display title, dek - is centred, and so is the goal caption
directly beneath it (with a rule either side; a single leading rule reads as an accident once
centred). Everything after that stays left-aligned: a centred masthead over left-aligned body is the
standard editorial structure, and it keeps the tiles and tables scanning normally. The dek needs
`margin-left/right:auto` as well as `text-align:center`, because it carries a `max-width` and would
otherwise centre its text inside a left-hugging box.

### The KPI tiles

Eight tiles in a 4x2 grid, **separated by whitespace, rounded (`--radius` 14px) and lifted on shadow
with no outline at all**. They were briefly one hairline-divided slab; the client asked for separated
rounded tiles instead (2026-08-18), which also removed every panel border across the dashboard - a
rule around each panel reads as a wireframe rather than as a surface.

Elevation is two tokens and two steps only, `--elev-1` at rest and `--elev-2` on hover, both in the
same ink hue so a shadow never looks blue or muddy. Every tile, card, insight and creative card lifts
on hover (`translateY(-3px)`, or -2px for the large panels, where 3px reads as the page twitching).

**Any element painting a wash or a texture over a rounded surface needs `border-radius: inherit` on
its `::after`**, or the overlay paints square corners over the rounded tile. `.kpi`, `.card.marble`,
`.pholder` and `.cc-fallback` all do this.

**One tile still reads differently**: "Qualified leads (modelled)", because it is the only MODELLED
figure on the page. It used to carry that distinction with 34px Fraunces italic; with the single-face
stack (2026-08-19) only its SIZE now sets it apart, so do not also strip the size. It used to
carry a 2px ink left border as well; that went when the corners were rounded, since a one-sided
border on a rounded corner always looks like a mistake. The serif figure plus a slightly deeper rest
shadow now carry it alone. **Do not extend this to another tile**; if every tile is special, none are.

**The modelled tile has no foot line.** It carried both a badge and a "pending target 120 - 30% of
enquiries" line, which made it taller than every other tile and forced row 1 to out-size row 2.
`kpiCard` now omits an empty `.sub` entirely rather than rendering `&nbsp;` (a blank foot line
still takes a line box, which was the actual cause). Nothing is lost: the same target and rate are
stated on the pacing panel's goal bars and again in the "How to read this" note.

**Label heights are reserved on purpose.** `.kpi .label` has `min-height:27px` (two lines) and
`letter-spacing:.18em` rather than .24em: at 4-up, a label like "QUALIFIED LEADS (MODELLED)" wraps,
and without the reserved height the tiles in a row went ragged and the values stopped sharing a
baseline.

### Two cascade traps this restyle hit (both cost a render to find)

1. **A breakpoint declared before the base rule it overrides simply loses.** The KPI slab's
   `repeat(4,1fr)` sits further down the stylesheet than the media query did, so at 680px it stayed
   4-up. All breakpoints now live in one block at the END of the stylesheet - keep new ones there.
2. **Same for `.grid`.** A `gap:1px` override placed near `.container` lost to the original
   `.grid{gap:16px}` further down, and the 16px gaps showed the slab background as a grey band. Patch
   the base rule, not a copy of it.

### Do not "tidy up" the legacy token names

`--accent`, `--panel`, `--muted`, `--leads`, `--qualified` and friends are read by ~600 CSS rules AND
by the JS `MC` map that colours every chart. Chronicle **remaps** them onto the ink ramp rather than
renaming them, which is what kept this a CSS change. Renaming them without editing the JS blanks the
chart palette. One side effect to know: `--accent` now resolves to near-black, so any chart using it
as a FILL went ink-black (the placement bars and the lead-type donut did; both were repointed to a
light/dark blue pair). Check any new chart fill against that.

## The aurora skin — the layer underneath

This is **the only dashboard in the estate with an animated background**, and it is the point of the
design rather than decoration. Three fixed, `pointer-events:none`, `z-index:0` layers, bottom to top:

| Layer | What | Where |
|---|---|---|
| 1 | **Ambient orbs** — four 45–60vw radial gradients at `blur(120px)`, drifting on 18–25s cycles | `.aurora-ambient` (CSS only) |
| 2 | **Diagonal light bands** — five wide rectangles rotated −15°..−22°, six-stop blue gradients, 10–15s drift | `.aurora-diagonals` (CSS only) — **the signature; it mirrors sophiie.ai's own background** |
| 3 | **Curtains** — ~24 vertical strips swaying on layered sine waves, drawn as filled polygons | `#aurora-bg` `<canvas>` + the `auroraCurtains()` IIFE at the bottom of `dashboard.html` |

Every piece of page chrome sits at `z-index:1`. Cost is one `requestAnimationFrame` loop plus CSS
keyframes on nine fixed divs — it never touches layout, so it cannot reflow the dashboard.

**Tuning it: alpha and strip COUNT are the dials - never darkness.** The first attempt at
"desaturating" the aurora darkened its hues, and ~27 overlapping semi-transparent dark curtains plus
five dark bands accumulated into a grey-brown wash over the warm `#EFEEEB` shell - the page looked
dirty. The palette must stay LIGHT-mid and COOL, close to the shell's own luminance; subtlety comes
from lower alpha and from **fewer strips** (the curtain count went from `W/55` to `W/105`, the
cheapest way to cut accumulation). Saturation is safe; darkness is not.

The aurora has now been through three settings: the original (saturated cyan, "too overpowering"),
a very quiet pass, and the current one - colour and motion back up, still short of the original.
Current dials: orb/band alphas ~.28-.48, curtain count `W/75`, curtain opacity `0.13+0.17`, sway
amplitude `30+66`, and the canvas time step `time += 0.027` - deliberately near the top of the
usable range, because the client asked twice for more visible movement (0.004 reads as static;
past ~0.035 it competes with the data). Durations are ~55% shorter than the quiet pass and the
orb/band travel distances were roughly doubled, which is what actually makes the motion legible -
a slow keyframe over a short distance reads as still no matter how high the alpha.

**Four rules that will break this design if ignored** (they are also written into the `:root` block):

1. **The aurora is the only background.** Content surfaces stay **solid white**, lifted on shadow
   with no border, and carry **no `backdrop-filter`**. A translucent or blurred card sitting over moving
   light shimmers, and reads as a rendering fault rather than a style. The sticky `.control-bar` is
   solid white for the same reason — translucent, the curtains slide under the tab labels.
2. **The palette is ~90% blue/cyan.** `--a-teal` and `--a-pink` are HINTS that separate one chart
   series from another — never fields, never a card background.
3. **Text on an accent fill is WHITE** (`--on-accent`). Sophiie's blue is dark enough to carry it.
   This is the **opposite** of the lime-brand clients (`geyervalmont`), whose `--on-accent` is ink —
   do not paste an "ink on accent" rule in from one of those files.
4. **Everything stops under `prefers-reduced-motion`.** The CSS query freezes the orbs and bands (it
   does not hide them — the static wash is still the brand), and the canvas `remove()`s itself in JS
   so no animation frame is ever scheduled.

Two more, specific to this file:

- **`time += 0.012` in `draw()` is tuned, not arbitrary.** Around `0.004` the curtains look static and
  the whole idea is lost; much above `0.02` they distract from the data.
- **Each diagonal band repeats its own `rotate()` in EVERY keyframe.** A transform is one property, so
  a frame that omits the rotation snaps the band flat mid-animation.

### Branding

Sophiie's own brand kit (sophiie.ai/brand-kit). The tokens live in one `:root` block at the top of
`dash/dashboard.html`; the login page in `dash/main.py` mirrors them as literals.

| Token | Hex | Role |
|---|---|---|
| `--accent` | `#2b84b4` | Sophiie primary blue. Fills, active chips, the hero series. |
| `--accent2` | `#206387` | Secondary blue. The **text** accent — links, eyebrow labels. |
| `--deep` | `#140934` | Brand deep navy. Dark chips, the active filter pill, chart tooltips, the logo tile. |
| `--ink` | `#111827` | Body text, headings, tables. |
| `--muted` | `#475569` | Secondary text (Sophiie's own gray-600). |
| `--on-accent` | `#FFFFFF` | Text placed **on** an accent fill. |

Typography is **Inter** — Sophiie's actual brand face — one family, 300–800, no second face.
Chart series order is blue → purple → cyan → teal (`CHART_SERIES`); funnel stages are cyan
(Awareness) → blue (Traffic) → purple (Conversion) → pink (Retargeting), matched to the filter chips.

### There is deliberately NO accent-stroke chart plugin

`geyervalmont` and `resetdata` register a Chart.js plugin that gives their lime/citron datasets a
hairline, because those fills vanish on a white plot. Sophiie's `#2b84b4` reads fine as a bare fill,
so that plugin was **removed** rather than ported. If you copy a chart in from one of those files,
drop its `borderColor` override instead of importing the plugin — and remember the repo-wide Chart.js
v4 rule: a plugin is **registered** (`Chart.register`), never parked in `options.plugins.*`, which is
treated as a scriptable option, auto-invoked, and silently blanks the whole chart.

### Four template defects fixed here (do not re-import them)

The Meta scaffold this was cloned from carries light-theme bugs inherited from a dark-themed
ancestor. All four are fixed in this file; if you diff against `client_geyervalmont` you will see them:

1. **Invisible target lines.** The dashed CPL / CPL-stretch / CTR target markers on the efficiency map
   and the CPL trend were stroked in `rgba(255,255,255,.28–.32)` — on a white plot they never drew at
   all. Now `rgba(17,24,39,.34–.38)`.
2. **Invisible chart tooltips.** `Chart.defaults.plugins.tooltip.backgroundColor` was a dark navy while
   `titleColor`/`bodyColor` were the page ink — dark on dark. Here the panel is `--deep` and the text
   is explicitly white.
3. **Stray palette leftovers.** Sage-green spend bars (`rgba(90,138,110,.62)`) and warm-orange area
   fills under blue/purple lines, from the geocon/Bell ancestor.
4. **`Be BELL-specific`** in `report.py`'s Stage A prompt — a Bell Shakespeare leftover that survived
   two clones.

### The marks ship twice, on purpose

Two supplied marks are in play: **Sophiie's own** (the headset - navy band, two cyan discs) and
**100% Digital's** (the green boxed wordmark, mirrored from `bidbrain-platform/Creatives/`). Each
appears in two places:

- **Inlined as base64** in `dashboard.html`'s topbar - because the dashboard is also served through
  the platform reverse proxy at `/d/sophiie/`, where a root-relative asset path does not resolve (the
  cloudflare lesson). Sophiie's mark is inlined a second time, in the stylesheet, as the
  `.cc-fb-mark` background for creative-gallery fallback tiles - once in CSS rather than once per
  card.
- **As `dash/logo.png`** (Sophiie's mark only), COPY'd by the Dockerfile and served at `/logo.png` for
  the login page, the favicon (`href="logo.png"` - **relative**, so it resolves proxied too) and the
  AI deck builder.

**Neither file has an alpha channel** - Sophiie's is an indexed PNG on a white field and 100%
Digital's is a JPEG - so a bare `<img>` laid over the moving aurora reads as a stray white rectangle.
Both therefore sit on a **white chip** at the panel radius (`.smark`, `.agency-chip`), which makes the
white deliberate and matches every other surface in the skin. On the login page, whose card is already
white, Sophiie's mark needs no chip and no glow - just size.

If the artwork changes, update all three copies: `creatives/sophiie_logo.png` (the committed source),
`dash/logo.png`, and the base64 in `dashboard.html`. There is no generator script - an earlier
`gen_logo.py` fabricated a placeholder mark and was deleted once the real artwork arrived, because its
only remaining effect would have been to overwrite it.

## Gotcha: the platform proxy needs to read this client's password

`dashboards.bidbrain.ai/d/sophiie/` proxies this dashboard and **logs into it on the user's behalf**
(`bidbrain-platform/dash/main.py` → `_upstream_pw` → `_upstream_login`). So `platform-dash-web@`
needs `roles/secretmanager.secretAccessor` on `sophiie-dash-password`. Without it the portal tile's
"Open preview →" returns a bare **500 Internal Server Error** — `PermissionDenied: 403
secretmanager.versions.access` in the platform-dash logs, and **nothing in this client's own logs**,
because the request never reaches this service.

`deploy_sophiie.ps1` grants it, along with the god-mode pair (`secretVersionAdder` on the password +
`iam.serviceAccountUser` on the web SA) that lets the super-admin console reveal/rotate the password.
`sophiie` was also added to `$CLIENTS` in `scripts/enable_super_admin.ps1`, which is where those
god-mode grants are maintained centrally.

**If a new client's tile 500s, check this binding first** — it is not a code bug.

## Preview mechanism

Identical to Geyer Valmont / Bell Shakespeare / Next Smile — nothing here is bespoke:

- `dash/placeholder.json` carries `meta.placeholder = true`. That flag is the **only** tell.
- `main.py`'s `/data.json` prefers the real object in the GCS bucket and falls back to the baked-in
  placeholder. The bucket is created **empty**, so today the fallback always wins.
- `renderPlaceholderBanner()` shows the "Data coming soon" banner and flips the topbar pill from
  "Live · Meta paid social" to "Building · sample data".
- **The banner clears itself.** Real data has no `placeholder` flag, so the moment an export job
  writes `sophiie.json` into the bucket the dashboard switches over with **no code change and no
  redeploy**.

The sample is Sophiie-shaped: four funnel stages, ad sets split by **trade vertical** rather than
geography, trial-start / demo-booking copy paraphrased from Sophiie's own public positioning, a
male-skewed 25–54 audience, and a **current, mid-flight window** so every pacing card reads "in
progress" (the Bell/Next Smile placeholders were seeded with a window that has since ended, which
reads as "flight over" on every pacing card — `md/AGENTS.md` lists that as one of their go-live
blockers, so it was not worth inheriting). It is tuned to land just inside its CPL and CTR targets, so
the vs-target logic renders in its healthy state.

## Data contract (TODO — this is the shape the pipeline must emit)

`sql/*.sql` view column → `job/main.py` env dict key → `dashboard.html` `data.*` key, matched **by
name**. None of the first two exist yet; `gen_placeholder.py` is the written-down contract in the
meantime. Top-level keys: `meta`, `flight`, `benchmarks`, `targets`, `rows[]`, `breakdowns[]`.

`rows[]` is per date × campaign × adset × ad: `spend`, `impressions`, `reach`, `clicks`,
`link_clicks`, `lpv`, `leads`, `leads_website`, `leads_onfacebook`, `video_3s_views`,
`video_completes`, `thruplays`, plus `stage` (Awareness / Traffic / Conversion / Retargeting, which
must match `STAGE_COLORS`) and the creative fields. `breakdowns[]` is `age_gender` + `placement`.

**One deliberate rename from the template:** the lead goal is `flight_lead_target`, not
`monthly_lead_target`. Every consumer — the KPI sub-label AND the cumulative "on track to goal?"
chart — treats it as a **whole-flight** number, so the template's key name was simply wrong. Keep it
as `flight_lead_target` when you build `seed_static.py`.

**Channel set is the template default (Meta).** Confirm the media mix when the plan lands; the UI is
driven by what the payload contains, so channels follow the pipeline, not an HTML edit.

**Qualified leads are MODELLED**, not measured: `qualification_rate_target` (0.30) × Meta-reported
enquiries. Meta cannot see trial-to-paid conversion, so the dashboard says so on screen and
`report.py` is explicitly forbidden from asserting a trial-to-paid rate, LTV, CAC or payback. Wire a
CRM / product-analytics feed before treating that tile as an actual.

## FLIPPING PREVIEW → LIVE

Do these in order. Steps 1–4 are the work; 5–8 are the flip.

1. **Confirm the media plan**: flight dates, budget, lead target, CPL target. Replace the `PENDING`
   rows in `targets/targets.csv` + `targets/budget.csv` with the signed numbers, update the three
   flight constants at the top of `gen_placeholder.py` to match, then re-run
   `.\.venv\Scripts\python.exe clients\client_sophiie\gen_placeholder.py` so the sample can never
   contradict the seed.
2. **Confirm the channels.** If the mix is not Meta-only, the cloned Meta model does not fit as-is —
   fix the model before the UI (see the client rows in `md/AGENTS.md` for the multi-channel patterns).
3. **Get data flowing** into the raw layer: `raw_windsor.perf_meta`, plus a
   `raw_windsor.sophiie_meta_breakdown` table for the audience/placement charts (Bell Shakespeare
   ships `ingest/meta_breakdown_pull.py` for exactly this and can be copied). **Verify the campaigns
   actually exist in the raw table before building anything on top of them** — and note the standing
   estate issue: the Windsor **Meta** grant has lapsed before, so check the connector is authed.
4. **Build the pipeline**: BigQuery dataset `client_sophiie`, `sql/` views, `seed_static.py`,
   `create_views.py`, `job/` (vendor `job/freshness.py` — the export job must be self-gating on a
   `*/10` tick per the freshness contract), and the scheduler. Copy Bell Shakespeare's or geocon's,
   the nearest complete Meta examples. **Never key a view off a raw campaign name** — strip any
   brief-number prefix into `CAMPAIGN_NAME_NORM` first (`md/AGENTS.md`).
5. **Run the job once** with `FORCE_REBUILD=1`. It writes `sophiie.json` to
   `gs://bidbrain-analytics-sophiie-dash`. The dashboard picks it up and the sample banner clears on
   its own — **no dashboard edit, no redeploy**.
6. **Set the dashboard password** so the client can log in: either set it in the super-admin console
   (which reveals + rotates), or grant their Google/Microsoft email to this dashboard in that
   console's sign-in access panel. Do **not** hand out the 100% Digital agency password — it opens
   every other 100% Digital client.
7. **Flip the tile**: in `bidbrain-platform/dash/set_sophiie_tile.py` set `STATUS = "active"`,
   `NOTE = ""` and the campaign tuple's status to `"active"`, then run it with `--yes`. Make the same
   change in `bidbrain-platform/dash/config.py` (the source of truth in code) so a future re-seed
   doesn't revert it. This is exactly the path `set_caltex_tile.py` took.
8. **Register it for monitoring and sync**: add `sophiie` to **`BQ_CLIENTS`** in
   `status_dashboard/job/main.py` (it is Meta-sourced, so it belongs in the BigQuery-native list, NOT
   the Snowflake one) and remove it from the "NOT YET MONITORED" comment there; add
   `"sophiie-export"` to `_SYNC_EXPORT_JOBS` in `bidbrain-platform/dash/main.py` so the Overview's
   **"Sync all dashboards now"** button covers it — **not before the job exists**, because the Run
   Admin API 404s an unknown job and that lands the button in a permanent red failure. Add it to
   `SLIDES_CLIENTS` if the AI deck is wanted, and enable `/report` with
   `dash/enable_report_sophiie.ps1` (needs `roles/aiplatform.user`), which is dormant until then.

Finally, update this client's row in `md/AGENTS.md` (reports / currency / views / gotchas) in the
same change — that table is the repo's index and a stale row is worse than none.
