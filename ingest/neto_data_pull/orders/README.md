# ingest/neto_data_pull/orders/ — Neto / Maropost loader (`raw_neto.orders`)

> Loads **Neto / Maropost Commerce Cloud** orders (City Perfume's e-commerce platform) into
> BigQuery as a dumb raw mirror — **one table, `raw_neto.orders`**, one row per order. The Neto
> sibling of [`ingest/windsor_data_pull/`](../../windsor_data_pull/README.md) (`raw_windsor`) and
> [`ingest/snowflake_data_pull/`](../../snowflake_data_pull/README.md) (`raw_snowflake`): same
> `raw_<source>` pattern, same ADC auth + Secret Manager + structured logging + idempotent
> staging→MERGE + crash-safe resumable backfill.

**Plain English:** Neto is the shopping-cart / POS / order-management system behind City Perfume.
This unit pulls the **orders** — who bought what, when, for how much, paid how — out of Neto's API
and lands them tidily in our warehouse, one shared raw copy a client dashboard can read from. Like
the Windsor loaders it's **incremental** and safe to re-run: re-pulling any window never creates
duplicates.

**One table — no separate customers table.** Each order already carries everything we need about the
buyer: `email`, `username`, the billing/shipping address fields, and `customer_ref1` (the marketplace
handle). So customer attributes ride along on the order, and the reporting views resolve customer
identity from the order's **email** (see [`../reporting/`](../reporting)). There is no `GetCustomer`
pull.

**Raw layer is DUMB.** No per-client filter, no business logic here — that all lives in the client /
reporting layer (e.g. `clients/client_cityperfume/sql/`), exactly like the other clients read `raw_windsor` /
`raw_snowflake`. The two `../reporting/*.sql` views are committed only as **worked examples**; they are
**not** part of `raw_neto`.

---

## What's in here

| File | What it does |
|---|---|
| [`orders_loader.py`](orders_loader.py) | **The loader.** POSTs `GetOrder` to the Neto API, walks 0-indexed pages, transforms, and `MERGE`s into `raw_neto.orders`. Creates the dataset + table if missing. Runtime artifacts (window cache, log, NDJSON, backfill checkpoint) go to `_run/`. |
| [`../reporting/v_orders_overview.sql`](../reporting/v_orders_overview.sql) | **SAMPLE** order-grain reporting view (NOT raw). One row per order + derived customer history. |
| [`../reporting/v_sales.sql`](../reporting/v_sales.sql) | **SAMPLE** product-grain reporting view (NOT raw). `UNNEST(order_lines)` → one row per SKU per order, with `line_total` / `margin`. |
| [`Dockerfile`](Dockerfile) + [`requirements.txt`](requirements.txt) + [`.dockerignore`](.dockerignore) | Container build for the **`neto-orders-ingest`** Cloud Run job (Python 3.12-slim, non-root, pinned deps). Built/deployed/scheduled by [`scripts/deploy_ingest_jobs.ps1`](../../../scripts/deploy_ingest_jobs.ps1) — see *Scheduling & deployment* below. |
| `README.md` | This file. |

---

## Auth

- **Neto API key** from Secret Manager secret **`neto-api-key`** (read via the same ADC helper the
  Windsor loaders use — no gcloud path / machine config baked in; runs identically locally after
  `gcloud auth application-default login` and on Cloud Run).
- **`NETOAPI_USERNAME` is OPTIONAL** — the header is only sent if a Secret Manager secret
  **`neto-api-username`** exists. City Perfume uses a **global key** that authenticates on the key
  alone, so that secret is absent and the loader must (and does) **not** fail on its absence.
- **BigQuery + Cloud Storage** via ADC.

Transport (confirmed live): `POST {STORE_URL}/do/WS/NetoAPI` with headers `NETOAPI_ACTION` (`GetOrder`),
`NETOAPI_KEY`, `Accept` + `Content-Type` = `application/json`. `STORE_URL` comes from `$NETO_STORE_URL`
(default `https://www.cityperfume.com.au`), overridable with `--store-url`; a trailing slash is stripped.

---

## How it works (request / pagination / idempotency)

1. **Request.** Body is `{"Filter": { <date filter>, "Page": N, "Limit": 200, "OutputSelector": [...] }}`.
   `GetOrder` **requires a real selecting filter** — `Limit` alone returns zero rows — so every call
   carries a date filter. We **never** send an `UpdateResults` block (it would mutate each order's
   export state and must never touch fulfillment — the loader is strictly read-only).
2. **Paginate.** `Page` is **0-indexed**; we walk `0,1,2,…` until the response array is empty (an
   out-of-range page returns `Ack=Success` with `"Order": []`).
3. **Check the envelope.** `Ack != "Success"` or a populated `Messages.Error` is a hard, loud failure.
4. **Transform** into the typed schema, keeping the full original object in the `_raw` **JSON** column
   (navigable: `JSON_VALUE(_raw,'$.OrderStatus')` works).
5. **Load → staging → `MERGE`** through the shared `bidbrain-analytics-staging` GCS bucket, on
   `order_id`, so re-pulling a window is **idempotent** (no dupes; revised orders overwrite). Each load
   is deduped on `order_id` first (last occurrence wins).

**Resilience:** exponential backoff + jitter on HTTP 429/5xx, fail-fast on permanent 4xx, and a request
throttle that stays well under Neto's 500 requests/minute.

---

## Run modes & CLI

| Invocation | Mode |
|---|---|
| *(no args)* | **Incremental** (normal / scheduled). `DateUpdatedFrom = MAX(date_updated) − 2 days`, `DateUpdatedTo = now`. A brand-new (empty) table **bootstraps** the last 7 days and warns you to run `--backfill` for history. |
| `--backfill --since YYYY-MM-DD` | **Full history**, chunked by **calendar month** on `DatePlaced`. Each finished month is written to a checkpoint, so a crash **resumes** from the next month. |
| `--dry-run` | Fetch **page 0** + parse + log a sample row and counts. **No BigQuery reads or writes.** |

Flags: `--store-url URL`, `--limit N` (Neto page size, default 200), `--since YYYY-MM-DD`, `--force`
(backfill: ignore the window cache + month checkpoint and re-fetch/re-MERGE).

```powershell
# normal incremental
.\.venv\Scripts\python.exe neto_data_pull\orders\orders_loader.py

# one full historical backfill (the deliberate first load) — resumable, idempotent
.\.venv\Scripts\python.exe neto_data_pull\orders\orders_loader.py --backfill --since 2015-01-01

# inspect the live response shape without touching BigQuery
.\.venv\Scripts\python.exe neto_data_pull\orders\orders_loader.py --dry-run --limit 5 --since 2026-05-01
```

### Watching a run

The loader logs verbosely to **stdout and `_run/orders_loader.log`** so a long backfill is visible as
it moves:

- a startup banner with every resolved setting (store, target table, page size, watermark/overlap, throttle);
- the exact filter window being requested, then **every page**: `page N: HTTP 200 in X.Xs -- K orders (window running total: …)`;
- the `BQ LOAD` broken into timed steps: `[transform] → [ndjson] → [gcs] → [staging] → [merge] → [cleanup]`, ending with `+N new / ~M updated`;
- on `--backfill`, a `[month i/total]` header per month plus a **CUMULATIVE** line (months done, rows fetched/inserted/updated, pages, minutes elapsed) so you can gauge progress and ETA.

To follow a backfill running in another window: `Get-Content neto_data_pull\orders\_run\orders_loader.log -Wait -Tail 40`.

---

## Scheduling & deployment (the `neto-orders-ingest` Cloud Run job)

In production the *incremental* run is **not** launched from a laptop — it's one of the four shared
**ingest** Cloud Run jobs. The [`Dockerfile`](Dockerfile) here (Python 3.12-slim, non-root,
`requirements.txt` pinned to the repo `.venv`) builds the **`neto-orders-ingest`** job, which is
built, deployed, and scheduled by [`scripts/deploy_ingest_jobs.ps1`](../../../scripts/deploy_ingest_jobs.ps1)
(run as yourself; never `cloudbuild` from a laptop):

```powershell
.\scripts\deploy_ingest_jobs.ps1 -Only neto        # build + deploy + (re)schedule just this one
.\scripts\deploy_ingest_jobs.ps1 -Only neto -Run   # also execute it once after deploy
```

- **Job:** `neto-orders-ingest` (region `australia-southeast1`, repo `bidbrain`, `1Gi` / 1 CPU, 1-hour task timeout).
- **Runtime SA:** the shared `ingest-runner@bidbrain-analytics.iam.gserviceaccount.com` — granted `secretAccessor`
  on `neto-api-key`, BigQuery `dataEditor` + `jobUser`, and `objectAdmin` on the `bidbrain-analytics-staging` bucket.
- **Schedule:** Cloud Scheduler `neto-orders-ingest-daily` runs **`0 21 * * *` UTC — a fixed daily cron**,
  staggered *before* the 22:00 UTC `*-export` client jobs so City Perfume's nightly export reads fresh orders.

> **Freshness note.** Unlike the `*/10` SELF-GATING pattern in the freshness contract (which today only
> `snowflake-ingest` implements), this loader is a plain **fixed daily** job: there is no `freshness.py`,
> no `_freshness.json` watermark, and no upstream-advanced gate — each scheduled tick simply does the
> incremental `MAX(date_updated) − 2d → now` pull. (Re-running is cheap and idempotent; the day-to-day
> orders volume is small, and the incremental overlap makes a daily cadence sufficient for this source.)

---

## `raw_neto.orders` — one row per `order_id` (= Neto `OrderID`, == `ID`)

Order header + financials + the buyer / address fields, **plus two nested `REPEATED RECORD` columns**:

- **`order_lines`** — `sku, product_name, quantity (INT64), unit_price/tax/cost_price/product_discount/
  percent_discount (NUMERIC), tax_code, order_line_id, warehouse_name`.
- **`order_payments`** — `id, amount (NUMERIC), payment_type, date_paid (TIMESTAMP) + date_paid_raw`.

Plus `_loaded_at TIMESTAMP` and the full source object in `_raw JSON`.

### Buyer fields carried on the order
`email`, `username`, `customer_ref1`, and the `bill_*` / `ship_*` address fields — everything a
dashboard needs about the customer, without a second table. (See the address caveat below.)

### Types (confirmed from live data)
- **Money** comes back as strings (8-dp on line items `"300.00000000"`, 2-dp on totals `"270.00"`) →
  cast to **NUMERIC**, passing the string through (not float) to keep full precision.
- **Quantities** are strings (`"1"`) → **INT64**.
- **Datetimes** are `"YYYY-MM-DD HH:MM:SS"`; `DateInvoiced` / `DateCompleted` are sometimes **date-only**
  (`"2026-05-08"`), and Neto uses **`"0000-00-00"`** as an empty-date sentinel — all handled (→ NULL
  parsed, raw kept). Every datetime is stored both parsed (`TIMESTAMP`) and raw (`*_raw STRING`).
- `email` is frequently empty and `username` is often `"noreg"` (guest/POS) or a scrambled system
  handle — **stored as-is, never cleaned**.

---

## Customer identity (resolved in the views, from the order's email)

Because there is no customers table, the reporting views derive identity straight from the order:
**identity = `email` when present; when email is null the order is its OWN one-off identity** (anchored
on `order_id`). They **never** key on `username` — guest/POS orders share `"noreg"` or scrambled
handles, so windowing on `username` would collapse every `noreg` order into one fake mega-customer. See
[`../reporting/v_orders_overview.sql`](../reporting/v_orders_overview.sql).

---

## ⏰ Timezone convention (read this before querying timestamps)

Neto filters and timestamps are **store-local (Australia/Sydney)** with no offset. To make the
incremental watermark match the filter semantics exactly, this loader keeps the whole watermark loop in
**store-local wall-clock**:

- the `*_raw` STRING columns hold the source string verbatim (the source of truth);
- the parsed **`TIMESTAMP` columns hold that same wall-clock**, loaded **without** a TZ offset — so they
  are the Sydney wall-clock, **not** UTC instants. Don't re-convert them to Sydney downstream (that would
  double-shift); treat them as already-local;
