"""Caltex export job (stage 2) — Caltex Trade Desk programmatic display.

REWORKED 2026-07 from the Meta scaffold to The Trade Desk (advertiser 0lw3hp6, mixed
awareness + consideration display in QLD+WA). Same single-fact-table architecture: this job
ships ONE compact per-(date x campaign x ad group x creative) fact array (`rows`) plus the
flight/pacing context, the numeric benchmarks, and the raw targets. The dashboard rolls
EVERYTHING up client-side (KPIs, by-stage / by-tactic / by-creative, the daily trend, the
vs-benchmark delta table) filtered by the chosen date range — which is what makes the
date-range filter and the CSV "export all data" exact and free.

Reads BigQuery views client_caltex.{fact, targets, budget}. The raw layer is
raw_windsor.perf_the_trade_desk (Windsor TTD connector, self-refreshing via the
windsor-tradedesk-ingest job) — NOT Snowflake; there is no stage-1 loader to run here.
"""
import os, json, datetime
from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when the upstream raw
# table this job reads has advanced. The raw layer IS raw_windsor.perf_the_trade_desk.
# GATING_TABLES is the "dataset.table" id probed via BQ __TABLES__.last_modified; watermark = GCS
# sidecar.
WINDSOR_TABLES = ["raw_windsor.perf_the_trade_desk"]
GATING_TABLES = WINDSOR_TABLES
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
CLIENT  = "caltex"
DATASET     = f"client_{CLIENT}"                    # client_caltex
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-caltex-dash
DATA_OBJECT = f"{CLIENT}.json"                      # caltex.json

# Flight identity (the budget seed has the dates; this is the campaign_key to read).
FLIGHT_KEY = "CALTEX"


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
    fact = rows(bq, f"SELECT * FROM {t('fact')} ORDER BY date, ad_group_name, creative_name")
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
        "cpm":                bnum("cpm_target_aud"),
        "ctr":                bnum("ctr_target"),
        "cpc":                bnum("cpc_target_aud"),
        "impressions_target": bnum("impressions_target"),
        # the plan states impressions as a RANGE (low = the committed target, high = upside)
        "impressions_target_high": bnum("impressions_target_high"),
        "monthly_budget":     bnum("monthly_budget_aud"),
        "daily_pace":         bnum("daily_pace_aud"),
        "flight_budget":      bnum("flight_budget_aud"),
        # Committed in the media plan but NOT measurable from this feed as instrumented - shipped so
        # the UI can show the commitment and say why it has no actual, instead of hiding it:
        #   signups   -> needs the application-container tag (only a sitewide base pixel is live)
        #   viewability -> IAS/DoubleVerify data is not in the Windsor TTD feed at all
        "signups_target":     bnum("signups_target"),
        "viewability_target": bnum("viewability_target"),
    }

    # --- flight / pacing (flight-window based; independent of the dashboard's date filter) -------
    b = bud[0] if bud else {}
    fstart = b.get("flight_start")
    fend   = b.get("flight_end")
    budget = num(b.get("budget_aud")) or benchmarks["flight_budget"]
    today  = datetime.datetime.now(datetime.timezone.utc).date()
    spend_total = sum(num(r["spend"]) or 0 for r in fact)
    imps_total  = sum(int(r["impressions"] or 0) for r in fact)
    actions_total = sum((num(r["post_view_conv"]) or 0) + (num(r["post_click_conv"]) or 0) for r in fact)

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
        "impressions_to_date": imps_total,
        "actions_to_date": round(actions_total, 1),
    }

    env = {
        "meta": {
            "client": CLIENT,
            "title": "Caltex",
            "currency": (fact[0].get("currency") if fact else None) or "AUD",
            "action_source_label": "TTD pixel-attributed",
            "channel": "The Trade Desk (programmatic display)",
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
        # The single fact table — one row per (date x campaign x ad group x creative). The dashboard
        # rolls up everything from this, filtered by the date range. Ratios recomputed client-side.
        "rows": [{
            "date": iso(r["date"]),
            "campaign_id": r.get("campaign_id"), "campaign": r.get("campaign_name"),
            "ad_group_id": r.get("ad_group_id"), "ad_group": r.get("ad_group_name"),
            "tactic": r.get("tactic"), "market": r.get("market"),
            "creative_id": r.get("creative_id"), "creative": r.get("creative_name"),
            "ad_format": r.get("ad_format"),
            "stage": r.get("funnel_stage") or "Awareness",
            "spend": num(r["spend"]), "impressions": num(r["impressions"]), "clicks": num(r["clicks"]),
            "video_starts": num(r.get("video_starts")), "video_25": num(r.get("video_25")),
            "video_50": num(r.get("video_50")), "video_75": num(r.get("video_75")),
            "video_completes": num(r.get("video_completes")),
            "pv_conv": num(r.get("post_view_conv")), "pc_conv": num(r.get("post_click_conv")),
        } for r in fact],
    }
    summary = (f"{len(fact)} fact rows, {imps_total:,} impressions, "
               f"{round(actions_total,1)} attributed actions, "
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
    # EMPTY-FACT GUARD: until the Caltex advertiser (0lw3hp6) is granted to the Windsor TTD
    # connector, the fact view is empty. Never upload an empty caltex.json — the dash service
    # prefers the bucket file over its baked-in sample payload, so an empty upload would replace
    # the labelled placeholder with a blank dashboard. Applies even under FORCE_REBUILD=1 (this is
    # about EMPTY DATA, not freshness). Exit 0 (and skip the watermark) so the */10 tick keeps
    # retrying and the FIRST rebuild after real rows land goes live automatically.
    if not env["rows"]:
        print("fact is EMPTY (advertiser not in raw_windsor.perf_the_trade_desk yet) -> "
              "NOT uploading; placeholder stays live. Grant the advertiser in Windsor to go live.")
        return
    bkt = storage.Client(project=PROJECT).bucket(BUCKET)
    bkt.blob(DATA_OBJECT).upload_from_string(json.dumps(env), content_type="application/json")
    # Watermark only after a successful upload (upload first, watermark second).
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {summary}")


if __name__ == "__main__":
    main()
