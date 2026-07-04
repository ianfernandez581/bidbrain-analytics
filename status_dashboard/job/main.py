"""status-export — the META / pipeline-status export job (Cloud Run job).

Assembles ONE JSON (status.json) that powers the meta dashboard. It answers two
questions, for every Snowflake-sourced client, in language a non-engineer can act on:

  1. DATA SYNC STATUS — is a stale dashboard Transmission's fault (the Snowflake
     SOURCE table hasn't updated) or 100% Digital's (our pipeline hasn't ingested
     /rebuilt)? We probe three stages and compare them:

       Transmission            100% Digital ────────────────────────────►
       Snowflake source        BigQuery raw mirror        Dashboard build
       (LAST_ALTERED)          (__TABLES__.last_modified)  (<client>.json last_updated)

     If our ingest has caught up to Snowflake's latest change, 100% Digital is GREEN
     no matter how old the numbers are — any staleness is then the SOURCE's (Transmission).
     If Snowflake moved and we haven't mirrored/rebuilt past it, 100% Digital is BEHIND.

  2. DATA ACCURACY — the number on each client dashboard vs the number pulled
     straight from Snowflake. Under healthy sync they are equal. We run the exact
     Snowflake COUNT/SUM and show it next to the dashboard's number AND the query
     itself, so anyone can reproduce it.

Cost discipline (mirrors the repo's self-gating jobs): the LAST_ALTERED freshness
probe is metadata-only and never resumes the warehouse, so it runs every tick for
free. The accuracy COUNT/SUM queries DO resume APAC_IN_WH, so they are gated: a
client's numbers are only recomputed when that client's Snowflake source advanced
since the previous status.json (otherwise the prior numbers are carried forward).

Reads: Snowflake (metadata + a few aggregates), BigQuery (__TABLES__ metadata), and
each client's <client>.json from its private bucket. Writes: status.json (+ nothing
else) to the status bucket. No pandas — every accuracy result is a single scalar.
"""
import os, json, datetime
from google.cloud import bigquery, storage
import snowflake.connector
from cryptography.hazmat.primitives import serialization

from freshness import (
    probe_snowflake_last_altered, probe_bq_last_modified, _to_utc, _iso, _parse_iso,
)

# --- Project-wide constants (identical for every client) ----------------------
PROJECT      = "bidbrain-analytics"
LOC          = "australia-southeast1"
SF_ACCOUNT   = "ZGKGHOH-ISA98947"
SF_USER      = "BQ_SYNC_USER"
SF_WAREHOUSE = "APAC_IN_WH"

BUCKET      = "bidbrain-analytics-status-dash"
DATA_OBJECT = "status.json"

# How long after a Snowflake change we still call 100% Digital "caught up" (the normal
# ingest cadence is */10–*/15, so a brief lag after a source change is expected, not a fault).
INGEST_LAG_TOLERANCE = datetime.timedelta(minutes=45)

# --- Snowflake source table -> BigQuery raw mirror (from ingest/snowflake_data_pull/loader.py).
# Used to label the freshness chain and to probe both stages.
SF_TO_MIRROR = {
    "Salesforce_CS_APAC_ALL":         "raw_snowflake.salesforce_cs_apac_all",
    "TradeDesk_APAC ALL":             "raw_snowflake.tradedesk_apac_all",
    "LinkedIn Ads - APAC":            "raw_snowflake.linkedin_ads_apac",
    "Reddit Ads - APAC_ALL":          "raw_snowflake.reddit_ads_apac_all",
    "DV360 - APAC":                   "raw_snowflake.dv360_apac",
    "Google Ads - APAC":              "raw_snowflake.google_ads_apac",
    "Google Analytics Data_APAC ALL": "raw_snowflake.google_analytics_apac_all",
}


def _num(x):
    """JSON value -> number (None/'' -> 0)."""
    if x is None or x == "":
        return 0
    try:
        return x if isinstance(x, (int, float)) else float(x)
    except (TypeError, ValueError):
        return 0


def _is_dummy(r):
    return str(r.get("LEAD_ID_SF") or "").startswith("DUMMY")


def _kpi(key):
    """dash-extractor: read d['kpi'][key] as a number (the whole-flight reference block)."""
    return lambda d: _num(d.get("kpi", {}).get(key))


# --- mongodb dash-side extractors --------------------------------------------
# Trade Desk numbers are the un-scoped sum over the top-level rows[] array
# (the campaign/region/date pickers only scope the on-screen KPI, not the JSON).
def _mdb_rows(field):
    return lambda d: sum(_num(r.get(field)) for r in d.get("rows", []))


# Content-Syndication is split into DNB (the 3 programme campaigns, which carry a
# non-null programme label) and KGA(IDC) (campaign NKKwQYAX, whose PROGRAMME_LABEL
# is NULL -> the only null-programme rows in cs_by_programme). This is the
# separation the monitor previously lacked: KGA(IDC) was invisible.
def _mdb_dnb(field):
    return lambda d: sum(_num(c.get(field)) for c in d.get("cs_by_programme", []) if c.get("programme"))


def _mdb_idc(field):
    return lambda d: sum(_num(c.get(field)) for c in d.get("cs_by_programme", []) if not c.get("programme"))


# BOTH mongodb and cloudflare CS now go through the BQ mirror (raw_snowflake.salesforce_cs_apac_all),
# and the Salesforce lead table is MUTABLE — leads are continuously added and re-statused — so a
# small delta vs the live source count is normal mirror lag, NOT a pipeline fault (the magnitude IS
# the signal: how many leads the mirror is behind). (cloudflare used to match the live modelled view
# exactly; since 2026-06-17 BQ owns its model and it reads the mirror like mongodb.) The Sync tab is
# the authority on whether the pipeline itself is healthy.
_MDB_CS_NOTE = (" · Mutable source: mongodb CS reads the BQ mirror and Salesforce leads are "
                "continuously added / re-statused, so a small delta vs the live source is normal "
                "mirror lag, not a pipeline fault — the Sync tab is the authority on health.")
_CF_CS_NOTE = (" · Mutable source: cloudflare CS is now derived in BigQuery from the "
               "raw_snowflake mirror (not the live Snowflake view), and Salesforce leads are "
               "continuously added / re-statused, so a small delta vs this live source query is "
               "normal mirror lag, not a pipeline fault — the Sync tab is the authority on health.")
# schneider CS reads the SAME shared, mutable Salesforce mirror (raw_snowflake.salesforce_cs_apac_all),
# so the same mirror-lag caveat applies — the magnitude of any delta is the signal, the Sync tab the authority.
_SCH_CS_NOTE = (" · Mutable source: schneider CS reads the BQ mirror of the shared Salesforce CS table "
                "(leads continuously added / re-statused), so a small delta vs this live source query is "
                "normal mirror lag, not a pipeline fault — the Sync tab is the authority on health.")


# --- cloudflare dash-side extractors -----------------------------------------
# Paid media: sum a field over paid_media.rows[] for one channel (the modelled
# V_PAID_ADS_FINAL_MODEL emits 'TTD'/'LinkedIn'/'Reddit'/'LINE'; the dash also
# tolerates the 'TradeDesk'/'LI' aliases, so match a set).
def _cf_pm(field, channels):
    return lambda d: sum(_num(r.get(field)) for r in d.get("paid_media", {}).get("rows", [])
                         if r.get("channel") in channels)


# Single-campaign LinkedIn dashboards: campaigns.<key>.totals.<field>.
def _cf_camp(key, field):
    return lambda d: _num(d.get("campaigns", {}).get(key, {}).get("totals", {}).get(field))


# Cloudflare's Content-Syndication checks (4 CS quality + KR/RIG segments + OTHER-residual reconcile + 4 CF1
# CS) are BUILT FROM DEFINITIONS at runtime — see _build_cf_cs_checks() below. The campaign-ID filter,
# the client-defined KR/RIG sets, the geographic map, the 11 market chips and the status buckets all
# come from definitions/<client>.json (the single source of truth shared with the client's seed tables),
# so editing that one file changes BOTH the dashboard and this verification — no two-place edit.


