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
