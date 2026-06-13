# ingest/windsor_data_pull/google_ads/ — Google Ads loader (`raw_windsor.perf_google_ads`)

> Loads **Google Ads** campaign-level daily delivery from Windsor.ai into BigQuery, one row
> per **(customer × date × campaign)**. Part of [`ingest/windsor_data_pull/`](../README.md) — read that
> first for the shared loader design (chunking, retries, MERGE, run modes).

**Plain English:** this is the ad-platform side of the story — what each Google Ads campaign
*delivered* per day: how many times it showed (impressions), how many clicks it got, what it
cost (spend), and the conversions / conversion value Google Ads attributes to it. GA4
(`perf_ga4`) then tells us what those clicks *did on the website*. Like the other loaders it's
incremental and safe to re-run.

**Where it joins the others:** `perf_google_ads` shares `client_slug` / `agency_slug` and a
campaign dimension with `perf_ga4` / `perf_meta` / `perf_the_trade_desk`, so a client view can
line up Google Ads spend against the on-site outcome it drove.

---

## What's in here

| File | What it does |
|---|---|
| [`create_google_ads_table.py`](create_google_ads_table.py) | **One-time, run FIRST.** Creates `raw_windsor.perf_google_ads` at the campaign grain, partitioned by `metric_date`, clustered by `customer_id, campaign_type`. Idempotent — but it **creates, doesn't alter**: to change columns on an existing (empty) table, drop it first (`bq rm -f -t bidbrain-analytics:raw_windsor.perf_google_ads`). |
| [`google_ads_loader.py`](google_ads_loader.py) | **The loader.** Single-pass fetch from Windsor's dedicated `google_ads` connector, transforms, and `MERGE`s into `perf_google_ads`. Runtime artifacts go to `_run/`. |
| [`probe_google_ads_fields.py`](probe_google_ads_fields.py) | **Throwaway diagnostic.** Hits the connector with the field set against the configured accounts and prints the account-format result, the exact `account_id` format, and a populated-vs-NULL summary per field — how the facts below were confirmed. Not part of the normal run. |
| [`truncate_google_ads.py`](truncate_google_ads.py) | **Manual reset.** `TRUNCATE`s `perf_google_ads`. Use to force a clean full backfill (rarely needed — the loader resumes backfills on its own). |
| `README.md` | This file. |

---

## Grain & key

- **Grain:** one row per **`customer_id` × `metric_date` × `campaign_id`** — campaign-level daily
  delivery.
- **MERGE key:** those three columns; `customer_id` / `campaign_id` coalesced to `'(not set)'` so
  the key is never NULL. `_MERGE_KEY_COLS` in [`google_ads_loader.py`](google_ads_loader.py) is the
  single source of truth for both the staging dedup and the SQL `ON` clause, so they can't drift.
- **`campaign_type` rides along as an attribute, NOT a key.** It's the advertising-channel type
  (SEARCH / PERFORMANCE_MAX / SHOPPING / …) and is functionally determined by `campaign_id` — it
  doesn't split the grain, exactly like `is_conversion_event` rides along in `perf_ga4_events`.
- **Tenant key:** `customer_id` (Windsor `account_id`, hyphenated e.g. `105-440-7474`). We select by
  customer id, so it's reliable per row.

---

## Single-pass fetch (vs GA4's two-pass)

