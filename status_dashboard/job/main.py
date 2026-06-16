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


# Cloudflare CS lives in Snowflake modelled views (read direct), so the dashboard
# number is a COUNT over the passed-through pacing rows.
def _cf_total_leads(d):
    rows = d.get("pacing", {}).get("rows", [])
    return sum(1 for r in rows if not _is_dummy(r) and r.get("LEAD_STATUS") is not None)


def _cf_accepted(d):
    A = {"Accepted", "Replied", "Unresponsive"}
    rows = d.get("pacing", {}).get("rows", [])
    return sum(1 for r in rows if not _is_dummy(r) and r.get("LEAD_STATUS") in A)


# ─────────────────────────────────────────────────────────────────────────────
# The per-client spec. Verified line-by-line against each client's sql/ views,
# job/main.py and dashboard JS (see status_dashboard/README.md for provenance).
#   sources : Snowflake source tables this client depends on (Transmission side).
#   reads_direct : True only for cloudflare (reads Snowflake modelled views directly;
#                  no BigQuery raw mirror in its CS path -> ingest stage = the build).
#   checks  : accuracy comparisons. `dash` extracts the comparable number from the
#             client's JSON; `sql` is the EXACT Snowflake query that should equal it.
# Spend is never used for an equality check (FX-converted on most clients).
# ─────────────────────────────────────────────────────────────────────────────
CLIENTS = [
    {
        "client": "mongodb", "label": "MongoDB APAC", "url": "https://mongodb.bidbrain.ai",
        "sources": ["TradeDesk_APAC ALL", "Salesforce_CS_APAC_ALL"],
        "reads_direct": False,
        "checks": [
            # Content-Syndication leads — ALL 4 MongoDB CS campaigns (3 DNB + the funded KGA/IDC),
            # bucketed exactly as the cs_leads view (and the dashboard): Accepted = 'Accepted',
            # Rejected = 'Rejected', New = 'Unresponsive' + 'Do Not Contact' + 'New'. KGA/IDC ('701RG00001NKKwQYAX',
            # NULL programme) is the LARGEST CS campaign (~479 leads, almost all New/unprocessed), so
            # it MUST be counted: the dashboard's cs[] (grouped by market, no programme filter) includes
            # it → 881 total / 353 accepted / 0 rejected / 527 new across all four. The SQL mirrors that.
            {"label": "Content-Syndication · Total leads", "kind": "count",
             "dash": lambda d: sum(_num(c.get("total")) for c in d.get("cs", [])),
             "sql": "SELECT COUNT(*) AS total_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3',\n"
                    "                      '701RG00001GvvrDYAR','701RG00001NKKwQYAX');",
             "note": "All 4 CS campaigns. Compared against the un-scoped sum of cs[].total in the JSON "
                     "(which the cs_leads view builds from these very rows), NOT the on-screen 'Total leads' "
                     "KPI (scoped to a programme + mapped markets). KGA/IDC alone is ~479 of the ~881."},
            {"label": "Content-Syndication · Accepted leads", "kind": "count",
             "dash": lambda d: sum(_num(c.get("accepted")) for c in d.get("cs", [])),
             "sql": "SELECT COUNT(*) AS accepted_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3',\n"
                    "                      '701RG00001GvvrDYAR','701RG00001NKKwQYAX')\n"
                    "  AND LEAD_STATUS = 'Accepted';",
             "note": "Accepted bucket = LEAD_STATUS 'Accepted' (matches cs_leads.ACCEPTED). "
                     "Compared against sum(cs[].accepted) in the JSON. (KGA/IDC contributes 0 accepted.)"},
            {"label": "Content-Syndication · Rejected leads", "kind": "count",
             "dash": lambda d: sum(_num(c.get("rejected")) for c in d.get("cs", [])),
             "sql": "SELECT COUNT(*) AS rejected_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3',\n"
                    "                      '701RG00001GvvrDYAR','701RG00001NKKwQYAX')\n"
                    "  AND LEAD_STATUS = 'Rejected';",
             "note": "Rejected bucket = LEAD_STATUS 'Rejected' (matches cs_leads.REJECTED). "
                     "Compared against sum(cs[].rejected) in the JSON."},
            {"label": "Content-Syndication · New (unprocessed) leads", "kind": "count",
             "dash": lambda d: sum(_num(c.get("new")) for c in d.get("cs", [])),
             "sql": "SELECT COUNT(*) AS new_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Salesforce_CS_APAC_ALL\"\n"
                    "WHERE CAMPAIGN_ID IN ('701RG00001DtQczYAF','701RG00001HcDIVYA3',\n"
                    "                      '701RG00001GvvrDYAR','701RG00001NKKwQYAX')\n"
                    "  AND LEAD_STATUS IN ('Unresponsive','Do Not Contact','New');",
             "note": "New bucket = LEAD_STATUS IN ('Unresponsive','Do Not Contact','New') (matches "
                     "cs_leads.NEW_LEADS). Compared against sum(cs[].new) in the JSON. 'Do Not Contact' "
                     "is IDC-only (1 lead); KGA/IDC contributes ~479 of these."},
            {"label": "TradeDesk · Total impressions", "kind": "sum",
             "dash": lambda d: sum(_num(r.get("imps")) for r in d.get("rows", [])),
             "sql": "SELECT SUM(CAST(COALESCE(IMPRESSIONS, IMPRESSION) AS INTEGER)) AS imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'MongoDB';",
             "note": "Clean integer pass-through (no FX). Compared against sum(rows[].imps) in the JSON."},
            {"label": "TradeDesk · Total clicks", "kind": "sum",
             "dash": lambda d: sum(_num(r.get("clicks")) for r in d.get("rows", [])),
             "sql": "SELECT SUM(CAST(CLICKS AS INTEGER)) AS clicks\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'MongoDB';",
             "note": "Clean integer pass-through. Compared against sum(rows[].clicks) in the JSON."},
        ],
    },
    {
        "client": "cloudflare", "label": "Cloudflare APAC", "url": "https://cloudflare.bidbrain.ai",
        "sources": ["Salesforce_CS_APAC_ALL", "TradeDesk_APAC ALL",
                    "LinkedIn Ads - APAC", "Reddit Ads - APAC_ALL"],
        "reads_direct": True,
        "checks": [
            {"label": "Content-Syndication · Total leads", "kind": "count",
             "dash": _cf_total_leads,
             "sql": "SELECT COUNT(*) AS total_leads\n"
                    "FROM CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL\n"
                    "WHERE (LEAD_ID_SF IS NULL OR LEAD_ID_SF NOT LIKE 'DUMMY%')\n"
                    "  AND LEAD_STATUS IS NOT NULL;",
             "note": "CS reads Snowflake modelled views DIRECTLY, so this query hits the very view the "
                     "dashboard was built from (campaign filter = the canonical 8 CS IDs, inside "
                     "V_SALESFORCE_LEADS_LIVE). Counts all non-null statuses (incl. New)."},
            {"label": "Content-Syndication · Accepted leads", "kind": "count",
             "dash": _cf_accepted,
             "sql": "SELECT COUNT(*) AS accepted_leads\n"
                    "FROM CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL\n"
                    "WHERE (LEAD_ID_SF IS NULL OR LEAD_ID_SF NOT LIKE 'DUMMY%')\n"
                    "  AND LEAD_STATUS IN ('Accepted','Replied','Unresponsive');",
             "note": "Accepted bucket = Accepted + Replied + Unresponsive. Compared against the same count "
                     "over pacing.rows[] in the JSON."},
            {"label": "LinkedIn ANZ-PEYC · Impressions", "kind": "sum",
             "dash": lambda d: _num(d.get("campaigns", {}).get("peyc", {}).get("totals", {}).get("imps")),
             "sql": "SELECT SUM(IMPRESSIONS) AS imps\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE CAMPAIGN_GROUP_NAME = 'CLOUD_ACQ_2026-Q2_CNC_LINKEDIN_GENERAL_SI_"
                    "APAC-ANZ_ANZ_MOFU_GENERAL_X_AWR-CONS_ANZ-PEYC';",
             "note": "This number comes via the raw_snowflake.linkedin_ads_apac mirror, so it equals "
                     "Snowflake only when the mirror is in sync — exactly what the Sync tab measures."},
        ],
    },
    {
        "client": "stt", "label": "STT GDC", "url": "https://stt.bidbrain.ai",
        "sources": ["Google Analytics Data_APAC ALL", "Google Ads - APAC",
                    "LinkedIn Ads - APAC", "DV360 - APAC"],
        "reads_direct": False,
        "checks": [
            {"label": "All paid channels · Total impressions", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_imps")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_ID IN ('515691430','511609128'))\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE ADVERTISER_ID IN ('7572338345','6466367438'))\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Ads - APAC\"\n"
                    "     WHERE CAMPAIGN_NAME LIKE '%STT%') AS total_ad_imps;",
             "note": "LinkedIn + DV360 + Google Ads, whole flight, no date floor. Clean integer sums "
                     "(spend is FX-converted, so spend is never checked). Compared against kpi.ad_imps."},
            {"label": "All paid channels · Total clicks", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_clicks")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_ID IN ('515691430','511609128'))\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE ADVERTISER_ID IN ('7572338345','6466367438'))\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Ads - APAC\"\n"
                    "     WHERE CAMPAIGN_NAME LIKE '%STT%') AS total_ad_clicks;",
             "note": "Same three channel filters as impressions. Compared against kpi.ad_clicks."},
            {"label": "GA4 · Total sessions", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("sessions")),
             "sql": "SELECT COALESCE(SUM(CASE WHEN EVENT_NAME = 'session_start' THEN SESSIONS ELSE 0 END),0)\n"
                    "         AS ga4_sessions\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"Google Analytics Data_APAC ALL\"\n"
                    "WHERE PROPERTY_ID = '318963196' AND TO_DATE(DAY) >= DATE '2025-06-01';",
             "note": "GA4 is event-grained, so sessions are taken only from session_start rows. "
                     "Compared against kpi.sessions."},
        ],
    },
    {
        "client": "hireright", "label": "HireRight APAC", "url": "https://hireright.bidbrain.ai",
        "sources": ["DV360 - APAC", "LinkedIn Ads - APAC", "TradeDesk_APAC ALL"],
        "reads_direct": False,
        "checks": [
            {"label": "All paid channels · Total impressions", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_imps")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(IMPRESSIONS, IMPRESSION)),0)\n"
                    "     FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\" WHERE ADVERTISER_NAME = 'HireRight')\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%') AS ad_imps;",
             "note": "DV360 + TradeDesk + LinkedIn, whole flight. TradeDesk imps use COALESCE(IMPRESSIONS, "
                     "IMPRESSION) (current + legacy column). Compared against kpi.ad_imps."},
            {"label": "All paid channels · Total clicks", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_clicks")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'HireRight')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%') AS ad_clicks;",
             "note": "Same three filters as impressions. Compared against kpi.ad_clicks."},
            {"label": "LinkedIn · Leads", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("li_conv")),
             "sql": "SELECT COALESCE(SUM(LEADS),0) AS li_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%';",
             "note": "Clean SUM(LEADS) over the LinkedIn HireRight slice. Compared against kpi.li_conv."},
        ],
    },
    {
        "client": "schneider", "label": "Schneider Electric APAC", "url": "https://schneider.bidbrain.ai",
        "sources": ["DV360 - APAC", "LinkedIn Ads - APAC", "TradeDesk_APAC ALL"],
        "reads_direct": False,
        "checks": [
            {"label": "All paid channels · Total impressions", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_imps")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE ADVERTISER_NAME LIKE 'APAC | Schneider Electric%')\n"
                    "+ (SELECT COALESCE(SUM(COALESCE(IMPRESSIONS, IMPRESSION)),0)\n"
                    "     FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\" WHERE ADVERTISER_NAME = 'Schneider Electric')\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%') AS total_imps;",
             "note": "DV360 + TradeDesk + LinkedIn, whole flight. TradeDesk filter is exact '='; DV360/LinkedIn "
                     "are LIKE patterns (the '_' is a wildcard, left unescaped to match the view). vs kpi.ad_imps."},
            {"label": "All paid channels · Total clicks", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_clicks")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"DV360 - APAC\"\n"
                    "     WHERE ADVERTISER_NAME LIKE 'APAC | Schneider Electric%')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'Schneider Electric')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%') AS total_clicks;",
             "note": "Same three filters as impressions. Compared against kpi.ad_clicks."},
            {"label": "LinkedIn · Leads", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("li_leads")),
             "sql": "SELECT COALESCE(SUM(LEADS),0) AS li_leads\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%';",
             "note": "LinkedIn-only leads (DV360/TradeDesk contribute 0). Compared against kpi.li_leads."},
        ],
    },
    {
        "client": "proptrack", "label": "PropTrack APAC", "url": "https://proptrack.bidbrain.ai",
        "sources": ["TradeDesk_APAC ALL", "LinkedIn Ads - APAC"],
        "reads_direct": False,
        "checks": [
            {"label": "All paid channels · Total impressions", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_imps")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(IMPRESSION),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'PopTrack')\n"
                    "+ (SELECT COALESCE(SUM(IMPRESSIONS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD') AS ad_imps;",
             "note": "TradeDesk + LinkedIn. Note the column spelling: TradeDesk impressions live in the "
                     "SINGULAR column IMPRESSION (plural is NULL for this advertiser); LinkedIn uses IMPRESSIONS. "
                     "TradeDesk spells the advertiser 'PopTrack'. Compared against kpi.ad_imps."},
            {"label": "All paid channels · Total clicks", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("ad_clicks")),
             "sql": "SELECT\n"
                    "  (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "     WHERE ADVERTISER_NAME = 'PopTrack')\n"
                    "+ (SELECT COALESCE(SUM(CLICKS),0) FROM APAC_ALL_PLATFORM.PUBLIC.\"LinkedIn Ads - APAC\"\n"
                    "     WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD') AS ad_clicks;",
             "note": "Both channels use the CLICKS column. Compared against kpi.ad_clicks."},
            {"label": "TradeDesk · Conversions", "kind": "sum",
             "dash": lambda d: _num(d.get("kpi", {}).get("td_conv")),
             "sql": "SELECT SUM(TOTAL_CLICK_PLUS_VIEW_CONVERSIONS) AS td_conv\n"
                    "FROM APAC_ALL_PLATFORM.PUBLIC.\"TradeDesk_APAC ALL\"\n"
                    "WHERE ADVERTISER_NAME = 'PopTrack';",
             "note": "TradeDesk click+view conversions (LinkedIn conv is 0 for this client, so this also "
                     "equals the blended kpi.ad_conv). Compared against kpi.td_conv."},
        ],
    },
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
