# client_mongodb/sql/ — the BigQuery view definitions (the stage-2 transform)

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
| [`02_stg_salesforce.sql`](02_stg_salesforce.sql) | `stg_salesforce` | Filters `raw_snowflake.salesforce_cs_apac_all` to MongoDB's **4 campaign IDs** and drops `LEAD_STATUS = "New"`. Maps campaign ID → `PROGRAMME_LABEL` and `COUNTRY_NAME` → the 4-market bucket (`ANZ` / `INDIA` / `ASEAN` / `KR-HK-TW`, else `OTHER`). |
| [`03_paid_media_model.sql`](03_paid_media_model.sql) | `paid_media_model` | The unified paid-media delivery model: labels channel `"TradeDesk"`, derives `WEEK_START` (Monday), and `SUM`s impressions/clicks/cost/conversions grouped by all dimensions. `LEADS = 0` (TTD has no lead pixel here). |
| [`04_cs_leads.sql`](04_cs_leads.sql) | `cs_leads` | Lead counts **by market** with per-status buckets (`Accepted`, `Rejected`, `New`, `Unresponsive`, `Do Not Contact`) + `LAST_LEAD_DAY`. |
| [`05_cs_leads_by_programme.sql`](05_cs_leads_by_programme.sql) | `cs_leads_by_programme` | Same rollup **by programme × market** (no `Rejected` bucket). |
| [`06_targets.sql`](06_targets.sql) | `targets` | Lead targets + delivered snapshot **as a hardcoded table** (plan numbers, per programme × market). |
| [`07_targets_by_programme.sql`](07_targets_by_programme.sql) | `targets_by_programme` | Rolls up `targets` and computes achievement %. |
| [`08_benchmarks_strategy.sql`](08_benchmarks_strategy.sql) | `benchmarks_strategy` | **Hardcoded** CPM / CTR / frequency-cap / budget-weight plan benchmarks per strategy. |
| [`09_benchmarks_market.sql`](09_benchmarks_market.sql) | `benchmarks_market` | **Hardcoded** budget-weight per market. |
| [`10_budget.sql`](10_budget.sql) | `budget` | **Hardcoded** programme budget envelopes (gross/net USD, start/end). |

> **The per-client filter is the main thing you change** when copying this folder for a new
> client: the advertiser in `01_*` and the campaign IDs + market mapping in `02_*`.

> **Plan tables are hardcoded snapshots.** `targets`, `benchmarks_*`, and `budget` are `UNNEST`
> literals transcribed from the media plan — they are **not** live data. Update them here when
> the plan changes.

> **Known pending item:** in `02_stg_salesforce.sql` the campaign-ID `CASE` labels only the
> three **DNB** campaigns; the **KGA/IDC** campaign (`701RG00001NKKwQYAX`) is in the `WHERE`
> filter but not yet mapped to a `PROGRAMME_LABEL` (so it currently resolves to `NULL`).
> Finishing the IDC split is on the [root TODO](../../README.md#11-current-status--todo).

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
           "benchmarks_strategy","benchmarks_market","budget")
$i = 0
foreach ($v in $views) {
  $i++
  $j = bq show --view --format=prettyjson "client_mongodb.$v" | ConvertFrom-Json
  $name = "{0:D2}_{1}.sql" -f $i, $v
  "CREATE OR REPLACE VIEW ``client_mongodb.$v`` AS`n" + $j.view.query |
    Set-Content "client_mongodb/sql/$name" -Encoding utf8
}
```

## From-scratch rebuild order

`windsor_data_pull/create_dataset.py` → `windsor_data_pull/*/create_*table*.py` →
`snowflake_data_pull/create_dataset.py` → `snowflake_data_pull/loader.py` (lands
`raw_snowflake.*`) → `client_mongodb/create_views.py` → run the export job.

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../job/README.md`](../job/README.md) — reads these views; documents the JSON contract.
- [`../../snowflake_data_pull/`](../../snowflake_data_pull/README.md) — fills the `raw_snowflake.*` tables these views read.
