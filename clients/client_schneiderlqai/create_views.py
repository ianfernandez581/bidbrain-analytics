"""
Apply the client_schneiderlqai BigQuery view definitions from version-controlled SQL.

Each *.sql file in client_schneiderlqai/sql/ holds one CREATE OR REPLACE VIEW, applied in
filename order (the NN_ prefix enforces dependency order: 01/02 stg_linkedin/stg_tradedesk ->
03 delivery -> 04 creative). The export job (client_schneiderlqai/job/main.py) SELECTs from these
views to assemble schneiderlqai.json.

This is the Schneider "Liquid AI Data Center" (LQAIDC) single-campaign dashboard — LinkedIn + The
Trade Desk TOFU/Awareness delivery across 6 countries. It reads its sources straight from the shared
raw layer (raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}), so there is NO src_* landing step.
Order:
    1. create the client_schneiderlqai dataset + GCS bucket
    2. python clients/client_schneiderlqai/load_seeds.py   (media-plan targets -> seed_media_plan)
    3. python clients/client_schneiderlqai/create_views.py
    4. run the export job to build schneiderlqai.json

Run:  python clients/client_schneiderlqai/create_views.py
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
