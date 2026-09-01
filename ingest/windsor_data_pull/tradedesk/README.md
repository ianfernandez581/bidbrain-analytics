# ingest/windsor_data_pull/tradedesk/ — The Trade Desk loader (`raw_windsor.perf_the_trade_desk`)

> Loads The Trade Desk (programmatic display/video) performance from Windsor.ai into BigQuery.
> Part of [`ingest/windsor_data_pull/`](../README.md) — read that first for the shared loader design
> (chunking, retries, MERGE, run modes).

**Plain English:** The Trade Desk is a programmatic advertising platform (it buys display and
video ad space across the web). This fetches its daily delivery numbers — impressions, clicks,
cost, and video completion — and stores them so client dashboards can read them. Like the Meta
loader, it's incremental and safe to re-run.

---

## What's in here

| File | What it does |
|---|---|
| [`create_trade_desk__tables.py`](create_trade_desk__tables.py) | **One-time.** Creates `raw_windsor.perf_the_trade_desk`, partitioned by `metric_date`, clustered by `campaign_id, ad_format`. Idempotent. |
| [`tradedesk_loader.py`](tradedesk_loader.py) | **The loader.** Fetches from Windsor's `/tradedesk` endpoint, transforms, and `MERGE`s into the table. |
| `Dockerfile` / `.dockerignore` / `requirements.txt` | Container for the Cloud Run ingest job (`windsor-tradedesk-ingest`, daily — see the [parent README](../README.md#deployment--scheduling-cloud-run-jobs)). |
| `README.md` | This file. |

---

## Grain & key

- **Grain:** one row per **campaign × ad_group × creative × metric_date × ad_format**.
- **MERGE key:** `campaign_id + ad_group_id + creative_id + metric_date + ad_format`. Missing
  IDs are coalesced to `"unknown"` so a NULL can never break the key (`NULL != NULL` in SQL).
- Fields come from Windsor's **"Ad Group Performance"** report (verified against the TTD field
  reference), so they're all queryable in a single request.

---

## Run modes (this loader's specifics)

See [the parent README](../README.md#how-the-loaders-work-shared-design) for the shared model.
Trade Desk's no-args mode is a **backward walk**: it starts at yesterday and walks back in
3-day chunks, loading as it goes, until `STOP_AFTER_EMPTY_CHUNKS` (5) consecutive empty chunks
or the `MIN_DATE` floor — auto-discovering how far back data exists.

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\tradedesk_loader.py                       # backward walk (normal)
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\tradedesk_loader.py 2026-05-01 2026-05-31 # fixed range
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\tradedesk_loader.py 2026-05-01 2026-05-31 --force
```

**Scheduled runs are BOUNDED (2026-09-01):** the Cloud Run job sets `WINDSOR_LOOKBACK_DAYS=35`
(no-args becomes a fixed range of the last 35 days, ~5 min instead of re-walking the seat's whole
history into the 3600s task kill) and `WINDSOR_MAX_ATTEMPTS=4` (a retry budget that fits the task
timeout, so a degraded Windsor gives up cleanly and the exit code stays meaningful). Neither env is
set for laptop runs, so the commands above behave exactly as written. **Consequence: an upstream
restatement older than 35 days no longer self-heals** — run a manual fixed range for the affected
window (MERGE is idempotent). A 400 for a day TTD has not published yet is recognised by MESSAGE,
not just by empty body — Windsor changed that error's shape once already (2026-08-31, empty →
JSON body), which silently killed the early scheduled run for weeks; see the `DATA NOT PUBLISHED
YET` comment in `fetch_chunk`.

**Accounts loaded:** `569` (single TTD account; was `484` until the 2026-08-25 re-grant issued a
new seat id - see the loader comment). An ungranted/revoked account is logged and
skipped (`AccountUnavailableError`) rather than aborting the run.

> **Status (2026-09-01):** healthy and flowing — `windsor-tradedesk-ingest` runs `35 4,21 * * *`
> UTC in bounded mode (~5 min/run, both runs green). Know the two failure modes this loader has
> already survived: a lapsed GRANT (2026-06-13 and again 2026-08-21 — re-grant at
> <https://onboard.windsor.ai?datasource=tradedesk>; note the re-grant can issue a NEW seat id, 484
> → 569, so a working re-auth can look like a failure until `SELECT_ACCOUNTS` is repointed), and
> Windsor's nightly degraded window ~00:00-03:30 UTC (ReadTimeouts + "day not published" 400s —
> which is why the early run sits at 04:35, not 01:35). An ungranted account is logged + skipped
> (`AccountUnavailableError`), it doesn't abort the run. See the
> [parent README](../README.md#deployment--scheduling-cloud-run-jobs).

---

## What's captured

- **Dimensions** — advertiser, campaign, ad group, creative, `ad_format`, currency, plus
  internal `client_slug` / `agency_slug` inferred from advertiser/campaign names.
- **Core metrics** — impressions, clicks, cost (advertiser currency).
- **Video** — player starts, 25/50/75% complete, completed views.
- **Conversions** — see the caveat below.
- **Provenance** — `ingested_at`, `source = 'windsor.tradedesk'`, full original row in
  `raw_row` (JSON).

### ⚠️ Conversions / "pixel fires" caveat

Windsor exposes TTD conversions only as **anonymous numbered slots**
(`click_conversion_01..12`, `view_through_conversion_01..12`, `conversion_touch_01..12`) — there
is **no pixel name / pixel ID** dimension in this connector. The loader pulls the slots and
stores the populated (non-zero) ones as a compact JSON map in the `conversions` column. A real
"Pixel → Event" table with named pixels is **not possible from Windsor alone** — it needs a
slot→pixel mapping you maintain, or the TTD API directly. To also capture time-weighted-decay
or revenue variants, extend the `_CONVERSION_KINDS` tuple in
[`tradedesk_loader.py`](tradedesk_loader.py).

## See also

- [Parent README](../README.md) — shared loader design, auth, first-time setup order.
- [`../meta/README.md`](../meta/README.md) — the sibling Meta/Facebook loader.
