r"""
dts_data_pull/create_views.py
=============================
Build the two "flattening" VIEWS that map Google's NATIVE BigQuery Data Transfer
Service (DTS) output into the same perf-table shape the rest of the warehouse uses
(modeled on `raw_windsor.perf_ga4`). These replace the Windsor Google Ads loader
that the Windsor Basic plan blocked, and give a native, zero-maintenance GA4 source.

    raw_google_ads.ads_CampaignBasicStats_<mcc> (+ ads_Campaign/ads_Customer)
        -> raw_google_ads.perf_google_ads        (campaign x date)
    raw_ga4.ga4_TrafficAcquisition_<property>
        -> raw_ga4.perf_ga4                       (property x date x session src/med/camp x channel)

WHY VIEWS (not loaded tables): DTS already lands + refreshes the data daily, and its
`ads_*` / `ga4_*` *convenience views* already DEDUPE each day's re-ingest to one
snapshot. So we read THROUGH those convenience views and never touch the `p_*` base
tables (touching p_* would double-count the daily reload). A view over them is always
current and costs no storage.

DYNAMIC UNION: there is one DTS table set per Google Ads MCC and per GA4 property.
This script DISCOVERS every `ads_CampaignBasicStats_*` and `ga4_TrafficAcquisition_*`
that currently exists and UNION ALLs them. So after you add the remaining GA4 property
transfers in the Cloud Console, just RE-RUN this script and perf_ga4 picks them up.

GA4 GRAIN CAVEAT: the GA4 DTS `TrafficAcquisition` report is SESSION-grain and exposes
sessions / engaged_sessions / event_count / key_events(=conversions) / total_revenue
only. The user-grain (total_users, new_users) and ecommerce columns (purchase_revenue,
ecommerce_purchases, transactions, screen_page_views) live in OTHER GA4 DTS reports at
incompatible grains, so they are emitted as NULL here rather than wrongly joined. The
perf_ga4 column list is preserved in full so the view stays a drop-in for that contract.

Auth: Application Default Credentials (same as the Windsor loaders). Run:
    .\.venv\Scripts\python.exe dts_data_pull\create_views.py
Idempotent (CREATE OR REPLACE). Also writes the exact applied DDL to sql/ for review.
"""
import logging
import re
import sys
from pathlib import Path

from google.cloud import bigquery

# ---------- Config ----------
PROJECT_ID = "bidbrain-analytics"
LOCATION = "australia-southeast1"
GADS_DATASET = "raw_google_ads"
GA4_DATASET = "raw_ga4"
GADS_VIEW = "perf_google_ads"
GA4_VIEW = "perf_ga4"
GA4_EVENTS_VIEW = "perf_ga4_events"

# DTS convenience-view name patterns -> the id (MCC / property) is the trailing number.
GADS_STATS_RE = re.compile(r"^ads_CampaignBasicStats_(\d+)$")
GA4_TRAFFIC_RE = re.compile(r"^ga4_TrafficAcquisition_(\d+)$")
GA4_EVENTS_RE = re.compile(r"^ga4_Events_(\d+)$")

# --- client/agency tagging (keeps the perf_* contract complete) ---
DEFAULT_AGENCY = "100-digital"   # operating agency; override per client below

# GA4's TrafficAcquisition report carries NO property name, so we supply it here (a
# one-time copy of the GA4 property display names — refresh from raw_windsor.perf_ga4
# if a property is renamed/added). Per property: account_name = this name, client_slug
# = a slug of it, agency_slug = DEFAULT_AGENCY (all overridable via GA4_CLIENT).
PROPERTY_NAMES = {
    "254028250": "City Perfume",
    "516276493": "Reset Data",
    "318963196": "STT GDC Web All",
    "434839993": "STT GDC Web Global",
    "413451542": "STT GDC Web India",
    "413487460": "STT GDC Web Indonesia",
    "434829327": "STT GDC Web Japan",
    "434854278": "STT GDC Web Korea",
    "434905821": "STT GDC Web Malaysia",
    "413491455": "STT GDC Web Philippines",
    "413490347": "STT GDC Web Singapore",
    "413495845": "STT GDC Web Thailand",
    "434852571": "STT GDC Web Vietnam",
    "273098216": "Atlantis Reservations",
    "506931798": "ChocolateGrove",
    "468621509": "Sophiie",
    "287370621": "VMCH Website - GA4",
    "341832593": "http://atlantisevents.com - GA4",
    "341827046": "http://rsvpvacations.com - GA4",
    "358885683": "https://100.digital/",
}

