# client_cloudflare/dash/ — the Web App (`cloudflare-dash`)

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
| [`main.py`](main.py) | The Flask app. **Byte-for-byte the same auth/serve/proxy logic as MongoDB** — only the login-page branding and the default `DATA_OBJECT` (`cloudflare.json`) differ. |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — "Core Demand Generation". ~1,690 lines (HTML + CSS + inline JS). Fetches `/data.json` once and renders everything client-side. |
| [`DASHBOARD.md`](DASHBOARD.md) | **How `dashboard.html` was built** from Cloudflare's original `index.html`: three small `<script>` edits to read one private `/data.json` instead of two public R2 files. Read this if you re-derive the page from a new design. |
| [`LIVE_URL.md`](LIVE_URL.md) | The live `…run.app` URL, the intended `cloudflare.bidbrain.ai`, and how to re-fetch the URL. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim` + gunicorn, non-root, copies `main.py` + `dashboard.html`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run deploy cloudflare-dash` → re-apply `--no-invoker-iam-check`. |
| [`requirements.txt`](requirements.txt) | `Flask`, `gunicorn`, `google-cloud-storage`. |
| `.dockerignore` | Keeps the build context lean. |

---

## Routes & security

Identical to the MongoDB service — see [that README](../../client_mongodb/dash/README.md#routes-mainpy)
for the route table. In short: `GET /` (login or dashboard), `POST /login` (constant-time
check), `GET /logout`, `GET /data.json` (**401 unless authenticated**, then streams the private
object), `GET /healthz`. Session cookie is `HttpOnly` + `Secure` + `SameSite=Lax`, 12-hour
lifetime, not domain-pinned (works through the Cloudflare proxy). The bucket stays private; the
public `…run.app` URL only ever shows the password screen.

---

## What the dashboard shows (`dashboard.html`)

Branding: Cloudflare orange gradient, Cloudflare + Transmission logos, title "Core Demand
Generation". One external library: Chart.js 4.5.0. Three tabs:

1. **Paid Media** — multi-channel delivery across **TTD, LinkedIn, Reddit, LINE**. KPI tiles
   (spend, impressions/CPM, clicks/CTR, LinkedIn leads, blended CPC), a channel-vs-benchmark
   table, daily TTD imps/clicks/CTR (mixed chart, 3 axes), channel-mix doughnut, daily stacked
   spend, spend by market, CTR/clicks/CPC trend trio, market-stacked-by-channel, a market
   summary table, a LinkedIn **weekly-target** chart and a LinkedIn **funnel** (impressions →
   clicks → form starts → submitted leads), plus an explanatory "why lead volume looks low"
   analysis and a TTD-pixel caveat.
2. **Content Syndication** — lead pacing from the pacing model: leads-vs-target and
   time-progress bars, weekly pacing, demographic doughnuts (solutions, country, job
   function/level), best-performing assets, daily accepted leads, and a per-region grid.
3. **CS Comparison** — two side-by-side region/country panels (KPI tiles + targets + weekly
   pacing charts).

Filters: **market chips** for the seven markets (`ANZ, ASEAN, SAARC, GCR, KR, JP, RIG`), with
select-all / clear-all, per tab. It reads the combined payload's `paid_media` and `pacing.rows`
branches — see the [JSON contract](../job/README.md#the-json-contract-it-produces).

---

## Deploy

Build the image, then deploy as yourself. **Don't** `gcloud builds submit --config
.../cloudbuild.yaml` from a laptop — it fails with `iam.serviceaccounts.actAs` (Cloud Build's
SA can't act as the runtime SA); that config is for a future push-to-main trigger only.

```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/cloudflare-dash:$(git rev-parse --short HEAD)"
gcloud builds submit client_cloudflare/dash --tag $IMG --region australia-southeast1
gcloud run services update cloudflare-dash --image $IMG --region australia-southeast1
gcloud run services describe cloudflare-dash --region australia-southeast1 --format="value(status.url)"   # then paste into LIVE_URL.md
```

## See also

- [`../README.md`](../README.md) — client overview and full deploy order.
- [`../job/README.md`](../job/README.md) — produces the JSON this app serves.
- [`../../client_mongodb/dash/README.md`](../../client_mongodb/dash/README.md) — the template web app (same gate).
