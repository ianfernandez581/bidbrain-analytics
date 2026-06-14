"""
Apply the client_vmch BigQuery view definitions from version-controlled SQL.

Mirrors client_STT/create_views.py. Each *.sql file in client_vmch/sql/ holds
one CREATE OR REPLACE VIEW, applied in filename order. VMCH reads straight from
the shared raw layers (raw_ga4 and raw_windsor), so there is NO src_* landing step
and NO bootstrap-first-failure.

Sources:
  - raw_ga4.perf_ga4 (session-grain)
  - raw_ga4.perf_ga4_events (event-grain)
  - raw_windsor.perf_the_trade_desk (The Trade Desk, AUD)

Run:  python clients/client_vmch/create_views.py
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