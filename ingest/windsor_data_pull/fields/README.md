# windsor_data_pull/fields/ — the Windsor field CATALOGUE (`raw_windsor.windsor_fields`)

> The odd one out among the windsor loaders: it loads **metadata, not performance data**. It
> mirrors Windsor.ai's entire field reference — every field token you can pass in `fields=`, and
> which connectors each one works in — into BigQuery, refreshed daily so we can **see when Windsor
> adds new fields**.

**Plain English:** the public page [windsor.ai/data-field/all](https://windsor.ai/data-field/all/)
lists every column Windsor can give you, across all ~242 connectors (~37.8k fields). That page is
backed by a JSON endpoint (`https://connectors.windsor.ai/all/fields`). This loader pulls that JSON
into `raw_windsor.windsor_fields` once a day so the catalogue is queryable in BigQuery and we get a
dated history of what's available — instead of a 9 MB file rotting in git.

## Why it's in BigQuery, not a file
The catalogue is ~9 MB of JSON and grows as Windsor adds connectors. It does **not** belong in the
repo. It lives in `raw_windsor` like every other Windsor table.

## The table — `raw_windsor.windsor_fields`
One row per field `id`. Created by [`create_fields_table.py`](create_fields_table.py).

| Column | Meaning |
|---|---|
| `id` | The field token (what you pass in `fields=`). **MERGE key.** |
| `name` / `description` / `type` | As Windsor reports them (`type` ∈ TEXT/NUMERIC/OBJECT/BOOLEAN/TIMESTAMP/DATE/PERCENT/COUNTRY/CITY/IMAGE_URL/REGION). |
| `available_in_connectors` | `ARRAY<STRING>` of connector slugs the field works in (`facebook`, `google_ads`, `googleanalytics4`, …). The catalogue's reason to exist. |
| `n_connectors` | `len(available_in_connectors)` — cheap filter/sort. |
| `first_seen` | Date the id was **first observed** → `WHERE first_seen = CURRENT_DATE()` is **"new today"**. |
| `last_seen` | Most recent run that still saw it → `last_seen < CURRENT_DATE()` is **"dropped from the catalogue"**. |
| `snapshot_date` / `ingested_at` / `source` / `raw_row` | Provenance + full original object. |

Not partitioned (small, slowly-changing); clustered by `type`, `id`.

## New-field detection (the point of refreshing daily)
We **never delete** rows — `first_seen`/`last_seen` carry the change history:
```sql
-- fields Windsor added today
SELECT id, name, type, available_in_connectors
FROM `bidbrain-analytics.raw_windsor.windsor_fields`
WHERE first_seen = CURRENT_DATE();

-- fields that disappeared (stopped showing up)
SELECT id FROM `bidbrain-analytics.raw_windsor.windsor_fields`
WHERE last_seen < CURRENT_DATE();

-- what can I pull from a given connector?
SELECT id, name, type FROM `bidbrain-analytics.raw_windsor.windsor_fields`
WHERE 'googleanalytics4' IN UNNEST(available_in_connectors) ORDER BY id;
```
The loader also prints `N new today` and lists the first 50 each run.

## How it works
1. GET `https://connectors.windsor.ai/all/fields` (a **public catalogue** — **no api_key**), capped-backoff retries.
2. Stage as NDJSON in `gs://bidbrain-analytics-staging/windsor_fields/`, load into a staging table.
3. `MERGE` on `id`: matched → refresh attrs + bump `last_seen`; unmatched → INSERT with `first_seen = today`.
4. Report new / dropped counts. Idempotent; no date arguments.

## Run
```powershell
.\.venv\Scripts\python.exe ingest\windsor_data_pull\fields\create_fields_table.py   # once
.\.venv\Scripts\python.exe ingest\windsor_data_pull\fields\fields_loader.py          # populate / refresh
```

## Deployment & schedule
Built + scheduled by [`scripts/deploy_ingest_jobs.ps1`](../../../scripts/deploy_ingest_jobs.ps1) as
Cloud Run job **`windsor-fields-ingest`**, cron **`45 21 * * *` UTC** (daily, after meta/tradedesk).
Runs as `ingest-runner@` — needs only the BigQuery + staging-bucket access that SA already has (the
catalogue endpoint is public, so **no `windsor-api-key`**).
```powershell
.\scripts\deploy_ingest_jobs.ps1 -Only fields          # build + deploy + schedule just this job
.\scripts\deploy_ingest_jobs.ps1 -Only fields -Run     # …and execute once
```

> **Freshness:** daily, like the other windsor loaders — **not** `*/10` self-gating. A field
> catalogue changes rarely; daily is plenty.
