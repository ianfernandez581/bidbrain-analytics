"""
One-time setup: create the shared raw ad-platform dataset (raw_windsor).

This is the dataset both Windsor loaders write to (perf_the_trade_desk, perf_meta)
and that create_meta_table.py / create_trade_desk__tables.py add tables into, so
it must exist FIRST. Idempotent (exists_ok=True).

Run:  python infra/create_dataset.py
"""
from google.cloud import bigquery
from _config import PROJECT, RAW_DATASET, LOCATION

client = bigquery.Client(project=PROJECT)

dataset_id = f"{PROJECT}.{RAW_DATASET}"
dataset = bigquery.Dataset(dataset_id)
dataset.location = LOCATION
dataset.description = "Shared raw ad-platform performance data (The Trade Desk, Meta, ...), ingested via Windsor.ai"

dataset = client.create_dataset(dataset, exists_ok=True)
print(f"Created dataset {client.project}.{dataset.dataset_id} in {dataset.location}")

for ds in client.list_datasets():
    print(f"  {ds.dataset_id}")
