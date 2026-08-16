"""Schneider Electric "Secure Power" — paid-media dashboard export job (Cloud Run job).

Stage 2 of the standard pattern: read the BigQuery views in client_schneidersecpwr/sql/ and write a
single schneidersecpwr.json to the private GCS bucket. The gated web app
(client_schneidersecpwr/dash) serves that JSON at /data.json.

This is a THREE-CAMPAIGN, paid-media-only dashboard, a lean sibling of client_schneiderlqai. It
reports the three Secure Power briefs that are deliberately OUT of client_schneider's scope because
they have separate stakeholders:

    ent_it          Enterprise IT Expansion      brief 1958   LinkedIn + Trade Desk, multi-region
    ind_edge        Industrial Edge / Prefab     brief 2463   LinkedIn + Trade Desk, AU/NZ (Wave 3)
    software_first  Software First EcoStruxure   brief 2305   LinkedIn + Trade Desk, AU/NZ

DELIVERY-ONLY: no media plan has been supplied for any of the three, so there are no impression /
click / lead targets and therefore NO pacing card - the dashboard reports delivered reach, clicks,
CTR and cost efficiency, plus each campaign's OBSERVED flight ("live since <first delivery>"). If a
signed plan ever lands, add it the repo-standard way (a committed data/media_plan.csv -> seed table
read here), exactly as client_schneiderlqai does - do not hardcode targets in this file.

There are no leads/conversions in the Salesforce sense here. LinkedIn's own on-platform LEAD-FORM
counts do come through (Industrial Edge runs Lead Generation ad sets) and are reported as a PAID
metric only; they are never a content-syndication lead total.

Read-only on BigQuery (SELECTs views, writes JSON to GCS). Reporting currency AUD.
"""
import os
import json
import datetime
from decimal import Decimal

from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (repo AGENTS.md "Freshness contract"): rebuild only when an upstream raw table this
# job reads has advanced. Probed via BQ __TABLES__.last_modified; watermark = GCS sidecar.
GATING_TABLES = [
    "raw_snowflake.linkedin_ads_apac",
    "raw_snowflake.tradedesk_apac_all",
]
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
CLIENT = "schneidersecpwr"
DATASET = f"client_{CLIENT}"
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"
DATA_OBJECT = f"{CLIENT}.json"
# STAFF-ONLY payload, written as a SEPARATE object. The Reports tab is for 100% Digital / the owning
# agency, never the client, so its ad-set targeting must not ride inside the client's data.json -
# hiding a tab in the browser does nothing about a payload the client can simply open. Served by the
# dash at /internal/reports.json and fetched only when a staff session opens the tab.
INTERNAL_OBJECT = f"{CLIENT}_internal.json"

# Campaign key -> display metadata. The keys MUST match the CASE arms in sql/01 + sql/02.
# Deliberately a code-level map, not a seed table: there are no targets to edit, so the only content
# is a label and a brief number. Order here is the dashboard's display order.
CAMPAIGN_META = [
    ("ent_it",         {"label": "Enterprise IT Expansion",    "brief": "1958"}),
    ("ind_edge",       {"label": "Industrial Edge / Prefab",   "brief": "2463"}),
    ("software_first", {"label": "Software First EcoStruxure", "brief": "2305"}),
]
CAMPAIGN_ORDER = {k: i for i, (k, _) in enumerate(CAMPAIGN_META)}

CHAN_LABEL = {"linkedin": "LinkedIn", "tradedesk": "The Trade Desk"}
# Fine markets first (AU/NZ), then the coarse regions, then anything unparsed - 'Unmapped' sorts last
# on purpose so a parsing regression shows up as a loud trailing chip instead of hiding mid-list.
MARKET_ORDER = {"Australia": 0, "New Zealand": 1, "ANZ": 2, "Pacific": 3,
                "India": 4, "MEA": 5, "South America": 6, "Unmapped": 9}
