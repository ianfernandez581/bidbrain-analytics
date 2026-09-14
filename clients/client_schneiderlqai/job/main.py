"""Schneider Electric "Liquid AI Data Center" (LQAIDC) — paid-media dashboard export job (Cloud Run job).

Stage 2 of the standard pattern: read the BigQuery views in client_schneiderlqai/sql/ and write a
single schneiderlqai.json to the private GCS bucket. The gated web app (client_schneiderlqai/dash)
serves that JSON at /data.json.

This is a SINGLE-CAMPAIGN, paid-media-only dashboard (NOT the multi-program Schneider Pacific one):
the LQAIDC TOFU / Awareness push for "Liquid Cooling for AI Data Centers", running LinkedIn + The
Trade Desk across 6 countries (India, Brazil, Australia, Chile, Saudi Arabia, UAE), plus a Google
Search (SEM) lane (5 markets: AU/UAE/SA/BR/CL) added 2026-08-31 as its own `search` payload block.
Awareness only — NO leads / conversions / Salesforce (the Search block's `engagement_actions` are
site engagement actions, NOT leads — see sql/05). The dashboard is delivery (spend / impressions /
clicks / CTR) + pacing against the media-plan targets (from data/media_plan.csv -> seed_media_plan)
+ a creative breakdown.

Read-only on BigQuery (SELECTs views, writes JSON to GCS). Reporting currency AUD for the delivery
rows; the `search` block is USD with a view-side USD->EUR conversion (pinned rate — see sql/05).
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
    "raw_snowflake.google_ads_apac",
    # The content-syndication lane (2026-09-14). Without this a CS-only advance would never
    # trigger a rebuild and the lead figures would sit frozen behind a green freshness stamp.
    "raw_snowflake.salesforce_cs_apac_all",
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
    # Google Search (SEM) is a SEPARATE block, deliberately NOT unioned into `delivery`: it bills
    # USD and converts USD->EUR once, in the view (pinned flight-start rate) — the other channels
    # are warehoused AUD and converted AUD->EUR in the browser (bbApplyFx). Folding it into the
    # delivery rows would invite a mixed-currency spend sum. The dashboard renders it as its own
    # section (Stage 3) and must EXEMPT these fields from bbApplyFx.
    # --- Content syndication (2026-09-14, client) -----------------------------
    # A SEPARATE lane, never unioned into `delivery`: these are LEADS, not impressions, and the two
    # must never meet in one total. The whole lane is scoped by seed_cs_campaign_map - if that seed
    # is empty, every view below returns 0 rows and the dashboard hides the tab rather than
    # rendering a page of zeros (which would read as a campaign that delivered nothing).
    cs_map = rows(bq, "seed_cs_campaign_map")
    cs_daily = rows(bq, "cs_daily", order_by="metric_date, region, country")
    cs_audience = rows(bq, "cs_audience")
    cs_titles = rows(bq, "cs_account_titles")
    cs_pacing = rows(bq, "cs_pacing", order_by="region")
    search_daily = rows(bq, "stg_google_search", order_by="day, market")
    search_totals_rows = rows(bq, "search_channel_totals")
    if not search_daily:
        # The Search scope is an exact five-name IN list (see sql/05) — a campaign rename empties
        # it. Loud in the job log; the dashboard hides the section rather than drawing zeros.
        print("WARNING: stg_google_search returned 0 rows - the SEM campaign names may have "
              "changed upstream (sql/05_stg_google_search.sql IN list).")

    # --- Countries / regions / channels present in the delivery data ----------
    countries = sorted({r["country"] for r in delivery}, key=lambda c: (COUNTRY_ORDER.get(c, 5), c))
    regions = sorted({r["region"] for r in delivery}, key=lambda r: (REGION_ORDER.get(r, 5), r))
    live_platforms = {r["platform"] for r in delivery}

    # --- Phases / tactics present (2026-09-14) --------------------------------
    # Rosters are built from DELIVERY, never from the plan: a phase that has not started must not
    # render as a row of zeros (that reads as a phase that FAILED rather than one not yet bought).
    # 'Unclassified' is a real parse outcome and is deliberately KEPT in the roster so it shows on
    # screen - a silent default would file a new buy under an existing phase. It is WARNed here so
    # a naming change is loud in the job log the same day it happens.
    PHASE_ORDER = {"Awareness": 0, "Consideration": 1, "Retargeting": 2, "Conversion": 3,
                   "Unclassified": 9}
    phases = sorted({r["phase"] for r in delivery if r["phase"]},
                    key=lambda p: (PHASE_ORDER.get(p, 5), p))
    tactics = sorted({r["tactic"] for r in delivery if r["tactic"]})
    unclassified = [r for r in delivery if r["phase"] == "Unclassified"]
    if unclassified:
        imps = sum(r["imps"] or 0 for r in unclassified)
        print(f"WARNING: {len(unclassified)} delivery rows parsed to phase 'Unclassified' "
              f"({imps:,} imps) - a campaign/ad-group naming change? Check the phase CASE in "
              f"sql/01_stg_linkedin.sql, sql/02_stg_tradedesk.sql and sql/05_stg_google_search.sql.")
    channels = [{"key": k, "label": CHAN_LABEL.get(k, k)}
                for k in ["linkedin", "tradedesk"] if k in live_platforms]

    # --- Data window (for the date picker) ------------------------------------
    dates = [r["metric_date"] for r in delivery if r["metric_date"]]
    wstart, wend = (min(dates), max(dates)) if dates else (None, None)
    wdays = (wend - wstart).days + 1 if (wstart and wend) else None

    # --- Media-plan targets ---------------------------------------------------
    # plan.lines = the full media plan, reseeded 2026-09-14 from the workbook's
    # "Media Plan_updated 2508" tab (12 lines; the previous seed was the 16 Jul brief's 7 and had
    # gone two months stale - that staleness, plus the narrower budget definition below, is what
    # the 2026-09-13 pace-to-plan reports were actually about).
    # plan.channels = per-channel targets summed over the LIVE lines (live=1 == currently delivering),
    # so the Media Plan tab's "delivered vs target" compares like for like.
    plan_lines = [{
        "channel": p["channel"], "channel_key": p["channel_key"], "phase": p["phase"],
        "geo": p["geo"], "flight_start": ymd(p["flight_start"]), "flight_end": ymd(p["flight_end"]),
        "imp_target": num(p["imp_target"]), "reach_target": num(p["reach_target"]),
        "click_target": num(p["click_target"]), "ctr_target": num(p["ctr_target"]),
        "spend_target": num(p["spend_target"]), "live": int(p["live"] or 0), "note": p["note"],
        # EUR-native (the plan's own column) - see the load_seeds.py schema note. Consumers must
        # NOT run this through the dashboard's AUD->EUR shim.
        "spend_target_eur": num(p["spend_target_eur"]), "budget_group": p["budget_group"],
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

    # PACE-TO-PLAN BASIS (changed 2026-09-14, client report: "total budget ... should be
    # EUR281,274"). The client paces against the whole PAID-MEDIA plan, not just the lines
    # currently delivering: budget_group == 'paid_media' excludes the unallocated
    # New/Reinvestment bucket and the Pangea lead-gen line, which are in the plan's EUR 300,000
    # total but are not media. Summed in EUR from the plan's own column (NOT converted from AUD -
    # that lands ~EUR 9k out and is what the report was about). Verified: EUR 281,274.31.
    # The imp/click targets use the SAME line set, so all three pace bars share one basis; mixing
    # a paid-media budget with live-only counts would re-create the mismatch in another axis.
    #
    # THIS DELIBERATELY DEPARTS FROM THE REPO-WIDE "PACE AGAINST THE BUDGET THAT CAN ACTUALLY
    # SPEND" RULE (md/AGENTS.md), AND IT IS A CLIENT INSTRUCTION, NOT AN OVERSIGHT. That rule says
    # to strip plan lines that have not started, because a denominator no delivery can close is a
    # permanent accusation. EUR 30,474 of this EUR 281,274 is exactly that today - Reddit, both
    # LinkedIn Bombora overlays and the intent test have never run. But in this card the budget IS
    # the denominator (it renders as "<spend> / <budget>" on the Spend bar), so the client asking
    # for "total budget in Pace to plan ... should be EUR281,274" is asking for that denominator by
    # name. Pacing against the in-market subset while the card printed her figure would put two
    # non-reconciling numbers back on the same card, which is the defect she reported.
    # Consequences, so nobody has to rediscover them: the percentage falls 38% -> 18% and the
    # verdict chip crosses the 0.6 threshold from "Slightly behind pace" to "Behind spend pace".
    # Both are TRUE - at 53% of the flight the campaign has spent 18% of the plan and needs a ~5x
    # rate increase to land it - and the old basis was flattering it by measuring against a third
    # of the plan. In-market would read 20% and keep the same red verdict, so the rule's refinement
    # changes little here.
    # DO NOT "restore the standard" without asking: this denominator was specified by the client.
    _paid = [p for p in plan_lines if p["budget_group"] == "paid_media"]
    paid_media_budget_eur = sum(p["spend_target_eur"] or 0 for p in _paid)
    paid_media_imp_target = sum(p["imp_target"] or 0 for p in _paid)
    paid_media_click_target = sum(p["click_target"] or 0 for p in _paid)

    # FLIGHT = the plan's CAMPAIGN-level window (header rows of the same tab), not min/max over the
    # line dates. The LinkedIn line carries a 2026-04-20 planned start that pre-dates both the
    # campaign start and first delivery (2026-05-16); deriving the window from the lines would drag
    # the even-pace marker ~4 weeks earlier and make every bar read as behind pace.
    CAMPAIGN_START, CAMPAIGN_END = "2026-05-15", "2026-12-31"
    flight = {"start": CAMPAIGN_START or ymd(wstart), "end": CAMPAIGN_END or ymd(wend)}

    # --- Content syndication block (2026-09-14, client) -----------------------
    # `confirmed` is the honest bit. The campaign id is PROVISIONAL until the client confirms it
    # (Schneider's Salesforce uploads carry a blank campaign name, so it cannot be confirmed from
    # data), and Pangea also delivers Schneider's C&SP programme - a wrong id would publish another
    # programme's leads here. The flag rides to the dashboard, which shows a pending banner: the
    # alternative is presenting unverified leads as settled fact, which is worse than showing
    # nothing. Clear it by setting confirmed=1 in data/cs_campaign_map.csv.
    cs_confirmed = bool(cs_map) and all(int(m["confirmed"] or 0) == 1 for m in cs_map)
    cs_total = sum(r["leads"] or 0 for r in cs_daily)
    cs_target_total = sum(p["lead_target"] or 0 for p in cs_pacing)
    if cs_map and not cs_daily:
        # The seed names a campaign that returned nothing. Loud, because the likeliest causes are a
        # wrong id or leads that have not reached Salesforce yet - both worth knowing the same day.
        print(f"WARNING: seed_cs_campaign_map names {len(cs_map)} campaign(s) but cs_daily is EMPTY "
              f"- wrong Salesforce campaign id, or the vendor's leads have not landed in the "
              f"salesforce_cs_apac_all mirror yet.")
    if not cs_map:
        print("note: no CS campaign seeded - the Content Syndication tab will stay hidden.")

    cs = {
        "enabled": bool(cs_daily),
        "confirmed": cs_confirmed,
        # Ids are carried so the pending banner can NAME the campaign it is provisional about -
        # a banner that cannot say which id is unconfirmed is not actionable.
        "campaigns": [{
            "id": m["salesforce_campaign_id"], "vendor": m["vendor"],
            "flight_start": ymd(m["flight_start"]), "flight_end": ymd(m["flight_end"]),
            "confirmed": int(m["confirmed"] or 0),
        } for m in cs_map],
        "leads": cs_total,
        "lead_target": cs_target_total,
        "daily": [{
            "date": ymd(r["metric_date"]), "vendor": r["vendor"], "region": r["region"],
            "country": r["country"], "status": r["status_bucket"], "leads": num(r["leads"]),
        } for r in cs_daily],
        "pacing": [{
            "vendor": p["vendor"], "region": p["region"], "leads": num(p["leads"]),
            "lead_target": num(p["lead_target"]), "cpl_aud": num(p["cpl_aud"]),
            "cost_aud": num(p["cost_aud"]),
            "first_lead": ymd(p["first_lead"]), "last_lead": ymd(p["last_lead"]),
        } for p in cs_pacing],
        # LONG rows: dim in {account, function, seniority}. Seniority is DERIVED from the job title
        # (JOB_LEVEL is empty on this feed) - sql/09 explains why, and the dashboard says so on
        # screen. Do not relabel it as a CRM field.
        "audience": [{
            "vendor": a["vendor"], "region": a["region"], "dim": a["dim"],
            "value": a["value"], "leads": num(a["leads"]),
        } for a in cs_audience],
        "account_titles": [{
            "vendor": t["vendor"], "region": t["region"], "company": t["company"],
            "job_title": t["job_title"], "leads": num(t["leads"]),
        } for t in cs_titles],
    }

    # --- Google Search totals (single row; empty scope -> all-None fields) ----
    st = search_totals_rows[0] if search_totals_rows else {}
    search_totals = {
        "impressions": num(st.get("impressions")), "clicks": num(st.get("clicks")),
        "cost_usd": num(st.get("cost_usd")), "cost_eur": num(st.get("cost_eur")),
        "engagement_actions": num(st.get("engagement_actions")),
        "ctr": num(st.get("ctr")), "cpc_usd": num(st.get("cpc_usd")), "cpc_eur": num(st.get("cpc_eur")),
        "fx_usd_eur": num(st.get("fx_usd_eur")), "fx_rate_date": ymd(st.get("fx_rate_date")),
        "data_through": ymd(st.get("data_through")),
    }
    if not search_daily and not search_totals["data_through"]:
        # A channel that HAD data must fail loud on the client dashboard, not vanish: the exact
        # five-name scope in sql/05 empties on a campaign rename, and hiding the section would
        # leave the Cloud Run WARN above as the only signal. Carry the last published data_through
        # forward so the dash can tell "never delivered" (data_through null -> section hidden)
        # from "delivered, now gone" (data_through set + no rows -> visible unavailable state).
        try:
            prev = json.loads(storage.Client(project=PROJECT).bucket(BUCKET)
                              .blob(DATA_OBJECT).download_as_text())
            search_totals["data_through"] = (prev.get("search") or {}).get("data_through")
            if search_totals["data_through"]:
                print(f"search: carrying forward previous data_through "
                      f"{search_totals['data_through']} so the dash shows an unavailable state")
        except Exception as e:
            print(f"search: no previous JSON to carry data_through from ({e})")

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
        "phases": phases,
        "tactics": tactics,
        "flight": flight,
        "delivery": [{
            "platform": r["platform"], "date": ymd(r["metric_date"]),
            "country": r["country"], "region": r["region"],
            # phase = the media plan's Phase (Awareness / Retargeting); tactic = the finer buy
            # within it (Premium Publishers / TAL & Intent / Prospecting / Retargeting / Search).
            # Added 2026-09-14 at the client's request to split performance by channel phase.
            "phase": r["phase"], "tactic": r["tactic"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in delivery],
        "creative": [{
            "platform": r["platform"], "country": r["country"], "concept": r["concept"],
            "phase": r["phase"], "tactic": r["tactic"],
            "format": r["creative_format"], "creative_name": r["creative_name"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]), "spend_aud": num(r["spend_aud"]),
        } for r in creative],
        # Content syndication - LEADS, deliberately a separate top-level block from `delivery`
        # (impressions) and `search` (a third currency basis). Nothing may sum across them.
        "cs": cs,
        "plan": {
            "channels": plan_channels, "lines": plan_lines,
            "live_budget": live_budget, "total_budget": total_budget,
            # EUR-native pace-to-plan basis - exempt from the dashboard's AUD->EUR shim.
            "paid_media_budget_eur": paid_media_budget_eur,
            "paid_media_imp_target": paid_media_imp_target,
            "paid_media_click_target": paid_media_click_target,
        },
        # Google Search (SEM) — own block, own currency basis (USD, converted USD->EUR once in
        # sql/05 at the pinned flight-start rate carried here as fx_usd_eur/fx_rate_date). Search
        # loads ~a day behind Trade Desk, so it carries its OWN data_through: any rolling window on
        # the dashboard must be computed per channel from it, never shared with the other channels.
        # NEVER sum cost_usd/cost_eur with the delivery rows' spend_aud in AUD space - the
        # dashboard blends Search into its Overview figures only after BOTH sides are EUR
        # (GS_BLEND in dashboard.html), and keeps it out of pace-to-plan (LinkedIn+TTD budget).
        "search": {
            "daily": [{
                "date": ymd(r["day"]), "market": r["market"], "campaign_name": r["campaign_name"],
                "phase": r["phase"], "tactic": r["tactic"],
                "network": r["network"], "currency": r["currency"],
                "impressions": num(r["impressions"]), "clicks": num(r["clicks"]),
                "cost_usd": num(r["cost_usd"]), "cost_eur": num(r["cost_eur"]),
                "engagement_actions": num(r["engagement_actions"]),
            } for r in search_daily],
            "totals": search_totals,
            "data_through": search_totals["data_through"],
        },
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    tot_imp = sum(r["imps"] or 0 for r in env["delivery"])
    tot_spend = sum(r["spend_aud"] or 0 for r in env["delivery"])
    print(f"  cs: {cs_total} leads of {cs_target_total} target across {len(cs_pacing)} regions, "
          f"{len(cs['account_titles'])} account-title rows, confirmed={cs_confirmed}")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['delivery'])} delivery rows, "
          f"{len(env['creative'])} creatives, {len(countries)} countries, "
          f"{tot_imp:,.0f} imps / A${tot_spend:,.0f} spend, "
          f"window {env['window']['start']}..{env['window']['end']}")
    s = env["search"]["totals"]
    print(f"search: {len(env['search']['daily'])} daily rows, "
          f"{(s['impressions'] or 0):,.0f} imps / {(s['clicks'] or 0):,.0f} clicks / "
          f"${(s['cost_usd'] or 0):,.2f} (EUR {(s['cost_eur'] or 0):,.2f} @ {s['fx_usd_eur']}), "
          f"data through {s['data_through']}")


if __name__ == "__main__":
    main()
