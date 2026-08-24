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

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when an
# upstream raw table this job reads has advanced. GATING_TABLES are "dataset.table"
# ids in this project, probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
GATING_TABLES = [
    "raw_snowflake.dv360_apac",
    "raw_snowflake.linkedin_ads_apac",
    "raw_snowflake.tradedesk_apac_all",
]
WATERMARK_OBJECT = "_freshness.json"

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
    li_creative = rows(bq, "li_creative")
    li_campaigns = rows(bq, "li_campaigns")
    # Campaign-grained ad delivery — the dashboard's Campaign filter sums the
    # selected campaigns out of these client-side, rescaling every ad-delivery
    # figure. ad_campaign_market also powers the Market filter + by-market charts.
    ad_campaigns = rows(bq, "ad_campaigns")
    ad_campaign_monthly = rows(bq, "ad_campaign_monthly")
    ad_campaign_weekly = rows(bq, "ad_campaign_weekly")
    ad_campaign_daily = rows(bq, "ad_campaign_daily")
    ad_campaign_market = rows(bq, "ad_campaign_market")
    li_campaign_creative = rows(bq, "li_campaign_creative")
    scope = rows(bq, "scope_audit")
    # Media-plan pacing. `targets/media_plan.csv` is blank until a signed plan lands, in
    # which case has_targets is False and the dashboard hides the whole pacing section
    # rather than drawing 0/0 cards. See sql/19_pacing.sql + targets/README.md.
    pacing = rows(bq, "pacing")
    has_targets = bool(pacing and pacing[0].get("has_targets"))

    # --- Refuse to publish an empty fact (the caltex pattern). A view that returns
    # nothing - a renamed advertiser, a truncated mirror, a broken filter - would
    # otherwise overwrite a good hireright.json with a dashboard reading zero across
    # the board, which looks like "the campaign stopped" rather than "the pipeline
    # broke". Better to fail the run, leave the last good JSON in place, and go red
    # in `gcloud run jobs executions list`.
    if not ad_campaigns:
        raise SystemExit(
            "ABORT: ad_campaigns is EMPTY - refusing to overwrite hireright.json with a blank "
            "dashboard. Check sql/17_scope_audit (did an advertiser/account get renamed?) and "
            "that raw_snowflake.{dv360_apac,tradedesk_apac_all,linkedin_ads_apac} still hold rows.")

    # --- Scope audit: the three filters are name matches (two of them substring), so
    # print exactly what they swept in. A NEW entity appearing here means every KPI on
    # the dashboard just moved for a reason nobody chose. Logged every run so the
    # widening is discoverable from the job log alone.
    print(f"scope audit - {len(scope)} matched entities:")
    for r in scope:
        print(f"  [{r['source']:9}] {r['entity']!r} via {r['matched_on']} | "
              f"{r['rows_matched']:,} rows | {r['first_day']} -> {r['last_day']} | "
              f"{r['campaigns']} campaigns | currency={r['currency_forms']}")
    by_src = {}
    for r in scope:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    for src, n in sorted(by_src.items()):
        if n > 1:
            print(f"  WARNING: {src} matched {n} DISTINCT entities - the filter has widened. "
                  f"Confirm all of them are HireRight before trusting these numbers.")

    # Market options for the filter, ordered by total spend desc. DV360 carries real
    # countries; TradeDesk + LinkedIn are 'Global'. Default = all markets selected.
    mkt_spend = {}
    reg_spend = {}
    for r in ad_campaign_market:
        mkt_spend[r["market"]] = mkt_spend.get(r["market"], 0) + (num(r["spend_usd"]) or 0)
        reg_spend[r["region"]] = reg_spend.get(r["region"], 0) + (num(r["spend_usd"]) or 0)
    markets = sorted(mkt_spend, key=lambda m: mkt_spend[m], reverse=True)
    regions = sorted(reg_spend, key=lambda m: reg_spend[m], reverse=True)

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max([v for v in observed.values() if v])
                         .strftime("%Y-%m-%dT%H:%M:%SZ") if observed else None),
        "fx_aud_usd": num(kpi["fx_aud_usd"]),
        "window": {
            "start": ymd(kpi["campaign_start"]),
            "end": ymd(kpi["campaign_end"]),
            "days": kpi["campaign_days"],
        },
        "dv_window": {"start": ymd(kpi["dv_start"]), "end": ymd(kpi["dv_end"])},
        "td_window": {"start": ymd(kpi["td_start"]), "end": ymd(kpi["td_end"])},
        "li_window": {"start": ymd(kpi["li_start"]), "end": ymd(kpi["li_end"])},
        # Outcomes are carried SEPARATELY and never summed into one "conversions"
        # figure - `attr_conv` is programmatic post-click/post-view (DV360 + TTD,
        # NOT deduplicated between them), `leads` is LinkedIn lead-gen form
        # submissions. See sql/04_stg_ad_delivery.sql for the full reasoning.
        "kpi": {
            "dv_imps": num(kpi["dv_imps"]),
            "dv_clicks": num(kpi["dv_clicks"]),
            "dv_spend_usd": num(kpi["dv_spend_usd"]),
            "dv_attr_conv": num(kpi["dv_attr_conv"]),
            "td_imps": num(kpi["td_imps"]),
            "td_clicks": num(kpi["td_clicks"]),
            "td_spend_usd": num(kpi["td_spend_usd"]),
            "td_attr_conv": num(kpi["td_attr_conv"]),
            "li_imps": num(kpi["li_imps"]),
            "li_clicks": num(kpi["li_clicks"]),
            "li_cost_usd": num(kpi["li_cost_usd"]),
            "li_leads": num(kpi["li_leads"]),
            "li_lead_form_opens": num(kpi["li_lead_form_opens"]),
            "ad_imps": num(kpi["ad_imps"]),
            "ad_clicks": num(kpi["ad_clicks"]),
            "ad_spend_usd": num(kpi["ad_spend_usd"]),
            "ad_attr_conv": num(kpi["ad_attr_conv"]),
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
        "daily": [{
            "day": r["day"],
            "dv_imps": num(r["dv_imps"]),
            "td_imps": num(r["td_imps"]),
            "li_imps": num(r["li_imps"]),
            "ad_imps": num(r["ad_imps"]),
            "ad_clicks": num(r["ad_clicks"]),
            "ad_spend_usd": num(r["ad_spend_usd"]),
        } for r in daily],
        "markets": markets,
        "regions": regions,
        # Pacing. `has_targets` is the ONE switch the dashboard reads to decide whether
        # the pacing section exists at all - a *_pct/*_pace of NULL means the plan made
        # no commitment on that metric and it must be omitted, never rendered as 0%.
        "has_targets": has_targets,
        "pacing": [{
            "platform": r["platform"],
            "plan_lines": num(r["plan_lines"]),
            "flight_start": ymd(r["flight_start"]),
            "flight_end": ymd(r["flight_end"]),
            "flight_source": r["flight_source"],     # 'planned' | 'observed'
            "elapsed_frac": num(r["elapsed_frac"]),
            "budget_usd": num(r["budget_usd"]),
            "imp_target": num(r["imp_target"]),
            "click_target": num(r["click_target"]),
            "lead_target": num(r["lead_target"]),
            "ctr_target": num(r["ctr_target"]),
            "cpm_target_usd": num(r["cpm_target_usd"]),
            "cpc_target_usd": num(r["cpc_target_usd"]),
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_usd": num(r["spend_usd"]),
            "leads": num(r["leads"]),
            "attr_conv": num(r["attr_conv"]),
            "spend_pct": num(r["spend_pct"]),
            "imp_pct": num(r["imp_pct"]),
            "click_pct": num(r["click_pct"]),
            "lead_pct": num(r["lead_pct"]),
            "spend_pace": num(r["spend_pace"]),
            "imp_pace": num(r["imp_pace"]),
            "click_pace": num(r["click_pace"]),
            "lead_pace": num(r["lead_pace"]),
        } for r in pacing],
        # What the three name filters actually matched this run. Surfaced in the JSON
        # (not just the log) so the dashboard's data-provenance note can state the
        # scope, and so the status pipeline has a non-circular thing to check.
        "scope_audit": [{
            "source": r["source"],
            "matched_on": r["matched_on"],
            "entity": r["entity"],
            "rows": num(r["rows_matched"]),
            "campaigns": num(r["campaigns"]),
            "first_day": ymd(r["first_day"]),
            "last_day": ymd(r["last_day"]),
            "currency_forms": r["currency_forms"],
        } for r in scope],
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
            "brief": r["brief"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_usd": num(r["spend_usd"]),
            "engagements": num(r["engagements"]),
            # Kept apart on purpose - never add these two together (sql/04).
            "leads": num(r["leads"]),
            "attr_conv": num(r["attr_conv"]),
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
        "ad_campaign_daily": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "day": r["day"],
            "imps": num(r["imps"]),
            "clicks": num(r["clicks"]),
            "spend_usd": num(r["spend_usd"]),
        } for r in ad_campaign_daily],
        "ad_campaign_market": [{
            "platform": r["platform"],
            "campaign": r["campaign"],
            "market": r["market"],
            "region": r["region"],
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
    # Record the watermark only after a successful upload (upload first, watermark
    # second), so a failed upload simply retries on the next tick.
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    k = env["kpi"]
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['monthly'])} months, "
          f"{len(env['ad_campaigns'])} campaigns, {len(env['markets'])} markets, "
          f"US${k['ad_spend_usd']:,.0f} ad spend | "
          f"{k['ad_attr_conv'] or 0:,.0f} attributed conv (DV360+TTD), "
          f"{k['li_leads'] or 0:,.0f} LinkedIn leads")
    # Per-platform last delivery day - the cheapest read on "is a feed dead?". DV360
    # has been frozen upstream at Transmission since 2026-07-01; this line is how a
    # future stall on any of the three gets noticed from the job log.
    for lbl, w in (("dv360", env["dv_window"]), ("tradedesk", env["td_window"]),
                   ("linkedin", env["li_window"])):
        print(f"  last delivery [{lbl:9}] {w['start']} -> {w['end']}")
    print(f"  pacing: has_targets={has_targets} "
          f"({'rendering' if has_targets else 'HIDDEN - no signed media plan; see targets/README.md'})")


if __name__ == "__main__":
    main()
