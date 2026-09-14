# client_lacevo — Lacevo (PREVIEW, no data)

Australian direct-to-consumer brand on Shopify: wearable breast pumps (S70), a portable bottle
warmer (N6), a light-therapy set, and spare parts. Two storefronts — **lacevo.com** (Australia) and
**lacevo.us** (United States). Agency: **100% Digital** (not Transmission, not Extra Black).

**Status: PREVIEW.** No feed is connected. There is deliberately **no `sql/`, no `job/`, no
BigQuery dataset and no scheduler** — the dashboard serves a baked-in sample payload behind a
preview notice, exactly like `client_geyervalmont`. Everything on screen is placeholder data and
the page says so in four places (topbar chip, the notice bar, a KPI chip, the export filename).

Live preview URL, once deployed: `https://lacevo-dash-516554645957.australia-southeast1.run.app/`
Through the front door: `dashboards.bidbrain.ai` → 100% Digital portal → Lacevo → **Open preview**.

---

## File map

| Path | What it is |
|---|---|
| `dash/dashboard.html` | The whole UI. Four tabs: Overview, Paid media, Store, Internal notes. Renders entirely from `/data.json`. |
| `dash/main.py` | Flask gate: login, platform SSO, `/data.json`, `/internal/notes.json`, `/logo.png`, `/icon.png`, `/healthz`. |
| `dash/placeholder.json` | The sample payload. **Generated — do not hand-edit.** |
| `dash/internal_notes.json` | Staff-only content for the Internal notes tab. Kept OUT of `data.json` on purpose. |
| `dash/platform_sso.py` | Vendored verbatim from the platform. Never edit one copy. |
| `dash/logo.png` | The bone STACKED lockup, for the dark login card. Generated. |
| `dash/icon.png` | The CLAY droplet, for the browser tab. Generated. |
| `creatives/LACEVO-master.webp` | The supplied master artwork. Every variant derives from this. |
| `dash/Dockerfile`, `requirements.txt`, `cloudbuild.yaml` | Container. No trigger is wired; deploys are laptop/ship driven. |
| `dash/deploy_dash_lacevo.ps1` | Redeploy the service after editing anything under `dash/`. |
| `deploy_lacevo.ps1` | One-shot idempotent standup (APIs, bucket, SA, secrets, service). |
| `gen_placeholder.py` | Builds `dash/placeholder.json` and asserts it reconciles. |
| `gen_brand_assets.py` | Derives all three brand variants from the master. **Regenerate, never hand-edit.** |

Platform side (outside this folder):
- `bidbrain-platform/dash/config.py` — the `lacevo` CLIENTS entry + membership of the 100% Digital agency.
- `bidbrain-platform/dash/set_lacevo_tile.py` — surgical live-registry upsert for the portal tile.

---

## Branding

Tokens verified from the live lacevo.com Shopify theme, and used exactly:

| Token | Value | Where |
|---|---|---|
| clay | `#965F48` | primary accent, meter fill, submit button, active tab underline |
| clay lifted | `#C98A6E` | **anything clay that must be legible on ink** |
| bone | `#E4E0DA` | text on the dark shell; `#E9E5DF` is the warmed page field |
| ink | `#1C1C1C` | top bar, login field, body text |
| type | Instrument Sans (headings + numerals), Montserrat (body) | both from Google Fonts |

**The one rule that matters: clay is a FILL, not a text colour.** `#965F48` on `#1C1C1C` is far
too dark to read, to carry a 1px edge, or to draw a caret. Anything sitting ON the dark shell uses
the lifted `#C98A6E`; the solid clay is only ever a filled surface with bone on top of it. Getting
that backwards is how a brand colour ends up as an invisible border — which is also why the login
kit entry in `scripts/apply_login_kit.py` pins the accent to the lifted value, not the brand value.

The **dashboard** is a bone field with near-white cards under the brand's black header bar (the
approved reference layout). The **login** is the inverse — the black header treatment taken
full-page — which is what the brief meant by a dark shell.

