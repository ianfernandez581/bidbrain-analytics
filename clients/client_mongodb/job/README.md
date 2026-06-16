# clients/client_mongodb/job/ — the Export Job (stage 2: BigQuery views → `mongodb.json`)

> A **Cloud Run Job** (`mongodb-export`) that reads this client's BigQuery views, assembles one
> tidy JSON file, and uploads it to the private data bucket. It runs, finishes, and stops.

**Plain English:** this is the *kitchen*. On a frequent schedule (every 10 minutes — and
whenever we run it by hand) it checks whether the warehouse data actually moved, and only if it
did does it pull the prepared numbers out, pack them into a single file the dashboard knows how
to read (`mongodb.json`), and put that file in locked storage. It does **not** talk to
Snowflake — the shared [`ingest/snowflake_data_pull/`](../../../ingest/snowflake_data_pull/README.md) already
mirrored the source data, and this client's [`sql/`](../sql/README.md) views did the filtering
and maths. This job just reads those views and serialises the result.

**Where this sits:** `raw_snowflake` → [`../sql/`](../sql/README.md) views → **[this job]** →
`gs://bidbrain-analytics-mongodb-dash/mongodb.json` → [`../dash/`](../dash/README.md) serves it.

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. Runs the freshness gate, then (only if stale) reads each view, builds the `env = {…}` payload, uploads `mongodb.json`, and writes the watermark. The one line that makes it client-specific is `CLIENT = "mongodb"` — everything (dataset, bucket, object name) derives from it. |
| [`freshness.py`](freshness.py) | The shared self-gating helper, vendored per job folder (`probe_bq_last_modified`, `read_watermark` / `write_watermark`, `is_stale`). No heavy top-level imports so a no-op tick stays a light container. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim`, installs deps, runs as non-root `appuser`, `COPY main.py freshness.py`, `CMD python main.py`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run jobs deploy mongodb-export` (for a future push-to-`main` trigger; deploys are manual today). |
| [`requirements.txt`](requirements.txt) | Just `google-cloud-bigquery` + `google-cloud-storage` — no Snowflake, no pandas. |
| `.dockerignore` | Keeps the build context lean. |

---

## Self-gating freshness (every 10 min, rebuild only on real change)

This job is **self-gating** (see the repo CLAUDE.md "Freshness contract"). Cloud Scheduler ticks
it every 10 minutes UTC ([`../scheduler.ps1`](../scheduler.ps1)), but each tick first does a
cheap metadata probe and **exits 0 without rebuilding unless the upstream actually advanced**:

- **Gate source** = the BigQuery raw tables this job's views read, set in `GATING_TABLES`:
  the live mirrors `raw_snowflake.tradedesk_apac_all` + `raw_snowflake.salesforce_cs_apac_all`
  (`SNOWFLAKE_TABLES`), **plus** the static pixel seed `client_mongodb.seed_tradedesk_pixel`
  (`SEED_TABLES`). It probes their `__TABLES__.last_modified_time` (metadata-only). Including the
  seed means re-running [`../seed_pixel.py`](../seed_pixel.py) advances the gate, so a fresh CSV
  rebuilds on the next tick with no `FORCE_REBUILD`. **`data_through` is derived from the Snowflake
  subset only** — never the seed's load time, which would overstate how current the live data is.
- **Watermark** = a tiny `_freshness.json` sidecar in this client's own bucket. Order matters:
  upload `mongodb.json` **first**, write the watermark **second**, so a failed upload simply
  retries next tick.