# Optional explicit overrides. GA4: property_id -> (client_slug, agency_slug); wins over
# the name-derived defaults above. Google Ads: customer_id -> (client_slug, agency_slug);
# falls back to a slug of the account name + DEFAULT_AGENCY. Leave empty to auto-derive.
GA4_CLIENT = {}
GADS_CLIENT = {}

# Google Ads MCC sub-account display names (BARE customer_id -> name) for consistent
# account_name/client_slug across the native + Windsor bridge arms (mirrors PROPERTY_NAMES).
CUSTOMER_NAMES = {
    "2617916504": "City Perfume",
    "1054407474": "Reset Data",
    "1869745895": "The Little Marionette",
    "5196596415": "Liberty",
    "8509313407": "Paradise",
}

BASE_DIR = Path(__file__).resolve().parent
SQL_DIR = BASE_DIR / "sql"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("dts_views")


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "unknown"


def sql_str(s):
    """A SQL string literal (single-quote-escaped) or a typed NULL."""
    if s is None:
        return "CAST(NULL AS STRING)"
    return "'" + str(s).replace("'", "''") + "'"


def discover(bq, dataset, pattern):
    """Return {id: full_table_id} for every convenience view matching `pattern`."""
    out = {}
    for t in bq.list_tables(f"{PROJECT_ID}.{dataset}"):
        m = pattern.match(t.table_id)
        if m:
            out[m.group(1)] = t.table_id
    return dict(sorted(out.items()))


# ---------- Google Ads ----------
def gads_client_case():
    """SQL CASE on customer_id -> client_slug / agency_slug, generated from GADS_CLIENT.
    Fallback = slug of the account name / 'unknown'. Returns (client_expr, agency_expr)."""
    name_slug = (
        "COALESCE(NULLIF(LOWER(TRIM(REGEXP_REPLACE("
        "cust.customer_descriptive_name, r'[^A-Za-z0-9]+', '-'), '-')), ''), 'unknown')"
    )
    if not GADS_CLIENT:
        return name_slug, f"'{DEFAULT_AGENCY}'"
    cwhen = "\n".join(f"      WHEN '{cid}' THEN '{cs}'" for cid, (cs, _ag) in GADS_CLIENT.items())
    awhen = "\n".join(f"      WHEN '{cid}' THEN '{ag}'" for cid, (_cs, ag) in GADS_CLIENT.items())
    client_expr = f"CASE CAST(s.customer_id AS STRING)\n{cwhen}\n      ELSE {name_slug} END"
    agency_expr = f"CASE CAST(s.customer_id AS STRING)\n{awhen}\n      ELSE '{DEFAULT_AGENCY}' END"
    return client_expr, agency_expr


def gads_block(mcc):
    """One MCC's perf_google_ads SELECT block (campaign x date, summed over segments)."""
    client_expr, agency_expr = gads_client_case()
    return f"""SELECT
  'google_ads'                          AS platform,
  CAST(s.customer_id AS STRING)         AS customer_id,
  cust.customer_descriptive_name        AS account_name,
  {client_expr} AS client_slug,
  {agency_expr} AS agency_slug,
  s.metric_date                         AS metric_date,
  CAST(s.campaign_id AS STRING)         AS campaign_id,
  c.campaign_name                       AS campaign_name,
  c.campaign_advertising_channel_type   AS campaign_type,
  cust.customer_currency_code           AS currency_code,
  s.impressions                         AS impressions,
  s.clicks                              AS clicks,
  s.spend                               AS spend,
  s.conversions                         AS conversions,
  s.conversions_value                   AS conversions_value,
  CURRENT_TIMESTAMP()                   AS ingested_at,
  'dts.google_ads'                      AS source,
  TO_JSON(s)                            AS raw_row
FROM (
  SELECT customer_id, campaign_id, segments_date AS metric_date,
         SUM(metrics_impressions)                        AS impressions,
         SUM(metrics_clicks)                             AS clicks,
         CAST(SUM(metrics_cost_micros) / 1e6 AS NUMERIC) AS spend,
         CAST(SUM(metrics_conversions) AS NUMERIC)       AS conversions,
         CAST(SUM(metrics_conversions_value) AS NUMERIC) AS conversions_value
  FROM `{PROJECT_ID}.{GADS_DATASET}.ads_CampaignBasicStats_{mcc}`
  GROUP BY customer_id, campaign_id, segments_date
) s
LEFT JOIN (
  SELECT campaign_id, customer_id, campaign_name, campaign_advertising_channel_type
  FROM `{PROJECT_ID}.{GADS_DATASET}.ads_Campaign_{mcc}`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY campaign_id ORDER BY _DATA_DATE DESC) = 1
) c USING (campaign_id, customer_id)
LEFT JOIN (
  SELECT customer_id, customer_descriptive_name, customer_currency_code
  FROM `{PROJECT_ID}.{GADS_DATASET}.ads_Customer_{mcc}`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY _DATA_DATE DESC) = 1
) cust USING (customer_id)"""


