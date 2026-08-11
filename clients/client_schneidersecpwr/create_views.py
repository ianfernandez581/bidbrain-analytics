"""
Apply the client_schneidersecpwr BigQuery view definitions from version-controlled SQL.

Each *.sql file in client_schneidersecpwr/sql/ holds one CREATE OR REPLACE VIEW, applied in filename
order (the NN_ prefix enforces dependency order: 01/02 stg_linkedin/stg_tradedesk -> 03 delivery ->
04 creative). The export job (client_schneidersecpwr/job/main.py) SELECTs from these views to
assemble schneidersecpwr.json.

This is the Schneider Electric "Secure Power" dashboard - the three briefs held OUT of
client_schneider because they have separate stakeholders (Enterprise IT Expansion 1958, Industrial
Edge / Prefab 2463, Software First EcoStruxure 2305). It reads its sources straight from the shared
raw layer (raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}), so there is NO src_* landing step
and NO seed table - the campaigns are delivery-only (no media plan, no targets).

Order:
    1. create the client_schneidersecpwr dataset + GCS bucket
    2. python clients/client_schneidersecpwr/create_views.py
    3. run the export job to build schneidersecpwr.json

NEVER edit these views in the BigQuery console - sql/*.sql is the source of truth or they drift.

Run:  .\.venv\Scripts\python.exe clients\client_schneidersecpwr\create_views.py
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