REGION_ORDER = {"Pacific": 0, "India": 1, "MEA": 2, "South America": 3, "Other": 9}


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
    delivery = rows(bq, "delivery", order_by="metric_date, campaign, platform, market")
    creative = rows(bq, "creative")
    # One row per LinkedIn ad set - the skeleton of the Reports tab's "Targeting Breakdown", plus the
    # hand-recorded audience columns seeded from targeting/adset_targeting.csv. Small (tens of rows)
    # and NOT date-scoped: the report describes how each ad set is SET UP, which is a whole-flight
    # fact, so it is emitted unfiltered and the dashboard's date picker is hidden on that tab.
    adsets = rows(bq, "linkedin_adsets", order_by="campaign, phase, geo, adset_name")

    # REFUSE TO PUBLISH AN EMPTY FACT. A scope regression (a renamed campaign that no token matches)
    # would otherwise silently overwrite a good JSON with an empty one and the dashboard would read as
    # "campaign stopped" rather than "the pipeline broke". Same guard as client_caltex.
    if not delivery:
        raise SystemExit(
            "ABORT: delivery view returned 0 rows - refusing to overwrite "
            f"gs://{BUCKET}/{DATA_OBJECT} with an empty fact. Check the campaign tokens in "
            "sql/01_stg_linkedin.sql + sql/02_stg_tradedesk.sql against the live campaign names.")

    # --- Vocabulary actually present in the data ------------------------------
    markets = sorted({r["market"] for r in delivery}, key=lambda m: (MARKET_ORDER.get(m, 7), m))
    regions = sorted({r["region"] for r in delivery}, key=lambda r: (REGION_ORDER.get(r, 5), r))
    live_platforms = {r["platform"] for r in delivery}
    channels = [{"key": k, "label": CHAN_LABEL.get(k, k)}
                for k in ["linkedin", "tradedesk"] if k in live_platforms]

    # --- Per-campaign rollup (drives the chips, the Campaigns tab and the flight captions) ----
    campaigns = []
    for key, meta in CAMPAIGN_META:
        crows = [r for r in delivery if r["campaign"] == key]
        if not crows:
            # Seeded but not delivering: emit it with zeros rather than dropping it, so a campaign
            # that stops shows as an explicit zero instead of quietly vanishing from the dashboard.
            campaigns.append({"key": key, "label": meta["label"], "brief": meta["brief"],
                              "markets": [], "platforms": [], "imps": 0, "clicks": 0,
                              "spend_aud": 0, "leads": None, "first_delivery": None,
                              "last_delivery": None})
            continue
        dates = [r["metric_date"] for r in crows if r["metric_date"]]
        lead_vals = [r["leads"] for r in crows if r["leads"] is not None]
        campaigns.append({
            "key": key, "label": meta["label"], "brief": meta["brief"],
            "markets": sorted({r["market"] for r in crows},
                              key=lambda m: (MARKET_ORDER.get(m, 7), m)),
            "platforms": sorted({r["platform"] for r in crows}),
            "imps": sum(r["imps"] or 0 for r in crows),
            "clicks": sum(r["clicks"] or 0 for r in crows),
            "spend_aud": num(sum(float(r["spend_aud"] or 0) for r in crows)),
            # NULL not 0 when no platform in this campaign reports lead forms, so the UI can hide it.
            "leads": (sum(lead_vals) if lead_vals else None),
            # No signed plan for any of the three -> the flight is OBSERVED, and the UI says
            # "live since" rather than implying a booked flight window.
            "first_delivery": ymd(min(dates)) if dates else None,
            "last_delivery": ymd(max(dates)) if dates else None,
        })
    campaigns.sort(key=lambda c: CAMPAIGN_ORDER.get(c["key"], 9))

    # --- Data window (for the date picker) ------------------------------------
    dates = [r["metric_date"] for r in delivery if r["metric_date"]]
    wstart, wend = (min(dates), max(dates)) if dates else (None, None)
    wdays = (wend - wstart).days + 1 if (wstart and wend) else None

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max([v for v in observed.values() if v]).strftime("%Y-%m-%dT%H:%M:%SZ")
                         if observed else None),
        "currency": "AUD",
        "client_label": "Schneider Electric - Secure Power",
        # No media plan for any of the three briefs; the UI keys off this to hide every pacing
        # affordance rather than drawing 0% against a zero target.
        "has_targets": False,
        "window": {"start": ymd(wstart), "end": ymd(wend), "days": wdays},
        "campaigns": campaigns,
        "markets": markets,
        "regions": regions,
        "channels": channels,
        "delivery": [{
            "campaign": r["campaign"], "platform": r["platform"], "date": ymd(r["metric_date"]),
            "market": r["market"], "region": r["region"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
            "leads": num(r["leads"]), "lead_form_opens": num(r["lead_form_opens"]),
        } for r in delivery],
        "creative": [{
            "campaign": r["campaign"], "platform": r["platform"], "market": r["market"],
            "concept": r["concept"], "format": r["creative_format"],
            "creative_name": r["creative_name"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in creative],
    }

    # --- STAFF-ONLY payload (separate object; see INTERNAL_OBJECT) -------------
    internal = {
        "last_updated": env["last_updated"],
        "window": env["window"],
        # LinkedIn ad-set setup for the Reports tab. `has_targeting` is false until the buyer fills
        # targeting/adset_targeting.csv in - the report then labels itself "not yet recorded" rather
        # than printing blanks that read as "no targeting applied".
        "adsets": [{
            "adset_id": r["adset_id"], "campaign": r["campaign"], "adset_name": r["adset_name"],
            "group_name": r["group_name"], "phase": r["phase"], "geo": r["geo"],
            "aliases": list(r["aliases"] or []),
            "first_delivery": ymd(r["first_delivery"]), "last_delivery": ymd(r["last_delivery"]),
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
            "leads": num(r["leads"]),
            "targeting_method": r["targeting_method"], "job_titles": r["job_titles"],
            "job_seniorities": r["job_seniorities"], "job_functions": r["job_functions"],
            "industries": r["industries"], "company_list": r["company_list"],
            "exclusions": r["exclusions"], "audience_size": r["audience_size"],
            "notes": r["notes"], "has_targeting": bool(r["has_targeting"]),
        } for r in adsets],
    }

    bucket = storage.Client(project=PROJECT).bucket(BUCKET)
    bucket.blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    bucket.blob(INTERNAL_OBJECT).upload_from_string(
        json.dumps(internal), content_type="application/json")
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    tot_imp = sum(r["imps"] or 0 for r in env["delivery"])
    tot_spend = sum(r["spend_aud"] or 0 for r in env["delivery"])
    per_camp = " | ".join(f"{c['label']}: {c['imps']:,.0f} imp / A${c['spend_aud']:,.0f}"
                          for c in campaigns)
    n_targeted = sum(1 for a in internal["adsets"] if a["has_targeting"])
    print(f"wrote gs://{BUCKET}/{INTERNAL_OBJECT} (staff-only) | {len(internal['adsets'])} "
          f"LinkedIn ad sets, {n_targeted} with targeting recorded")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['delivery'])} delivery rows, "
          f"{len(env['creative'])} creatives, {len(markets)} markets, "
          f"{tot_imp:,.0f} imps / A${tot_spend:,.0f} spend, "
          f"window {env['window']['start']}..{env['window']['end']}")
    print(f"  per campaign -> {per_camp}")


if __name__ == "__main__":
    main()
