# clients/client_cloudflare/dash/ — the Web App (`cloudflare-dash`)

> A **Cloud Run Service** that's always on: a password gate that serves the Cloudflare
> dashboard and proxies the private `cloudflare.json` to authenticated users only.

**Plain English:** the *waiter behind the locked door* for Cloudflare. Same gate as MongoDB —
a login screen, then the dashboard, with the data file fetched from locked storage on the
visitor's behalf. Different branding (Cloudflare orange) and a different data file
(`cloudflare.json`); the security and serving logic are identical.

**Where this sits:** [`../job/`](../job/README.md) writes `cloudflare.json` → **[this app]**
authenticates and serves it at `/data.json` → `dashboard.html` draws the charts.

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The Flask app. Same auth/serve/proxy logic as MongoDB (login-page branding and the default `DATA_OBJECT` = `cloudflare.json` differ), **plus the `POST /feedback` route + the Feedback pill this service injects for DIRECT logins** (see below). |
| [`feedback_widget.py`](feedback_widget.py) | The **Feedback pill for direct logins** — the injected HTML/JS plus the `save()` that writes the note into the **platform's** bucket, so it lands in the existing tracker. Vendored from `bidbrain-platform/dash/feedback.py` (**that file is the source of truth for the record shape** — keep the two in step). |
| [`enable_feedback_cloudflare.ps1`](enable_feedback_cloudflare.ps1) | **One-time** standup for the above: grants the runtime SA create-only write on the platform bucket and sets `PLATFORM_BUCKET` on the service (the switch that makes the pill appear). Idempotent. |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — two program lanes, **"Core DG APJ"** (`core`; renamed from "Core Demand Generation" 2026-08-05) and **"Surround ABM"** (`surround_abm`, brief 2193, split out 2026-08-14), plus three single-campaign LinkedIn dashboards, and a **disabled "Core DG EMEA - coming soon"** placeholder in the lane dropdown. ~3,900 lines (HTML + CSS + inline JS). Fetches `/data.json` once and renders everything client-side. |
| [`DASHBOARD.md`](DASHBOARD.md) | **How `dashboard.html` was built** from Cloudflare's original `index.html`: three small `<script>` edits to read one private `/data.json` instead of two public R2 files. Read this if you re-derive the page from a new design. |
| [`LIVE_URL.md`](LIVE_URL.md) | The upstream `…run.app` URL, the front-door access path (`dashboards.bidbrain.ai/d/cloudflare/`), and how to re-fetch the URL. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim` + gunicorn, non-root, copies `main.py`, `platform_sso.py`, `report.py`, `feedback_widget.py`, `dashboard.html`, `bb_deck.js`. **A new module has to be added to that `COPY` line or the import fails at boot.** |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run deploy cloudflare-dash` → re-apply `--no-invoker-iam-check`. |
| [`requirements.txt`](requirements.txt) | `Flask`, `gunicorn`, `google-cloud-storage`. |
| `.dockerignore` | Keeps the build context lean. |

---

## Routes & security

