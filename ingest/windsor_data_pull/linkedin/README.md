# ingest/windsor_data_pull/linkedin/ — LinkedIn Ads loader (`raw_windsor.perf_linkedin`)

> Loads **LinkedIn Ads** creative-level daily delivery from Windsor.ai into BigQuery, one row per
> **(account × creative × date)**. Part of [`ingest/windsor_data_pull/`](../README.md) — read that first for the
> shared loader design (chunking, retries, MERGE, run modes).

**Plain English:** this is the ad-platform side of the LinkedIn story — what each LinkedIn ad
*delivered* per day: impressions, clicks, spend, reach, the leads its Lead Gen Forms captured
(`one_click_leads` / `lead_form_opens`), the site conversions its pixel attributed, plus engagement
and the video funnel. Like the other loaders it's incremental and safe to re-run.

**Where it joins the others:** `perf_linkedin` shares `client_slug` / `agency_slug` and a campaign
dimension with `perf_ga4` / `perf_the_trade_desk`, so a client view can line up LinkedIn spend
against the outcome it drove. It is the **Windsor-native replacement** for the Snowflake-sourced
`raw_snowflake.linkedin_ads_apac` that Schneider / PropTrack / STT / HireRight / Cloudflare read today
— those clients can migrate their `stg_linkedin` onto this table over time (same metrics, richer set).

---

## What's in here

| File | What it does |
|---|---|
| [`create_linkedin_table.py`](create_linkedin_table.py) | **One-time, run FIRST.** Creates `raw_windsor.perf_linkedin` at the creative grain, partitioned by `metric_date`, clustered by `account_id, campaign_id`. Idempotent — but it **creates, doesn't alter**: to change columns on an existing (empty) table, drop it first (`bq rm -f -t bidbrain-analytics:raw_windsor.perf_linkedin`). |
| [`linkedin_loader.py`](linkedin_loader.py) | **The loader.** Per-account **two-pass** fetch from Windsor's blended `/all` endpoint (with the `linkedin__` prefix), merges the passes, transforms, and `MERGE`s into `perf_linkedin`. Runtime artifacts go to `_run/`. |
| [`probe_linkedin_fields.py`](probe_linkedin_fields.py) | **Throwaway diagnostic.** Hits `/all` per-account and prints the hierarchy verdict, currency, populated-vs-NULL, the account roster, and any MongoDB campaigns — how the facts below were confirmed. Not part of the normal run. |
| [`truncate_linkedin.py`](truncate_linkedin.py) | **Manual reset.** `TRUNCATE`s `perf_linkedin`. Rarely needed — the loader resumes backfills on its own. |
| `Dockerfile` / `.dockerignore` / `requirements.txt` | Container for the `windsor-linkedin-ingest` Cloud Run job. **Wired into [`scripts/deploy_ingest_jobs.ps1`](../../../scripts/deploy_ingest_jobs.ps1)** (2026-07-21) — scheduled daily at **21:40 UTC**, just before the client exports. The broken account is skipped cleanly each run. |
| `README.md` | This file. |

---

## Grain & key

- **Grain:** one row per **`account_id` × `creative_id` × `metric_date`** — creative-level daily delivery.
- **MERGE key:** those three columns; `account_id` / `creative_id` coalesced to `'(not set)'` so the key
  is never NULL. `_MERGE_KEY_COLS` in [`linkedin_loader.py`](linkedin_loader.py) is the single source of
  truth for both the staging dedup and the SQL `ON` clause.
- **Campaign / campaign-group / creative attributes ride along, NOT keys.** `campaign_id`,
  `campaign_name` (Windsor `campaign`), `campaign_group_name`, `campaign_type`, `objective_type`,
  `campaign_status`, `creative_status`, `landing_page`, `share_title` are functionally determined by
  `creative_id`.
- **Tenant key:** `account_id` — LinkedIn's numeric account id (`510177932`).

---

## The five findings the probe settled (2026-07-21)

1. **Grain.** On `/all`, `campaign_group_id` comes back **ALL NULL**, but `campaign_id` (100%) and
   `creative_id` (100%) both populate — exactly one row per (account, campaign, creative, date). So the
   grain is **creative by id**, and we store `campaign_group_name` but **omit** `campaign_group_id`.
2. **20-field cap.** LinkedIn's adAnalytics API rejects any request with **> 20 fields**. We want ~30
   columns, so each chunk is fetched in **TWO ≤20-field passes** (`FIELDS_GROUP_A` = delivery + leads +
   conversions, `FIELDS_GROUP_B` = engagement + video) and merged on `(account_id, creative_id, date)`
   before the MERGE — the **GA4 two-pass pattern**.
3. **92-day reach cap.** `approximate_unique_impressions` (reach) is only available for windows **≤ 92
   days**. `CHUNK_DAYS = 30` keeps every request under it.
4. **Per-account fetch is mandatory.** `/all` fails the **whole** multi-account request if **one**
   account errors, so the loader fetches **one account per request**. Two failure shapes seen: account
   **`502299829` returns HTTP 500 `'start'` for every request** (a Windsor bug — a campaign missing a
   start date breaks its adAnalytics pull) → treated like "not available" and **skipped**; a big account
   over a 90-day window can return 500 **"Response ended prematurely"** (size) → **transient, retried**
   (small chunks avoid it).
5. **Currency.** `currency` populates 100% and is the account's **native** spend currency — **AUD, SGD
   and USD** all appear across accounts, **not USD**. Stored on every row for FX in client views.

---

