import os, json, datetime
import pandas as pd
from google.cloud import bigquery, storage
import snowflake.connector
from cryptography.hazmat.primitives import serialization

# --- Project-wide constants ---------------------------------------------------
# One GCP project, one Snowflake account -> these are identical for EVERY client,
# so they're hardcoded here (same pattern as the Windsor loaders, which each
# hardcode their own PROJECT_ID / dataset / bucket rather than sharing a module).
# A shared module can't be imported here anyway: the Dockerfile copies only
# main.py, so anything outside this folder isn't in the container.
PROJECT      = "bidbrain-analytics"
LOC          = "australia-southeast1"
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

# --- The ONE line that differs per client -------------------------------------
# Copy this folder for a new client and change ONLY this (e.g. "acme").
# Dataset / bucket / output object all follow from it via the naming convention
# (README section 9), so they can never drift or be pointed at the wrong client
# by a stale shell variable.
CLIENT = "mongodb"

DATASET     = f"client_{CLIENT}"                    # client_mongodb
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-mongodb-dash
DATA_OBJECT = f"{CLIENT}.json"                      # mongodb.json

TD_SQL = """
SELECT DAY, CAMPAIGN_NAME, AD_GROUP_NAME,
       AD_TYPE AS CREATIVE_FORMAT, PARTNER_NAME AS PUBLISHER,
       COALESCE(IMPRESSIONS, IMPRESSION) AS IMPRESSIONS,
       COSTS, CLICKS, TOTAL_CLICK_PLUS_VIEW_CONVERSIONS AS CONVERSIONS
FROM APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"
WHERE ADVERTISER_NAME = 'MongoDB'
"""

# Salesforce content-syndication leads, by campaign:
#   DNB IDE programmes -> 701RG00001DtQczYAF, 701RG00001HcDIVYA3, 701RG00001GvvrDYAR
#   KGA / IDC programme -> 701RG00001NKKwQYAX  (added once Ankit made IDC data live in Snowflake)
# NOTE: the BigQuery `stg_salesforce` view must map 701RG00001NKKwQYAX -> programme 'IDC'
# so these leads roll up under IDC (not IDE) in cs_leads / cs_leads_by_programme.
# LEAD_STATUS != 'New' excludes not-yet-actioned leads at the source, so they drop
# out of every downstream bucket (total / new_pending / rollups) automatically.
SF_SQL = """
SELECT DAY, COUNTRY_NAME, CAMPAIGN_ID, LEAD_STATUS
FROM APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"
WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3','701RG00001GvvrDYAR',
                      '701RG00001NKKwQYAX')
  AND LEAD_STATUS != 'New'
"""

def _snowflake_key_bytes():
    """Snowflake private key (PEM) as bytes for cryptography.

    Cloud Run injects it as the SNOWFLAKE_KEY env var (--set-secrets), so in prod
    this just reads the env var -- byte-identical to before. Locally, when that
    env var is absent, fall back to reading the secret from Secret Manager via
    ADC -- the same pattern the Windsor loaders use -- so `python main.py` runs
    with no env setup. Reading through the client library (not gcloud) returns
    the raw stored bytes, so the CRLF mangling that run-export-job.ps1 guards
    against (a gcloud-on-Windows / PowerShell-pipeline artefact) doesn't occur.
    """
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

def iso(v):
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return str(v)

def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]

def load(bq, df, table, schema):
    df.columns = [c.upper() for c in df.columns]
    cfg = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
    ref = f"{PROJECT}.{DATASET}.{table}"
    bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
    print(f"loaded {len(df)} rows -> {table}")

