# client_schneider/ — Schneider Electric (APAC) · **scaffolded, not yet deployed**

> Schneider Electric's APAC paid-media portfolio (run via the agency **Transmission**), across
> **DV360**, **The Trade Desk** and **LinkedIn**. Built on the [`client_STT`](../client_STT/README.md)
> archetype: filter the shared raw layers to SE's slice, model it in BigQuery views, export one
> JSON, serve it from a password-gated web app. Reporting currency **AUD**.

**Plain English:** Schneider runs a large, multi-campaign APAC programme (EcoStruxure Automation
Expert, AI & Liquid Cooling, C&SP, Enterprise IT, Industries of the Future, Impact Maker, MEA
Segment, …) across three ad platforms, mostly ANZ-weighted with India / SEA / MEA / South America
/ Pacific spill. This dashboard puts plan **budget & targets** (from the media plans) next to live
**spend & delivery** so stakeholders can see pacing, funnel and channel/geo performance per campaign.

**Status:** 🟡 **Built in-repo, not yet stood up on GCP.** Run [`deploy_schneider.ps1`](deploy_schneider.ps1)
once to provision everything. GA4 (website) ships **disabled** until the SE GA4 property id(s) are known.

---

## What's different from STT (the archetype)
- **Three platforms, all programmatic/social** (DV360 + TradeDesk + LinkedIn) — **no GA4 website
  layer yet**, **no Google Ads / Reddit / Salesforce** (Schneider has no rows there).
- **Reporting currency AUD.** USD→AUD @1.50, SGD→AUD @1.15 (placeholders — confirm). LinkedIn has
  no currency column, so its currency is inferred from the account-name suffix (`_USD`/`_AUD`/`_SGD`).
- **Plan vs actual is the story**, not ads→traffic. The dashboard is driven by **seed tables**
  (campaign map / budget / flighting / targets / channel split) joined to live delivery by a
  `match_pattern` CONTAINS bridge — see [`sql/30_seed_campaign_map.sql`](sql/30_seed_campaign_map.sql).
- **GA4 shipped disabled** behind a property-id placeholder + `GA4_ENABLED` flag in the job.

## The 5 dashboard tabs (`dash/dashboard.html`)
Filters: **Platform** · **Objective** · **Campaign** (internal, searchable multi-select) · **Region**
(Geography tab). Persona / vertical / account / funnel-stage filters are stubs for a later seed-backed pass.

1. **Portfolio Overview** — one card per internal campaign (objective, region, budget vs spend + %
   consumed, pacing vs flight-elapsed, KPI-vs-target where set), portfolio rollups, and a flight-window
   **Gantt** so overlapping flights (cannibalisation risk) are visible.
2. **Spend & Pacing** — plan budget vs actual by campaign/platform, cumulative-spend pacing, the
   budget-basis (incl/ex fees) label, and the approved **2306 channel split** (Search & Reddit flagged
   "planned, no warehouse delivery").
3. **Delivery & Funnel** — Impressions → Clicks (CTR/CPC) → Video (VCR, LinkedIn) → Conversions/Leads,
   with each campaign's primary KPI.
4. **Channel Comparison** — DV360 vs TradeDesk vs LinkedIn (CTR/CPC/CPM/VCR) + awareness-vs-RT split.
5. **Geography** — region split + the AU/NZ split within ANZ + region×platform.

Data-readiness chips make missing lanes explicit (Website/GA4 "awaiting property id"; Leads/ABM
"manual feed, not yet wired"; Search & Reddit "no platform delivery").

## How it works (3 stages — same shape as every client)
```
 (1) SOURCE → RAW (shared)              (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 snowflake_data_pull fills              client_schneider/sql/*.sql filter   schneider-dash (Cloud Run service)
 raw_snowflake.{dv360_apac,             SE's slice + roll it up + seeds;    shows a login page, then
 tradedesk_apac_all, linkedin_ads_apac} schneider-export (Cloud Run JOB)    dashboard.html, which fetches
 (google_analytics_apac_all when GA4 on) reads views → schneider.json       /data.json and draws the charts
```
Read-only on BigQuery (it only SELECTs views + writes JSON). No `src_*` landing, no bootstrap failure.

| What to change | Edit | Stage |
|---|---|---|
| SE filter / FX rate | `sql/01_stg_dv360.sql` · `02_stg_linkedin.sql` · `03_stg_tradedesk.sql` (+ `05_kpi.sql`) | 2 |
| Campaign map / budget / targets / flighting / channel split | `sql/30–34_seed_*.sql` | 2 |
| Enable GA4 | set property id(s) in `sql/40_stg_ga4.sql` (+ `46_`), `GA4_ENABLED=True` in `job/main.py` | 2 |
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

## Deploy / refresh (copy-paste, PowerShell)
Project `bidbrain-analytics`, region `australia-southeast1`. **First-time stand-up:** run
[`deploy_schneider.ps1`](deploy_schneider.ps1) once (idempotent — bucket, dataset, SAs, IAM, secrets,
both Cloud Run units, daily scheduler). After that:

```powershell
# ① refresh data now (scheduler schneider-export-daily runs */10 UTC, self-gating)
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py            # optional: refresh shared raw layer
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ② edited a view (sql/*.sql) — apply, then re-run the job
.\.venv\Scripts\python.exe client_schneider\create_views.py
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ③ edited job/main.py (JSON shape) — build, deploy, run
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-export:$(git rev-parse --short HEAD)"
gcloud builds submit client_schneider/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy schneider-export --image $IMG --region australia-southeast1 --service-account schneider-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ④ edited dash/dashboard.html or dash/main.py — build + redeploy the service
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-dash:$(git rev-parse --short HEAD)"
gcloud builds submit client_schneider/dash --tag $IMG --region australia-southeast1
gcloud run services update schneider-dash --image $IMG --region australia-southeast1
```
> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs`. Build the image, deploy as yourself (above). The `cloudbuild.yaml`
> files are for a future push-to-main trigger.

## Coordinates
| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_schneider` (25 views) |
| Data bucket / object | `bidbrain-analytics-schneider-dash` / `schneider.json` |
| Export job | `schneider-export` (runtime SA `schneider-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `schneider-dash` (runtime SA `schneider-dash-web@…`) → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `schneider-dash-password` · `schneider-dash-session-key` |
| Refresh | Cloud Scheduler `schneider-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Domain (later) | `schneider.bidbrain.ai` (CNAME + Host Header Override, wired later) |

## Files
- [`sql/`](sql/README.md) — the 25 BigQuery views (filter + model + seeds + disabled GA4).
- [`job/`](job/README.md) — the export job (stage 2): views → `schneider.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved data slice + open items handed to the client.

## See also
- [Root README](../README.md) · the [`client_STT`](../client_STT/README.md) archetype · [`snowflake_data_pull`](../snowflake_data_pull/README.md).
