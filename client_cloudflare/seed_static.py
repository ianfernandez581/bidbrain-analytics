"""
client_cloudflare/seed_static.py — one-time pull of Cloudflare's STATIC inputs.

Unlike the shared APAC platform tables (which snowflake_data_pull mirrors into
raw_snowflake for every client), these three live in CLOUDFLARE_SANDBOX and are
Cloudflare-specific manual uploads that rarely change. So they get a simple
one-shot copy into the client_cloudflare dataset as src_* tables; re-run only
when the manual upload changes.

    CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINE_CF -> client_cloudflare.src_line_cf      (LINE JP spend)
    CLOUDFLARE_SANDBOX.CS_REPORTING.REAL_TARGETS          -> client_cloudflare.src_real_targets  (pacing targets)
    CLOUDFLARE_SANDBOX.CS_REPORTING.TIERS                 -> client_cloudflare.src_tiers          (account -> tier)

Auth (same as every job): Snowflake key from $SNOWFLAKE_KEY else Secret Manager
(snowflake-bq-key) via ADC; BigQuery via ADC.

Run:  .\.venv\Scripts\python.exe client_cloudflare\seed_static.py
"""
import os, re
import pandas as pd
from google.cloud import bigquery
import snowflake.connector
from cryptography.hazmat.primitives import serialization

PROJECT      = "bidbrain-analytics"
LOC          = "australia-southeast1"
DATASET      = "client_cloudflare"
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

# Snowflake static source -> BigQuery table name in client_cloudflare.
TABLES = {
    "CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINE_CF": "src_line_cf",
    "CLOUDFLARE_SANDBOX.CS_REPORTING.REAL_TARGETS":          "src_real_targets",
    "CLOUDFLARE_SANDBOX.CS_REPORTING.TIERS":                 "src_tiers",
}


def _snowflake_key_bytes():
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


def bq_colname(c):
    """BigQuery-safe column name: uppercase, only [A-Z0-9_], must start with a
    letter/underscore. These tables are manual uploads with messy headers like
    'CPM (COST PER THOUSAND IMPRESSIONS)', which BigQuery rejects verbatim."""
    c = re.sub(r"[^0-9A-Za-z_]+", "_", c.strip()).strip("_").upper()
    if not c or not re.match(r"^[A-Z_]", c):
        c = "_" + c
    return c


def main():
    bq = bigquery.Client(project=PROJECT)
    cn = sf_connect()
    try:
        for src, dest in TABLES.items():
            df = cn.cursor().execute(f"SELECT * FROM {src}").fetch_pandas_all()
            df.columns = [bq_colname(c) for c in df.columns]
            ref = f"{PROJECT}.{DATASET}.{dest}"
            cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
            print(f"loaded {len(df):>6} rows | {src}  ->  {ref}")
    finally:
        cn.close()
    print("done.")


if __name__ == "__main__":
    main()
