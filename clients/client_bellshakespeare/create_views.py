"""
Apply the client_bellshakespeare BigQuery view definitions from version-controlled SQL.

The export job (client_bellshakespeare/job/main.py) SELECTs from these views; until they
exist in BigQuery the job fails on a fresh project. Each *.sql file in
client_bellshakespeare/sql/ holds one `CREATE OR REPLACE VIEW`, applied in filename
order (use an NN_ prefix to control dependency order: stg_* before the daily
model and the rollups that read it).

Bell Shakespeare's raw layer is raw_windsor.perf_meta (Windsor-sourced, self-refreshing) --
NOT Snowflake. So there is no stage-1 loader to run first; the raw table already
exists and refreshes itself.

Fresh-project order:
    1. (raw_windsor.perf_meta already exists via the Windsor connector)
    2. python client_bellshakespeare/seed_static.py   (lands seed_targets / seed_budget)
    3. python client_bellshakespeare/create_views.py  (these views read raw_windsor.* + seeds)
    4. run the export job to build bellshakespeare.json

See client_bellshakespeare/sql/README.md for how to export the live view DDL.

Run:  python client_bellshakespeare/create_views.py
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
            f"No .sql files in {os.path.abspath(SQL_DIR)} -- export the live view "
            f"DDL first (see client_bellshakespeare/sql/README.md)."
        )
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    for path in files:
        print(f"Applying {os.path.basename(path)} ...")
        with open(path, encoding="utf-8") as f:
            client.query(f.read()).result()
    print(f"Applied {len(files)} view(s).")


if __name__ == "__main__":
    main()