"""TLM e-commerce dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_resetdata/job/main.py): read the BigQuery
views in client_tlm/sql/ and write a single tlm.json to the private GCS bucket. The
gated web app (client_tlm/dash) serves that JSON at /data.json.

TLM is an Australian specialty-coffee e-commerce retailer. The story is "ads → revenue /
ROAS" (Google Ads conversions_value = revenue AUD), with Trade Desk contributing delivery
metrics but no attributable revenue (pixel fires are anonymous). Two sources across TWO
shared raw layers:
  * Google Ads (raw_google_ads.perf_google_ads)   -> paid-search + shopping + PMax delivery (AUD; native DTS)
  * Trade Desk (raw_windsor.perf_the_trade_desk)  -> programmatic display delivery (AUD; Windsor already AUD)

This job is READ-ONLY on BigQuery — it only SELECTs the views and writes JSON to GCS.
Currency is AUD throughout (Google spend is already AUD — NOT micros; TTD Windsor is
already AUD). FX_USD_AUD=1.50 is documented but the CASE in stg_ttd passes AUD through
unchanged (TTD currency = 'AUD' per EDA).
"""
import os
import json
import datetime
from decimal import Decimal

from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when an
# upstream raw table this job reads has advanced. GATING_TABLES are "dataset.table"
# ids in this project, probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
GATING_TABLES = [
    "raw_google_ads.perf_google_ads",
    "raw_windsor.perf_the_trade_desk",
]
WATERMARK_OBJECT = "_freshness.json"

# --- Project-wide constants (identical for every client) ----------------------
PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
# Dataset / bucket / output object all follow from it via the naming convention.
CLIENT = "tlm"

DATASET = f"client_{CLIENT}"                    # client_tlm
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-tlm-dash
DATA_OBJECT = f"{CLIENT}.json"                  # tlm.json


def num(v):
    """JSON-safe number: NUMERIC/Decimal -> float, leave ints/None alone."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def ymd(v):
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()[:10]
    return str(v)[:10]


def rows(bq, name):
    sql = f"SELECT * FROM `{PROJECT}.{DATASET}.{name}`"
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def main():
    bq = bigquery.Client(project=PROJECT)

    # --- Freshness gate: cheap metadata probe; skip the rebuild unless an upstream
    # raw table advanced. Reading __TABLES__.last_modified is metadata-only.
    observed = probe_bq_last_modified(bq, GATING_TABLES)
    wm = read_watermark(BUCKET, WATERMARK_OBJECT)
    times = ", ".join(f"{k}={observed[k].strftime('%Y-%m-%dT%H:%M:%SZ')}"
                      for k in sorted(observed)) or "(no tables found)"
    if os.environ.get("FORCE_REBUILD") == "1":
        print(f"FORCE_REBUILD=1 -> rebuilding regardless of freshness | {times}")
    elif not is_stale(observed, wm):
        print(f"no change, skipping rebuild | {times}")
        return
    else:
        print(f"upstream advanced -> rebuilding | {times}")

    kpi = rows(bq, "kpi")[0]
    monthly = rows(bq, "monthly")
    weekly = rows(bq, "weekly")
    google_campaigns = rows(bq, "google_campaigns")
    google_by_type = rows(bq, "google_by_type")
    ttd_campaigns = rows(bq, "ttd_campaigns")
    ttd_creative = rows(bq, "ttd_creative")
    # Campaign-grained ad delivery — the dashboard's Campaign filter sums the selected
    # campaigns out of these client-side, rescaling every ad-delivery figure.
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max([v for v in observed.values() if v])
                         .strftime("%Y-%m-%dT%H:%M:%SZ") if observed else None),
        "fx_usd_aud": num(kpi["fx_usd_aud"]),
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "kpi": {
            "spend_aud": num(kpi["ad_spend_aud"]),
            "imps": num(kpi["ad_imps"]),
            "clicks": num(kpi["ad_clicks"]),
            "conversions": num(kpi["conversions"]),
            "revenue": num(kpi["revenue"]),
            "g_imps": num(kpi["g_imps"]),
            "g_clicks": num(kpi["g_clicks"]),
            "g_spend_aud": num(kpi["g_spend_aud"]),
            "g_conv": num(kpi["g_conv"]),
            "g_revenue": num(kpi["g_revenue"]),
            "t_imps": num(kpi["t_imps"]),
            "t_clicks": num(kpi["t_clicks"]),
            "t_spend_aud": num(kpi["t_spend_aud"]),
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_aud": num(kpi["ad_spend_aud"]),
        },
        "monthly": [{
            "month": r["month"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "revenue": num(r["revenue"]),
            "g_imps": num(r["g_imps"]),
            "g_clicks": num(r["g_clicks"]),
            "g_spend_aud": num(r["g_spend_aud"]),
            "g_conv": num(r["g_conv"]),
            "g_revenue": num(r["g_revenue"]),
            "t_imps": num(r["t_imps"]),
            "t_clicks": num(r["t_clicks"]),
            "t_spend_aud": num(r["t_spend_aud"]),
        } for r in monthly],
        "weekly": [{
            "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "revenue": num(r["revenue"]),
            "g_imps": num(r["g_imps"]),
            "g_clicks": num(r["g_clicks"]),
            "g_spend_aud": num(r["g_spend_aud"]),
            "g_conv": num(r["g_conv"]),
            "g_revenue": num(r["g_revenue"]),
            "t_imps": num(r["t_imps"]),
            "t_clicks": num(r["t_clicks"]),
            "t_spend_aud": num(r["t_spend_aud"]),
        } for r in weekly],
        "google_campaigns": [{
            "campaign": r["campaign"],
            "campaign_type": r.get("campaign_type"),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "revenue": num(r["revenue"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in google_campaigns],
        "google_by_type": [{
            "campaign_type": r["campaign_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "revenue": num(r["revenue"]),
        } for r in google_by_type],
        "ttd_campaigns": [{
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in ttd_campaigns],
        "ttd_creative": [{
            "creative": r["creative_name"],
            "ad_format": r["ad_format"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "video_starts": num(r["video_starts"]),
            "video_completes": num(r["video_completes"]),
        } for r in ttd_creative],
        # --- Campaign filter: campaign-grained ad delivery (spend all AUD) --------
        "ad_campaigns": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "revenue": num(r["revenue"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in ad_campaigns],
        "ad_campaign_monthly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "month": r["month"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "revenue": num(r["revenue"]),
        } for r in ad_campaign_monthly],
        "ad_campaign_weekly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),  # Google-only (TTD NULL)
            "revenue": num(r["revenue"]),          # Google-only (TTD NULL)
        } for r in ad_campaign_weekly],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    # Record the watermark only after a successful upload (upload first, watermark
    # second), so a failed upload simply retries on the next tick.
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['weekly'])} weeks, "
          f"A${env['kpi']['ad_spend_aud']:,.0f} ad spend, "
          f"{env['kpi']['conversions']:,.0f} purchases, "
          f"A${env['kpi']['revenue']:,.0f} revenue")


if __name__ == "__main__":
    main()