GA4's Data API caps a single request at 9 dimensions / 10 metrics, so
[`ga4_loader.py`](../ga4/ga4_loader.py) splits each chunk into two metric-group passes and merges
them. **The Windsor `google_ads` connector has no such cap**, so this loader is **one request per
chunk** — no `FIELDS_GROUP_A/B`, no `merge_metric_groups`, no `fetch_chunk_combined`. Because
campaign × date is low-cardinality and single-pass, `CHUNK_DAYS = 90` (large chunks are cheap and
there's no GA4-style sampling risk; drop it if Windsor times out on a backfill).

**Connector / format (confirmed via `probe_google_ads_fields.py`):** use the dedicated
`google_ads` connector (`WINDSOR_URL`), **not** the blended `/all` endpoint. Customer ids are
**bare, no prefix** (`105-440-7474`); the `google_ads__…` prefix is only for `/all` and returns
HTTP 400 here. Windsor returns `account_id` **hyphenated**; `account_key()` normalises to digits so
`SELECT_ACCOUNTS` matches the stored `customer_id` either way. All requested fields populate,
including `campaign_type` and `currency_code`.

---

## Metrics are additive base only

`perf_google_ads` stores only **additive base metrics**: `impressions`, `clicks`, `spend`,
`conversions`, `conversions_value`. Do **not** add `ctr` / `average_cpc` / `cpm` / `cost_per_*` /
`*_rate` / `roas` as columns — they're non-additive and break when summed across days or campaigns.
Derive them in client SQL:

```sql
ctr  = SUM(clicks) / SUM(impressions)
cpc  = SUM(spend)  / SUM(clicks)
cpm  = SUM(spend)  / SUM(impressions) * 1000
cpa  = SUM(spend)  / NULLIF(SUM(conversions), 0)
cvr  = SUM(conversions) / SUM(clicks)
roas = SUM(conversions_value) / NULLIF(SUM(spend), 0)
```

**One cost field:** `spend` (Google Ads cost). Windsor's `cost` / `cost_micros` / `totalcost`
variants are deliberately **not** stored (duplicates). **`conversions` / `conversions_value` are
NUMERIC, never INT** — Google Ads conversions can be fractional (conversion modeling / fractional
attribution). Plus provenance: `ingested_at`, `source = 'windsor.google_ads'`, and the full
original row in `raw_row`. See [`create_google_ads_table.py`](create_google_ads_table.py) for every
column + description.

---

## Run modes

See [the parent README](../README.md#how-the-loaders-work-shared-design) for the shared model.
The no-args mode is **incremental per-account** (same shape as the other loaders):

- **Account already has data** → forward-load from its last BigQuery day minus
  `INCREMENTAL_LOOKBACK_DAYS` (**7**) up to yesterday; then resume the backward backfill below the
  earliest day it has (so an interrupted backfill continues — no truncate needed).
- **Account has no data yet** → full backfill via a backward walk from yesterday until
  `STOP_AFTER_EMPTY_CHUNKS` (5) consecutive empty chunks, or the `MIN_DATE` floor.

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\google_ads\google_ads_loader.py                       # normal incremental run
.\.venv\Scripts\python.exe windsor_data_pull\google_ads\google_ads_loader.py 2026-05-15 2026-05-30  # fixed range (all accounts)
.\.venv\Scripts\python.exe windsor_data_pull\google_ads\google_ads_loader.py 2026-05-15 2026-05-30 --force  # ignore cache
```

**Accounts loaded:** `105-440-7474`, `261-791-6504`, `519-659-6415`, `850-931-3407`. (A 5th account
`186-974-5895` is also configured in Windsor but not loaded.)

**To add an account:** append its bare customer id to `SELECT_ACCOUNTS` in
[`google_ads_loader.py`](google_ads_loader.py) **and** map it in `CUSTOMER_TO_CLIENT`
(`customer_id → (client_slug, agency_slug)`, checked first in `infer_slugs`). Otherwise it falls
back to a keyword match over `account_name` + `campaign`.

---

## ⚠️ Conversion-window caveat

`INCREMENTAL_LOOKBACK_DAYS = 7` re-pulls a trailing 7 days each incremental run, because Google Ads
conversions settle as they're attributed back to the **click date**. These are **B2B accounts with
potentially long conversion windows** — a 7-day rolling lookback will **not** recapture conversions
that land more than 7 days after the click. For full reconciliation, periodically run a fixed-range
re-pull of a trailing **30–90 days** (the two-date-arg mode supports this directly).

---

## See also

- [Parent README](../README.md) — shared loader design, auth, first-time setup order.
- [`../ga4/README.md`](../ga4/README.md) — the GA4 loader this one mirrors (two-pass, on-site outcomes).