### The logo

The real artwork landed 2026-09-14 and lives at `creatives/LACEVO-master.webp`. It is a **stacked
lockup — droplet above a serif wordmark — in near-black ink on SOLID WHITE, with no alpha channel**.
Every surface it appears on here is dark, so it cannot be used as supplied on any of them.

`gen_brand_assets.py` derives three variants and is the only thing that should ever write them:

| Output | What | Where |
|---|---|---|
| `dash/logo.png` | bone STACKED lockup | the dark login card, served at `/logo.png` |
| `dash/icon.png` | clay droplet, square | the browser tab, served at `/icon.png` |
| `creatives/topbar_lockup.b64.txt` | bone HORIZONTAL lockup | inlined as base64 in the topbar |

**The white is keyed out by LUMINANCE, not by a colour match**: `alpha = 255 - L`, then the RGB is
set flat to the target colour. That keeps every antialiased edge pixel at its correct partial
opacity. A threshold, or a "replace white with transparent" pass, leaves a ragged light fringe on a
dark ground, which is the tell of a badly key-dropped logo.

**The topbar lockup is HORIZONTAL and we composed it.** The supplied stacked lockup cannot fit a
50px bar without shrinking the wordmark to noise, and the obvious alternative — the droplet beside
"Lacevo" set in Instrument Sans, which the placeholder build did — puts a grotesque next to the
brand's own serif wordmark, and a font mismatch at that size reads as a mistake. So the generator
places the master's own two elements side by side, unmodified, at their native proportions. Nothing
is redrawn or retyped, but it is still a DERIVED arrangement: **if Lacevo supply an official
horizontal lockup, drop it in and delete that step.**

**The topbar mark is inlined as base64 on purpose.** A root-relative asset path does not resolve
behind the platform proxy at `/d/lacevo/`, so `<img src="/logo.png">` inside the dashboard would 404
once deployed. That is the same "logo ships twice" gotcha `client_geyervalmont` carries. The login
page is served from the service root, so it can use the route. The dashboard's own favicon link is
**relative** (`icon.png`) for the same reason the internal-notes fetch is.

**The favicon is CLAY, not bone.** A near-white mark is invisible on a browser's light tab strip;
clay carries on both light and dark chrome.

Assets are sized to their DISPLAY, not to round numbers. The master is only 300x166, so anything
past about 2x is upscaling a low-res source and paying in bytes for detail that is not in the file.
The inline lockup ships inside every page load, so its size is not free.

`gen_logo.py`, which fabricated the placeholder droplet, was deleted with this change: a generator
whose only remaining effect would be to overwrite real artwork is a liability, not a tool. That is
the `client_sophiie` precedent.

---

## Preview mechanism

`meta.placeholder` is the single switch. `main.py` serves `dash/placeholder.json` at `/data.json`
whenever the bucket has no real `lacevo.json`; that payload carries `placeholder: true`, and the
dashboard derives the notice bar, the topbar "Preview" chip, the KPI chip and the `PREVIEW_` export
filename prefix from it. The moment an export job writes a real object to the bucket, that wins and
every one of those disappears — **no code change and no redeploy.**

The bucket is created EMPTY by the standup script precisely so this path is exercised from day one.

---

## Data contract — the shape the pipeline must emit

