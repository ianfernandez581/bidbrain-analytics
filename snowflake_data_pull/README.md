# snowflake_data_pull/ — mirror Snowflake into BigQuery (`raw_snowflake`)

> One of the two **shared ingest** units. Copies the Snowflake source tables into a shared
> BigQuery dataset (`raw_snowflake`), **once, for every client**. The Snowflake sibling of
> [`windsor_data_pull/`](../windsor_data_pull/) (which fills `raw_windsor`).

**Plain English:** a lot of our clients' raw data (Salesforce leads, ad-platform numbers)
lives in a separate warehouse called Snowflake, which we don't control. Rather than have every
client dashboard hammer Snowflake separately, we copy those source tables into our own
warehouse (BigQuery) **once per refresh**. Each client then picks out just their slice from
that shared copy. Adding a client becomes "write a view," and Snowflake is touched once, not
once-per-client.

**Where this sits in the pipeline:**

```
Snowflake (APAC_ALL_PLATFORM.PUBLIC.*)  ──[this unit]──►  BigQuery raw_snowflake.*  ──►  each client's sql/ views filter their slice
```

---

## What's in here

| File | What it does |
|---|---|
| [`create_dataset.py`](create_dataset.py) | **One-time.** Creates the shared `raw_snowflake` dataset in `australia-southeast1`. Idempotent (`exists_ok=True`). Run this first. |
| [`loader.py`](loader.py) | **The refresh.** Per-table **freshness-gated** (see below): `SELECT *` → `WRITE_TRUNCATE` into `raw_snowflake.*`, but only for tables whose Snowflake `LAST_ALTERED` advanced. No filter, no transform on the data — a dumb full copy of whatever changed. |
| [`freshness.py`](freshness.py) | The shared freshness gate (vendored, like `sf_connect`). Here it supplies `probe_snowflake_last_altered` for the per-table gate. See the repo `CLAUDE.md` "Freshness contract". |
| `README.md` | This file. |

---

## Freshness gate (per-table) — why it runs `*/10` but rarely pulls

This unit is **self-gating** (repo `CLAUDE.md` → "Freshness contract"). It runs on a `*/10` UTC
Cloud Scheduler tick (`snowflake-ingest`, set in [`../scripts/deploy_ingest_jobs.ps1`](../scripts/deploy_ingest_jobs.ps1)),
but each tick it first probes `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` for the source tables —
**metadata-only, no warehouse credits, never resumes `APAC_IN_WH`** — and re-mirrors only the
tables whose `LAST_ALTERED` advanced past the stored watermark. So a "nothing changed" tick costs
~nothing, and the shared raw layer is fresh within ~10 min of Snowflake updating (downstream client
dashboards then gate on these tables' BQ `last_modified`, so freshness composes down the chain).

- **Watermark:** a per-table BQ table `raw_snowflake._sync_state` (`table_name`, `last_altered`).
  Updated only **after** a table's successful re-load, so a failed load just retries next tick.
- **`FORCE_REBUILD=1`** re-mirrors every table regardless (for manual full refreshes).
- The watermark advances per table independently — TradeDesk landing at 02:43Z re-mirrors only
  `tradedesk_apac_all`, not the other six.

## What it pulls

A **dumb full copy** — `SELECT *`, no client filter, no transformation, on purpose. Every
client reads this one shared raw layer and applies its own `WHERE` + rollups in its own views.

| Snowflake source | → BigQuery table |
|---|---|
| `APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"` | `raw_snowflake.salesforce_cs_apac_all` |
| `APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"` | `raw_snowflake.tradedesk_apac_all` |
| `APAC_ALL_PLATFORM.PUBLIC."LinkedIn Ads - APAC"` | `raw_snowflake.linkedin_ads_apac` |
| `APAC_ALL_PLATFORM.PUBLIC."Reddit Ads - APAC_ALL"` | `raw_snowflake.reddit_ads_apac_all` |
| `APAC_ALL_PLATFORM.PUBLIC."DV360 - APAC"` | `raw_snowflake.dv360_apac` |
| `APAC_ALL_PLATFORM.PUBLIC."Google Ads - APAC"` | `raw_snowflake.google_ads_apac` |
| `APAC_ALL_PLATFORM.PUBLIC."Google Analytics Data_APAC ALL"` | `raw_snowflake.google_analytics_apac_all` |

**To add another source table:** add one line to the `TABLES` dict in [`loader.py`](loader.py).

---

## Run

```powershell
# use the repo's .venv Python (deps live there, not in global Python)
.\.venv\Scripts\python.exe snowflake_data_pull\create_dataset.py   # once — creates raw_snowflake
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py           # full WRITE_TRUNCATE refresh of every table
```

**Auth (same as every Snowflake-touching unit):** Snowflake key-pair from `$SNOWFLAKE_KEY`,
else pulled from Secret Manager (`snowflake-bq-key`) via ADC; BigQuery via ADC. Run
`gcloud auth application-default login` first if ADC isn't set up (or
[`scripts/start_day.ps1`](../scripts/README.md)).

**Snowflake coordinates (read-only):** account `ZGKGHOH-ISA98947`, user `BQ_SYNC_USER`,
warehouse `APAC_IN_WH`.

---

## How clients consume it

```sql
-- a client's staging view filters the shared raw table down to its slice:
CREATE OR REPLACE VIEW client_mongodb.stg_salesforce AS
SELECT ...
FROM   raw_snowflake.salesforce_cs_apac_all
WHERE  CAMPAIGN_ID IN ('701RG…','701RG…')   -- per-client filter
  AND  LEAD_STATUS != 'New';                  -- business rule
```

Today's consumers:
- **MongoDB** filters `tradedesk_apac_all` (by advertiser) and `salesforce_cs_apac_all` (by
  campaign IDs) — see [`client_mongodb/sql/`](../client_mongodb/sql/README.md).
- **Cloudflare** does *not* use `raw_snowflake` — its model lives in a separate Snowflake
  schema and its job pulls that directly (see [`client_cloudflare/`](../client_cloudflare/README.md)).
- **STT** filters `google_ads_apac`, `google_analytics_apac_all`, `linkedin_ads_apac`, and
  `dv360_apac` in its staging views (see [`client_STT/sql/`](../client_STT/sql/README.md)).

---

## Gotchas

- **Full refresh, not incremental.** Each run truncates and reloads every table — simple and
  always-correct, at the cost of re-pulling everything. (Contrast the Windsor loaders, which
  are incremental.) Fine while the tables are small.
- **Column names are uppercased** on load so client views can reference them predictably.
- A Snowflake **column rename** flows straight through (it's `SELECT *`) and will surface in
  the client view that reads that column by name — fix it in the client's `sql/`.

## See also

- [`windsor_data_pull/`](../windsor_data_pull/README.md) — the other shared ingest unit (`raw_windsor`).
- [Root README §6.1](../README.md#61-the-layered-bigquery-model) — how the raw layers fit the model.
