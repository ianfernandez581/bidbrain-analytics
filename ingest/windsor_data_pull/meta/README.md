# ingest/windsor_data_pull/meta/ — Meta / Facebook Ads loader (`raw_windsor.perf_meta`)

> Loads Meta/Facebook Ads performance from Windsor.ai into BigQuery, one row per
> **(ad × date)**. Part of [`ingest/windsor_data_pull/`](../README.md) — read that first for the
> shared loader design (chunking, retries, MERGE, run modes).

**Plain English:** this fetches the daily numbers for every Facebook/Instagram ad we run
(impressions, clicks, spend, leads, video views, and a lot more) and stores them so client
dashboards can roll them up however they need. It's smart about updates: it only pulls what's
new for each ad account, and re-running it never creates duplicates.

---

## What's in here

| File | What it does |
|---|---|
| [`create_meta_table.py`](create_meta_table.py) | **One-time.** Creates `raw_windsor.perf_meta` with the full typed schema (~80 columns), partitioned by `metric_date`, clustered by `campaign_id, ad_id`. Idempotent — but it **creates, doesn't alter**: to add columns to an existing table, drop it first (it's safe when empty). |
| [`meta_loader.py`](meta_loader.py) | **The loader.** Fetches from Windsor's blended `/all` endpoint for an explicit list of Facebook accounts (currently 6), transforms, and `MERGE`s into `perf_meta`. |
| `Dockerfile` / `.dockerignore` / `requirements.txt` | Container for the Cloud Run ingest job (`windsor-meta-ingest`, daily — see the [parent README](../README.md#deployment--scheduling-cloud-run-jobs)). |
| `README.md` | This file. |

---

## Grain & key

- **Grain:** one row per **`ad_id` × `metric_date`** — the finest level Meta exposes without
  breakdown dimensions. Roll up to adset / campaign / account in SQL; join creative metadata
  for creative-level views.
- **MERGE key:** `ad_id + metric_date`. Re-pulling a day overwrites in place (idempotent).
- **No breakdown dimensions** (publisher_platform, age, gender, country, device) are stored —
  any of those would multiply rows and change the grain. Platform/demographic splits would go
  in a separate table.

---

## Run modes (this loader's specifics)

See [the parent README](../README.md#how-the-loaders-work-shared-design) for the shared model.
Meta's no-args mode is **incremental per-account**:

- **Account already has data** → forward-load from its last BigQuery day (minus
  `INCREMENTAL_LOOKBACK_DAYS`, default `0`) up to yesterday. The boundary day is deliberately
  re-pulled because Meta revises recent metrics — the staging + MERGE absorb the duplicates.
- **Account has no data yet** → full backfill via a **backward walk** from yesterday until
  `STOP_AFTER_EMPTY_CHUNKS` (5) consecutive empty chunks, or the `MIN_DATE` floor. So adding a
  brand-new account discovers its history **without** re-pulling accounts already current.

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py                       # normal incremental run
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py 2026-05-25 2026-05-30 # fixed range (all accounts)
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py 2026-05-25 2026-05-30 --force  # ignore cache
```

**To add a client/account:** append their `facebook__<account_id>` to `SELECT_ACCOUNTS` in
[`meta_loader.py`](meta_loader.py). To widen the re-pull window for late conversions, raise
`INCREMENTAL_LOOKBACK_DAYS`.

---

## What's captured (column groups in `perf_meta`)

The schema is intentionally wide so any client can build any view without a re-pull. Groups
(see [`create_meta_table.py`](create_meta_table.py) for every field + description):

- **Identifiers / dimensions** — account, campaign, objective, adset, ad, effective_status,
  currency, plus internal `client_slug` / `agency_slug`.
- **Delivery & cost** — impressions, reach, frequency, cost (spend), cpc, cpm, cpp.
- **Clicks** — all / unique / link / outbound (use the *link* clicks for CTR/CPC).
- **Engagement** — post & page engagement, reactions, comments, shares, saves, 3s video views.
- **Awareness** — estimated ad-recall lift/rate, Instagram profile visits.
- **Leads** — total / website / on-Facebook / unique, cost-per-lead.
- **Conversions & value** — landing-page views, add-to-cart, checkout, purchases, ROAS (ecom;
  null for lead-gen).
- **Video funnel** — starts, 25/50/75/95/100%, thruplays, avg watch time.
- **Optimization signals** — quality / engagement-rate / conversion-rate rankings.
- **Creative metadata** — creative id, thumbnails, title, body, link/destination URLs.
- **Provenance** — `ingested_at`, `source = 'windsor.facebook'`, and the full original row in
  `raw_row` (JSON).

> **Watch:** several Windsor "CTR/rate" fields arrive on a PERCENT scale — verify 0–1 vs 0–100
> on first load (noted inline in the schema).

## See also

- [Parent README](../README.md) — shared loader design, auth, first-time setup order.
- [`../tradedesk/README.md`](../tradedesk/README.md) — the sibling Trade Desk loader.
