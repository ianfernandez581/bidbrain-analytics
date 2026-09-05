"""Sophiie AI export job (stage 2) - The Trade Desk programmatic display, AU.

Sophiie AI (sophiie.ai) sells an AI receptionist / back-office product to Australian trades and
service businesses. The campaign is ONE Trade Desk display campaign
(SOPHIIE_2026-Q3_TTD_AU_DISPLAY_PROSPECTING, advertiser gjcl0pp) across three prospecting audience
tiers plus a retargeting ad group, and it is judged on the platform's own KPI ladder:
    primary   CPA   A$150  (custom CPA, conversion source "Sign up")
    secondary CPC   A$3.00
    tertiary  CTR   0.15%

Single-fact-table architecture, same as every other lean client here: this job ships ONE compact
per-(date x campaign x ad group x creative) fact array (`rows`) plus the flight/pacing context, the
numeric benchmarks and the raw targets. The dashboard rolls EVERYTHING up client-side (KPIs,
by-stage / by-tier / by-creative, the daily trend, the vs-target delta table) filtered by the chosen
date range - which is what makes the date-range filter and the CSV "export all data" exact and free.

Reads BigQuery views client_sophiie.{fact, targets, budget}. The raw layer is
raw_windsor.perf_the_trade_desk (Windsor TTD connector, self-refreshing via the shared
windsor-tradedesk-ingest job) - NOT Snowflake; there is no stage-1 loader to run here.
"""
import os, json, datetime
from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see md/AGENTS.md "Freshness contract"): rebuild only when the upstream raw table
# this job reads has advanced. The raw layer IS raw_windsor.perf_the_trade_desk. GATING_TABLES is
# the "dataset.table" id probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
WINDSOR_TABLES = ["raw_windsor.perf_the_trade_desk"]
GATING_TABLES = WINDSOR_TABLES
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
CLIENT  = "sophiie"
DATASET     = f"client_{CLIENT}"                    # client_sophiie
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-sophiie-dash
DATA_OBJECT = f"{CLIENT}.json"                      # sophiie.json

# Flight identity (the budget seed has the dates; this is the campaign_key to read).
FLIGHT_KEY = "SOPHIIE"


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


def audit(fact):
    """Print the two things that can go silently wrong on this client, every run.

    1. FUNNEL STAGE. sql/01 maps the ad-group name's trailing stage token (AWR / CONSID / CONV) and
       sends anything else to 'Unclassified' rather than defaulting it to a real value - so a rename
       in The Trade Desk shows up as a named warning here and as a visible chip on the dashboard,
       instead of quietly filing a retargeting ad group under Awareness.
    2. CONVERSION SLOTS. Windsor reports TTD conversions as anonymous numbered slots and this
       campaign has TWO conversion data sources attached ("Sign up +1"), so the sign-up total is a
       sum over slots we cannot individually name. Printing which slots actually fire is the only
       way to notice a second action arriving in a different slot - at which point it must be SPLIT
       OUT in sql/01, never left folded into "sign-ups".
    """
    unclassified = sorted({r.get("ad_group_name") for r in fact
                           if (r.get("funnel_stage") or "") == "Unclassified"})
    if unclassified:
        print("WARNING: ad groups with no recognised stage token (-> 'Unclassified'): "
              + ", ".join(str(a) for a in unclassified)
              + " | add the code to the CASE in sql/01_stg_ttd.sql")
    slots = sorted({s for r in fact for s in str(r.get("conv_slots") or "").split(",") if s})
    if slots:
        print(f"conversion slots reporting ({len(slots)}): " + ", ".join(slots))
        if len(slots) > 1:
            print("WARNING: more than one TTD conversion slot is populated. Sign-ups are currently "
                  "the SUM of every slot. Identify each slot in The Trade Desk and split any "
                  "non-sign-up action out in sql/01_stg_ttd.sql before reporting it as sign-ups.")
    else:
        print("conversion slots reporting: none yet (0 attributed sign-ups so far)")


