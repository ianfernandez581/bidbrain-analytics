# clients/client_mongodb/sql/ — the BigQuery view definitions (the stage-2 transform)

> The version-controlled `CREATE OR REPLACE VIEW` files that turn the shared raw data into
> MongoDB's dashboard-ready numbers. The export job ([`../job/main.py`](../job/README.md)) reads
> these views to build `mongodb.json`.

**Plain English:** the raw warehouse data is generic and messy. These saved queries are where
we pick out *only MongoDB's* rows and shape them into the exact figures the dashboard shows —
leads by market, spend by strategy, targets, benchmarks, budgets. **This is where the business
logic lives.** If a number on the dashboard looks wrong, it's almost always one of these files.

These files are the **source of truth** — edit them and re-apply, rather than editing views in
the BigQuery console (or the two drift). The `NN_` filename prefix sets apply order: staging
views (`stg_*`) must exist before the models and rollups that read them.

**Where this sits:** `raw_snowflake.*` → **[these views]** → [`../job/`](../job/README.md) →
`mongodb.json`.

---

## The views (in dependency order)

| File | View | What it does |
|---|---|---|
| [`01_stg_tradedesk.sql`](01_stg_tradedesk.sql) | `stg_tradedesk` | Filters `raw_snowflake.tradedesk_apac_all` to **`ADVERTISER_NAME = "MongoDB"`** and parses the campaign/ad-group naming convention into `PROGRAMME`, `MARKET`, `STRATEGY`, `OBJECTIVE` (via `SPLIT(... , "_")[SAFE_OFFSET(n)]`). |
| [`02_stg_salesforce.sql`](02_stg_salesforce.sql) | `stg_salesforce` | Filters `raw_snowflake.salesforce_cs_apac_all` to MongoDB's **4 campaign IDs** (3 DNB + KGA/IDC) (no status filter). Maps the 3 DNB IDs → `PROGRAMME_LABEL` (KGA/IDC stays `NULL`) and `UPPER(TRIM(COUNTRY_NAME))` → the 4-market bucket (`ANZ` / `INDIA` / `ASEAN` / `KR-HK-TW`, else `OTHER`). **Case-normalised** so variants (`Republic of Korea`, `INDIA`/`india`) land correctly instead of leaking to `OTHER`; genuinely off-plan countries (China, Japan) stay `OTHER`, which the dash surfaces as its own region (in `all_markets`) so every lead is counted. |
| [`03_paid_media_model.sql`](03_paid_media_model.sql) | `paid_media_model` | The unified paid-media delivery model: labels channel `"TradeDesk"`, derives `WEEK_START` (Monday), and `SUM`s impressions/clicks/cost/conversions grouped by all dimensions. `LEADS = 0` (TTD has no lead pixel here). |
| [`04_cs_leads.sql`](04_cs_leads.sql) | `cs_leads` | Lead counts **by market** with three status buckets — `ACCEPTED` (`LEAD_STATUS = "Accepted"`), `REJECTED` (`= "Rejected"`), `NEW_LEADS` (`IN ("Unresponsive","Do Not Contact","New")`, i.e. unprocessed; `Do Not Contact` is IDC-only) — plus `LAST_LEAD_DAY`. **`TOTAL_LEADS` counts only the delivered statuses** `New` / `Unresponsive` / `Accepted` / `Do Not Contact` (the union of the DNB + KGA/IDC definitions below) — it **excludes** `Unqualified` / `Rejected`, so it is **not** `COUNT(*)`. |
| [`05_cs_leads_by_programme.sql`](05_cs_leads_by_programme.sql) | `cs_leads_by_programme` | Same rollup **by programme × market**. **`TOTAL_LEADS` is the "delivered" count, NOT `COUNT(*)`:** for the 3 **DNB** programmes it's `New + Unresponsive + Accepted` (excludes `Unqualified` / `Rejected` — e.g. 399, not the 402 a raw `COUNT(*)` gives); for **KGA/IDC** (the `NULL`-label programme) it's `Unresponsive + Do Not Contact + New` (IDC has no Accepted/Rejected lifecycle). `ACCEPTED` / `REJECTED` / `NEW_LEADS` (=`Unresponsive+New`) keep the full lifecycle breakdown. |
| [`06_targets.sql`](06_targets.sql) | `targets` | Lead targets + delivered snapshot **as a hardcoded table** (plan numbers, per programme × market). |
| [`07_targets_by_programme.sql`](07_targets_by_programme.sql) | `targets_by_programme` | Rolls up `targets` and computes achievement %. |
| [`08_benchmarks_strategy.sql`](08_benchmarks_strategy.sql) | `benchmarks_strategy` | **Hardcoded** CPM / CTR / frequency-cap / budget-weight plan benchmarks per strategy. |
| [`09_benchmarks_market.sql`](09_benchmarks_market.sql) | `benchmarks_market` | **Hardcoded** budget-weight per market. |
| [`10_budget.sql`](10_budget.sql) | `budget` | **Hardcoded** programme budget envelopes (gross/net USD, start/end). |
| [`11_stg_tradedesk_pixel.sql`](11_stg_tradedesk_pixel.sql) | `stg_tradedesk_pixel` | Content-engagement **live staging**: per-fire TTD Universal Pixel conversions from `raw_snowflake.tradedesk_apac_conversion` (`ADVERTISER_ID='9c1w83i'`), rolled up to **`CAMPAIGN_KEY` × `ASSET_KEY`**. Maps the 7 tracking tags → `ASSET_KEY`/`ASSET`, derives click-vs-view (`DISPLAY_CLICK_COUNT>0`) and per-fire DNB vs KGA(IDC) (`COALESCE(click,impression)` campaign → `SPLIT("_")[2]` → `campaignOf`). **Replaced the retired CSV seed.** |
| [`12_pixel_assets.sql`](12_pixel_assets.sql) | `pixel_assets` | Content-engagement: Universal Pixel landing-page views per **content asset × campaign** (the 6 named `MDB_UPM_LPView_*` pixels; the catch-all `default` is excluded here). Reads `stg_tradedesk_pixel`. |
| [`13_pixel_summary.sql`](13_pixel_summary.sql) | `pixel_summary` | **One row per `CAMPAIGN_KEY`** (DNB / KGA(IDC)): window + the `CONTENT_*` (named pixels) vs `DEFAULT_*` (catch-all, view-through-dominated) conversion split (from `stg_tradedesk_pixel`), plus `IMPS`/`COST_USD`/`CLICKS` from the live `paid_media_model` for the same campaign. |

