# windsor_data_pull/linkedin/truncate_linkedin.py
from google.cloud import bigquery
bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")
bq.query("TRUNCATE TABLE `bidbrain-analytics.raw_windsor.perf_linkedin`").result()
print("perf_linkedin truncated")
