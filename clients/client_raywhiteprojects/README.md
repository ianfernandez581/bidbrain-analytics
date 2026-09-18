# client_raywhiteprojects - Ray White Projects

**Ray White Projects** is the Ray White Group's residential **project-marketing** division
(raywhiteprojects.com.au). It is **not** Ray White Commercial / RWC - a different business, and the
confusion is why the Slack channel was renamed. Agency: **100% Digital**.

**Monair, Greenwich is the first CAMPAIGN, not the client.** Over-55s development at 170 Pacific
Highway, 48 residences, move in mid 2028, site at monair.com.au (Webflow, built by Heard).
Developer **Realside**, architect **WMK**, builder **FDC**. More projects are expected on the same
account, so **project is a DIMENSION, never a route** - see "Project is a filter" below.

## Status: LIVE as a `coming_soon` preview (deployed 2026-09-18)

The campaign goes live **25 Sep 2026** and GA4 + GTM are not installed on monair.com.au yet, so
there is **no dataset, no `sql/`, no `job/` and no scheduler**. The bucket is deliberately EMPTY, so
`/data.json` serves the baked-in **illustrative** `placeholder.json` behind a preview notice, and
the page says so on its face.

| | |
|---|---|
| direct url | `https://raywhiteprojects-dash-516554645957.australia-southeast1.run.app` |
| through the front door | `/d/raywhiteprojects/` (no second password - SSO is wired) |
| password | the estate preview convention, `<key>2026`. **Rotate before handing it out** - reveal/rotate in the super-admin console. |
| tile | 100% Digital portal, `coming_soon` -> renders as a preview row with "Open preview ->" |
| Data Accuracy | greyed "awaiting connection" row (`show_pending_row`), beside geyervalmont / lacevo / burnet |
| serving revision | `raywhiteprojects-dash-00002-qtb`, image `sha256:263a1316fef5437255d4897f2a38811bbbaae9cec9fa9ab940020f497ebd7b00` |

**The image TAG is `ea1e596` and that tag lies.** It was built from an uncommitted working tree
during an unfinished merge, so the commit it names does not contain this code (the repo-wide
"deploy from an uncommitted tree" rule). The **digest above is the only honest identifier** of what
the revision runs. Content hashes of what actually shipped:
`dashboard.html 3759aae5`, `main.py 11f8ab9e`, `placeholder.json 201a1882`,
`internal_notes.json 1233ba7f`, `platform_sso.py 6ddfc9cf`, `Dockerfile 8a08187d`
(`git hash-object`). Once this lands on main, redeploy so the tag becomes true again.

**Verified on the live service, not just locally:** unauthenticated `/data.json`,
`/data-version.json` and `/internal/notes.json` all 401; a wrong password 401s and a correct one
302s to the dashboard; the served `dashboard.html` and `data.json` are **byte-identical** to the
repo files; through the proxy the page gets `BB_INTERNAL` / `BB_SPEND_MULT` / `BB_SPEND_BASIS`
injected, `/data.json` is rewritten to `/d/raywhiteprojects/data.json`, and the **relative**
`internal/notes.json` resolves under the prefix in a real browser. `/healthz` 404s at the Cloud Run
edge, as it does estate-wide; nothing uses it.

### To re-stand it up from scratch

```powershell
$env:CLOUDSDK_ACTIVE_CONFIG_NAME="personal"   # or the deploy uses the agora account and fails
$env:DASH_PASSWORD="<choose>"                 # or the script prompts, which hangs non-interactively
.\clients\client_raywhiteprojects\deploy_raywhiteprojects.ps1
.\scripts\enable_platform_sso.ps1 -Keys raywhiteprojects
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\set_raywhiteprojects_tile.py --yes
```

`platform-dash` does **not** need redeploying for the tile: `_upstream_base()` and `_may_open()`
both read the runtime registry in GCS, which `set_raywhiteprojects_tile.py` writes. `config.py` is
the source of truth in code and ships with the next platform deploy.

---

## Key vs slug - do not "tidy" this

| | value | why |
|---|---|---|
| client key | `raywhiteprojects` | every infrastructure name derives from it |
| public slug | `raywhite-projects` | the registry/display identifier |

