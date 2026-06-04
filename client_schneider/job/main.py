"""Schneider Electric (APAC) dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_STT/job/main.py): read the BigQuery
views in client_schneider/sql/ and write a single schneider.json to the private GCS
bucket. The gated web app (client_schneider/dash) serves that JSON at /data.json.

The Schneider story is multi-platform paid-media delivery (no website/GA4 layer yet),
read straight from the shared raw layer and modelled in BigQuery views:
  * DV360     (raw_snowflake.dv360_apac, ADVERTISER_NAME 'APAC | Schneider Electric%')
  * TradeDesk (raw_snowflake.tradedesk_apac_all, ADVERTISER_NAME = 'Schneider Electric')
  * LinkedIn  (raw_snowflake.linkedin_ads_apac, ACCOUNT_NAME 'SchneiderElectric_TransmissionSG%')

Reporting currency AUD (USD/SGD converted at fixed FX in the stg_* views). On top of the
delivery roll-ups it ships the SEED tables (campaign map / plan budget / flighting / targets /
channel split) as their own JSON branches — the dashboard joins delivery → internal campaign
via seed_campaign_map.match_pattern client-side.

GA4 (website) is SHIPPED DISABLED: GA4_ENABLED gates the ga4_* branches. The views exist (with
a property-id placeholder → 0 rows) but are NOT queried while disabled; the payload carries
ga4_enabled:false and the dashboard renders the "awaiting GA4 property id" stub.

This job does NOT touch Snowflake directly — the shared raw layer is filled by
snowflake_data_pull/. Read-only on BigQuery: it SELECTs views and writes JSON to GCS.
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
CLIENT = "schneider"

DATASET = f"client_{CLIENT}"                    # client_schneider
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-schneider-dash
DATA_OBJECT = f"{CLIENT}.json"                  # schneider.json

# GA4 (Website tab) ships DISABLED until the SE GA4 property id(s) are known. Flip to True
# AFTER setting the real PROPERTY_ID(s) in sql/40_stg_ga4.sql (+ 46_) and reapplying views.
GA4_ENABLED = False


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
    weekly = rows(bq, "weekly")
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")
    ad_campaign_market = rows(bq, "ad_campaign_market")
    ad_campaign_metrics = rows(bq, "ad_campaign_metrics")
    li_creative = rows(bq, "li_creative")
    li_campaign_creative = rows(bq, "li_campaign_creative")
    # Seeds (the human bridge + plan data) — joined to delivery client-side via match_pattern.
    seed_campaign_map = rows(bq, "seed_campaign_map")
    seed_plan_budget = rows(bq, "seed_plan_budget")
    seed_plan_flighting = rows(bq, "seed_plan_flighting")
    seed_targets = rows(bq, "seed_targets")
    seed_channel_split = rows(bq, "seed_channel_split")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "AUD",
        "fx_usd_aud": num(kpi["fx_usd_aud"]),
        "fx_sgd_aud": num(kpi["fx_sgd_aud"]),
        "ga4_enabled": GA4_ENABLED,
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "dv_window": {"start": ymd(kpi["dv_start"]), "end": ymd(kpi["dv_end"])},
        "td_window": {"start": ymd(kpi["td_start"]), "end": ymd(kpi["td_end"])},
        "li_window": {"start": ymd(kpi["li_start"]), "end": ymd(kpi["li_end"])},
        "kpi": {
            "dv_imps": num(kpi["dv_imps"]), "dv_clicks": num(kpi["dv_clicks"]),
            "dv_spend_aud": num(kpi["dv_spend_aud"]), "dv_conv": num(kpi["dv_conv"]),
            "dv_engagements": num(kpi["dv_engagements"]), "dv_viewable_imps": num(kpi["dv_viewable_imps"]),
            "td_imps": num(kpi["td_imps"]), "td_clicks": num(kpi["td_clicks"]),
            "td_spend_aud": num(kpi["td_spend_aud"]), "td_conv": num(kpi["td_conv"]),
            "li_imps": num(kpi["li_imps"]), "li_clicks": num(kpi["li_clicks"]),
            "li_spend_aud": num(kpi["li_spend_aud"]),
            "li_leads": num(kpi["li_leads"]), "li_lead_form_opens": num(kpi["li_lead_form_opens"]),
            "li_video_views": num(kpi["li_video_views"]), "li_video_starts": num(kpi["li_video_starts"]),
            "li_video_completions": num(kpi["li_video_completions"]), "li_engagements": num(kpi["li_engagements"]),
            "ad_imps": num(kpi["ad_imps"]), "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_aud": num(kpi["ad_spend_aud"]),
            "ad_conversions": num(kpi["ad_conversions"]), "ad_leads": num(kpi["ad_leads"]),
        },
        "monthly": [{
            "month": r["month"],
            "dv_imps": num(r["dv_imps"]), "dv_clicks": num(r["dv_clicks"]), "dv_spend_aud": num(r["dv_spend_aud"]),
            "td_imps": num(r["td_imps"]), "td_clicks": num(r["td_clicks"]), "td_spend_aud": num(r["td_spend_aud"]),
            "li_imps": num(r["li_imps"]), "li_clicks": num(r["li_clicks"]), "li_spend_aud": num(r["li_spend_aud"]),
            "ad_imps": num(r["ad_imps"]), "ad_clicks": num(r["ad_clicks"]), "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in monthly],
        "weekly": [{
            "week_start": ymd(r["week_start"]),
            "dv_imps": num(r["dv_imps"]), "dv_clicks": num(r["dv_clicks"]), "dv_spend_aud": num(r["dv_spend_aud"]),
            "td_imps": num(r["td_imps"]), "td_clicks": num(r["td_clicks"]), "td_spend_aud": num(r["td_spend_aud"]),
            "li_imps": num(r["li_imps"]), "li_clicks": num(r["li_clicks"]), "li_spend_aud": num(r["li_spend_aud"]),
            "ad_imps": num(r["ad_imps"]), "ad_clicks": num(r["ad_clicks"]), "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in weekly],
        # --- Campaign filter: campaign-grained ad delivery (spend all AUD) --------
        "ad_campaigns": [{
            "platform": r["platform"], "campaign": r["campaign"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
            "start": ymd(r["start_date"]), "end": ymd(r["end_date"]),
        } for r in ad_campaigns],
        "ad_campaign_monthly": [{
            "platform": r["platform"], "campaign": r["campaign"], "month": r["month"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in ad_campaign_monthly],
        "ad_campaign_weekly": [{
            "platform": r["platform"], "campaign": r["campaign"], "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in ad_campaign_weekly],
        "ad_campaign_market": [{
            "platform": r["platform"], "campaign": r["campaign"], "market": r["market"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in ad_campaign_market],
        "ad_campaign_metrics": [{
            "platform": r["platform"], "campaign": r["campaign"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "video_starts": num(r["video_starts"]), "video_completions": num(r["video_completions"]),
            "video_views": num(r["video_views"]),
            "leads": num(r["leads"]), "lead_form_opens": num(r["lead_form_opens"]),
            "engagements": num(r["engagements"]), "viewable_imps": num(r["viewable_imps"]),
        } for r in ad_campaign_metrics],
        "li_creative": [{
            "creative_type": r["creative_type"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "cost_aud": num(r["cost_aud"]),
            "video_views": num(r["video_views"]), "video_starts": num(r["video_starts"]),
            "video_completions": num(r["video_completions"]), "engagements": num(r["engagements"]),
        } for r in li_creative],
        "li_campaign_creative": [{
            "campaign": r["campaign"], "creative_type": r["creative_type"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "cost_aud": num(r["cost_aud"]),
            "video_views": num(r["video_views"]), "video_starts": num(r["video_starts"]),
            "video_completions": num(r["video_completions"]), "engagements": num(r["engagements"]),
        } for r in li_campaign_creative],
        # --- Seeds (plan side): the dashboard joins these to delivery client-side ---
        "seed_campaign_map": [{
            "id": r["internal_campaign_id"], "display": r["display_name"],
            "brief_job_no": r["brief_job_no"], "objective_type": r["objective_type"],
            "primary_kpi": r["primary_kpi"], "pillar": r["pillar"],
            "primary_region": r["primary_region"], "match_pattern": r["match_pattern"],
        } for r in seed_campaign_map],
        "seed_plan_budget": [{
            "id": r["internal_campaign_id"], "budget_aud": num(r["budget_aud"]),
            "budget_basis": r["budget_basis"],
            "flight_start": ymd(r["flight_start"]), "flight_end": ymd(r["flight_end"]),
        } for r in seed_plan_budget],
        "seed_plan_flighting": [{
            "id": r["internal_campaign_id"], "period": r["period"], "weight_pct": num(r["weight_pct"]),
        } for r in seed_plan_flighting],
        "seed_targets": [{
            "id": r["internal_campaign_id"], "kpi": r["kpi"], "target_value": num(r["target_value"]),
        } for r in seed_targets],
        "seed_channel_split": [{
            "id": r["internal_campaign_id"], "stage": r["stage"],
            "channel": r["channel"], "budget_aud": num(r["budget_aud"]),
        } for r in seed_channel_split],
    }

    # --- GA4 (Website) branches — only when enabled (else empty + ga4_enabled:false) ---
    if GA4_ENABLED:
        ga4_kpi_market = rows(bq, "ga4_kpi_market")
        ga4_monthly_market = rows(bq, "ga4_monthly_market")
        ga4_weekly_market = rows(bq, "ga4_weekly_market")
        ga4_channels_market = rows(bq, "ga4_channels_market")
        ga4_sources_market = rows(bq, "ga4_sources_market")
        ga4_key_events_market = rows(bq, "ga4_key_events_market")
        env["countries"] = [r["market"] for r in ga4_kpi_market]
        env["ga4_kpi_market"] = [{
            "market": r["market"], "sessions": num(r["sessions"]),
            "engaged_sessions": num(r["engaged_sessions"]), "users": num(r["users"]),
            "new_users": num(r["new_users"]), "page_views": num(r["page_views"]),
            "eng_duration": num(r["eng_duration"]), "conversions": num(r["conversions"]),
            "paid_sessions": num(r["paid_sessions"]), "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]), "search_sessions": num(r["search_sessions"]),
            "prior_sessions": num(r["prior_sessions"]), "prior_paid_sessions": num(r["prior_paid_sessions"]),
        } for r in ga4_kpi_market]
        env["ga4_monthly_market"] = [{
            "month": r["month"], "market": r["market"], "sessions": num(r["sessions"]),
            "paid_sessions": num(r["paid_sessions"]), "organic_sessions": num(r["organic_sessions"]),
            "direct_sessions": num(r["direct_sessions"]), "other_sessions": num(r["other_sessions"]),
            "display_sessions": num(r["display_sessions"]), "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]), "engaged_sessions": num(r["engaged_sessions"]),
            "users": num(r["users"]), "conversions": num(r["conversions"]),
        } for r in ga4_monthly_market]
        env["ga4_weekly_market"] = [{
            "week_start": ymd(r["week_start"]), "market": r["market"],
            "ga4_sessions": num(r["ga4_sessions"]), "paid_sessions": num(r["paid_sessions"]),
            "display_sessions": num(r["display_sessions"]), "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]),
        } for r in ga4_weekly_market]
        env["ga4_channels_market"] = [{
            "market": r["market"], "channel": r["channel_group"], "bucket": r["channel_bucket"],
            "sessions": num(r["sessions"]), "engaged": num(r["engaged_sessions"]),
            "users": num(r["users"]), "conversions": num(r["conversions"]),
        } for r in ga4_channels_market]
        env["ga4_sources_market"] = [{
            "market": r["market"], "source_medium": r["source_medium"],
            "channel": r["channel"], "bucket": r["bucket"], "sessions": num(r["sessions"]),
            "engaged": num(r["engaged"]), "conversions": num(r["conversions"]),
        } for r in ga4_sources_market]
        env["ga4_key_events_market"] = [{
            "month": r["month"], "market": r["market"],
            "event_name": r["event_name"], "key_events": num(r["key_events"]),
        } for r in ga4_key_events_market]
    else:
        env["countries"] = []
        for k in ("ga4_kpi_market", "ga4_monthly_market", "ga4_weekly_market",
                  "ga4_channels_market", "ga4_sources_market", "ga4_key_events_market"):
            env[k] = []

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['ad_campaigns'])} campaigns, "
          f"A${env['kpi']['ad_spend_aud']:,.0f} ad spend, GA4={'on' if GA4_ENABLED else 'off'}")


if __name__ == "__main__":
    main()
