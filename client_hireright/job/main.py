"""HireRight paid-media dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_STT/job/main.py): read the
BigQuery views in client_hireright/sql/ and write a single hireright.json to the
private GCS bucket. The gated web app (client_hireright/dash) serves that JSON at
/data.json.

This is a GENERIC paid-media DELIVERY baseline — "all of HireRight's paid media in
one place", reporting currency USD. There is NO GA4 / website side, and only three
platforms have data:
  * DV360     (raw_snowflake.dv360_apac)        -> programmatic display (USD; the only real geo)
  * TradeDesk (raw_snowflake.tradedesk_apac_all)-> programmatic air-cover (AUD -> USD @0.65)
  * LinkedIn  (raw_snowflake.linkedin_ads_apac) -> paid social air-cover (USD; _AUD acct -> @0.65)

This job does NOT touch Snowflake directly — the shared raw layer is filled by
snowflake_data_pull/, and the client_hireright views read their HireRight slice. So
the refresh is just: (re)run the loader if needed, then run this job.
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
CLIENT = "hireright"

DATASET = f"client_{CLIENT}"                    # client_hireright
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-hireright-dash
DATA_OBJECT = f"{CLIENT}.json"                  # hireright.json


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
    li_creative = rows(bq, "li_creative")
    li_campaigns = rows(bq, "li_campaigns")
    # Campaign-grained ad delivery — the dashboard's Campaign filter sums the
    # selected campaigns out of these client-side, rescaling every ad-delivery
    # figure. ad_campaign_market also powers the Market filter + by-market charts.
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")
    ad_campaign_market = rows(bq, "ad_campaign_market")
    li_campaign_creative = rows(bq, "li_campaign_creative")

    # Market options for the filter, ordered by total spend desc. DV360 carries real
    # countries; TradeDesk + LinkedIn are 'Global'. Default = all markets selected.
    mkt_spend = {}
    for r in ad_campaign_market:
        mkt_spend[r["market"]] = mkt_spend.get(r["market"], 0) + (num(r["spend_usd"]) or 0)
    markets = sorted(mkt_spend, key=lambda m: mkt_spend[m], reverse=True)

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fx_aud_usd": num(kpi["fx_aud_usd"]),
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "dv_window": {"start": ymd(kpi["dv_start"]), "end": ymd(kpi["dv_end"])},
        "td_window": {"start": ymd(kpi["td_start"]), "end": ymd(kpi["td_end"])},
        "li_window": {"start": ymd(kpi["li_start"]), "end": ymd(kpi["li_end"])},
        "kpi": {
            "dv_imps": num(kpi["dv_imps"]),
            "dv_clicks": num(kpi["dv_clicks"]),
            "dv_spend_usd": num(kpi["dv_spend_usd"]),
            "dv_conv": num(kpi["dv_conv"]),
            "td_imps": num(kpi["td_imps"]),
            "td_clicks": num(kpi["td_clicks"]),
            "td_spend_usd": num(kpi["td_spend_usd"]),
            "td_conv": num(kpi["td_conv"]),
            "li_imps": num(kpi["li_imps"]),
            "li_clicks": num(kpi["li_clicks"]),
            "li_cost_usd": num(kpi["li_cost_usd"]),
            "li_conv": num(kpi["li_conv"]),
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_usd": num(kpi["ad_spend_usd"]),
            "ad_conv": num(kpi["ad_conv"]),
        },
        "monthly": [{
            "month": r["month"],
            "dv_imps": num(r["dv_imps"]),
            "dv_clicks": num(r["dv_clicks"]),
            "dv_spend_usd": num(r["dv_spend_usd"]),
            "td_imps": num(r["td_imps"]),
            "td_clicks": num(r["td_clicks"]),
            "td_spend_usd": num(r["td_spend_usd"]),
            "li_imps": num(r["li_imps"]),
            "li_clicks": num(r["li_clicks"]),
            "li_cost_usd": num(r["li_cost_usd"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_usd": num(r["ad_spend_usd"]),
        } for r in monthly],
        "weekly": [{
            "week_start": ymd(r["week_start"]),
            "dv_imps": num(r["dv_imps"]),
            "td_imps": num(r["td_imps"]),
            "li_imps": num(r["li_imps"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_usd": num(r["ad_spend_usd"]),
        } for r in weekly],
        "markets": markets,
        "li_creative": [{
            "creative_type": r["creative_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "cost_usd": num(r["cost_usd"]),
            "video_views": num(r["video_views"]),
            "video_starts": num(r["video_starts"]),
            "video_completions": num(r["video_completions"]),
            "lead_form_opens": num(r["lead_form_opens"]),
            "leads": num(r["leads"]),
            "engagements": num(r["engagements"]),
        } for r in li_creative],
        "li_campaigns": [{
            "campaign": r["campaign_name"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "cost_usd": num(r["cost_usd"]),
            "video_views": num(r["video_views"]),
            "leads": num(r["leads"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in li_campaigns],
        # --- Campaign filter: campaign-grained ad delivery (spend all USD) --------
        "ad_campaigns": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_usd": num(r["spend_usd"]),
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
            "spend_usd": num(r["spend_usd"]),
        } for r in ad_campaign_monthly],
        "ad_campaign_weekly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_usd": num(r["spend_usd"]),
        } for r in ad_campaign_weekly],
        "ad_campaign_market": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "market": r["market"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_usd": num(r["spend_usd"]),
        } for r in ad_campaign_market],
        "li_campaign_creative": [{
            "campaign": r["campaign"],
            "creative_type": r["creative_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "cost_usd": num(r["cost_usd"]),
            "video_views": num(r["video_views"]),
            "video_starts": num(r["video_starts"]),
            "video_completions": num(r["video_completions"]),
            "lead_form_opens": num(r["lead_form_opens"]),
            "leads": num(r["leads"]),
            "engagements": num(r["engagements"]),
        } for r in li_campaign_creative],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['ad_campaigns'])} campaigns, {len(env['markets'])} markets, "
          f"US${env['kpi']['ad_spend_usd']:,.0f} ad spend")


if __name__ == "__main__":
    main()
