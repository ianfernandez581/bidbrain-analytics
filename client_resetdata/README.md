# client_resetdata/ — ResetData (Australia) · B2B sovereign-AI / data-centre

> The effect of paid media on the ResetData website: spend → traffic → engagement → leads / key
> events. Built on the [`client_STT`](../client_STT/README.md) archetype (the lean "ads → website
> traffic" pattern that reads straight from the shared raw layers, no Snowflake final-model step).
> **ResetData tells the same B2B story as STT — NOT the e-commerce shape:** there is no
> revenue / ROAS / AOV / transactions. Conversions here are leads / form-fills / key events.

**Plain English:** ResetData is an Australian sovereign-AI / data-centre infrastructure brand, run
by the agency **100 Digital**. It advertises on **Google Ads** (paid search), **Meta** (paid social)
and **The Trade Desk** (programmatic display). This dashboard puts that ad spend next to what
happened on the ResetData **website** (Google Analytics 4) — sessions, engagement, and the demand-gen
key events (lead form, sign-up, $50-credit click, file downloads).

**Reporting currency: AUD.** Status: built 2026-06-08; see [`dash/LIVE_URL.md`](dash/LIVE_URL.md).

---

## What's different from `client_STT` (the deltas)

| | STT | **ResetData** |
|---|---|---|
| Platforms | Google Ads · LinkedIn · DV360 | **Google Ads · Meta · The Trade Desk** |
| Source datasets | all `raw_snowflake` | **three layers**: `raw_google_ads` · `raw_windsor` · `raw_ga4` |
| GA4 source | Snowflake event-grain (reconstructed) | **`raw_ga4.perf_ga4`** — already Traffic-Acquisition grain → `stg_ga4` is a plain filter |
| Currency | SGD (FX_USD_SGD=1.34) | **AUD** (FX_USD_AUD=1.50, TTD only) |
| Geography | 9 APAC markets + Country filter | **AU-only — no Country filter** |
| Conversions | GA4 key events | GA4 key events **+ platform-reported** (Google solid, Meta sparse, TTD none) |

## The five sources (three raw datasets) + the exact slice filters

| Source | Raw table | ResetData filter | Currency | Contributes |
|---|---|---|---|---|
| **Google Ads** (paid search) | `raw_google_ads.perf_google_ads` | `account_name = 'Reset Data'` | AUD | imps / clicks / **spend (already AUD — not micros)** / conversions (83) |
| **Meta** (paid social) | `raw_windsor.perf_meta` | `account_name = 'Reset backup – Ad account'` (**en-dash –**) | AUD | imps / clicks / spend / **leads** / creative mix |
| **The Trade Desk** (display) | `raw_windsor.perf_the_trade_desk` | `advertiser_name = 'ResetData'` | **USD → AUD ×1.50** | imps / clicks / spend |
| **GA4** (the outcome) | `raw_ga4.perf_ga4` | `client_slug = 'reset-data'` | — | sessions / users / engagement / channels / conversions |
| **GA4 events** | `raw_ga4.perf_ga4_events` | `client_slug = 'reset-data'` | — | key events by name (leads / sign-ups / …) |

> **Slug split (important):** Google Ads + GA4 tag the client `reset-data` (hyphen); Meta + TTD tag it
> `resetdata` (no hyphen). Each `stg_*` view filters by the **stable per-table key** above
> (account / advertiser name), not a single shared slug.

## Currency & FX

Everything is **AUD**. Google Ads `spend` from the native DTS table is **already whole AUD dollars**
(verified ~A$8 CPM — do **not** divide by 1,000,000). Meta `cost` is already AUD. The Trade Desk bills
**USD**, converted once in [`sql/04_stg_ttd.sql`](sql/04_stg_ttd.sql) at **`FX_USD_AUD = 1.50`** (the same
constant `client_schneider` uses) and surfaced as `kpi.fx_usd_aud`. _If the real rate differs, edit the
`1.50` in `04_stg_ttd.sql` and re-run the views._

## GA4 conversion health (read honestly)

GA4 key-event tracking **is live and does populate**, but volumes are **modest** for this B2B / low-traffic
site (~72 key events over the window). The configured GA4 conversion event is **`Leadform_submit`**; other
demand events — `sign_up`, `start_$50_free_credit_click`, `file_download`, `learn_more_click` — also fire.
The dashboard shows these as **directional demand signals, not a high-volume funnel**, and flags the
caveat in-app. Platform-reported conversions are separate: **Google Ads = 83 (reliable)**, **Meta leads = 2
(sparse)**, **The Trade Desk = none reported upstream** (its `conversions` JSON is null → cost-per-lead "—").

**GA4 channel blend:** Paid Search ≈ Google Ads (clean); Paid Social also carries Reddit traffic; Display
also carries Google PMax/Demand-Gen — so the platform↔channel mapping (Google↔Search, Meta↔Social,
TTD↔Display) is approximate. The Ads→Traffic correlation uses mapped paid sessions for the selected platforms.

## The 4 dashboard tabs (`dash/dashboard.html`)

Two filters (top of page, on Overview + Ads → Traffic; Website Traffic shows none):
- **Platform** — Google Ads · Meta · Trade Desk. Scopes ad-delivery figures; on Ads → Traffic also scopes
  the mapped GA4 channel sessions. (Paid Media ignores Platform — it always compares all three.)
- **Campaign** — searchable multi-select of every delivering campaign (grouped by platform, sorted by
  spend), all selected by default. Scopes **ad delivery only**; the GA4/website side stays whole. Powered
  by the campaign-grained `ad_campaign*` views, summed client-side.

1. **Overview** — KPI cards (media spend · impressions · clicks · sessions · ad-driven sessions · engaged ·
   key events), hero monthly **spend (stacked by platform) vs sessions** with key-events dashed line, and
   channel-mix / spend-by-platform donuts.
2. **Paid Media** — platform comparison table (CTR/CPM/CPC/conv/CPL), monthly spend by platform, per-platform
   campaign tables (Google / Meta / TTD), and the Meta creative mix.
3. **Website Traffic** (GA4) — sessions / users / engagement KPIs, sessions by channel, total-vs-ad-driven
   trend, **key events by type**, and top sources/mediums (ad platforms flagged `AD`).
4. **Ads → Traffic** — monthly spend vs sessions, weekly impressions vs mapped sessions, a **Pearson-r
   correlation scatter**, and conversions / cost-per-lead by platform.

## How it works (3 stages — same shape as every client)

```
 (1) SOURCE → RAW (shared)              (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 raw_google_ads.perf_google_ads         client_resetdata/sql/*.sql filter   resetdata-dash (Cloud Run service)
 raw_windsor.perf_meta / _the_trade_desk ResetData's slice + roll it up;     shows a login page, then
 raw_ga4.perf_ga4 / perf_ga4_events     resetdata-export (Cloud Run JOB)     dashboard.html, which fetches
                                        reads the views → writes             /data.json and draws the charts
                                        resetdata.json to the private bucket
```

The job is **read-only on BigQuery** (it only SELECTs the views, across all three raw datasets, and writes
JSON to GCS). The data contract is matched by name across three files:
`sql/*.sql view column → job/main.py env key → dashboard.html data.* key`.

## Deploy / refresh (PowerShell, project `bidbrain-analytics`, region `australia-southeast1`)

**First-time stand-up:** `.\client_resetdata\deploy_resetdata.ps1` once (idempotent — bucket, dataset,
SAs, IAM, secrets, both Cloud Run units, the daily scheduler). The job SA gets **project-scoped**
`roles/bigquery.dataViewer`, which covers all three raw datasets — don't narrow it. After that:

```powershell
# ① edited a view (sql/*.sql) → reapply + re-run the job:
.\client_resetdata\sql\deploy_views_resetdata.ps1
# ② edited job/main.py (JSON shape) → rebuild + deploy + run the job:
.\client_resetdata\job\deploy_job_resetdata.ps1
# ③ edited dash/dashboard.html or dash/main.py → rebuild + redeploy the service:
.\client_resetdata\dash\deploy_dash_resetdata.ps1
```

> **Views are applied via `create_views.py` (the venv python BigQuery client), NOT `Get-Content | bq query`** —
> one filter contains an en-dash (`Reset backup – Ad account`) and WinPS `Get-Content` re-encoding corrupts
> non-ASCII SQL. `create_views.py` reads files as UTF-8. (It needs ADC authed as an account with access to
> `bidbrain-analytics` — `gcloud auth application-default login`.) Never run `gcloud builds submit --config
> cloudbuild.yaml` from a laptop (fails on `iam.serviceaccounts.actAs`); build the image + deploy as yourself.

## Branding

Skinned to **ResetData's brand**: crimson-pink accent (`#E84A6F`, from the logo + website) on deep navy.
The **100% Digital** agency mark and the **ResetData** wordmark are inlined as base64 (sourced from
[`creatives/`](creatives/README.md)) — agency mark · divider · client wordmark in the topbar and on the login
page. `agency_slug` in the data is `100-digital`. To re-skin later, edit the `:root` palette + the `.logo`
block in `dash/dashboard.html` and the `LOGIN_HTML` block in `dash/main.py`.

## What was skipped / noted (no-blockers)

- **Revenue / ROAS / AOV / transactions** — omitted entirely (B2B; `total_revenue` & `transactions` are 0).
- **Trade Desk conversions** — none reported upstream (`conversions` JSON null) → no TTD cost-per-lead.
- **GA4 conversion volume** — modest; shown honestly as directional (see above).
- **Country filter** — none (AU-only).

## Coordinates

| | |
|---|---|
| BigQuery dataset | `client_resetdata` (19 views) |
| Data bucket / object | `bidbrain-analytics-resetdata-dash` / `resetdata.json` |
| Export job | `resetdata-export` (runtime SA `resetdata-dash-job@…`, read-only BQ + bucket write) |
| Web service | `resetdata-dash` (runtime SA `resetdata-dash-web@…`) → [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `resetdata-dash-password` · `resetdata-dash-session-key` |
| Refresh | Cloud Scheduler `resetdata-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |

## Files

- [`sql/`](sql/README.md) — 19 BigQuery views (filter + model); `create_views.py` applies them in `NN_` order.
- [`job/`](job/README.md) — the export job (stage 2): views → `resetdata.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`creatives/`](creatives/README.md) — branding source assets (the ResetData wordmark + a site
  screenshot), now wired in as inline base64 / the sampled palette.
- [`data/`](data/) — a one-off reference export (`resetdata_reddit_febmar26.csv`, Reddit Feb–Mar 2026
  ad delivery). **Not read by the views/job** — the pipeline has no Reddit source; it's only a manual
  reference (Reddit traffic shows up inside the GA4 Paid Social channel). The repo-wide Windsor Reddit
  loader (`raw_windsor.perf_reddit`) is separate and unused here.
