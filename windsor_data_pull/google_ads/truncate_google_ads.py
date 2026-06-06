# windsor_data_pull/google_ads/truncate_google_ads.py
from google.cloud import bigquery
bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")
bq.query("TRUNCATE TABLE `bidbrain-analytics.raw_windsor.perf_google_ads`").result()
print("perf_google_ads truncated")