# --- schneider dash-side extractors ------------------------------------------
# RESTRUCTURED 2026-06-22: schneider became a client_mongodb-style Content-Syndication clone scoped to
# 5 lead-gen programs (the 11 SF campaign IDs in data/salesforce_map.csv). The old kpi.* delivery block
# is GONE — leads now live in cs_by_programme[] (campaign = internal program id; total = SUM(leads) per
# program × programme × market). A program's dashboard lead count = sum of cs_by_programme[].total for it.
def _sch_cs_camp(program):
    return lambda d: sum(_num(r.get("total")) for r in d.get("cs_by_programme", [])
                         if r.get("campaign") == program)


def _sch_cs_total(d):
    return sum(_num(r.get("total")) for r in d.get("cs_by_programme", []))


# ─────────────────────────────────────────────────────────────────────────────
# The per-client spec — the comprehensive list of every important data pull that
# feeds each dashboard, separated by source (one check per platform × metric,
# plus the lead/CS breakdowns broken out). Verified line-by-line against each
# client's sql/ views, job/main.py and dashboard JS (see status_dashboard/README.md).
#   sources : Snowflake source tables this client depends on (Transmission side).
#   reads_direct : True when the client reads Snowflake modelled views DIRECTLY (no BigQuery
#                  raw mirror in its path) → ingest freshness = the build's data_through.
#                  Now False for EVERY client: cloudflare moved onto the raw_snowflake mirror
#                  on 2026-06-17 (BQ owns its model now, like the rest), so the field is inert.
#   checks  : accuracy comparisons. `group` clusters checks by data domain in the UI;
#             `dash` extracts the comparable number from the client's JSON; `sql` is
#             the EXACT Snowflake query that should equal it.
# Only un-transformed integers are equality-checked (counts / impressions / clicks /
# conversions / leads / sessions). SPEND is deliberately never checked: most clients
# FX-convert it (AUD/SGD/JPY->USD) and even native spend is a float, so a rounded
# equality would read as a false ✗ — see the README "Data Accuracy" note.
# ─────────────────────────────────────────────────────────────────────────────
CLIENTS = [
    {
        "client": "mongodb", "label": "MongoDB APAC", "url": "https://mongodb.bidbrain.ai",
        "sources": ["TradeDesk_APAC ALL", "Salesforce_CS_APAC_ALL"],
        "reads_direct": False,
        "checks": [
            # --- Trade Desk paid media (rows[] = the whole-flight pass-through) ----
            {"label": "Trade Desk · Impressions", "kind": "sum", "group": "Trade Desk",
             "dash": _mdb_rows("imps"),
             "sql": "SELECT SUM(COALESCE(IMPRESSIONS, IMPRESSION)) AS imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'MongoDB';",
             "note": "COALESCE(IMPRESSIONS, IMPRESSION): the source carries both a current and a legacy "
                     "singular column. Clean integer (no FX). vs sum(rows[].imps)."},
            {"label": "Trade Desk · Clicks", "kind": "sum", "group": "Trade Desk",
             "dash": _mdb_rows("clicks"),
             "sql": "SELECT SUM(CLICKS) AS clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'MongoDB';",
             "note": "Clean integer pass-through. vs sum(rows[].clicks)."},
            {"label": "Trade Desk · Conversions (click+view)", "kind": "sum", "group": "Trade Desk",
             "dash": _mdb_rows("conversions"),
             "sql": "SELECT SUM(TOTAL_CLICK_PLUS_VIEW_CONVERSIONS) AS conversions\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'MongoDB';",
             "note": "The blended click+view conversion count. The per-Universal-Pixel breakout is a "
                     "static seed (not in Snowflake) — see the README. vs sum(rows[].conversions)."},

            # --- Content Syndication — DNB (3 programme campaigns) ----------------
            # DNB rows in cs_by_programme carry a non-null programme label; total = the
            # delivered statuses (New + Unresponsive + Accepted), NOT COUNT(*).
            {"label": "DNB · Total leads", "kind": "count", "group": "Content Syndication — DNB",
             "dash": _mdb_dnb("total"),
             "sql": "SELECT COUNT(*) AS dnb_total_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3','701RG00001GvvrDYAR')\n"
                    "  AND LEAD_STATUS IN ('New','Unresponsive','Accepted');",
             "note": "The 3 DNB programme campaigns (DtQcz / HcDIV / Gvvr). DNB delivered total = "
                     "New + Unresponsive + Accepted ONLY — EXCLUDES 'Unqualified' / 'Rejected', so it is "
                     "NOT COUNT(*) (COUNT(*) over-counts by the 3 'Unqualified' Technical-DMs leads: 402 vs "
                     "399). vs sum(cs_by_programme[programme≠null].total)." + _MDB_CS_NOTE},
            {"label": "DNB · Accepted", "kind": "count", "group": "Content Syndication — DNB",
             "dash": _mdb_dnb("accepted"),
             "sql": "SELECT COUNT(*) AS dnb_accepted\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3','701RG00001GvvrDYAR')\n"
                    "  AND LEAD_STATUS = 'Accepted';",
             "note": "DNB accepted = LEAD_STATUS = 'Accepted'. vs sum(cs_by_programme[DNB].accepted)." + _MDB_CS_NOTE},
            {"label": "DNB · New (Unresponsive + New)", "kind": "count", "group": "Content Syndication — DNB",
             "dash": _mdb_dnb("new"),
             "sql": "SELECT COUNT(*) AS dnb_new\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3','701RG00001GvvrDYAR')\n"
                    "  AND LEAD_STATUS IN ('Unresponsive','New');",
             "note": "DNB 'New' bucket = Unresponsive + New (does NOT include 'Do Not Contact' — that is "
                     "KGA/IDC only). vs sum(cs_by_programme[DNB].new)." + _MDB_CS_NOTE},
            {"label": "DNB · Rejected", "kind": "count", "group": "Content Syndication — DNB",
             "dash": _mdb_dnb("rejected"),
             "sql": "SELECT COUNT(*) AS dnb_rejected\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3','701RG00001GvvrDYAR')\n"
                    "  AND LEAD_STATUS = 'Rejected';",
             "note": "DNB rejected = LEAD_STATUS = 'Rejected'. vs sum(cs_by_programme[DNB].rejected)." + _MDB_CS_NOTE},

            # --- Content Syndication — KGA(IDC) (campaign NKKwQYAX) ---------------
            # KGA/IDC has a NULL PROGRAMME_LABEL -> the only null-programme rows in
            # cs_by_programme, and its 'delivered' definition DIFFERS from DNB.
            {"label": "KGA(IDC) · Delivered leads", "kind": "count", "group": "Content Syndication — KGA(IDC)",
             "dash": _mdb_idc("total"),
             "sql": "SELECT COUNT(*) AS idc_delivered_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID = '701RG00001NKKwQYAX'\n"
                    "  AND LEAD_STATUS IN ('Unresponsive','Do Not Contact','New');",
             "note": "KGA(IDC) is campaign NKKwQYAX — its delivered-leads definition is Unresponsive + "
                     "Do Not Contact + New ONLY (no Accepted/Rejected lifecycle), which is why the dash "
                     "stores its total as that 3-status count (NOT COUNT(*)). vs the KGA/IDC row "
                     "(programme = null) total in cs_by_programme. This was previously MISSING from the monitor." + _MDB_CS_NOTE},
        ],
    },
    {
        "client": "cloudflare", "label": "Cloudflare APAC", "url": "https://cloudflare.bidbrain.ai",
        "sources": ["Salesforce_CS_APAC_ALL", "TradeDesk_APAC ALL",
                    "LinkedIn Ads - APAC", "Reddit Ads - APAC_ALL"],
        "reads_direct": False,   # BQ owns the model since 2026-06-17 — reads raw_snowflake mirrors
        "cs_from_definitions": "cloudflare",   # CS checks built from definitions/cloudflare.json at runtime
        "checks": [
            # --- Paid media ---
            # The dashboard's paid_media.rows[] are now derived in BigQuery (stg_* over the
            # raw_snowflake mirrors → paid_media_model). The SQL below still queries Snowflake's
            # V_PAID_ADS_FINAL_MODEL as the independent source of truth, so this validates the
            # whole chain (mirror sync + BQ port). These channel sums are append-only/daily, so
            # they match exactly when the mirror is in sync.
            {"label": "Trade Desk · Impressions", "kind": "sum", "group": "Trade Desk",
             "dash": _cf_pm("imps", {"TTD", "TradeDesk"}),
             "sql": "SELECT SUM(IMPS) AS imps\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL IN ('TTD','TradeDesk');",
             "note": "Reads the CF modelled view directly (not the raw mirror). vs sum of paid_media.rows[] "
                     "where channel is TTD/TradeDesk."},
            {"label": "Trade Desk · Clicks", "kind": "sum", "group": "Trade Desk",
             "dash": _cf_pm("clicks", {"TTD", "TradeDesk"}),
             "sql": "SELECT SUM(CLICKS) AS clicks\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL IN ('TTD','TradeDesk');",
             "note": "vs sum of paid_media.rows[] clicks where channel is TTD/TradeDesk."},
            {"label": "LinkedIn · Impressions", "kind": "sum", "group": "LinkedIn (paid media)",
             "dash": _cf_pm("imps", {"LinkedIn", "LI"}),
             "sql": "SELECT SUM(IMPS) AS imps\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL IN ('LinkedIn','LI');",
             "note": "vs sum of paid_media.rows[] imps where channel is LinkedIn/LI."},
            {"label": "LinkedIn · Clicks", "kind": "sum", "group": "LinkedIn (paid media)",
             "dash": _cf_pm("clicks", {"LinkedIn", "LI"}),
             "sql": "SELECT SUM(CLICKS) AS clicks\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL IN ('LinkedIn','LI');",
             "note": "vs sum of paid_media.rows[] clicks where channel is LinkedIn/LI."},
            {"label": "LinkedIn · Leads", "kind": "sum", "group": "LinkedIn (paid media)",
             "dash": _cf_pm("leads", {"LinkedIn", "LI"}),
             "sql": "SELECT SUM(LEADS) AS leads\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL IN ('LinkedIn','LI');",
             "note": "LinkedIn is the only paid channel reporting leads (TTD/Reddit/LINE carry 0). "
                     "vs sum of paid_media.rows[] leads where channel is LinkedIn/LI."},
            {"label": "Reddit · Impressions", "kind": "sum", "group": "Reddit",
             "dash": _cf_pm("imps", {"Reddit"}),
             "sql": "SELECT SUM(IMPS) AS imps\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL = 'Reddit';",
             "note": "Reddit spend is native USD here (no ×2 markup — that is resetdata-only). "
                     "vs sum of paid_media.rows[] imps where channel = Reddit."},
            {"label": "Reddit · Clicks", "kind": "sum", "group": "Reddit",
             "dash": _cf_pm("clicks", {"Reddit"}),
             "sql": "SELECT SUM(CLICKS) AS clicks\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL = 'Reddit';",
             "note": "vs sum of paid_media.rows[] clicks where channel = Reddit."},
            {"label": "LINE · Impressions", "kind": "sum", "group": "LINE",
             "dash": _cf_pm("imps", {"LINE"}),
             "sql": "SELECT SUM(IMPS) AS imps\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL = 'LINE';",
             "note": "LINE imps/clicks are clean integers; only its USD spend is FX-derived (JPY/155), so "
                     "spend is not checked. vs sum of paid_media.rows[] imps where channel = LINE."},
            {"label": "LINE · Clicks", "kind": "sum", "group": "LINE",
             "dash": _cf_pm("clicks", {"LINE"}),
             "sql": "SELECT SUM(CLICKS) AS clicks\n"
                    "FROM CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL\n"
                    "WHERE CHANNEL = 'LINE';",
             "note": "vs sum of paid_media.rows[] clicks where channel = LINE."},

            # --- Content Syndication checks (CS quality + Korea & RIG + CF1 Double-Touch) are APPENDED
            #     AT RUNTIME from definitions/cloudflare.json — see _build_cf_cs_checks() + main(). ---

            # --- Single-campaign LinkedIn dashboards (raw_snowflake mirror) --------
            # Each is its own dashboard, filtered by an exact CAMPAIGN_GROUP_NAME.
            {"label": "ANZ PEYC · Impressions", "kind": "sum", "group": "LinkedIn — ANZ PEYC",
             "dash": _cf_camp("peyc", "imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_"
                    "APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-PEYC';",
             "note": "Built via the raw_snowflake.linkedin_ads_apac mirror, so it equals Snowflake only "
                     "when the mirror is in sync. vs campaigns.peyc.totals.imps."},
            {"label": "ANZ PEYC · Leads", "kind": "sum", "group": "LinkedIn — ANZ PEYC",
             "dash": _cf_camp("peyc", "leads"),
             "sql": "SELECT SUM(IFNULL(LEADS,0)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_"
                    "APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-PEYC';",
             "note": "vs campaigns.peyc.totals.leads."},
            {"label": "CF1 India · Impressions", "kind": "sum", "group": "LinkedIn — CF1 India",
             "dash": _cf_camp("cf1_india", "imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_"
                    "APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_CF1-Integrated';",
             "note": "vs campaigns.cf1_india.totals.imps."},
            {"label": "CF1 India · Leads", "kind": "sum", "group": "LinkedIn — CF1 India",
             "dash": _cf_camp("cf1_india", "leads"),
             "sql": "SELECT SUM(IFNULL(LEADS,0)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_"
                    "APAC-IN_IN_MOFU_GENERAL_X_AWR-CONS_CF1-Integrated';",
             "note": "vs campaigns.cf1_india.totals.leads."},
            {"label": "Coles Hyper · Impressions", "kind": "sum", "group": "LinkedIn — Coles Hyper",
             "dash": _cf_camp("coles_hyper", "imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_MDS_LINKEDIN_GENERAL_SI_"
                    "APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_Hyper_COLES';",
             "note": "Note _MDS_ (not _CNC_) in the group name. vs campaigns.coles_hyper.totals.imps."},
            {"label": "Coles Hyper · Leads", "kind": "sum", "group": "LinkedIn — Coles Hyper",
             "dash": _cf_camp("coles_hyper", "leads"),
             "sql": "SELECT SUM(IFNULL(LEADS,0)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_MDS_LINKEDIN_GENERAL_SI_"
                    "APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_Hyper_COLES';",
             "note": "vs campaigns.coles_hyper.totals.leads."},
        ],
    },
    {
        "client": "stt", "label": "STT GDC", "url": "https://stt.bidbrain.ai",
        "sources": ["Google Analytics Data_APAC ALL", "Google Ads - APAC",
                    "LinkedIn Ads - APAC", "DV360 - APAC"],
        "reads_direct": False,
        "checks": [
            # --- Google Ads (CAMPAIGN_NAME LIKE '%STT%') --------------------------
            {"label": "Google Ads · Impressions", "kind": "sum", "group": "Google Ads",
             "dash": _kpi("ga_imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS ga_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Ads - APAC\"\n"
                    "WHERE CAMPAIGN_NAME LIKE '%STT%';",
             "note": "Whole flight, no date floor — the '%STT%' campaign-name LIKE is the only filter. vs kpi.ga_imps."},
            {"label": "Google Ads · Clicks", "kind": "sum", "group": "Google Ads",
             "dash": _kpi("ga_clicks"),
             "sql": "SELECT SUM(CLICKS) AS ga_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Ads - APAC\"\n"
                    "WHERE CAMPAIGN_NAME LIKE '%STT%';",
             "note": "vs kpi.ga_clicks."},
            # --- LinkedIn (ACCOUNT_ID IN the two STT accounts) --------------------
            {"label": "LinkedIn · Impressions", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS li_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_ID IN ('515691430','511609128');",
             "note": "Two accounts: 515691430 (SGD) + 511609128 (USD). vs kpi.li_imps."},
            {"label": "LinkedIn · Clicks", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_clicks"),
             "sql": "SELECT SUM(CLICKS) AS li_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_ID IN ('515691430','511609128');",
             "note": "vs kpi.li_clicks."},
            # --- DV360 (ADVERTISER_ID IN the two STT advertisers) -----------------
            {"label": "DV360 · Impressions", "kind": "sum", "group": "DV360",
             "dash": _kpi("dv_imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS dv_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "WHERE ADVERTISER_ID IN ('7572338345','6466367438');",
             "note": "vs kpi.dv_imps."},
            {"label": "DV360 · Clicks", "kind": "sum", "group": "DV360",
             "dash": _kpi("dv_clicks"),
             "sql": "SELECT SUM(CLICKS) AS dv_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "WHERE ADVERTISER_ID IN ('7572338345','6466367438');",
             "note": "vs kpi.dv_clicks."},
            # --- Blended rollup (the headline KPIs) -------------------------------
            {"label": "All paid channels · Impressions", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_imps"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_ID IN ('515691430','511609128'))\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE ADVERTISER_ID IN ('7572338345','6466367438'))\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Ads - APAC\"\n"
                    "     WHERE CAMPAIGN_NAME LIKE '%STT%') AS total_ad_imps;",
             "note": "LinkedIn + DV360 + Google Ads. Clean integer sums (spend is FX-converted, never checked). vs kpi.ad_imps."},
            {"label": "All paid channels · Clicks", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_clicks"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_ID IN ('515691430','511609128'))\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE ADVERTISER_ID IN ('7572338345','6466367438'))\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Ads - APAC\"\n"
                    "     WHERE CAMPAIGN_NAME LIKE '%STT%') AS total_ad_clicks;",
             "note": "Same three filters as impressions. vs kpi.ad_clicks."},
            # --- GA4 website (PROPERTY_ID 318963196, campaign-window date floor) ---
            {"label": "GA4 · Sessions", "kind": "sum", "group": "GA4 (website)",
             "dash": _kpi("sessions"),
             "sql": "SELECT COALESCE(SUM(CASE WHEN EVENT_NAME = 'session_start' THEN SESSIONS ELSE 0 END),0)\n"
                    "         AS ga4_sessions\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Analytics Data_APAC ALL\"\n"
                    "WHERE PROPERTY_ID = '318963196' AND TO_DATE(DAY) >= DATE '2025-06-01';",
             "note": "GA4 is event-grained: SESSIONS repeats on every event row, so sessions come ONLY from "
                     "session_start rows. vs kpi.sessions (whole property; the on-screen headline drops 'Global')."},
            {"label": "GA4 · Engaged sessions", "kind": "sum", "group": "GA4 (website)",
             "dash": _kpi("engaged_sessions"),
             "sql": "SELECT COALESCE(SUM(CASE WHEN EVENT_NAME = 'user_engagement' THEN SESSIONS ELSE 0 END),0)\n"
                    "         AS ga4_engaged\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Analytics Data_APAC ALL\"\n"
                    "WHERE PROPERTY_ID = '318963196' AND TO_DATE(DAY) >= DATE '2025-06-01';",
             "note": "Engaged sessions use the user_engagement event grain. vs kpi.engaged_sessions."},
            {"label": "GA4 · Key events (conversions)", "kind": "sum", "group": "GA4 (website)",
             "dash": _kpi("conversions"),
             "sql": "SELECT COALESCE(SUM(CASE WHEN EVENT_NAME IN\n"
                    "         ('contact_submit_success','generate_lead','newsletter_subscribe_success')\n"
                    "         THEN KEY_EVENTS ELSE 0 END),0) AS ga4_key_events\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Analytics Data_APAC ALL\"\n"
                    "WHERE PROPERTY_ID = '318963196' AND TO_DATE(DAY) >= DATE '2025-06-01';",
             "note": "Headline 'Key events' = a fixed 3-event allowlist summed over KEY_EVENTS. vs kpi.conversions."},
            {"label": "GA4 · Ad-driven (paid) sessions", "kind": "sum", "group": "GA4 (website)",
             "dash": _kpi("paid_sessions"),
             "sql": "SELECT COALESCE(SUM(CASE WHEN EVENT_NAME = 'session_start'\n"
                    "         AND CHANNEL_GROUPING IN ('Paid Search','Paid Social','Paid Other','Cross-network','Display')\n"
                    "         THEN SESSIONS ELSE 0 END),0) AS ga4_paid_sessions\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Analytics Data_APAC ALL\"\n"
                    "WHERE PROPERTY_ID = '318963196' AND TO_DATE(DAY) >= DATE '2025-06-01';",
             "note": "Paid bucket = the 5 paid CHANNEL_GROUPING values (incl. Display + Cross-network), "
                     "session_start only. vs kpi.paid_sessions."},
        ],
    },
    {
        "client": "hireright", "label": "HireRight APAC", "url": "https://hireright.bidbrain.ai",
        "sources": ["DV360 - APAC", "LinkedIn Ads - APAC", "TradeDesk_APAC ALL"],
        "reads_direct": False,
        "checks": [
            # --- DV360 (LOWER(ADVERTISER_NAME) LIKE '%hireright%') ----------------
            {"label": "DV360 · Impressions", "kind": "sum", "group": "DV360",
             "dash": _kpi("dv_imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS dv_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%';",
             "note": "Case-insensitive substring filter. vs kpi.dv_imps."},
            {"label": "DV360 · Clicks", "kind": "sum", "group": "DV360",
             "dash": _kpi("dv_clicks"),
             "sql": "SELECT SUM(CLICKS) AS dv_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%';",
             "note": "vs kpi.dv_clicks."},
            {"label": "DV360 · Conversions", "kind": "sum", "group": "DV360",
             "dash": _kpi("dv_conv"),
             "sql": "SELECT SUM(CONVERSIONS_TOTAL) AS dv_conv\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%';",
             "note": "DV360's conversion column is CONVERSIONS_TOTAL. vs kpi.dv_conv."},
            # --- Trade Desk (ADVERTISER_NAME = 'HireRight') -----------------------
            {"label": "Trade Desk · Impressions", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_imps"),
             "sql": "SELECT SUM(COALESCE(IMPRESSIONS, IMPRESSION)) AS td_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'HireRight';",
             "note": "COALESCE(IMPRESSIONS, IMPRESSION) (current + legacy column); exact advertiser '='. vs kpi.td_imps."},
            {"label": "Trade Desk · Clicks", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_clicks"),
             "sql": "SELECT SUM(CLICKS) AS td_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'HireRight';",
             "note": "vs kpi.td_clicks."},
            {"label": "Trade Desk · Conversions (click+view)", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_conv"),
             "sql": "SELECT SUM(TOTAL_CLICK_PLUS_VIEW_CONVERSIONS) AS td_conv\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'HireRight';",
             "note": "vs kpi.td_conv."},
            # --- LinkedIn (LOWER(ACCOUNT_NAME) LIKE 'hireright%') -----------------
            {"label": "LinkedIn · Impressions", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS li_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%';",
             "note": "Case-insensitive prefix filter. vs kpi.li_imps."},
            {"label": "LinkedIn · Clicks", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_clicks"),
             "sql": "SELECT SUM(CLICKS) AS li_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%';",
             "note": "vs kpi.li_clicks."},
            {"label": "LinkedIn · Leads", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_conv"),
             "sql": "SELECT SUM(LEADS) AS li_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%';",
             "note": "LinkedIn's 'conversion' metric here = SUM(LEADS). vs kpi.li_conv."},
            # --- Blended rollup (the Overview headline tiles) ---------------------
            {"label": "All paid channels · Impressions", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_imps"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(IMPRESSIONS, IMPRESSION)),0)\n"
                    "     FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\" WHERE ADVERTISER_NAME = 'HireRight')\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%') AS ad_imps;",
             "note": "DV360 + TradeDesk + LinkedIn. TradeDesk imps use COALESCE(IMPRESSIONS, IMPRESSION). vs kpi.ad_imps."},
            {"label": "All paid channels · Clicks", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_clicks"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'HireRight')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%') AS ad_clicks;",
             "note": "Same three filters as impressions. vs kpi.ad_clicks."},
            {"label": "All paid channels · Conversions", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_conv"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CONVERSIONS_TOTAL),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%')\n"
                    "+ (SELECT COALESCE(SUM(TOTAL_CLICK_PLUS_VIEW_CONVERSIONS),0)\n"
                    "     FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\" WHERE ADVERTISER_NAME = 'HireRight')\n"
                    "+ (SELECT COALESCE(SUM(LEADS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%') AS ad_conv;",
             "note": "Heterogeneous: DV360 CONVERSIONS_TOTAL + TradeDesk click+view + LinkedIn LEADS. vs kpi.ad_conv."},
        ],
    },
    {
        "client": "schneider", "label": "Schneider Electric APAC", "url": "https://schneider.bidbrain.ai",
        "sources": ["DV360 - APAC", "LinkedIn Ads - APAC", "TradeDesk_APAC ALL",
                    "Salesforce_CS_APAC_ALL"],
        "reads_direct": False,
        "checks": [
            # RESTRUCTURED 2026-06-22: the old 6-tab Pacific paid-media dashboard (a kpi.* block of
            # DV360 / TradeDesk / LinkedIn delivery totals) became a client_mongodb-style Content-
            # Syndication clone scoped to 5 lead-gen programs (the 11 SF campaign IDs in
            # data/salesforce_map.csv). Two consequences for this monitor:
            #   1. kpi.* is GONE -> the old delivery checks are removed (they'd read missing keys = false ✗).
            #   2. PAID DELIVERY (pm_delivery) is now SEED-SCOPED via seed_campaign_map's match_pattern
            #      first-match-wins join, which has NO independent Snowflake definition to reproduce — so
            #      paid delivery is intentionally NOT equality-checked here. DV360 / TradeDesk / LinkedIn
            #      stay in `sources` because pm_delivery still READS them (they drive the Sync tab).
            # CS leads ARE Snowflake-checkable: known campaign IDs + the DETERMINISTIC flight clamp that
            # stg_salesforce (sql/17) applies — WHERE DAY within each program's seed_plan_budget flight.
            # The per-program flight bounds below MIRROR data/plan_budget.csv; if the client changes a
            # flight, update them here (same maintenance contract as the hardcoded campaign IDs).
            # Salesforce DAY is wrapped in TO_DATE() (repo convention) and SUM(COALESCE(LEADS,1)) ==
            # the view's SUM(leads). Status today is uniformly 'New' (CRM-raw), so total == new.
            # --- Content Syndication — per program (the 5 lead-gen programs) ------
            # Each program's dashboard lead count = sum of cs_by_programme[].total for that campaign.
            # SQL reproduces stg_salesforce exactly: the program's SF campaign IDs (data/salesforce_map.csv)
            # + the flight clamp (data/plan_budget.csv). Today every lead is 'New' (CRM-raw, ungraded).
            {"label": "Water & Environment · CS leads", "kind": "count", "group": "Content Syndication",
             "dash": _sch_cs_camp("water_env"),
             "sql": "SELECT SUM(COALESCE(LEADS,1)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001RTyAQYA1','701RG00001RUkTfYAL')\n"
                    "  AND TO_DATE(DAY) >= DATE '2026-04-30' AND TO_DATE(DAY) <= DATE '2027-01-31';",
             "note": "water_env = the 2 W&E pillar campaign IDs; flight 2026-04-30..2027-01-31 (mirrors "
                     "seed_plan_budget). vs sum of cs_by_programme[campaign='water_env'].total (54)." + _SCH_CS_NOTE},
            {"label": "EcoStruxure Building Activate (EBA) · CS leads", "kind": "count", "group": "Content Syndication",
             "dash": _sch_cs_camp("eba"),
             "sql": "SELECT SUM(COALESCE(LEADS,1)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID = '701RG00001OwE65YAF'\n"
                    "  AND TO_DATE(DAY) >= DATE '2026-05-25' AND TO_DATE(DAY) <= DATE '2026-08-31';",
             "note": "eba flight 2026-05-25..2026-08-31. The clamp EXCLUDES EBA's ~4 pre-flight spillover "
                     "leads (2026-05-21..24) exactly as the dashboard does. "
                     "vs cs_by_programme[campaign='eba'].total (83)." + _SCH_CS_NOTE},
            {"label": "Heavy Industries · CS leads", "kind": "count", "group": "Content Syndication",
             "dash": _sch_cs_camp("heavy"),
             "sql": "SELECT SUM(COALESCE(LEADS,1)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001KhQEcYAN','701RG00001T4zGfYAJ',\n"
                    "                      '701RG00001KhQL4YAN','701RG00001KhOntYAF')\n"
                    "  AND TO_DATE(DAY) >= DATE '2026-05-01' AND TO_DATE(DAY) <= DATE '2026-10-31';",
             "note": "heavy = the 4 Heavy-Industries campaign IDs; flight 2026-05-01..2026-10-31. heavy is "
                     "leads-only (no paid delivery). vs cs_by_programme[campaign='heavy'].total (152)." + _SCH_CS_NOTE},
            {"label": "Global Rebrand Activation · CS leads", "kind": "count", "group": "Content Syndication",
             "dash": _sch_cs_camp("global_rebrand"),
             "sql": "SELECT SUM(COALESCE(LEADS,1)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID = '701RG00001VHiiJYAT'\n"
                    "  AND TO_DATE(DAY) >= DATE '2026-07-01';",
             "note": "global_rebrand flight_start 2026-07-01 (no end seeded). Until then the clamp yields 0 "
                     "delivered leads (leads-only; no paid delivery). vs cs_by_programme[campaign="
                     "'global_rebrand'].total." + _SCH_CS_NOTE},
            {"label": "AirSeT · CS leads", "kind": "count", "group": "Content Syndication",
             "dash": _sch_cs_camp("airset"),
             "sql": "SELECT SUM(COALESCE(LEADS,1)) AS leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001VI10DYAT','701RG00001VbxRrYAJ','701RG00001VbvbTYAR')\n"
                    "  AND TO_DATE(DAY) >= DATE '2026-06-11' AND TO_DATE(DAY) <= DATE '2026-12-31';",
             "note": "airset = the 3 AirSeT campaign IDs in seed_salesforce_map (base + Roverpath MQL + Final Funnel); "
                     "Roverpath (701RG00001VbxRrYAJ) carries 7 leads from 2026-07-01. Flight 2026-06-11..2026-12-31. "
                     "vs cs_by_programme[campaign='airset'].total (7)." + _SCH_CS_NOTE},
            # --- Content Syndication — combined headline -------------------------
            {"label": "All 5 programs · Total CS leads", "kind": "count", "group": "Content Syndication",
             "dash": _sch_cs_total,
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(COALESCE(LEADS,1)),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "     WHERE CAMPAIGN_ID IN ('701RG00001RTyAQYA1','701RG00001RUkTfYAL')\n"
                    "       AND TO_DATE(DAY) >= DATE '2026-04-30' AND TO_DATE(DAY) <= DATE '2027-01-31')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(LEADS,1)),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "     WHERE CAMPAIGN_ID = '701RG00001OwE65YAF'\n"
                    "       AND TO_DATE(DAY) >= DATE '2026-05-25' AND TO_DATE(DAY) <= DATE '2026-08-31')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(LEADS,1)),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "     WHERE CAMPAIGN_ID IN ('701RG00001KhQEcYAN','701RG00001T4zGfYAJ','701RG00001KhQL4YAN','701RG00001KhOntYAF')\n"
                    "       AND TO_DATE(DAY) >= DATE '2026-05-01' AND TO_DATE(DAY) <= DATE '2026-10-31')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(LEADS,1)),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "     WHERE CAMPAIGN_ID = '701RG00001VHiiJYAT'\n"
                    "       AND TO_DATE(DAY) >= DATE '2026-07-01')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(LEADS,1)),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "     WHERE CAMPAIGN_ID IN ('701RG00001VI10DYAT','701RG00001VbxRrYAJ','701RG00001VbvbTYAR')\n"
                    "       AND TO_DATE(DAY) >= DATE '2026-06-11' AND TO_DATE(DAY) <= DATE '2026-12-31')\n"
                    "  AS total_cs_leads;",
             "note": "Sum of the 5 programs' flight-clamped lead counts (296 today: water_env 54 / eba 83 / "
                     "heavy 152 / airset 7 / global_rebrand 0). vs sum of all cs_by_programme[].total." + _SCH_CS_NOTE},
        ],
    },
    {
        "client": "proptrack", "label": "PropTrack APAC", "url": "https://proptrack.bidbrain.ai",
        "sources": ["TradeDesk_APAC ALL", "LinkedIn Ads - APAC"],
        "reads_direct": False,
        "checks": [
            # --- Trade Desk (ADVERTISER_NAME = 'PopTrack' — note the spelling) ----
            # TradeDesk impressions live in the SINGULAR column IMPRESSION (the plural
            # IMPRESSIONS is NULL for this advertiser); LinkedIn uses the plural.
            {"label": "Trade Desk · Impressions", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_imps"),
             "sql": "SELECT SUM(IMPRESSION) AS td_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'PopTrack';",
             "note": "MUST use IMPRESSION (singular) — the plural is NULL here. Advertiser spelled 'PopTrack' "
                     "on TradeDesk. vs kpi.td_imps."},
            {"label": "Trade Desk · Clicks", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_clicks"),
             "sql": "SELECT SUM(CLICKS) AS td_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'PopTrack';",
             "note": "vs kpi.td_clicks."},
            {"label": "Trade Desk · Conversions (click+view total)", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_conv"),
             "sql": "SELECT SUM(TOTAL_CLICK_PLUS_VIEW_CONVERSIONS) AS td_conv\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'PopTrack';",
             "note": "Should equal td_click_conv + td_vt_conv below. vs kpi.td_conv."},
            {"label": "Trade Desk · Click conversions", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_click_conv"),
             "sql": "SELECT SUM(CLICK_CONVERSION) AS td_click_conv\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'PopTrack';",
             "note": "Column CLICK_CONVERSION (singular). vs kpi.td_click_conv."},
            {"label": "Trade Desk · View-through conversions", "kind": "sum", "group": "Trade Desk",
             "dash": _kpi("td_vt_conv"),
             "sql": "SELECT SUM(VIEW_THROUGH_CONVERSION) AS td_vt_conv\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'PopTrack';",
             "note": "Column VIEW_THROUGH_CONVERSION (singular). vs kpi.td_vt_conv."},
            # --- LinkedIn (ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD') ---------
            {"label": "LinkedIn · Impressions", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_imps"),
             "sql": "SELECT SUM(IMPRESSIONS) AS li_imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';",
             "note": "LinkedIn uses IMPRESSIONS (plural) — opposite of TradeDesk. Account spelled 'PropTrack'. vs kpi.li_imps."},
            {"label": "LinkedIn · Clicks", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_clicks"),
             "sql": "SELECT SUM(CLICKS) AS li_clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';",
             "note": "vs kpi.li_clicks."},
            {"label": "LinkedIn · Engagements", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_eng"),
             "sql": "SELECT SUM(ENGAGEMENTS) AS li_eng\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';",
             "note": "vs kpi.li_eng."},
            {"label": "LinkedIn · Video views", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_video_views"),
             "sql": "SELECT SUM(VIDEO_VIEWS) AS li_video_views\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';",
             "note": "vs kpi.li_video_views."},
            {"label": "LinkedIn · Leads", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_leads"),
             "sql": "SELECT SUM(LEADS) AS li_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';",
             "note": "vs kpi.li_leads (LinkedIn CONVERSIONS is ~0; leads tracked via LEADS/LEAD_FORM_OPENS)."},
            {"label": "LinkedIn · Lead-form opens", "kind": "sum", "group": "LinkedIn",
             "dash": _kpi("li_lead_opens"),
             "sql": "SELECT SUM(LEAD_FORM_OPENS) AS li_lead_opens\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';",
             "note": "vs kpi.li_lead_opens."},
            # --- Blended rollup ---------------------------------------------------
            {"label": "All paid channels · Impressions", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_imps"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSION),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'PopTrack')\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD') AS ad_imps;",
             "note": "The blend mixes IMPRESSION (TradeDesk, singular) with IMPRESSIONS (LinkedIn, plural) — "
                     "wrong column on either side breaks the rollup. vs kpi.ad_imps."},
            {"label": "All paid channels · Clicks", "kind": "sum", "group": "All paid channels",
             "dash": _kpi("ad_clicks"),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'PopTrack')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD') AS ad_clicks;",
             "note": "Both channels use CLICKS. vs kpi.ad_clicks."},
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Definitions-driven checks. The SINGLE SOURCE OF TRUTH for a client's churny CS
# parameters (campaign-ID filter, KR/RIG segment sets, geographic map, market
# chips, status buckets) is definitions/<client>.json in the status bucket. The
# CLIENT side loads the same file into client_<c>.seed_* tables (definitions_seed.py)
# that its views read; here we rebuild the EXACT Snowflake verification SQL from it.
# Editing that one file (via the platform Data Accuracy tab → "Make this live")
# changes BOTH sides at once. When the file equals the old literals this is a no-op.
# ─────────────────────────────────────────────────────────────────────────────
def _sql_inlist(vals):
    """Render a python list as a SQL IN(...) body: 'a', 'b' (single-quotes escaped)."""
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)


def read_definitions(client):
    """Read the LIVE single-source-of-truth doc gs://{BUCKET}/definitions/{client}.json -> dict.
    Raises if absent (the caller logs the failure and skips that client's definition-built checks)."""
    blob = storage.Client(project=PROJECT).bucket(BUCKET).blob(f"definitions/{client}.json")
    return json.loads(blob.download_as_bytes())


def _cf_cs_cte(defs):
    """Rebuild cloudflare's CS region CTE (sql/10's REGION_GRP logic) from definitions.json —
    byte-equivalent to sql/10: country match is case-normalised (UPPER(TRIM)), KR = Korea in the 6
    El* campaigns (2026-07-02, seed_kr_campaign_ids), and the geographic arms are the 11-market grain.
    RIG then KR are evaluated BEFORE the geographic buckets; the geographic arms follow in declared
    order. REGION_GRP='OTHER' (the ELSE) now holds Korea leads outside the 6 KR campaigns."""
    def esc(s):
        return str(s).replace("'", "''")
    def upinlist(vals):   # uppercased in-list to match sql/10's UPPER(TRIM(COUNTRY_NAME))
        return _sql_inlist([str(v).upper() for v in vals])
    src = defs["source_table_snowflake"]
    cs_ids = [c["id"] for c in defs["cs_campaigns"]]
    kr, rig, geo = defs["segments"]["KR"], defs["segments"]["RIG"], defs["geographic_regions"]
    arms = [
        "          WHEN UPPER(TRIM(COUNTRY_NAME)) <> '%s' AND ASSET_2 IN (%s) AND CAMPAIGN_ID IN (%s) THEN 'RIG'"
        % (esc(rig["exclude_country"]).upper(), _sql_inlist(rig["asset_2"]), _sql_inlist(rig["campaign_ids"])),
        "          WHEN UPPER(TRIM(COUNTRY_NAME)) = '%s' AND CAMPAIGN_ID IN (%s) THEN 'KR'"
        % (esc(kr["country"]).upper(), _sql_inlist(kr["campaign_ids"])),
    ]
    for region_name, countries in geo.items():
        if region_name.startswith("_"):
            continue
        arms.append("          WHEN UPPER(TRIM(COUNTRY_NAME)) IN (%s) THEN '%s'" % (upinlist(countries), region_name))
    return ("WITH cf_cs AS (\n"
            "  SELECT LEAD_STATUS,\n"
            "    CASE\n" + "\n".join(arms) + "\n          ELSE 'OTHER'\n    END AS REGION_GRP\n"
            "  FROM " + src + "\n"
            "  WHERE CAMPAIGN_ID IN (" + _sql_inlist(cs_ids) + ")\n"
            ")\n")


def _build_cf_cs_checks(defs):
    """Cloudflare's Content-Syndication checks (4 CS quality + Korea, RIG & OTHER residual + 4 CF1), built
    entirely from definitions.json. Core CS counts span the whole 12-campaign universe (all regions
    incl. the OTHER residual) — a pipeline-integrity check on pacing.rows[]. NOTE (2026-07-02): the
    dashboard's *displayed* CS total excludes OTHER (its totals sum over the 11 market chips, and KR is
    now the 6 El* campaigns), so the displayed total runs ~55 below this whole-universe count (live 2026-07-02)."""
    src = defs["source_table_snowflake"]
    buckets = defs["status_buckets"]
    kr, rig = defs["segments"]["KR"], defs["segments"]["RIG"]
    cs_ids = [c["id"] for c in defs["cs_campaigns"]]
    cf1_ids = [c["id"] for c in defs["cf1_cs_campaigns"]]
    cte = _cf_cs_cte(defs)

    def esc(s):
        return str(s).replace("'", "''")

    def total_leads(d):
        # Whole 12-campaign CS universe — every market (no residual since 2026-06-25). The total
        # is unchanged by the re-bucketing; only which market each lead lands in changed.
        return sum(1 for r in d.get("pacing", {}).get("rows", [])
                   if not _is_dummy(r) and r.get("LEAD_STATUS") is not None)

    def status(statuses):
        s = set(statuses)
        return lambda d: sum(1 for r in d.get("pacing", {}).get("rows", [])
                             if not _is_dummy(r) and r.get("LEAD_STATUS") in s)

    def region(rg):
        return lambda d: sum(1 for r in d.get("pacing", {}).get("rows", [])
                             if not _is_dummy(r) and r.get("LEAD_STATUS") is not None
                             and r.get("MARKET_REGION") == rg)

    def cf1cs(field):
        return lambda d: _num(d.get("campaigns", {}).get("cf1_india", {}).get("cs", {}).get(field))

    return [
        {"label": "CS · Total leads", "kind": "count", "group": "Content Syndication",
         "dash": total_leads,
         "sql": cte + "SELECT COUNT(*) AS total_leads\nFROM cf_cs\n"
                "WHERE LEAD_STATUS IS NOT NULL;",
         "note": "SQL = the dash pipeline itself (definitions.json: campaign filter + client-defined "
                 "REGION_GRP), the whole 12-campaign universe — every one of the 11 markets (no residual). "
                 "Counts every non-null status (incl. New). vs the same count over pacing.rows[] "
                 "(all markets)." + _CF_CS_NOTE},
        {"label": "CS · Accepted (Accepted+Replied+Unresponsive)", "kind": "count", "group": "Content Syndication",
         "dash": status(buckets["accepted"]),
         "sql": cte + "SELECT COUNT(*) AS accepted_leads\nFROM cf_cs\n"
                "WHERE LEAD_STATUS IN (%s);" % _sql_inlist(buckets["accepted"]),
         "note": "Cloudflare's Accepted bucket = %s (OPPOSITE of mongodb). All 11 markets, no region "
                 "filter (every lead is counted in some market). vs the same count over pacing.rows[]."
                 % " + ".join(buckets["accepted"]) + _CF_CS_NOTE},
        {"label": "CS · Rejected", "kind": "count", "group": "Content Syndication",
         "dash": status(buckets["rejected"]),
         "sql": cte + "SELECT COUNT(*) AS rejected_leads\nFROM cf_cs\n"
                "WHERE LEAD_STATUS IN (%s);" % _sql_inlist(buckets["rejected"]),
         "note": "vs count of pacing.rows[] with a Rejected status (all regions)." + _CF_CS_NOTE},
        {"label": "CS · New / unprocessed", "kind": "count", "group": "Content Syndication",
         "dash": status(buckets["new"]),
         "sql": cte + "SELECT COUNT(*) AS new_leads\nFROM cf_cs\n"
                "WHERE LEAD_STATUS IN (%s);" % _sql_inlist(buckets["new"]),
         "note": "On the dash this is derived (total - accepted - rejected); checked here directly "
                 "over pacing.rows[] (all regions)." + _CF_CS_NOTE},
        {"label": "Korea Leads · Total (KR bucket)", "kind": "count", "group": "Content Syndication — Korea, RIG & residual",
         "dash": region("KR"),
         "sql": "SELECT COUNT(*) AS korea_leads\nFROM " + src + "\n"
                "WHERE UPPER(TRIM(COUNTRY_NAME)) = '%s'\n  AND CAMPAIGN_ID IN (%s);"
                % (esc(kr["country"]).upper(), _sql_inlist(kr["campaign_ids"])),
         "note": "Korea Leads = Country '%s' leads in the 6 ORIGINAL El* CS campaigns ONLY (2026-07-02: "
                 "reverted the 2026-06-25 all-Korea rule at the client's request; Korea leads outside "
                 "these 6 land in OTHER). vs the count of pacing.rows[] with MARKET_REGION = 'KR'."
                 % kr["country"] + _CF_CS_NOTE},
        {"label": "RIG Leads · Total (RIG bucket)", "kind": "count", "group": "Content Syndication — Korea, RIG & residual",
         "dash": region("RIG"),
         "sql": "SELECT COUNT(*) AS rig_leads\nFROM " + src + "\n"
                "WHERE UPPER(TRIM(COUNTRY_NAME)) <> '%s'\n  AND ASSET_2 IN (%s)\n  AND CAMPAIGN_ID IN (%s);"
                % (esc(rig["exclude_country"]).upper(), _sql_inlist(rig["asset_2"]), _sql_inlist(rig["campaign_ids"])),
         "note": "RIG Leads = NON-Korea AND the Modernize-Applications asset(s) AND the Final Funnel "
                 "campaigns. Asset-based, so it spans all countries — the dashboard's RIG bucket. vs the "
                 "count of pacing.rows[] with MARKET_REGION = 'RIG'." + _CF_CS_NOTE},
        {"label": "Residual (OTHER: Korea outside the 6 KR campaigns)", "kind": "count",
         "group": "Content Syndication — Korea, RIG & residual", "dash": region("OTHER"),
         "sql": cte + "SELECT COUNT(*) AS other_leads\nFROM cf_cs\nWHERE REGION_GRP = 'OTHER';",
         "note": "2026-07-02: with KR restricted to the 6 El* campaigns, REGION_GRP='OTHER' holds the "
                 "Korea leads from the other 6 campaigns (~55 live 2026-07-02) plus any brand-new/unmapped "
                 "country. OTHER is NOT a market chip, so these are excluded from the dashboard; this check "
                 "just reconciles the dash's OTHER count to Snowflake. A jump well beyond the Korea residual "
                 "means a new unmapped country needs adding to geographic_regions. vs the count of "
                 "pacing.rows[] with MARKET_REGION = 'OTHER'." + _CF_CS_NOTE},
        {"label": "CF1 CS · Accepted (delivered Double Touch MQLs)", "kind": "count",
         "group": "Content Syndication — CF1 (Double Touch)", "dash": cf1cs("accepted"),
         "sql": "SELECT COUNT(*) AS cf1_cs_accepted\nFROM " + src + "\n"
                "WHERE CAMPAIGN_ID IN (%s)\n  AND LEAD_STATUS = 'Accepted';" % _sql_inlist(cf1_ids),
         "note": "CF1's Double-Touch CS campaigns. Accepted = the delivered double-touch MQL count "
                 "(counts toward the 110 target). vs campaigns.cf1_india.cs.accepted." + _CF_CS_NOTE},
        {"label": "CF1 CS · Rejected", "kind": "count",
         "group": "Content Syndication — CF1 (Double Touch)", "dash": cf1cs("rejected"),
         "sql": "SELECT COUNT(*) AS cf1_cs_rejected\nFROM " + src + "\n"
                "WHERE CAMPAIGN_ID IN (%s)\n  AND LEAD_STATUS = 'Rejected';" % _sql_inlist(cf1_ids),
         "note": "vs campaigns.cf1_india.cs.rejected." + _CF_CS_NOTE},
        {"label": "CF1 CS · New", "kind": "count",
         "group": "Content Syndication — CF1 (Double Touch)", "dash": cf1cs("new"),
         "sql": "SELECT COUNT(*) AS cf1_cs_new\nFROM " + src + "\n"
                "WHERE CAMPAIGN_ID IN (%s)\n  AND LEAD_STATUS = 'New';" % _sql_inlist(cf1_ids),
         "note": "Today the 2 campaigns carry only Accepted/Rejected, so New is normally 0. "
                 "vs campaigns.cf1_india.cs.new." + _CF_CS_NOTE},
        {"label": "CF1 CS · Total leads (New + Accepted)", "kind": "count",
         "group": "Content Syndication — CF1 (Double Touch)", "dash": cf1cs("total"),
         "sql": "SELECT COUNT(*) AS cf1_cs_total\nFROM " + src + "\n"
                "WHERE CAMPAIGN_ID IN (%s)\n  AND LEAD_STATUS IN ('New','Accepted');" % _sql_inlist(cf1_ids),
         "note": "The client's headline 'Total Leads' = New + Accepted (deliberately NOT COUNT(*) — it "
                 "excludes Rejected). vs campaigns.cf1_india.cs.total." + _CF_CS_NOTE},
    ]


def _snowflake_key_bytes():
    """Snowflake private key (PEM) as bytes. Cloud Run injects SNOWFLAKE_KEY
    (--set-secrets); locally it falls back to Secret Manager via ADC. Mirrors
    clients/client_cloudflare/job/main.py and ingest/snowflake_data_pull/loader.py."""
    pem = os.environ.get("SNOWFLAKE_KEY")
    if pem is None:
        from google.cloud import secretmanager
        sm = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT}/secrets/snowflake-bq-key/versions/latest"
        pem = sm.access_secret_version(name=name).payload.data.decode("utf-8")
    return pem.encode()


def sf_connect():
    pkey = serialization.load_pem_private_key(_snowflake_key_bytes(), password=None)
    der = pkey.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    return snowflake.connector.connect(
        account=SF_ACCOUNT, user=SF_USER, private_key=der, warehouse=SF_WAREHOUSE)


def scalar(cn, sql):
    """Run a single-value Snowflake aggregate and return it as a python number/None."""
    cur = cn.cursor()
    try:
        cur.execute(sql)
        row = cur.fetchone()
        v = row[0] if row else None
        if v is None:
            return None
        return int(v) if float(v).is_integer() else float(v)
    finally:
        cur.close()


def read_json(bucket, obj):
    """Read a client's <client>.json from its bucket -> dict, or None if absent."""
    blob = storage.Client(project=PROJECT).bucket(bucket).blob(obj)
    if not blob.exists():
        return None
    return json.loads(blob.download_as_text())


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _verdict(transmission_latest, ingest_latest, has_json, now):
    """Decide who the staleness is coming from. Returns (verdict, t_state, d_state, caught_up).

    caught_up = our ingest has reached Snowflake's latest change (within the normal
    ingest-cadence tolerance). If caught up, 100% Digital is green no matter how old the
    data is -> any staleness is the SOURCE (Transmission). If not caught up, we're behind.
    """
    if not has_json or transmission_latest is None:
        return "no_data", "unknown", "unknown", None
    caught_up = (ingest_latest is not None
                 and ingest_latest >= transmission_latest - INGEST_LAG_TOLERANCE)
    t_age = now - transmission_latest
    if t_age <= datetime.timedelta(hours=36):
        t_state = "ok"
    elif t_age <= datetime.timedelta(days=5):
        t_state = "warn"
    else:
        t_state = "bad"
    if not caught_up:
        # We're behind; Transmission is delivering, so don't also blame the source.
        return "digital_behind", "ok", "bad", caught_up
    if t_state in ("warn", "bad"):
        return "transmission_stale", t_state, "ok", caught_up
    return "ok", "ok", "ok", caught_up


def main():
    force = os.environ.get("FORCE_REBUILD") == "1"
    bq = bigquery.Client(project=PROJECT)
    cn = sf_connect()

    # Splice in checks BUILT FROM DEFINITIONS (the single source of truth shared with the client
    # seed tables). Today: cloudflare's CS checks. On any failure (e.g. the doc not yet uploaded),
    # log + skip them so the sync tab and the static checks are unaffected.
    for spec in CLIENTS:
        dkey = spec.get("cs_from_definitions")
        if not dkey:
            continue
        try:
            spec["checks"] = list(spec["checks"]) + _build_cf_cs_checks(read_definitions(dkey))
        except Exception as e:   # noqa: BLE001 - never let a missing/bad doc abort the whole run
            print(f"  [{spec['client']}] definitions load failed — CS checks skipped: {e}")

    # Previous status.json -> carry forward gated accuracy numbers when a client's
    # Snowflake source hasn't advanced (avoids resuming the warehouse needlessly).
    prev = read_json(BUCKET, DATA_OBJECT) or {}
    prev_by_client = {c["client"]: c for c in prev.get("clients", [])}

    # --- Probe both freshness stages ONCE for the union of all tables ---------
    all_sources = sorted({s for c in CLIENTS for s in c["sources"]})
    all_mirrors = sorted({SF_TO_MIRROR[s] for c in CLIENTS for s in c["sources"]
                          if not c["reads_direct"]})
    try:
        sf_altered = probe_snowflake_last_altered(cn, all_sources)   # {bare_name: LAST_ALTERED} (free)
        bq_modified = probe_bq_last_modified(bq, all_mirrors)        # {"ds.table": last_modified} (free)

        now = now_utc()
        out_clients = []
        warehouse_resumes = 0

        for spec in CLIENTS:
            entry = {"client": spec["client"], "label": spec["label"], "url": spec.get("url"),
                     "reads_direct": spec["reads_direct"]}

            # ---- Stage timestamps -------------------------------------------
            src_rows, t_vals = [], []
            for s in spec["sources"]:
                la = sf_altered.get(s)
                t_vals.append(la)
                src_rows.append({"snowflake_name": s, "raw_mirror": SF_TO_MIRROR[s],
                                 "last_altered": _iso(la)})
            transmission_latest = max([t for t in t_vals if t], default=None)

            client_json = read_json(f"bidbrain-analytics-{spec['client']}-dash",
                                    f"{spec['client']}.json")
            build_at = _parse_iso(client_json.get("last_updated")) if client_json else None
            data_through = _parse_iso(client_json.get("data_through")) if client_json else None

            if spec["reads_direct"]:
                # No BigQuery mirror in the path: our ingest freshness = what the build captured.
                ingest_latest = data_through
                ingest_label = "Direct Snowflake read (no mirror)"
            else:
                m_vals = [bq_modified.get(SF_TO_MIRROR[s]) for s in spec["sources"]]
                ingest_latest = max([m for m in m_vals if m], default=None)
                ingest_label = "BigQuery raw mirror"

            # ---- Verdict: who is the staleness coming from? -----------------
            verdict, t_state, d_state, caught_up = _verdict(
                transmission_latest, ingest_latest, client_json is not None, now)

            entry["freshness"] = {
                "transmission_latest": _iso(transmission_latest),
                "transmission_tables": src_rows,
                "ingest_latest": _iso(ingest_latest),
                "ingest_label": ingest_label,
                "build_at": _iso(build_at),
                "data_through": _iso(data_through),
                "caught_up": caught_up,
                "verdict": verdict,
                "transmission_state": t_state,
                "digital_state": d_state,
            }

            # ---- Accuracy: gate the Snowflake counts on source freshness -----
            prev_entry = prev_by_client.get(spec["client"], {})
            prev_checks = {c.get("label"): c for c in prev_entry.get("accuracy", [])}
            prev_gate = (prev_entry.get("freshness") or {}).get("transmission_latest")
            gate_unchanged = (not force) and prev_gate is not None and \
                _iso(transmission_latest) == prev_gate

            checks_out = []
            for chk in spec["checks"]:
                dash_val = None
                if client_json is not None:
                    try:
                        dash_val = chk["dash"](client_json)
                    except Exception as e:   # noqa: BLE001 - record, don't crash the whole run
                        dash_val = None
                        print(f"  [{spec['client']}] dash extract failed for {chk['label']}: {e}")

                pc = prev_checks.get(chk["label"], {})
                if gate_unchanged and "snowflake_value" in pc and pc.get("error") is None:
                    sf_val = pc["snowflake_value"]
                    computed_at = pc.get("computed_at")
                    err = None
                else:
                    try:
                        sf_val = scalar(cn, chk["sql"])
                        warehouse_resumes += 1
                        computed_at = _iso(now)
                        err = None
                    except Exception as e:   # noqa: BLE001
                        sf_val = None
                        computed_at = _iso(now)
                        err = str(e)
                        print(f"  [{spec['client']}] snowflake query failed for {chk['label']}: {e}")

                match = (sf_val is not None and dash_val is not None
                         and round(float(sf_val)) == round(float(dash_val)))
                checks_out.append({
                    "label": chk["label"], "metric_kind": chk["kind"],
                    "group": chk.get("group", ""),
                    "snowflake_value": sf_val, "dashboard_value": dash_val,
                    "match": (None if (sf_val is None or dash_val is None) else match),
                    "snowflake_query": chk["sql"], "note": chk.get("note", ""),
                    "computed_at": computed_at, "error": err,
                })

            entry["accuracy"] = checks_out
            out_clients.append(entry)
            print(f"  {spec['client']:11s} verdict={entry['freshness']['verdict']:18s} "
                  f"caught_up={entry['freshness']['caught_up']} checks={len(checks_out)}")
    finally:
        cn.close()

    payload = {
        "generated_at": _iso(now_utc()),
        "tolerance_minutes": int(INGEST_LAG_TOLERANCE.total_seconds() // 60),
        "clients": out_clients,
    }
    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(payload), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(out_clients)} clients, "
          f"{warehouse_resumes} Snowflake aggregate(s) run this tick "
          f"({'forced' if force else 'gated on source freshness'})")


if __name__ == "__main__":
    main()
