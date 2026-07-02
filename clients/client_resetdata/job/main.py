"""ResetData B2B dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_STT/job/main.py): read the BigQuery
views in client_resetdata/sql/ and write a single resetdata.json to the private GCS
bucket. The gated web app (client_resetdata/dash) serves that JSON at /data.json.

ResetData is a B2B Australian sovereign-AI / data-centre brand, so the story is
"ads -> website traffic / leads" (NOT e-commerce — there is no revenue/ROAS). The
payload pairs five sources the views already filtered + rolled up, across THREE
shared raw layers:
  * Google Ads (raw_google_ads.perf_google_ads)   -> paid-search delivery (AUD; native DTS)
  * Meta       (raw_windsor.perf_meta)             -> paid-social delivery (AUD)
  * Trade Desk (raw_windsor.perf_the_trade_desk)   -> programmatic display (USD -> AUD @1.50)
  * Reddit     (raw_windsor.perf_reddit)           -> community awareness / traffic (AUD)
  * GA4        (raw_ga4.perf_ga4)                  -> website sessions / users / channels (the OUTCOME)
  * GA4 events (raw_ga4.perf_ga4_events)           -> key events / leads by name

This job is READ-ONLY on BigQuery — it only SELECTs the views and writes JSON to GCS.
Currency is AUD throughout (Google spend is already AUD — NOT micros; TTD USD is
converted to AUD at FX_USD_AUD=1.50 in stg_ttd, surfaced here as kpi.fx_usd_aud).
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
    "raw_windsor.perf_meta",
    "raw_windsor.perf_the_trade_desk",
    "raw_windsor.perf_reddit",
    "raw_ga4.perf_ga4",
    "raw_ga4.perf_ga4_events",
    "raw_windsor.hubspot_contacts",   # CRM tab: rebuild when the HubSpot snapshot refreshes
]
WATERMARK_OBJECT = "_freshness.json"

# --- Project-wide constants (identical for every client) ----------------------
PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
# Dataset / bucket / output object all follow from it via the naming convention.
CLIENT = "resetdata"

DATASET = f"client_{CLIENT}"                    # client_resetdata
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-resetdata-dash
DATA_OBJECT = f"{CLIENT}.json"                  # resetdata.json


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
    daily = rows(bq, "daily")
    ga4_channels = rows(bq, "ga4_channels")
    ga4_key_events = rows(bq, "ga4_key_events")
    ga4_key_events_daily = rows(bq, "ga4_key_events_daily")
    ga4_sources = rows(bq, "ga4_sources")
    google_campaigns = rows(bq, "google_campaigns")
    meta_campaigns = rows(bq, "meta_campaigns")
    ttd_campaigns = rows(bq, "ttd_campaigns")
    reddit_campaigns = rows(bq, "reddit_campaigns")
    meta_creative = rows(bq, "meta_creative")
    # Overview demographics + Paid Media gallery/keywords (the client's "birds-eye audience" +
    # "deep dive: who we targeted + creative previews" asks).
    ga_audience = rows(bq, "ga_audience")        # Google Ads age/gender/device (ad audience reached)
    ga_keywords = rows(bq, "ga_keywords")        # Google Ads top keywords ("who we targeted")
    meta_creatives = rows(bq, "meta_creatives")  # Meta creatives WITH preview thumbnails
    # Campaign-grained ad delivery — the dashboard's Campaign filter sums the selected
    # campaigns out of these client-side, rescaling every ad-delivery figure (the
    # GA4/website side has no campaign dimension, so website metrics stay whole).
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")
    ad_campaign_daily = rows(bq, "ad_campaign_daily")
    # --- Signups & CRM tab (HubSpot via raw_windsor.hubspot_contacts/_owners) ----------
    crm_kpi = rows(bq, "crm_kpi")[0]
    crm_signups_weekly = rows(bq, "crm_signups_weekly")
    crm_source_quality = rows(bq, "crm_source_quality")
    crm_lifecycle_owner = rows(bq, "crm_lifecycle_owner")
    crm_lead_queue = rows(bq, "crm_lead_queue")

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
        "ga_window": {"start": ymd(kpi["ga_start"]), "end": ymd(kpi["ga_end"])},
        "me_window": {"start": ymd(kpi["me_start"]), "end": ymd(kpi["me_end"])},
        "td_window": {"start": ymd(kpi["td_start"]), "end": ymd(kpi["td_end"])},
        "rd_window": {"start": ymd(kpi["rd_start"]), "end": ymd(kpi["rd_end"])},
        "kpi": {
            "sessions": num(kpi["sessions"]),
            "engaged_sessions": num(kpi["engaged_sessions"]),
            "users": num(kpi["users"]),
            "new_users": num(kpi["new_users"]),
            "page_views": num(kpi["page_views"]),
            "eng_duration": num(kpi["eng_duration"]),
            "conversions": num(kpi["conversions"]),
            "paid_sessions": num(kpi["paid_sessions"]),
            "search_sessions": num(kpi["search_sessions"]),
            "social_sessions": num(kpi["social_sessions"]),
            "display_sessions": num(kpi["display_sessions"]),
            "ga_imps": num(kpi["ga_imps"]),
            "ga_clicks": num(kpi["ga_clicks"]),
            "ga_spend_aud": num(kpi["ga_spend_aud"]),
            "ga_conv": num(kpi["ga_conv"]),
            "me_imps": num(kpi["me_imps"]),
            "me_clicks": num(kpi["me_clicks"]),
            "me_spend_aud": num(kpi["me_spend_aud"]),
            "me_conv": num(kpi["me_conv"]),
            "td_imps": num(kpi["td_imps"]),
            "td_clicks": num(kpi["td_clicks"]),
            "td_spend_aud": num(kpi["td_spend_aud"]),
            "rd_imps": num(kpi["rd_imps"]),
            "rd_clicks": num(kpi["rd_clicks"]),
            "rd_spend_aud": num(kpi["rd_spend_aud"]),
            "rd_conv": num(kpi["rd_conv"]),
            "rd_page_visits": num(kpi["rd_page_visits"]),
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_aud": num(kpi["ad_spend_aud"]),
            "ad_conv": num(kpi["ad_conv"]),
        },
        "monthly": [{
            "month": r["month"],
            "sessions": num(r["sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "organic_sessions": num(r["organic_sessions"]),
            "direct_sessions": num(r["direct_sessions"]),
            "other_sessions": num(r["other_sessions"]),
            "search_sessions": num(r["search_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "engaged_sessions": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "conversions": num(r["conversions"]),
            "ga_imps": num(r["ga_imps"]),
            "ga_clicks": num(r["ga_clicks"]),
            "ga_spend_aud": num(r["ga_spend_aud"]),
            "me_imps": num(r["me_imps"]),
            "me_clicks": num(r["me_clicks"]),
            "me_spend_aud": num(r["me_spend_aud"]),
            "td_imps": num(r["td_imps"]),
            "td_clicks": num(r["td_clicks"]),
            "td_spend_aud": num(r["td_spend_aud"]),
            "rd_imps": num(r["rd_imps"]),
            "rd_clicks": num(r["rd_clicks"]),
            "rd_spend_aud": num(r["rd_spend_aud"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in monthly],
        "weekly": [{
            "week_start": ymd(r["week_start"]),
            "ga4_sessions": num(r["ga4_sessions"]),
            "conversions": num(r["conversions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "search_sessions": num(r["search_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "ga_imps": num(r["ga_imps"]),
            "me_imps": num(r["me_imps"]),
            "td_imps": num(r["td_imps"]),
            "rd_imps": num(r["rd_imps"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in weekly],
        # Day grain (View by -> Day). raw_ga4.perf_ga4 is day-grained, so this is real
        # per-day data. Mirrors `monthly` (same keys, keyed on `day` = 'YYYY-MM-DD').
        "daily": [{
            "day": ymd(r["day"]),
            "sessions": num(r["sessions"]),
            "paid_sessions": num(r["paid_sessions"]),
            "organic_sessions": num(r["organic_sessions"]),
            "direct_sessions": num(r["direct_sessions"]),
            "other_sessions": num(r["other_sessions"]),
            "search_sessions": num(r["search_sessions"]),
            "social_sessions": num(r["social_sessions"]),
            "display_sessions": num(r["display_sessions"]),
            "engaged_sessions": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "conversions": num(r["conversions"]),
            "ga_imps": num(r["ga_imps"]),
            "ga_clicks": num(r["ga_clicks"]),
            "ga_spend_aud": num(r["ga_spend_aud"]),
            "me_imps": num(r["me_imps"]),
            "me_clicks": num(r["me_clicks"]),
            "me_spend_aud": num(r["me_spend_aud"]),
            "td_imps": num(r["td_imps"]),
            "td_clicks": num(r["td_clicks"]),
            "td_spend_aud": num(r["td_spend_aud"]),
            "rd_imps": num(r["rd_imps"]),
            "rd_clicks": num(r["rd_clicks"]),
            "rd_spend_aud": num(r["rd_spend_aud"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_aud": num(r["ad_spend_aud"]),
        } for r in daily],
        "ga4_channels": [{
            "channel": r["channel_group"],
            "bucket": r["channel_bucket"],
            "sessions": num(r["sessions"]),
            "engaged": num(r["engaged_sessions"]),
            "users": num(r["users"]),
            "conversions": num(r["conversions"]),
        } for r in ga4_channels],
        "ga4_key_events": [{
            "month": r["month"],
            "event_name": r["event_name"],
            "is_conversion_event": bool(r["is_conversion_event"]) if r["is_conversion_event"] is not None else False,
            "event_count": num(r["event_count"]),
            "conversions": num(r["conversions"]),
            "event_value": num(r["event_value"]),
        } for r in ga4_key_events],
        # Day grain for the key-events breakdown (View by -> Day). Mirrors ga4_key_events,
        # keyed on `day` = 'YYYY-MM-DD'. Week grain is bucketed client-side from these.
        "ga4_key_events_daily": [{
            "day": ymd(r["day"]),
            "event_name": r["event_name"],
            "is_conversion_event": bool(r["is_conversion_event"]) if r["is_conversion_event"] is not None else False,
            "event_count": num(r["event_count"]),
            "conversions": num(r["conversions"]),
            "event_value": num(r["event_value"]),
        } for r in ga4_key_events_daily],
        "ga4_sources": [{
            "source_medium": r["source_medium"],
            "channel": r["channel_group"],
            "bucket": r["channel_bucket"],
            "sessions": num(r["sessions"]),
            "engaged": num(r["engaged_sessions"]),
            "conversions": num(r["conversions"]),
            "is_ad": bool(r["is_ad"]),
        } for r in ga4_sources],
        "google_campaigns": [{
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in google_campaigns],
        "meta_campaigns": [{
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "link_clicks": num(r["link_clicks"]),
            "landing_page_views": num(r["landing_page_views"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in meta_campaigns],
        "ttd_campaigns": [{
            "campaign": r["campaign"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in ttd_campaigns],
        "reddit_campaigns": [{
            "campaign": r["campaign"],
            "objective": r["objective"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
            "page_visits": num(r["page_visits"]),
            "start": ymd(r["start_date"]),
            "end": ymd(r["end_date"]),
        } for r in reddit_campaigns],
        "meta_creative": [{
            "creative": r["creative_name"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "link_clicks": num(r["link_clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
        } for r in meta_creative],
        # --- Overview: Google Ads AD-AUDIENCE demographics (age / gender / device) -------
        # "Who the ADS reached" (Google-inferred) — GA4 demographics are thresholded to empty
        # for this low-traffic property, so Google Ads is the only audience source. Label it so.
        "ga_audience": [{
            "dim": r["dim"],
            "bucket": r["bucket"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
        } for r in ga_audience],
        # --- Paid Media: "who we targeted" — top Google Ads keywords (search intent) ------
        "ga_keywords": [{
            "keyword": r["keyword"],
            "match_type": r["match_type"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
        } for r in ga_keywords],
        # --- Paid Media: Meta creative gallery (thumbnail + copy per creative) ------------
        # thumbnail_url is a Meta CDN link that can expire; the export refreshes it each rebuild.
        "meta_creatives": [{
            "creative_id": r["creative_id"],
            "title": r["title"],
            "body": r["body"],
            "thumbnail_url": r["thumbnail_url"],
            "link_url": r["link_url"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "link_clicks": num(r["link_clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
        } for r in meta_creatives],
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
        "ad_campaign_weekly": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "week_start": ymd(r["week_start"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in ad_campaign_weekly],
        # Day grain for the Campaign-filtered ad-delivery charts (View by -> Day). Mirrors
        # ad_campaign_weekly, keyed on `day` = 'YYYY-MM-DD' (carries conversions too).
        "ad_campaign_daily": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "day": ymd(r["day"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
            "conversions": num(r["conversions"]),
        } for r in ad_campaign_daily],
        # --- Signups & CRM (HubSpot) -------------------------------------------------
        # The signup funnel Caroline asks about: Leads -> App signups -> Loaded balance
        # -> Paying. Plus lifecycle×owner, source quality, and the BDM lead queue.
        "crm": {
            "kpi": {
                "leads": num(crm_kpi["leads"]),
                "app_signups": num(crm_kpi["app_signups"]),
                "loaded_balance": num(crm_kpi["loaded_balance"]),
                "paying": num(crm_kpi["paying"]),
                "signups_not_paying": num(crm_kpi["signups_not_paying"]),
                "customers": num(crm_kpi["customers"]),
                "with_deal": num(crm_kpi["with_deal"]),
                "total_balance": num(crm_kpi["total_balance"]),
                "total_rd_spend": num(crm_kpi["total_rd_spend"]),
                "total_hs_revenue": num(crm_kpi["total_hs_revenue"]),
                "queue_new": num(crm_kpi["queue_new"]),
                "queue_unassigned": num(crm_kpi["queue_unassigned"]),
                "queue_new_unassigned": num(crm_kpi["queue_new_unassigned"]),
                "last_signup_at": crm_kpi["last_signup_at"],
                "last_contact_at": crm_kpi["last_contact_at"],
            },
            "signups_weekly": [{
                "week_start": ymd(r["week_start"]),
                "source": r["source_bucket"],
                "signups": num(r["signups"]),
                "loaded_balance": num(r["loaded_balance"]),
                "paying": num(r["paying"]),
                "ad_attributed": num(r["ad_attributed"]),
                "rd_spend": num(r["rd_spend"]),
            } for r in crm_signups_weekly],
            "source_quality": [{
                "source": r["source_bucket"],
                "leads": num(r["leads"]),
                "signups": num(r["signups"]),
                "loaded_balance": num(r["loaded_balance"]),
                "paying": num(r["paying"]),
                "free_only": num(r["free_only"]),
                "with_deal": num(r["with_deal"]),
                "customers": num(r["customers"]),
                "ad_attributed": num(r["ad_attributed"]),
                "rd_spend": num(r["rd_spend"]),
                "signup_rate_pct": num(r["signup_rate_pct"]),
                "pay_rate_pct": num(r["pay_rate_pct"]),
            } for r in crm_source_quality],
            "lifecycle_owner": [{
                "owner": r["owner_name"],
                "lifecycle": r["lifecycle_stage"],
                "contacts": num(r["contacts"]),
                "signups": num(r["signups"]),
                "paying": num(r["paying"]),
                "with_deal": num(r["with_deal"]),
            } for r in crm_lifecycle_owner],
            "lead_queue": [{
                "lead_status": r["lead_status"],
                "owner": r["owner_name"],
                "unassigned": bool(r["unassigned"]),
                "contacts": num(r["contacts"]),
                "unworked": num(r["unworked"]),
                "signups": num(r["signups"]),
            } for r in crm_lead_queue],
        },
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    # Record the watermark only after a successful upload (upload first, watermark
    # second), so a failed upload simply retries on the next tick.
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['weekly'])} weeks, {len(env['daily'])} days, {env['kpi']['sessions']:,} sessions, "
          f"A${env['kpi']['ad_spend_aud']:,.0f} ad spend, "
          f"{env['kpi']['conversions']:,.0f} GA4 key events")


if __name__ == "__main__":
    main()
