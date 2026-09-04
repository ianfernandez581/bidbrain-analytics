# ingest/windsor_data_pull/ — pull ad-platform + analytics performance into BigQuery (`raw_windsor`)

> One of the two **shared ingest** units. Loads ad-platform performance (Meta, Trade Desk,
> Google Ads, Reddit Ads) and web-analytics outcomes (GA4) from **Windsor.ai** into the shared
> BigQuery dataset `raw_windsor`, for all clients. The Windsor sibling of
> [`ingest/snowflake_data_pull/`](../snowflake_data_pull) (which fills `raw_snowflake`).

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
| [`google_ads/`](google_ads/README.md) | The **Google Ads** loader (`perf_google_ads`) + its table-creation script. One row per (customer × date × campaign), via the dedicated `google_ads` connector (single-pass). [Open its README →](google_ads/README.md) |
| [`reddit/`](reddit/README.md) | The **Reddit Ads** loader (`perf_reddit`) + its table-creation script. One row per (account × ad × date), via the blended `/all` endpoint. [Open its README →](reddit/README.md) |
| [`linkedin/`](linkedin/README.md) | The **LinkedIn Ads** loader (`perf_linkedin`) + its table-creation script. One row per (account × creative × date), via the blended `/all` endpoint with a `linkedin__` prefix. **Two-pass fetch** (LinkedIn caps a request at 20 fields); per-account (skips accounts that hard-error). The Windsor-native replacement for `raw_snowflake.linkedin_ads_apac`. [Open its README →](linkedin/README.md) |
| [`fields/`](fields/README.md) | The **field CATALOGUE** loader (`windsor_fields`) — metadata, not performance. Mirrors Windsor's entire field reference (`https://connectors.windsor.ai/all/fields`, the [data-field/all](https://windsor.ai/data-field/all/) page, ~37.8k fields × 242 connectors) into BigQuery daily with `first_seen`/`last_seen` so new fields are visible. [Open its README →](fields/README.md) |
| [`hubspot/`](hubspot/README.md) | The **HubSpot CRM** loader (`hubspot_contacts` ~4.7k + `hubspot_deals` ~242) for **Reset Data** (connector `hubspot`, account `45274177`). CRM **state, not a date series** → a WRITE_TRUNCATE snapshot; all-STRING raw + typed `v_hubspot_*` views. Includes Reset Data's custom `contact_rd_*` props (`contact_rd_billing_balance` = **RdBillingBalance**). [Open its README →](hubspot/README.md) |
| [`connections/`](connections/README.md) | **NOT a loader - the monitor of the loaders.** The `windsor-connections-probe` Cloud Run job (hourly) probes every configured account above directly against Windsor, reads each account's newest day in BigQuery, classifies it (ok / frozen / quiet / not_granted / error / idle), writes `windsor_connections.json` to the status bucket for **The Grid -> Connections tab**, and **emails ian@ + charles@ on a state change** (Gmail API). Exists because a lapsed grant fails nothing: the loader exits green while one account survives. `config.json` there is the account -> client map + the grant re-auth ledger. [Open its README →](connections/README.md) |
| `README.md` | This file. |

---

## First-time setup order

```powershell
.\.venv\Scripts\python.exe windsor_data_pull\create_dataset.py                       # 1. the shared dataset
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\create_trade_desk__tables.py  # 2. the TTD table
.\.venv\Scripts\python.exe windsor_data_pull\meta\create_meta_table.py               # 3. the Meta table
.\.venv\Scripts\python.exe windsor_data_pull\ga4\create_ga4_table.py                 # 4. the GA4 acquisition table
.\.venv\Scripts\python.exe windsor_data_pull\ga4\create_ga4_events_table.py          # 5. the GA4 events table
.\.venv\Scripts\python.exe windsor_data_pull\google_ads\create_google_ads_table.py   # 6. the Google Ads table
.\.venv\Scripts\python.exe windsor_data_pull\reddit\create_reddit_table.py           # 7. the Reddit table
.\.venv\Scripts\python.exe windsor_data_pull\linkedin\create_linkedin_table.py       # 7b. the LinkedIn table
.\.venv\Scripts\python.exe windsor_data_pull\fields\create_fields_table.py           # 8. the field catalogue table
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py                     # 8. first load (backfills)
.\.venv\Scripts\python.exe windsor_data_pull\tradedesk\tradedesk_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\ga4\ga4_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\ga4\events_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\google_ads\google_ads_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\reddit\reddit_loader.py
.\.venv\Scripts\python.exe windsor_data_pull\linkedin\linkedin_loader.py             # LinkedIn (per-account backfill)
.\.venv\Scripts\python.exe windsor_data_pull\fields\fields_loader.py                 # populate the catalogue
```