## Accounts (34 granted; 10 delivering data as of 2026-07-21)

The connector is granted **34** LinkedIn accounts. A scan over 2025-07 → 2026-07 found **10** with
delivery data; the rest returned zero rows (no spend in-window) and one is broken:

| account_id | account_name | client / agency | note |
|---|---|---|---|
| 517045062 | SchneiderElectric_TransmissionSG_AUD | schneider / transmission | |
| 504047196 | SchneiderElectric_TransmissionSG_USD | schneider / transmission | |
| 516221072 | SchneiderElectric_TransmissionSG_SGD | schneider / transmission | |
| 515691430 | APAC - STT GDC - SGD | stt / transmission | |
| 511609128 | STTGDC_TransmissionSG_USD | stt / transmission | |
| 510177932 | PropTrack_TransmissionSG_AUD | proptrack / transmission | |
| 513554482 | HireRight_TransmissionSG_USD | hireright / transmission | |
| 520254094 | Cloudflare APAC | cloudflare / transmission | |
| 516746102 | ResetData | resetdata / 100-digital | new LinkedIn source for a 100-digital client |
| 507877947 | APJC | *(unmapped → 'apjc')* | Cisco APJC — real spend, **not one of our dashboards** |
| **502299829** | **(unreadable)** | — | **BROKEN**: HTTP 500 `'start'` on every request; skipped every run |

The other 23 accounts (`504606769`, `504758918`, `507224127`, `508673116`, `508732444`, `508766215`,
`508768204/5`, `508801607`, `509003962`, `509046900`, `509091286`, `509841591`, `510202977`,
`511313581`, `512344932`, `512350710`, `512810387`, `516748074`, `517047078`, `547920275`, `547920277`,
`547960230`) returned **zero rows** — connected but no delivery in the scanned window. **MongoDB was not
among any of them** (see below).

**Client mapping** lives in `LINKEDIN_ACCOUNT_TO_CLIENT` (checked first) with a keyword fallback over
`account_name` + `campaign` (`CLIENT_TO_AGENCY`). The keyword fallback tags any `MONGODB_…` campaign to
`('mongodb','transmission')` the moment such a row appears, regardless of which account it lands in.

### ⚠️ MongoDB has no LinkedIn data yet

The requested campaign `MONGODB_2026-Q3_AWS-IMMERSION-DAY_AU_LEAD-GENERATION_LINKEDIN` was **not found**
in any readable account across a full year. It is therefore either **(a)** in the unreadable broken
account `502299829`, or **(b)** built in LinkedIn but **not yet delivering/spending** (Q3 2026 had just
begun) — so Windsor returns no rows for it. The loader + the `client_mongodb` view are built so that the
moment MongoDB delivery lands (or Windsor fixes `502299829`), it flows through with no further code
change.

---

## Metrics are additive base only

`perf_linkedin` stores only **additive base metrics** — delivery (`impressions`, `clicks`, `spend`,
`reach`, `landing_page_clicks`), engagement (`engagements`, `likes`, `comments`, `shares`, `follows`),
lead-gen forms (`one_click_leads`, `lead_form_opens`), the site-conversion split
(`ext_website_conversions` + post-click / post-view) and the video funnel (`video_views` /
`video_starts` / `video_completions` / `video_q25` / `video_q50` / `video_q75`). Do **not** add
`ctr` / `cpc` / `cpm` / `cpl` / `*_rate` / `frequency` / `roas` as columns — derive them in client SQL:

```sql
ctr  = SUM(clicks) / NULLIF(SUM(impressions), 0)
cpc  = SUM(spend)  / NULLIF(SUM(clicks), 0)
cpm  = SUM(spend)  / NULLIF(SUM(impressions), 0) * 1000
cpl  = SUM(spend)  / NULLIF(SUM(one_click_leads), 0)
video_completion_rate = SUM(video_completions) / NULLIF(SUM(video_starts), 0)
frequency = SUM(impressions) / NULLIF(SUM(reach), 0)   -- approximate; daily reach is not additive
```

**One cost field:** `spend` (LinkedIn cost, in `currency`). Windsor's `totalcost` variant is **not**
stored (duplicate). **Site conversions are NUMERIC** (LinkedIn can report modeled/fractional); lead-form
counts + engagement + video are INT64. `reach` is **non-additive across days** — derive frequency, never
SUM reach for a period total. Full fidelity is preserved in `raw_row` (both passes merged).

---

## Run modes

See [the parent README](../README.md#how-the-loaders-work-shared-design) for the shared model. Same
per-account incremental / backward-walk backfill as the Reddit loader:

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\linkedin\create_linkedin_table.py                 # one-time
.\.venv\Scripts\python.exe windsor_data_pull\linkedin\linkedin_loader.py                        # normal incremental run
.\.venv\Scripts\python.exe windsor_data_pull\linkedin\linkedin_loader.py 2026-06-22 2026-07-21  # fixed range (all accounts)
.\.venv\Scripts\python.exe windsor_data_pull\linkedin\linkedin_loader.py 2026-06-22 2026-07-21 --force  # ignore cache
```

The broken account is logged and **skipped** (`AccountUnavailableError`) rather than aborting the run.

---

## See also

- [Parent README](../README.md) — shared loader design, auth, first-time setup order.
- [`../reddit/README.md`](../reddit/README.md) — the loader whose per-account `/all` skeleton this shares.
- [`../ga4/README.md`](../ga4/README.md) — the two-pass metric-group merge this borrows for the 20-field cap.