Identical to the MongoDB service — see [that README](../../client_mongodb/dash/README.md#routes-mainpy)
for the route table. In short: `GET /` (login or dashboard), `POST /login` (constant-time
check), `GET /logout`, `GET /data.json` (**401 unless authenticated**, then streams the private
object), `GET /healthz`. Session cookie is `HttpOnly` + `Secure` + `SameSite=None`, 12-hour
lifetime, not domain-pinned. `SameSite=None` (requires `Secure`) is needed because the dashboard
is embedded as a cross-origin iframe under `dashboards.bidbrain.ai` — `Lax` would drop the session
cookie there. The bucket stays private; the public `…run.app` URL only ever shows the password
screen.

### Feedback pill on DIRECT logins (2026-08-20, Transmission request)

The front-door injects a Feedback pill into every dashboard it proxies, so anyone arriving via
`dashboards.bidbrain.ai/d/cloudflare/` has always had one. **Cloudflare's own people mostly open
this service directly on its `…run.app` URL** — their office network does not resolve
`dashboards.bidbrain.ai` (see the platform README) — and a direct hit never passes through that
proxy, so the client company had no way to send feedback at all. This service now carries its own
pill: `POST /feedback` in `main.py` plus [`feedback_widget.py`](feedback_widget.py).

- **Where notes go:** the **platform's** private bucket, `feedback/cloudflare/<ts>-<id>.{json,webm,jpg}`,
  in the platform's own record shape — so they appear in the existing tracker at
  `dashboards.bidbrain.ai/feedback/admin` and get the same lazy AI transcript/summary pass, with
  **no platform-side change**. Tagged `user_kind` **`client-direct`**, which is how you tell a
  direct submission from a front-door one.
- **Only one pill ever draws.** The widget stands down when it finds itself under `/d/` (the proxy
  appends its own copy *after* this script, so mounting there would give two), and its ids are
  scoped `#bbfbn-*` against the platform's `#bbfb-*` so the two can never collide. Behind the
  front-door, nothing here changes.
- **`PLATFORM_BUCKET` is the switch.** Unset => no pill is injected **and** the route 503s, so the
  button can never appear without somewhere to store what it collects. Set it once with
  [`enable_feedback_cloudflare.ps1`](enable_feedback_cloudflare.ps1); it survives image swaps.
- **The IAM grant is create-only** (`roles/storage.objectCreator`), not `objectAdmin`. Without
  `storage.objects.delete` this SA cannot overwrite anything already in the platform bucket — not
  the registry, not another client's notes — and every object it writes has a fresh unique name,
  so it never needs to. **Don't widen it.**
- The form field the widget posts as `client` is **ignored**: the key is pinned to `cloudflare`
  server-side, so a caller cannot file a note into another client's folder.
- `MAX_CONTENT_LENGTH` was raised from 256 KB to audio+image+256 KB (a 2-minute voice note plus a
  JPEG screenshot), matching the allowance the platform makes for the same widget.
- `cloudbuild.yaml` uses `--set-env-vars`, which **replaces** the whole env, so `PLATFORM_BUCKET` is
  listed there too. Anything a future `enable_*.ps1` sets out-of-band needs the same treatment.

**Copying this to another client** (mongodb, schneider, …): copy `feedback_widget.py`, the
`POST /feedback` route, the import + `MAX_CONTENT_LENGTH` bump + the `</body>` splice in `main.py`,
add the module to the `Dockerfile` `COPY` line, and run the enable script with `$SERVICE`/`$SA` and
the pinned client key changed. Nothing on the platform side needs to know.

#### "Could not send" is almost always an EXPIRED SESSION, not a broken widget (2026-08-26)

Transmission reported the pill failing with *"could not send, try again"* and moved the feedback to
Teams. It was not the widget: `POST /feedback` was returning **401/403 because the session was gone**.
This tab's session is a **hard 12h cap** (`PERMANENT_SESSION_LIFETIME` in `main.py`) - Flask re-sends
the cookie on each request but never re-signs it, so activity does **not** slide it - and an
already-rendered dashboard keeps looking perfectly healthy, because its 5-min `/data.json` poll
swallows the failure in a bare `catch(_){}`. So the failing Feedback button was the only symptom the
client ever saw, and "please try again" is advice that can never work for an auth failure.

What the pill now does about it, in both this widget and the platform's (keep the two in step):

- **`GET /feedback/ping`** - the same two checks as `POST /feedback`, in the same order, so the probe
  and the real post can never disagree. Called when the panel **opens**, on tab **re-focus**, and
  every 10 min, so a tab that died overnight **flags itself**: amber ring on the pill + a tooltip.
- **A 401 is handled as its own case:** the panel says you are signed out and links to the login page.
  Sign in there, come back, press Send - the note goes. Any other failure prints **the server's own
  message**, never a blanket retry.
- **The typed note is kept** in `localStorage` (`bbfbn.draft.<client>`, `bbfb.draft.<client>` on the
  platform's copy) on every keystroke, and only cleared on a confirmed 200 - so it survives the page
  reload that signing in again requires. Every access is `try`-wrapped: a browser with site data
  blocked throws on the accessor itself.
- **Diagnosing the next report:** check the status code before touching the widget -
  `gcloud logging read 'resource.labels.service_name="cloudflare-dash" AND httpRequest.requestUrl:"/feedback"'`
  (or `platform-dash` for a front-door session). The tell for a dead tab is a **302 on
  `/d/<c>/data.json` on a fixed 5-minute cadence, for days, from a browser that never posts
  `/login`**.

---

## What the dashboard shows (`dashboard.html`)

Branding: Cloudflare orange gradient, Cloudflare + Transmission logos, title "Core Demand
Generation". One external library: Chart.js 4.5.0.

A top-bar **lane selector** (`#dashSelect`) holds two KINDS of entry (see the client README →
*Surround ABM split out of Core DG*):

- **PROGRAM lanes** — **Core DG APJ** (`core`) and **Surround ABM** (`surround_abm`, brief 2193,
  added 2026-08-14). Both render the FULL core shell below, scoped to one brief by the paid rows'
  `program` field (`PROGRAMS` / `progOk` in `dashboard.html`). Surround ABM is Trade Desk only and
  is restricted to the **Paid Media tab**, with budget pacing and the LinkedIn lead-commit block
  hidden — those plans are Core DG's.
- **CAMPAIGN lanes** — three **single-campaign LinkedIn dashboards**, *ANZ PEYC*, *CF1 India*,
  *Coles Hyper*, which render the `campaigns` branch of the payload (sourced from the shared
  `raw_snowflake.linkedin_ads_apac` BigQuery mirror).

The Core view has three tabs:

1. **Paid Media** — multi-channel delivery across **TTD, LinkedIn, Reddit, LINE**. KPI tiles
   (spend, impressions/CPM, clicks/CTR, LinkedIn leads, blended CPC), a channel-vs-benchmark
   table, daily TTD imps/clicks/CTR (mixed chart, 3 axes), channel-mix doughnut, daily stacked
   spend, spend by market, CTR/clicks/CPC trend trio, market-stacked-by-channel, a market
   summary table, **top & bottom performing creatives** tables (from `paid_media.creatives`), a
   LinkedIn **weekly-target** chart and a LinkedIn **funnel** (impressions → clicks → form starts
   → submitted leads), plus an explanatory "why lead volume looks low" analysis and a TTD-pixel
   caveat.
2. **Content Syndication** — lead pacing from the pacing model: leads-vs-target and
   time-progress bars, weekly pacing, demographic doughnuts (solutions, country, job
   function/level), best-performing assets, daily accepted leads, and a per-region grid.
3. **CS Comparison** — two side-by-side region/country panels (KPI tiles + targets + weekly
   pacing charts).

Filters: **market chips** for the seven markets (`ANZ, ASEAN, SAARC, GCR, KR, JP, RIG`), with
select-all / clear-all, per tab, plus a shared date-range picker for the Core tabs — quarter
presets, the usual relative presets, and (2026-08-14) a **Custom range** preset with typed
**From / To** date inputs bound to the same draft as the calendar. It reads the
combined payload's `paid_media`, `pacing.rows`, and `campaigns` branches — see the
[JSON contract](../job/README.md#the-json-contract-it-produces). The footer shows `last_updated`
(build time) and source-data-through, and notes that the dashboard auto-refreshes within ~10 min
of new Snowflake data.

### Restyle pass (2026-09-07) — values only, and the one contrast bug it closed

A presentation-only pass over the `<style>` block: everything outside it is byte-identical, so
no element, label, chart, filter or click path moved. It resolved the scale that had drifted
under the dark-glow skin (19 font sizes with five half-pixel steps, 11 radii, 9 px trackings and
3 grid gutters for the same roles) into one token ladder at the foot of `:root` — `--t-*` sizes,
`--tr-*` tracking in em, `--s-*`/`--gap`/`--gap-lg`, `--r-*`, `--pad-card`, `--shadow-pop`. Every
existing rule now reads a token instead of a hand-typed value, so the next reskin moves with the
tokens. The refinements that had to win the cascade sit in a final block AFTER the motion layer
(this file's own lesson: the motion layer is last on purpose).
**The bug worth remembering is repo-wide: `#fff` on `--brand-accent` (#F38020) is 2.65:1 and
fails AA at every size.** `--on-accent` (#25120A) is 6.77:1 and was already declared in `:root`
for exactly this — and `.cchip.on` was already using dark ink on the same orange, so the page
disagreed with itself: channel chips read correctly while the market chips, the Grain segs, the
date picker's presets / selected days / Apply button and the `.reason` numerals did not. All of
them now take `--on-accent`, including the QoQ heat map's `heatCell()` in the script, whose
`a > 0.55 ? '#fff'` put white on the hottest cell in the map — the one figure a reader goes to
first. **A white-on-brand-orange control anywhere in this estate is a contrast bug, not a style
choice.** Also closed here: `.qoq-cell`'s `rgba(11,16,23,.04)` cell border and `.dp-pop`'s
`rgba(0,0,0,.18)` shadow (both light-theme leftovers that rendered as nothing on a near-black
base), the `.dp` selector's dead blue defaults, `#bbb` in the topbar, the unused `--muted-2`
(now the third text tier, so column headers sit behind the data they label — 6.4:1 on
`--surface`), proportional numerals in the four data tables that lacked `tabular-nums`, and the
browser's own unthemed surfaces (selection, caret, Firefox scrollbar, list markers).
The three callout `border-left` rules were 4px / 5px / 5px for one idiom and are now a
consistent 3px; the detector still flags them as side-tabs, which is an accepted exception —
they are the client-approved incumbent language, not new decoration.

### Polish pass (2026-09-07, same day) — motion, surface tiers, and two real defects

The restyle above fixed the value layer. This pass went after what still read as machine-made,
and found two things that were not cosmetic at all.

**`@media print` is now present, and it is NOT optional.** The scroll-reveal hides every
surface at `opacity:0` until an observer says otherwise, and printing computes the styles as
they stand without re-running the observer — so the dashboard printed **blank below the fold**.
`md/AGENTS.md` records this measured on mongodb (40 dimmed surfaces on screen, 0 in print);
this dashboard's bespoke motion layer never got the escape hatch. Clients PDF these reports.

**The reveal now fails OPEN.** `[data-bb-reveal]{opacity:0}` was unscoped and the string
`bb-motion` appeared nowhere in this file, so unlike the shared `scripts/motion_kit/` version
there was no class a bootstrap could take back when the engine did not report in — the only
net was the in-JS watchdog, which reveals just what is already in the viewport. There is now a
head bootstrap that adds `html.bb-motion`, removes it again after 3.5s unless `init()` calls
`__bbMotionOK()`, and skips the class entirely under `prefers-reduced-motion`. Verified both
ways: gate on → `opacity:0`; gate removed → all 99 unrevealed surfaces snap to 1. **Never
unscope that rule again** — losing a fade is cheaper than losing a number.

**The travelling KPI stripe light is gone (22 of it).** `.kpi .stripe::after` ran a light along
the accent stripe of *every* KPI tile; at 22 tiles that was 22 of the **32 infinite animations
running on this page at rest** (measured). One reads as "live"; 22 reads as decoration, and
nothing that is on every tile can emphasise any of them. Now **10** at rest, and the aurora,
the masthead rail and the pacing-bar sheen — all client-approved — are untouched. The
hover-only `.kpi::after` sheen survives as the one piece of gloss, where the user is pointing.

**Nested surfaces got a second, flatter tier.** 95 card-like surfaces all carried border +
radius + shadow + inset highlight + a 3px hover lift, which means none of them was emphasised;
7 `.kpi` and 2 `.cspd-reason` sat *inside* a `.card` with the full outer treatment. `.card .kpi`
/ `.card .cspd-reason` are now flat and borderless — a tile inside a panel is content, not a
panel. `.compare-kpi` was already flat and needed nothing.

**Charts read as one family.** `tension` was 4 values in 5 spellings, `borderRadius` 3-vs-4 with
a *global default of 4 contradicting all 18 explicit datasets*, `pointRadius` and `borderWidth`
scattered. Now one curvature (`.25`), one bar radius (3, default included), and four
**role-scoped** stroke weights that are deliberate, not drift: line series 2, bar outline 1,
dashed reference 1.5, hero cumulative 2.5. The three dashed target lines were `[6,4]@2` twice
and `[5,4]@1.5` once for the same meaning; all three are now `[6,4]@1.5`. **Do not "simplify"
those four widths to one** — a bar outline and a doughnut slice separator are not stroke
weights, and the 2.5px hero line exists to out-weigh its own dashed twin. **`tension:.2` is a
prefix of `tension:.25`**, so never edit these with a bare find/replace.

**The palette leak is closed at both ends.** The chart colours were hardcoded hex in JS
(`PM_*`, plus `CF`/`TARGET`/`LINE` — 65 references) duplicating `:root`, so a reskin moved the
CSS and left all 28 charts on the old palette. The four channel colours were duplicated a
*third* time in the `.cchip.on.c-*` rules, so a channel's filter chip and its own chart series
had independent copies. New `--chan-ttd/-li/-rd/-ln/-ga/-purple` tokens are the one
declaration both ends read. Reads are **eager and that is safe**: the `:root` CSS is in
`<head>`, the script is in `<body>`, and there is no runtime theme switching anywhere in this
file. Palette constants go through **`cssTokOr(name, fallback)`** — a hoisted *function*, not a
`const`, because `CF`/`TARGET`/`LINE` execute far earlier in the same scope and a `const` would
be in its temporal dead zone there. The fallback matters: `getPropertyValue` returns `''` for a
renamed token and Chart.js given `borderColor:''` **draws nothing**, so a bad token name has to
degrade to the old colour, not to a blank canvas. Verified all 11 tokens resolve to exactly the
hex they replaced — the swap is a strict visual no-op.

**Two light-theme leftovers were hiding in inline styles.** `background:#FEF2F2` tinted the row
for a seeded campaign id *missing* from the data (Admin View) — the row's text inherits `--ink`,
so that was **1.02:1 and the id, label and campaign name were invisible in exactly the rows an
admin is looking for**; now a `--bad-red` wash at 12.18:1. And a cool blue-grey `#B9C2CC`
bar in an entirely warm palette became `--muted-2`.

**~80 of the 232 inline styles moved onto the ladder** (37 font-sizes, the margin rhythm, radii,
and the cool-grey-on-warm text). The one place a value deliberately *moved*: 14px and 18px card
separation both went to `--gap-lg` (16px), so in-grid gutters are `--gap` (12px) and card-to-card
separation is 16px — related things tight, separate groups apart. **~150 are deliberately left**:
structural properties, `font-weight`/`line-height`/`letter-spacing` (no tokens exist on those
axes), optical nudges like the 2px label/value gap, and 3 values computed in JS ternaries.

**Known and deliberately NOT changed** (raise these before "fixing" them):
- ~~9 dead CSS blocks~~ — **swept 2026-09-07, see below.**
- ~~Two one-item legends.~~ **Fixed 2026-09-07 — but only one of them was reachable, see below.**
- ~~`beginAtZero` missing on 3 bar value axes~~ — **stated explicitly 2026-09-07. It was a
  no-op, and now it is measured rather than assumed: all three already had `min:0` and a
  computed `beginAtZero:true`, because Chart.js v4's `BarController.overrides` sets
  `_value_:{beginAtZero:true}` — a bar chart gets it from the controller, not from these
  options. Axes were never truncated (verified min/max/tick counts identical before and
  after). It is stated anyway for two reasons: the other 18 value axes state it, and the
  guarantee lives in the CONTROLLER — switch one of these charts from `'bar'` to `'line'` and
  the override leaves with it, at which point the axis can float off zero and quietly
  exaggerate the differences it draws.**
### Icons are drawn now — one sprite, one geometry (2026-09-07)

The two **emoji are gone** (📅 in the date banner, 🎯 on the pacing badge — which only ever
appeared on the `good` state, so the three badge states are consistent now), and every Unicode
glyph that was standing in for an icon is a real drawn SVG: the tick (pacing badges + market
chips), the picker's caret and its two month-nav arrows, and the LinkedIn funnel's step
connector — which was a filled **play triangle** (`▶`), reading as a media button on what is a
flow.

**Geometry is not invented.** The date-picker button already carried one proper stroked icon
(the calendar): 24-unit box, `stroke-width:2`, round caps and joins — Lucide/Feather
parameters. The set **extends that family** rather than starting a second one.

Rules worth keeping:
- **One sprite** (`<symbol>` block immediately after the body opens), referenced by
  `<svg class="i"><use href="#i-…"/></svg>`. Pasting the same path into three static tags plus
  a JS template is how two copies of one icon start to drift.
- **Stroke lives in CSS (`.i`), never on the symbol.** That is what allows the 10px market-chip
  tick to take `stroke-width:3` while everything else stays at 2 — optical compensation, which
  real icon sets ship. A single weight across sizes is what makes a small icon look broken.
- **Sized in `em`, coloured by `currentColor`.** Each instance follows the type beside it and
  inherits the state logic that was already there — the funnel connector still goes
  `--cf-mute` → `--bad-red` with no per-icon rule, verified rendering at 18px in
  `rgb(251,142,128)`.
- `.prog-badge` is `inline-flex` with a 6px gap, so the icon is a flex item and the gap replaced
  the manual space that used to follow the glyph.
- The month-nav buttons gained `aria-label`s; they previously announced only `‹` / `›`.

**The delta arrows `▲` `▼` are deliberately still glyphs** (client call): they are data
indicators inside a figure, not interface chrome. They are the only icon-duty glyphs left —
`✓ ▶ ▾ ‹ ›` are all gone. A `<use>` that fails to resolve renders **nothing**, so if you add a
symbol, assert it paints (all 12 instances were checked for a non-zero box, not just for the
symbol existing).

### Dead CSS swept (2026-09-07) — and the test that makes it safe

**240 → 215 classes, 8772 → 8728 lines**, strict visual no-op. Removed: `.alert`(+`.ico`),
`.info`, `.pixel-compare`/`.pix`(+`.what`/`.ok`/`.miss`), `.why`(+`.lede`), `.reasons`,
`.reason`(+`.num`), `.gap-box`/`.gap-tile`(+`.lbl`/`.val`), `.friction`(+`.field-list`/`.req`/
`.auto`/`.smoking`), `.demo-list`/`.demo-row`(+`.lbl`/`.bar`/`.met`), `.grid-4`, `.lce-mk`, and
the `@media (max-width:1100px)` rule that existed only to resize three of them.

**The test that matters: a class is dead only if something never APPLIES it.** Appearing inside
a `querySelectorAll` string is a *reference*, not an application — that is a false negative that
made `.gap-tile`, `.pix`, `.alert`, `.info`, `.reason` and `.demo-row` look live on a first
scan, because they are all named in `bbMotion`'s `REVEAL_SEL` / `COUNT_SEL` / `BAR_SEL`. Each
class was cleared three ways: no word-boundary occurrence outside those selector strings, **zero
matches at runtime** across all six tabs + Admin view + an open date picker, and no consumer in
`main.py` / `report.py` / `bb_deck.js` / `feedback_widget.py` / the platform proxy.

**Proof of no-op**: the old and new selector strings were counted against the live DOM and match
exactly — `REVEAL_SEL` 121 = 121, `COUNT_SEL` 101 = 101, `BAR_SEL` 49 = 49. The fragments
removed matched nothing, which is the whole claim.

**KEPT despite also rendering zero times today** — these are live STATE classes this quarter's
data does not trigger, and deleting them would break a future render:
`.pace-risk.behind` · `.cchip.on.c-rd` / `.c-ln` (Reddit + LINE don't deliver under Q3) ·
`.cspd-book.regional` / `.unclassified`.

**`.reason` is NOT `.cspd-reason`.** The latter is live (3 on screen) and stays. A substring
match would have taken it out; word-boundary matching is what separated them.

Two of the four side-tab findings the detector used to report were on the dead `.alert` /
`.info` — it now reports **2**, and the remaining pair is the live `.qoq-note` idiom, unified
at 3px (the two inline `laneNote` / `dateScopeNote` copies still said 4px, so one callout drew
two different rules on one page). Detector total **13 → 11**.

Also removed here: a `.friction .field-list li::marker` rule added earlier the same day — for a
selector that never existed in the markup.

### One-item legends + one pending swatch (2026-09-07)

A legend exists to tell two series apart. With one dataset it is a swatch beside a label,
spending a row of vertical space to repeat what the card heading already says. Both charts now
use the predicate `cspdMarketChart` in this same file already uses **and comments**:
`display: ds.length > 1`.

**`A_/B_chartWeekly` was the real one, and it is REACHABLE.** On the **EMEA lane**, drilling to a
country makes `cscAgg` drop the market-grain target (`useTargets = targetsApply && !country`),
collapsing the chart to a single `Leads` series — while its sibling `A_/B_chartTargets` on the
*same card* already hid its own legend in exactly that case, so the two panels disagreed.
Verified live: UKI shows `['Target','Leads']` with the legend on; drilling to Germany gives
`['Leads']` with the legend off, and the sibling now agrees. The datasets array was hoisted to a
`wds` const purely so the legend could be gated on it.

**`weeklyChart` was NOT reachable, and the note that flagged it was out of date.** The
one-dataset branch is `isRel`, and `csWeeklyScale` is a **`const 'abs'`** — Relative mode was
removed on 2026-08-20 at the client's request (see the absolute-only note in `md/AGENTS.md`), so
`isRel` can never be true and that legend always had 2-3 datasets. The guard added there is
**defensive only**; it changes nothing on screen today and exists so the legend behaves if
Relative mode ever comes back. Do not cite it as a fixed defect.

**The "Unprocessed" swatch is now one declaration — and this closes a regression of my own.**
That metric is drawn in three places (the per-market `reg-fill` bar and two chart series), all
three previously the same hardcoded cool-grey `#B9C2CC`, with the `UNPROC` const's own comment
stating they *must* match. An earlier pass moved only the bar to `--muted-2`, breaking that
invariant. All three now read a real **`--pending:#B5A192`** token: warm, and clearly apart from
`--target-gray` so a pending bar is never read as a target bar. Deliberately **not** `--muted-2`
— that is a TEXT tier, and coupling a chart series to it means tuning text contrast silently
moves a chart. `UNPROC` is now `= PENDING` rather than a second literal, so the invariant is
structural instead of a comment. Verified: no `B9C2CC` survives anywhere, and the series renders
`#B5A192`.

**Editing note:** patches here were applied with Python. Use `write_bytes` and keep LF —
`write_text` on Windows rewrites all 8735 line endings to CRLF and turns the diff into
"whole file changed" (`core.autocrlf=true` is set globally, so the committed blob is LF either
way, but the working-tree diff becomes unreviewable).

---

## Deploy

Build the image, then deploy as yourself. **Don't** `gcloud builds submit --config
.../cloudbuild.yaml` from a laptop — it fails with `iam.serviceaccounts.actAs` (Cloud Build's
SA can't act as the runtime SA); that config is for a future push-to-main trigger only.

```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/cloudflare-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_cloudflare/dash --tag $IMG --region australia-southeast1
gcloud run services update cloudflare-dash --image $IMG --region australia-southeast1
gcloud run services describe cloudflare-dash --region australia-southeast1 --format="value(status.url)"   # then paste into LIVE_URL.md
```

## See also

- [`../README.md`](../README.md) — client overview and full deploy order.
- [`../job/README.md`](../job/README.md) — produces the JSON this app serves.
- [`../../client_mongodb/dash/README.md`](../../client_mongodb/dash/README.md) — the template web app (same gate).
