# dts_data_pull/ — native Google → BigQuery via Data Transfer Service

> The **third ingest unit**, sibling of [`windsor_data_pull/`](../windsor_data_pull/README.md)
> (Windsor → `raw_windsor`) and [`snowflake_data_pull/`](../snowflake_data_pull/README.md)
> (→ `raw_snowflake`). This one uses **Google's own** BigQuery Data Transfer Service (DTS) to
> land **Google Ads** and **GA4** straight into BigQuery — no third-party connector, no Windsor
> plan cap. It then exposes two **flattening views** in the familiar `perf_*` shape.

**Why this exists:** Windsor's Basic plan capped data sources and returned an "Uh-oh, upgrade"
placeholder for Google Ads (real data never arrived). DTS has first-party `google_ads` and `ga4`
connectors, both available in `australia-southeast1`, and both **free** (Google-owned sources cost
nothing for the transfer — you pay only BigQuery storage/query). So Google Ads is solved natively,
and GA4 gets a native alternative to the Windsor `perf_ga4` loader.

**Where this sits:**

```
Google Ads ─┐                          raw_google_ads.ads_*  ──► raw_google_ads.perf_google_ads ─┐
            ├─► BigQuery Data Transfer ─┤                                                          ├─► client views
GA4 ────────┘   Service (daily, free)   raw_ga4.ga4_*         ──► raw_ga4.perf_ga4 ───────────────┘
```

---

## What's in here

| Path | What it does |
|---|---|
| [`create_views.py`](create_views.py) | **The source of truth.** Discovers every DTS table set that exists (one per Google Ads MCC, one per GA4 property), builds the UNION, and `CREATE OR REPLACE`s the three flattening views. Idempotent — **re-run it after adding more GA4 property transfers** and `perf_ga4` extends automatically. Also writes the exact applied DDL to `sql/` for review. |
| [`backfill.py`](backfill.py) | Schedules **GA4 historical backfills** (up to Google's 37-month hard cap) across every GA4 transfer config — a fresh transfer only loads a tiny rolling window, not history. Chunks into ≤180-day requests. **Runs in waves**: DTS caps inflight runs at **300/config**, so re-run every few days until the `perf_ga4` date range stops growing. `--dry-run` to preview. Skips no-access properties (`SKIP_PROPERTIES`). |
| [`backfill_google_ads_history.ps1`](backfill_google_ads_history.ps1) / [`register_backfill_task.ps1`](register_backfill_task.ps1) | **Google Ads** history backfill (kept separate from `backfill.py` to avoid colliding on the 300-run cap). Walks backward one ~290-day chunk per drain, driven by the `BidbrainGoogleAdsBackfill` scheduled task that fires **every 3 hours from 06:00** (a no-op while a chunk is still draining — inflight > 5 — so frequent firing just minimises idle time between chunks); self-unregisters when the account start (or the 37-month `2023-06-01` floor) is reached. |
| [`sql/perf_google_ads.sql`](sql/perf_google_ads.sql) | The applied DDL for `raw_google_ads.perf_google_ads` (generated; for inspection/diffing). |
| [`sql/perf_ga4.sql`](sql/perf_ga4.sql) | The applied DDL for `raw_ga4.perf_ga4` (generated; for inspection/diffing). |
| [`sql/perf_ga4_events.sql`](sql/perf_ga4_events.sql) | The applied DDL for `raw_ga4.perf_ga4_events` (generated; for inspection/diffing). |

Run: `.\.venv\Scripts\python.exe dts_data_pull\create_views.py` (Application Default Credentials,
same as the Windsor loaders).

---

## The views

### `raw_google_ads.perf_google_ads`  — campaign × date
A **transitional bridge** (built by `build_gads_bridge_ddl`), mirroring the GA4 one. Native arm:
DTS `ads_CampaignBasicStats_<mcc>` summed over device/network/slot segments to one row per
campaign×date, joined to `ads_Campaign_<mcc>` (name, channel type) + `ads_Customer_<mcc>`
(account name, currency); `spend = metrics_cost_micros / 1e6`; one MCC config pulls all
sub-accounts. History arm: `raw_windsor.perf_google_ads` (now built — deep history, **back to
2018** for some accounts). Deduped on `(customer_id, campaign_id, metric_date)` with **native
winning**; Windsor's hyphenated `customer_id` is normalized to bare to match. Tagging re-derived
from `customer_id` (`CUSTOMER_NAMES`). Drop the Windsor arm (revert `build_gads_bridge_ddl` →
`build_view_ddl`) once the native backfill is complete.

### `raw_ga4.perf_ga4`  — property × date × session source/medium/campaign × channel group
A **transitional bridge** (built by `build_ga4_bridge_ddl`): native DTS
`ga4_TrafficAcquisition_<property>` rows `UNION` `raw_windsor.perf_ga4` (which already holds
deep contiguous history — back to **2022** for some properties), deduped on the GA4 grain key
with **native winning over Windsor**. So you get full history *immediately* while the throttled
native backfill catches up; once native covers everything, drop the Windsor arm (revert
`build_ga4_bridge_ddl` → `build_view_ddl`) with zero consumer impact. Windsor also covers the
properties native can't reach. Column-for-column identical to `raw_windsor.perf_ga4` (same schema
on both arms). **13 properties** currently have a native DTS transfer (the 7 with no
`ian@100.digital` GA4 access — see `SKIP_PROPERTIES` in `backfill.py` — are served by the
Windsor arm only); across both arms the view spans the full ~20-property set, ~360k rows today.

