"""
One-time setup: create the shared raw ad-platform dataset (raw_windsor).

This is the dataset all the Windsor loaders write to (perf_the_trade_desk,
perf_meta, perf_ga4, perf_ga4_events) and that the per-loader create_*_table.py
scripts add tables into, so it must exist FIRST. Idempotent (exists_ok=True).

Lives at the windsor_data_pull root because the dataset is shared by every
loader -- it belongs to no single one (meta / tradedesk / ga4).

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
