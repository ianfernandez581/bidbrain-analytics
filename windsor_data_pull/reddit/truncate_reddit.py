# windsor_data_pull/reddit/truncate_reddit.py
from google.cloud import bigquery
bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")
bq.query("TRUNCATE TABLE `bidbrain-analytics.raw_windsor.perf_reddit`").result()
print("perf_reddit truncated")
