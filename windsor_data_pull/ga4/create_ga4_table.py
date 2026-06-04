"""
One-time setup: create the GA4 performance table (perf_ga4).

Grain: ONE ROW per (property_id x metric_date x session acquisition) -- i.e. the
GA4 "Traffic Acquisition" report. This is the grain that joins back to perf_meta
/ perf_the_trade_desk: GA4 tells you what the ad click DID on-site (sessions,
engagement, key events, revenue) per source / campaign / day.

WHY NOT one giant all-metrics table like Meta: GA4's Data API caps each request
at 9 dimensions / 10 metrics, enforces dimension-metric compatibility, and mixes
scopes (user / session / event / item) that are NOT additive against one row
grain. So -- exactly like create_meta_table.py's "platform/demographic splits go
in a separate table later" -- this is the PRIMARY table at the acquisition
grain; landing-page / demographics / geo / device / events / items each get
their own perf_ga4_* table later.

Session-scoped acquisition is the spine (session_source/medium/campaign), NOT
first_user_* (that's the User Acquisition grain) and NOT the key-event-scoped
source/medium (scope conflict). property_id is the tenant key (we select by GA4
property ID, so it's reliable per row; measurement_id is stream-scoped and would
fragment multi-stream properties, so it's deliberately not stored).

METRICS ARE ADDITIVE BASE ONLY. Do NOT add engagement_rate / bounce_rate /
average_session_duration / AOV / ARPU as columns -- they're non-additive and
break when summed across days or sources. Store numerator + denominator and
derive in SQL:
    engagement_rate          = SUM(engaged_sessions) / SUM(sessions)
    bounce_rate              = 1 - engagement_rate
    avg engagement time/sess = SUM(user_engagement_duration) / SUM(sessions)
    AOV                      = SUM(purchase_revenue) / NULLIF(SUM(transactions),0)
    ARPU                     = SUM(total_revenue) / NULLIF(SUM(total_users),0)

Lives in raw_windsor alongside perf_meta and perf_the_trade_desk.

Run:  python windsor_data_pull/ga4/create_ga4_table.py   (after create_dataset.py)
Idempotent (exists_ok=True) -- but note it CREATES, it does not ALTER. If the
table already exists from an earlier (narrower) version, drop it first (it's
empty) so the new columns take effect:
    bq rm -f -t bidbrain-analytics:raw_windsor.perf_ga4
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
RAW_DATASET = "raw_windsor"

client = bigquery.Client(project=PROJECT)

schema = [
    # ---- Identifiers / tenant ----
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED",
        description="Source platform, always 'ga4'"),
    bigquery.SchemaField("property_id", "STRING", mode="REQUIRED",
        description="GA4 property ID (Windsor 'account_id'); tenant key + part of MERGE key"),
    bigquery.SchemaField("account_name", "STRING",
        description="GA4 property display name (Windsor 'account_name')"),
    bigquery.SchemaField("client_slug", "STRING",
        description="Internal client slug, derived from property name / campaign / PROPERTY_TO_CLIENT"),
    bigquery.SchemaField("agency_slug", "STRING",
        description="Internal agency slug, e.g. 'ad-assembly' / '100-digital'"),
    bigquery.SchemaField("metric_date", "DATE", mode="REQUIRED",
        description="Date of metrics (GA4 'date', normalised to YYYY-MM-DD); MERGE key + partition field"),

    # ---- Session-scoped acquisition (the grain spine; MERGE-key dims coalesced to '(not set)') ----
    bigquery.SchemaField("session_source", "STRING", mode="REQUIRED",
        description="GA4 session_source. MERGE key."),
    bigquery.SchemaField("session_medium", "STRING", mode="REQUIRED",
        description="GA4 session_medium. MERGE key."),
    bigquery.SchemaField("session_source_medium", "STRING",
        description="Derived 'source / medium' (built in transform, not requested -- saves a GA4 dim slot)"),
    bigquery.SchemaField("session_campaign_name", "STRING", mode="REQUIRED",
        description="GA4 session_campaign_name. MERGE key. Join key to Meta/TTD via UTM campaign naming."),
    bigquery.SchemaField("session_default_channel_group", "STRING", mode="REQUIRED",
        description="GA4 session_default_channel_group (Paid Social / Display / ...)"),

    # ---- Metrics: ADDITIVE BASE ONLY (derive rates / AOV / ARPU in SQL; see docstring) ----
    bigquery.SchemaField("sessions", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("engaged_sessions", "INT64",
        description="-> engagement rate = engaged/sessions; bounce = 1 - that"),
    bigquery.SchemaField("total_users", "INT64", description="GA4 'Users' (totalUsers)"),
    bigquery.SchemaField("new_users", "INT64"),
    bigquery.SchemaField("screen_page_views", "INT64",
        description="Views (screen_view + page_view events)"),
    bigquery.SchemaField("user_engagement_duration", "NUMERIC",
        description="Total engagement, seconds; -> avg engagement time = this/sessions"),
    bigquery.SchemaField("event_count", "INT64"),
    bigquery.SchemaField("conversions", "NUMERIC",
        description="GA4 'Key events' (NUMERIC: can be fractional with conversion modeling)"),
    bigquery.SchemaField("total_revenue", "NUMERIC",
        description="purchase + subscription + ad revenue, in the property's reporting currency"),
    bigquery.SchemaField("purchase_revenue", "NUMERIC"),
    bigquery.SchemaField("ecommerce_purchases", "INT64"),
    bigquery.SchemaField("transactions", "INT64"),

    # ---- Provenance ----
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="'windsor.ga4'"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full original Windsor row (both metric groups merged), for fidelity"),
]

table_id = f"{PROJECT}.{RAW_DATASET}.perf_ga4"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["property_id", "session_default_channel_group"]
table.description = "GA4 Traffic Acquisition, one row per (property x date x session source/medium/campaign x default channel group), via Windsor.ai"

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")