A **BigQuery dataset cannot contain a hyphen**, so `client_raywhite-projects` would not be a legal
dataset id the day a pipeline lands. The estate already carries this split - `cityperfume` /
`city-perfume`, `tlm` / `the-little-marionette`, `sophiie` / `sophiie-ai`.

Everything else follows the key: dataset `client_raywhiteprojects`, bucket
`bidbrain-analytics-raywhiteprojects-dash`, service `raywhiteprojects-dash`, future export job
`raywhiteprojects-export`, **proxy path `/d/raywhiteprojects/`**.

---

## File map

| path | what it is |
|---|---|
| `dash/dashboard.html` | the whole UI, one file. Renders entirely from `/data.json`. |
| `dash/main.py` | Flask: password gate, `LOGIN_HTML`, `/data.json` (+ placeholder fallback), `/data-version.json`, `/internal/notes.json`, `/healthz`. |
| `dash/placeholder.json` | **GENERATED** illustrative payload. Do not hand-edit. |
| `dash/internal_notes.json` | staff-only Internal notes content, deliberately **off** `data.json`. |
| `dash/platform_sso.py` | vendored verbatim from the estate - do not edit locally. |
| `dash/Dockerfile`, `dash/cloudbuild.yaml`, `dash/requirements.txt` | container + CD (no trigger wired). |
| `dash/deploy_dash_raywhiteprojects.ps1` | redeploy the service after a `dash/` edit. What `/ship` runs. |
| `deploy_raywhiteprojects.ps1` | one-shot idempotent stand-up. |
| `gen_placeholder.py` | builds `dash/placeholder.json` **and asserts it reconciles**. |
| `gen_brand_assets.py` | derives the brand assets once artwork is supplied. Exits 1 today. |
| `creatives/` | where the artwork goes. Empty; `creatives/README.md` says what to ask for. |

There is **no `sql/`, `job/`, `targets/` or `scheduler.ps1`** yet, and no `/report` (the AI deck
needs `roles/aiplatform.user` and a client-specific prompt set; neither is warranted while every
number is illustrative).

---

## The data contract

Normally this is the three-stage `sql/*.sql` column -> `job/main.py` env key -> `dashboard.html`
`data.*` key chain. There is no pipeline yet, so today it is two stages - the payload key and its
consumer - and **the payload shape IS the interface a pipeline fills in**, so connecting the feeds
is a data change and not a template rewrite.

| payload key | grain | drives |
|---|---|---|
| `meta.placeholder` | flag | **the ONE switch**: preview notice, topbar chip, `Illustrative` tag, `PREVIEW_` export prefix |
| `meta.projects[]` + `meta.project_default` | project | the project selector (`initProject`), which renders as a plain label below 2 entries |
| `meta.period_label`, `date_min`, `date_max`, `data_through` | - | the date-range **statement**, band caption, footer |
| `meta.feeds_expected[]` | - | the preview banner's "not connected yet" list |
| `projects[]` | project | hero title + credits, live chip, flight, budget, targets, `plan_channels` |
| `projects[].targets.derived` | flag | puts a literal `(derived)` on every target label |
| `projects[].flight.pace_basis` | - | states that expected-to-date is an assumption, and **withholds the verdict colour** |
| `channels[]` | channel | label, colour, `plan_ctr` / `plan_cpe`. **One definition**, read by the table, the CPE chart, the donut and the share bar. |
| `daily[]` | date x project x **channel** | THE PAID FACT: impressions, clicks, spend, enquiries. Everything paid derives from it. |
| `site_daily[]` | date x project | **whole-site** sessions + CRM appointments. Deliberately NOT channel-grain. |
| `line_items[]` | line item | the Media tab table |
| `enquiries.by_configuration` / `by_suburb` / `funnel` | - | the Enquiries tab |
| `selldown.units[]` | residence | the stock board, one square each |

**Almost nothing is precomputed.** CPE, CTR, CPC, enquiry rate, shares, pacing percentages and
every per-channel total are derived in the browser from `daily[]` / `site_daily[]`. That is what
lets the channel chips re-sum the page instead of only relabelling it.

