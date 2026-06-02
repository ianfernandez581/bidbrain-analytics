"""Cloudflare APAC dashboard export job (Cloud Run job).

Mirrors client_mongodb/job/main.py. The one difference in intent: Cloudflare's
data model already lives in Snowflake (CLOUDFLARE_SANDBOX.* views), so this job
pulls the already-modelled *final* views, lands them as BigQuery src_* tables
(a queryable per-client copy, uniform with every client folder), then reads the
thin BigQuery views in client_cloudflare/sql/ to assemble cloudflare.json.

    Snowflake final-model views
      -> BigQuery src_*            (landed here)
      -> BigQuery views (sql/)     (read here)
      -> cloudflare.json           (one combined payload)
      -> GCS (private)

The combined payload merges what Cloudflare today writes as two separate R2
files (paid_media.json + pacing.json) into a single object served at /data.json
by the gated Cloud Run service in client_cloudflare/dash.

BOOTSTRAP: on a fresh project the BigQuery views don't exist yet, and they read
FROM the src_* tables this job lands. So the first run lands src_* and then
*errors* on the view reads -- that's expected. Then run
`python client_cloudflare/create_views.py`, then re-run this job. (Same flow as
client_mongodb README section 10.)
"""
import os, json, datetime
import pandas as pd
from google.cloud import bigquery, storage
import snowflake.connector
from cryptography.hazmat.primitives import serialization

from decimal import Decimal as _Decimal
import datetime as _dt

def _json_default(o):
    if isinstance(o, _Decimal):
        return float(o)
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

# --- Project-wide constants (identical for every client) ----------------------
PROJECT      = "bidbrain-analytics"
LOC          = "australia-southeast1"
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

# --- The ONE line that differs per client -------------------------------------
# Copy this folder for a new client and change ONLY this. Dataset / bucket /
# output object all follow from it via the naming convention, so they can never
# drift or be pointed at the wrong client by a stale shell variable.
CLIENT = "cloudflare"

DATASET     = f"client_{CLIENT}"                    # client_cloudflare
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-cloudflare-dash
DATA_OBJECT = f"{CLIENT}.json"                      # cloudflare.json

# --- Snowflake source views ---------------------------------------------------
# Unlike the MongoDB job (which pulls raw tables and models in BigQuery), these
# are Cloudflare's *final* model views -- the same objects the existing Snowflake
# DAILY_* tasks COPY INTO R2. The seven APAC markets and the JSON shapes below
# match those tasks exactly, so the dashboard renders identical numbers.
SF_PAID = "CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING"
SF_CS   = "CLOUDFLARE_SANDBOX.CS_REPORTING"

PAID_SQL      = f"SELECT * FROM {SF_PAID}.V_PAID_ADS_FINAL_MODEL"
PACING_SQL    = f"SELECT * FROM {SF_CS}.V_PACING_FINAL_MODEL"
BENCH_CH_SQL  = f"SELECT CHANNEL, CTR, CPM, CPC FROM {SF_PAID}.V_BENCHMARKS_CHANNEL"
BENCH_MKT_SQL = f"SELECT MARKET, CTR, CPM, CPC FROM {SF_PAID}.V_BENCHMARKS_MARKET"
LI_WEEKLY_SQL = f"SELECT WEEK, PERIOD, WEEK_START, TARGET, CUM_TARGET FROM {SF_PAID}.V_LI_WEEKLY_TARGETS"

ALL_MARKETS = ["ANZ", "ASEAN", "SAARC", "RIG", "KR", "JP", "GCR"]


