"""
Apply the client_cityperfume BigQuery view definitions from version-controlled SQL.

Mirrors client_STT/create_views.py. Each *.sql file in client_cityperfume/sql/ holds
one CREATE OR REPLACE VIEW, applied in filename order (the NN_ prefix enforces
dependency order: the stg_* filter views — 01..06 — before the 10..35 rollups that
read them). The export job (client_cityperfume/job/main.py) SELECTs from these views
to assemble cityperfume.json.

City Perfume sources span three raw layers + one first-party view, all already in
BigQuery (no Snowflake src_* landing step):
    - raw_google_ads.perf_google_ads        (account_name='City Perfume')
    - raw_windsor.perf_meta                  (account_name='Cityperfume.com.au')
    - raw_windsor.perf_the_trade_desk        (advertiser_name='City Perfume')
    - raw_ga4.perf_ga4 / raw_ga4.perf_ga4_events
    - client_cityperfume.v_sales             (first-party order-line sales — TRUTH)

Everything is AUD (no FX). The reporting window is 2025-06-01 -> latest, applied once
in each stg_* view. v_sales (and its customer-identity columns) NEVER leave BigQuery
in row form — the rollups and the export job emit aggregates only.

Run:  .\\.venv\\Scripts\\python.exe client_cityperfume\\create_views.py
"""
import glob
import os

from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"

SQL_DIR = os.path.join(os.path.dirname(__file__), "sql")


def main():
    files = sorted(glob.glob(os.path.join(SQL_DIR, "*.sql")))
    if not files:
        raise SystemExit(
            f"No .sql files in {os.path.abspath(SQL_DIR)} -- nothing to apply."
        )
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    for path in files:
        print(f"Applying {os.path.basename(path)} ...")
        with open(path, encoding="utf-8") as f:
            client.query(f.read()).result()
    print(f"Applied {len(files)} view(s).")


if __name__ == "__main__":
    main()