---

## Project is a filter, not a route

Built the `client_geocon` way. `projOk(r)` is the **single enforcement point**; `ROWS()` is the only
paid accessor and it goes through it. Adding the second project is:

1. `meta.projects[]` + `projects[]` gain an entry, and `daily[]` / `site_daily[]` / `line_items[]`
   rows carry its `project` key.
2. One more `st.set_campaign(KEY, 1, ...)` row in `set_raywhiteprojects_tile.py`.

**No dashboard code changes.** The selector appears by itself at two projects (`initProject` renders
a plain label below that - a dropdown with one option is a control that cannot do anything), and the
in-page Project pill row unhides with it. A project with `status: "coming_soon"` renders disabled
and enables itself when its first row lands.

---

## What the channel chips may and may not move

This is the load-bearing rule on this dashboard.

- `daily[]` is channel-grain, so the chips legitimately re-sum **impressions, clicks, spend,
  enquiries, CTR, CPC, CPE** and the trend's bars and spend line.
- `site_daily[]` is **not**. A session on monair.com.au has no delivering channel, and an
  appointment comes off the CRM with no channel attribution at all. So **sessions, appointments and
  the sessions line on the trend do not move**, the tiles carry a `Whole site` marker while a filter
  is on, and the legend note says so.
- The **Enquiries tab** panels (configuration, suburb, funnel) come from the register-interest form,
  which records no channel. The tab states that in its own banner rather than letting the chips look
  broken.
- **Pacing does not follow the chips either** - it is a full-flight fact and reads the unfiltered
  project total.

If those figures ever start moving with the chips, someone has put `sessions` or `appointments` into
the channel-grain fact. Don't.

Verified: unticking Meta takes enquiries 214 -> 118 and spend A$18,420 -> A$10,220 (exactly Meta's
96 / A$8,200), while sessions stay 8,120 and appointments stay 38.

---

## Gotchas

- **Only `/data.json` survives the platform proxy.** It string-replaces that one literal
  (`/data.json` -> `/d/raywhiteprojects/data.json`). Every other fetch here is **relative**
  (`internal/notes.json`, `data-version.json`) because an absolute path resolves against the
  PLATFORM root and never reaches this service. `client_schneidersecpwr` still carries that bug.
- **That literal is also how the proxy recognises the dashboard page** (`is_dashboard`) and injects
  `window.BB_INTERNAL` / `BB_SPEND_MULT`. Remove the `/data.json` fetch and the staff gate silently
  stops working.
- **A root-relative asset path 404s behind the proxy.** The topbar lockup is inline for that reason;
  only the login (served from the service root) may reference a route.
- **`[hidden]` is forced `display:none !important`.** The UA rule loses to any author `display`, and
  several rows here are `display:flex`.
- **Reduced motion must name the pseudo-elements.** `*` matches elements only, and this build
  animates `body::before` (a 38s ambient wash) and transitions `.cell::after`. The rule is
  `*,*::before,*::after`. Verified with `--force-prefers-reduced-motion` +
  `document.getAnimations().length === 0`.
- **An empty state hides its canvas, never replaces the canvas's parent** (`chartEmpty()`).
  Overwriting the parent deletes the `<svg>` and every later render short-circuits on its own guard.
- **`Number(null)` and `Number('')` are both `0`**, so `Number.isFinite(Number(x))` is not a null
  guard. Use `numOrNull()`, or a deliberately blank target reads as "target 0".
- **The spend multiplier is applied per row by that row's OWN channel.** `realestate.com.au` and
  `Domain` have no key in the platform's `SPEND_CHANNELS`, so they stay at factor 1 = raw. See
  "Open items".
- **The plan side is never grossed** - a media plan is already the client-billed figure.
- **`dash_dir`-relative reads only.** Assets are anchored to `__file__`, not the cwd.
- **Charts are hand-written SVG, no Chart.js.** `scripts/apply_motion_kit.py` anchors on a
  `<title>` fallback for exactly this case - but see below, the motion kit is not applied here.

---

## Motion

