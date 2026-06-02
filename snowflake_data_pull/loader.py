"""
snowflake_data_pull/loader.py — mirror the Snowflake source tables into BigQuery.

A simple, dumb copy: `SELECT *` from each configured Snowflake source table and
WRITE_TRUNCATE it into the shared `raw_snowflake` dataset. There is NO per-client
filter and NO transformation here on purpose -- every client dashboard reads this
one shared raw layer and applies its own `WHERE`/rollups in BigQuery views.

This is the Snowflake sibling of windsor_data_pull (which lands Windsor data in
raw_windsor). Run create_dataset.py once first.

To pull another Snowflake source table, add one line to TABLES below.

Auth (same as client_mongodb/job/main.py):
  - Snowflake private key from $SNOWFLAKE_KEY, else Secret Manager
    (snowflake-bq-key) via ADC.
  - BigQuery via ADC.

Run:  python snowflake_data_pull/loader.py
"""
import os
import pandas as pd
from google.cloud import bigquery
import snowflake.connector
from cryptography.hazmat.primitives import serialization

PROJECT      = "bidbrain-analytics"
LOC          = "australia-southeast1"
RAW_DATASET  = "raw_snowflake"
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

# Snowflake source table (fully qualified)  ->  BigQuery table name in raw_snowflake.
# Whole table, every client. Add a line to mirror another source table.
TABLES = {
    'APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"': "salesforce_cs_apac_all",
    'APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"':      "tradedesk_apac_all",
}


def _snowflake_key_bytes():
    """Snowflake private key (PEM) as bytes. Reads $SNOWFLAKE_KEY if set, else
    pulls it from Secret Manager via ADC (the client library returns the raw
    stored bytes, so no CRLF mangling). Mirrors client_mongodb/job/main.py."""
    pem = os.environ.get("SNOWFLAKE_KEY")
    if pem is None:
        from google.cloud import secretmanager
        sm = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT}/secrets/snowflake-bq-key/versions/latest"
        pem = sm.access_secret_version(name=name).payload.data.decode("utf-8")
    return pem.encode()


def sf_connect():
    pkey = serialization.load_pem_private_key(_snowflake_key_bytes(), password=None)
    der = pkey.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    return snowflake.connector.connect(
        account=SF_ACCOUNT, user=SF_USER,
        private_key=der, warehouse=SF_WAREHOUSE)


def main():
    bq = bigquery.Client(project=PROJECT)
    cn = sf_connect()
    try:
        for src, dest in TABLES.items():
            df = cn.cursor().execute(f"SELECT * FROM {src}").fetch_pandas_all()
            df.columns = [c.upper() for c in df.columns]
            ref = f"{PROJECT}.{RAW_DATASET}.{dest}"
            cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
            print(f"loaded {len(df):>7} rows | {src}  ->  {ref}")
    finally:
        cn.close()
    print("done.")


if __name__ == "__main__":
    main()