**Auth:** Windsor API key + BigQuery + Storage all via **Application Default Credentials** —
no gcloud-path or machine-specific config baked in, so the same code runs locally
(after `gcloud auth application-default login`) and on Cloud Run/Cloud Build. The key itself
is read from Secret Manager (`windsor-api-key`). Run [`scripts/start_day.ps1`](../../scripts/README.md)
first to confirm both credential systems are valid.

---

## How the loaders work (shared design)

All the loaders share the same per-chunk pipeline, so once you understand one you understand them all:

1. **Fetch in date chunks** from the Windsor API (`CHUNK_DAYS` per loader — Meta & Trade Desk
   `3`, GA4 acquisition `14`, GA4 events `200`, Google Ads `90`, Reddit `30`), with
   capped-backoff **retries** on transient
   errors (timeouts, 429, 5xx) and **fail-fast** on permanent 4xx (bad field / auth). An
   unattended/scheduled run can't hang forever.
2. **Cache each chunk** to disk so a re-run doesn't re-fetch what it already has (`--force`
   overrides).
3. **Transform** the raw row into the table's typed schema, keeping the full original row in a
   `raw_row` JSON column for fidelity.
4. **Load → staging table → `MERGE`** into the main table on a natural key, so re-pulling a
   day is **idempotent** (no duplicates; revised metrics overwrite).

**Run modes (every loader):**

