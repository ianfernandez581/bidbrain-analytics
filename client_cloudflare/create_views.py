"""
Apply the client_cloudflare BigQuery view definitions from version-controlled SQL.

Mirrors client_mongodb/create_views.py. Each *.sql file in client_cloudflare/sql/
holds one CREATE OR REPLACE VIEW, applied in filename order (use an NN_ prefix to
control order). The export job (client_cloudflare/job/main.py) reads these views
to assemble cloudflare.json.

DELIBERATE DIVERGENCE FROM client_mongodb:
Cloudflare's data model already lives in Snowflake (CLOUDFLARE_SANDBOX.* views),
so these BigQuery views are *thin*: the job pulls Snowflake's final-model views,
lands them as BigQuery src_* tables, and these views expose them in the shape the
dashboard expects. MongoDB does the modelling in BigQuery; Cloudflare does not
re-derive it. See client_cloudflare/sql/README.md.

Fresh-project order (see ../README.md):
    1. create the client_cloudflare dataset + GCS bucket
    2. run the export job once to land the src_* tables
    3. python client_cloudflare/create_views.py
    4. re-run the export job to build cloudflare.json

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
