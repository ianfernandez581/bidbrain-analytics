# windsor_data_pull/reddit/ — Reddit Ads loader (`raw_windsor.perf_reddit`)

> Loads **Reddit Ads** ad-level daily delivery from Windsor.ai into BigQuery, one row per
> **(account × ad × date)**. Part of [`windsor_data_pull/`](../README.md) — read that first for the
> shared loader design (chunking, retries, MERGE, run modes).

**Plain English:** this is the ad-platform side of the story — what each Reddit ad *delivered* per
day: how many times it showed (impressions), how many clicks it got, what it cost (spend), who it
reached, plus the conversions Reddit attributes to it (lead / sign-up / page-visit, split by click
vs view). GA4 (`perf_ga4`) then tells us what those clicks *did on the website*. Like the other
loaders it's incremental and safe to re-run.

**Where it joins the others:** `perf_reddit` shares `client_slug` / `agency_slug` and a campaign
dimension with `perf_ga4` / `perf_meta` / `perf_google_ads` / `perf_the_trade_desk`, so a client
view can line up Reddit spend against the on-site outcome it drove.

---

## What's in here

| File | What it does |
|---|---|
| [`create_reddit_table.py`](create_reddit_table.py) | **One-time, run FIRST.** Creates `raw_windsor.perf_reddit` at the ad grain, partitioned by `metric_date`, clustered by `account_id, campaign_id`. Idempotent — but it **creates, doesn't alter**: to change columns on an existing (empty) table, drop it first (`bq rm -f -t bidbrain-analytics:raw_windsor.perf_reddit`). |
| [`reddit_loader.py`](reddit_loader.py) | **The loader.** Single-pass fetch from Windsor's blended `/all` endpoint (with the `reddit__` account prefix), transforms, and `MERGE`s into `perf_reddit`. Runtime artifacts go to `_run/`. |
| [`probe_reddit_fields.py`](probe_reddit_fields.py) | **Throwaway diagnostic.** Hits `/all` with the field set against the configured account and prints the hierarchy-ID verdict, the exact `account_id` format, currency, and a populated-vs-NULL summary per field — how the facts below were confirmed. Not part of the normal run. |
| [`truncate_reddit.py`](truncate_reddit.py) | **Manual reset.** `TRUNCATE`s `perf_reddit`. Use to force a clean full backfill (rarely needed — the loader resumes backfills on its own). |
| `Dockerfile` / `.dockerignore` / `requirements.txt` | Container for the Cloud Run ingest job (`windsor-reddit-ingest`). |
| `README.md` | This file. |

---

## Grain & key

- **Grain:** one row per **`account_id` × `ad_id` × `metric_date`** — ad-level daily delivery.
- **MERGE key:** those three columns; `account_id` / `ad_id` coalesced to `'(not set)'` so the key
  is never NULL. `_MERGE_KEY_COLS` in [`reddit_loader.py`](reddit_loader.py) is the single source of
  truth for both the staging dedup and the SQL `ON` clause, so they can't drift.
- **Campaign / ad-group fields ride along as attributes, NOT keys.** `campaign_id`, `campaign_name`,
  `campaign_objective`, `ad_group_id`, `ad_group_name`, `ad_name` are functionally determined by
  `ad_id` — they don't split the grain.
- **Tenant key:** `account_id` — Reddit's **opaque alphanumeric** id (`a2_igd0szmw7roq`), not a
  number. We select by account id, so it's reliable per row.

---

## `/all` returns the Reddit hierarchy (the probe finding)

Reddit is pulled through the **blended `/all` endpoint** with a `reddit__` account prefix (same
mechanics as the Meta loader), **not** a dedicated `/reddit` connector. The open question before
building — the GA4 lesson — was whether `/all` returns Reddit's `campaign_id` / `ad_group_id` /
`ad_id` or silently NULLs them the way it nulls some GA4 platform dims.
[`probe_reddit_fields.py`](probe_reddit_fields.py) **confirmed all three populate** (campaign /
ad-group / ad ids, 168/168 rows), so the loader keys on the finest grain (`ad_id`) and treats every
id as an opaque string. No escalation to a dedicated connector or a name-based grain was needed.

**Single-pass fetch.** The Windsor `/all` connector has **no GA4-style 9-dim/10-metric cap**, so
this loader is **one request per chunk** — no metric-group split. Ad × date is higher cardinality
than Google Ads' campaign grain, so `CHUNK_DAYS = 30` (start conservative; drop it if Windsor times
out on a backfill).

**Format (confirmed via the probe):** Windsor returns `account_id` **bare** (`a2_igd0szmw7roq` — it
strips the `reddit__` prefix from the response). `campaign` and `campaign_name` are identical; we
keep `campaign_name`. We do **not** request Windsor's `datasource` (we set our own `source`).

---

## ⚠️ The alphanumeric `account_key` gotcha

Reddit account ids are **alphanumeric** (`a2_igd0szmw7roq`). The sibling loaders normalise the
account key with `re.sub(r"\D", "", …)` (strip to digits) — which would collapse `a2_igd0szmw7roq`
to **`"2"`**, merging every account together and breaking both `SELECT_ACCOUNTS` matching and
`date_bounds_per_account`. So `account_key()` here is a **string** normaliser instead: strip a
leading `reddit__` connector prefix, lowercase, trim — keeping the full `a2_…` body intact. It works
on the bare id, the prefixed handle, and the value stored in BigQuery. Campaign / ad-group / ad ids
are likewise treated as opaque strings, never coerced to numbers.

