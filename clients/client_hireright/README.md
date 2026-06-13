# clients/client_hireright/ — HireRight (paid media) · **live**

> All of HireRight's paid media in one place. Built on the
> [`client_STT`](../client_STT/README.md) template, stripped to a pure paid-media **delivery** baseline:
> filter the shared raw layers down to HireRight's slice, model it in BigQuery views, export one JSON,
> serve it from a password-gated web app.

**Plain English:** HireRight runs paid media across three platforms — **DV360** (programmatic display),
**The Trade Desk** (programmatic air-cover) and **LinkedIn** (paid social). This is a generic delivery
dashboard: spend, impressions, clicks, conversions and efficiency in one view. There is **no GA4 /
website side** (HireRight's GA4 property can't be identified) and **no media plan / targets / seeds** —
it renders fully from delivery alone.

**Status:** 🟢 Deployed & live (password-gated). Stood up via
[`deploy_hireright.ps1`](deploy_hireright.ps1); verified serving HTTP 200 (login) and `/data.json`
(401-gated / 200-after-login) on **2026-06-04**. See [`dash/LIVE_URL.md`](dash/LIVE_URL.md).

---

## The story it tells

Three live ad sources, folded into one delivery narrative. **Reporting currency is USD.**

| Source | Raw table (shared) | HireRight filter | Currency → USD | Geo |
|---|---|---|---|---|
| **DV360** programmatic display | `raw_snowflake.dv360_apac` | `LOWER(ADVERTISER_NAME) LIKE '%hireright%'` | already USD | **real country** (`COUNTRY_NAME`) |
| **The Trade Desk** programmatic | `raw_snowflake.tradedesk_apac_all` | `ADVERTISER_NAME = 'HireRight'` | AUD → USD @ `0.65` | `'Global'` (persona/TAL, no geo) |
| **LinkedIn** paid social | `raw_snowflake.linkedin_ads_apac` | `LOWER(ACCOUNT_NAME) LIKE 'hireright%'` | already USD (`_AUD` acct → @0.65) | `'Global'` (audience combined) |

There are **no** Google Ads / Reddit / Salesforce / GA4 views — HireRight has no rows in those sources.

Confirmed against the raw layer at build time (window **2025-10-25 → 2026-06-02**): DV360 ≈ **$14.9k** /
15 country markets, LinkedIn ≈ **$22.6k**, TradeDesk ≈ A$6.8k → **~$4.4k** — combined **~$42k** USD.

**FX:** the single constant `FX_AUD_USD = 0.65` (a placeholder — editable) is applied where each AUD
source is staged (`sql/03_stg_tradedesk.sql`, and the `_AUD` guard in `sql/02_stg_linkedin.sql`) and
surfaced as `fx_aud_usd` in `sql/05_kpi.sql`. Only TradeDesk is actually converted today.

---

## The 2 dashboard tabs (`dash/dashboard.html`)

Three filters at the top:
- **Platform** — DV360 · TradeDesk · LinkedIn. Scopes the **Overview** figures. (Paid Media always shows
  all three for comparison.)
- **Campaign** — a searchable multi-select dropdown of every delivering campaign (grouped by platform,
  sorted by spend), **all selected by default**. Scopes ad delivery everywhere, summed client-side from
  the campaign-grained `ad_campaign*` views.
- **Market** — DV360 country names + `'Global'`, **all selected by default**. Scopes the **by-market**
  charts only (DV360 has real countries; TradeDesk + LinkedIn are `'Global'` air-cover).

1. **Overview** — KPI tiles (spend, impressions, clicks, blended CTR, CPM, CPC, conversions); a monthly
   hero (spend by platform stacked + clicks line); a spend-mix doughnut; spend-by-platform; spend-by-market.
2. **Paid Media** — monthly delivery by platform; a platform comparison table (DV360 / TradeDesk /
   LinkedIn + Combined: spend, impressions, clicks, CTR, CPM, CPC); DV360 spend & impressions by country;
   a top-campaigns-by-spend table (all platforms); a LinkedIn creative-mix doughnut; and a LinkedIn
   engagement funnel (impressions → clicks → video views → VCR = completions ÷ starts → lead-form opens → leads).

---

## How it works (3 stages — same shape as every client)

