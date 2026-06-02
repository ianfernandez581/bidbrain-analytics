# snowflake_data_pull

Mirrors the **Snowflake source tables** into a shared BigQuery dataset
(`raw_snowflake`), once, for **all** clients. The Snowflake sibling of
`windsor_data_pull` (which lands Windsor data in `raw_windsor`).

It does a **dumb full copy** — `SELECT *`, no client filter, no transformation.
Each client dashboard reads this one shared raw layer and applies its own
`WHERE` + rollups in its own BigQuery views. So adding a client is just *a view*,
and Snowflake (which we don't control) is hit **once per refresh**, not once per
client.

## What it pulls

| Snowflake source | → BigQuery table |
|---|---|
| `APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"` | `raw_snowflake.salesforce_cs_apac_all` |
| `APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"` | `raw_snowflake.tradedesk_apac_all` |
| `APAC_ALL_PLATFORM.PUBLIC."LinkedIn Ads - APAC"` | `raw_snowflake.linkedin_ads_apac` |
| `APAC_ALL_PLATFORM.PUBLIC."Reddit Ads - APAC_ALL"` | `raw_snowflake.reddit_ads_apac_all` |
| `APAC_ALL_PLATFORM.PUBLIC."DV360 - APAC"` | `raw_snowflake.dv360_apac` |
| `APAC_ALL_PLATFORM.PUBLIC."Google Ads - APAC"` | `raw_snowflake.google_ads_apac` |

To add another source table, add one line to `TABLES` in `loader.py`.

## Run

```powershell
# use the repo's .venv Python (deps live there, not in global Python)
.\.venv\Scripts\python.exe snowflake_data_pull\create_dataset.py   # once — creates raw_snowflake
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py           # WRITE_TRUNCATE refresh of every table
```

Auth (same as the MongoDB job): Snowflake key from `$SNOWFLAKE_KEY` or Secret
Manager (`snowflake-bq-key`) via ADC; BigQuery via ADC. Run
`gcloud auth application-default login` first if ADC isn't set up.

## How clients consume it

```sql
-- a client's staging view filters the shared raw table:
CREATE OR REPLACE VIEW client_mongodb.stg_salesforce AS
SELECT ...
FROM   raw_snowflake.salesforce_cs_apac_all
WHERE  CAMPAIGN_ID IN ('701RG...','701RG...')   -- per-client filter
  AND  LEAD_STATUS != 'New';                      -- business rule
```

See `client_mongodb/README.md` for the full 3-stage pipeline.
