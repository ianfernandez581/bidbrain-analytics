# clients/client_schneider/ — Schneider Electric (APAC) · **live (deployed 2026-06-04)**

> Schneider Electric's APAC paid-media portfolio (run via the agency **Transmission**), across
> **DV360**, **The Trade Desk** and **LinkedIn**. Built on the [`client_STT`](../client_STT/README.md)
> archetype: filter the shared raw layers to SE's slice, model it in BigQuery views, export one
> JSON, serve it from a password-gated web app. Reporting currency **AUD**.

**Plain English:** Schneider runs a large, multi-campaign APAC programme (EcoStruxure Automation
Expert, AI & Liquid Cooling, C&SP, Enterprise IT, Industries of the Future, Impact Maker, MEA
Segment, …) across three ad platforms, mostly ANZ-weighted with India / SEA / MEA / South America
/ Pacific spill. This dashboard puts plan **budget & targets** (from the media plans) next to live
**spend & delivery** so stakeholders can see pacing, funnel and channel/geo performance per campaign.

**Status:** 🟢 **Live on GCP (stood up 2026-06-04; PACIFIC carve-out 2026-06-16).** All 28 views,
`schneider.json`, the `schneider-export` job and the `schneider-dash` service are deployed; the `*/10`
self-gating scheduler is running. [`deploy_schneider.ps1`](deploy_schneider.ps1) was the one-shot
stand-up and stays idempotent for a rebuild from scratch. GA4 (website) ships **disabled** until the
SE GA4 property id(s) are known. Seeded plan budgets cover 12 of the 27 mapped campaigns; the rest are
TODO (see [`INTAKE.md`](INTAKE.md)).

## 🌏 Pacific carve-out (the default view) — 2026-06-16
Per Transmission (Gabby O'Driscoll), the dashboard now **defaults to the SE *Pacific* book of work**,
kept COMPLETELY SEPARATE from the rest of APAC. `sql/30_seed_campaign_map.sql` carries a **`portfolio`**
column (`'Pacific'` | `'APAC-other'`); the dash has a **Portfolio toggle (Pacific / APAC-other / All)**
defaulting to Pacific. **This is the ORGANISATIONAL Pacific** (the client's named program list) — *not*
the geographic Pacific region chip on the Geography tab (Fiji/PNG/… parsed from campaign names), which
is deliberately **left untouched**. The 3 explicit excludes (AI & Liquid Cooling, Enterprise IT
Expansion, C&SP) are `'APAC-other'`. Newly mapped from the Phase-1 EDA: **AirSeT** (job 2223) and **EBA
/ EcoStruxure Building Activate** (job 2079) — EBA split into its own row out of `eae` (Automation
Expert) with the 300-opt-in-MQL target moved onto it. Job numbers corrected from the client Drive
(water_env 2026, mcset 2389, ind_edge 2463, eae 1974, ia_services 2280, heavy 2281, ecoconsult 2279).
**Full EDA, reconciliation table, the architecture decision (A: tag+toggle, one deployment) and the
open NEEDS-CONFIRMATION questions are in [`_eda/pacific_eda.md`](_eda/pacific_eda.md)** — read that
before changing portfolio tags. Flip candidates flagged in the seed comments: `ind_edge` /
`pac_hybrid_it` (geo-"Pacific"-named, tagged APAC-other), `ecocare`≡"EcoCare BMS", `enterprise_software`.

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
 snowflake_data_pull fills              clients/client_schneider/sql/*.sql filter   schneider-dash (Cloud Run service)
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
both Cloud Run units, scheduler). Note `deploy_schneider.ps1` seeds the scheduler at a fixed daily
cron; [`scheduler.ps1`](scheduler.ps1) flips it to the binding `*/10` self-gating cadence (the live
schedule). After that:

```powershell
# ① refresh data now (scheduler schneider-export-daily runs */10 UTC, self-gating)
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py            # optional: refresh shared raw layer
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ② edited a view (sql/*.sql) — apply, then re-run the job
.\.venv\Scripts\python.exe client_schneider\create_views.py
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ③ edited job/main.py (JSON shape) — build, deploy, run
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_schneider/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy schneider-export --image $IMG --region australia-southeast1 --service-account schneider-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ④ edited dash/dashboard.html or dash/main.py — build + redeploy the service
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_schneider/dash --tag $IMG --region australia-southeast1
gcloud run services update schneider-dash --image $IMG --region australia-southeast1
```
> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs`. Build the image, deploy as yourself (above). The `cloudbuild.yaml`
> files are for a future push-to-main trigger.

## Coordinates
| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_schneider` (26 views) |
| Data bucket / object | `bidbrain-analytics-schneider-dash` / `schneider.json` |
| Export job | `schneider-export` (runtime SA `schneider-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `schneider-dash` (runtime SA `schneider-dash-web@…`) → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `schneider-dash-password` · `schneider-dash-session-key` |
| Refresh | Cloud Scheduler `schneider-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Domain (later) | `schneider.bidbrain.ai` (CNAME + Host Header Override, wired later) |

## Files
- [`sql/`](sql/README.md) — the 26 BigQuery views (filter + model + seeds + disabled GA4).
- [`job/`](job/README.md) — the export job (stage 2): views → `schneider.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved data slice + open items handed to the client.

## See also
- [Root README](../../README.md) · the [`client_STT`](../client_STT/README.md) archetype · [`snowflake_data_pull`](../../ingest/snowflake_data_pull/README.md).
