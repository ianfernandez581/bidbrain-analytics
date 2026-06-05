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

# DTS convenience-view name patterns -> the id (MCC / property) is the trailing number.
GADS_STATS_RE = re.compile(r"^ads_CampaignBasicStats_(\d+)$")
GA4_TRAFFIC_RE = re.compile(r"^ga4_TrafficAcquisition_(\d+)$")

# --- client/agency tagging (optional but keeps the perf_* contract complete) ---
# Google Ads: keyed by customer_id (sub-account, digits only). Fill the slugs your
# dashboards expect; anything not listed falls back to a slug of the account name.
# Sub-accounts under MCC 345-189-6252: 261-791-6504 City Perfume, 519-659-6415 Liberty,
# 850-931-3407 Paradise, 105-440-7474 Reset Data, 186-974-5895 The Little Marionette.
GADS_CLIENT = {
    # "2617916504": ("cp", "100-digital"),
    # "1054407474": ("resetdata", "100-digital"),
    # "1869745895": ("tlm", "100-digital"),
}
# GA4: keyed by property_id -> (client_slug, agency_slug, account_name). No account name
# exists in the TrafficAcquisition report, so set it here if you want one on the row.
GA4_CLIENT = {
    "318963196": ("stt", "unknown", "STT GDC Web All"),
}

BASE_DIR = Path(__file__).resolve().parent
SQL_DIR = BASE_DIR / "sql"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("dts_views")


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "unknown"


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
        return name_slug, "'unknown'"
    cwhen = "\n".join(f"      WHEN '{cid}' THEN '{cs}'" for cid, (cs, _ag) in GADS_CLIENT.items())
    awhen = "\n".join(f"      WHEN '{cid}' THEN '{ag}'" for cid, (_cs, ag) in GADS_CLIENT.items())
    client_expr = f"CASE CAST(s.customer_id AS STRING)\n{cwhen}\n      ELSE {name_slug} END"
    agency_expr = f"CASE CAST(s.customer_id AS STRING)\n{awhen}\n      ELSE 'unknown' END"
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
    """One property's perf_ga4 SELECT block. client/agency/account_name are injected as
    literals (we know the property id here); session-grain metrics map directly, the rest
    are NULL (see module docstring)."""
    cs, ag, name = GA4_CLIENT.get(prop, ("unknown", "unknown", None))
    name_lit = "CAST(NULL AS STRING)" if name is None else f"'{name}'"
    return f"""SELECT
  'ga4'                                 AS platform,
  '{prop}'                              AS property_id,
  {name_lit}                            AS account_name,
  '{cs}'                                AS client_slug,
  '{ag}'                                AS agency_slug,
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
        ddl = build_view_ddl(GADS_DATASET, GADS_VIEW, [gads_block(m) for m in mccs])
        (SQL_DIR / f"{GADS_VIEW}.sql").write_text(ddl, encoding="utf-8")
        apply_view(bq, f"{GADS_DATASET}.{GADS_VIEW}", ddl)
    else:
        log.warning("  no ads_CampaignBasicStats_* tables yet -- skipping perf_google_ads")

    # --- GA4 ---
    props = discover(bq, GA4_DATASET, GA4_TRAFFIC_RE)
    log.info(f"GA4 property table sets found ({len(props)}): {list(props) or 'NONE'}")
    if props:
        ddl = build_view_ddl(GA4_DATASET, GA4_VIEW, [ga4_block(p) for p in props])
        (SQL_DIR / f"{GA4_VIEW}.sql").write_text(ddl, encoding="utf-8")
        apply_view(bq, f"{GA4_DATASET}.{GA4_VIEW}", ddl)
    else:
        log.warning("  no ga4_TrafficAcquisition_* tables yet -- skipping perf_ga4")

    log.info("Done. Re-run after adding more GA4 property transfers to extend perf_ga4.")


if __name__ == "__main__":
    main()
