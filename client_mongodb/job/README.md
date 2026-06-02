# client_mongodb/job/ — the Export Job (stage 2: BigQuery views → `mongodb.json`)

> A **Cloud Run Job** (`mongodb-export`) that reads this client's BigQuery views, assembles one
> tidy JSON file, and uploads it to the private data bucket. It runs, finishes, and stops.

**Plain English:** this is the *kitchen*. Once a day (and whenever we run it by hand) it pulls
the prepared numbers out of the warehouse, packs them into a single file the dashboard knows
how to read (`mongodb.json`), and puts that file in locked storage. It does **not** talk to
Snowflake — the shared [`snowflake_data_pull/`](../../snowflake_data_pull/README.md) already
mirrored the source data, and this client's [`sql/`](../sql/README.md) views did the filtering
and maths. This job just reads those views and serialises the result.

**Where this sits:** `raw_snowflake` → [`../sql/`](../sql/README.md) views → **[this job]** →
`gs://bidbrain-analytics-mongodb-dash/mongodb.json` → [`../dash/`](../dash/README.md) serves it.

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. Reads each view, builds the `env = {…}` payload, uploads `mongodb.json`. The one line that makes it client-specific is `CLIENT = "mongodb"` — everything (dataset, bucket, object name) derives from it. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim`, installs deps, runs as non-root `appuser`, `CMD python main.py`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run jobs deploy mongodb-export` (for a future push-to-`main` trigger; deploys are manual today). |
| [`requirements.txt`](requirements.txt) | Just `google-cloud-bigquery` + `google-cloud-storage` — no Snowflake, no pandas. |
| `.dockerignore` | Keeps the build context lean. |

---

## The JSON contract it produces

`main.py` reads the views in [`../sql/`](../sql/README.md) and emits this envelope (the
dashboard reads these keys **by name** — rename one here and you must fix `dashboard.html`):

```jsonc
{
  "last_updated": "2026-05-29T22:00:00Z",        // UTC ISO-8601
  "row_count": 1234,
  "window": { "start": "2026-04-01", "end": "2026-06-30", "days": 91 },
  "all_markets":    ["ANZ", "ASEAN", "INDIA", "KR-HK-TW"],
  "all_programmes": ["IDE", "IDC"],
  "rows":     [ /* paid-media per day: channel, date, week_start, programme, market, strategy, objective, imps, clicks, spend_usd, conversions, leads */ ],
  "targets":  [ /* programme, market, target, delivered */ ],
  "benchmarks_strategy": { /* keyed by strategy: { cpm, ctr, frequency, weight } */ },
  "benchmarks_market":   { /* keyed by market:   { budget_weight } */ },
  "budget":   [ /* programme, tradedesk_code, gross_usd, net_usd, start, end */ ],
  "cs":              [ /* market, total, accepted, rejected, new_pending, unresponsive, do_not_contact, last_lead_day */ ],
  "cs_by_programme": [ /* programme, market, total, accepted, new_pending, unresponsive, do_not_contact, last_lead_day (no 'rejected') */ ]
}
```

Source views, one per payload branch: `paid_media_model` → `rows`; `targets` → `targets`;
`benchmarks_strategy` / `benchmarks_market`; `budget`; `cs_leads` → `cs`;
`cs_leads_by_programme` → `cs_by_programme`. The `window` is computed from the min/max date in
`paid_media_model`.

---

## Run & deploy (manual today)

```powershell
# Run the daily refresh now (reads current views, rewrites mongodb.json):
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait

# If you edited main.py (changed the JSON shape) — build, swap the image, run:
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-export:$(git rev-parse --short HEAD)"
gcloud builds submit client_mongodb/job --tag $IMG --region australia-southeast1
gcloud run jobs update  mongodb-export --image $IMG --region australia-southeast1
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```

The daily schedule is created by [`../scheduler.ps1`](../scheduler.ps1) (Cloud Scheduler →
`mongodb-export` at 22:00 UTC).

---

## What it needs (when something breaks)

- Runtime SA `mongodb-dash-job@…` with **BigQuery** read/write on `client_mongodb` **and read
  on `raw_snowflake`** (the views read across to it), and **Storage** write on the bucket.
- The views must **exist** (run [`../create_views.py`](../create_views.py)) and `raw_snowflake`
  must be **populated** (run [`../../snowflake_data_pull/loader.py`](../../snowflake_data_pull/README.md)).
- It reads BigQuery and writes GCS only — **no Snowflake key, no env vars, no secrets** needed
  (contrast the Cloudflare job, which does pull Snowflake).

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../sql/README.md`](../sql/README.md) — the views this job reads (and their business logic).
- [`../dash/README.md`](../dash/README.md) — stage 3, which serves the file this job writes.
