from google.cloud import bigquery

client = bigquery.Client(project="bidbrain-analytics")

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

table_id = "bidbrain-analytics.reports.perf_the_trade_desk"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["campaign_id", "ad_format"]
table.description = "TTD performance data, one row per (campaign × date × ad_format)"

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")