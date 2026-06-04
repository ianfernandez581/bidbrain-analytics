"""STT GDC APAC dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_mongodb/job/main.py): read the
BigQuery views in client_STT/sql/ and write a single stt.json to the private GCS
bucket. The gated web app (client_STT/dash) serves that JSON at /data.json.

The STT story is "what the ads did to website traffic", so the payload pairs
four sources the views already filtered + rolled up:
  * GA4   (raw_snowflake.google_analytics_apac_all, property 318963196) -> website sessions / users / channels
  * LinkedIn (raw_snowflake.linkedin_ads_apac) -> paid-social delivery (SGD; USD account rows @1.34)
  * DV360 (raw_snowflake.dv360_apac)        -> programmatic display delivery (SGD)
  * Google Ads (raw_snowflake.google_ads_apac) -> paid-search delivery (SGD; USD rows @1.34)

This job does NOT touch Snowflake directly — the shared raw layer is filled by
snowflake_data_pull/, and the client_STT views read their STT slice. (GA4 was
previously sourced from Windsor's perf_ga4; it now comes from Snowflake too —
see client_STT/sql/01_stg_ga4.sql.) So the refresh is just: (re)run the loader
if needed, then run this job.
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
CLIENT = "stt"

DATASET = f"client_{CLIENT}"                    # client_stt
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-stt-dash
DATA_OBJECT = f"{CLIENT}.json"                  # stt.json


def num(v):
    """JSON-safe number: NUMERIC/Decimal -> float, leave ints/None alone."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def iso(v):
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return str(v)


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
    weekly = rows(bq, "weekly")
    li_creative = rows(bq, "li_creative")
    li_campaigns = rows(bq, "li_campaigns")
    dv_markets = rows(bq, "dv_markets")
    google_markets = rows(bq, "google_markets")
    # Campaign-grained ad delivery — the dashboard's Campaign filter sums the
    # selected campaigns out of these client-side, rescaling every ad-delivery
    # figure (the GA4/website side has no campaign dimension, so it stays whole).
    # Mirrors how the market-grained GA4 arrays power the Country filter.
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")
    ad_campaign_market = rows(bq, "ad_campaign_market")
    li_campaign_creative = rows(bq, "li_campaign_creative")
    # Market-grained GA4 — the dashboard's Country filter sums the selected
    # markets out of these client-side. Replaces the old whole-campaign GA4
    # rollups (ga4_channels / ga4_markets / ga4_sources).
    ga4_kpi_market = rows(bq, "ga4_kpi_market")
    ga4_monthly_market = rows(bq, "ga4_monthly_market")
    ga4_weekly_market = rows(bq, "ga4_weekly_market")
    ga4_channels_market = rows(bq, "ga4_channels_market")
    ga4_sources_market = rows(bq, "ga4_sources_market")
    # Key events by type (all GA4 key events, not just the 3 stg_ga4 folds into
    # `conversions`) x month x market — powers the Website tab's key-events breakdown.
    ga4_key_events_market = rows(bq, "ga4_key_events_market")

    # Country options for the filter, ordered by total sessions desc (ga4_kpi_market
    # is already ordered that way). "Global" is excluded by default in the frontend.
    countries = [r["market"] for r in ga4_kpi_market]

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fx_usd_sgd": num(kpi["fx_usd_sgd"]),
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "li_window": {"start": ymd(kpi["li_start"]), "end": ymd(kpi["li_end"])},
        "dv_window": {"start": ymd(kpi["dv_start"]), "end": ymd(kpi["dv_end"])},
        "ga_window": {"start": ymd(kpi["ga_start"]), "end": ymd(kpi["ga_end"])},
        "kpi": {
            "sessions": num(kpi["sessions"]),
            "engaged_sessions": num(kpi["engaged_sessions"]),
            "users": num(kpi["users"]),
            "new_users": num(kpi["new_users"]),
            "page_views": num(kpi["page_views"]),
            "eng_duration": num(kpi["eng_duration"]),
            "conversions": num(kpi["conversions"]),
            "paid_sessions": num(kpi["paid_sessions"]),
            "display_sessions": num(kpi["display_sessions"]),
            "social_sessions": num(kpi["social_sessions"]),
            "prior_sessions": num(kpi["prior_sessions"]),
            "prior_paid_sessions": num(kpi["prior_paid_sessions"]),
            "li_imps": num(kpi["li_imps"]),
            "li_clicks": num(kpi["li_clicks"]),
            "li_cost_usd": num(kpi["li_cost_usd"]),
            "dv_imps": num(kpi["dv_imps"]),
            "dv_clicks": num(kpi["dv_clicks"]),
            "dv_spend_sgd": num(kpi["dv_spend_sgd"]),
            "ga_imps": num(kpi["ga_imps"]),
            "ga_clicks": num(kpi["ga_clicks"]),
            "ga_spend_sgd": num(kpi["ga_spend_sgd"]),
            "ga_conv": num(kpi["ga_conv"]),
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_sgd": num(kpi["ad_spend_sgd"]),
        },
        "monthly": [{
            "month": r["month"],
            "sessions": num(r["sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "organic_sessions": num(r["organic_sessions"]),
            "direct_sessions": num(r["direct_sessions"]),
            "other_sessions": num(r["other_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "engaged_sessions": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "conversions": num(r["conversions"]),
            "li_imps": num(r["li_imps"]),
            "li_clicks": num(r["li_clicks"]),
            "li_cost_usd": num(r["li_cost_usd"]),
            "dv_imps": num(r["dv_imps"]),
            "dv_clicks": num(r["dv_clicks"]),
            "dv_spend_sgd": num(r["dv_spend_sgd"]),
            "ga_imps": num(r["ga_imps"]),
            "ga_clicks": num(r["ga_clicks"]),
            "ga_spend_sgd": num(r["ga_spend_sgd"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_sgd": num(r["ad_spend_sgd"]),
        } for r in monthly],
        "countries": countries,
        "ga4_kpi_market": [{
            "market": r["market"],
            "sessions": num(r["sessions"]),
            "engaged_sessions": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "new_users": num(r["new_users"]),
            "page_views": num(r["page_views"]),
            "eng_duration": num(r["eng_duration"]),
            "conversions": num(r["conversions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]),
            "prior_sessions": num(r["prior_sessions"]),
            "prior_paid_sessions": num(r["prior_paid_sessions"]),
        } for r in ga4_kpi_market],
        "ga4_monthly_market": [{
            "month": r["month"],
            "market": r["market"],
            "sessions": num(r["sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "organic_sessions": num(r["organic_sessions"]),
            "direct_sessions": num(r["direct_sessions"]),
            "other_sessions": num(r["other_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]),
            "engaged_sessions": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "conversions": num(r["conversions"]),
        } for r in ga4_monthly_market],
        "ga4_weekly_market": [{
            "week_start": ymd(r["week_start"]),
            "market": r["market"],
            "ga4_sessions": num(r["ga4_sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]),
        } for r in ga4_weekly_market],
        "ga4_channels_market": [{
            "market": r["market"],
            "channel": r["channel_group"],
            "bucket": r["channel_bucket"],
            "sessions": num(r["sessions"]),
            "engaged": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "conversions": num(r["conversions"]),
        } for r in ga4_channels_market],
        "ga4_sources_market": [{
            "market": r["market"],
            "source_medium": r["source_medium"],
            "channel": r["channel"],
            "bucket": r["bucket"],
            "sessions": num(r["sessions"]),
            "engaged": num(r["engaged"]),
            "conversions": num(r["conversions"]),
        } for r in ga4_sources_market],
        "ga4_key_events_market": [{
            "month": r["month"],
            "market": r["market"],
            "event_name": r["event_name"],
            "key_events": num(r["key_events"]),
        } for r in ga4_key_events_market],
        "li_creative": [{
            "creative_type": r["creative_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "cost_usd": num(r["cost_usd"]),
            "video_views": num(r["video_views"]),
            "engagements": num(r["engagements"]),
        } for r in li_creative],
        "li_campaigns": [{
            "campaign": r["campaign_name"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "cost_usd": num(r["cost_usd"]),
            "video_views": num(r["video_views"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in li_campaigns],
        "dv_markets": [{
            "market": r["market"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_sgd": num(r["spend_sgd"]),
            "conversions": num(r["conversions"]),
        } for r in dv_markets],
        "google_markets": [{
            "market": r["market"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_sgd": num(r["spend_sgd"]),
            "conversions": num(r["conversions"]),
        } for r in google_markets],
        # --- Campaign filter: campaign-grained ad delivery (spend all SGD) --------
        "ad_campaigns": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_sgd": num(r["spend_sgd"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in ad_campaigns],
        "ad_campaign_monthly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "month": r["month"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_sgd": num(r["spend_sgd"]),
        } for r in ad_campaign_monthly],
        "ad_campaign_weekly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_sgd": num(r["spend_sgd"]),
        } for r in ad_campaign_weekly],
        "ad_campaign_market": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "market": r["market"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_sgd": num(r["spend_sgd"]),
        } for r in ad_campaign_market],
        "li_campaign_creative": [{
            "campaign": r["campaign"],
            "creative_type": r["creative_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "cost_usd": num(r["cost_usd"]),
            "video_views": num(r["video_views"]),
            "engagements": num(r["engagements"]),
        } for r in li_campaign_creative],
        "weekly": [{
            "week_start": ymd(r["week_start"]),
            "ga4_sessions": num(r["ga4_sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]),
            "li_imps": num(r["li_imps"]),
            "dv_imps": num(r["dv_imps"]),
            "ga_imps": num(r["ga_imps"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_sgd": num(r["ad_spend_sgd"]),
        } for r in weekly],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['weekly'])} weeks, {env['kpi']['sessions']:,} sessions, "
          f"S${env['kpi']['ad_spend_sgd']:,.0f} ad spend")


if __name__ == "__main__":
    main()
