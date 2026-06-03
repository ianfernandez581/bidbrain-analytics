# client_STT/ — ST Telemedia GDC (APAC) · **LIVE**

> The effect of paid media on STT GDC website traffic. Built on the
> [`client_mongodb`](../client_mongodb/README.md) template: filter the shared raw layers down to
> STT's slice, model it in BigQuery views, export one JSON, serve it from a password-gated web app.

**Plain English:** STT GDC (ST Telemedia Global Data Centres), via the agency **Transmission**, runs
an FY25-26 "Always On" campaign across APAC on **LinkedIn** (paid social) and **DV360** (programmatic
display). This dashboard puts that ad spend next to what actually happened on the STT GDC **websites**
(Google Analytics 4) — so stakeholders can see the campaign lifting site traffic, not just ad metrics.

**Status:** ✅ **Live** (password-gated). See [`dash/LIVE_URL.md`](dash/LIVE_URL.md) for the URL + password.

---

## The story it tells

Three live sources, joined into one "ads → traffic" narrative:

| Source | Raw table (shared) | STT filter | What it contributes |
|---|---|---|---|
| **GA4** website analytics | `raw_windsor.perf_ga4` | the 11 `STT GDC Web *` properties | sessions / users / engagement, split by channel — **the outcome** |
| **Google Ads** paid search | `raw_snowflake.google_ads_apac` | `CAMPAIGN_NAME LIKE '%STT%'` | keyword delivery (USD→SGD); market from the campaign name |
| **DV360** programmatic display | `raw_snowflake.dv360_apac` | `CAMPAIGN_NAME = '(APAC) - STTGDC_Always On_Nov-Feb - (JN1663)'` | prospecting delivery (SGD) |
| **LinkedIn** paid social | `raw_snowflake.linkedin_ads_apac` | `ACCOUNT_NAME = 'STTGDC_TransmissionSG_USD'` | awareness delivery (USD) |

Headline (campaign window from 2025-06-01): **~1.48M website sessions**, **520k ad-driven**, with
**~S$109k** of LinkedIn + DV360 media behind **8.5M** impressions. Programmatic-display sessions rose
~5× after the DV360 flight launched (Nov 2025) — the dashboard's **Ads → Traffic** tab makes that link
explicit (Display ← DV360, Paid Social ← LinkedIn; weekly correlation + before/during lift).

**Reporting currency is SGD.** LinkedIn is billed in USD and converted at a fixed
`FX_USD_SGD = 1.34` (set once in the views — `sql/04_kpi.sql`, `05_monthly.sql`, `12_weekly.sql`).
Paid Search in GA4 is Google Ads, which is **not** in this spend dataset — so the spend-matched
"Ads → Traffic" view deliberately uses only Display + Paid Social.

---

## The 4 dashboard tabs (`dash/dashboard.html`)

Two filters at the top of the page:
- **Country** — slices every website-traffic figure by GA4 property (`account_name` → market),
  **Global deselected by default**. Shown on every tab except Paid Media.
- **Platform** — Google Ads · DV360 · LinkedIn (the three platforms with STT data; Meta & Trade
  Desk had none). Scopes the ad-delivery figures, and on **Ads → Traffic** also scopes the matched
  GA4 channels (Google Ads↔Paid Search, DV360↔Display, LinkedIn↔Paid Social). Shown on Overview
  and Ads → Traffic.

Spend is reported in SGD: LinkedIn (USD) and Google Ads' USD account rows are converted at the
fixed `FX_USD_SGD = 1.34`.

1. **Overview** — media spend / impressions / clicks vs website sessions; the monthly hero chart, the
   channel-mix donut, paid-vs-rest stacked sessions, and spend-by-platform.
2. **Paid Media** — LinkedIn + DV360 delivery: monthly impressions & spend, platform comparison table,
   DV360 by market, LinkedIn creative mix + campaigns.
3. **Website Traffic** — GA4: sessions by channel, total-vs-ad-driven trend, sessions by market
   (paid overlaid), top sources/mediums (the ad platforms flagged `AD`).
4. **Ads → Traffic** — the connection: weekly ad-impressions-vs-sessions, a correlation scatter (Pearson r),
   and the before-vs-during display-session lift.

---

## How it works (3 stages — same shape as every client)