- **Manual override**: set `FORCE_REBUILD=1` to bypass the gate (e.g. after a hardcoded plan-table
  edit in `sql/`, which the gate doesn't watch — kick the job once by hand afterward).

Net effect: the dashboard refreshes within ~10 min of new upstream data; most ticks are a ~3s
no-op. The dashboard shows `last_updated` (this build's time); the job also emits `data_through`
(the newest upstream `last_modified`, UTC).

---

## The JSON contract it produces

`main.py` reads the views in [`../sql/`](../sql/README.md) and emits this envelope (the
dashboard reads these keys **by name** — rename one here and you must fix `dashboard.html`):

```jsonc
{
  "last_updated": "2026-06-13T02:00:00Z",        // UTC ISO-8601 — this build's time
  "data_through": "2026-06-13T01:50:00Z",        // newest upstream raw last_modified (UTC); may be null
  "row_count": 1234,
  "window": { "start": "2026-04-01", "end": "2026-06-30", "days": 91 },
  "all_markets":    ["ANZ", "ASEAN", "INDIA", "KR-HK-TW", "OTHER"],   // OTHER = leads outside the 4 plan markets (e.g. China, Japan); surfaced as a region so totals are complete
  "all_programmes": ["IDE", "IDC"],
  "rows":     [ /* paid-media per day: channel, date, week_start, programme, market, strategy, objective, imps, clicks, spend_usd, conversions, leads */ ],
  "targets":  [ /* programme, market, target, delivered, cpl (plan cost/lead; null for KGA IDC Report) */ ],
  "benchmarks_strategy": { /* keyed by strategy: { cpm, ctr, cpc, frequency, weight } */ },
  "benchmarks_market":   { /* keyed by market:   { budget_weight } */ },
  "budget":   [ /* programme, tradedesk_code, gross_usd, net_usd, start, end, est_cpc (committed blended CPC; null for DNB IDE) */ ],
  "cs":              [ /* market, total, accepted, rejected, new, last_lead_day (status buckets: Accepted / Rejected / New=Unresponsive+Do Not Contact+New) */ ],
  "cs_by_programme": [ /* programme, market, total, accepted, rejected, new, last_lead_day (same buckets; for KGA/IDC total & new = Unresponsive+Do Not Contact+New only) */ ],
  "pixel": {                                       // TTD Universal Pixel content-engagement snapshot; null if the seed/views are absent
    "summary": { /* start, end, days, imps, cost_usd, clicks, all_conv, content_total/click/view (6 named pixels), default_total/view/click (catch-all) */ },
    "assets":  [ /* key, asset, total, click, view — per named content landing page (Gartner MQ Leader, AI Readiness, …) */ ],
    "dims":    { "device": [...], "environment": [...], "format": [...] }   // each: { label, imps, cost_usd, clicks }
  }
}
```

Source views, one per payload branch: `paid_media_model` → `rows`; `targets` → `targets`;
`benchmarks_strategy` / `benchmarks_market`; `budget`; `cs_leads` → `cs`;
`cs_leads_by_programme` → `cs_by_programme`; `pixel_summary` / `pixel_assets` / `pixel_dims` →
`pixel` (wrapped in `try/except` → `null` if those views/seed don't exist yet). The `window` is
computed from the min/max date in `paid_media_model`.

---

## Run & deploy (manual today)

```powershell
# Run the refresh now (the gate still applies — pass FORCE_REBUILD=1 to bypass it,
# e.g. after editing a hardcoded plan table in sql/):
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait

# If you edited main.py (changed the JSON shape) — build, swap the image, run:
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_mongodb/job --tag $IMG --region australia-southeast1
gcloud run jobs update  mongodb-export --image $IMG --region australia-southeast1
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```

The schedule is created by [`../scheduler.ps1`](../scheduler.ps1) (Cloud Scheduler →
`mongodb-export` every 10 minutes UTC, job `mongodb-export-daily`). The job self-gates, so most
of those ticks are a ~3s no-op — see "Self-gating freshness" above.

---

## What it needs (when something breaks)

- Runtime SA `mongodb-dash-job@…` with **BigQuery** read/write on `client_mongodb` **and read
  on `raw_snowflake`** (the views read across to it), and **Storage** write on the bucket.
- The views must **exist** (run [`../create_views.py`](../create_views.py)) and `raw_snowflake`
  must be **populated** (run [`../../snowflake_data_pull/loader.py`](../../../ingest/snowflake_data_pull/README.md)).
- It reads BigQuery and writes GCS only — **no Snowflake key, no env vars, no secrets** needed
  (contrast the Cloudflare job, which does pull Snowflake).

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../sql/README.md`](../sql/README.md) — the views this job reads (and their business logic).
- [`../dash/README.md`](../dash/README.md) — stage 3, which serves the file this job writes.
