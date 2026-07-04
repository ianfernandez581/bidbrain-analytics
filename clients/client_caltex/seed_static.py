r"""
client_caltex/seed_static.py -- load the VERSION-CONTROLLED target CSVs in targets/ into
BigQuery `client_caltex.seed_*` tables.

Caltex's targets are a flat key/value model (flight_budget_aud, cpl_target_aud, ctr_target,
monthly_lead_target, ...) loaded to seed_targets; the budget/flight window is loaded to
seed_budget. The views sql/03_targets + sql/04_budget SELECT from these seed tables. Edit the
CSV, re-run this, then run the export job with FORCE_REBUILD=1 (a seed change is invisible to
the freshness gate). targets/ is version-controlled (NOT the gitignored data/).

Rows with status='PENDING' are placeholders needing client sign-off; the UI renders them with a
"target pending confirmation" marker so nobody mistakes an assumption for an agreed KPI.

Run:  .\.venv\Scripts\python.exe clients\client_caltex\seed_static.py
"""
import os
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
DATASET = "client_caltex"
TARGETS_DIR = os.path.join(os.path.dirname(__file__), "targets")

SF = bigquery.SchemaField
# CSV file (in targets/) -> (BigQuery table, explicit schema in CSV COLUMN ORDER).
SEEDS = {
    "targets.csv": ("seed_targets", [
        SF("key", "STRING"), SF("value", "STRING"), SF("status", "STRING"),
    ]),
    "budget.csv": ("seed_budget", [
        SF("campaign_key", "STRING"), SF("budget_aud", "FLOAT64"),
        SF("flight_start", "DATE"), SF("flight_end", "DATE"),
    ]),
}


def _ensure_not_view(bq, ref):
    """A load job can't overwrite a VIEW. sql/03 + sql/04 may already exist as views of the
    destination seed name on a prior layout -- drop any such view first. No-op once it's a table."""
    try:
        t = bq.get_table(ref)
        if t.table_type == "VIEW":
            bq.delete_table(ref)
    except Exception:  # noqa: BLE001  (absent table -> nothing to drop)
        pass


def main():
    bq = bigquery.Client(project=PROJECT)
    for fname, (dest, schema) in SEEDS.items():
        path = os.path.join(TARGETS_DIR, fname)
        ref = f"{PROJECT}.{DATASET}.{dest}"
        _ensure_not_view(bq, ref)
        cfg = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            schema=schema,
            write_disposition="WRITE_TRUNCATE",
            allow_quoted_newlines=True,
        )
        with open(path, "rb") as f:
            bq.load_table_from_file(f, ref, job_config=cfg, location=LOC).result()
        n = bq.get_table(ref).num_rows
        print(f"loaded {n:>4} rows | {fname}  ->  {ref}")
    print("done.")


if __name__ == "__main__":
    main()