> **The pixel views are now LIVE from `raw_snowflake`** (the manual CSV seed was retired).
> `stg_tradedesk_pixel` reads `raw_snowflake.tradedesk_apac_conversion` (per-fire TTD Universal
> Pixel; mirrored by [`snowflake_data_pull`](../../../ingest/snowflake_data_pull/README.md)) and
> `pixel_assets`/`pixel_summary` read it — so the section refreshes on the normal `*/10` cadence
> with **no manual step**. Each fire carries a derived **`CAMPAIGN_KEY`** (`DNB` / `IDC`) so the
> dashboard's campaign toggle filters the section (still independent of region/date). The old
> device / ad-environment / creative-size dimension cuts are **gone** — those columns aren't in the
> conversion feed (`pixel_dims`, `seed_pixel.py`, and the seed tables were removed).

> **The per-client filter is the main thing you change** when copying this folder for a new
> client: the advertiser in `01_*` and the campaign IDs + market mapping in `02_*`.

> **Plan tables are hardcoded snapshots.** `targets`, `benchmarks_*`, and `budget` are `UNNEST`
> literals transcribed from the media plan — they are **not** live data. Update them here when
> the plan changes.

> **CS scope = 4 campaigns (3 DNB + KGA/IDC).** `02_stg_salesforce.sql` pulls the three **DNB**
> campaign IDs (each mapped to a `PROGRAMME_LABEL`) plus the **KGA/IDC** campaign
> (`701RG00001NKKwQYAX`). The IDC campaign has a `NULL` `PROGRAMME_LABEL` by design — the dashboard
> normalises it to the single KGA (IDC) programme (`progLabel`/`campaignOf`). IDC was briefly
> removed from the pull (2026-06-12) and restored 2026-06-15, so the dashboard's **KGA (IDC)**
> campaign toggle shows delivered leads again; its media-plan rows live in `targets`/`budget`.

---

## Apply them

```powershell
.\.venv\Scripts\python.exe client_mongodb\create_views.py
```
The runner ([`../create_views.py`](../create_views.py)) applies every `*.sql` here in filename
order. Then re-run the export job so `mongodb.json` reflects the change.

## Re-sync from the live views (if someone edited a view in the console)

These files are the source of truth, so prefer editing them. But if a view was changed directly
in BigQuery, re-export to bring git back in sync:

```powershell
$views = @("stg_tradedesk","stg_salesforce","paid_media_model","cs_leads",
           "cs_leads_by_programme","targets","targets_by_programme",
           "benchmarks_strategy","benchmarks_market","budget",
           "stg_tradedesk_pixel","pixel_assets","pixel_summary")
$i = 0
foreach ($v in $views) {
  $i++
  $j = bq show --view --format=prettyjson "client_mongodb.$v" | ConvertFrom-Json
  $name = "{0:D2}_{1}.sql" -f $i, $v
  "CREATE OR REPLACE VIEW ``client_mongodb.$v`` AS`n" + $j.view.query |
    Set-Content "clients/client_mongodb/sql/$name" -Encoding utf8
}
```

## From-scratch rebuild order

`ingest/windsor_data_pull/create_dataset.py` → `ingest/windsor_data_pull/*/create_*table*.py` →
`ingest/snowflake_data_pull/create_dataset.py` → `ingest/snowflake_data_pull/loader.py` (lands
`raw_snowflake.*`) → `clients/client_mongodb/create_views.py` → run the export job.

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../job/README.md`](../job/README.md) — reads these views; documents the JSON contract.
- [`../../snowflake_data_pull/`](../../../ingest/snowflake_data_pull/README.md) — fills the `raw_snowflake.*` tables these views read.