def build_env(bq, observed):
    """Read the views and assemble the JSON the dashboard consumes. Pure (no upload), so a dev
    harness can dump it to disk without touching the live bucket. `observed` is the freshness probe
    result (used for meta.data_through)."""
    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    fact = rows(bq, f"SELECT * FROM {t('fact')} ORDER BY date, ad_group_name, creative_name")
    tgt  = rows(bq, f"SELECT * FROM {t('targets')}")
    bud  = rows(bq, f"SELECT * FROM {t('budget')} WHERE campaign_key = '{FLIGHT_KEY}' LIMIT 1")
    audit(fact)

    # --- targets: flat {key: {value, status}}; value parsed to float where possible (dates stay str)
    def tgt_value(raw):
        f = num(raw)
        return f if f is not None else raw
    targets = {r["key"]: {"value": tgt_value(r["value"]), "status": r["status"]} for r in tgt}

    def bnum(k):
        return num((targets.get(k) or {}).get("value"))

    # Numeric benchmarks the UI compares actuals against (the vs-target delta table reads these).
    # cpa / cpc / ctr are the campaign's OWN KPI targets in The Trade Desk (status HARD in the seed).
    # cpm / impressions_target / signups_target are DERIVED from those - the UI must label them, or a
    # red delta accuses the campaign of missing a KPI nobody agreed to (the caltex rule).
    benchmarks = {
        "cpa":                bnum("cpa_target_aud"),
        "cpc":                bnum("cpc_target_aud"),
        "ctr":                bnum("ctr_target"),
        "cpm":                bnum("cpm_target_aud"),
        "impressions_target": bnum("impressions_target"),
        "signups_target":     bnum("signups_target"),
        "daily_pace":         bnum("daily_pace_aud"),
        "flight_budget":      bnum("flight_budget_aud"),
    }

    # --- flight / pacing (flight-window based; independent of the dashboard's date filter) -------
    b = bud[0] if bud else {}
    fstart = b.get("flight_start")
    fend   = b.get("flight_end")
    budget = num(b.get("budget_aud")) or benchmarks["flight_budget"]
    today  = datetime.datetime.now(datetime.timezone.utc).date()
    spend_total = sum(num(r["spend"]) or 0 for r in fact)
    imps_total  = sum(int(r["impressions"] or 0) for r in fact)
    clicks_total = sum(int(r["clicks"] or 0) for r in fact)
    signups_total = sum((num(r["post_view_conv"]) or 0) + (num(r["post_click_conv"]) or 0)
                        for r in fact)

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

    # PROJECTION RUNS ON THE DELIVERING WINDOW, NOT THE ELAPSED FLIGHT (md/AGENTS.md, "PACE AGAINST
    # THE BUDGET THAT CAN ACTUALLY SPEND"; reference impl clients/client_geocon/job/main.py).
    #
    # The seeded flight opens 2026-09-03 but the campaign's first delivery was 2026-09-04. Averaging
    # A$337 over 3 elapsed days projected A$3,487 of a A$10,000 flight - a 65% underspend warning
    # about a campaign that is in fact running at a rate which lands on budget. A projection that
    # contradicts the campaign's own run rate is worse than none: it argues for topping up a line
    # that needs nothing.
    #
    # `run_days` is measured across the REPORTED window (first..last delivery inclusive), NOT
    # `today - first_delivery` as geocon does. That difference matters here because The Trade Desk
    # refuses same-day data, so this feed is structurally a day behind: counting to `today` would
    # divide one day of spend across two days and halve the rate every single run.
    dates_with_delivery = sorted({r["date"] for r in fact
                                  if r.get("date") and (num(r.get("spend")) or 0) > 0})
    first_delivery = dates_with_delivery[0] if dates_with_delivery else None
    last_delivery = dates_with_delivery[-1] if dates_with_delivery else None
    run_days = ((last_delivery - first_delivery).days + 1) if first_delivery else None
    days_remaining = max(0, days_total - days_elapsed) if (days_total and days_elapsed) else None
    if run_days and days_remaining is not None and days_elapsed and run_days < days_elapsed:
        # Late start (or a gap): project the OBSERVED daily rate across the days still to run.
        projected_spend = spend_total + (spend_total / run_days) * days_remaining
        pace_basis = "delivering_window"
    else:
        projected_spend = (spend_total / days_elapsed * days_total) if (days_elapsed and days_total) else None
        pace_basis = "elapsed_flight"

    dates = [r["date"] for r in fact if r.get("date")]
    flight = {
        "start": iso(fstart), "end": iso(fend),
        "budget": budget, "days_total": days_total, "days_elapsed": days_elapsed,
        "daily_pace": daily_pace, "pace_expected": pace_expected,
        "projected_spend": projected_spend, "spend_to_date": round(spend_total, 2),
        # What the projection was computed FROM, so the dashboard can say so on screen instead of
        # leaving the reader to assume it is the elapsed flight (md/AGENTS.md: name the basis).
        "pace_basis": pace_basis,
        "delivering_days": run_days,
        "first_delivery": iso(first_delivery),
        "last_delivery": iso(last_delivery),
        "impressions_to_date": imps_total,
        "clicks_to_date": clicks_total,
        "signups_to_date": round(signups_total, 1),
        # Flight-level viewability sample. Kept as the two components (never a pre-divided rate) so
        # any date sub-range stays exact; None-vs-0 is meaningful - TTD measures only a SAMPLE, and
        # both sides are NULL until viewability measurement is enabled on the ad groups.
        "vw_viewed_to_date": round(sum(num(r.get("sampled_viewed")) or 0 for r in fact), 0),
        "vw_tracked_to_date": round(sum(num(r.get("sampled_tracked")) or 0 for r in fact), 0),
    }

    env = {
        "meta": {
            "client": CLIENT,
            "title": "Sophiie AI",
            "currency": (fact[0].get("currency") if fact else None) or "AUD",
            # Badge under the "Sign-ups" KPI. Names WHAT is counted, not just the platform: these are
            # The Trade Desk's own attributed conversions on the campaign's "Sign up" conversion
            # source, post-click plus post-view. If a second tracker starts reporting (the job WARNs
            # when it does) this label and the dashboard copy must be re-checked together.
            "action_source_label": "Sign up · TTD-attributed",
            "channel": "The Trade Desk (programmatic display)",
            "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_through": (lambda sf: max(sf).strftime("%Y-%m-%dT%H:%M:%SZ") if sf else None)(
                [observed[k] for k in WINDSOR_TABLES if observed.get(k)]),
            "date_min": iso(min(dates)) if dates else None,
            "date_max": iso(max(dates)) if dates else None,
            "row_count": len(fact),
            # Which anonymous TTD conversion slots are actually reporting. Surfaced so the sign-up
            # caveat on screen can be specific rather than generic.
            "conversion_slots": sorted({s for r in fact
                                        for s in str(r.get("conv_slots") or "").split(",") if s}),
        },
        "flight": flight,
        "benchmarks": benchmarks,
        "targets": targets,
        # The single fact table - one row per (date x campaign x ad group x creative). The dashboard
        # rolls up everything from this, filtered by the date range. Ratios recomputed client-side.
        "rows": [{
            "date": iso(r["date"]),
            "campaign_id": r.get("campaign_id"), "campaign": r.get("campaign_name"),
            "ad_group_id": r.get("ad_group_id"), "ad_group": r.get("ad_group_name"),
            "tier": r.get("tier"), "market": r.get("market"),
            "creative_id": r.get("creative_id"), "creative": r.get("creative_name"),
            "ad_format": r.get("ad_format"),
            "stage": r.get("funnel_stage") or "Unclassified",
            "spend": num(r["spend"]), "impressions": num(r["impressions"]), "clicks": num(r["clicks"]),
            "video_starts": num(r.get("video_starts")), "video_25": num(r.get("video_25")),
            "video_50": num(r.get("video_50")), "video_75": num(r.get("video_75")),
            "video_completes": num(r.get("video_completes")),
            # Sign-ups, split by attribution path. Summed to one "sign-ups" figure on screen; kept
            # apart here so post-view and post-click can be told apart without a re-export.
            "pv_conv": num(r.get("post_view_conv")), "pc_conv": num(r.get("post_click_conv")),
            # Viewability sample. None (not 0) when TTD is not measuring it, so the UI can say
            # "not measured" instead of claiming 0% viewable.
            "vw_viewed": num(r.get("sampled_viewed")), "vw_tracked": num(r.get("sampled_tracked")),
        } for r in fact],
    }
    summary = (f"{len(fact)} fact rows, {imps_total:,} impressions, {clicks_total:,} clicks, "
               f"{round(signups_total,1)} sign-ups, "
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
    # EMPTY-FACT GUARD (the caltex pattern): until the Sophiie AI advertiser (gjcl0pp) is granted to
    # the Windsor Trade Desk connector, the fact view is empty. Never upload an empty sophiie.json -
    # the dash service prefers the bucket file over its baked-in sample payload, so an empty upload
    # would replace the labelled placeholder with a blank dashboard. Applies even under
    # FORCE_REBUILD=1 (this is about EMPTY DATA, not freshness). Exit 0 (and skip the watermark) so
    # the */10 tick keeps retrying and the FIRST rebuild after real rows land goes live automatically.
    if not env["rows"]:
        print("fact is EMPTY (advertiser gjcl0pp not in raw_windsor.perf_the_trade_desk yet) -> "
              "NOT uploading; placeholder stays live. Grant the advertiser at "
              "https://onboard.windsor.ai?datasource=tradedesk to go live.")
        return
    bkt = storage.Client(project=PROJECT).bucket(BUCKET)
    bkt.blob(DATA_OBJECT).upload_from_string(json.dumps(env), content_type="application/json")
    # Watermark only after a successful upload (upload first, watermark second).
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {summary}")


if __name__ == "__main__":
    main()
