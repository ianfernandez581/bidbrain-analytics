# windsor_data_pull/ga4/ — GA4 Traffic Acquisition loader (`raw_windsor.perf_ga4`)

> Loads Google Analytics 4 **Traffic Acquisition** data from Windsor.ai into BigQuery, one row
> per **(property × date × session source/medium/campaign × channel group)**. Part of
> [`windsor_data_pull/`](../README.md) — read that first for the shared loader design
> (chunking, retries, MERGE, run modes).

**Plain English:** Meta and Trade Desk tell us what an ad *delivered* (impressions, clicks,
spend). GA4 tells us what the click *did on the website* — how many sessions it drove, whether
people engaged, and whether they converted or bought. This fetches those on-site numbers per
traffic source per day so a client dashboard can sit ad spend next to the sessions and revenue
it produced. Like the other loaders it's incremental and safe to re-run.

**Where it joins the others:** `perf_ga4` shares `client_slug` / `agency_slug` and a campaign
dimension with `perf_meta` / `perf_the_trade_desk`, so a client view can line up ad-platform
delivery against the GA4 outcome it drove (by source / campaign / day).

---

## What's in here

| File | What it does |
|---|---|
| [`create_ga4_table.py`](create_ga4_table.py) | **One-time, run FIRST.** Creates `raw_windsor.perf_ga4` at the acquisition grain, partitioned by `metric_date`, clustered by `property_id, session_default_channel_group`. Idempotent — but it **creates, doesn't alter**: to change columns on an existing (empty) table, drop it first (`bq rm -f -t bidbrain-analytics:raw_windsor.perf_ga4`). |
| [`ga4_loader.py`](ga4_loader.py) | **The loader.** Fetches from Windsor's dedicated `googleanalytics4` connector, merges the two metric-group passes, transforms, and `MERGE`s into `perf_ga4`. |
| [`probe_ga4_fields.py`](probe_ga4_fields.py) | **Throwaway diagnostic.** Hits the connector with a handful of fields against one property and prints raw rows — how the field-name gotcha below was found. Not part of the normal run. |
| [`truncate_ga4.py`](truncate_ga4.py) | **Manual reset.** `TRUNCATE`s `perf_ga4`. Use to force a clean full backfill (rarely needed — the loader resumes backfills on its own). |
| `README.md` | This file. |

---

## Grain & key

- **Grain:** one row per **`property_id` × `metric_date` × `session_source` × `session_medium`
  × `session_campaign_name` × `session_default_channel_group`** — the GA4 "Traffic Acquisition"
  report. This is the **primary** GA4 table; landing-page / demographics / geo / device /
  events / items each get their own `perf_ga4_*` table later (the GA4 Data API mixes scopes
  that aren't additive against one grain, so they can't all share one wide table the way
  `perf_meta` does).
- **MERGE key:** the six grain columns above, each coalesced to `'(not set)'` so the key is
  never NULL. **`session_default_channel_group` is in the key on purpose** — Windsor can return
  source/medium/campaign NULL for some rows, and without the channel group those rows all
  collapse to one key and the MERGE fails with "matched multiple source rows". `_MERGE_KEY_COLS`
  in [`ga4_loader.py`](ga4_loader.py) is the single source of truth for both the dedup and the
  SQL `ON` clause, so they can't drift.
- **Tenant key:** `property_id` (we select by GA4 property ID, reliable per row).
  `measurement_id` is deliberately **not** stored — it's stream-scoped and would fragment
  multi-stream properties.

---

## Two GA4-specific quirks (vs meta_loader / tradedesk_loader)

**1. Two-pass fetch.** GA4's Data API caps a single request at 9 dimensions / 10 metrics. We
want 12 metrics, so each chunk is fetched in **two passes** with identical dimensions and a
6-metric subset each (`FIELDS_GROUP_A` = traffic/engagement, `FIELDS_GROUP_B` = outcomes), then
merged on the dimension key into one row *before* transform/MERGE. A dim combo with traffic but
zero conversions/revenue may be absent from pass B — those outcome metrics default to 0 in
transform (missing == 0 at this grain).

**2. ⚠️ Field-name gotcha.** Windsor's GA4 connector populates the **plain**
`source` / `medium` / `campaign` request fields, **not** the `session_*` variants (those exist
in the field reference but come back NULL). The channel group is the exception — it's requested
as `session_default_channel_group`. And the blended `/all` endpoint silently nulls **all** of
these GA4-native dims, so this loader uses the dedicated `googleanalytics4` connector
(`WINDSOR_URL`), with bare numeric property IDs and **no** account prefix. `session_source_medium`
is *derived* in transform (`"source / medium"`), not requested, to save a dimension slot.

---

## Metrics are additive base only

`perf_ga4` stores only **additive base metrics**. Do **not** add `engagement_rate` /
`bounce_rate` / `average_session_duration` / AOV / ARPU as columns — they're non-additive and
break when summed across days or sources. Store numerator + denominator and derive in SQL:

```sql
engagement_rate          = SUM(engaged_sessions) / SUM(sessions)
bounce_rate              = 1 - engagement_rate
avg engagement time/sess = SUM(user_engagement_duration) / SUM(sessions)
AOV                      = SUM(purchase_revenue) / NULLIF(SUM(transactions), 0)
ARPU                     = SUM(total_revenue)    / NULLIF(SUM(total_users), 0)
```

Captured base metrics: `sessions`, `engaged_sessions`, `total_users`, `new_users`,
`screen_page_views`, `user_engagement_duration`, `event_count`, `conversions` (GA4 "Key
events", NUMERIC — can be fractional under modeling), `total_revenue`, `purchase_revenue`,
`ecommerce_purchases`, `transactions`. Plus provenance (`ingested_at`, `source = 'windsor.ga4'`,
full original row in `raw_row`). See [`create_ga4_table.py`](create_ga4_table.py) for every
column + description.

---

## Run modes (this loader's specifics)

See [the parent README](../README.md#how-the-loaders-work-shared-design) for the shared model.
GA4's no-args mode is **incremental per-property** (same shape as Meta):

- **Property already has data** → forward-load from its last BigQuery day minus
  `INCREMENTAL_LOOKBACK_DAYS` (**3**, higher than Meta's 0 because GA4 conversions / modeled
  data settle over ~24–48h), up to yesterday; then resume the backward backfill below the
  earliest day it has (so an interrupted backfill continues — no truncate needed).
- **Property has no data yet** → full backfill via a backward walk from yesterday until
  `STOP_AFTER_EMPTY_CHUNKS` (5) consecutive empty chunks, or the `MIN_DATE` floor.

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\ga4\ga4_loader.py                       # normal incremental run
.\.venv\Scripts\python.exe windsor_data_pull\ga4\ga4_loader.py 2026-05-25 2026-05-30 # fixed range (all properties)
.\.venv\Scripts\python.exe windsor_data_pull\ga4\ga4_loader.py 2026-05-25 2026-05-30 --force  # ignore cache
```

**To add a property:** append its bare numeric GA4 property ID to `SELECT_ACCOUNTS` in
[`ga4_loader.py`](ga4_loader.py). Because GA4 property names are often generic
("GA4 - example.com") and don't carry the client keyword, prefer mapping the property ID
straight to `(client_slug, agency_slug)` in `PROPERTY_TO_CLIENT` (checked first in
`infer_slugs`) rather than relying on the keyword fallback.

---

## See also

- [Parent README](../README.md) — shared loader design, auth, first-time setup order.
- [`../meta/README.md`](../meta/README.md) and [`../tradedesk/README.md`](../tradedesk/README.md) — the sibling ad-platform loaders.
