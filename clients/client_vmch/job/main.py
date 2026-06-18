"""VMCH dashboard export job (Cloud Run job).

Stage 2 of the standard pattern: read the BigQuery views in client_vmch/sql/
and write a single vmch.json to the private GCS bucket. The gated web app
(client_vmch/dash) serves that JSON at /data.json.

The VMCH story is "The Trade Desk programmatic display -> VMCH website traffic (GA4)",
so the payload pairs:
  * GA4   (raw_ga4.perf_ga4) -> website sessions / users / channels (AUD, no FX)
  * TTD   (raw_windsor.perf_the_trade_desk) -> programmatic display delivery (AUD)

This job does NOT touch Snowflake directly. The shared raw layers are filled by
ingest/windsor_data_pull/ and ingest/dts_data_pull/.
"""
import os
import json
import datetime
from decimal import Decimal

from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate: probe these raw tables for new data.
# GA4 has a DTS→Windsor fallback (see sql/01_stg_ga4.sql): raw_ga4.* are the native
# Data-Transfer source (currently frozen — failed transfer), raw_windsor.perf_ga4(+events)
# are the Windsor fallback BASE TABLES that advance when the Windsor loaders run. Watching
# the Windsor base tables makes the gate fire when GA4 catches up via Windsor.
GATING_TABLES = [
    "raw_ga4.perf_ga4",
    "raw_ga4.perf_ga4_events",
    "raw_windsor.perf_ga4",
    "raw_windsor.perf_ga4_events",
    "raw_windsor.perf_the_trade_desk",
]
WATERMARK_OBJECT = "_freshness.json"

# --- Project-wide constants --------------------------------------------------
PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
CLIENT = "vmch"

DATASET = f"client_{CLIENT}"                    # client_vmch
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-vmch-dash
DATA_OBJECT = f"{CLIENT}.json"                  # vmch.json


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

    # --- Freshness gate ---
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
    daily = rows(bq, "daily")
    ttd_markets = rows(bq, "ttd_markets")
    ttd_adgroups = rows(bq, "ttd_adgroups")
    ttd_creative = rows(bq, "ttd_creative")

    # Campaign-grained ad delivery
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")
    ad_campaign_daily = rows(bq, "ad_campaign_daily")
    ad_campaign_market = rows(bq, "ad_campaign_market")
    ad_campaign_market_monthly = rows(bq, "ad_campaign_market_monthly")

    # Market-grained GA4 (single "Australia" market for VMCH)
    ga4_kpi_market = rows(bq, "ga4_kpi_market")
    ga4_monthly_market = rows(bq, "ga4_monthly_market")
    ga4_weekly_market = rows(bq, "ga4_weekly_market")
    ga4_daily_market = rows(bq, "ga4_daily_market")
    ga4_channels_market = rows(bq, "ga4_channels_market")
    ga4_sources_market = rows(bq, "ga4_sources_market")
    ga4_key_events = rows(bq, "ga4_key_events")
    ga4_key_events_daily = rows(bq, "ga4_key_events_daily")

    # Country options (single market for VMCH)
    countries = [r["market"] for r in ga4_kpi_market]

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max([v for v in observed.values() if v])
                         .strftime("%Y-%m-%dT%H:%M:%SZ") if observed else None),
        "currency": "AUD",
        "currency_sym": "A$",
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "ttd_window": {"start": ymd(kpi["ttd_start"]), "end": ymd(kpi["ttd_end"])},
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
            "ttd_imps": num(kpi["ttd_imps"]),
            "ttd_clicks": num(kpi["ttd_clicks"]),
            "ttd_spend_aud": num(kpi["ttd_spend_aud"]),
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_aud": num(kpi["ad_spend_aud"]),
            "ad_post_view": num(kpi["ad_post_view"]),
            "ad_post_click": num(kpi["ad_post_click"]),
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
            "ttd_imps": num(r["ttd_imps"]),
            "ttd_clicks": num(r["ttd_clicks"]),
            "ttd_spend_aud": num(r["ttd_spend_aud"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in monthly],
        "daily": [{
            "day": ymd(r["day"]),
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
            "ttd_imps": num(r["ttd_imps"]),
            "ttd_clicks": num(r["ttd_clicks"]),
            "ttd_spend_aud": num(r["ttd_spend_aud"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in daily],
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
        "ga4_daily_market": [{
            "day": ymd(r["day"]),
            "market": r["market"],
            "ga4_sessions": num(r["ga4_sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "search_sessions": num(r["search_sessions"]),
        } for r in ga4_daily_market],
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
        "ga4_key_events": [{
            "month": r["month"],
            "event_name": r["event_name"],
            "key_events": num(r["key_events"]),
        } for r in ga4_key_events],
        "ga4_key_events_daily": [{
            "day": ymd(r["day"]),
            "event_name": r["event_name"],
            "key_events": num(r["key_events"]),
        } for r in ga4_key_events_daily],
        "ttd_markets": [{
            "market": r["market"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in ttd_markets],
        "ttd_adgroups": [{
            "ad_group": r["ad_group"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in ttd_adgroups],
        "ttd_creative": [{
            "creative": r["creative"],
            "ad_format": r["ad_format"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in ttd_creative],
        # --- Campaign filter ---
        "ad_campaigns": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "post_view": num(r["post_view"]),
            "post_click": num(r["post_click"]),
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
            "post_view": num(r["post_view"]),
            "post_click": num(r["post_click"]),
        } for r in ad_campaign_monthly],
        "ad_campaign_weekly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "post_view": num(r["post_view"]),
            "post_click": num(r["post_click"]),
        } for r in ad_campaign_weekly],
        "ad_campaign_daily": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "day": ymd(r["day"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "post_view": num(r["post_view"]),
            "post_click": num(r["post_click"]),
        } for r in ad_campaign_daily],
        "ad_campaign_market": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "market": r["market"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in ad_campaign_market],
        "ad_campaign_market_monthly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "market": r["market"],
            "month": r["month"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in ad_campaign_market_monthly],
        "weekly": [{
            "week_start": ymd(r["week_start"]),
            "ga4_sessions": num(r["ga4_sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "ttd_imps": num(r["ttd_imps"]),
            "ttd_clicks": num(r["ttd_clicks"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in weekly],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['weekly'])} weeks, {env['kpi']['sessions']:,} sessions, "
          f"A${env['kpi']['ad_spend_aud']:,.0f} ad spend")


if __name__ == "__main__":
    main()