def main():
    bq = bigquery.Client(project=PROJECT)

    cn = sf_connect()
    try:
        td = cn.cursor().execute(TD_SQL).fetch_pandas_all()
        sf = cn.cursor().execute(SF_SQL).fetch_pandas_all()
    finally:
        cn.close()

    td.columns = [c.upper() for c in td.columns]
    sf.columns = [c.upper() for c in sf.columns]
    td["DAY"] = pd.to_datetime(td["DAY"]).dt.date
    sf["DAY"] = pd.to_datetime(sf["DAY"]).dt.date
    for c in ["IMPRESSIONS","CLICKS"]:
        td[c] = pd.to_numeric(td[c], errors="coerce").astype("Int64")
    for c in ["COSTS","CONVERSIONS"]:
        td[c] = pd.to_numeric(td[c], errors="coerce").astype(float)

    load(bq, td, "src_tradedesk", [
        bigquery.SchemaField("DAY","DATE"),
        bigquery.SchemaField("CAMPAIGN_NAME","STRING"),
        bigquery.SchemaField("AD_GROUP_NAME","STRING"),
        bigquery.SchemaField("CREATIVE_FORMAT","STRING"),
        bigquery.SchemaField("PUBLISHER","STRING"),
        bigquery.SchemaField("IMPRESSIONS","INT64"),
        bigquery.SchemaField("COSTS","FLOAT64"),
        bigquery.SchemaField("CLICKS","INT64"),
        bigquery.SchemaField("CONVERSIONS","FLOAT64")])
    load(bq, sf, "src_salesforce", [
        bigquery.SchemaField("DAY","DATE"),
        bigquery.SchemaField("COUNTRY_NAME","STRING"),
        bigquery.SchemaField("CAMPAIGN_ID","STRING"),
        bigquery.SchemaField("LEAD_STATUS","STRING")])

    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    pm  = rows(bq, f"SELECT * FROM {t('paid_media_model')}")
    win = rows(bq, f"SELECT MIN(d.DATE) AS s, MAX(d.DATE) AS e, "
                   f"DATE_DIFF(MAX(d.DATE),MIN(d.DATE),DAY)+1 AS days FROM {t('paid_media_model')} d")[0]
    tgt = rows(bq, f"SELECT * FROM {t('targets')}")
    bs  = rows(bq, f"SELECT * FROM {t('benchmarks_strategy')}")
    bm  = rows(bq, f"SELECT * FROM {t('benchmarks_market')}")
    bud = rows(bq, f"SELECT * FROM {t('budget')}")
    cso = rows(bq, f"SELECT * FROM {t('cs_leads')}")
    csp = rows(bq, f"SELECT * FROM {t('cs_leads_by_programme')}")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_count": len(pm),
        "window": {"start": iso(win["s"]), "end": iso(win["e"]), "days": win["days"]},
        "all_markets": ["ANZ","ASEAN","INDIA","KR-HK-TW"],
        "all_programmes": ["IDE","IDC"],
        "rows": [{"channel": r["CHANNEL"], "date": iso(r["DATE"]), "week_start": iso(r["WEEK_START"]),
                  "programme": r["PROGRAMME"], "market": r["MARKET"], "strategy": r["STRATEGY"],
                  "objective": r["OBJECTIVE"], "imps": r["IMPS"], "clicks": r["CLICKS"],
                  "spend_usd": r["SPEND_USD"], "conversions": r["CONVERSIONS"], "leads": r["LEADS"]} for r in pm],
        "targets": [{"programme": r["PROGRAMME_LABEL"], "market": r["MARKET"],
                     "target": r["TARGET_LEADS"], "delivered": r["DELIVERED_LEADS_SNAPSHOT"]} for r in tgt],
        "benchmarks_strategy": {r["STRATEGY"]: {"cpm": r["CPM"], "ctr": r["CTR"],
                     "frequency": r["FREQUENCY_CAP"], "weight": r["BUDGET_WEIGHT"]} for r in bs},
        "benchmarks_market": {r["MARKET"]: {"budget_weight": r["BUDGET_WEIGHT"]} for r in bm},
        "budget": [{"programme": r["PROGRAMME_LABEL"], "tradedesk_code": r["TRADEDESK_CODE"],
                    "gross_usd": r["GROSS_BUDGET_USD"], "net_usd": r["NET_BUDGET_USD"],
                    "start": iso(r["START_DATE"]), "end": iso(r["END_DATE"])} for r in bud],
        "cs": [{"market": r["MARKET"], "total": r["TOTAL_LEADS"], "accepted": r["ACCEPTED"],
                "rejected": r["REJECTED"], "new_pending": r["NEW_PENDING"], "unresponsive": r["UNRESPONSIVE"],
                "do_not_contact": r["DO_NOT_CONTACT"], "last_lead_day": iso(r["LAST_LEAD_DAY"])} for r in cso],
        "cs_by_programme": [{"programme": r["PROGRAMME_LABEL"], "market": r["MARKET"], "total": r["TOTAL_LEADS"],
                "accepted": r["ACCEPTED"], "new_pending": r["NEW_PENDING"], "unresponsive": r["UNRESPONSIVE"],
                "do_not_contact": r["DO_NOT_CONTACT"], "last_lead_day": iso(r["LAST_LEAD_DAY"])} for r in csp],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['rows'])} rows, "
          f"{sum(c['total'] for c in env['cs'])} leads")

if __name__ == "__main__":
    main()