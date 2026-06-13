# client_cloudflare — BigQuery view definitions (DDL)

The export job ([../job/main.py](../job/main.py)) reads these BigQuery views to
build `cloudflare.json`. Apply them with `python client_cloudflare/create_views.py`
(runner one level up).

**Plain English:** for most clients these files hold the business logic. For Cloudflare they're
deliberately **thin** — the real modelling already happened in Snowflake, so these views just
re-expose the landed copy in the exact column shape the dashboard expects. Their job is to
**lock the JSON contract**, not to compute anything.

**Where this sits:** Snowflake final-model views → [`../job/`](../job/README.md) lands `src_*`
→ **[these views]** → `cloudflare.json`.

## Why these are thin (unlike client_mongodb/sql)

MongoDB's BigQuery views *derive* its model from raw `src_*` tables. Cloudflare's
model already exists in Snowflake:

- `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL` — unified
  per-channel/market/day paid delivery (+ LinkedIn engagement, JPY/FX)
- `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_BENCHMARKS_CHANNEL` / `V_BENCHMARKS_MARKET`
- `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_LI_WEEKLY_TARGETS`
- `CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL` — the CS lead pacing model
- the per-channel staging views `…PAID_MEDIA_REPORTING.V_STG_{LINKEDIN,TRADEDESK,REDDIT,LINE}_CF`
  — for the creative-grain pull (`src_paid_creatives`); the final model collapses
  the creative dimension away, so the job re-derives it one level lower (see
  `PAID_CREATIVES_SQL` in `../job/main.py`)

The job runs six Snowflake queries and lands their results as BigQuery `src_*`
tables. The views here just re-expose those tables in the exact shape the
dashboard reads, so the on-screen numbers are byte-for-byte what Snowflake
already produces.

## Views (dependency order)

| file | view | source table (landed by the job) |
|---|---|---|
| `01_paid_media_model.sql` | `paid_media_model`   | `src_paid_media` |
| `02_pacing_model.sql`     | `pacing_model`       | `src_pacing` |
| `03_benchmarks_channel.sql` | `benchmarks_channel` | `src_benchmarks_channel` |
| `04_benchmarks_market.sql`  | `benchmarks_market`  | `src_benchmarks_market` |
| `05_li_weekly_targets.sql`  | `li_weekly_targets`  | `src_li_weekly` |
| `06_paid_creatives_model.sql` | `paid_creatives_model` | `src_paid_creatives` |

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

## See also

- [`../README.md`](../README.md) — client overview and the divergence rationale.
- [`../job/README.md`](../job/README.md) — lands the `src_*` tables these views read; documents the JSON contract.
- [`../../client_mongodb/sql/README.md`](../../client_mongodb/sql/README.md) — the template's views, which *do* compute the model.
