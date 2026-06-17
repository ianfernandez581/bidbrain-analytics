r"""
client_cloudflare/pull_static.py -- ONE-TIME pull of Cloudflare's STATIC Snowflake
inputs into clients/client_cloudflare/data/ as committed CSV snapshots.

WHY THIS EXISTS
---------------
Cloudflare was the only client that didn't follow the MongoDB pattern (replicate
the source TABLES to BigQuery, then model in BigQuery views). The dynamic platform
tables it needs are already mirrored into `raw_snowflake` by the shared
`ingest/snowflake_data_pull` unit:
    Salesforce_CS_APAC_ALL, TradeDesk_APAC ALL, LinkedIn Ads - APAC, Reddit Ads - APAC_ALL
What is NOT in that shared layer are three Cloudflare-specific STATIC tables that
live only in CLOUDFLARE_SANDBOX and rarely change. This script snapshots them to
`data/*.csv`. NOTE: `data/` is gitignored (`clients/*/data/`, repo-wide) -- TIERS is
sensitive client ABM data -- so the CSVs are NOT in the repo; the live seeds persist
as BigQuery `client_cloudflare.seed_*` tables. `seed_static.py` loads these CSVs into
those tables, and the `sql/` views model everything in BigQuery -- so the export job
no longer touches Snowflake at all. Re-run this on a fresh checkout (data/ absent) or
when a manual upload changes.

    CLOUDFLARE_SANDBOX.CS_REPORTING.REAL_TARGETS           -> data/real_targets.csv  (pacing targets)
    CLOUDFLARE_SANDBOX.CS_REPORTING.TIERS                  -> data/tiers.csv         (account -> tier mapping)
    CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINE_CF  -> data/line_cf.csv       (LINE JP manual upload)

This is a MANUAL, occasional script (not part of the scheduled job). Re-run it only
when one of those manual Snowflake uploads changes; then re-run seed_static.py +
the export job (FORCE_REBUILD=1).

Auth: Snowflake key from $SNOWFLAKE_KEY else Secret Manager (snowflake-bq-key) via
ADC -- the read-only BQ_SYNC_USER key, same as every job.

Run:  .\.venv\Scripts\python.exe clients\client_cloudflare\pull_static.py
"""
import os
import pandas as pd
import snowflake.connector
from cryptography.hazmat.primitives import serialization

PROJECT      = "bidbrain-analytics"
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Snowflake source query -> data/<file>.csv. LINE is column-subset on purpose: the
# source table has ~160 mostly-NULL e-commerce metric columns and the model only
# uses these six (see sql/04_stg_line.sql); the messy header "Video (100% watched)"
# is aliased to a BigQuery-safe name here.
PULLS = {
    "real_targets.csv": "SELECT * FROM CLOUDFLARE_SANDBOX.CS_REPORTING.REAL_TARGETS",
    "tiers.csv":        "SELECT * FROM CLOUDFLARE_SANDBOX.CS_REPORTING.TIERS",
    "line_cf.csv": (
        'SELECT DAY, AD_NAME, IMPRESSIONS, CLICKS, COST, VIDEO_STARTS, '
        '"Video (100% watched)" AS VIDEO_100_WATCHED '
        "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINE_CF"
    ),
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


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    cn = sf_connect()
    try:
        for fname, sql in PULLS.items():
            df = cn.cursor().execute(sql).fetch_pandas_all()
            df.columns = [c.upper() for c in df.columns]
            path = os.path.join(DATA_DIR, fname)
            df.to_csv(path, index=False)
            print(f"pulled {len(df):>6} rows x {len(df.columns):>2} cols  ->  {path}")
    finally:
        cn.close()
    print("done.")


if __name__ == "__main__":
    main()
