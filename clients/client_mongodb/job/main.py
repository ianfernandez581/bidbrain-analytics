import os, json, datetime
from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when an
# upstream raw table this job reads has advanced. GATING_TABLES are "dataset.table"
# ids in this project, probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
# These are the live mirrors the views read; they also define `data_through`.
# `tradedesk_apac_conversion` backs the Universal-Pixel content-engagement section
# (live since the manual CSV seed was retired), so it both gates the rebuild and
# counts toward `data_through`.
SNOWFLAKE_TABLES = [
    "raw_snowflake.tradedesk_apac_all",
    "raw_snowflake.salesforce_cs_apac_all",
    "raw_snowflake.tradedesk_apac_conversion",
]
# The LinkedIn lane (AWS Immersion Day etc.) reads the shared Windsor raw layer, so gate on it
# too. It's a SHARED table (all clients' LinkedIn), so its last_modified advances whenever the
# windsor-linkedin loader runs for ANY client - a cheap over-trigger (mongodb rebuilds ~daily),
# acceptable per the freshness contract ("gate on what you read"). Kept out of `data_through`
# (that stays on the MongoDB-specific Snowflake mirrors).
WINDSOR_TABLES = [
    "raw_windsor.perf_linkedin",
]
GATING_TABLES = SNOWFLAKE_TABLES + WINDSOR_TABLES
WATERMARK_OBJECT = "_freshness.json"

# --- Project-wide constants ---------------------------------------------------
# One GCP project -> identical for EVERY client, so hardcoded here.
PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
# Copy this folder for a new client and change ONLY this (e.g. "acme").
# Dataset / bucket / output object all follow from it via the naming convention.
CLIENT = "mongodb"

DATASET     = f"client_{CLIENT}"                    # client_mongodb
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-mongodb-dash
DATA_OBJECT = f"{CLIENT}.json"                      # mongodb.json

# This job no longer touches Snowflake. The Snowflake source tables are mirrored
# into BigQuery (raw_snowflake.*) by the shared snowflake_data_pull/ unit, and
# this client's views filter + transform them (see client_mongodb/sql/). So the
# refresh is TWO steps now:
#   1. python snowflake_data_pull/loader.py     (refresh the shared raw layer)
#   2. run this job                             (BigQuery views -> mongodb.json)
# The per-client filter (the 3 DNB campaign IDs) and the country->market mapping
# live in the stg_salesforce view, not here.


def iso(v):
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return str(v)


