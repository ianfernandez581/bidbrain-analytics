# client_cloudflare — BigQuery view definitions (DDL)

The export job ([../job/main.py](../job/main.py)) reads these BigQuery views to
build `cloudflare.json`. Apply them with `python client_cloudflare/create_views.py`
(runner one level up).

## Why these are thin (unlike client_mongodb/sql)

MongoDB's BigQuery views *derive* its model from raw `src_*` tables. Cloudflare's
model already exists in Snowflake:

- `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL` — unified
  per-channel/market/day paid delivery (+ LinkedIn engagement, JPY/FX)
- `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_BENCHMARKS_CHANNEL` / `V_BENCHMARKS_MARKET`
- `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_LI_WEEKLY_TARGETS`
- `CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL` — the CS lead pacing model

The job pulls those five views and lands them as BigQuery `src_*` tables. The
views here just re-expose those tables in the exact shape the dashboard reads,
so the on-screen numbers are byte-for-byte what Snowflake already produces.

## Views (dependency order)

| file | view | source table (landed by the job) |
|---|---|---|
| `01_paid_media_model.sql` | `paid_media_model`   | `src_paid_media` |
| `02_pacing_model.sql`     | `pacing_model`       | `src_pacing` |
| `03_benchmarks_channel.sql` | `benchmarks_channel` | `src_benchmarks_channel` |
| `04_benchmarks_market.sql`  | `benchmarks_market`  | `src_benchmarks_market` |
| `05_li_weekly_targets.sql`  | `li_weekly_targets`  | `src_li_weekly` |

## Column-name contract

`01_paid_media_model.sql` lists columns explicitly so the JSON keys are locked.
If `V_PAID_ADS_FINAL_MODEL` ever renames a column (e.g. `FORM_OPENS`), change it
here — this is the single place that maps Snowflake column names to the
dashboard's expected fields. `02_pacing_model.sql` is `SELECT *` because the
dashboard reads `V_PACING_FINAL_MODEL` columns by name (e.g. `LEAD_STATUS`,
`MARKET_REGION`, `ALLOCATED_TARGET`, `DAY`, `LEAD_ID_SF`).

## Want true MongoDB parity later?

Replace these pass-throughs with real BigQuery DDL ported from the four Snowflake
`CREATE …` scripts (the `V_STG_*`, `V_PAID_ADS_FINAL_MODEL`, `V_PACING_FINAL_MODEL`
logic), and switch the job to pull the raw `APAC_ALL_PLATFORM.PUBLIC.*` tables.
Then BigQuery owns the model, exactly like MongoDB.
