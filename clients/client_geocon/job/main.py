import os, json, datetime
from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when the
# upstream raw table this job reads has advanced. The raw layer IS raw_windsor.perf_meta
# (Windsor-sourced, self-refreshing) -- NOT Snowflake. GATING_TABLES is the "dataset.table"
# id in this project, probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
WINDSOR_TABLES = [
    "raw_windsor.perf_meta",
]
GATING_TABLES = WINDSOR_TABLES
WATERMARK_OBJECT = "_freshness.json"

# --- Project-wide constants ---------------------------------------------------
# One GCP project -> identical for EVERY client, so hardcoded here.
PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
# Copy this folder for a new client and change ONLY this (e.g. "acme").
# Dataset / bucket / output object all follow from it via the naming convention.
CLIENT = "geocon"

DATASET     = f"client_{CLIENT}"                    # client_geocon
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-geocon-dash
DATA_OBJECT = f"{CLIENT}.json"                      # geocon.json

# This job reads BigQuery views that filter raw_windsor.perf_meta to Geocon's campaigns
# (see client_geocon/sql/). The Windsor connector refreshes the raw table itself; there is
# no stage-1 loader to run here.


def iso(v):
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return str(v)


def num(v):
    """BigQuery returns NUMERIC/FLOAT64 as Decimal/float; coerce to JSON-safe float (None-safe)."""
    if v is None: return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def main():
    bq = bigquery.Client(project=PROJECT)

    # --- Freshness gate: cheap metadata probe; skip the rebuild unless the upstream
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
    ov  = rows(bq, f"SELECT * FROM {t('overview')}")[0]
    cmp = rows(bq, f"SELECT * FROM {t('by_campaign')}")
    ad  = rows(bq, f"SELECT * FROM {t('by_ad')}")
    dt  = rows(bq, f"SELECT * FROM {t('daily_trend')}")
    ft  = rows(bq, f"SELECT * FROM {t('fatigue')}")
    st  = rows(bq, f"SELECT * FROM {t('by_stage')}")
    tgt = rows(bq, f"SELECT * FROM {t('targets')}")

    # targets as a flat dict {key: {value, status}} so the UI can mark PENDING ones.
    # value is STRING in the seed (numbers + dates); parse to float where possible, keep
    # the raw string for dates (flight_start/flight_end).
    def tgt_value(raw):
        f = num(raw)
        return f if f is not None else raw
    targets = {r["key"]: {"value": tgt_value(r["value"]), "status": r["status"]} for r in tgt}

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (lambda sf: max(sf).strftime("%Y-%m-%dT%H:%M:%SZ") if sf else None)(
            [observed[k] for k in WINDSOR_TABLES if observed.get(k)]),
        "client": CLIENT,
        "currency": ov.get("currency") or "AUD",
        "lead_source_label": "Meta-reported",  # honest labelling; CRM/quality feed can layer in later
        "overview": {
            "spend":          num(ov.get("spend")),
            "budget":         num(ov.get("budget_aud")),
            "pace_expected":  num(ov.get("pace_expected")),
            "projected_spend":num(ov.get("projected_spend")),
            "leads":          num(ov.get("leads")),
            "cpl":            num(ov.get("cpl")),
            "reach":          num(ov.get("reach")),
            "impressions":    num(ov.get("impressions")),
            "clicks":         num(ov.get("clicks")),
            "link_clicks":    num(ov.get("link_clicks")),
            "ctr":            num(ov.get("ctr")),
            "cpm":            num(ov.get("cpm")),
            "cpc":            num(ov.get("cpc")),
            "cost_per_lpv":   num(ov.get("cost_per_lpv")),
            "frequency":      num(ov.get("frequency")),
            "landing_page_views": num(ov.get("landing_page_views")),
            "days_elapsed":   ov.get("days_elapsed"),
            "days_total":     ov.get("days_total"),
            "flight_start":   iso(ov.get("flight_start")),
            "flight_end":     iso(ov.get("flight_end")),
            "date_start":     iso(ov.get("date_start")),
            "date_end":       iso(ov.get("date_end")),
        },
        "by_campaign": [{
            "campaign": r["campaign_name"], "funnel_stage": r["funnel_stage"],
            "spend": num(r["spend"]), "impressions": num(r["impressions"]), "reach": num(r["reach"]),
            "frequency": num(r["frequency"]), "clicks": num(r["clicks"]),
            "link_clicks": num(r["link_clicks"]), "ctr": num(r["ctr"]),
            "cpm": num(r["cpm"]), "cpc": num(r["cpc"]),
            "lpv": num(r["landing_page_views"]), "cost_per_lpv": num(r["cost_per_lpv"]),
            "leads": num(r["leads"]), "cpl": num(r["cpl"]),
            "video_3s_views": num(r.get("video_3s_views")), "video_completes": num(r.get("video_completes")),
        } for r in cmp],
        "by_ad": [{
            "ad": r["ad_name"], "adset": r["adset_name"], "campaign": r["campaign_name"],
            "funnel_stage": r["funnel_stage"],
            "creative_id": r.get("creative_id"), "creative_title": r.get("creative_title"),
            "creative_body": r.get("creative_body"), "creative_thumbnail_url": r.get("creative_thumbnail_url"),
            "spend": num(r["spend"]), "impressions": num(r["impressions"]), "reach": num(r["reach"]),
            "frequency": num(r["frequency"]), "clicks": num(r["clicks"]),
            "link_clicks": num(r["link_clicks"]), "ctr": num(r["ctr"]),
            "cpm": num(r["cpm"]), "cpc": num(r["cpc"]),
            "lpv": num(r["landing_page_views"]), "cost_per_lpv": num(r["cost_per_lpv"]),
            "leads": num(r["leads"]), "cpl": num(r["cpl"]),
            "video_3s_views": num(r.get("video_3s_views")), "video_completes": num(r.get("video_completes")),
        } for r in ad],
        "daily": [{
            "date": iso(r["date"]), "spend": num(r["spend"]), "leads": num(r["leads"]),
            "cpl": num(r["cpl"]), "cpl_7d": num(r["cpl_7d"]),
            "cum_leads": num(r["cum_leads"]), "cum_spend": num(r["cum_spend"]),
            "impressions": num(r["impressions"]), "link_clicks": num(r["link_clicks"]),
            "ctr": num(r["ctr"]), "cpm": num(r["cpm"]),
        } for r in dt],
        "fatigue": [{
            "campaign": r["campaign_name"], "adset": r["adset_name"], "ad": r["ad_name"],
            "week_start": iso(r["week_start"]), "impressions": num(r["impressions"]),
            "frequency": num(r["frequency"]), "ctr": num(r["ctr"]),
            "freq_wow": num(r["freq_wow"]), "ctr_wow": num(r["ctr_wow"]),
            "flag": r["flag"],
        } for r in ft],
        "by_stage": [{
            "funnel_stage": r["funnel_stage"], "spend": num(r["spend"]), "leads": num(r["leads"]),
            "spend_share": num(r["spend_share"]), "lead_share": num(r["lead_share"]),
            "cpl": num(r["cpl"]), "ctr": num(r["ctr"]), "cpm": num(r["cpm"]),
            "impressions": num(r["impressions"]), "link_clicks": num(r["link_clicks"]),
            "lpv": num(r["landing_page_views"]), "frequency": num(r["frequency"]),
        } for r in st],
        "targets": targets,
        # Optional CRM/quality feed (lead_source dimension). Renders only when present.
        # Today only Meta-reported leads exist; the structure is ready for a later CRM layer
        # without rework.
        "quality": None,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    # Record the watermark only after a successful upload (upload first, watermark
    # second), so a failed upload simply retries on the next tick.
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | "
          f"{env['overview']['leads']} Meta-reported leads, "
          f"${env['overview']['spend']} spend")


if __name__ == "__main__":
    main()