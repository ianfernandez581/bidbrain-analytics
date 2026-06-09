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

# Creative-grain delivery for the "Top & bottom performing creatives" tables.
# V_PAID_ADS_FINAL_MODEL collapses the creative dimension away, so we re-derive the
# same per-channel union (identical campaign filters + market CASE expressions) one
# level lower -- grouping by creative instead of date. Aggregated over the whole
# window (no date), so each row is one channel x market x creative. The dashboard
# normalizes MARKET (TTD L3 tokens -> 7 L1 buckets) and ranks client-side.
PAID_CREATIVES_SQL = f"""
WITH fx AS (SELECT 155.0::FLOAT AS USD_JPY_RATE),
linkedin AS (
  SELECT 'LinkedIn' AS channel,
    CASE
      WHEN CAMPAIGN_NAME ILIKE '%APAC-ANZ%'   THEN 'ANZ'
      WHEN CAMPAIGN_NAME ILIKE '%APAC-ASEAN%' THEN 'ASEAN'
      WHEN CAMPAIGN_NAME ILIKE '%APAC-IN%'    THEN 'SAARC'
      WHEN CAMPAIGN_NAME ILIKE '%APAC-TCN%'   THEN 'GCR'
      WHEN CAMPAIGN_NAME ILIKE '%_JP_%' OR CAMPAIGN_NAME ILIKE '%APAC-JP%' THEN 'JP'
      WHEN CAMPAIGN_NAME ILIKE '%_KR_%' OR CAMPAIGN_NAME ILIKE '%APAC-KR%' THEN 'KR'
      WHEN CAMPAIGN_NAME ILIKE '%RIG%'        THEN 'RIG'
      ELSE 'UNMAPPED' END AS market,
    COALESCE(NULLIF(TRIM(CREATIVE_NAME),''), NULLIF(TRIM(AD_TITLE),''), '(unnamed)') AS creative,
    SUM(IMPRESSIONS) AS imps, SUM(CLICKS) AS clicks, SUM(COSTS) AS spend_usd, SUM(LEADS) AS leads
  FROM {SF_PAID}.V_STG_LINKEDIN_CF
  WHERE STARTSWITH(CAMPAIGN_NAME, 'CLOUD_ACQ_')
  GROUP BY 1, 2, 3
),
tradedesk AS (
  SELECT 'TTD' AS channel, MARKET_L3 AS market,
    COALESCE(NULLIF(TRIM(CREATIVE_NAME),''), '(unnamed)') AS creative,
    SUM(IMPRESSIONS) AS imps, SUM(CLICKS) AS clicks, SUM(COSTS) AS spend_usd, 0 AS leads
  FROM {SF_PAID}.V_STG_TRADEDESK_CF
  WHERE MARKET_L3 IS NOT NULL AND MARKET_L3 <> ''
  GROUP BY 1, 2, 3
),
reddit AS (
  SELECT 'Reddit' AS channel,
    CASE
      WHEN CAMPAIGN_NAME ILIKE '%ANZ%'   THEN 'ANZ'
      WHEN CAMPAIGN_NAME ILIKE '%ASEAN%' THEN 'ASEAN'
      WHEN CAMPAIGN_NAME ILIKE '%SAARC%' OR CAMPAIGN_NAME ILIKE '%INDIA%' THEN 'SAARC'
      WHEN CAMPAIGN_NAME ILIKE '%GCR%'   THEN 'GCR'
      WHEN CAMPAIGN_NAME ILIKE '%JP%'    THEN 'JP'
      WHEN CAMPAIGN_NAME ILIKE '%KR%'    THEN 'KR'
      WHEN CAMPAIGN_NAME ILIKE '%RIG%'   THEN 'RIG'
      ELSE 'ANZ' END AS market,
    COALESCE(NULLIF(TRIM(AD_NAME),''), '(unnamed)') AS creative,
    SUM(IMPRESSIONS) AS imps, SUM(CLICKS) AS clicks, SUM(COSTS) AS spend_usd, 0 AS leads
  FROM {SF_PAID}.V_STG_REDDIT_CF
  GROUP BY 1, 2, 3
),
line_jp AS (
  SELECT 'LINE' AS channel, 'JP' AS market,
    COALESCE(NULLIF(TRIM(AD_NAME),''), '(unnamed)') AS creative,
    SUM(l.IMPRESSIONS) AS imps, SUM(l.CLICKS) AS clicks,
    ROUND(SUM(l.COST) / fx.USD_JPY_RATE, 2) AS spend_usd, 0 AS leads
  FROM {SF_PAID}.V_STG_LINE_CF l CROSS JOIN fx
  GROUP BY 1, 2, 3, fx.USD_JPY_RATE
)
SELECT channel, market, creative, imps, clicks, spend_usd, leads
FROM (SELECT * FROM linkedin UNION ALL SELECT * FROM tradedesk
      UNION ALL SELECT * FROM reddit UNION ALL SELECT * FROM line_jp)
WHERE imps > 0
"""

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
        creat  = cn.cursor().execute(PAID_CREATIVES_SQL).fetch_pandas_all()
    finally:
        cn.close()

    # Normalise column case and coerce the date columns the dashboard slices.
    for df in (paid, pacing, bch, bmkt, liw, creat):
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
    land(bq, creat,  "src_paid_creatives")

    # Read the thin BigQuery views (client_cloudflare/sql) to assemble the payload.
    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    pm  = rows(bq, f"SELECT * FROM {t('paid_media_model')}")
    pac = rows(bq, f"SELECT * FROM {t('pacing_model')}")
    bc  = rows(bq, f"SELECT * FROM {t('benchmarks_channel')}")
    bm  = rows(bq, f"SELECT * FROM {t('benchmarks_market')}")
    lw  = rows(bq, f"SELECT * FROM {t('li_weekly_targets')} ORDER BY WEEK_START")
    cre = rows(bq, f"SELECT * FROM {t('paid_creatives_model')}")

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
        "creatives": [{
            "channel":   r.get("CHANNEL"),
            "market":    r.get("MARKET"),
            "creative":  r.get("CREATIVE"),
            "imps":      jval(r.get("IMPS")),
            "clicks":    jval(r.get("CLICKS")),
            "spend_usd": jval(r.get("SPEND_USD")),
            "leads":     jval(r.get("LEADS")),
        } for r in cre],
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

    # --- Extra single-campaign LinkedIn dashboards from the SHARED raw layer.
    # raw_snowflake.linkedin_ads_apac is already in BigQuery (snowflake_data_pull),
    # so read it directly -- no Snowflake roundtrip. Columns stored UPPERCASE.
    # EDA-confirmed names: DAY (daily grain), IMPRESSIONS, CLICKS, COSTS (USD),
    # LEADS (FLOAT64), LEAD_FORM_OPENS (FLOAT64, null for these AWR-CONS groups).
    CAMPAIGN_GROUPS = {
        "peyc":        ("ANZ PEYC",    "CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-PEYC"),
        "cf1_india":   ("CF1 India",   "CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_CF1-Integrated"),
        "coles_hyper": ("Coles Hyper", "CLOUD_ACQ_2026-Q2_MDS_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_Hyper_COLES"),
    }
    groups_sql = ",".join(f"'{g}'" for _, g in CAMPAIGN_GROUPS.values())
    li_sql = f"""
      SELECT
        DAY                                       AS DATE,
        CAMPAIGN_GROUP_NAME,
        CAMPAIGN_NAME,
        SUM(IMPRESSIONS)                          AS IMPS,
        SUM(CLICKS)                               AS CLICKS,
        SUM(COSTS)                                AS SPEND,
        SUM(IFNULL(LEADS,0))                      AS LEADS,
        SUM(IFNULL(LEAD_FORM_OPENS,0))            AS FORM_OPENS
      FROM `{PROJECT}.raw_snowflake.linkedin_ads_apac`
      WHERE CAMPAIGN_GROUP_NAME IN ({groups_sql})
      GROUP BY DAY, CAMPAIGN_GROUP_NAME, CAMPAIGN_NAME
      ORDER BY DAY
    """
    li_rows = rows(bq, li_sql)
    campaigns = {}
    for key, (label, group) in CAMPAIGN_GROUPS.items():
        grp = [r for r in li_rows if r.get("CAMPAIGN_GROUP_NAME") == group]
        dmap = {}
        for r in grp:
            d = ymd(r.get("DATE"))
            if not d:
                continue
            o = dmap.setdefault(d, {"date": d, "imps": 0, "clicks": 0, "spend": 0.0, "leads": 0, "form_opens": 0})
            o["imps"]       += int(jval(r.get("IMPS")) or 0)
            o["clicks"]     += int(jval(r.get("CLICKS")) or 0)
            o["spend"]      += float(jval(r.get("SPEND")) or 0)
            o["leads"]      += int(jval(r.get("LEADS")) or 0)
            o["form_opens"] += int(jval(r.get("FORM_OPENS")) or 0)
        daily = [dmap[d] for d in sorted(dmap)]
        keys = ("imps", "clicks", "spend", "leads", "form_opens")
        tot = {k: sum(x[k] for x in daily) for k in keys} if daily else {k: 0 for k in keys}
        cmap = {}
        for r in grp:
            nm = r.get("CAMPAIGN_NAME") or "(unnamed)"
            o = cmap.setdefault(nm, {"campaign": nm, "imps": 0, "clicks": 0, "spend": 0.0, "leads": 0})
            o["imps"]   += int(jval(r.get("IMPS")) or 0)
            o["clicks"] += int(jval(r.get("CLICKS")) or 0)
            o["spend"]  += float(jval(r.get("SPEND")) or 0)
            o["leads"]  += int(jval(r.get("LEADS")) or 0)
        dts = [x["date"] for x in daily]
        window = ({"start": dts[0], "end": dts[-1],
                   "days": (datetime.date.fromisoformat(dts[-1]) - datetime.date.fromisoformat(dts[0])).days + 1}
                  if dts else {"start": None, "end": None, "days": 0})
        campaigns[key] = {
            "label": label, "campaign_group": group, "window": window,
            "totals": tot, "daily": daily,
            "by_campaign": sorted(cmap.values(), key=lambda x: x["spend"], reverse=True),
        }

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paid_media": paid_media,
        "pacing": pacing_payload,
        "campaigns": campaigns,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env, default=_json_default), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | paid {len(pm)} rows, pacing {len(pac)} rows, creatives {len(cre)} rows")
    print(f"  linkedin single-campaign rows: {len(li_rows)} total across {len(CAMPAIGN_GROUPS)} groups")
    for key, c in campaigns.items():
        t, w = c["totals"], c["window"]
        print(f"    {key:12s} {c['label']:12s} days={w['days']:>3} daily={len(c['daily']):>3} "
              f"campaigns={len(c['by_campaign']):>2} imps={t['imps']:>9} clicks={t['clicks']:>6} "
              f"spend=${t['spend']:>11.2f} leads={t['leads']:>4} form_opens={t['form_opens']:>4}")


if __name__ == "__main__":
    main()
