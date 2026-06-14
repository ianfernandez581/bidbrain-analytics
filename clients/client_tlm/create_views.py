"""Apply the client_tlm BigQuery view definitions from version-controlled SQL.

Mirrors client_resetdata/create_views.py. Each *.sql file in client_tlm/sql/ holds
one CREATE OR REPLACE VIEW, applied in filename order (the NN_ prefix enforces
dependency order: the stg_* filter views — 01-03 — before the 04-13 rollups that
read them). The export job (client_tlm/job/main.py) SELECTs from these views
to assemble tlm.json.

TLM reads two sources from TWO shared raw layers:
  * raw_google_ads.perf_google_ads      -> paid search + shopping + PMax (native DTS; spend already AUD)
  * raw_windsor.perf_the_trade_desk     -> programmatic display (AUD via Windsor — no FX needed)
There is NO Meta, NO GA4, NO Reddit — TLM is a two-platform e-commerce build.
There is NO src_* landing step and NO bootstrap-first-failure — the views exist as
soon as this runs, so the order is simply:
    1. create the client_tlm dataset + GCS bucket
    2. python client_tlm/create_views.py
    3. run the export job to build tlm.json

Using create_views.py (the python BigQuery client) rather than `Get-Content | bq query`
on Windows avoids the WinPS UTF-8 corruption of SQL comments.

Run:  python client_tlm/create_views.py
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