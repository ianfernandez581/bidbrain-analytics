"""Schneider Electric (APAC) — Content-Syndication dashboard export job (Cloud Run job).

Stage 2 of the standard pattern: read the BigQuery views in client_schneider/sql/ and write a
single schneider.json to the private GCS bucket. The gated web app (client_schneider/dash) serves
that JSON at /data.json.

This dashboard is a **client_mongodb-style clone** scoped to 6 programs: the 5 Salesforce lead-gen
programs (water_env / eba / heavy / global_rebrand / airset) behind 9 SF campaign IDs, plus NEL
(New Energy Landscape) — an awareness-only program with paid delivery but no CS leads. Three tabs:
  * Paid Media          — DV360 / TradeDesk / LinkedIn delivery for the selected program (pm_delivery,
                          the match_pattern-tagged delivery at program × day × market × platform grain).
  * Content Syndication — Salesforce leads vs the media-plan MQL+HQL target (cs_by_programme / cs_weekly).
  * CS Comparison       — market A vs B for the selected program.
The campaign→programme→market model: CAMPAIGN = internal program, PROGRAMME = SF pillar_label,
MARKET = normalized COUNTRY_NAME (Australia / New Zealand / ANZ / Other).

Read-only on BigQuery (SELECTs views, writes JSON to GCS). The shared raw layer is filled by
snowflake_data_pull/. Reporting currency AUD.
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
    "raw_snowflake.dv360_apac",
    "raw_snowflake.linkedin_ads_apac",
    "raw_snowflake.tradedesk_apac_all",
    "raw_snowflake.salesforce_cs_apac_all",   # the CS leads lane
]
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
CLIENT = "schneider"
DATASET = f"client_{CLIENT}"
BUCKET = f"bidbrain-analytics-{CLIENT}-dash"
DATA_OBJECT = f"{CLIENT}.json"

# The programs the dashboard surfaces: the 5 Content-Syndication programs (== the distinct internal
# ids in seed_salesforce_map) + NEL, an awareness-only program that has paid delivery but no CS leads
# (renders Paid Media only, like global_rebrand). Drives both the Campaign dropdown and the scorecard.
CS_PROGRAMS = ["water_env", "eba", "heavy", "global_rebrand", "airset", "nel"]


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
    cs = rows(bq, "cs_by_programme")
    csw = rows(bq, "cs_weekly")
    pm = rows(bq, "pm_delivery")
    aud = rows(bq, "cs_audience")   # Executive Scorecard: account / function / seniority mix
    media = rows(bq, "seed_media_plan")
    budget = {b["internal_campaign_id"]: b for b in rows(bq, "seed_plan_budget")}
    display = {m["internal_campaign_id"]: m["display_name"]
               for m in rows(bq, "seed_campaign_map", order_by="seq")}
    fx = rows(bq, "kpi")[0]   # FX constants + (unused here) headline

    # --- Per-campaign aggregates: target (MQL+HQL), plan-CPL tiers, committed spend, flight ----
    leads_by_camp = {}
    for r in cs:
        leads_by_camp[r["campaign"]] = leads_by_camp.get(r["campaign"], 0) + (r["total"] or 0)

    # Programs that have ACTUAL paid delivery (rows in pm_delivery), for the per-campaign tab logic.
    paid_programs = {r["program"] for r in pm}

    def chan_group(line_type, channel):
        """Bucket a media-plan line into the reporting channel it feeds:
          cs    — lead-gen (LeadGen-MQL/HQL) → Salesforce Content Syndication,
          paid  — Programmatic / LinkedIn    → DV360/TTD/LinkedIn delivery (pm_delivery),
          other — Search / publisher sponsorships / Trade / Email → NO warehouse feed (plan only)."""
        if line_type in ("LeadGen-MQL", "LeadGen-HQL"):
            return "cs"
        c = (channel or "").lower()
        if "linkedin" in c or "programmatic" in c:
            return "paid"
        return "other"

    campaigns = []
    for cid in CS_PROGRAMS:
        lines = [m for m in media if m["internal_campaign_id"] == cid]
        lead_lines = [m for m in lines if m["line_type"] in ("LeadGen-MQL", "LeadGen-HQL")
                      and m["lead_target"]]
        mql = sum(m["lead_target"] for m in lines if m["line_type"] == "LeadGen-MQL" and m["lead_target"])
        hql = sum(m["lead_target"] for m in lines if m["line_type"] == "LeadGen-HQL" and m["lead_target"])
        cpl_tiers = [{
            "label": m["channel"],
            "leads": m["lead_target"],
            "spend": num(m["spend_aud"]),
            "cpl": (float(m["spend_aud"]) / m["lead_target"]) if (m["spend_aud"] and m["lead_target"]) else None,
        } for m in lead_lines]
        committed = sum(float(m["spend_aud"]) for m in lead_lines if m["spend_aud"])
        b = budget.get(cid, {})

        # Per-campaign channel lineup (from the media plan) + which reporting tabs that implies.
        channels = []
        for m in lines:
            g = chan_group(m["line_type"], m["channel"])
            has_target = any(m.get(k) for k in
                             ("spend_aud", "imp_target", "reach_target", "click_target", "lead_target"))
            channels.append({
                "name": m["channel"], "group": g, "line_type": m["line_type"],
                "spend": num(m["spend_aud"]), "imp_target": m["imp_target"],
                "click_target": m["click_target"], "lead_target": m["lead_target"],
                "has_target": bool(has_target),
            })
        n_leads = leads_by_camp.get(cid, 0)
        has_paid = any(c["group"] == "paid" for c in channels) or (cid in paid_programs)
        has_cs = any(c["group"] == "cs" for c in channels) or n_leads > 0
        other_chans = [c for c in channels if c["group"] == "other" and c["has_target"]]
        # Tab order matches the dashboard's: Paid Media · Content Syndication · CS Comparison · Other.
        tabs = []
        if has_paid:
            tabs.append("paid")
        if has_cs:
            tabs.append("cs")
        if n_leads > 0:                      # CS Comparison needs real leads to compare markets
            tabs.append("compare")
        if other_chans:                      # plan-only channels (Search / publishers / Trade / Email)
            tabs.append("other")
        if not tabs:
            tabs = ["cs"]

        campaigns.append({
            "id": cid,
            "label": display.get(cid, cid),
            "target_mql": mql, "target_hql": hql, "target": mql + hql,
            "cpl_tiers": cpl_tiers, "committed_spend": committed,
            "flight_start": ymd(b.get("flight_start")), "flight_end": ymd(b.get("flight_end")),
            "leads": n_leads,
            "channels": channels, "tabs": tabs,
        })
    # default campaign = most leads, then biggest target (dashboard reads campaigns[0] as default).
    campaigns.sort(key=lambda c: (-c["leads"], -c["target"], c["label"]))

    # --- Shared market vocab (union of CS + paid markets), ordered ------------
    mk_order = {"Australia": 0, "New Zealand": 1, "ANZ": 2, "Other": 9}
    all_markets = sorted({r["market"] for r in cs} | {r["market"] for r in pm},
                         key=lambda m: (mk_order.get(m, 5), m))

    # --- Overall data window (paid delivery + leads) for the date picker ------
    wq = list(bq.query(
        f"""SELECT MIN(d) s, MAX(d) e FROM (
              SELECT metric_date d FROM `{PROJECT}.{DATASET}.pm_delivery`
              UNION ALL SELECT metric_date FROM `{PROJECT}.{DATASET}.stg_salesforce`)""",
        location=LOC).result())[0]
    wstart, wend = wq["s"], wq["e"]
    wdays = (wend - wstart).days + 1 if (wstart and wend) else None

    # --- GA4 website analytics (whole-property, via raw_ga4.perf_ga4) ----------
    # SHIPPED DISABLED: the ga4_* views return 0 rows until the SE GA4 property id is set in
    # sql/40_stg_ga4.sql + sql/40b_stg_ga4_events.sql. ga4_enabled flips true automatically on the first
    # rebuild after real sessions land, and the dashboard's Website tab appears then. Wrapped so any GA4
    # hiccup never breaks the CS/paid dashboard. Freshness: GA4 rides the existing gate (a rebuild fires
    # when the Snowflake CS/paid tables advance daily); once enabled, you MAY add the property's
    # raw_ga4.ga4_TrafficAcquisition_<id> base table to GATING_TABLES for tighter GA4 freshness.
    ga4_enabled = False
    ga4 = {"kpi": None, "daily": [], "channels": [], "sources": [], "events": []}
    try:
        gk = rows(bq, "ga4_kpi_market")
        ga4_enabled = bool(gk and (gk[0].get("sessions") or 0) > 0)
        if ga4_enabled:
            k = gk[0]
            ga4 = {
                "kpi": {
                    "sessions": num(k["sessions"]), "engaged_sessions": num(k["engaged_sessions"]),
                    "users": num(k["users"]), "new_users": num(k["new_users"]),
                    "page_views": num(k["page_views"]), "eng_duration": num(k["eng_duration"]),
                    "conversions": num(k["conversions"]), "paid_sessions": num(k["paid_sessions"]),
                    "display_sessions": num(k["display_sessions"]),
                    "social_sessions": num(k["social_sessions"]),
                    "search_sessions": num(k["search_sessions"]),
                },
                "daily": [{
                    "day": ymd(r["day"]), "ga4_sessions": num(r["ga4_sessions"]),
                    "engaged_sessions": num(r["engaged_sessions"]), "conversions": num(r["conversions"]),
                    "paid_sessions": num(r["paid_sessions"]), "organic_sessions": num(r["organic_sessions"]),
                    "direct_sessions": num(r["direct_sessions"]), "other_sessions": num(r["other_sessions"]),
                } for r in rows(bq, "ga4_daily_market", order_by="day")],
                "channels": [{
                    "channel_group": r["channel_group"], "channel_bucket": r["channel_bucket"],
                    "sessions": num(r["sessions"]), "engaged_sessions": num(r["engaged_sessions"]),
                    "users": num(r["users"]), "conversions": num(r["conversions"]),
                } for r in rows(bq, "ga4_channels_market", order_by="sessions DESC")],
                "sources": [{
                    "source_medium": r["source_medium"], "channel": r["channel"], "bucket": r["bucket"],
                    "sessions": num(r["sessions"]), "engaged": num(r["engaged"]),
                    "conversions": num(r["conversions"]),
                } for r in rows(bq, "ga4_sources_market", order_by="sessions DESC")],
                "events": [{
                    "month": r["month"], "event_name": r["event_name"], "events": num(r["key_events"]),
                } for r in rows(bq, "ga4_key_events_market")],
            }
            print(f"GA4 enabled: {ga4['kpi']['sessions']} sessions, {len(ga4['daily'])} day(s)")
    except Exception as e:
        print(f"GA4 block skipped ({e}); dashboard Website tab stays hidden.")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (max([v for v in observed.values() if v]).strftime("%Y-%m-%dT%H:%M:%SZ")
                         if observed else None),
        "currency": "AUD",
        "fx_usd_aud": num(fx["fx_usd_aud"]), "fx_sgd_aud": num(fx["fx_sgd_aud"]),
        "window": {"start": ymd(wstart), "end": ymd(wend), "days": wdays},
        "all_markets": all_markets,
        "campaigns": campaigns,
        "cs_by_programme": [{
            "campaign": r["campaign"], "programme": r["programme"], "market": r["market"],
            "total": num(r["total"]), "new": num(r["new_leads"]), "working": num(r["working"]),
            "qualified": num(r["qualified"]), "disqualified": num(r["disqualified"]),
            "last_lead_day": ymd(r["last_lead_day"]),
        } for r in cs],
        "cs_weekly": [{
            "campaign": r["campaign"], "programme": r["programme"], "market": r["market"],
            "week_start": ymd(r["week_start"]), "leads": num(r["leads"]),
        } for r in csw],
        "pm_delivery": [{
            "program": r["program"], "platform": r["platform"], "date": ymd(r["metric_date"]),
            "market": r["market"], "imps": num(r["imps"]), "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]),
        } for r in pm],
        "cs_audience": [{
            "campaign": r["campaign"], "market": r["market"], "dim": r["dim"],
            "value": r["value"], "leads": num(r["leads"]),
        } for r in aud],
        "ga4_enabled": ga4_enabled,
        "ga4": ga4,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    n_leads = sum(r["total"] for r in env["cs_by_programme"])
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['campaigns'])} programs, "
          f"{n_leads} CS leads, {len(env['pm_delivery'])} paid-delivery rows, "
          f"window {env['window']['start']}..{env['window']['end']}")


if __name__ == "__main__":
    main()