- the next `DateUpdatedFrom` is `FORMAT_TIMESTAMP(MAX(date_updated)) − 2 days`, which round-trips back to
  the original store-local string. Only "now" (the `DateUpdatedTo` bound) is read from the Sydney clock.

---

## ⚠️ Address PII is empty for this store (data finding, not a bug)

The order-level **`bill_*` / `ship_*` address fields are requested** (the raw layer mirrors the source)
**but currently return EMPTY** for City Perfume — verified across ~4,000 orders spanning POS / Website /
eBay / BigW / Amazon / marketplace channels (the store/key does not expose order-level address PII). The
columns are **kept** for fidelity and forward-compat (they'd populate for a store/key that returns them);
meanwhile buyer identity is carried by `email` / `username` / `customer_ref1` (the latter often holds the
marketplace handle, e.g. an eBay username). `v_orders_overview.buyer_name` therefore comes out blank
today — expected.

---

## Reporting views (samples — belong in the client layer)

[`../reporting/v_orders_overview.sql`](../reporting/v_orders_overview.sql) — one row per order with
derived `last_order_date` / `total_orders` / `order_ytd` (windowed on the email identity),
`amount_received` (Σ payments) and `amount_owed` (`grand_total − amount_received`).
[`../reporting/v_sales.sql`](../reporting/v_sales.sql) — flattens `order_lines` to one row per SKU per
order with `line_total` and gross `margin` (the product-grain dataset for top-products / revenue-by-SKU
/ units-sold / basket-size). Move these into `clients/client_cityperfume/sql/` when wiring a dashboard.

---

## First-time setup

Nothing to pre-create — the loader **creates `raw_neto` and the table on first run**. Just:

```powershell
# (optional) confirm credentials + response shape first
.\.venv\Scripts\python.exe neto_data_pull\orders\orders_loader.py --dry-run --limit 5 --since 2026-05-01
# the one deliberate full backfill (done once, locally)
.\.venv\Scripts\python.exe neto_data_pull\orders\orders_loader.py --backfill --since 2015-01-01
```

After that, the scheduled `neto-orders-ingest` Cloud Run job keeps the table current with daily
incrementals — see *Scheduling & deployment* above. (The full backfill 2015-01 .. 2026-06 has already
been run; the local `_run/orders_backfill_done.json` checkpoint records every completed month.)

## See also

- [`../README.md`](../README.md) — the `ingest/neto_data_pull/` component map (this loader + the sample reporting views).
- [`ingest/windsor_data_pull/`](../../windsor_data_pull/README.md) & [`ingest/snowflake_data_pull/`](../../snowflake_data_pull/README.md) — the other shared-ingest units this mirrors.
- [`ingest/windsor_data_pull/ga4/ga4_loader.py`](../../windsor_data_pull/ga4/ga4_loader.py) — the loader whose chunking / retries / MERGE / resume design this follows.
