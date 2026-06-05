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
| [`create_views.py`](create_views.py) | **The source of truth.** Discovers every DTS table set that exists (one per Google Ads MCC, one per GA4 property), builds the UNION, and `CREATE OR REPLACE`s the two flattening views. Idempotent — **re-run it after adding more GA4 property transfers** and `perf_ga4` extends automatically. Also writes the exact applied DDL to `sql/` for review. |
| [`sql/perf_google_ads.sql`](sql/perf_google_ads.sql) | The applied DDL for `raw_google_ads.perf_google_ads` (generated; for inspection/diffing). |
| [`sql/perf_ga4.sql`](sql/perf_ga4.sql) | The applied DDL for `raw_ga4.perf_ga4` (generated; for inspection/diffing). |

Run: `.\.venv\Scripts\python.exe dts_data_pull\create_views.py` (Application Default Credentials,
same as the Windsor loaders).

---

## The two views

### `raw_google_ads.perf_google_ads`  — campaign × date
Replaces the never-built Windsor `perf_google_ads`. Sourced from the DTS convenience views
`ads_CampaignBasicStats_<mcc>` (summed over the device/network/slot segments to one row per
campaign×date), joined to `ads_Campaign_<mcc>` (name, channel type) and `ads_Customer_<mcc>`
(account name, currency). `spend = metrics_cost_micros / 1e6`. One MCC config pulls **all**
sub-accounts (the `customer_id` column separates them).

### `raw_ga4.perf_ga4`  — property × date × session source/medium/campaign × channel group
The native twin of `raw_windsor.perf_ga4` — **column-for-column identical** (verified: a
`SELECT * … UNION ALL …` of the two compiles), so client views can read either source
interchangeably. Sourced from `ga4_TrafficAcquisition_<property>` (one per property; the
script UNIONs them).

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
  supersedes for Google Ads; its `ga4_loader.py` holds the canonical 20-property list.
- [Root README §6.1](../README.md#61-the-layered-bigquery-model) — how the raw layers feed clients.