def _snowflake_key_bytes():
    """Snowflake private key (PEM) as bytes for cryptography.

    Cloud Run injects it as the SNOWFLAKE_KEY env var (--set-secrets), so in prod
    this just reads the env var. Locally, when that env var is absent, fall back
    to reading the secret from Secret Manager via ADC -- so `python main.py` runs
    with no env setup. Reading through the client library (not gcloud) returns the
    raw stored bytes, so no CRLF mangling.
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


def jval(v):
    """JSON-safe value: dates -> ISO strings, numpy scalars -> python, NaN -> None."""
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, float) and pd.isna(v):
        return None
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return v


def ymd(v):
    """Date as 'YYYY-MM-DD' (the dashboard slices these for axis labels)."""
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()[:10]
    s = str(v)
    return s[:10] if s else None


def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def land(bq, df, table):
    """Land a Snowflake pull as a BigQuery src_* table (schema inferred from the df)."""
    df.columns = [c.upper() for c in df.columns]
    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    ref = f"{PROJECT}.{DATASET}.{table}"
    bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
    print(f"landed {len(df)} rows -> {table}")


def main():
    bq = bigquery.Client(project=PROJECT)

    cn = sf_connect()
    try:
        paid   = cn.cursor().execute(PAID_SQL).fetch_pandas_all()
        pacing = cn.cursor().execute(PACING_SQL).fetch_pandas_all()
        bch    = cn.cursor().execute(BENCH_CH_SQL).fetch_pandas_all()
        bmkt   = cn.cursor().execute(BENCH_MKT_SQL).fetch_pandas_all()
        liw    = cn.cursor().execute(LI_WEEKLY_SQL).fetch_pandas_all()
    finally:
        cn.close()

    # Normalise column case and coerce the date columns the dashboard slices.
    for df in (paid, pacing, bch, bmkt, liw):
        df.columns = [c.upper() for c in df.columns]
    for c in ("DATE", "WEEK_START"):
        if c in paid.columns:
            paid[c] = pd.to_datetime(paid[c]).dt.date
    if "WEEK_START" in liw.columns:
        liw["WEEK_START"] = pd.to_datetime(liw["WEEK_START"]).dt.date
    if "DAY" in pacing.columns:
        pacing["DAY"] = pd.to_datetime(pacing["DAY"]).dt.date

    # Land the pulls as BigQuery src_* tables (queryable copy; the sql/ views read these).
    land(bq, paid,   "src_paid_media")
    land(bq, pacing, "src_pacing")
    land(bq, bch,    "src_benchmarks_channel")
    land(bq, bmkt,   "src_benchmarks_market")
    land(bq, liw,    "src_li_weekly")

    # Read the thin BigQuery views (client_cloudflare/sql) to assemble the payload.
    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    pm  = rows(bq, f"SELECT * FROM {t('paid_media_model')}")
    pac = rows(bq, f"SELECT * FROM {t('pacing_model')}")
    bc  = rows(bq, f"SELECT * FROM {t('benchmarks_channel')}")
    bm  = rows(bq, f"SELECT * FROM {t('benchmarks_market')}")
    lw  = rows(bq, f"SELECT * FROM {t('li_weekly_targets')} ORDER BY WEEK_START")

    # Window over the paid rows (min/max date + inclusive day count).
    pdates = sorted(d for d in (ymd(r.get("DATE")) for r in pm) if d)
    if pdates:
        d0 = datetime.date.fromisoformat(pdates[0])
        d1 = datetime.date.fromisoformat(pdates[-1])
        window = {"start": pdates[0], "end": pdates[-1], "days": (d1 - d0).days + 1}
    else:
        window = {"start": None, "end": None, "days": 0}

    paid_media = {
        "row_count": len(pm),
        "window": window,
        "all_markets": ALL_MARKETS,
        "rows": [{
            "channel":           r.get("CHANNEL"),
            "date":              ymd(r.get("DATE")),
            "week_start":        ymd(r.get("WEEK_START")),
            "market":            r.get("MARKET"),
            "imps":              jval(r.get("IMPS")),
            "clicks":            jval(r.get("CLICKS")),
            "spend_usd":         jval(r.get("SPEND_USD")),
            "leads":             jval(r.get("LEADS")),
            "form_opens":        jval(r.get("FORM_OPENS")),
            "link_clicks":       jval(r.get("LINK_CLICKS")),
            "action_clicks":     jval(r.get("ACTION_CLICKS")),
            "video_starts":      jval(r.get("VIDEO_STARTS")),
            "video_completions": jval(r.get("VIDEO_COMPLETIONS")),
            "spend_jpy":         jval(r.get("SPEND_JPY")),
            "fx_usd_jpy":        jval(r.get("FX_USD_JPY")),
        } for r in pm],
        "benchmarks":        {r["CHANNEL"]: {"ctr": jval(r["CTR"]), "cpm": jval(r["CPM"]), "cpc": jval(r["CPC"])} for r in bc},
        "benchmarks_market": {r["MARKET"]:  {"ctr": jval(r["CTR"]), "cpm": jval(r["CPM"]), "cpc": jval(r["CPC"])} for r in bm},
        "li_weekly": [{
            "week":       r.get("WEEK"),
            "period":     r.get("PERIOD"),
            "week_start": ymd(r.get("WEEK_START")),
            "target":     jval(r.get("TARGET")),
            "cum_target": jval(r.get("CUM_TARGET")),
        } for r in lw],
    }

    # Pacing: pass every V_PACING_FINAL_MODEL column straight through (dates -> ISO).
    pacing_payload = {
        "row_count": len(pac),
        "rows": [{k: jval(v) for k, v in r.items()} for r in pac],
    }

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paid_media": paid_media,
        "pacing": pacing_payload,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env, default=_json_default), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | paid {len(pm)} rows, pacing {len(pac)} rows")


if __name__ == "__main__":
    main()
