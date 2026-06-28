"""Geocon export job (stage 2) — Gateway Braddon Meta paid media.

REBUILT 2026-06 around a single fact table. Instead of many server-side rollup views, this job
ships ONE compact per-(date x campaign x adset x ad) fact array (`rows`) plus the flight/pacing
context, the numeric benchmarks, and the raw targets. The dashboard rolls EVERYTHING up
client-side (KPIs, by-campaign / by-stage / by-creative, the daily trend, the vs-benchmark delta
table, the segment breakdown) filtered by the chosen date range — which is what makes the
date-range filter and the CSV "export all data" exact and free.

Reads BigQuery views client_geocon.{fact, targets, budget}. The raw layer is raw_windsor.perf_meta
(Windsor-sourced, self-refreshing) — NOT Snowflake; there is no stage-1 loader to run here.
"""
import os, json, datetime
from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when the upstream raw
# table this job reads has advanced. The raw layer IS raw_windsor.perf_meta. GATING_TABLES is the
# "dataset.table" id probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
WINDSOR_TABLES = ["raw_windsor.perf_meta"]
GATING_TABLES = WINDSOR_TABLES
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
CLIENT  = "geocon"
DATASET     = f"client_{CLIENT}"                    # client_geocon
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-geocon-dash
DATA_OBJECT = f"{CLIENT}.json"                      # geocon.json

# Flight identity (the budget seed has the dates; this is the campaign_key to read).
FLIGHT_KEY = "GATEWAY"


def iso(v):
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return str(v)


def num(v):
    if v is None: return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def build_env(bq, observed):
    """Read the views and assemble the JSON the dashboard consumes. Pure (no upload), so a dev
    harness can dump it to disk without touching the live bucket. `observed` is the freshness
    probe result (used for meta.data_through)."""
    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    fact = rows(bq, f"SELECT * FROM {t('fact')} ORDER BY date, campaign_name, adset_name, ad_name")
    tgt  = rows(bq, f"SELECT * FROM {t('targets')}")
    bud  = rows(bq, f"SELECT * FROM {t('budget')} WHERE campaign_key = '{FLIGHT_KEY}' LIMIT 1")

    # --- targets: flat {key: {value, status}}; value parsed to float where possible (dates stay str)
    def tgt_value(raw):
        f = num(raw)
        return f if f is not None else raw
    targets = {r["key"]: {"value": tgt_value(r["value"]), "status": r["status"]} for r in tgt}

    def bnum(k):
        return num((targets.get(k) or {}).get("value"))

    # numeric benchmarks the UI compares actuals against (the vs-benchmark delta table reads these)
    benchmarks = {
        "cpl":          bnum("cpl_target_aud"),
        "cpl_stretch":  bnum("cpl_stretch_aud"),
        "ctr":          bnum("ctr_target"),
        "cpm":          bnum("cpm_target_aud"),
        "cpc":          bnum("cpc_target_aud"),
        "cost_per_lpv": bnum("cost_per_lpv_target_aud"),
        "lead_target":  bnum("monthly_lead_target"),
        "qualified_lead_target": bnum("qualified_lead_target"),
        "daily_pace":   bnum("daily_pace_aud"),
        "flight_budget": bnum("flight_budget_aud"),
    }

    # --- flight / pacing (flight-window based; independent of the dashboard's date filter) -------
    b = bud[0] if bud else {}
    fstart = b.get("flight_start")
    fend   = b.get("flight_end")
    budget = num(b.get("budget_aud")) or benchmarks["flight_budget"]
    today  = datetime.datetime.now(datetime.timezone.utc).date()
    spend_total = sum(num(r["spend"]) or 0 for r in fact)
    leads_total = sum(int(r["leads"] or 0) for r in fact)

    days_total = (fend - fstart).days + 1 if (fstart and fend) else None
    days_elapsed = None
    if fstart:
        days_elapsed = (today - fstart).days + 1
        if days_total:
            days_elapsed = max(0, min(days_elapsed, days_total))
        else:
            days_elapsed = max(0, days_elapsed)
    daily_pace = benchmarks["daily_pace"] or (budget / days_total if (budget and days_total) else None)
    pace_expected = (daily_pace * days_elapsed) if (daily_pace and days_elapsed) else None
    projected_spend = (spend_total / days_elapsed * days_total) if (days_elapsed and days_total) else None

    dates = [r["date"] for r in fact if r.get("date")]
    flight = {
        "start": iso(fstart), "end": iso(fend),
        "budget": budget, "days_total": days_total, "days_elapsed": days_elapsed,
        "daily_pace": daily_pace, "pace_expected": pace_expected,
        "projected_spend": projected_spend, "spend_to_date": round(spend_total, 2),
        "leads_to_date": leads_total,
    }

    env = {
        "meta": {
            "client": CLIENT,
            "title": "Gateway Braddon",
            "currency": (fact[0].get("currency") if fact else None) or "AUD",
            "lead_source_label": "Meta-reported",
            "channel": "Meta (Facebook + Instagram)",
            "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_through": (lambda sf: max(sf).strftime("%Y-%m-%dT%H:%M:%SZ") if sf else None)(
                [observed[k] for k in WINDSOR_TABLES if observed.get(k)]),
            "date_min": iso(min(dates)) if dates else None,
            "date_max": iso(max(dates)) if dates else None,
            "row_count": len(fact),
        },
        "flight": flight,
        "benchmarks": benchmarks,
        "targets": targets,
        # The single fact table — one row per (date x campaign x adset x ad). The dashboard rolls
        # up everything from this, filtered by the date range. Ratios are recomputed client-side.
        "rows": [{
            "date": iso(r["date"]),
            "campaign_id": r.get("campaign_id"), "campaign": r.get("campaign_name"),
            "adset_id": r.get("adset_id"), "adset": r.get("adset_name"),
            "ad_id": r.get("ad_id"), "ad": r.get("ad_name"),
            "stage": r.get("funnel_stage") or "Other",
            "creative_id": r.get("creative_id"), "creative_title": r.get("creative_title"),
            "creative_body": r.get("creative_body"), "creative_thumbnail_url": r.get("creative_thumbnail_url"),
            "destination_url": r.get("destination_url"),
            "spend": num(r["spend"]), "impressions": num(r["impressions"]), "reach": num(r["reach"]),
            "clicks": num(r["clicks"]), "link_clicks": num(r["link_clicks"]),
            "lpv": num(r["landing_page_views"]), "leads": num(r["leads"]),
            "video_3s_views": num(r.get("video_3s_views")), "video_completes": num(r.get("video_completes")),
        } for r in fact],
    }
    summary = (f"{len(fact)} fact rows, {leads_total} Meta-reported leads, "
               f"${round(spend_total,2)} spend ({env['meta']['date_min']}..{env['meta']['date_max']})")
    return env, summary


def main():
    bq = bigquery.Client(project=PROJECT)

    # --- Freshness gate: cheap metadata probe; skip the rebuild unless the upstream advanced. ---
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

    env, summary = build_env(bq, observed)
    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    # Watermark only after a successful upload (upload first, watermark second).
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {summary}")


if __name__ == "__main__":
    main()