```
 (1) SOURCE → RAW (shared)            (2) RAW → VIEWS → JSON            (3) JSON → FRONTEND
 ───────────────────────             ─────────────────────             ──────────────────
 windsor_data_pull  fills             client_STT/sql/*.sql filter        stt-dash (Cloud Run service)
 raw_windsor.perf_ga4                 STT's slice + roll it up;          shows a login page, then
 snowflake_data_pull fills            stt-export (Cloud Run JOB)         dashboard.html, which fetches
 raw_snowflake.{linkedin,dv360}_apac  reads the views → writes           /data.json and draws the charts
                                      stt.json to the private bucket
```

**Divergence from the template:** STT reads its three sources straight from the shared raw layers, so
there is **no `src_*` landing step** and **no bootstrap-first-failure** (unlike `client_cloudflare`).
The job is read-only on BigQuery — it only `SELECT`s the views and writes JSON to GCS.

| What to change | Edit | Stage |
|---|---|---|
| STT's filter (accounts / campaign IDs) | `sql/01_stg_ga4.sql` · `02_stg_linkedin.sql` · `03_stg_dv360.sql` | 2 |
| FX rate / campaign window | the `1.34` / `DATE '2025-06-01'` constants in `sql/04,05,12` | 2 |
| Roll-ups / new metrics | the relevant `sql/*.sql` view | 2 |
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

---

## Deploy / refresh (copy-paste, PowerShell)

Project `bidbrain-analytics`, region `australia-southeast1`. Use the repo `.venv`
(`.\.venv\Scripts\python.exe`). **First-time stand-up:** run [`deploy_stt.ps1`](deploy_stt.ps1) once
(idempotent — bucket, dataset, SAs, IAM, secrets, both Cloud Run units, the daily scheduler). After that:

**① Refresh the data now** (a daily Cloud Scheduler `stt-export-daily` already runs 22:00 UTC):
```powershell
# (optional) refresh the shared raw layers first if you want the very latest source data:
.\.venv\Scripts\python.exe windsor_data_pull\ga4\ga4_loader.py
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py
gcloud run jobs execute stt-export --region australia-southeast1 --wait    # views -> stt.json
```

**② You edited a view (`sql/*.sql`)** — apply, then re-run the job:
```powershell
.\.venv\Scripts\python.exe client_STT\create_views.py
gcloud run jobs execute stt-export --region australia-southeast1 --wait
```

**③ You edited `job/main.py`** (the JSON shape) — build, deploy, run:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/stt-export:$(git rev-parse --short HEAD)"
gcloud builds submit client_STT/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy stt-export --image $IMG --region australia-southeast1 --service-account stt-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute stt-export --region australia-southeast1 --wait
```

**④ You edited `dash/dashboard.html` or `dash/main.py`** — build + redeploy the service:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/stt-dash:$(git rev-parse --short HEAD)"
gcloud builds submit client_STT/dash --tag $IMG --region australia-southeast1
gcloud run services update stt-dash --image $IMG --region australia-southeast1
```
The service goes live as soon as the new revision is ready; it reads whatever JSON is in the bucket.

> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs` (Cloud Build's SA can't act as the runtime SA). Build the image, deploy
> as yourself (above). The `cloudbuild.yaml` files are for a future push-to-main trigger.

---

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_stt` (12 views) |
| Data bucket / object | `bidbrain-analytics-stt-dash` / `stt.json` |
| Export job | `stt-export` (runtime SA `stt-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `stt-dash` → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) (runtime SA `stt-dash-web@…`) |
| Secrets | `stt-dash-password` · `stt-dash-session-key` |
| Daily refresh | Cloud Scheduler `stt-export-daily` (22:00 UTC) |

## Files

- [`sql/`](sql/README.md) — the 12 BigQuery views (filter + model); `create_views.py` applies them.
- [`job/`](job/README.md) — the export job (stage 2): views → `stt.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the original pre-build scoping notes (historical).

## See also

- [Root README](../README.md) — platform map, security model, naming, add-a-client playbook.
- [`../client_mongodb/`](../client_mongodb/README.md) — the template this follows.
- [`../windsor_data_pull/ga4/`](../windsor_data_pull/ga4/README.md) — where `raw_windsor.perf_ga4` comes from.
