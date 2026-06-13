"""
Apply the client_schneider BigQuery view definitions from version-controlled SQL.

Mirrors client_STT/create_views.py. Each *.sql file in client_schneider/sql/ holds one
CREATE OR REPLACE VIEW, applied in filename order (the NN_ prefix enforces dependency
order: the stg_* filters — 01/02/03 — then the unified base 04, then the 05-14 roll-ups,
then the 30-34 seeds, then the 40-46 GA4 layer). The export job (client_schneider/job/main.py)
SELECTs from these views to assemble schneider.json.

Like client_STT, Schneider reads its sources straight from the shared raw layer in BigQuery
(raw_snowflake.{dv360_apac, linkedin_ads_apac, tradedesk_apac_all} — and, once enabled,
google_analytics_apac_all), so there is NO src_* landing step and NO bootstrap-first-failure.
The views exist as soon as this runs, so the order is simply:
    1. create the client_schneider dataset + GCS bucket
    2. python client_schneider/create_views.py
    3. run the export job to build schneider.json

Run:  python client_schneider/create_views.py
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
