"""
Apply the client_proptrack BigQuery view definitions from version-controlled SQL.

Mirrors client_STT/create_views.py. Each *.sql file in client_proptrack/sql/ holds
one CREATE OR REPLACE VIEW, applied in filename order (the NN_ prefix enforces
dependency order: the stg_* filter views — 01/02/03 — before the 04–15 roll-ups that
read them). The export job (client_proptrack/job/main.py) SELECTs from these views to
assemble proptrack.json.

Like client_STT, PropTrack reads its two sources straight from the shared raw layer in
Snowflake (raw_snowflake.{tradedesk_apac_all, linkedin_ads_apac}), so there is NO src_*
landing step and NO bootstrap-first-failure. The views exist as soon as this runs, so
the order is simply:
    1. create the client_proptrack dataset + GCS bucket
    2. python client_proptrack/create_views.py
    3. run the export job to build proptrack.json

Run:  python client_proptrack/create_views.py
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
