"""
One-time setup: create the shared raw ad-platform dataset (raw_windsor).

This is the dataset both Windsor loaders write to (perf_the_trade_desk, perf_meta)
and that meta/create_meta_table.py / tradedesk/create_trade_desk__tables.py add
tables into, so it must exist FIRST. Idempotent (exists_ok=True).

Lives at the windsor_data_pull root because the dataset is shared by both
loaders -- it belongs to neither meta nor tradedesk specifically.

Run:  python windsor_data_pull/create_dataset.py
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
RAW_DATASET = "raw_windsor"  # shared raw ad-platform dataset; loaders write here

client = bigquery.Client(project=PROJECT)

dataset_id = f"{PROJECT}.{RAW_DATASET}"
dataset = bigquery.Dataset(dataset_id)
dataset.location = LOCATION
dataset.description = "Shared raw ad-platform performance data (The Trade Desk, Meta, ...), ingested via Windsor.ai"

dataset = client.create_dataset(dataset, exists_ok=True)
print(f"Created dataset {client.project}.{dataset.dataset_id} in {dataset.location}")

for ds in client.list_datasets():
    print(f"  {ds.dataset_id}")
