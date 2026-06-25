# ingest/neto_data_pull/ — mirror Neto / Maropost orders into BigQuery (`raw_neto`)

> A **shared ingest** unit — the third sibling of [`ingest/windsor_data_pull/`](../windsor_data_pull)
> (`raw_windsor`) and [`ingest/snowflake_data_pull/`](../snowflake_data_pull) (`raw_snowflake`). Loads
> **Neto / Maropost Commerce Cloud** orders into the shared BigQuery dataset `raw_neto` as a dumb
> raw mirror — **one table, `raw_neto.orders`**, one row per order. Same `raw_<source>` pattern,
> ADC auth + Secret Manager, idempotent staging→MERGE, crash-safe resumable backfill.

**Plain English:** Neto is the shopping-cart / POS / order-management platform behind **City Perfume**.
This unit pulls the orders — who bought what, when, for how much, paid how — out of Neto's API and lands
them tidily in our warehouse, one shared raw copy a client dashboard can read from. City Perfume is the
first (and today only) Neto store, but the layer stays **client-neutral**: no per-client filter and no
business logic here — every client dashboard applies its own `WHERE` / rollups in BigQuery views.

**Where this sits in the pipeline:**

```
Neto API (www.cityperfume.com.au)  ──[orders/orders_loader.py]──►  BigQuery raw_neto.orders  ──►  client views filter their slice (e.g. clients/client_cityperfume/sql/)
```

---

## What's in here

| Path | What it does |
|---|---|
| [`orders/`](orders/README.md) | **The loader.** `orders/orders_loader.py` POSTs `GetOrder` to the Neto API, walks 0-indexed pages, transforms, and `MERGE`s into `raw_neto.orders`; the `Dockerfile` here builds the **`neto-orders-ingest`** Cloud Run job. [Open its README →](orders/README.md) |
| [`reporting/`](reporting) | **SAMPLE** reporting views (NOT raw): `v_orders_overview.sql` (one row per order + derived customer history) and `v_sales.sql` (`UNNEST(order_lines)` → product grain). Committed only as worked examples of how to consume `raw_neto.orders`; move them into `clients/client_cityperfume/sql/` when wiring a dashboard. |
| `README.md` | This file. |

---

## Scheduling

The production refresh is the **`neto-orders-ingest`** Cloud Run job, built/deployed/scheduled by
[`scripts/deploy_ingest_jobs.ps1`](../../scripts/deploy_ingest_jobs.ps1) and run by the shared
`ingest-runner@` service account. Its Cloud Scheduler trigger is a **fixed daily `0 21 * * *` UTC**
cron (staggered before the 22:00 UTC `*-export` client jobs) — it is **not** the `*/10` self-gating
pattern (only `snowflake-ingest` self-gates today). See [`orders/README.md`](orders/README.md#scheduling--deployment-the-neto-orders-ingest-cloud-run-job).

---

## See also

- [`orders/README.md`](orders/README.md) — full loader detail (auth, pagination, schema, MERGE key, timezone convention, address-PII caveat).
- [`ingest/windsor_data_pull/`](../windsor_data_pull/README.md) & [`ingest/snowflake_data_pull/`](../snowflake_data_pull/README.md) — the other shared ingest units this mirrors.
- [`scripts/deploy_ingest_jobs.ps1`](../../scripts/deploy_ingest_jobs.ps1) — builds/deploys/schedules all five shared ingest jobs.
