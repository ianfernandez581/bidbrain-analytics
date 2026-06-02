# windsor_data_pull/ga4/truncate_ga4.py
from google.cloud import bigquery
bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")
bq.query("TRUNCATE TABLE `bidbrain-analytics.raw_windsor.perf_ga4`").result()
print("perf_ga4 truncated")