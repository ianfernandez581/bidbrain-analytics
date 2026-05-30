# client_mongodb — BigQuery view definitions (DDL)

The export job ([../job/main.py](../job/main.py)) reads from these BigQuery
views to build `mongodb.json`. They must be version-controlled so the data model
is reproducible on a fresh project (today the live definitions exist **only**
inside BigQuery — that gap is what this folder closes).

Each view is one file: `NN_<view>.sql` containing a single
`CREATE OR REPLACE VIEW`. The `NN_` prefix sets apply order — staging views
(`stg_*`) before the models and rollups that read them.

Apply them with: `python infra/create_views.py`

## Views the job depends on (dependency order)

1. `stg_tradedesk`, `stg_salesforce` — parse/clean the `src_*` tables
2. `paid_media_model` — unified paid-media delivery model
3. `cs_leads`, `cs_leads_by_programme` — lead rollups
4. `targets`, `targets_by_programme` — lead targets
5. `benchmarks_strategy`, `benchmarks_market` — plan benchmarks
6. `budget` — programme budget envelopes

## Export the live definitions (one-time, from a machine with BigQuery access)

PowerShell:

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

Commit the generated `.sql` files. After that, a from-scratch rebuild is:
`create_dataset.py` → `create_*_tables.py` → run export job once (lands `src_*`)
→ `create_views.py` → re-run export job.
