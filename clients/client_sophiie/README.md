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
| `dash/logo.png` | Sophiie's **supplied mark** (the headset) - a copy of `creatives/sophiie_logo.png`, baked into the image. |
| `dash/report.py` | AI deck generator, prompts re-templated for Sophiie's business. **Dormant** until `/report` is enabled. |
| `dash/platform_sso.py`, `dash/bb_deck.js` | Vendored, unchanged from the template. |
| `gen_placeholder.py` | Builds `dash/placeholder.json` from `targets/*.csv`. Deterministic (`random.seed(42)`). |
| `creatives/` | The **supplied artwork**, version-controlled: `sophiie_logo.png` (the client's mark) and `100digital_light.jpg` (the agency mark, mirrored from `bidbrain-platform/Creatives/`). Both are inlined as base64 into `dash/dashboard.html`. |
| `targets/targets.csv`, `targets/budget.csv` | Committed targets. **All `PENDING`** — no signed media plan yet. |
| `deploy_sophiie.ps1` | One-shot preview standup (service only — no dataset/job/scheduler). |
| `dash/deploy_dash_sophiie.ps1` | Redeploy just the service after a UI edit. |

## The aurora skin — what makes this dashboard different

This is **the only dashboard in the estate with an animated background**, and it is the point of the
design rather than decoration. Three fixed, `pointer-events:none`, `z-index:0` layers, bottom to top:

| Layer | What | Where |
|---|---|---|
| 1 | **Ambient orbs** — four 45–60vw radial gradients at `blur(120px)`, drifting on 18–25s cycles | `.aurora-ambient` (CSS only) |
| 2 | **Diagonal light bands** — five wide rectangles rotated −15°..−22°, six-stop blue gradients, 10–15s drift | `.aurora-diagonals` (CSS only) — **the signature; it mirrors sophiie.ai's own background** |
| 3 | **Curtains** — ~24 vertical strips swaying on layered sine waves, drawn as filled polygons | `#aurora-bg` `<canvas>` + the `auroraCurtains()` IIFE at the bottom of `dashboard.html` |

Every piece of page chrome sits at `z-index:1`. Cost is one `requestAnimationFrame` loop plus CSS
keyframes on nine fixed divs — it never touches layout, so it cannot reflow the dashboard.

**Four rules that will break this design if ignored** (they are also written into the `:root` block):

1. **The aurora is the only background.** Content surfaces stay **solid white** with a hairline and a
   soft shadow, and carry **no `backdrop-filter`**. A translucent or blurred card sitting over moving
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