### `raw_ga4.perf_ga4_events`  — property × date × event_name
The event-grain sibling, same bridge pattern (`build_ga4_events_bridge_ddl`): native DTS
`ga4_Events_<property>` (eventName → event_name, eventCount → event_count, totalRevenue →
event_value) `UNION` `raw_windsor.perf_ga4_events` (deep history, **back to 2020**), deduped on
`(property_id, metric_date, event_name)` with native preferred. This target schema has no `source`
column, so a literal `_arm` rank (0 native / 1 windsor) drives the dedup and is dropped. **Caveat:**
`is_conversion_event` and `conversions` populate only on the Windsor arm — the GA4 DTS Events report
doesn't expose them. Same 13 native DTS properties as `perf_ga4` (the other 7 ride the Windsor
arm); ~272k rows across the full ~20-property set, 218 event types today.

> **GA4 grain caveat (by design):** `TrafficAcquisition` is **session-grain** and only carries
> sessions / engaged_sessions / event_count / **key_events (= GA4's renamed "conversions")** /
> total_revenue. The user-grain columns (`total_users`, `new_users`) and ecommerce columns
> (`purchase_revenue`, `ecommerce_purchases`, `transactions`, `screen_page_views`,
> `user_engagement_duration`) live in *other* GA4 DTS reports at incompatible grains, so they are
> emitted as **NULL** here — never wrongly joined. The full perf_ga4 column list is kept so the
> view stays a drop-in.

**`client_slug` / `agency_slug` tagging:** edit the `GADS_CLIENT` / `GA4_CLIENT` dicts at the top
of `create_views.py`. Google Ads falls back to a slug of the account name; GA4 has no account name
in this report, so it defaults to `unknown` until you map the property. `318963196` is seeded as
`stt`.

---

## The transfers themselves (one-time setup, already done)

Created in region `australia-southeast1`, project `bidbrain-analytics`:

- Datasets `raw_google_ads` and `raw_ga4`.
- **Google Ads:** one config on the **MCC `345-189-6252`** (`customer_id` `3451896252`, no
  hyphens) → `raw_google_ads`. Pulls all 5 sub-accounts. **Done.**
- **GA4:** one config **per property** (`property_id` is a single string — no batch). `318963196`
  done via CLI; the rest are created in the
  [Cloud Console transfers UI](https://console.cloud.google.com/bigquery/transfers/new?project=bidbrain-analytics)
  (source *Google Analytics 4*, dest `raw_ga4`) — one OAuth consent covers a whole browser session.

**OAuth gotcha (CLI):** these are `FIRST_PARTY_OAUTH` sources. `bq mk --transfer_config` prints a
consent URL and reads a single-use `version_info` code from stdin
(`printf '%s\n' CODE | bq mk --transfer_config …`). The authorization does **not** carry across
separate `bq mk` runs — each config needs its own fresh code. That's why many GA4 properties go
through the Console, not the CLI.

To add a transfer from the CLI (example):
```bash
bq --location=australia-southeast1 mk -d raw_ga4   # once
printf '%s\n' '<version_info_from_consent_url>' | bq mk --transfer_config \
  --project_id=bidbrain-analytics --data_source=ga4 --target_dataset=raw_ga4 \
  --display_name="GA4 <property_id> -> raw_ga4" --params='{"property_id":"<property_id>"}'
```

---

## See also
- [`windsor_data_pull/`](../windsor_data_pull/README.md) — the connector-based ingest this
  supersedes for Google Ads; its `ga4/ga4_loader.py` holds the canonical 20-property list.
- [Root README §6.1](../README.md#61-the-layered-bigquery-model) — how the raw layers feed clients.
