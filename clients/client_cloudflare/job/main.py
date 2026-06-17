"""Cloudflare APAC dashboard export job (Cloud Run job).

Now on the SAME pattern as every other client (MongoDB template): BigQuery owns the
model. The shared ingest unit (ingest/snowflake_data_pull) already mirrors the four
dynamic APAC platform tables into raw_snowflake; the Cloudflare-specific STATIC tables
(pacing targets, account tiers, LINE JP upload) are committed CSV snapshots seeded into
client_cloudflare.seed_* (pull_static.py -> data/ -> seed_static.py). The sql/ views
model everything in BigQuery, and this job just reads those views and assembles
cloudflare.json. IT NO LONGER TOUCHES SNOWFLAKE.

    raw_snowflake.* mirrors (+ client_cloudflare.seed_* static seeds)
      -> BigQuery views (client_cloudflare/sql/)   read here
      -> cloudflare.json                           one combined payload
      -> GCS (private)

Refresh is two steps, like MongoDB:
    1. python ingest/snowflake_data_pull/loader.py   (refresh the shared raw layer)
    2. run this job                                  (BigQuery views -> cloudflare.json)

History: this client used to pull Snowflake's pre-modelled CLOUDFLARE_SANDBOX.* views
and land them as src_* pass-throughs. That deviated from the repo pattern; it was ported
to BigQuery modelling on 2026-06-17 (see client_cloudflare/README.md + sql/README.md).
"""
import os, json, datetime
from decimal import Decimal as _Decimal
import datetime as _dt
import math

from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale


def _json_default(o):
    if isinstance(o, _Decimal):
        return float(o)
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


# --- Project-wide constants (identical for every client) ----------------------
PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
CLIENT = "cloudflare"

DATASET     = f"client_{CLIENT}"                    # client_cloudflare
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-cloudflare-dash
DATA_OBJECT = f"{CLIENT}.json"                      # cloudflare.json

# --- Freshness gate -----------------------------------------------------------
# BigQuery-reading client now (see CLAUDE.md "Freshness contract"): rebuild only when
# an upstream raw_snowflake mirror this job's views read has advanced. These are the
# four dynamic platform tables behind the paid-media + CS views; they also define
# `data_through`. The static seed_* tables are NOT freshness drivers (re-seed forces a
# manual rebuild -- see seed_static.py / the FORCE_REBUILD caveat in CLAUDE.md).
GATING_TABLES = [
    "raw_snowflake.salesforce_cs_apac_all",   # -> salesforce_leads_live -> pacing_model (CS)
    "raw_snowflake.tradedesk_apac_all",        # -> stg_tradedesk -> paid_media_model
    "raw_snowflake.linkedin_ads_apac",         # -> stg_linkedin -> paid_media_model + the campaigns block
    "raw_snowflake.reddit_ads_apac_all",       # -> stg_reddit -> paid_media_model
]
WATERMARK_OBJECT = "_freshness.json"

ALL_MARKETS = ["ANZ", "ASEAN", "SAARC", "RIG", "KR", "JP", "GCR"]


def jval(v):
    """JSON-safe value: dates -> ISO strings, NaN -> None (BQ returns native types)."""
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def ymd(v):
    """Date as 'YYYY-MM-DD' (the dashboard slices these for axis labels)."""
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()[:10]
    s = str(v)
    return s[:10] if s else None


