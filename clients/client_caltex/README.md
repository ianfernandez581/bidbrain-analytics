# client_caltex — Caltex (100% Digital) — PLACEHOLDER / ONBOARDING

> **Status (2026-07-04): placeholder.** This is a full, Caltex-branded dashboard scaffold **cloned
> from `client_geocon`** (the lean Meta paid-media template) for onboarding **Caltex** as a **100%
> Digital** client. **No live data is connected yet** — the dashboard serves a baked-in SAMPLE payload
> (`dash/placeholder.json`, `meta.placeholder=true`) behind a loud "sample data — not connected yet"
> banner, so every tab, KPI tile and chart renders end-to-end for the demo. See
> [`dash/LIVE_URL.md`](dash/LIVE_URL.md) for stand-up + go-live steps.
>
> **Theme:** Caltex red (`#E4002B`) accent on a dark petrol-teal canvas, in the Bidbrain house style
> (the same recolour-the-`:root` approach used across resetdata/schneider/geocon). Logo = an inline
> SVG "CALTEX" wordmark (no binary asset). Regenerate the sample data with
> `.\.venv\Scripts\python.exe clients\client_caltex\gen_placeholder.py`.
>
> **TBD at onboarding (assumptions inherited from the geocon template — revisit with the client):**
> the real channel mix (this scaffold is Meta-only; Caltex may add Google/TTD/GA4), currency (AUD
> placeholder; Caltex is Singapore-facing so SGD may be right), markets, the `Caltex_*` campaign
> naming filter in `sql/01_stg_meta.sql`, and the target/benchmark values in `targets/*.csv`. The
> AI-report prompts in `dash/report.py` still carry the template's property-marketing framing.

Self-hosted paid-media dashboard scaffold. **Single channel** (Meta — Facebook + Instagram),
**lead generation** (enquiries). No Snowflake / Trade Desk / Salesforce / Content-Syndication lane —
it is a lean, Meta-only client, like geocon.

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
   (no stage-1 loader)         caltex-export JOB (stage 2)                          caltex-dash SERVICE (3)
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

**Rebuilt 2026-07 into the Bidbrain dark house style, branded to Caltex** (deep forest-green
canvas + a terracotta accent and the shared soft glow; modelled on `client_resetdata`). One file,
**three topic tabs**: **Overview · Paid Media · Creative**. Everything honours the shared **Looker
date-range picker**, **stage chips**, and search; time-series charts carry **VIEW BY Month/Week/Day +
AXIS Relative/Absolute** toggles (default Relative + Month).

- **North-star = qualified leads (MODELLED).** Meta reports RAW enquiries only, so qualified leads =
  `enquiries × qualification_rate_target` (0.20, PENDING) — shown with a "modelled · no CRM feed" badge
  and an explainer note, **never as a measured actual**. Wire a CRM feed to report true qualified leads.
  Green is reserved for that goal metric (house rule: green = goal/good only); enquiries=gold,
  spend=sage, cost=terracotta, CTR=amber.
- **Overview** — clickable KPI dot-cards (**Qualified · Enquiries · Spend** toggle their series on the
  hero), the delivery hero (spend bars + enquiries + modelled-qualified lines), budget pacing,
  spend-by-stage donut, the enquiry funnel, money-flow, and insight cards.
- **Paid Media** — a **Performance vs Targets Δ table** (CPL/CTR/CPM/CPC per campaign), spend-by-ad-set,
  budget burn, the per-ad table (thin-volume guard: ⚠ under 15k impressions or <8 leads), and a
  **fatigue watch** (weekly WoW frequency/CTR, ≥1,000-impression guard).
- **Creative** — the **top 10 creatives by spend**: real ad headline + body copy + metrics, with the
  real Meta ad image, a lightbox showing the full copy + a landing-page link. **Meta signs
  `thumbnail_url` with only a ~4-day validity**, so we cache the image bytes to our own bucket and serve
  them durably: the export job (`job/main.py` → `cache_creative_images`) downloads each top creative's
  thumbnail — using the **freshest** (latest-date) signed URL per creative — to
  `gs://bidbrain-analytics-caltex-dash/creatives/<creative_id>` (skips ones already cached), and the dash
  serves them at **`/creative-img/<creative_id>`** (same auth as `/data.json`). The gallery `<img>` falls
  back **cache → live CDN URL → branded tile** (`ccImgErr` in `dashboard.html`). Because the URL is only
  fetchable for a few days, the *export must run while it's live* — the freshness gate fires the export
  within ~10 min of the Windsor loader re-pulling `perf_meta` (which re-signs the URL), so active
  creatives get a permanent copy on that next run. A creative that's paused before it was ever cached
  can't be recovered (its URL is dead); a one-off backfill (pull fresh URLs from Windsor →
  `gcloud storage cp` into `creatives/`) can seed those.

