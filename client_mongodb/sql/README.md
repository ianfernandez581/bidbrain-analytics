# client_mongodb — BigQuery view definitions (DDL)

The export job ([../job/main.py](../job/main.py)) reads from these BigQuery
views to build `mongodb.json`. They are version-controlled here so the data
model is reproducible on a fresh project. (These files are now the source of
truth — edit them and re-apply, rather than editing views in the BigQuery
console, or the two drift.)

Each view is one file: `NN_<view>.sql` containing a single
`CREATE OR REPLACE VIEW`. The `NN_` prefix sets apply order — staging views
(`stg_*`) before the models and rollups that read them.

`01_stg_tradedesk` / `02_stg_salesforce` read the **shared** raw mirror
`raw_snowflake.*` (filled by `../../snowflake_data_pull/`) and apply THIS
client's filter (advertiser / campaign IDs / `LEAD_STATUS != 'New'`). That filter
is the main thing you change when copying this folder for a new client.

Apply them with: `python client_mongodb/create_views.py` (the runner lives one
level up, in [../create_views.py](../create_views.py)).

## Views the job depends on (dependency order)

1. `stg_tradedesk`, `stg_salesforce` — filter this client's slice out of `raw_snowflake.*`
2. `paid_media_model` — unified paid-media delivery model
3. `cs_leads`, `cs_leads_by_programme` — lead rollups
4. `targets`, `targets_by_programme` — lead targets
5. `benchmarks_strategy`, `benchmarks_market` — plan benchmarks
6. `budget` — programme budget envelopes

## Re-sync from the live views (if someone edited a view in the console)

These files are the source of truth, so prefer editing them and re-applying. But
if a view was changed directly in BigQuery, re-export to bring git back in sync:

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

From-scratch rebuild: `windsor_data_pull/create_dataset.py` →
`windsor_data_pull/*/create_*table*.py` → `snowflake_data_pull/create_dataset.py`
→ `snowflake_data_pull/loader.py` (lands `raw_snowflake.*`) →
`client_mongodb/create_views.py` → run the export job.