def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def main():
    bq = bigquery.Client(project=PROJECT)

    # --- Freshness gate: cheap metadata probe; skip the rebuild unless an upstream
    # raw mirror advanced. Reading __TABLES__.last_modified is metadata-only.
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

    # Read the BigQuery views (client_cloudflare/sql) to assemble the payload.
    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    pm  = rows(bq, f"SELECT * FROM {t('paid_media_model')}")
    pac = rows(bq, f"SELECT * FROM {t('pacing_model')}")
    bc  = rows(bq, f"SELECT * FROM {t('benchmarks_channel')}")
    bm  = rows(bq, f"SELECT * FROM {t('benchmarks_market')}")
    lw  = rows(bq, f"SELECT * FROM {t('li_weekly_targets')} ORDER BY WEEK_START")
    cre = rows(bq, f"SELECT * FROM {t('paid_creatives_model')}")

    # Window over the paid rows (min/max date + inclusive day count).
    pdates = sorted(d for d in (ymd(r.get("DATE")) for r in pm) if d)
    if pdates:
        d0 = datetime.date.fromisoformat(pdates[0])
        d1 = datetime.date.fromisoformat(pdates[-1])
        window = {"start": pdates[0], "end": pdates[-1], "days": (d1 - d0).days + 1}
    else:
        window = {"start": None, "end": None, "days": 0}

    paid_media = {
        "row_count": len(pm),
        "window": window,
        "all_markets": ALL_MARKETS,
        "rows": [{
            "channel":           r.get("CHANNEL"),
            "date":              ymd(r.get("DATE")),
            "week_start":        ymd(r.get("WEEK_START")),
            "market":            r.get("MARKET"),
            "imps":              jval(r.get("IMPS")),
            "clicks":            jval(r.get("CLICKS")),
            "spend_usd":         jval(r.get("SPEND_USD")),
            "leads":             jval(r.get("LEADS")),
            "form_opens":        jval(r.get("FORM_OPENS")),
            "link_clicks":       jval(r.get("LINK_CLICKS")),
            "action_clicks":     jval(r.get("ACTION_CLICKS")),
            "video_starts":      jval(r.get("VIDEO_STARTS")),
            "video_completions": jval(r.get("VIDEO_COMPLETIONS")),
            "spend_jpy":         jval(r.get("SPEND_JPY")),
            "fx_usd_jpy":        jval(r.get("FX_USD_JPY")),
        } for r in pm],
        "creatives": [{
            "channel":   r.get("CHANNEL"),
            "market":    r.get("MARKET"),
            "creative":  r.get("CREATIVE"),
            "imps":      jval(r.get("IMPS")),
            "clicks":    jval(r.get("CLICKS")),
            "spend_usd": jval(r.get("SPEND_USD")),
            "leads":     jval(r.get("LEADS")),
        } for r in cre],
        "benchmarks":        {r["CHANNEL"]: {"ctr": jval(r["CTR"]), "cpm": jval(r["CPM"]), "cpc": jval(r["CPC"])} for r in bc},
        "benchmarks_market": {r["MARKET"]:  {"ctr": jval(r["CTR"]), "cpm": jval(r["CPM"]), "cpc": jval(r["CPC"])} for r in bm},
        "li_weekly": [{
            "week":       r.get("WEEK"),
            "period":     r.get("PERIOD"),
            "week_start": ymd(r.get("WEEK_START")),
            "target":     jval(r.get("TARGET")),
            "cum_target": jval(r.get("CUM_TARGET")),
        } for r in lw],
    }

    # Pacing: pass every pacing_model column straight through (dates -> ISO).
    pacing_payload = {
        "row_count": len(pac),
        "rows": [{k: jval(v) for k, v in r.items()} for r in pac],
    }

    # --- Extra single-campaign LinkedIn dashboards from the SHARED raw layer.
    # raw_snowflake.linkedin_ads_apac is already in BigQuery (snowflake_data_pull),
    # so read it directly. EDA-confirmed names: DAY (daily grain), IMPRESSIONS, CLICKS,
    # COSTS (USD), LEADS (FLOAT64), LEAD_FORM_OPENS (FLOAT64, null for these AWR-CONS groups).
    CAMPAIGN_GROUPS = {
        "peyc":        ("ANZ PEYC",    "CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-PEYC"),
        "cf1_india":   ("CF1 India",   "CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_CF1-Integrated"),
        "coles_hyper": ("Coles Hyper", "CLOUD_ACQ_2026-Q2_MDS_LINKEDIN_GENERAL_SI_APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_Hyper_COLES"),
    }
    groups_sql = ",".join(f"'{g}'" for _, g in CAMPAIGN_GROUPS.values())
    li_sql = f"""
      SELECT
        DAY                                       AS DATE,
        CAMPAIGN_GROUP_NAME,
        CAMPAIGN_NAME,
        SUM(IMPRESSIONS)                          AS IMPS,
        SUM(CLICKS)                               AS CLICKS,
        SUM(COSTS)                                AS SPEND,
        SUM(IFNULL(LEADS,0))                      AS LEADS,
        SUM(IFNULL(LEAD_FORM_OPENS,0))            AS FORM_OPENS
      FROM `{PROJECT}.raw_snowflake.linkedin_ads_apac`
      WHERE CAMPAIGN_GROUP_NAME IN ({groups_sql})
      GROUP BY DAY, CAMPAIGN_GROUP_NAME, CAMPAIGN_NAME
      ORDER BY DAY
    """
    li_rows = rows(bq, li_sql)
    campaigns = {}
    for key, (label, group) in CAMPAIGN_GROUPS.items():
        grp = [r for r in li_rows if r.get("CAMPAIGN_GROUP_NAME") == group]
        dmap = {}
        for r in grp:
            d = ymd(r.get("DATE"))
            if not d:
                continue
            o = dmap.setdefault(d, {"date": d, "imps": 0, "clicks": 0, "spend": 0.0, "leads": 0, "form_opens": 0})
            o["imps"]       += int(jval(r.get("IMPS")) or 0)
            o["clicks"]     += int(jval(r.get("CLICKS")) or 0)
            o["spend"]      += float(jval(r.get("SPEND")) or 0)
            o["leads"]      += int(jval(r.get("LEADS")) or 0)
            o["form_opens"] += int(jval(r.get("FORM_OPENS")) or 0)
        daily = [dmap[d] for d in sorted(dmap)]
        keys = ("imps", "clicks", "spend", "leads", "form_opens")
        tot = {k: sum(x[k] for x in daily) for k in keys} if daily else {k: 0 for k in keys}
        cmap = {}
        for r in grp:
            nm = r.get("CAMPAIGN_NAME") or "(unnamed)"
            o = cmap.setdefault(nm, {"campaign": nm, "imps": 0, "clicks": 0, "spend": 0.0, "leads": 0})
            o["imps"]   += int(jval(r.get("IMPS")) or 0)
            o["clicks"] += int(jval(r.get("CLICKS")) or 0)
            o["spend"]  += float(jval(r.get("SPEND")) or 0)
            o["leads"]  += int(jval(r.get("LEADS")) or 0)
        dts = [x["date"] for x in daily]
        window = ({"start": dts[0], "end": dts[-1],
                   "days": (datetime.date.fromisoformat(dts[-1]) - datetime.date.fromisoformat(dts[0])).days + 1}
                  if dts else {"start": None, "end": None, "days": 0})
        campaigns[key] = {
            "label": label, "campaign_group": group, "window": window,
            "totals": tot, "daily": daily,
            "by_campaign": sorted(cmap.values(), key=lambda x: x["spend"], reverse=True),
        }

    # last_updated = when THIS build ran; data_through = the newest upstream mirror
    # last_modified (UTC). The dashboard shows both so "fresh build" and "fresh data"
    # are never conflated.
    _dt_vals = [v for v in observed.values() if v]
    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max(_dt_vals).strftime("%Y-%m-%dT%H:%M:%SZ") if _dt_vals else None),
        "paid_media": paid_media,
        "pacing": pacing_payload,
        "campaigns": campaigns,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env, default=_json_default), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | paid {len(pm)} rows, pacing {len(pac)} rows, creatives {len(cre)} rows")

    # Record the watermark ONLY after a successful upload, so a failed upload
    # leaves the old watermark in place and simply retries on the next tick.
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"watermark updated -> gs://{BUCKET}/{WATERMARK_OBJECT} | data_through={env['data_through']}")
    print(f"  linkedin single-campaign rows: {len(li_rows)} total across {len(CAMPAIGN_GROUPS)} groups")
    for key, c in campaigns.items():
        tt, w = c["totals"], c["window"]
        print(f"    {key:12s} {c['label']:12s} days={w['days']:>3} daily={len(c['daily']):>3} "
              f"campaigns={len(c['by_campaign']):>2} imps={tt['imps']:>9} clicks={tt['clicks']:>6} "
              f"spend=${tt['spend']:>11.2f} leads={tt['leads']:>4} form_opens={tt['form_opens']:>4}")


if __name__ == "__main__":
    main()
