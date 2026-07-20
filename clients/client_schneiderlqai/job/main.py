"""Schneider Electric "Liquid AI Data Center" (LQAIDC) — paid-media dashboard export job (Cloud Run job).

Stage 2 of the standard pattern: read the BigQuery views in client_schneiderlqai/sql/ and write a
single schneiderlqai.json to the private GCS bucket. The gated web app (client_schneiderlqai/dash)
serves that JSON at /data.json.

This is a SINGLE-CAMPAIGN, paid-media-only dashboard (NOT the multi-program Schneider Pacific one):
the LQAIDC TOFU / Awareness push for "Liquid Cooling for AI Data Centers", running LinkedIn + The
Trade Desk across 6 countries (India, Brazil, Australia, Chile, Saudi Arabia, UAE). Awareness only —
NO leads / conversions / Salesforce. The dashboard is delivery (spend / impressions / clicks / CTR)
+ pacing against the media-plan targets (from data/media_plan.csv -> seed_media_plan) + a creative
breakdown.

Read-only on BigQuery (SELECTs views, writes JSON to GCS). Reporting currency AUD.
"""
import os
import json
import datetime
from decimal import Decimal

from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (repo CLAUDE.md "Freshness contract"): rebuild only when an upstream raw table this
# job reads has advanced. Probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
GATING_TABLES = [
    "raw_snowflake.linkedin_ads_apac",
    "raw_snowflake.tradedesk_apac_all",
]
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
CLIENT = "schneiderlqai"
DATASET = f"client_{CLIENT}"
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"
DATA_OBJECT = f"{CLIENT}.json"

# Channel key -> display label. Only channels with delivery rows are emitted.
CHAN_LABEL = {"linkedin": "LinkedIn", "tradedesk": "The Trade Desk"}
# Country display order (India dominates; then the media-plan regions).
COUNTRY_ORDER = {"India": 0, "Australia": 1, "Brazil": 2, "Chile": 3, "Saudi Arabia": 4, "UAE": 5, "Other": 9}
REGION_ORDER = {"India": 0, "Pacific": 1, "South America": 2, "MEA": 3, "Other": 9}


def num(v):
    """JSON-safe number: NUMERIC/Decimal -> float; leave ints/None alone."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def ymd(v):
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()[:10]
    return str(v)[:10]


def rows(bq, name, order_by=None):
    sql = f"SELECT * FROM `{PROJECT}.{DATASET}.{name}`"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def main():
    bq = bigquery.Client(project=PROJECT)

    # --- Freshness gate -------------------------------------------------------
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

    # --- Read the views -------------------------------------------------------
    delivery = rows(bq, "delivery", order_by="metric_date, platform, country")
    creative = rows(bq, "creative")
    plan = rows(bq, "seed_media_plan")

    # --- Countries / regions / channels present in the delivery data ----------
    countries = sorted({r["country"] for r in delivery}, key=lambda c: (COUNTRY_ORDER.get(c, 5), c))
    regions = sorted({r["region"] for r in delivery}, key=lambda r: (REGION_ORDER.get(r, 5), r))
    live_platforms = {r["platform"] for r in delivery}
    channels = [{"key": k, "label": CHAN_LABEL.get(k, k)}
                for k in ["linkedin", "tradedesk"] if k in live_platforms]

    # --- Data window (for the date picker) ------------------------------------
    dates = [r["metric_date"] for r in delivery if r["metric_date"]]
    wstart, wend = (min(dates), max(dates)) if dates else (None, None)
    wdays = (wend - wstart).days + 1 if (wstart and wend) else None

    # --- Media-plan targets ---------------------------------------------------
    # plan.lines = the full brief media plan (7 lines incl. not-yet-live Search / Reddit / Retargeting);
    # plan.channels = per-channel targets summed over the LIVE lines (live=1 == currently delivering),
    # so the dashboard's pacing compares delivered vs the targets for the phase that's actually running.
    plan_lines = [{
        "channel": p["channel"], "channel_key": p["channel_key"], "phase": p["phase"],
        "geo": p["geo"], "flight_start": ymd(p["flight_start"]), "flight_end": ymd(p["flight_end"]),
        "imp_target": num(p["imp_target"]), "reach_target": num(p["reach_target"]),
        "click_target": num(p["click_target"]), "ctr_target": num(p["ctr_target"]),
        "spend_target": num(p["spend_target"]), "live": int(p["live"] or 0), "note": p["note"],
    } for p in plan]

    plan_channels = []
    for k in ["linkedin", "tradedesk"]:
        live = [p for p in plan_lines if p["channel_key"] == k and p["live"]]
        if not live:
            continue
        plan_channels.append({
            "key": k, "label": CHAN_LABEL.get(k, k),
            "imp_target": sum(p["imp_target"] or 0 for p in live),
            "reach_target": sum(p["reach_target"] or 0 for p in live),
            "click_target": sum(p["click_target"] or 0 for p in live),
            "spend_target": sum(p["spend_target"] or 0 for p in live),
        })
    live_budget = sum(p["spend_target"] or 0 for p in plan_lines if p["live"])
    total_budget = sum(p["spend_target"] or 0 for p in plan_lines)
    live_starts = [p["flight_start"] for p in plan_lines if p["live"] and p["flight_start"]]
    live_ends = [p["flight_end"] for p in plan_lines if p["live"] and p["flight_end"]]
    flight = {"start": min(live_starts) if live_starts else ymd(wstart),
              "end": max(live_ends) if live_ends else ymd(wend)}

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max([v for v in observed.values() if v]).strftime("%Y-%m-%dT%H:%M:%SZ")
                         if observed else None),
        "currency": "AUD",
        "campaign": "Liquid AI Data Center",
        "phase": "TOFU / Awareness",
        "window": {"start": ymd(wstart), "end": ymd(wend), "days": wdays},
        "countries": countries,
        "regions": regions,
        "channels": channels,
        "flight": flight,
        "delivery": [{
            "platform": r["platform"], "date": ymd(r["metric_date"]),
            "country": r["country"], "region": r["region"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in delivery],
        "creative": [{
            "platform": r["platform"], "country": r["country"], "concept": r["concept"],
            "format": r["creative_format"], "creative_name": r["creative_name"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in creative],
        "plan": {
            "channels": plan_channels, "lines": plan_lines,
            "live_budget": live_budget, "total_budget": total_budget,
        },
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    tot_imp = sum(r["imps"] for r in env["delivery"])
    tot_spend = sum(r["spend_aud"] for r in env["delivery"])
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['delivery'])} delivery rows, "
          f"{len(env['creative'])} creatives, {len(countries)} countries, "
          f"{tot_imp:,.0f} imps / A${tot_spend:,.0f} spend, "
          f"window {env['window']['start']}..{env['window']['end']}")


if __name__ == "__main__":
    main()
