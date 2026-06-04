"""
Apply the client_mongodb BigQuery view definitions from version-controlled SQL.

The export job (client_mongodb/job/main.py) SELECTs from these views; until they
exist in BigQuery the job fails on a fresh project. Each *.sql file in
client_mongodb/sql/ holds one `CREATE OR REPLACE VIEW`, applied in filename
order (use an NN_ prefix to control dependency order: stg_* before the models
and rollups that read them).

Fresh-project order:
    1. python snowflake_data_pull/create_dataset.py
    2. python snowflake_data_pull/loader.py   (lands raw_snowflake.*, shared)
    3. python client_mongodb/create_views.py  (these views read raw_snowflake.*)
    4. run the export job to build <client>.json

See client_mongodb/sql/README.md for how to export the live view DDL.

Run:  python client_mongodb/create_views.py
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
            f"DDL first (see client_mongodb/sql/README.md)."
        )
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    for path in files:
        print(f"Applying {os.path.basename(path)} ...")
        with open(path, encoding="utf-8") as f:
            client.query(f.read()).result()
    print(f"Applied {len(files)} view(s).")


if __name__ == "__main__":
    main()