---

## Spend currency (store `account_currency`, always)

Reddit `spend` comes back in the **account's native currency**, not USD — the probe confirmed
**AUD** for the ResetData account. We store `account_currency` (ISO-4217) on every row so a client
view can FX to its reporting currency. Getting this wrong is the silent bug that's bitten other
pipelines, so the column is non-negotiable even when the account currency already matches the
client's.

---

## Metrics are additive base only

`perf_reddit` stores only **additive base metrics** — delivery (`impressions`, `clicks`, `spend`,
`reach`), engagement (`upvotes`, `downvotes`, `comment_submissions`), the video funnel
(`video_starts` / `video_25` / `video_50` / `video_75` / `video_completes`), and the conversion
click/view split (`lead_clicks` / `lead_views` / `signup_clicks` / `signup_views` /
`page_visit_clicks` / `page_visit_views`) plus their values (`lead_total_value`,
`signup_total_value`). Do **not** add `ctr` / `cpc` / `cpm` / `cpl` / `*_cvr` / `frequency` /
`video_completion_rate` / `roas` as columns — they're non-additive and break when summed across days
or ads. Derive them in client SQL:

```sql
ctr  = SUM(clicks)/NULLIF(SUM(impressions),0)
cpc  = SUM(spend)/NULLIF(SUM(clicks),0)
cpm  = SUM(spend)/NULLIF(SUM(impressions),0)*1000
cpl  = SUM(spend)/NULLIF(SUM(lead_clicks)+SUM(lead_views),0)
lead_cvr = (SUM(lead_clicks)+SUM(lead_views))/NULLIF(SUM(clicks),0)
video_completion_rate = SUM(video_completes)/NULLIF(SUM(video_starts),0)
frequency = SUM(impressions)/NULLIF(SUM(reach),0)   -- approximate; daily reach is not truly additive
```

**One cost field:** `spend` (Reddit cost, in account currency). Windsor's `totalcost` variant is
deliberately **not** stored (duplicate). **Conversion counts/values are NUMERIC, never INT** — Reddit
reports fractional conversions under modeling / attribution; **never sum a click + a view into one
number** (keep the split). `reach` is **non-additive across days** (unique people, like GA4
`total_users`) — derive frequency, never SUM reach for a period total. Plus provenance:
`ingested_at`, `source = 'windsor.reddit'`, and the full original row in `raw_row` (so any
un-promoted field is recoverable). See [`create_reddit_table.py`](create_reddit_table.py) for every
column + description.

> **Note — engagement fields currently NULL.** `upvotes` / `downvotes` / `comment_submissions` come
> back NULL from Windsor for the configured account (it doesn't surface Reddit engagement there).
> The columns stay anyway — they're additive, cost nothing, and auto-populate if Windsor starts
> returning them; full fidelity is preserved in `raw_row` regardless.

---

## Run modes

See [the parent README](../README.md#how-the-loaders-work-shared-design) for the shared model. The
no-args mode is **incremental per-account** (same shape as the other loaders):

- **Account already has data** → forward-load from its last BigQuery day minus
  `INCREMENTAL_LOOKBACK_DAYS` (**7**) up to yesterday; then resume the backward backfill below the
  earliest day it has (so an interrupted backfill continues — no truncate needed).
- **Account has no data yet** → full backfill via a backward walk from yesterday until
  `STOP_AFTER_EMPTY_CHUNKS` (5) consecutive empty chunks, or the `MIN_DATE` floor.

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\reddit\reddit_loader.py                       # normal incremental run
.\.venv\Scripts\python.exe windsor_data_pull\reddit\reddit_loader.py 2026-05-15 2026-05-30  # fixed range (all accounts)
.\.venv\Scripts\python.exe windsor_data_pull\reddit\reddit_loader.py 2026-05-15 2026-05-30 --force  # ignore cache
```

**Accounts loaded:** `a2_igd0szmw7roq` (ResetData). One revoked/ungranted account is logged and
**skipped** (`AccountUnavailableError`) rather than aborting the run — Reddit access can be revoked
per-account, like the Trade Desk's was.

**To add an account:** append its bare Reddit account id to `SELECT_ACCOUNTS` in
[`reddit_loader.py`](reddit_loader.py) **and** map it in `REDDIT_ACCOUNT_TO_CLIENT`
(`account_id → (client_slug, agency_slug)`, checked first in `infer_slugs`). Otherwise it falls back
to a keyword match over `account_name` + `campaign_name`. Find account ids at
<https://onboard.windsor.ai?datasource=reddit>.

---

## ⚠️ Conversion-window caveat

`INCREMENTAL_LOOKBACK_DAYS = 7` re-pulls a trailing 7 days each incremental run, because Reddit
conversions settle as they're attributed back to the **click date**. This is a **B2B lead-gen
account with a potentially long conversion window** — a 7-day rolling lookback will **not** recapture
conversions that land more than 7 days after the click. For full reconciliation, periodically run a
fixed-range re-pull of a trailing **30–90 days** (the two-date-arg mode supports this directly).

---

## See also

- [Parent README](../README.md) — shared loader design, auth, first-time setup order.
- [`../meta/README.md`](../meta/README.md) — the Meta loader whose `/all` + ad-grain mechanics this one shares.
- [`../google_ads/README.md`](../google_ads/README.md) — the loader skeleton this one is copied from.