This is the last leg of the repo's three-stage contract, matched BY NAME:

    sql/*.sql view column  ->  job/main.py env dict key  ->  dashboard.html DATA.* key

There is no `sql/` or `job/` yet, so the contract below is what a future job MUST emit. Build it to
this shape and the template does not change — that is the point of the preview.

| Key | Shape | Notes |
|---|---|---|
| `meta` | object | `placeholder`, `currency_symbol`, `period_label`, `date_min`/`date_max`/`data_through`, `channels_connected`, `channels_expected`, `markets`, `market_default`, `sites`, `excludes_note` |
| `targets` | object | `roas_target`, `cac_ceiling`, `derived` |
| `flight` | object | `start`, `end`, `days_total`, `days_elapsed`, `budget` |
| `daily[]` | `date, revenue, spend, sessions, orders` | the ONLY dated array |
| `channels[]` | `channel, colour, note, spend, revenue, orders, delta_vs_prior` | |
| `campaigns[]` | `campaign, sub, channel, stage, spend, revenue, orders` | the paid GRAIN |
| `stages[]` | `stage, spend, colour` | supplies display ORDER + colour only |
| `products[]` | `product, units, revenue, unit_price` | `units`/`unit_price` may be null (bundles) |
| `funnel[]` | `step, value` | |
| `store` | object | `repeat_purchase_rate`, `refund_value`, `repeat_note` |
| `customers` | object | `new`, `returning` |

**Almost nothing is carried precomputed, and that is deliberate.** Revenue, spend, orders, ROAS,
AOV, conversion rate, cost per order, units, units per order, refund rate, revenue share, spend to
date, expected to date and the projection are all DERIVED in the browser from the arrays above. A
precomputed headline sitting beside a table that can be filtered out from under it is how two
panels on one page start disagreeing, and the preview exists to build trust in the numbers.

`gen_placeholder.py` asserts the reconciliations that the real job will also have to hold:
daily revenue = channel revenue = product revenue; daily orders = channel orders = the funnel's
last step; stage spend = channel spend; new + returning customers = orders.

---

## Things that were decided here, not inherited

**Cost per order, not "cost to acquire a customer".** The reference called the tile CAC while
computing ad spend ÷ ORDERS, which is cost per order. Renamed to what it measures, and the real
definition is listed as an open question on the Internal notes tab. If the client wants spend ÷
first-time buyers, the figure rises (A$81.37 → A$104.49 on the sample) and the A$110 ceiling has to
move with it.

**Stage split derives from the campaign table above it.** The reference's stage chart folded the
Performance Max line (tagged `Mixed`) into `Capture`, so the chart said Capture = A$28,640 while
the table on the same tab called A$9,260 of that `Mixed`. The chart is now built from the rendered
campaign rows, so it follows the channel chips and can never contradict the table.

**Targets are labelled `(derived)`.** Neither the 3.50x return nor the A$110 ceiling comes from a
signed media plan. `targets.derived` drives the label. An unlabelled red delta accuses a campaign
of missing a KPI nobody agreed to — the caltex rule. Drop the flag when the real plan lands.

**Budget pacing withholds a green for overspend.** Within ±5% of plan reads "On plan"; either side
reads "Over plan" / "Under plan" in amber. A budget can miss in both directions, so the only good
state is on it. Expected-to-date and the projection derive from `flight.days_elapsed`, falling back
to the count of DELIVERING days — never "today minus the start", which halves the run rate on a
feed that is a day behind and under-projects a campaign performing to plan.

**Channel chips are on the Paid media tab only.** Not an oversight. The Overview headline is
BLENDED by definition (store revenue over total ad spend) and Shopify revenue has no delivering
channel at all, so a chip on those tabs would either visibly fail to move the numbers beside it or,
worse, silently move half the panel. Same reason `client_schneider` hides its platform chips on the
tabs that read Salesforce.

**The period control is a statement, not a picker.** `daily` is the only dated array; channels,
campaigns, products and the funnel are whole-period aggregates. A date filter today would move the
KPI band while every table under it stayed put. It becomes a real picker the day those aggregates
carry a date column — and the US market chip is drawn disabled with a reason for the same honesty.

---

## The lighting layer

The dashboard is deliberately more animated than the estate default. That default exists to protect
a client's weekly familiarity with an instrument they already read, and Lacevo has no incumbent
viewer: it went live as a `coming_soon` preview and the client has never opened it. Sophiie is the
precedent for a dashboard whose light is part of the design.

**Three layers, in z-order, and the order matters:**

| z | Layer | Cost |
|---|---|---|
| -3 | `.lumen-sun` | static CSS gradients. Free, and it does most of the work. |
| -2 | `#lumen` | one low-resolution canvas of drifting light, built in JS. |
| -1 | `.bb-fx` | the motion kit's three CSS orbs, **suppressed** by `body .bb-fx{display:none}`. |

**Why the kit's orbs are suppressed rather than kept.** The estate's measured rule is that the cost
of ambient motion is the NUMBER OF ANIMATED FULL-SCREEN LAYERS, not the drawing. Keeping three
animated DOM orbs and adding a canvas would be four. One canvas replaces all three, so this build
animates FEWER layers than the plain kit build did. Measured at **60fps** with the canvas running.
The kit block itself is untouched, so re-running `apply_motion_kit.py` cannot fight this.

**The static layer is about SHADE, not highlight.** The first attempt tinted light over a light
field and the painted pixels landed within 4 points of it, which is invisible. A lit page needs
somewhere for the light to come up from, so `.lumen-sun` darkens the bottom and the far corner and
the top then reads as illuminated. Canvas hues stay LIGHT, near the shell's own luminance, with
saturation running free. That is the rule Sophiie paid for: darkening hues to make them visible
instead makes overlapping layers accumulate into grey-brown mud over a warm shell.

**Never put `filter:blur()` on that canvas.** It is drawn at 26% scale and upscaled by the
compositor, and that bilinear upscale of soft radial gradients IS the blur, for free. A blur filter
on a full-viewport canvas measured 61fps to 3fps, because it re-applies on every painted frame.
Equally: no `mix-blend-mode`, which forces the whole stack underneath to re-composite every frame.

**Chart entrance animation** (`animateChart`) walks the SVG a draw function just produced and uses
the Web Animations API rather than per-element keyframes. Bars need `transform-box:fill-box` or an
SVG element's `transform-origin` resolves against the whole viewBox and the bar scales in from
off-screen. It uses the `scale` / `translate` properties, never the `transform` shorthand, for the
same reason the motion kit does. Re-running it on a filter change is intentional: the chart
redrawing is the feedback that the filter applied.

**`litFill()` gives each data colour one cached gradient** so a bar stays a single `<rect>`. The
alternative, overlaying a second "gloss" rect per bar, would double the shapes the entrance
animation has to stagger.

**The trap this layer actually hit: `*` matches elements, NEVER pseudo-elements.** The blanket
`@media (prefers-reduced-motion:reduce){*{animation:none}}` left the meter's `.fill::after` sheen
looping for exactly the visitors it exists to protect. Any animated `::before` / `::after` has to be
named explicitly. Verified with `--force-prefers-reduced-motion`: `document.getAnimations()` now
returns an empty list, and the canvas removes itself so no rAF loop survives at all.

Presentation only. The rendered TEXT of all three client tabs is byte-identical to the build before
this layer landed, verified by diffing headless renders against the same payload.

## Internal notes — how it is protected, and how far that goes

Two mechanisms, following `client_schneidersecpwr`'s Reports tab:

1. **The tab is not built** unless `window.BB_INTERNAL` is set. The platform proxy injects that in
   `<head>` only for superadmin / admin / owning-agency sessions — the same `_internal_allowed`
   predicate that decides whether the staff Internal Notes widget is injected. A client session, and
   any direct `*.run.app` URL, never receives it, so the tab is absent, its pane stays hidden, and
   `#notes` in the URL falls back to Overview.
2. **The content is not in `data.json`.** It is fetched from `/internal/notes.json` only when that
   tab opens, so hiding the tab is not the only thing standing between a client and it.

**The honest limit: that route authenticates but does not authorize by ROLE.** This service cannot
yet tell a staff session from a client one — the `bb_sso` cookie carries the allowed-CLIENT list,
not the role — so a logged-in client who guessed the path would be served it. Closing that means
putting the role in the SSO token in `platform_sso.py`, which is vendored into every dashboard in
the estate. **Until then, nothing genuinely sensitive goes in `internal_notes.json`** — today it
holds feed status and questions to ask, which is the right ceiling for it.

One deliberate difference from the secpwr precedent: the fetch URL here is **relative**
(`internal/notes.json`, no leading slash). secpwr uses a root-relative path, which resolves to the
PLATFORM's own `/internal/` namespace once proxied at `/d/<c>/` and only works on the direct
run.app URL. The relative form resolves correctly under both origins.

---

## Deploying

| You changed | Run |
|---|---|
| anything under `dash/` | `clients\client_lacevo\dash\deploy_dash_lacevo.ps1` (also what `/ship` runs) |
| `gen_placeholder.py` | `.\.venv\Scripts\python.exe clients\client_lacevo\gen_placeholder.py` then the dash deploy |
| `bidbrain-platform/dash/config.py` | `bidbrain-platform\dash\deploy_dash_platform.ps1` |
| first-ever standup | `clients\client_lacevo\deploy_lacevo.ps1`, then `set_lacevo_tile.py --yes` |

Deploys need `ian@100.digital` (charles@ has no perms): `$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"`.

After the standup, run `scripts\enable_platform_sso.ps1` so the platform's `bb_sso` cookie opens
this dashboard without a second password. Without it the dashboard still works, on its own password
only.

---

## Not wired yet (deliberate)

- **No `/report` AI deck.** It needs `roles/aiplatform.user`, an `enable_report_lacevo.ps1`, a
  vendored `bb_deck.js` and a client-specific prompt set. None of that is worth wiring while every
  number is a placeholder. `requirements.txt` is correspondingly shorter than the other tenants'
  (no `anthropic`, no `httpx`) — add them back alongside a real `report.py`.
- **No status-pipeline entry.** `status_dashboard/job/main.py`'s `BQ_CLIENTS` verifies a JSON
  against BigQuery; there is no dataset to verify against. The registry's `show_pending_row` flag
  gives it the greyed "awaiting connection" row on the Data Accuracy tab instead, which is the
  honest state. **When it goes live, adding it to `BQ_CLIENTS` ALSO requires adding it to the
  bucket-grant list in `status_dashboard/job/deploy_job_status.ps1`** — missing that 403s, and that
  403 aborts the whole BigQuery accuracy section for EVERY client (it happened on the Sophiie
  standup).
- **No Extra Black visibility.** Lacevo is attached to 100% Digital only. Dual visibility for an
  external agency is a per-client decision, never a default.

---

## FLIPPING PREVIEW → LIVE

In order:

1. **Get the feeds.** Shopify private app token, Meta partner access, Google Ads manager link,
   TikTok business centre invite, GA4 read access (both properties if both markets are reported).
   The current asks are tracked on the Internal notes tab.
2. **Answer the open questions first**, especially the revenue definition and whether AU and US are
   reported together — both change the shape of the views, not just their values.
3. **Build `sql/` + `job/`** to the data contract above, with `job/freshness.py` vendored in (the
   repo's freshness contract binds every export job: self-gating on a `*/10` tick, watermark in a
   `_freshness.json` sidecar, and never watermark a VIEW).
4. **Re-run `deploy_lacevo.ps1`** — it will need a `-WithData` branch adding for the dataset, the
   job service account and the scheduler; copy it from `clients/client_sophiie/deploy_sophiie.ps1`.
5. **Set `meta.placeholder` false** in the job's output (not in the template).
6. **Flip the tile**: in `set_lacevo_tile.py` set `STATUS = "active"`, `NOTE = ""` and the campaign
   tuple's status to `"active"`, then re-run with `--yes`. Mirror it in `config.py` and drop
   `show_pending_row`.
7. **Set the client password** in the super-admin console, or grant their Google/Microsoft email to
   this dashboard there. **Do not hand out the 100% Digital agency password** — it opens every other
   100% Digital client.
8. **Add to the status pipeline** (see the two-list warning above).
