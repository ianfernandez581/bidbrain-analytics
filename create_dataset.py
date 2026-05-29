from google.cloud import bigquery

client = bigquery.Client(project="bidbrain-analytics")

dataset_id = "bidbrain-analytics.reports"
dataset = bigquery.Dataset(dataset_id)
dataset.location = "australia-southeast1"
dataset.description = "TTD + future ad platform performance data, ingested via Windsor.ai"

dataset = client.create_dataset(dataset, exists_ok=True)
print(f"Created dataset {client.project}.{dataset.dataset_id} in {dataset.location}")

for ds in client.list_datasets():
    print(f"  {ds.dataset_id}")