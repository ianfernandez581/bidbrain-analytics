# clients/client_caltex/job/ — the Export Job (stage 2: BigQuery views → `caltex.json`)

> A **Cloud Run Job** (`caltex-export`) that reads this client's BigQuery views, assembles one
> tidy JSON file, and uploads it to the private data bucket. It runs, finishes, and stops.

**Plain English:** this is the *kitchen*. On a frequent schedule (every 10 minutes — and whenever
run by hand) it checks whether the shared Windsor Trade Desk table actually moved, and only if it
did does it read the prepared views, pack them into the single file the dashboard reads
(`caltex.json`), and put that file in locked storage. It does **not** talk to The Trade Desk or
Windsor — the shared [`ingest/windsor_data_pull/tradedesk/`](../../../ingest/windsor_data_pull/tradedesk/README.md)
loader already landed the raw rows; this client's [`sql/`](../sql/README.md) views did the
filtering and shaping. This job just reads those views and serialises the result.

**Where this sits:** `raw_windsor.perf_the_trade_desk` → [`../sql/`](../sql/README.md) views →
**[this job]** → `gs://bidbrain-analytics-caltex-dash/caltex.json` → [`../dash/`](../dash/README.md) serves it.

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. Runs the freshness gate (on `raw_windsor.perf_the_trade_desk`), then (only if stale or `FORCE_REBUILD=1`) reads `fact`/`targets`/`budget`, builds the payload, uploads `caltex.json`, and writes the watermark. `CLIENT = "caltex"` — dataset/bucket/object all derive from it. |
| [`freshness.py`](freshness.py) | The shared self-gating helper, vendored per job folder (`probe_bq_last_modified`, `read_watermark`/`write_watermark`, `is_stale`). No heavy top-level imports so a no-op tick stays light. |
| [`Dockerfile`](Dockerfile) / [`requirements.txt`](requirements.txt) / [`cloudbuild.yaml`](cloudbuild.yaml) | Standard job image (`google-cloud-bigquery` + `google-cloud-storage`); cloudbuild is for a future push-to-main trigger — deploys are manual. |
| [`deploy_job_caltex.ps1`](deploy_job_caltex.ps1) | Per-stage deploy: rebuild + deploy + run the JOB (use after editing `main.py`). |

## The JSON contract (matched BY NAME across the 3 stages)

`caltex.json` = `{meta, flight, benchmarks, targets, rows[]}`:

- **meta** — client/title/currency (AUD), `channel` ("The Trade Desk (programmatic display)"),
  `action_source_label` ("TTD pixel-attributed"), `last_updated`, `data_through`,
  `date_min`/`date_max`, `row_count`. (The baked placeholder adds `placeholder: true`.)
- **flight** — full-flight pacing (independent of the dashboard's date filter): start/end/budget/
  days, `daily_pace`, `pace_expected`, `projected_spend`, `spend_to_date`,
  `impressions_to_date`, `actions_to_date`.
- **benchmarks** — numeric targets the UI compares against: `cpm`, `ctr`, `cpc`,
  `impressions_target`, `daily_pace`, `flight_budget`.
- **targets** — the raw seed rows `{key: {value, status}}` (`PENDING` = a planning assumption
  awaiting sign-off; the UI marks these).
- **rows[]** — the fact, one row per (date × campaign × ad group × creative): `date`,
  `campaign_id`/`campaign`, `ad_group_id`/`ad_group`, `tactic`, `market`, `creative_id`/`creative`,
  `ad_format`, `stage` (Awareness/Consideration), `spend`, `impressions`, `clicks`,
  `video_starts`/`video_25`/`video_50`/`video_75`/`video_completes`, `pv_conv`, `pc_conv`.
  Ratios (CTR/CPM/CPC/cost-per-action/completion) are NEVER shipped — the dashboard recomputes
  them from summed components so any date sub-range is exact.

Renaming a key here breaks `dashboard.html` — fix both ends in the same change.

## Self-gating freshness (every 10 min, rebuild only on real change)

Per the repo CLAUDE.md "Freshness contract": Cloud Scheduler ticks `*/10` UTC
([`../scheduler.ps1`](../scheduler.ps1)); each tick probes
`raw_windsor.perf_the_trade_desk.__TABLES__.last_modified` (metadata-only), compares to the
`_freshness.json` watermark in this client's bucket, and exits 0 unless the upstream advanced.
Order matters: upload `caltex.json` **first**, watermark **second**. Static re-seeds
(targets/budget via `../seed_static.py`) and view-only edits don't move the gate — run with
`--update-env-vars FORCE_REBUILD=1`.

## See also

- [`../README.md`](../README.md) — client overview · [`../sql/README.md`](../sql/README.md) — the views · [`../dash/README.md`](../dash/README.md) — the web app.