# ---------- GA4 ----------
def ga4_block(prop):
    """One property's perf_ga4 SELECT block. session-grain metrics map directly, the rest
    are NULL (see module docstring). account_name comes from PROPERTY_NAMES; client_slug
    defaults to a slug of it; agency_slug defaults to DEFAULT_AGENCY (GA4_CLIENT overrides)."""
    name = PROPERTY_NAMES.get(prop)
    cs = slugify(name) if name else prop
    ag = DEFAULT_AGENCY
    if prop in GA4_CLIENT:
        o_cs, o_ag = GA4_CLIENT[prop]
        cs = o_cs or cs
        ag = o_ag or ag
    return f"""SELECT
  'ga4'                                 AS platform,
  '{prop}'                              AS property_id,
  {sql_str(name)}                       AS account_name,
  {sql_str(cs)}                         AS client_slug,
  {sql_str(ag)}                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  COALESCE(NULLIF(t.sessionSource, ''), '(not set)')               AS session_source,
  COALESCE(NULLIF(t.sessionMedium, ''), '(not set)')               AS session_medium,
  COALESCE(NULLIF(t.sessionSourceMedium, ''),
           CONCAT(COALESCE(NULLIF(t.sessionSource, ''), '(not set)'), ' / ',
                  COALESCE(NULLIF(t.sessionMedium, ''), '(not set)')))   AS session_source_medium,
  COALESCE(NULLIF(t.sessionCampaignName, ''), '(not set)')         AS session_campaign_name,
  COALESCE(NULLIF(t.sessionDefaultChannelGroup, ''), '(not set)')  AS session_default_channel_group,
  t.sessions                            AS sessions,
  t.engagedSessions                     AS engaged_sessions,
  CAST(NULL AS INT64)                   AS total_users,
  CAST(NULL AS INT64)                   AS new_users,
  CAST(NULL AS INT64)                   AS screen_page_views,
  CAST(NULL AS NUMERIC)                 AS user_engagement_duration,
  t.eventCount                          AS event_count,
  CAST(t.keyEvents AS NUMERIC)          AS conversions,
  CAST(t.totalRevenue AS NUMERIC)       AS total_revenue,
  CAST(NULL AS NUMERIC)                 AS purchase_revenue,
  CAST(NULL AS INT64)                   AS ecommerce_purchases,
  CAST(NULL AS INT64)                   AS transactions,
  CURRENT_TIMESTAMP()                   AS ingested_at,
  'dts.ga4'                             AS source,
  TO_JSON(t)                            AS raw_row
FROM `{PROJECT_ID}.{GA4_DATASET}.ga4_TrafficAcquisition_{prop}` t"""


def build_view_ddl(dataset, view, blocks):
    body = "\nUNION ALL\n".join(blocks)
    return f"CREATE OR REPLACE VIEW `{PROJECT_ID}.{dataset}.{view}` AS\n{body};\n"


# Grain key for GA4 (matches raw_windsor.perf_ga4's MERGE key).
_GA4_KEY = ("property_id, metric_date, session_source, session_medium, "
            "session_campaign_name, session_default_channel_group")


