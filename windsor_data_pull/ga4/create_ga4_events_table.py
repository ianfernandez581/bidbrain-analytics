# windsor_data_pull/ga4/create_ga4_events_table.py
#
# Event-grain sibling of create_ga4_table.py.
# Creates  bidbrain-analytics.raw_windsor.perf_ga4_events  at grain
#   (property_id x metric_date x event_name)  -- one row per event type per day.
#
# Unlike perf_ga4 (session / acquisition scope, where event-scoped fields would
# multiply rows and break additivity), EVERY metric here is event-scoped and
# additive across the grain, so SUM(event_count) / SUM(event_value) /
# SUM(conversions) across event_name are all correct.
#
# Idempotent: CREATE TABLE IF NOT EXISTS. Run once, or again after a schema edit.
#   python windsor_data_pull/ga4/create_ga4_events_table.py

from google.cloud import bigquery

PROJECT_ID = "bidbrain-analytics"
DATASET    = "raw_windsor"          # VERIFY: same dataset perf_ga4 lives in (create_ga4_table.py)
TABLE      = "perf_ga4_events"
TABLE_FQN  = f"{PROJECT_ID}.{DATASET}.{TABLE}"

SCHEMA = [
    # --- identity / tenancy (mirror perf_ga4) ---
    bigquery.SchemaField("property_id",         "STRING",    mode="REQUIRED",
                         description="GA4 property id (Windsor account_id)."),
    bigquery.SchemaField("client_slug",         "STRING",    mode="REQUIRED",
                         description="Tenant slug, e.g. mongodb / cloudflare / stt."),
    bigquery.SchemaField("agency_slug",         "STRING",    mode="NULLABLE",
                         description="Owning agency slug (mirrors perf_ga4)."),
    # --- grain ---
    bigquery.SchemaField("metric_date",         "DATE",      mode="REQUIRED",
                         description="Event date. Partition key."),
    bigquery.SchemaField("event_name",          "STRING",    mode="REQUIRED",
                         description="GA4 event name; '(not set)' when absent. Grain dimension."),
    # --- attribute (functionally determined by event_name, so not part of the key) ---
    bigquery.SchemaField("is_conversion_event", "BOOL",      mode="NULLABLE",
                         description="True when event_name is a GA4 key event."),
    # --- additive event metrics ---
    bigquery.SchemaField("event_count",         "INTEGER",   mode="NULLABLE",
                         description="Event count. Additive across the grain."),
    bigquery.SchemaField("event_value",         "FLOAT",     mode="NULLABLE",
                         description="Sum of the 'value' event param. Additive."),
    bigquery.SchemaField("conversions",         "FLOAT",     mode="NULLABLE",
                         description="GA4 key events (can be fractional). Additive."),
    # --- audit (mirror perf_ga4) ---
    bigquery.SchemaField("raw_row",             "JSON",      mode="NULLABLE",
                         description="Raw Windsor row for this grain."),
    bigquery.SchemaField("_loaded_at",          "TIMESTAMP", mode="NULLABLE",
                         description="UTC load timestamp."),
]


def main():
    client = bigquery.Client(project=PROJECT_ID)
    table = bigquery.Table(TABLE_FQN, schema=SCHEMA)
    # Same strategy as perf_ga4: partition by the date, cluster by tenant + the
    # grain dimension so per-client / per-event scans stay cheap.
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="metric_date"
    )
    table.clustering_fields = ["client_slug", "event_name"]   # VERIFY: align with perf_ga4 cluster keys
    created = client.create_table(table, exists_ok=True)
    print(f"ready: {created.project}.{created.dataset_id}.{created.table_id}")


if __name__ == "__main__":
    main()