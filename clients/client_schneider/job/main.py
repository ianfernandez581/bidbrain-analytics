"""Schneider Electric (APAC) — Content-Syndication dashboard export job (Cloud Run job).

Stage 2 of the standard pattern: read the BigQuery views in client_schneider/sql/ and write a
single schneider.json to the private GCS bucket. The gated web app (client_schneider/dash) serves
that JSON at /data.json.

This dashboard is a **client_mongodb-style clone** scoped to 8 programs: the 5 Salesforce lead-gen
programs (water_env / eba / heavy / global_rebrand / airset) behind 11 SF campaign IDs, plus NEL
(New Energy Landscape), Microgrid and EcoConsult — paid-only programs with delivery but no CS leads.
Three tabs:
  * Paid Media          — DV360 / TradeDesk / LinkedIn / Google Search delivery for the selected
                          program (pm_delivery, the match_pattern-tagged delivery at program × day ×
                          market × platform grain), incl. LinkedIn's on-platform lead-form leads
                          (`leads`/`lead_form_opens`) and, for Google Search, a campaign-grain
                          brand-vs-non-brand detail block (`search_campaigns`, from sql/23).
                          Google Search carries NO conversion metric on purpose — the account's
                          CONVERSIONS column is unresolved (possibly inflated ~100x) and nothing may
                          be displayed or derived from it, CPA and ROAS included, until a manual
                          reconciliation against the Google Ads UI lands. See sql/03b's header.
  * Content Syndication — Salesforce leads vs the media-plan MQL+HQL target (cs_by_programme /
                          cs_weekly), plus audience intelligence (cs_audience) and the top job
                          titles behind each named account (cs_account_titles).
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
    "raw_snowflake.google_ads_apac",          # Google Search (SEM), added 2026-09-02
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
# ids in seed_salesforce_map) + NEL, Microgrid and EcoConsult, paid-only programs that have delivery
# but no Salesforce CS leads (render Paid Media only, like global_rebrand). Drives the Campaign
# dropdown, including its "All campaigns" all-up scope. (EcoConsult's LinkedIn lead-gen-form leads stay out of the CS lane until SE
# provision a Salesforce campaign for it — that lane is Salesforce-only, same as heavy — but they DO
# surface as paid `pm_delivery.leads`, LinkedIn's own on-platform lead-form count.)
#
# SCOPE RULE (client, 2026-08-10): this dashboard shows ONLY the programs on the client's own intake
# sheet. Enterprise IT Expansion (1958), Industrial Edge (2463) and Software First EcoStruxure (2305)
# were added on 2026-08-10 and REMOVED the same day at the client's request — they are separate
# campaigns with separate stakeholders. Delivering != in scope: do not re-add a program just because
# it has live delivery under the Schneider advertiser/account. They now have their OWN dashboard,
# client_schneidersecpwr ("Schneider Electric - Secure Power"), because a different group of people
# views them. See clients/client_schneider/README.md for what re-adding each here would take (ent_it
# in particular needs the multi-region market arm restored in sql/20, or its non-Pacific spend
# reports as Australia).
CS_PROGRAMS = ["water_env", "eba", "heavy", "global_rebrand", "airset", "nel", "microgrid",
               "ecoconsult", "mcset"]


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
    sc = rows(bq, "search_campaigns")   # Paid Media tab: Google Search at campaign x brand grain
    aud = rows(bq, "cs_audience")   # Content Syndication tab: account / function / seniority mix
    # Top job titles per account (client, 2026-09-01). Companion to cs_audience, deliberately a
    # SEPARATE array: a title belongs to a company, which the LONG dim/value shape cannot key.
    acct_titles = rows(bq, "cs_account_titles")
    # PUBLISHER REPORTS (Other Channels tab, 2026-09-14). Direct publisher buys with no API feed -
    # hand-keyed monthly from emailed PDFs / workbooks into data/publisher_reports.csv. Wrapped so a
    # missing view can never break the CS/paid export, exactly like the GA4 and search-audit blocks.
    # NOTE these rows carry NO spend, NO market and NO day: they are monthly aggregates and must
    # never reach pm_delivery, the blended KPI band or any CPM/CPC figure. They travel in their own
    # payload keys and nothing else reads them.
    try:
        pub_rows = rows(bq, "publisher_delivery",
                        order_by="campaign, publisher, period_start, placement_group, placement")
        pub_meta = rows(bq, "publisher_report_meta", order_by="seq, campaign, publisher")
    except Exception as e:
        print(f"WARNING: publisher report views unavailable ({e}); Other Channels shows plan only.")
        pub_rows, pub_meta = [], []

    media = rows(bq, "seed_media_plan")
    budget = {b["internal_campaign_id"]: b for b in rows(bq, "seed_plan_budget")}
    display = {m["internal_campaign_id"]: m["display_name"]
               for m in rows(bq, "seed_campaign_map", order_by="seq")}
    fx = rows(bq, "kpi")[0]   # FX constants + (unused here) headline

    # --- Google Search scope audit -------------------------------------------
    # Search is the first platform here whose ad ACCOUNT is not Pacific-only: 'AAG region Account'
    # also carries the brief-2306 campaigns running in Brazil / Chile / Saudi / UAE. Those are kept
    # out by PROGRAM (2306 is ai_lc, which has its own dashboard) and never by region - but both
    # failure modes are silent, so print the resolution every run and WARN on anything unexpected.
    # An UNMAPPED campaign is invisible on every surface; an IN_SCOPE_NON_ANZ one is being reported
    # AS AUSTRALIA by pm_delivery's market fold. See sql/24_search_scope_audit.sql.
    try:
        audit = rows(bq, "search_scope_audit")
        n_in = sum(1 for r in audit if r["status"] == "IN_SCOPE")
        print(f"search scope audit: {len(audit)} campaign(s) on the Google Ads account, "
              f"{n_in} in scope")
        for r in audit:
            line = (f"  [{r['status']}] {r['campaign_name']} -> {r['program'] or '(unmapped)'} | "
                    f"{r['markets']} | {r['networks']} | {r['imps']} imps, {r['clicks']} clicks, "
                    f"A${float(r['spend_aud'] or 0):,.2f}")
            if r["status"] in ("UNMAPPED", "IN_SCOPE_NON_ANZ"):
                print("WARNING: Google Search scope needs attention:")
                print(line)
            else:
                print(line)
    except Exception as e:                       # never let the audit break the export
        print(f"WARNING: search scope audit unavailable: {e}")

    # --- Publisher-report audit ----------------------------------------------
    # Every failure mode on this lane is SILENT on screen: a row whose campaign is not a dashboard
    # program renders nowhere, an unknown `unit` is counted in no total, and a plan_channel typo
    # looks exactly like a buy that legitimately has no plan row. So each one is printed by name
    # every run. validate_publisher_reports.py catches the same things before the load, on the
    # laptop of whoever keyed the report in - this is the runtime net behind it.
    pub_drop = {}
    if pub_meta or pub_rows:
        for m in pub_meta:
            cid, pub = m["campaign"], m["publisher"]
            if m["plan_match"] == "PLAN_ROW_NOT_FOUND":
                print(f"WARNING: publisher {pub} ({cid}) names plan_channel "
                      f"{m['plan_channel']!r}, which matches no seed_media_plan line. It renders "
                      f"flagged, NOT as 'missing plan row' - fix the CSV or the plan.")
            elif m["plan_match"] == "NO_META_ROW":
                print(f"WARNING: publisher {pub} ({cid}) has delivery rows but no row in "
                      f"publisher_report_meta.csv - the card has no heading, source or plan match.")
            elif m["plan_match"] == "NO_DELIVERY_ROWS":
                print(f"publisher {pub} ({cid}): meta row present, no delivery keyed in yet.")
            if not m["campaign_known"]:
                print(f"WARNING: publisher {pub} names campaign {cid!r}, which is not in "
                      f"seed_campaign_map - its rows would render on no campaign at all.")
            elif cid not in CS_PROGRAMS:
                print(f"WARNING: publisher {pub} names campaign {cid!r}, which is a known program "
                      f"but is NOT on this dashboard - its rows are dropped from the payload.")
            if m["n_unknown_unit"]:
                print(f"WARNING: publisher {pub} ({cid}) has {m['n_unknown_unit']} row(s) with an "
                      f"unrecognised `unit`. They are counted in NO total - see "
                      f"sql/25_publisher_delivery.sql for the vocabulary.")
        # Scope to the dashboard's programs. Dropping is under-inclusion, which is normally the
        # silent failure - so it is only ever done alongside the WARNING above that names the id.
        kept = [r for r in pub_rows if r["campaign"] in CS_PROGRAMS]
        for r in pub_rows:
            if r["campaign"] not in CS_PROGRAMS:
                pub_drop[r["campaign"]] = pub_drop.get(r["campaign"], 0) + 1
        pub_rows = kept
        pub_meta = [m for m in pub_meta if m["campaign"] in CS_PROGRAMS]
        for cid, n in sorted(pub_drop.items()):
            print(f"WARNING: dropped {n} publisher row(s) for out-of-scope campaign {cid!r}.")
        # Per-publisher totals, computed the ONLY way they may be computed: impressions come from
        # the impressions column alone. Solus sends and sponsored-article views are printed beside
        # them precisely so it stays obvious they are not in that first figure.
        for m in pub_meta:
            mine = [r for r in pub_rows
                    if r["campaign"] == m["campaign"] and r["publisher"] == m["publisher"]]
            imps = sum(r["impressions"] or 0 for r in mine)
            clicks = sum(r["clicks"] or 0 for r in mine)
            sends = sum(r["sends"] or 0 for r in mine)
            arts = sum(r["article_views"] or 0 for r in mine)
            booked = sum(r["booked_quantity"] or 0 for r in mine)
            if m.get("internal_note"):
                print(f"  note ({m['publisher']}): {m['internal_note']}")
            print(f"publisher {m['publisher']} ({m['campaign']}, {m['plan_match']}): "
                  f"{imps:,.0f} impressions, {clicks:,.0f} clicks"
                  + (f", {sends:,.0f} eDM sends" if sends else "")
                  + (f", {arts:,.0f} article views vs {booked:,.0f} booked" if arts else "")
                  + f" | {len(mine)} row(s)")

    # --- Per-campaign aggregates: target (MQL+HQL), plan-CPL tiers, committed spend, flight ----
    leads_by_camp = {}
    for r in cs:
        leads_by_camp[r["campaign"]] = leads_by_camp.get(r["campaign"], 0) + (r["total"] or 0)

    # Programs that have ACTUAL paid delivery (rows in pm_delivery), for the per-campaign tab logic.
    paid_programs = {r["program"] for r in pm}

    # OBSERVED delivery window + on-platform lead-form leads per program. The observed window is the
    # fallback flight for programs whose media plan is still unsigned (Microgrid / EcoConsult have
    # BLANK flight_start/flight_end in seed_plan_budget), so the dashboard can say "live since <date>"
    # instead of "no flight dates" for a program that is demonstrably delivering. Plan dates always
    # win when present, and a plan start with an open end (global_rebrand) is left open on purpose.
    obs_start, obs_end, li_leads = {}, {}, {}
    for r in pm:
        p, d = r["program"], r["metric_date"]
        if d is not None:
            if p not in obs_start or d < obs_start[p]:
                obs_start[p] = d
            if p not in obs_end or d > obs_end[p]:
                obs_end[p] = d
        li_leads[p] = li_leads.get(p, 0) + (r["leads"] or 0)

    def chan_group(line_type, channel):
        """Bucket a media-plan line into the reporting channel it feeds:
          cs    — lead-gen (LeadGen-MQL/HQL) → Salesforce Content Syndication,
          paid  — Programmatic / LinkedIn / Search → DV360/TTD/LinkedIn/Google Search delivery
                  (pm_delivery),
          other — publisher sponsorships / Trade / Email → NO warehouse feed (plan only).

        SEARCH MOVED other -> paid on 2026-09-02. It was bucketed `other`
        ("no warehouse source", as the media-plan note still said) and rendered on the Other
        Channels tab as a plan-only line. Google Ads has in fact been delivering against it since
        2026-07-06 and now reaches the dashboard through stg_google_search -> pm_delivery, so its
        plan line belongs with the measured channels — that is what puts its committed click target
        (global_rebrand: 1,222 clicks at a 3% CTR) next to real clicks instead of next to nothing.
        global_rebrand keeps its Other Channels tab regardless: Capital Brief / Energy Magazine /
        Innovation Aus are still genuinely plan-only."""
        if line_type in ("LeadGen-MQL", "LeadGen-HQL"):
            return "cs"
        c = (channel or "").lower()
        if "linkedin" in c or "programmatic" in c or "search" in c:
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

        # Flight: the media plan wins. Only when it seeds NO start at all do we fall back to the
        # observed first delivery day (flight_source='observed' so the UI can label it honestly as
        # "live since" rather than a planned flight). The end is NEVER synthesized — an unsigned plan
        # has no agreed end date, and the dashboard already treats a missing end as ongoing.
        f_start, f_end = ymd(b.get("flight_start")), ymd(b.get("flight_end"))
        f_source = "plan" if f_start else None
        if not f_start and cid in obs_start:
            f_start, f_source = ymd(obs_start[cid]), "observed"

        campaigns.append({
            "id": cid,
            "label": display.get(cid, cid),
            "target_mql": mql, "target_hql": hql, "target": mql + hql,
            "cpl_tiers": cpl_tiers, "committed_spend": committed,
            "flight_start": f_start, "flight_end": f_end, "flight_source": f_source,
            "plan_budget": num(b.get("budget_aud")),
            "first_delivery": ymd(obs_start.get(cid)), "last_delivery": ymd(obs_end.get(cid)),
            "leads": n_leads,
            # LinkedIn on-platform lead-form leads (whole flight, all markets). A PAID metric, kept
            # strictly out of `leads` (Salesforce CS) - see the CS_PROGRAMS note.
            "li_leads": num(li_leads.get(cid, 0)),
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
            # LinkedIn-only on-platform lead-form counts (NULL on DV360/TradeDesk). PAID metrics -
            # never fold into cs_by_programme.
            "leads": num(r["leads"]), "lead_form_opens": num(r["lead_form_opens"]),
        } for r in pm],
        # GOOGLE SEARCH detail, campaign x brand/non-brand x market x day (sql/22). Scoped and
        # market-folded EXACTLY as pm_delivery is, from the same campaign_program view, so the
        # Search section always ties to the Google Search row of the platform table.
        # NO conversion field of any kind - the account's CONVERSIONS column is unresolved
        # (possibly inflated ~100x) and nothing may be displayed or derived from it, CPA and ROAS
        # included, until a manual reconciliation against the Google Ads UI lands. cost_usd is the
        # pre-FX source figure, carried so the dashboard can footnote the USD->AUD conversion.
        "search_campaigns": [{
            "program": r["program"], "date": ymd(r["metric_date"]),
            "campaign": r["campaign_name"], "campaign_id": r["campaign_id"],
            "brief": r["brief"], "match_type": r["match_type"],
            "market": r["market"], "market_parsed": r["market_parsed"],
            "network": r["network"],
            "imps": num(r["imps"]), "clicks": num(r["clicks"]),
            "spend_aud": num(r["spend_aud"]), "cost_usd": num(r["cost_usd"]),
        } for r in sc],
        # The Search lane's source currency + the rate stg_google_search converted it at, so the
        # dashboard can state the conversion instead of quietly blending USD into an AUD total.
        "search_fx": {"source_currency": "USD", "rate_to_aud": 1.50},
        "cs_audience": [{
            "campaign": r["campaign"], "market": r["market"], "dim": r["dim"],
            "value": r["value"], "leads": num(r["leads"]),
        } for r in aud],
        # One row per company x job title x market. The dashboard sums across the selected markets
        # and ranks, so the ranking honours the Campaign dropdown + Region chips. JOB_TITLE is ~90%
        # populated, so per-account title counts can be LOWER than the account's lead total - that
        # gap is stated on screen, never coalesced into an invented "Unknown" title.
        "cs_account_titles": [{
            "campaign": r["campaign"], "market": r["market"], "company": r["company"],
            "job_title": r["job_title"], "leads": num(r["leads"]),
        } for r in acct_titles],
        # PUBLISHER REPORTS - Other Channels tab only. Deliberately their own two keys: nothing
        # else in this payload reads them, so they cannot reach Paid Media or any blended total.
        #
        # `quantity` is NOT carried. Each row's number arrives in exactly ONE of impressions /
        # sends / article_views / rate_value, so a consumer cannot add a solus send or a sponsored
        # -article view to an impression total by summing the obvious column - there is no obvious
        # column to sum. Each is NULL (never 0) outside its own unit: 0 would assert a measured
        # zero where the publisher simply reports a different measure.
        "publisher_delivery": [{
            "campaign": r["campaign"], "publisher": r["publisher"],
            "period_label": r["period_label"],
            "period_start": ymd(r["period_start"]), "period_end": ymd(r["period_end"]),
            "placement_group": r["placement_group"], "placement": r["placement"],
            "unit": r["unit"], "metric": r["metric"],
            "impressions": num(r["impressions"]), "sends": num(r["sends"]),
            "article_views": num(r["article_views"]), "rate_value": num(r["rate_value"]),
            "clicks": num(r["clicks"]), "booked_quantity": num(r["booked_quantity"]),
            "note": r["note"],
        } for r in pub_rows],
        # One per campaign x publisher: card heading, provenance, status, and the plan join state
        # (matched / no_plan_row / PLAN_ROW_NOT_FOUND). Carries no delivered totals on purpose -
        # the tab derives every rendered figure from publisher_delivery under the current campaign
        # selection, and a second copy here is how two panels on one tab start disagreeing.
        "publisher_reports": [{
            "seq": num(m["seq"]), "campaign": m["campaign"], "publisher": m["publisher"],
            "publisher_label": m["publisher_label"], "plan_channel": m["plan_channel"],
            "report_source": m["report_source"], "report_label": m["report_label"],
            "report_job": m["report_job"], "delivery_status": m["delivery_status"],
            # status_note ONLY. `internal_note` is agency commentary and is deliberately not
            # carried: this dashboard has no staff/client session distinction, so anything in the
            # payload is on the client's screen (or one devtools tab away from it).
            "status_note": m["status_note"], "plan_match": m["plan_match"],
        } for m in pub_meta],
        "ga4_enabled": ga4_enabled,
        "ga4": ga4,
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    n_leads = sum(r["total"] for r in env["cs_by_programme"])
    n_li = sum(c["li_leads"] or 0 for c in env["campaigns"])
    n_titled = sum(r["leads"] or 0 for r in env["cs_account_titles"])
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['campaigns'])} programs, "
          f"{n_leads} CS leads, {n_li} LinkedIn lead-form leads, "
          f"{len(env['pm_delivery'])} paid-delivery rows, "
          f"{len(env['cs_account_titles'])} account-title rows covering {n_titled}/{n_leads} leads, "
          f"window {env['window']['start']}..{env['window']['end']}")


if __name__ == "__main__":
    main()