| Invocation | Mode |
|---|---|
| no args | **The normal/scheduled run.** Meta, GA4, Google Ads & Reddit = incremental per-account/property (forward from each one's last day; brand-new ones get a full backward-walk backfill). Trade Desk = backward walk that auto-discovers how far back data exists. |
| two dates, e.g. `… 2026-05-25 2026-05-30` | **Fixed range** (all accounts/properties together) — a targeted re-pull. |
| append `--force` | re-fetch even cached chunks (the MERGE stays idempotent). |

GA4 adds one wrinkle on top of this shared model — each chunk is fetched in **two metric-group
passes** (the GA4 Data API caps a request at 9 dims / 10 metrics) and merged before the MERGE.
See [`ga4/README.md`](ga4/README.md).

**Runtime artifacts** (cached chunk JSON, logs, temp NDJSON) are written to a `_run/` folder
**next to each loader**, anchored via `__file__` — never the repo root, never committed
(`_run/` is gitignored).

**Shared infrastructure:** every loader stages NDJSON through the `bidbrain-analytics-staging`
GCS bucket before the BigQuery `MERGE`. Every table is **partitioned by `metric_date`** and
**clustered** for cheap, fast slicing. Each tags every row with `client_slug` / `agency_slug`
inferred from the account/property/campaign names (see the `CLIENT_TO_AGENCY` map in each loader;
GA4 supports an explicit `PROPERTY_TO_CLIENT` override, Google Ads a `CUSTOMER_TO_CLIENT` map, and
Reddit a `REDDIT_ACCOUNT_TO_CLIENT` map — since those account/property names are often generic).

---

## Deployment & scheduling (Cloud Run jobs)

These loaders run in production as shared **Cloud Run ingest jobs**, built and scheduled by
[`scripts/deploy_ingest_jobs.ps1`](../../scripts/deploy_ingest_jobs.ps1) (run as yourself — never
cloudbuild from a laptop). All run as the shared `ingest-runner@` service account and read the
Windsor key from Secret Manager (`windsor-api-key`).

| Loader | Cloud Run job | Cron (UTC) |
|---|---|---|
| Meta | `windsor-meta-ingest` | `15 21 * * *` (daily) |
| Trade Desk | `windsor-tradedesk-ingest` | `35 4,21 * * *` (twice daily; the 04:35 UTC = 14:35 AEST run lands Sydney-yesterday data by ~14:45 the same Sydney day, benefiting every TTD dashboard. Was 01:35 from 2026-08-07; moved 2026-09-01 because Windsor's TTD endpoint is degraded ~00:00-03:30 UTC while TTD finalises the prior day, so the 01:35 run failed or limped for weeks. The job also sets `WINDSOR_LOOKBACK_DAYS=35` + `WINDSOR_MAX_ATTEMPTS=4` — bounded pulls that fit the 3600s task cap; see the loader header) |
| Field catalogue | `windsor-fields-ingest` | `45 21 * * *` (daily) |
| Reddit | `windsor-reddit-ingest` | `50 21 * * *` (daily) |
| LinkedIn | `windsor-linkedin-ingest` | `40 21 * * *` (daily) |
| HubSpot | `windsor-hubspot-ingest` | `55 21 * * *` (daily) |

> **Freshness contract — windsor is deliberately DAILY, not `*/10` self-gating.** Unlike the
> binding `*/10` self-gating rule for *client export jobs* and `snowflake-ingest`, these raw-layer
> Windsor loaders run on a **fixed daily** Cloud Scheduler trigger (`<job>-daily`), staggered to
> land **before the 22:00 UTC `*-export` jobs** so every dashboard's nightly export reads fresh raw
> data. Only `snowflake-ingest` self-gates at `*/10`; neto + windsor stay on fixed crons (tradedesk
> is the one twice-daily exception, see the table). There is **no `_freshness.json` watermark** in
> this unit.
>
> - **Reddit & HubSpot** are now scheduled (wired into `deploy_ingest_jobs.ps1` on 2026-07-16). The
>   Reddit job **skips cleanly (exit 0, 0 rows)** if its Windsor connector grant lapses — so it
>   self-heals the moment the account is re-granted; no code change needed then.
> - **A TOTAL outage now FAILS the job (2026-08-17).** One unavailable account stays a designed skip,
>   but when the skipped set covers **every** configured account, `meta` / `linkedin` / `reddit` exit
>   1 naming the re-auth URL. Before this, a lapsed grant looked identical to a quiet night: the
>   **Meta grant lapsed 2026-08-11**, all 6 accounts returned HTTP 400 `not available` every night,
>   the job completed successfully with `Rows fetched: 0`, and geocon's dashboard silently stopped
>   advancing for six days while its campaigns were still ACTIVE — the only symptom being a
>   `source_stale` badge that reads as somebody else's problem. Re-auth:
>   <https://onboard.windsor.ai> (`?datasource=facebook` / `linkedin` / `reddit`).
> - **After a Windsor re-grant, VERIFY the account_name before repointing any id.** The 2026-07-16
>   reddit re-grant appeared to mint a new id (`a2_iq3fdsq6rem5`) and the loader was repointed to it —
>   but that id was actually **Transmission_Cloudflare's** Reddit account, so Cloudflare delivery flowed
>   into the ResetData dashboard for 3 weeks (and ResetData's real rows were deleted as a presumed
>   duplicate). The 2026-08-05 re-grant restored ResetData's **original** id (`a2_igd0szmw7roq`) — ids
>   are not reliably re-minted. An opaque `a2_...` id proves nothing about whose account it is: probe
>   the API for `account_name` first (see `reddit/README.md` for the full incident + recovery).
> - **Google Ads & GA4** also auto-refresh daily via the native **BigQuery Data Transfer Service**
>   (`raw_google_ads` / `raw_ga4`); the Windsor `google_ads` / `ga4` loaders here coexist with — and
>   do not replace — those DTS mirrors. They are run from a laptop, not scheduled here.
> - **Trade Desk** is healthy and flowing (verified 2026-07-16: `windsor-tradedesk-ingest` ran to
>   success and `perf_the_trade_desk` is fresh). The earlier "connector down" state (from 2026-06-13)
>   is resolved.

---

## See also

- [`meta/README.md`](meta/README.md), [`tradedesk/README.md`](tradedesk/README.md), [`ga4/README.md`](ga4/README.md), [`google_ads/README.md`](google_ads/README.md), and [`reddit/README.md`](reddit/README.md) — per-loader detail (schemas, fields, MERGE keys, caveats).
- [`scripts/deploy_ingest_jobs.ps1`](../../scripts/deploy_ingest_jobs.ps1) — builds + schedules the shared ingest Cloud Run jobs.
- [`ingest/snowflake_data_pull/`](../snowflake_data_pull/README.md) — the other shared ingest unit.
- [Root README §6.1](../../README.md#61-the-layered-bigquery-model) — how the raw layers feed clients.