def build_ga4_bridge_ddl(blocks):
    """perf_ga4 as a TRANSITIONAL BRIDGE: native DTS rows UNION raw_windsor.perf_ga4
    (which already holds deep contiguous history -- back to 2022 for some properties),
    deduped on the GA4 grain key with NATIVE winning over Windsor. This gives full
    history immediately while the slow native backfill catches up; once native covers
    everything, drop the Windsor arm (revert to build_view_ddl) with zero consumer impact.
    Windsor also supplies the properties native can't reach (no-access ones)."""
    native = "\nUNION ALL\n".join(blocks)
    name_case = ("CASE property_id "
                 + " ".join(f"WHEN '{p}' THEN {sql_str(n)}" for p, n in PROPERTY_NAMES.items())
                 + " ELSE account_name END")
    slug_case = ("CASE property_id "
                 + " ".join(f"WHEN '{p}' THEN {sql_str(slugify(n))}" for p, n in PROPERTY_NAMES.items())
                 + " ELSE client_slug END")
    return f"""CREATE OR REPLACE VIEW `{PROJECT_ID}.{GA4_DATASET}.{GA4_VIEW}` AS
-- Re-derive account_name/client_slug/agency_slug from property_id so the Windsor and
-- native arms tag CONSISTENTLY (Windsor tags per-row from its own keyword map, so the
-- two arms otherwise disagree -- e.g. agency 'unknown' on history vs '100-digital' on native).
SELECT * REPLACE (
  {name_case} AS account_name,
  {slug_case} AS client_slug,
  '{DEFAULT_AGENCY}' AS agency_slug
)
FROM (
  SELECT * FROM (
{native}
    UNION ALL
    SELECT * FROM `{PROJECT_ID}.raw_windsor.{GA4_VIEW}`
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY {_GA4_KEY}
    ORDER BY CASE source WHEN 'dts.ga4' THEN 0 ELSE 1 END
  ) = 1
);
"""


def ga4_events_block(prop):
    """One property's perf_ga4_events SELECT block (property x date x event_name). The GA4 DTS
    Events report has no is_conversion_event / conversions metric, so those are NULL here (only the
    Windsor arm populates them); event_value = totalRevenue. Columns/order match
    raw_windsor.perf_ga4_events exactly."""
    name = PROPERTY_NAMES.get(prop)
    cs = slugify(name) if name else prop
    ag = DEFAULT_AGENCY
    if prop in GA4_CLIENT:
        o_cs, o_ag = GA4_CLIENT[prop]
        cs = o_cs or cs
        ag = o_ag or ag
    return f"""SELECT
  '{prop}'                              AS property_id,
  {sql_str(cs)}                         AS client_slug,
  {sql_str(ag)}                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `{PROJECT_ID}.{GA4_DATASET}.ga4_Events_{prop}` t"""


def build_ga4_events_bridge_ddl(blocks):
    """perf_ga4_events BRIDGE: native ga4_Events_* UNION raw_windsor.perf_ga4_events (deep history,
    back to 2020), deduped on (property_id, metric_date, event_name), native preferred. This target
    schema has NO `source` column, so a literal _arm rank (0 native / 1 windsor) drives the dedup
    and is dropped at the end. client_slug/agency_slug re-derived from property_id for consistency.
    NOTE: is_conversion_event + conversions populate only on the Windsor (history) arm -- the GA4
    DTS Events report doesn't expose them. Drop the Windsor arm once native backfill completes."""
    native = "\nUNION ALL\n".join(blocks)
    slug_case = ("CASE property_id "
                 + " ".join(f"WHEN '{p}' THEN {sql_str(slugify(n))}" for p, n in PROPERTY_NAMES.items())
                 + " ELSE client_slug END")
    return f"""CREATE OR REPLACE VIEW `{PROJECT_ID}.{GA4_DATASET}.{GA4_EVENTS_VIEW}` AS
SELECT * EXCEPT(_arm) REPLACE (
  {slug_case} AS client_slug,
  '{DEFAULT_AGENCY}' AS agency_slug
)
FROM (
  SELECT * FROM (
    SELECT *, 0 AS _arm FROM (
{native}
    )
    UNION ALL
    SELECT *, 1 AS _arm FROM `{PROJECT_ID}.raw_windsor.{GA4_EVENTS_VIEW}`
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY property_id, metric_date, event_name
    ORDER BY _arm
  ) = 1
);
"""