**This dashboard is NOT a `scripts/apply_motion_kit.py` target, deliberately** - the
`client_cloudflare` / `client_sophiie` precedent, where a richer client-approved layer stays its
own. It ships its own scroll progress bar, `.rev` reveal, count-up, meter fills, sparklines, trend
crosshair, donut sweep and stock-board fill. Running the kit as well would paint a **second**
progress bar over the existing one and its `[data-bb-reveal]` / `.value` selectors would match
nothing.

**The LOGIN is a `scripts/apply_login_kit.py` target** (`page="dark", card="dark"`, accent = the
yellow, `wash=False`), for the three behaviours a password gate should always have had: show/hide,
a Caps Lock warning and submit-once. `wash=False` because the login already paints a radial glow, a
moving sweep, a vignette, an SVG grain layer and the stacked floorplates - a sixth layer is a haze.
Re-apply with `.\.venv\Scripts\python.exe scripts\apply_login_kit.py raywhiteprojects`;
**do not hand-edit the injected block**, the next run overwrites it.

Two guards on the count-up: a generation token (so a frame from a previous filter scope cannot paint
over fresh figures) and a text check (so an animation whose element was re-rendered underneath it
cannot restore the old value and leave it there).

---

## Brand

- ink `#131311`, bone `#F4F2ED` / field `#EFEDE8`, concrete `#8E8B83`, sand `#C4B49C`
- **Ray White yellow `#FFE512` is a FILL and a RULE, never text.** It is ~1.3:1 on the bone field
  and ~1.07:1 on white. On this dashboard it appears only as: the scroll progress bar, the 6px
  live/agency dots, a 3px border on the callout, one donut/bar segment, and the EOI state on the
  stock board.
- **The exception is background-dependent, not a contradiction.** On the **login**, the card is
  near-black, where the same yellow is ~13.6:1 - so it carries the focus ring, the field underline
  and the login kit's accent there. Same "which shade depends on what it sits on" split
  `client_lacevo` and `client_burnet` carry.
- Ray White **Projects** uses the **concrete** lockup on Monair, not the yellow one.
- Archivo for UI and numbers, Instrument Serif for display (Google Fonts, as the rest of the estate).
- **VERIFY `#FFE512` AGAINST THE BRAND KIT BEFORE THIS GOES TO THE CLIENT.** It is the design
  reference's value and has not been checked against Ray White's own artwork.

### Brand assets

**No artwork has been supplied.** The mark on both the login and the topbar is a **typographic
stand-in** in markup, and the favicon is an inline data URI - there is deliberately no generated
placeholder image and no `logo.svg` / `icon.png` in this unit. The estate has twice had to delete a
fabricated mark the day the real one arrived (`client_sophiie`, `client_lacevo`).

When the files land: drop them in `creatives/` and run `gen_brand_assets.py`. It prints the three
edits that go with it - the Dockerfile `COPY` line, the `/logo.svg` + `/icon.png` routes in
`main.py` (**content-hashed**, or a browser serves the old art for a day and the deploy looks like
it failed - the Lacevo trap), and the two deploy guards.

---

## Internal notes - staff only, and the honest limit

The tab is gated on `window.BB_INTERNAL`, which only the platform proxy sets, for
superadmin/admin/owning-agency sessions. Its **content is not in `data.json` at all** - it is
fetched from `/internal/notes.json` when the tab opens, so a client session never receives the text.

**That route AUTHENTICATES but does not AUTHORIZE BY ROLE.** The `bb_sso` cookie carries the list of
clients a session may open, not the role, so a logged-in client who guessed the path would be served
it. Closing that gap means putting the role in the SSO token in
`bidbrain-platform/dash/platform_sso.py`, which is vendored into every dashboard in the estate.
**Until then, keep `internal_notes.json` to feed status and questions to ask** - no commercial
terms, no rates, nothing about another client.

### A login for the developer

Realside is a separate stakeholder and may need a login that does not see agency commentary. Today:

- **Per-person email grants** in the super-admin console's sign-in access panel are how to give them
  one. Do **not** hand out the 100% Digital agency password - it opens every other 100% Digital
  client.
