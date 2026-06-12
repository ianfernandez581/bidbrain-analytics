# windsor_data_pull/ — pull ad-platform + analytics performance into BigQuery (`raw_windsor`)

> One of the two **shared ingest** units. Loads ad-platform performance (Meta, Trade Desk) and
> web-analytics outcomes (GA4) from **Windsor.ai** into the shared BigQuery dataset
> `raw_windsor`, for all clients. The Windsor sibling of
> [`snowflake_data_pull/`](../snowflake_data_pull/) (which fills `raw_snowflake`).

**Plain English:** Windsor.ai is a connector service that pulls numbers out of advertising
platforms (how many people saw an ad, clicked it, what it cost) and out of Google Analytics
(what those clicks then did on the website). This unit fetches that data through Windsor's API
and stores it tidily in our warehouse, one shared copy that any client dashboard can read from.
Unlike the Snowflake copy, these loaders are **incremental** — they only fetch what's new and
safely re-run without creating duplicates.

**Where this sits in the pipeline:**

```
Ad platforms ──► Windsor.ai API ──[these loaders]──► BigQuery raw_windsor.*  ──► client views read their slice
```

---

## What's in here

| Path | What it does |
|---|---|
| [`create_dataset.py`](create_dataset.py) | **One-time, run FIRST.** Creates the shared `raw_windsor` dataset. Lives at this level because the dataset belongs to *all* loaders, not to any one. Idempotent. |
| [`meta/`](meta/README.md) | The **Meta / Facebook** loader (`perf_meta`) + its table-creation script. One row per (ad × date). [Open its README →](meta/README.md) |
| [`tradedesk/`](tradedesk/README.md) | The **Trade Desk** loader (`perf_the_trade_desk`) + its table-creation script. One row per (campaign × ad-group × creative × date × ad-format). [Open its README →](tradedesk/README.md) |
| [`ga4/`](ga4/README.md) | The **Google Analytics 4** loaders + their table-creation scripts. The acquisition loader (`perf_ga4`) — on-site outcomes (sessions, engagement, revenue), one row per (property × date × session source/medium/campaign × channel group) — plus an event-grain sibling (`perf_ga4_events`, one row per property × date × event_name). [Open its README →](ga4/README.md) |
| [`reddit/`](reddit/README.md) | The **Reddit Ads** loader (`perf_reddit`) + its table-creation script. One row per (account × ad × date), via the blended `/all` endpoint. [Open its README →](reddit/README.md) |
| `README.md` | This file. |

---

## First-time setup order

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\create_dataset.py                       # 1. the shared dataset
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\create_trade_desk__tables.py  # 2. the TTD table
.\.venv\Scripts\python.exe windsor_data_pull\meta\create_meta_table.py               # 3. the Meta table
.\.venv\Scripts\python.exe windsor_data_pull\ga4\create_ga4_table.py                 # 4. the GA4 acquisition table
.\.venv\Scripts\python.exe windsor_data_pull\ga4\create_ga4_events_table.py          # 5. the GA4 events table
.\.venv\Scripts\python.exe windsor_data_pull\reddit\create_reddit_table.py           # 6. the Reddit table
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py                     # 7. first load (backfills)
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\tradedesk_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\ga4\ga4_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\ga4\events_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\reddit\reddit_loader.py
```

**Auth:** Windsor API key + BigQuery + Storage all via **Application Default Credentials** —
no gcloud-path or machine-specific config baked in, so the same code runs locally
(after `gcloud auth application-default login`) and on Cloud Run/Cloud Build. The key itself
is read from Secret Manager (`windsor-api-key`). Run [`scripts/start_day.ps1`](../scripts/README.md)
first to confirm both credential systems are valid.

---

## How the loaders work (shared design)

All three loaders share the same per-chunk pipeline, so once you understand one you understand them all:

1. **Fetch in date chunks** from the Windsor API (`CHUNK_DAYS` per loader — Meta & Trade Desk
   `3`, GA4 acquisition `14`, GA4 events `200`), with capped-backoff **retries** on transient
   errors (timeouts, 429, 5xx) and **fail-fast** on permanent 4xx (bad field / auth). An
   unattended/scheduled run can't hang forever.
2. **Cache each chunk** to disk so a re-run doesn't re-fetch what it already has (`--force`
   overrides).
3. **Transform** the raw row into the table's typed schema, keeping the full original row in a
   `raw_row` JSON column for fidelity.
4. **Load → staging table → `MERGE`** into the main table on a natural key, so re-pulling a
   day is **idempotent** (no duplicates; revised metrics overwrite).

**Run modes (all three loaders):**

| Invocation | Mode |
|---|---|
| no args | **The normal/scheduled run.** Meta & GA4 = incremental per-account/property (forward from each one's last day; brand-new ones get a full backward-walk backfill). Trade Desk = backward walk that auto-discovers how far back data exists. |
| two dates, e.g. `… 2026-05-25 2026-05-30` | **Fixed range** (all accounts/properties together) — a targeted re-pull. |
| append `--force` | re-fetch even cached chunks (the MERGE stays idempotent). |

GA4 adds one wrinkle on top of this shared model — each chunk is fetched in **two metric-group
passes** (the GA4 Data API caps a request at 9 dims / 10 metrics) and merged before the MERGE.
See [`ga4/README.md`](ga4/README.md).

**Runtime artifacts** (cached chunk JSON, logs, temp NDJSON) are written to a `_run/` folder
**next to each loader**, anchored via `__file__` — never the repo root, never committed
(`_run/` is gitignored).

**Shared infrastructure:** all three loaders stage NDJSON through the `bidbrain-analytics-staging`
GCS bucket before the BigQuery `MERGE`. Every table is **partitioned by `metric_date`** and
**clustered** for cheap, fast slicing. Each tags every row with `client_slug` / `agency_slug`
inferred from the account/property/campaign names (see the `CLIENT_TO_AGENCY` map in each loader;
GA4 also supports an explicit `PROPERTY_TO_CLIENT` override, since property names are often generic).

---

## See also

- [`meta/README.md`](meta/README.md), [`tradedesk/README.md`](tradedesk/README.md), and [`ga4/README.md`](ga4/README.md) — per-loader detail (schemas, fields, MERGE keys, caveats).
- [`snowflake_data_pull/`](../snowflake_data_pull/README.md) — the other shared ingest unit.
- [Root README §6.1](../README.md#61-the-layered-bigquery-model) — how the raw layers feed clients.
