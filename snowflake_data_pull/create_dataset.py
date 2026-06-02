"""
One-time setup: create the shared raw Snowflake dataset (raw_snowflake).

Sibling of windsor_data_pull/create_dataset.py (which makes raw_windsor). The
loader (snowflake_data_pull/loader.py) WRITE_TRUNCATEs each Snowflake source
table into here; every client dashboard then reads this ONE shared raw layer
and applies its own filter + rollups in its own BigQuery views.

Idempotent (exists_ok=True).

Run:  python snowflake_data_pull/create_dataset.py
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
RAW_DATASET = "raw_snowflake"  # shared raw source mirror; the loader writes here

client = bigquery.Client(project=PROJECT)

dataset_id = f"{PROJECT}.{RAW_DATASET}"
dataset = bigquery.Dataset(dataset_id)
dataset.location = LOCATION
dataset.description = (
    "Shared raw source tables mirrored 1:1 from Snowflake (Salesforce CS, "
    "TradeDesk, ...). All clients, unfiltered; each client filters/transforms "
    "this in its own views."
)

dataset = client.create_dataset(dataset, exists_ok=True)
print(f"Created dataset {client.project}.{dataset.dataset_id} in {dataset.location}")

for ds in client.list_datasets():
    print(f"  {ds.dataset_id}")
