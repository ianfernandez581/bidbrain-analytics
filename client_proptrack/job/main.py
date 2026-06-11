"""PropTrack (Transmission) dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_STT/job/main.py): read the BigQuery
views in client_proptrack/sql/ and write a single proptrack.json to the private GCS
bucket. The gated web app (client_proptrack/dash) serves that JSON at /data.json.

The PropTrack story is "Banking ABM": an always-on LinkedIn presence plus a
concentrated May–Jun 2026 programmatic ABM burst on The Trade Desk. The payload pairs
the two paid sources the views already filtered + rolled up:
  * The Trade Desk (raw_snowflake.tradedesk_apac_all, ADVERTISER_NAME 'PopTrack') -> programmatic display+video
  * LinkedIn       (raw_snowflake.linkedin_ads_apac, ACCOUNT_NAME 'PropTrack_TransmissionSG_AUD') -> paid social

Single currency = AUD everywhere; there is NO FX conversion. This job is read-only on
BigQuery — it only SELECTs the views and writes JSON to GCS. The shared raw layer is
filled by snowflake_data_pull/; this job never touches Snowflake directly.
"""
import os
import json
import datetime
from decimal import Decimal

from google.cloud import bigquery, storage

# --- Project-wide constants (identical for every client) ----------------------
PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
# Dataset / bucket / output object all follow from it via the naming convention.
CLIENT = "proptrack"

DATASET = f"client_{CLIENT}"                    # client_proptrack
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-proptrack-dash
DATA_OBJECT = f"{CLIENT}.json"                  # proptrack.json


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

    kpi = rows(bq, "kpi")[0]
    monthly = rows(bq, "monthly")
    td_media_type = rows(bq, "td_media_type")
    td_segments = rows(bq, "td_segments")
    td_creative_sizes = rows(bq, "td_creative_sizes")
    td_daily = rows(bq, "td_daily")
    li_groups = rows(bq, "li_groups")
    li_creative = rows(bq, "li_creative")
    li_campaigns = rows(bq, "li_campaigns")
    # Campaign-grained ad delivery — the dashboard's Campaign filter sums the selected
    # campaigns out of these client-side, rescaling the combined ad-delivery figures
    # (the per-platform breakdowns above have no campaign grain, so they stay whole).
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_daily = rows(bq, "ad_campaign_daily")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "td_window": {"start": ymd(kpi["td_start"]), "end": ymd(kpi["td_end"])},
        "li_window": {"start": ymd(kpi["li_start"]), "end": ymd(kpi["li_end"])},
        "kpi": {
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_aud": num(kpi["ad_spend_aud"]),
            "ad_conv": num(kpi["ad_conv"]),
            "td_imps": num(kpi["td_imps"]),
            "td_clicks": num(kpi["td_clicks"]),
            "td_spend_aud": num(kpi["td_spend_aud"]),
            "td_conv": num(kpi["td_conv"]),
            "td_click_conv": num(kpi["td_click_conv"]),
            "td_vt_conv": num(kpi["td_vt_conv"]),
            "li_imps": num(kpi["li_imps"]),
            "li_clicks": num(kpi["li_clicks"]),
            "li_spend_aud": num(kpi["li_spend_aud"]),
            "li_eng": num(kpi["li_eng"]),
            "li_video_views": num(kpi["li_video_views"]),
            "li_leads": num(kpi["li_leads"]),
            "li_lead_opens": num(kpi["li_lead_opens"]),
        },
        "monthly": [{
            "month": r["month"],
            "td_imps": num(r["td_imps"]),
            "td_clicks": num(r["td_clicks"]),
            "td_spend_aud": num(r["td_spend_aud"]),
            "td_conv": num(r["td_conv"]),
            "li_imps": num(r["li_imps"]),
            "li_clicks": num(r["li_clicks"]),
            "li_spend_aud": num(r["li_spend_aud"]),
            "li_eng": num(r["li_eng"]),
            "li_video_views": num(r["li_video_views"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
            "ad_conv": num(r["ad_conv"]),
        } for r in monthly],
        "td_media_type": [{
            "media_type": r["media_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conv": num(r["conv"]),
        } for r in td_media_type],
        "td_segments": [{
            "segment": r["segment"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conv": num(r["conv"]),
        } for r in td_segments],
        "td_creative_sizes": [{
            "creative_size": r["creative_size"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in td_creative_sizes],
        "td_daily": [{
            "date": ymd(r["metric_date"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conv": num(r["conv"]),
        } for r in td_daily],
        "li_groups": [{
            "campaign_group": r["campaign_group"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "engagements": num(r["engagements"]),
            "video_views": num(r["video_views"]),
            "lead_form_opens": num(r["lead_form_opens"]),
        } for r in li_groups],
        "li_creative": [{
            "creative_type": r["creative_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "video_views": num(r["video_views"]),
            "engagements": num(r["engagements"]),
        } for r in li_creative],
        "li_campaigns": [{
            "campaign": r["campaign_name"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "engagements": num(r["engagements"]),
            "video_views": num(r["video_views"]),
            "leads": num(r["leads"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in li_campaigns],
        # --- Campaign filter: campaign-grained ad delivery (spend all AUD) --------
        "ad_campaigns": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
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
        } for r in ad_campaign_monthly],
        "ad_campaign_daily": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "date": ymd(r["day"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
        } for r in ad_campaign_daily],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['ad_campaigns'])} campaigns, {env['kpi']['ad_imps']:,} impressions, "
          f"A${env['kpi']['ad_spend_aud']:,.0f} ad spend")


if __name__ == "__main__":
    main()
