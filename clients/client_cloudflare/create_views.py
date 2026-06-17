"""
Apply the client_cloudflare BigQuery view definitions from version-controlled SQL.

Mirrors client_mongodb/create_views.py. Each *.sql file in client_cloudflare/sql/
holds one CREATE OR REPLACE VIEW, applied in filename order (the NN_ prefix encodes
dependency order: staging -> models). The export job (client_cloudflare/job/main.py)
reads the final views to assemble cloudflare.json.

BigQuery owns the model (MongoDB parity, since 2026-06-17). The views model everything
in BigQuery over the shared raw_snowflake.* mirrors + the client_cloudflare.seed_*
static tables -- the job no longer pulls pre-modelled Snowflake views. See
client_cloudflare/sql/README.md for the ported chain.

Fresh-project order (see ../README.md):
    1. create the client_cloudflare dataset + GCS bucket
    2. python client_cloudflare/pull_static.py   (Snowflake -> data/ CSVs, one-time)
    3. python client_cloudflare/seed_static.py   (data/ CSVs -> client_cloudflare.seed_*)
    4. python client_cloudflare/create_views.py  (this; needs the seeds + raw_snowflake to exist)
    5. run the export job to build cloudflare.json

Run:  python client_cloudflare/create_views.py
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