Login password lives in Secret Manager `caltex-dash-password` (mounted `DASH_PASSWORD`); agency = **100% Digital**.

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
refresh** (`gs://…-caltex-dash/reports/…`, keyed by `client + data_through`).

- **One-time standup:** `dash/enable_report_caltex.ps1` (provisions IAM, mounts the `anthropic-api-key`
  + optional `gemini-api-key` secrets, sets the 900s timeout). After standup, normal redeploys keep it.

## Deploy (PowerShell; project `bidbrain-analytics`, region `australia-southeast1`)

Build the image, deploy as yourself — **do not** `gcloud builds submit --config cloudbuild.yaml` from a
laptop (its deploy step fails `iam.serviceaccounts.actAs`).

```powershell
# edited dash/dashboard.html, dash/main.py, or dash/report.py → rebuild + swap the SERVICE:
.\clients\client_caltex\dash\deploy_dash_caltex.ps1

# edited a sql/*.sql view → reapply views + re-run the JOB (FORCE_REBUILD bypasses the freshness gate):
.\.venv\Scripts\python.exe clients\client_caltex\create_views.py
gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# edited job/main.py (the fact / JSON shape) → rebuild + swap + run the JOB:
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/caltex-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients\client_caltex\job --tag $IMG --region australia-southeast1
gcloud run jobs update  caltex-export --image $IMG --region australia-southeast1
gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

## Meta breakdowns — audience (age×gender) + placement (`ingest/meta_breakdown_pull.py`)

The **Audience** and **Placement** charts read `client_caltex.breakdowns` (view over the ISOLATED table
`raw_windsor.caltex_meta_breakdown`). This is a **separate, caltex-only** pull — it does **NOT** touch the
shared `raw_windsor.perf_meta` loader/table (Windsor breakdowns multiply the row grain: age×gender×placement).
Region was pulled but is ~100% ACT (single market) so it isn't charted. It's a **manual refresh** (not
scheduled) — re-run when you want fresh audience/placement data:

```powershell
# scratchpad path for the NDJSON is arbitrary
$env:WINDSOR_API_KEY = (gcloud secrets versions access latest --secret=windsor-api-key)
.\.venv\Scripts\python.exe clients\client_caltex\ingest\meta_breakdown_pull.py 2026-05-01 <today> out.ndjson
bq load --replace --source_format=NEWLINE_DELIMITED_JSON raw_windsor.caltex_meta_breakdown out.ndjson `
  date:DATE,campaign:STRING,breakdown:STRING,seg1:STRING,seg2:STRING,impressions:INTEGER,reach:INTEGER,clicks:INTEGER,link_clicks:INTEGER,spend:FLOAT,leads:INTEGER
# then re-run the export job so caltex.json picks it up (FORCE_REBUILD as above)
```
The `caltex-export` job tolerates the table's absence (`breakdowns` → `[]`), so the dashboard never breaks
if the pull hasn't run. **Real qualified leads** still need a client CRM feed (the north-star is modelled ×20%).


The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy is live immediately;
it always reads whatever `caltex.json` is currently in the bucket.

## Freshness

`caltex-export` is **self-gating** on a Cloud Scheduler `*/10` UTC tick (`scheduler.ps1`): each tick
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
| Views | `client_caltex.{stg_meta, fact, targets, budget}` (+ `seed_targets` / `seed_budget` tables) |
| Job / Service | `caltex-export` / `caltex-dash` |
| Data bucket / file | `bidbrain-analytics-caltex-dash` / `caltex.json` (report cache in `reports/`) |
| Dash runtime SA | `caltex-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | `anthropic-api-key` (required) · `gemini-api-key` (optional fallback) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
