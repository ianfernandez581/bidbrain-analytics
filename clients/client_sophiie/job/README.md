# clients/client_sophiie/job/ — the Export Job (stage 2: BigQuery views → `sophiie.json`)

> A **Cloud Run Job** (`sophiie-export`) that reads this client's BigQuery views, assembles one
> tidy JSON file, and uploads it to the private data bucket. It runs, finishes, and stops.

**Plain English:** this is the *kitchen*. On a frequent schedule (every 10 minutes — and whenever
run by hand) it checks whether the shared Windsor Trade Desk table actually moved, and only if it
did does it read the prepared views, pack them into the single file the dashboard reads
(`sophiie.json`), and put that file in locked storage. It does **not** talk to The Trade Desk or
Windsor — the shared [`ingest/windsor_data_pull/tradedesk/`](../../../ingest/windsor_data_pull/tradedesk/README.md)
loader already landed the raw rows; this client's [`sql/`](../sql/README.md) views did the
filtering and shaping. This job just reads those views and serialises the result.

**Where this sits:** `raw_windsor.perf_the_trade_desk` → [`../sql/`](../sql/README.md) views →
**[this job]** → `gs://bidbrain-analytics-sophiie-dash/sophiie.json` → [`../dash/`](../dash/README.md) serves it.

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. Runs the freshness gate (on `raw_windsor.perf_the_trade_desk`), then (only if stale or `FORCE_REBUILD=1`) reads `fact`/`targets`/`budget`, builds the payload, uploads `sophiie.json`, and writes the watermark. `CLIENT = "sophiie"` — dataset/bucket/object all derive from it. |
| [`freshness.py`](freshness.py) | The shared self-gating helper, vendored per job folder (`probe_bq_last_modified`, `read_watermark`/`write_watermark`, `is_stale`). No heavy top-level imports so a no-op tick stays light. |
| [`Dockerfile`](Dockerfile) / [`requirements.txt`](requirements.txt) / [`cloudbuild.yaml`](cloudbuild.yaml) | Standard job image (`google-cloud-bigquery` + `google-cloud-storage`); cloudbuild is for a future push-to-main trigger — deploys are manual. |
| [`deploy_job_sophiie.ps1`](deploy_job_sophiie.ps1) | Per-stage deploy: rebuild + deploy + run the JOB (use after editing `main.py`). |

## The JSON contract (matched BY NAME across the 3 stages)

`sophiie.json` = `{meta, flight, benchmarks, targets, rows[]}`:

- **meta** - client/title/currency (AUD), `channel` ("The Trade Desk (programmatic display)"),
  `action_source_label` ("Sign up . TTD-attributed"), `last_updated`, `data_through`,
  `date_min`/`date_max`, `row_count`, and `conversion_slots` (which anonymous Trade Desk conversion
  slots are actually reporting - see the sign-up note below). The baked placeholder adds
  `placeholder: true`, which is the ONLY tell the dashboard uses to show its sample-data banner.
- **flight** - full-flight pacing (independent of the dashboard's date filter): start/end/budget/
  days, `daily_pace`, `pace_expected`, `projected_spend`, `spend_to_date`, `impressions_to_date`,
  `clicks_to_date`, `signups_to_date`.
- **benchmarks** - numeric targets the UI compares against: `cpa`, `cpc`, `ctr`, `cpm`,
  `impressions_target`, `signups_target`, `daily_pace`, `flight_budget`.
- **targets** - the raw seed rows `{key: {value, status}}`. `status` is load-bearing: `HARD` = the
  campaign's own committed KPI settings in The Trade Desk (CPA / CPC / CTR / budget / flight dates);
  `DERIVED` = our own arithmetic on those (CPM, the impression target, the sign-up volume target),
  which every dashboard surface LABELS so a red delta never accuses the campaign of missing a KPI
  nobody agreed to; `PENDING` = a planning assumption awaiting sign-off.
- **rows[]** - the fact, one row per (date x campaign x ad group x creative): `date`,
  `campaign_id`/`campaign`, `ad_group_id`/`ad_group`, `tier`, `market`, `creative_id`/`creative`,
  `ad_format`, `stage` (Awareness / Consideration / Conversion / Unclassified), `spend`,
  `impressions`, `clicks`, `video_starts`/`video_25`/`video_50`/`video_75`/`video_completes`,
  `pv_conv`, `pc_conv`, `vw_viewed`, `vw_tracked`.
  Ratios (CTR/CPM/CPC/CPA/completion) are NEVER shipped - the dashboard recomputes them from summed
  components so any date sub-range is exact.

**SIGN-UPS.** `pv_conv` + `pc_conv` are the conversions The Trade Desk attributed to this campaign
on its "Sign up" conversion source, post-view and post-click. Windsor exposes TTD conversions only
as anonymous NUMBERED slots with no pixel name, and this campaign has TWO conversion sources
attached ("Sign up +1"), so `sql/01_stg_ttd.sql` sums all 12 slots per kind and carries the slot
names forward. **The job WARNs whenever more than one slot reports** - when that happens, identify
each slot in The Trade Desk and SPLIT the non-sign-up action out in `sql/01`, rather than leaving
two different actions folded into one "sign-ups" number.

**FUNNEL STAGE.** `sql/01` maps the ad group's trailing token (`AWR` / `CONSID` / `CONV`) and sends
anything else to `Unclassified` rather than defaulting it to a real stage - so a rename in The Trade
Desk shows up as a named WARNING here and a visible chip on the dashboard instead of quietly filing
a retargeting ad group under Awareness.

Renaming a key here breaks `dashboard.html` - fix both ends in the same change.

## Self-gating freshness (every 10 min, rebuild only on real change)

Per the repo CLAUDE.md "Freshness contract": Cloud Scheduler ticks `*/10` UTC
([`../scheduler.ps1`](../scheduler.ps1)); each tick probes
`raw_windsor.perf_the_trade_desk.__TABLES__.last_modified` (metadata-only), compares to the
`_freshness.json` watermark in this client's bucket, and exits 0 unless the upstream advanced.
Order matters: upload `sophiie.json` **first**, watermark **second**. Static re-seeds
(targets/budget via `../seed_static.py`) and view-only edits don't move the gate — run with
`--update-env-vars FORCE_REBUILD=1`.

## See also

- [`../README.md`](../README.md) — client overview · [`../sql/README.md`](../sql/README.md) — the views · [`../dash/README.md`](../dash/README.md) — the web app.