- Agency commentary is already off the client surface (the gate above).
- A genuinely **narrower** client view is **not yet possible** - same missing role in the SSO token.
  Scope any promise to that.

---

## Cookbook

**Change an illustrative figure** - edit the constants at the top of `gen_placeholder.py`, run it
(the assertions will stop you if a KPI stops matching its own table), then
`dash/deploy_dash_raywhiteprojects.ps1`.

**Edit the UI** - `dash/dashboard.html`, then
`.\.venv\Scripts\python.exe scripts\_validate_dash_js.py clients\client_raywhiteprojects\dash\dashboard.html`,
then the same deploy script (it re-runs both gates itself).

**Render it locally exactly as a browser sees it** - serve `dash/` with `/data.json` mapped to
`placeholder.json`, then headless Chrome. Add `--force-prefers-reduced-motion` to populate the KPI
figures without scrolling (the count-up is IntersectionObserver-driven, so off-screen tiles stay at
`0` in a headless snapshot) and to assert `document.getAnimations()` is empty.

**Rotate the password / open the preview** - super-admin console. It reveals and rotates.

---

## Flipping preview to live

In this order:

1. **Feeds.** GA4 + GTM on monair.com.au (through Heard), the register-interest form submit event
   **with the configuration field**, partner access to Meta and Google Ads, a decision on how
   realestate.com.au and Domain enquiries arrive, and the CRM for sell-down + appointments.
2. **Read in the signed media plan** (`Ray White Projects Monair Sydney x 100% Digital.xlsx`) - the
   real cost per enquiry, budget, flight dates and per-channel plan rates. Drop
   `targets.derived` and `flight.pace_basis` in the same edit, or the UI keeps labelling real
   targets as derived and keeps withholding the pacing verdict.
3. **Build the pipeline**: `sql/` views, `job/main.py` writing `raywhiteprojects.json` to the
   bucket, a `*/10` scheduler and `job/freshness.py` (the estate's freshness contract). Keep the
   payload keys in the contract table above and the dashboard needs no edit.
4. **Drop `meta.placeholder`.** That alone removes the preview notice, the topbar chip, the
   `Illustrative` tags and the `PREVIEW_` export prefix.
5. **Flip the tile**: `STATUS = "active"`, `NOTE = ""`, campaign status `active`,
   `show_pending_row=False` in `set_raywhiteprojects_tile.py`, and mirror it in
   `bidbrain-platform/dash/config.py`.
6. **Status pipeline**: add to `BQ_CLIENTS` in `status_dashboard/job/main.py` **and** to the
   bucket-grant list in `status_dashboard/job/deploy_job_status.ps1`. **Those two always move
   together** - a missing grant 403s, and that 403 aborts the whole BigQuery accuracy section for
   every client.
7. **`Resolve-DeployPlan`** in `scripts/merge-branches.ps1`: add this client's seed directory to the
   seed-input regex if one is created, or the seed silently rots.

---

## Open items

- **Artwork** and **the yellow hex** - above.
- **The media plan.** Every target is derived. Do not quote a number off this dashboard yet.
- **The illustrative figures are mutually inconsistent, and that is a question for the plan, not a
  rounding error.** 214 enquiries at the A$95 plan rate is ~A$20,330 for 30 days, which over the
  98-day flight is ~A$66k, not the A$85,000 committed. So the card genuinely reads under pace. It
  states its basis and withholds the verdict colour rather than asserting a position the plan has
  not confirmed. **Do not "fix" it by nudging a number.**
- **Supply mix** across the 48 residences. Without it the configuration chart is demand only and
  must not be read as an over/under-supply call - `enquiries.supply_mix_known` gates that wording.
- **Portal spend basis.** `realestate.com.au` and `Domain` have no `SPEND_CHANNELS` key, so if a
  billed-rate multiplier is ever set for Meta or Google, the blended total mixes billed and raw.
  Either add portal keys to `bidbrain-platform/dash/store.py` or leave the multiplier unset here.
- **Cross-domain tracking.** If ads land on raywhiteprojects.com.au before monair.com.au, this hits
  the `client_geocon` attribution problem.
- **Second project.** Confirm what is behind Monair so the campaign naming convention is agreed once.
