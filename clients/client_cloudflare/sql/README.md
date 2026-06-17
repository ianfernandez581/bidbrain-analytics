# client_cloudflare — BigQuery view definitions (DDL)

The export job ([../job/main.py](../job/main.py)) reads the **final** views here to
build `cloudflare.json`. Apply them with `python clients/client_cloudflare/create_views.py`
(runner one level up; the `NN_` prefix encodes dependency order).

**Plain English:** these files hold Cloudflare's business logic — **BigQuery owns the
model** now (since 2026-06-17), exactly like every other client. They were ported from
the Snowflake `CLOUDFLARE_SANDBOX.*` views and read the shared `raw_snowflake.*` mirrors
+ the `client_cloudflare.seed_*` static tables. (Previously these were *thin* pass-throughs
of a Snowflake-modelled `src_*` copy — that exception is gone; see
[../README.md](../README.md#bigquery-owns-the-model-was-the-snowflake-modelled-exception).)

**Where this sits:** `raw_snowflake.*` mirrors + `seed_*` static → **[these views]** →
`cloudflare.json`.

## Views (dependency order)

| file | view | reads | ported from (Snowflake) |
|---|---|---|---|
| `01_stg_linkedin.sql`        | `stg_linkedin`        | `raw_snowflake.linkedin_ads_apac` (ACCOUNT_NAME='Cloudflare APAC') | `V_STG_LINKEDIN_CF` |
| `02_stg_reddit.sql`          | `stg_reddit`          | `raw_snowflake.reddit_ads_apac_all` (ACCOUNT_NAME='Transmission_Cloudflare') | `V_STG_REDDIT_CF` |
| `03_stg_tradedesk.sql`       | `stg_tradedesk`       | `raw_snowflake.tradedesk_apac_all` (ADVERTISER_NAME='Cloudflare') + campaign-name parsing | `V_STG_TRADEDESK_CF` |
| `04_stg_line.sql`            | `stg_line`            | `seed_line_cf` (static) | `V_STG_LINE_CF` |
| `05_paid_media_model.sql`    | `paid_media_model`    | the four `stg_*` (union, market CASE, week key, JPY→USD@155) | `V_PAID_ADS_FINAL_MODEL` |
| `06_paid_creatives_model.sql`| `paid_creatives_model`| the four `stg_*` at creative grain | (was `PAID_CREATIVES_SQL` in the job) |
| `07_benchmarks_channel.sql`  | `benchmarks_channel`  | — (literal constants) | `V_BENCHMARKS_CHANNEL` |
| `08_benchmarks_market.sql`   | `benchmarks_market`   | — (literal constants) | `V_BENCHMARKS_MARKET` |
| `09_li_weekly_targets.sql`   | `li_weekly_targets`   | — (literal constants) | `V_LI_WEEKLY_TARGETS` |
| `10_salesforce_leads_live.sql`| `salesforce_leads_live`| `raw_snowflake.salesforce_cs_apac_all` (the 12-ID CS filter + region/publisher/offer) | `V_SALESFORCE_LEADS_LIVE` |
| `11_tier_mapping_cleaned.sql`| `tier_mapping_cleaned`| `seed_tiers` (static) | `V_TIER_MAPPING_CLEANED` |
| `12_targets_v2_norm.sql`     | `targets_v2_norm`     | `seed_real_targets` (static) | `V_TARGETS_V2_NORM` |
| `13_pacing_model.sql`        | `pacing_model`        | `salesforce_leads_live` + `tier_mapping_cleaned` + `targets_v2_norm` | `V_PACING_FINAL_MODEL` |

## Porting notes (Snowflake → BigQuery)

- `TRUNC(d,'WEEK')` / `DATE_TRUNC('WEEK',d)` → `DATE_TRUNC(d, WEEK(MONDAY))` (Snowflake weeks start Monday — verified).
- `ILIKE '%x%'` → `LOWER(col) LIKE '%x%'`; `LIKE 'CLOUD\_ACQ\_%' ESCAPE` → `STARTS_WITH(...,'CLOUD_ACQ_')`.
- `SPLIT_PART(s,'_',N)` → `IFNULL(SPLIT(s,'_')[SAFE_OFFSET(N-1)], '')` (mirror Snowflake's empty-string-on-overflow).
- `REGEXP_REPLACE(...,'i')` → RE2 `(?i)` inline flag; `UUID_STRING()` → `GENERATE_UUID()`; `QUALIFY` is native.
- The 12-ID CS campaign filter lives in `10_salesforce_leads_live.sql` (this is now its source of truth, not the Snowflake view).
- **`pacing_model` tier sub-split is non-deterministic** (inherited from the source model — see [../README.md](../README.md#bigquery-owns-the-model-was-the-snowflake-modelled-exception)). Dummy rows use `GENERATE_UUID()` so their `LEAD_ID_SF` differs each run (always `DUMMY_*`, excluded from lead counts).

## See also

- [`../README.md`](../README.md) — client overview + the cutover/parity notes.
- [`../job/README.md`](../job/README.md) — reads these views; documents the JSON contract.
- [`../../client_mongodb/sql/README.md`](../../client_mongodb/sql/README.md) — the template's views.
