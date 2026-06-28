# client_geocon — Gateway Braddon (Meta paid media)

Self-hosted paid-media dashboard for **Geocon's Gateway Braddon** residential launch.
**Single channel** (Meta — Facebook + Instagram), **single local market** (Canberra / ACT),
**lead generation** (Meta-reported enquiries). No Snowflake / Trade Desk / Salesforce /
Content-Syndication lane here — it is a lean, Meta-only client.

## Architecture — one fact table, rolled up in the browser (rebuilt 2026-06)

This client uses the **MongoDB pattern**: the export ships ONE compact per-(date × campaign × adset ×
ad) **fact table** (`rows[]`, ~200 rows) and the dashboard rolls EVERYTHING up **client-side** — KPIs,
by-campaign / by-stage / by-creative, the daily trend, the vs-benchmark Δ table, the segment
breakdown — filtered by the chosen **date range**. That is what makes the date-range filter and the
CSV "export all data" exact and free. The old per-rollup views (overview / by_campaign / by_ad /
daily / by_stage / fatigue) were removed — the browser computes them now.

```
 raw_windsor.perf_meta        sql: 01_stg_meta -> 02_fact      job/main.py           dash/dashboard.html
 (Windsor Meta connector,  →  client slice + funnel_stage,  →  reads fact+targets,→  fetches /data.json, rolls
  self-refreshing; shared)     one row per date x ad (fact);    writes fact + flight    up rows[] per the date
                               + 03_targets / 04_budget         + benchmarks            filter; draws everything
        │                             │                              │                          │
   (no stage-1 loader)         geocon-export JOB (stage 2)                          geocon-dash SERVICE (3)
```

The contract: `fact column → job rows[].key → dashboard rollups (agg / byStage / byCampaign / byAd /
dailyOf / fatigueOf)`. The JSON carries `meta`, `flight` (pacing context), `benchmarks` (numeric
targets), `targets` (raw + status), and `rows[]` (the fact). Ratios (CTR/CPM/CPC/CPL) are NEVER stored
— always recomputed from summed components client-side, so any date sub-range is exact. Reach is
summed across days (Meta reach is a deduped audience, not truly additive — kept summed for continuity;
frequency = impressions ÷ summed-reach).

| I want to change… | Edit |
|---|---|
| Campaign filter / funnel-stage mapping | `sql/01_stg_meta.sql` |
| The fact grain / fields shipped to the browser | `sql/02_fact.sql` + `job/main.py` `rows[]` |
| Lead / CPL / CTR / CPM / CPC / budget **targets + benchmarks** | `targets/targets.csv` · `targets/budget.csv` → `seed_static.py` → export `FORCE_REBUILD=1` |
| Flight / pacing math | `job/main.py` (`flight = {...}`, from the budget seed + today) |
| Charts, views, Δ table, segment breakdown, CSV export, the AI report deck | `dash/dashboard.html` |
| Login / how the JSON + `/report` are served | `dash/main.py` (rarely needed) |

## The dashboard (`dash/dashboard.html`)

One file, three **audience views** (top toggle): **Executive · Media Buyer · Client Story**.
Heritage-maroon theme; everything below honours the global **date range** (Last 7/14/30/90 days, custom,
or all-time) + a stage filter + search.

- **Executive** — KPI strip (vs targets), insight cards, the Performance-over-time chart, budget
  pacing, funnel health, spend & leads by stage, money flow.
- **Media Buyer** — a **Performance vs Targets Δ table** (green/red CPL/CTR/CPM/CPC deltas per
  campaign), a **segment breakdown** (spend by ad set, coloured by stage + a stage summary table),
  recommended moves, efficiency bubble maps, campaign + creative tables, budget burn, and a
  **fatigue watch** (weekly WoW frequency/CTR, ≥1,000-impression guard).
- **Client Story** — a plain-language read, spend doughnut, outcome bars, retargeting pool.

Two MongoDB/STT-grade capabilities every dashboard carries:
- **Performance-over-time chart** with **View by Month/Week/Day** grain + **Relative/Absolute axis**
  toggles (default Relative — lines indexed to peak=100; tooltips always show true values).
- **AI "Download report"** → a board-ready **3-slide deck** (What happened · Why · Recommended
  actions) previewed on-screen + a **Download Google Slides** `.pptx` export (PptxGenJS). KPI figures
  come VERBATIM from the live numbers; the model writes only the narrative. See below.

**CSV exports:** *Export tab* (the current view's table, honouring the date/stage/search filters) and
*Export all* (the full per-day, per-ad fact table).

## AI report (`dash/report.py` + `/report` in `dash/main.py`)

Two-stage Claude Opus 4.8 call (Stage A web-grounded analyst notes, Stage B strict-schema slide JSON),
re-templated for **Meta paid-social lead-gen**: single engine, funnel-stage framing, honest
"Meta-reported enquiries" labelling, the `area` taxonomy (`reach/traffic/leads/efficiency/budget` ·
`creative/audience/budget_pacing/landing_page/funnel`), no-PII / anti-injection guardrails. Falls back
to **Gemini** (`gemini-2.5-pro`) if Claude rate-limits / runs out of credit. The browser POSTs the
**whole-account** numbers (independent of the date filter), so the deck is stable and **cached per data
refresh** (`gs://…-geocon-dash/reports/…`, keyed by `client + data_through`).

- **One-time standup:** `dash/enable_report_geocon.ps1` (provisions IAM, mounts the `anthropic-api-key`
  + optional `gemini-api-key` secrets, sets the 900s timeout). After standup, normal redeploys keep it.

## Deploy (PowerShell; project `bidbrain-analytics`, region `australia-southeast1`)

Build the image, deploy as yourself — **do not** `gcloud builds submit --config cloudbuild.yaml` from a
laptop (its deploy step fails `iam.serviceaccounts.actAs`).

```powershell
# edited dash/dashboard.html, dash/main.py, or dash/report.py → rebuild + swap the SERVICE:
.\clients\client_geocon\dash\deploy_dash_geocon.ps1

# edited a sql/*.sql view → reapply views + re-run the JOB (FORCE_REBUILD bypasses the freshness gate):
.\.venv\Scripts\python.exe clients\client_geocon\create_views.py
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# edited job/main.py (the fact / JSON shape) → rebuild + swap + run the JOB:
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/geocon-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients\client_geocon\job --tag $IMG --region australia-southeast1
gcloud run jobs update  geocon-export --image $IMG --region australia-southeast1
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy is live immediately;
it always reads whatever `geocon.json` is currently in the bucket.

## Freshness

`geocon-export` is **self-gating** on a Cloud Scheduler `*/10` UTC tick (`scheduler.ps1`): each tick
cheaply probes whether `raw_windsor.perf_meta` advanced (`__TABLES__.last_modified` vs the
`_freshness.json` watermark) and rebuilds only when it did. Static re-seeds (targets/budget) don't move
the gate, so force them with `FORCE_REBUILD=1`. (Pacing is time-relative — `pace_expected` / projection
are computed from the wall clock at build time, so a no-data day leaves them a day stale until the next
rebuild; this is inherent to the gate and matches the other clients.)

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.perf_meta` (shared Windsor connector — no stage-1 loader here) |
| Views | `client_geocon.{stg_meta, fact, targets, budget}` (+ `seed_targets` / `seed_budget` tables) |
| Job / Service | `geocon-export` / `geocon-dash` |
| Data bucket / file | `bidbrain-analytics-geocon-dash` / `geocon.json` (report cache in `reports/`) |
| Dash runtime SA | `geocon-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | `anthropic-api-key` (required) · `gemini-api-key` (optional fallback) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
