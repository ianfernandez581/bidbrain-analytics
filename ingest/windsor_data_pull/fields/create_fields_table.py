"""
One-time setup: create the Windsor FIELD CATALOGUE table (windsor_fields).

Grain: ONE ROW per Windsor field `id` (the `fields=` token you pass to the connectors
API). This is NOT performance data -- it's the catalogue of EVERY field Windsor.ai
exposes across EVERY connector, the same list the public page renders:
    https://windsor.ai/data-field/all/   (data source: https://connectors.windsor.ai/all/fields)
~37.8k fields at build time.

Why this lives in BigQuery (and not a committed file): the catalogue is ~9 MB of JSON
and grows as Windsor adds connectors/fields -- it does not belong in git. It lives in
raw_windsor like every other Windsor table, refreshed DAILY by the windsor-fields-ingest
Cloud Run job (see fields_loader.py).

NEW-FIELD DETECTION is the whole point of refreshing it daily. Each field carries:
  - first_seen : the date we FIRST observed this id. A field Windsor just added gets
                 first_seen = today, so   WHERE first_seen = CURRENT_DATE()   == "new today".
  - last_seen  : the most recent run that still saw it. We never DELETE rows, so a field
                 Windsor drops simply stops advancing last_seen   (last_seen < CURRENT_DATE()
                 == "no longer in the catalogue").

available_in_connectors is the list of connector slugs each field works in (e.g.
['facebook','google_ads','googleanalytics4',...]) -- this is what makes the table useful:
"which connectors expose field X", or "what fields can I pull from connector Y".

Not partitioned (small, slowly-changing reference table); clustered by type then id.

Run:  python windsor_data_pull/fields/create_fields_table.py   (after create_dataset.py)
Idempotent (exists_ok=True) -- CREATEs, does not ALTER. If an earlier/narrower version
exists, drop it first (it's cheap to repopulate):  bq rm -f -t bidbrain-analytics:raw_windsor.windsor_fields
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
RAW_DATASET = "raw_windsor"

client = bigquery.Client(project=PROJECT, location="australia-southeast1")

schema = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED",
        description="Windsor field token (the value you pass in `fields=`). MERGE key."),
    bigquery.SchemaField("name", "STRING",
        description="Human-readable field name shown on windsor.ai/data-field/all"),
    bigquery.SchemaField("description", "STRING",
        description="Windsor's description of the field"),
    bigquery.SchemaField("type", "STRING",
        description="Windsor data type: TEXT / NUMERIC / OBJECT / BOOLEAN / TIMESTAMP / "
                    "DATE / PERCENT / COUNTRY / CITY / IMAGE_URL / REGION"),
    bigquery.SchemaField("available_in_connectors", "STRING", mode="REPEATED",
        description="Connector slugs this field is available in (e.g. 'facebook', "
                    "'google_ads', 'googleanalytics4'). The catalogue's reason to exist."),
    bigquery.SchemaField("n_connectors", "INT64",
        description="len(available_in_connectors) -- cheap filter/sort helper"),

    # ---- change tracking (the daily-refresh payoff) ----
    bigquery.SchemaField("first_seen", "DATE", mode="REQUIRED",
        description="Date this id was first observed. WHERE first_seen = CURRENT_DATE() == new today."),
    bigquery.SchemaField("last_seen", "DATE", mode="REQUIRED",
        description="Most recent run that still saw this id. last_seen < CURRENT_DATE() == dropped."),
    bigquery.SchemaField("snapshot_date", "DATE", mode="REQUIRED",
        description="Date of the snapshot that last touched this row (== last_seen)"),

    # ---- provenance ----
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="'windsor.all/fields' (our provenance tag)"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full original field object from the API, for fidelity"),
]

table_id = f"{PROJECT}.{RAW_DATASET}.windsor_fields"
table = bigquery.Table(table_id, schema=schema)
table.clustering_fields = ["type", "id"]
table.description = ("Windsor.ai field catalogue: one row per field id across all connectors, "
                     "with first_seen/last_seen change tracking. Source: "
                     "https://connectors.windsor.ai/all/fields (refreshed daily).")

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Clustered by: {table.clustering_fields}")
print(f"  Columns:      {len(table.schema)}")
