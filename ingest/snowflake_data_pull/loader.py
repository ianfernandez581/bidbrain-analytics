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
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
import snowflake.connector
from cryptography.hazmat.primitives import serialization

# pandas is NOT imported at module top: fetch_pandas_all() pulls it in only on the
# reload path, so a tick where nothing changed stays a light, fast container.
from freshness import probe_snowflake_last_altered, _to_utc, _iso

PROJECT      = "bidbrain-analytics"
LOC          = "australia-southeast1"
RAW_DATASET  = "raw_snowflake"
SYNC_TABLE   = "_sync_state"   # per-table freshness watermark (table_name, last_altered)
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

# Snowflake source table (fully qualified)  ->  BigQuery table name in raw_snowflake.
# Whole table, every client. Add a line to mirror another source table.
# These are the SHARED APAC ad-platform tables (one per channel); each client
# filters its own slice in its views (e.g. ACCOUNT_NAME / ADVERTISER_NAME).
TABLES = {
    'APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"': "salesforce_cs_apac_all",
    'APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"':      "tradedesk_apac_all",
    'APAC_ALL_PLATFORM.PUBLIC."LinkedIn Ads - APAC"':     "linkedin_ads_apac",
    'APAC_ALL_PLATFORM.PUBLIC."Reddit Ads - APAC_ALL"':   "reddit_ads_apac_all",
    'APAC_ALL_PLATFORM.PUBLIC."DV360 - APAC"':            "dv360_apac",
    'APAC_ALL_PLATFORM.PUBLIC."Google Ads - APAC"':       "google_ads_apac",
    'APAC_ALL_PLATFORM.PUBLIC."Google Analytics Data_APAC ALL"': "google_analytics_apac_all",
    # Per-fire Trade Desk Universal Pixel conversions (one row per pixel fire) —
    # the per-pixel/per-campaign breakdown the blended tradedesk_apac_all drops.
    # MongoDB's content-engagement section reads its slice (ADVERTISER_ID='9c1w83i').
    'APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL-Conversion"': "tradedesk_apac_conversion",
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


def _bare(fqn):
    """'APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"' -> 'Salesforce_CS_APAC_ALL'."""
    return fqn.split('"')[1]


def read_sync_state(bq):
    """Read the per-table watermark from BQ -> {table_name: LAST_ALTERED (UTC)}.
    Missing table (cold start) -> {}."""
    ref = f"{PROJECT}.{RAW_DATASET}.{SYNC_TABLE}"
    try:
        it = bq.query(f"SELECT table_name, last_altered FROM `{ref}`", location=LOC).result()
        return {r["table_name"]: _to_utc(r["last_altered"]) for r in it}
    except NotFound:
        return {}


def write_sync_state(bq, watermark):
    """Persist {table_name: LAST_ALTERED} to the BQ _sync_state table (WRITE_TRUNCATE,
    no pandas needed). Stored as ISO-UTC strings into a TIMESTAMP column."""
    ref = f"{PROJECT}.{RAW_DATASET}.{SYNC_TABLE}"
    rows = [{"table_name": k, "last_altered": _iso(v)} for k, v in sorted(watermark.items()) if v]
    schema = [bigquery.SchemaField("table_name", "STRING"),
              bigquery.SchemaField("last_altered", "TIMESTAMP")]
    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema)
    bq.load_table_from_json(rows, ref, job_config=cfg, location=LOC).result()


def main():
    bq = bigquery.Client(project=PROJECT)
    cn = sf_connect()
    # PER-TABLE freshness gate: mirror a source table only if its Snowflake
    # LAST_ALTERED advanced past our stored watermark. The probe is metadata-only
    # (no warehouse credits); only the actual SELECT * resumes the warehouse, and
    # only for tables that truly changed. FORCE_REBUILD=1 mirrors everything.
    force = os.environ.get("FORCE_REBUILD") == "1"
    try:
        observed = probe_snowflake_last_altered(cn, [_bare(s) for s in TABLES])
        wm = read_sync_state(bq)
        new_wm = dict(wm)
        refreshed, skipped = [], []
        for src, dest in TABLES.items():
            name = _bare(src)
            obs, prev = observed.get(name), wm.get(name)
            if not force and obs is not None and prev is not None and obs <= prev:
                skipped.append(name)
                print(f"skip (unchanged {_iso(obs)}) | {name}")
                continue
            df = cn.cursor().execute(f"SELECT * FROM {src}").fetch_pandas_all()
            df.columns = [c.upper() for c in df.columns]
            ref = f"{PROJECT}.{RAW_DATASET}.{dest}"
            cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
            print(f"loaded {len(df):>7} rows | {src}  ->  {ref}")
            if obs is not None:
                new_wm[name] = obs   # advance watermark only after a successful load
            refreshed.append(name)
    finally:
        cn.close()
    # Persist the watermark only if something actually refreshed (a fully no-op tick
    # touches nothing -- no warehouse, no BQ write).
    if refreshed:
        write_sync_state(bq, new_wm)
    print(f"done. refreshed {len(refreshed)}/{len(TABLES)} "
          f"(skipped {len(skipped)} unchanged): {refreshed or '(none)'}")


if __name__ == "__main__":
    main()