```
 (1) SOURCE → RAW (shared)             (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 ───────────────────────              ─────────────────────               ──────────────────
 snowflake_data_pull fills             clients/client_hireright/sql/*.sql filter    hireright-dash (Cloud Run service)
 raw_snowflake.{dv360_apac,            HireRight's slice + roll it up;      shows a login page, then
 tradedesk_apac_all,                   hireright-export (Cloud Run JOB)     dashboard.html, which fetches
 linkedin_ads_apac}                    reads the views → writes             /data.json and draws the charts
                                       hireright.json to the private bucket
```

The job is read-only on BigQuery — it only `SELECT`s the views and writes JSON to GCS (no Snowflake creds).

| What to change | Edit | Stage |
|---|---|---|
| HireRight's filter | `sql/01_stg_dv360.sql` · `02_stg_linkedin.sql` · `03_stg_tradedesk.sql` | 2 |
| FX rate `0.65` | the constant in `sql/02,03` and `sql/05_kpi.sql` | 2 |
| Roll-ups / new metrics | the relevant `sql/*.sql` view | 2 |
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

> **BigQuery note.** These run as BigQuery views. BigQuery has no `ILIKE` / `LIKE … ESCAPE`, so the
> brief's `ILIKE '%HireRight%'` is written `LOWER(col) LIKE '%hireright%'` and the LinkedIn `_AUD` guard
> as `ENDS_WITH(ACCOUNT_NAME, '_AUD')` (same intent, valid Standard SQL). See [`sql/README.md`](sql/README.md).

---

## Deploy / refresh (copy-paste, PowerShell)

Project `bidbrain-analytics`, region `australia-southeast1`. Use the repo `.venv`
(`.\.venv\Scripts\python.exe`). **First-time stand-up:** run [`deploy_hireright.ps1`](deploy_hireright.ps1)
once (idempotent — bucket, dataset, SAs, IAM, secrets, both Cloud Run units, the Cloud Scheduler trigger; it
prompts for the dashboard password, or set `$env:DASH_PASSWORD` first). The export **job is self-gating**
(see the Coordinates table). Note: `deploy_hireright.ps1` still seeds the scheduler at the legacy daily
`0 22 * * *` default — run [`scheduler.ps1`](scheduler.ps1) (default `*/10 * * * *`) to flip it to the
self-gating cadence. After that:

**① Refresh the data now** (the `hireright-export-daily` Cloud Scheduler runs `*/10` UTC, self-gating):
```powershell
# (optional) refresh the shared raw layer first if you want the very latest source data:
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py
gcloud run jobs execute hireright-export --region australia-southeast1 --wait    # views -> hireright.json
```

**② You edited a view (`sql/*.sql`)** — apply, then re-run the job:
```powershell
.\.venv\Scripts\python.exe client_hireright\create_views.py
gcloud run jobs execute hireright-export --region australia-southeast1 --wait
```

**③ You edited `job/main.py`** (the JSON shape) — build, deploy, run:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/hireright-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_hireright/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy hireright-export --image $IMG --region australia-southeast1 --service-account hireright-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute hireright-export --region australia-southeast1 --wait
```

**④ You edited `dash/dashboard.html` or `dash/main.py`** — build + redeploy the service:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/hireright-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_hireright/dash --tag $IMG --region australia-southeast1
gcloud run services update hireright-dash --image $IMG --region australia-southeast1
```
The service goes live as soon as the new revision is ready; it reads whatever JSON is in the bucket.

> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs`. Build the image, deploy as yourself (above). The `cloudbuild.yaml` files
> are for a future push-to-main trigger.

---

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_hireright` (14 views) |
| Data bucket / object | `bidbrain-analytics-hireright-dash` / `hireright.json` |
| Export job | `hireright-export` (runtime SA `hireright-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `hireright-dash` → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) (runtime SA `hireright-dash-web@…`) |
| Secrets | `hireright-dash-password` · `hireright-dash-session-key` |
| Refresh | Cloud Scheduler `hireright-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Custom domain | `hireright.bidbrain.ai` (note only — not yet wired; see `dash/LIVE_URL.md`) |

## Files

- [`sql/`](sql/README.md) — the 14 BigQuery views (filter + model); `create_views.py` applies them.
- [`job/`](job/README.md) — the export job (stage 2): views → `hireright.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved build slice (filters, currency, platforms).

## See also

- [Root README](../../README.md) — platform map, security model, naming, add-a-client playbook.
- [`../client_STT/`](../client_STT/README.md) — the template this follows (the GA4 half stripped out).
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — where the three HireRight raw layers come from.
