r"""City Perfume dashboard export job (Cloud Run job).

Stage 2 of the standard pattern (mirrors client_STT/job/main.py): read the BigQuery
views in client_cityperfume/sql/ and write a single cityperfume.json to the PRIVATE GCS
bucket. The password-gated web app (client_cityperfume/dash) serves that JSON at
/data.json.

City Perfume is e-commerce, so the story is "ads -> actual sales", anchored on the
first-party order ledger (v_sales) as the single source of truth:
  * v_sales (client_cityperfume.v_sales)  -> revenue / margin / orders / AOV / customers
  * Google Ads (raw_google_ads.perf_google_ads, 'City Perfume')      -> paid search/PMax/shopping
  * Meta       (raw_windsor.perf_meta, 'Cityperfume.com.au')         -> paid social (ad-grain, creative)
  * Trade Desk (raw_windsor.perf_the_trade_desk, 'City Perfume')     -> upper-funnel display pilot
  * GA4        (raw_ga4.perf_ga4 / perf_ga4_events, 'City Perfume')  -> website channel context

Everything is AUD (no FX). Headline blended ROAS = total sales / total ad spend (MER);
online-only ROAS (excl. in-store POS) is the stricter secondary lens. Each platform's
own conversions_value/purchase_value is shown as "platform-claimed" and NEVER summed.

PRIVACY (non-negotiable): this job emits AGGREGATES ONLY. It reads only the roll-up views
(never stg_sales / v_sales directly), none of which expose email or customer_id. A final
assertion scans the payload for forbidden keys and refuses to write if any leak through.

Run (deployed):   gcloud run jobs execute cityperfume-export --region australia-southeast1 --wait
Run (local dry):  $env:LOCAL_OUT="cityperfume.json"; .\.venv\Scripts\python.exe client_cityperfume\job\main.py
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
CLIENT = "cityperfume"

DATASET = f"client_{CLIENT}"                    # client_cityperfume
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"    # bidbrain-analytics-cityperfume-dash
DATA_OBJECT = f"{CLIENT}.json"                  # cityperfume.json

# Belt-and-braces privacy guard: no row-level identity must ever reach the JSON.
FORBIDDEN_KEYS = {"customer_id", "email", "customerid", "e_mail"}


def clean(row):
    """JSON-safe dict from a BigQuery row: Decimal/NUMERIC -> float, DATE -> 'YYYY-MM-DD'.
    Generic so the JSON keys mirror the view columns exactly (no hand-listing drift)."""
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = v.isoformat()[:10]
        else:
            out[k] = v
    return out


def rows(bq, name):
    sql = f"SELECT * FROM `{PROJECT}.{DATASET}.{name}`"
    return [clean(r) for r in bq.query(sql, location=LOC).result()]


def one(bq, name):
    r = rows(bq, name)
    return r[0] if r else {}


def assert_no_pii(obj, path="root"):
    """Recursively refuse to ship if any forbidden identity key appears."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in FORBIDDEN_KEYS:
                raise SystemExit(f"PII LEAK: key '{k}' found at {path} — refusing to write JSON.")
            assert_no_pii(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_no_pii(v, f"{path}[{i}]")


def main():
    bq = bigquery.Client(project=PROJECT)

    kpi = one(bq, "kpi")

    env = {
        "client": "City Perfume",
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "AUD",
        "window": {
            "start": kpi.get("window_start"),
            "end": kpi.get("window_end"),
            "days": kpi.get("window_days"),
        },
        # Notes the dashboard surfaces verbatim (attribution stance + data caveats).
        "notes": {
            "attribution": ("Blended marketing-efficiency ratio: v_sales is the source of "
                            "truth for revenue/orders/margin. Headline blended ROAS = total "
                            "sales / total ad spend; online ROAS excludes in-store POS. "
                            "Platform-claimed conversions_value/purchase_value are shown for "
                            "context only and never summed."),
            "ga4_caveat": ("GA4 tracking degraded from ~Oct 2025 (sessions/revenue collapse); "
                           "GA4 figures are directional only and never used as revenue truth."),
            "margin_caveat": ("Margin is net as-reported; some lines have zero cost_price "
                              "(inflates margin) or negative promo margins."),
        },
        # Headline + trends
        "kpi": kpi,
        "monthly": rows(bq, "monthly"),         # kept for the CSV export
        "weekly": rows(bq, "weekly"),
        # DAY-GRAINED sources — the dashboard clips these to the exact selected date range,
        # aggregates up for KPIs/donuts/tables, and buckets to day/week/month for trend charts
        # by range span. The full-period arrays below stay the EXACT source when the range is
        # NOT narrowed (so the default view is unchanged and distinct-customer counts stay exact).
        "sales_daily": rows(bq, "sales_daily"),
        "sales_by_channel_daily": rows(bq, "sales_by_channel_daily"),
        "sales_category_daily": rows(bq, "sales_category_daily"),
        "sales_products_daily": rows(bq, "sales_products_daily"),
        "ga4_channels_daily": rows(bq, "ga4_channels_daily"),
        "ga4_sources_daily": rows(bq, "ga4_sources_daily"),
        "ga4_funnel_daily": rows(bq, "ga4_funnel_daily"),
        "ad_campaign_daily": rows(bq, "ad_campaign_daily"),
        "google_campaign_type_daily": rows(bq, "google_campaign_type_daily"),
        "meta_creative_daily": rows(bq, "meta_creative_daily"),
        # GA4 / Website — full-period (exact source when the range is not narrowed)
        "ga4_channels": rows(bq, "ga4_channels"),
        "ga4_monthly_channel": rows(bq, "ga4_monthly_channel"),
        "ga4_sources": rows(bq, "ga4_sources"),
        "ga4_funnel": one(bq, "ga4_funnel"),
        # Sales & Products (first-party truth) — full-period (exact when not narrowed)
        "sales_kpi": one(bq, "sales_kpi"),
        "sales_monthly": rows(bq, "sales_monthly"),
        "sales_products": rows(bq, "sales_products"),
        "sales_by_channel": rows(bq, "sales_by_channel"),
        "sales_category": rows(bq, "sales_category"),
        "sales_new_returning": rows(bq, "sales_new_returning"),
        # Paid media detail — full-period (exact when not narrowed)
        "platform_summary": rows(bq, "platform_summary"),
        "google_campaign_type": rows(bq, "google_campaign_type"),
        "meta_creative": rows(bq, "meta_creative"),
        # Campaign filter list + whole-window per-campaign totals (the multi-select reads these).
        "ad_campaigns": rows(bq, "ad_campaigns"),
        "ad_campaign_monthly": rows(bq, "ad_campaign_monthly"),
        "ad_campaign_weekly": rows(bq, "ad_campaign_weekly"),
    }

    # Refuse to ship if any identity key leaked through (defence in depth).
    assert_no_pii(env)

    payload = json.dumps(env)

    local_out = os.environ.get("LOCAL_OUT")
    if local_out:
        with open(local_out, "w", encoding="utf-8") as f:
            f.write(payload)
        dest = os.path.abspath(local_out)
    else:
        storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
            payload, content_type="application/json")
        dest = f"gs://{BUCKET}/{DATA_OBJECT}"

    print(f"wrote {dest} | {len(payload):,} bytes | "
          f"rev ${kpi.get('revenue_total', 0):,.0f} | "
          f"ad spend ${kpi.get('ad_spend', 0):,.0f} | "
          f"blended ROAS {kpi.get('roas_blended', 0):.1f}x | "
          f"{len(env['monthly'])} months, {len(env['ad_campaigns'])} campaigns, "
          f"{len(env['meta_creative'])} creatives")


if __name__ == "__main__":
    main()