def build_gads_bridge_ddl(blocks):
    """perf_google_ads as a TRANSITIONAL BRIDGE: native DTS Google Ads UNION
    raw_windsor.perf_google_ads (deep history -- back to 2018 for some accounts), deduped on
    (customer_id, campaign_id, metric_date) with NATIVE winning. Windsor's customer_id is
    HYPHENATED (261-791-6504) so it's normalized to bare digits to match native and the key.
    Tagging is re-derived from customer_id (CUSTOMER_NAMES) for consistency. Drop the Windsor
    arm (revert to build_view_ddl) once the native backfill is complete -- zero consumer impact."""
    native = "\nUNION ALL\n".join(blocks)
    name_case = ("CASE customer_id "
                 + " ".join(f"WHEN '{c}' THEN {sql_str(n)}" for c, n in CUSTOMER_NAMES.items())
                 + " ELSE account_name END")
    slug_case = ("CASE customer_id "
                 + " ".join(f"WHEN '{c}' THEN {sql_str(slugify(n))}" for c, n in CUSTOMER_NAMES.items())
                 + " ELSE client_slug END")
    return f"""CREATE OR REPLACE VIEW `{PROJECT_ID}.{GADS_DATASET}.{GADS_VIEW}` AS
-- Re-derive account_name/client_slug/agency_slug from customer_id so the native and Windsor
-- arms tag CONSISTENTLY. Windsor's customer_id is hyphenated -> normalized to bare digits.
SELECT * REPLACE (
  {name_case} AS account_name,
  {slug_case} AS client_slug,
  '{DEFAULT_AGENCY}' AS agency_slug
)
FROM (
  SELECT * FROM (
{native}
    UNION ALL
    SELECT * REPLACE (REGEXP_REPLACE(customer_id, r'[^0-9]', '') AS customer_id)
    FROM `{PROJECT_ID}.raw_windsor.{GADS_VIEW}`
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY customer_id, campaign_id, metric_date
    ORDER BY CASE source WHEN 'dts.google_ads' THEN 0 ELSE 1 END
  ) = 1
);
"""


def apply_view(bq, name, ddl):
    log.info(f"Creating/replacing view {name} ...")
    bq.query(ddl).result()
    log.info(f"  done: {name}")


def main():
    bq = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    SQL_DIR.mkdir(parents=True, exist_ok=True)

    # --- Google Ads ---
    mccs = discover(bq, GADS_DATASET, GADS_STATS_RE)
    log.info(f"Google Ads MCC table sets found: {list(mccs) or 'NONE'}")
    if mccs:
        ddl = build_gads_bridge_ddl([gads_block(m) for m in mccs])
        (SQL_DIR / f"{GADS_VIEW}.sql").write_text(ddl, encoding="utf-8")
        apply_view(bq, f"{GADS_DATASET}.{GADS_VIEW}", ddl)
    else:
        log.warning("  no ads_CampaignBasicStats_* tables yet -- skipping perf_google_ads")

    # --- GA4 ---
    props = discover(bq, GA4_DATASET, GA4_TRAFFIC_RE)
    log.info(f"GA4 property table sets found ({len(props)}): {list(props) or 'NONE'}")
    if props:
        ddl = build_ga4_bridge_ddl([ga4_block(p) for p in props])
        (SQL_DIR / f"{GA4_VIEW}.sql").write_text(ddl, encoding="utf-8")
        apply_view(bq, f"{GA4_DATASET}.{GA4_VIEW}", ddl)
    else:
        log.warning("  no ga4_TrafficAcquisition_* tables yet -- skipping perf_ga4")

    # --- GA4 events ---
    eprops = discover(bq, GA4_DATASET, GA4_EVENTS_RE)
    log.info(f"GA4 Events table sets found ({len(eprops)}): {list(eprops) or 'NONE'}")
    if eprops:
        ddl = build_ga4_events_bridge_ddl([ga4_events_block(p) for p in eprops])
        (SQL_DIR / f"{GA4_EVENTS_VIEW}.sql").write_text(ddl, encoding="utf-8")
        apply_view(bq, f"{GA4_DATASET}.{GA4_EVENTS_VIEW}", ddl)
    else:
        log.warning("  no ga4_Events_* tables yet -- skipping perf_ga4_events")

    log.info("Done. Re-run after adding more GA4 property transfers to extend the perf_* views.")


if __name__ == "__main__":
    main()
