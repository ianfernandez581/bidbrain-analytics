"""
One-time setup: create the Trade Desk performance table (perf_the_trade_desk).

Lives in raw_windsor alongside perf_meta.

Run:  python windsor_data_pull/tradedesk/create_trade_desk__tables.py   (after create_dataset.py)
Idempotent (exists_ok=True).
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
RAW_DATASET = "raw_windsor"

client = bigquery.Client(project=PROJECT)

# Main fact table
schema = [
    # Identifiers / dimensions
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED",
        description="Source platform, e.g. 'the_trade_desk'"),
    bigquery.SchemaField("advertiser_id", "STRING",
        description="TTD advertiser_id (top-level account)"),
    bigquery.SchemaField("advertiser_name", "STRING",
        description="TTD advertiser name (e.g. 'WEHI')"),
    bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED",
        description="Platform's campaign ID (e.g. TTD campaign_id)"),
    bigquery.SchemaField("campaign_name", "STRING",
        description="Platform's campaign name (e.g. 'WEHI_Awareness_May2026_Display_AU')"),
    bigquery.SchemaField("ad_group_id", "STRING",
        description="TTD ad_group_id (coalesced to 'unknown' if absent — it's a MERGE key)"),
    bigquery.SchemaField("ad_group_name", "STRING",
        description="TTD ad group name"),
    bigquery.SchemaField("creative_id", "STRING",
        description="TTD creative_id (coalesced to 'unknown' if absent — it's a MERGE key)"),
    bigquery.SchemaField("creative_name", "STRING",
        description="TTD creative name (Windsor 'creative' field)"),
    bigquery.SchemaField("client_slug", "STRING",
        description="Internal client slug, derived from campaign name or advertiser"),
    bigquery.SchemaField("agency_slug", "STRING",
        description="Internal agency slug, e.g. 'ad-assembly' or '100-digital'"),
    bigquery.SchemaField("ad_format", "STRING",
        description="Creative dimensions from Windsor (e.g. '728x90', '300x250')"),
    bigquery.SchemaField("metric_date", "DATE", mode="REQUIRED",
        description="Date of the metrics"),

    # Metrics
    bigquery.SchemaField("impressions", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("clicks", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("cost", "NUMERIC", mode="REQUIRED",
        description="Cost in advertiser currency"),
    bigquery.SchemaField("currency", "STRING",
        description="Advertiser currency, e.g. 'AUD'"),
    bigquery.SchemaField("conversions", "JSON",
        description="Compact map of populated TTD conversion slots "
                    "(click_conversion_NN / view_through_conversion_NN / conversion_touch_NN); "
                    "NULL if none fired. See the loader docstring."),
    bigquery.SchemaField("video_starts", "INT64"),
    bigquery.SchemaField("video_25", "INT64"),
    bigquery.SchemaField("video_50", "INT64"),
    bigquery.SchemaField("video_75", "INT64"),
    bigquery.SchemaField("video_completes", "INT64"),

    # Provenance
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="Ingestion source, e.g. 'windsor.tradedesk'"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full original row from Windsor for fidelity"),
]

table_id = f"{PROJECT}.{RAW_DATASET}.perf_the_trade_desk"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["campaign_id", "ad_format"]
table.description = "TTD performance data, one row per (campaign × ad_group × creative × date × ad_format)"

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")