def rows(bq, sql):
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

    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    pm  = rows(bq, f"SELECT * FROM {t('paid_media_model')}")
    win = rows(bq, f"SELECT MIN(d.DATE) AS s, MAX(d.DATE) AS e, "
                   f"DATE_DIFF(MAX(d.DATE),MIN(d.DATE),DAY)+1 AS days FROM {t('paid_media_model')} d")[0]
    tgt = rows(bq, f"SELECT * FROM {t('targets')}")
    bs  = rows(bq, f"SELECT * FROM {t('benchmarks_strategy')}")
    bm  = rows(bq, f"SELECT * FROM {t('benchmarks_market')}")
    bud = rows(bq, f"SELECT * FROM {t('budget')}")
    cso = rows(bq, f"SELECT * FROM {t('cs_leads')}")
    csp = rows(bq, f"SELECT * FROM {t('cs_leads_by_programme')}")

    # Content-engagement snapshot (Trade Desk Universal Pixel) — LIVE from
    # raw_snowflake.tradedesk_apac_conversion via the pixel_* views (the manual CSV
    # seed was retired). Emitted PER CAMPAIGN ('DNB' / 'IDC') so the dashboard's
    # campaign toggle can pick its slice client-side. Resilient: if the views aren't
    # present yet, the rest of the dashboard still builds and the UI hides the section.
    pixel = None
    try:
        summ   = rows(bq, f"SELECT * FROM {t('pixel_summary')}")   # one row per CAMPAIGN_KEY
        assets = rows(bq, f"SELECT * FROM {t('pixel_assets')}")    # per CAMPAIGN_KEY x asset
        pixel = {
            # keyed by campaign: the dash reads pixel.summary[activeCampaign].
            "summary": {s["CAMPAIGN_KEY"]: {
                "start": iso(s["START_DAY"]), "end": iso(s["END_DAY"]), "days": s["DAYS"],
                "imps": s["IMPS"], "cost_usd": s["COST_USD"], "clicks": s["CLICKS"],
                "all_conv": s["ALL_CONV"],
                "content_total": s["CONTENT_TOTAL"], "content_click": s["CONTENT_CLICK"],
                "content_view": s["CONTENT_VIEW"],
                "default_total": s["DEFAULT_TOTAL"], "default_view": s["DEFAULT_VIEW"],
                "default_click": s["DEFAULT_CLICK"],
            } for s in summ},
            # each asset tagged with its campaign so the dash filters by the toggle.
            "assets": [{"campaign": r["CAMPAIGN_KEY"], "key": r["ASSET_KEY"], "asset": r["ASSET"],
                        "total": r["TOTAL_CONV"], "click": r["CLICK_CONV"], "view": r["VIEW_CONV"]}
                       for r in assets],
        }
    except Exception as e:
        print(f"pixel views unavailable -> skipping content-engagement block: {e}")

    # LinkedIn lane (AWS Immersion Day + any future MongoDB LinkedIn campaign) - from the shared
    # Windsor raw layer via the linkedin_* views. Emitted ONLY when there's real delivery
    # (imps > 0); otherwise stays None and the dashboard auto-hides the LinkedIn tab. Resilient:
    # if the views aren't present the rest of the dashboard still builds. Empty until the Windsor
    # connector for the MongoDB ad account is readable (see the linkedin ingest README).
    linkedin = None
    try:
        lsum = rows(bq, f"SELECT * FROM {t('linkedin_summary')}")
        if lsum and (lsum[0].get("imps") or 0) > 0:
            s = lsum[0]
            ldaily = rows(bq, f"SELECT * FROM {t('linkedin_daily')}")
            lcamps = rows(bq, f"SELECT * FROM {t('linkedin_by_campaign')}")
            linkedin = {
                "summary": {
                    "campaigns": s["campaigns"], "creatives": s["creatives"],
                    "start": iso(s["start_date"]), "end": iso(s["end_date"]),
                    "currency": s["currency"],
                    "imps": s["imps"], "clicks": s["clicks"], "spend_usd": s["spend_usd"],
                    "spend_native": s["spend_native"], "reach": s["reach"],
                    "landing_page_clicks": s["landing_page_clicks"],
                    "leads": s["leads"], "lead_form_opens": s["lead_form_opens"],
                    "engagements": s["engagements"], "video_views": s["video_views"],
                    "video_completions": s["video_completions"],
                    "ext_website_conversions": s["ext_website_conversions"],
                },
                "daily": [{"date": iso(r["DAY"]), "week_start": iso(r["WEEK_START"]),
                           "imps": r["imps"], "clicks": r["clicks"], "spend_usd": r["spend_usd"],
                           "leads": r["leads"], "lead_form_opens": r["lead_form_opens"]} for r in ldaily],
                "campaigns": [{"campaign": r["campaign_name"], "group": r["campaign_group_name"],
                               "objective": r["objective_type"], "currency": r["currency"],
                               "imps": r["imps"], "clicks": r["clicks"], "spend_usd": r["spend_usd"],
                               "spend_native": r["spend_native"], "leads": r["leads"],
                               "lead_form_opens": r["lead_form_opens"], "video_views": r["video_views"],
                               "engagements": r["engagements"],
                               "start": iso(r["start_date"]), "end": iso(r["end_date"])} for r in lcamps],
            }
            print(f"linkedin lane: {s['imps']} imps, {s['leads']} leads over "
                  f"{len(linkedin['daily'])} days, {len(linkedin['campaigns'])} campaign(s)")
        else:
            print("linkedin lane: no MongoDB LinkedIn delivery yet (tab will auto-hide)")
    except Exception as e:
        print(f"linkedin views unavailable -> skipping LinkedIn block: {e}")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # `data_through` reflects the LIVE ad/lead mirrors only — never the static pixel
        # seed's load time (which would overstate freshness).
        "data_through": (lambda sf: max(sf).strftime("%Y-%m-%dT%H:%M:%SZ") if sf else None)(
            [observed[k] for k in SNOWFLAKE_TABLES if observed.get(k)]),
        "row_count": len(pm),
        "window": {"start": iso(win["s"]), "end": iso(win["e"]), "days": win["days"]},
        # "OTHER" = leads in countries outside the 4 plan markets (e.g. China, Japan).
        # Surfaced as its own region so every lead is counted; has no plan target.
        "all_markets": ["ANZ","ASEAN","INDIA","KR-HK-TW","OTHER"],
        "all_programmes": ["IDE","IDC"],
        "rows": [{"channel": r["CHANNEL"], "date": iso(r["DATE"]), "week_start": iso(r["WEEK_START"]),
                  "programme": r["PROGRAMME"], "market": r["MARKET"], "strategy": r["STRATEGY"],
                  "objective": r["OBJECTIVE"], "imps": r["IMPS"], "clicks": r["CLICKS"],
                  "spend_usd": r["SPEND_USD"], "conversions": r["CONVERSIONS"], "leads": r["LEADS"]} for r in pm],
        "targets": [{"programme": r["PROGRAMME_LABEL"], "market": r["MARKET"],
                     "target": r["TARGET_LEADS"], "delivered": r["DELIVERED_LEADS_SNAPSHOT"],
                     "cpl": r["CPL"]} for r in tgt],
        "benchmarks_strategy": {r["STRATEGY"]: {"cpm": r["CPM"], "ctr": r["CTR"], "cpc": r["CPC"],
                     "frequency": r["FREQUENCY_CAP"], "weight": r["BUDGET_WEIGHT"]} for r in bs},
        "benchmarks_market": {r["MARKET"]: {"budget_weight": r["BUDGET_WEIGHT"]} for r in bm},
        "budget": [{"programme": r["PROGRAMME_LABEL"], "tradedesk_code": r["TRADEDESK_CODE"],
                    "gross_usd": r["GROSS_BUDGET_USD"], "net_usd": r["NET_BUDGET_USD"],
                    "start": iso(r["START_DATE"]), "end": iso(r["END_DATE"]),
                    "est_cpc": r["EST_CPC"]} for r in bud],
        "cs": [{"market": r["MARKET"], "total": r["TOTAL_LEADS"], "accepted": r["ACCEPTED"],
                "rejected": r["REJECTED"], "new": r["NEW_LEADS"],
                "last_lead_day": iso(r["LAST_LEAD_DAY"])} for r in cso],
        "cs_by_programme": [{"programme": r["PROGRAMME_LABEL"], "market": r["MARKET"], "total": r["TOTAL_LEADS"],
                "accepted": r["ACCEPTED"], "rejected": r["REJECTED"], "new": r["NEW_LEADS"],
                "last_lead_day": iso(r["LAST_LEAD_DAY"])} for r in csp],
        "pixel": pixel,
        "linkedin": linkedin,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    # Record the watermark only after a successful upload (upload first, watermark
    # second), so a failed upload simply retries on the next tick.
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['rows'])} rows, "
          f"{sum(c['total'] for c in env['cs'])} leads")


if __name__ == "__main__":
    main()
