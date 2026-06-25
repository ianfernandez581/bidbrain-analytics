# clients/client_schneider/ — Schneider Electric (APAC) · **live (deployed 2026-06-04)**

> Schneider Electric's APAC **Content Syndication** programme (run via the agency **Transmission**) —
> a [`client_mongodb`](../client_mongodb/README.md)-style dashboard scoped to the **5 Salesforce
> lead-gen programs**. Filter the shared raw layers to SE's slice, model it in BigQuery views, export
> one JSON, serve it from a password-gated web app. Reporting currency **AUD**.

**Plain English:** Schneider runs lead-gen ("content syndication") for 5 programs — **Water &
Environment, EBA, Heavy Industries, Global Rebrand, AirSeT** — backed by 9 Salesforce campaigns. This
dashboard (modelled on MongoDB's) shows, per program: live **Salesforce leads vs the media-plan MQL+HQL
target** (Content Syndication tab), the **DV360 / Trade Desk / LinkedIn paid delivery** behind them
(Paid Media tab), and a **market-vs-market comparison** (CS Comparison tab).

**Status:** 🟢 **Live on GCP.** Restructured **2026-06-22** into a **3-tab mongodb clone** (Paid Media ·
Content Syndication · CS Comparison) **scoped to the 5 lead-gen programs** — the earlier 6-tab Pacific
paid-media dashboard is superseded. 27 BigQuery views + 7 CSV-loaded `seed_*` tables; `schneider.json`,
the `schneider-export` job and `schneider-dash` service deployed; the `*/10` self-gating scheduler runs.
Salesforce leads are **CRM-raw** (all status `New` — the CRM hasn't graded MQL/SQL/HQL yet), so the CS
tab shows total leads vs target, not "MQLs achieved". Targets/CPL come from the media plan
(`targets/media_plan.csv`, version-controlled — the committed-CSV→BQ targets standard); see
[`INTAKE.md`](INTAKE.md) for the client-flagged discrepancies (EBA MQL 157
vs old 300, W&E/Heavy/EBA budgets, NEL added).

## Data model (mongodb concept → Schneider source)
- **Campaign** (single-select seg) = the 5 programs (`water_env` · `eba` · `heavy` · `global_rebrand` · `airset`).
- **Programme** (the CS breakdown) = the Salesforce `pillar_label` (9), from `seed_salesforce_map`.
- **Market / Region chips** = normalized `COUNTRY_NAME` (Australia / New Zealand / ANZ / Other).
- **Target** (per campaign) = Σ MQL+HQL `lead_target` from `seed_media_plan`; **Plan CPL tiers** = each
  lead line's spend ÷ lead_target; **committed spend** = Σ lead-line spend; **flight** from `seed_plan_budget`.
- **Scoped to the 5:** `pm_delivery` (`sql/20`) is `WHERE program IN (the 5)`; the CS views read only the
  9 SF ids via `seed_salesforce_map`. The old Pacific `portfolio` toggle and the other ~20 APAC programs
  are **gone from the dashboard** — the seed tables still carry them for the `match_pattern` tagging.
  (Historical Pacific-carve-out EDA: [`_eda/pacific_eda.md`](_eda/pacific_eda.md).)

---

## What's different from STT (the archetype)
- **It's a [`client_mongodb`](../client_mongodb/) clone, not the STT layout** — 3 tabs, a single-select
  Campaign control, Region chips + a date picker, scoped to the 5 lead-gen programs (Schneider skin —
  the mongodb *layout*, Schneider's green/dark theme + logo).
- **Three ad platforms** (DV360 + TradeDesk + LinkedIn), AUD (USD→AUD @1.50, SGD→AUD @1.15 placeholders;
  LinkedIn currency inferred from the `_USD`/`_AUD`/`_SGD` account suffix). **No GA4 website tab** in the
  clone (the `40–46 ga4_*` views still apply but are unused by the job).
- **Salesforce Content Syndication is the focus**: `stg_salesforce` + `cs_by_programme` / `cs_weekly`
  (`sql/17–19`) read SE's 9 SF campaigns via `seed_salesforce_map`; `pm_delivery` (`sql/20`) tags paid
  delivery to its program via the `match_pattern` join (replicating the old client-side `idOf` in SQL,
  first-match-wins by `seq`), scoped to the 5.
- **Seeds are CSV-loaded** via [`load_seeds.py`](load_seeds.py) into `seed_*` tables. The media-plan
  **targets** (`media_plan` / `targets` / `plan_budget`) live in the VERSION-CONTROLLED
  [`targets/`](targets/) dir (the committed-CSV→BQ targets standard, routed by `SRC_DIRS`); the other
  seeds read from gitignored `data/` (currently BQ-only — see *Updating targets*).

## The 3 dashboard tabs (`dash/dashboard.html`)
Filters (global): **Campaign** (the 5 programs, single-select seg) · **Region** chips · **Date range**.
Default tab = **Content Syndication**, default campaign = the one with most leads (EBA today).

1. **Paid Media** — for the selected program: KPI snapshot (spend / imps / clicks / blended CPC), a
   **platform comparison** table (DV360 / TTD / LinkedIn), a daily delivery chart (Month/Week/Day +
   Relative/Absolute toggles), spend-by-platform + spend-by-market, a market table, and the **Flight
   windows across the portfolio** Gantt. Heavy / Global Rebrand have no paid delivery yet (leads-only) —
   the tab says so rather than showing zeros.
2. **Content Syndication** — Salesforce leads vs the media-plan **MQL+HQL** target: the snapshot strip
   (Overall / Pacing / Delivery / Outlook), the **Plan-CPL** banner, **Leads-vs-target** + **Progress**
   panels, a **Weekly pacing** chart (real dated weekly leads vs the even target pace), **Leads-by-market**
   + **Leads-by-programme** doughnuts, a by-market summary, and a programme × market table. Leads are
   **CRM-raw** (`New`) — total leads vs target, not "MQLs achieved".
3. **CS Comparison** — pick two markets (e.g. Australia vs New Zealand) for the selected program and
   compare lead volume, share, programme mix and weekly pacing side by side.

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
| Media-plan **targets** (media_plan / targets / plan_budget) | `targets/*.csv` (version-controlled) → re-run `load_seeds.py` | 2 |
| Other seeds (campaign_map / plan_flighting / channel_split / salesforce_map) | `data/*.csv` → `load_seeds.py` (NB: currently BQ-only, no committed CSV) | 2 |
| CS + paid views (`stg_salesforce` / `cs_by_programme` / `cs_weekly` / `pm_delivery`) | `sql/17–20_*.sql` | 2 |
| Which 5 programs are in scope | `data/salesforce_map.csv` (the 9 SF ids) + the `CS_PROGRAMS` list in `job/main.py` + `WHERE program IN (…)` in `sql/20_pm_delivery.sql` | 2 |
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

### Updating targets (committed CSV → BQ)

The media-plan **targets** are the version-controlled source of truth in [`targets/`](targets/)
(`media_plan.csv`, `targets.csv`, `plan_budget.csv`) — NOT gitignored `data/`. To change a target:
edit the CSV → `.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py` (reloads only those
3 seeds from `targets/`; `SRC_DIRS` routes them) → run the export job with `FORCE_REBUILD=1`. The other
seeds (campaign_map / plan_flighting / channel_split / salesforce_map) are **currently BQ-only** (no
committed CSV — they predate this standard); extract+commit them to `targets/` or `data/` if you want
schneider fully repo-reproducible.

## Deploy / refresh (copy-paste, PowerShell)
Project `bidbrain-analytics`, region `australia-southeast1`. **First-time stand-up:** run
[`deploy_schneider.ps1`](deploy_schneider.ps1) once (idempotent — bucket, dataset, SAs, IAM, secrets,
both Cloud Run units, scheduler; its step [5/7] now loads the seed CSVs before applying the views).
Note `deploy_schneider.ps1` seeds the scheduler at a fixed daily cron; [`scheduler.ps1`](scheduler.ps1)
flips it to the binding `*/10` self-gating cadence (the live schedule). **Prefer the per-stage scripts**
— [`deploy_seeds_schneider.ps1`](deploy_seeds_schneider.ps1) (edited `data/*.csv`),
[`sql/deploy_views_schneider.ps1`](sql/deploy_views_schneider.ps1) (edited a view — loads seeds first),
[`job/deploy_job_schneider.ps1`](job/deploy_job_schneider.ps1) (edited `job/main.py`),
[`dash/deploy_dash_schneider.ps1`](dash/deploy_dash_schneider.ps1) (edited the dashboard). The raw
commands each wraps:

```powershell
# ⓪ edited a seed CSV (data/*.csv) — reload the seed_* tables, then re-run the job (FORCE_REBUILD,
#    because seeds are NOT an upstream the freshness gate watches). load_seeds.py runs BEFORE views.
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# ① refresh data now (scheduler schneider-export-daily runs */10 UTC, self-gating)
.\.venv\Scripts\python.exe ingest\snowflake_data_pull\loader.py     # optional: refresh shared raw layer
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ② edited a view (sql/*.sql) — load seeds (stg_salesforce needs seed_salesforce_map), apply, re-run
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
.\.venv\Scripts\python.exe clients\client_schneider\create_views.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

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
| BigQuery dataset | `client_schneider` (27 views + 7 CSV-loaded `seed_*` tables) |
| Data bucket / object | `bidbrain-analytics-schneider-dash` / `schneider.json` |
| Export job | `schneider-export` (runtime SA `schneider-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `schneider-dash` (runtime SA `schneider-dash-web@…`) → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `schneider-dash-password` · `schneider-dash-session-key` |
| Refresh | Cloud Scheduler `schneider-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Domain (later) | `schneider.bidbrain.ai` (CNAME + Host Header Override, wired later) |

## Files
- [`data/`](data/) — the human-editable seed CSVs (campaign map / budgets / targets / flighting /
  channel split / media plan / salesforce map), loaded to `seed_*` tables by [`load_seeds.py`](load_seeds.py).
- [`sql/`](sql/README.md) — the 27 BigQuery views (filter + CS leads + paid delivery + unused GA4).
- [`job/`](job/README.md) — the export job (stage 2): views + seed tables → `schneider.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved data slice + open items handed to the client.

## See also
- [Root README](../../README.md) · the [`client_STT`](../client_STT/README.md) archetype · [`snowflake_data_pull`](../../ingest/snowflake_data_pull/README.md).
