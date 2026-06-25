r"""
client_mongodb/seed_static.py -- load the VERSION-CONTROLLED target CSVs in targets/ into
BigQuery `client_mongodb.seed_*` tables.

Per the cross-client "targets live in BQ from a committed CSV" standard (see CLAUDE.md): MongoDB's
media-plan targets + media-plan budget used to be SQL-literal views (sql/06_targets.sql,
sql/10_budget.sql). They are now committed CSVs here in targets/ (the source of truth), loaded to
seed_targets / seed_budget; the views sql/06 + sql/10 just SELECT from those seed tables. Edit the
CSV, re-run this, then run the export job with FORCE_REBUILD=1 (a seed change is invisible to the
freshness gate). targets/ is version-controlled (NOT the gitignored data/).

Run:  .\.venv\Scripts\python.exe clients\client_mongodb\seed_static.py
"""
import os
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
DATASET = "client_mongodb"
TARGETS_DIR = os.path.join(os.path.dirname(__file__), "targets")

SF = bigquery.SchemaField
# CSV file (in targets/) -> (BigQuery table, explicit schema in CSV COLUMN ORDER).
SEEDS = {
    "targets.csv": ("seed_targets", [
        SF("PROGRAMME_LABEL", "STRING"), SF("MARKET", "STRING"),
        SF("TARGET_LEADS", "INT64"), SF("DELIVERED_LEADS_SNAPSHOT", "INT64"), SF("CPL", "INT64"),
    ]),
    "budget.csv": ("seed_budget", [
        SF("PROGRAMME_LABEL", "STRING"), SF("TRADEDESK_CODE", "STRING"),
        SF("GROSS_BUDGET_USD", "INT64"), SF("NET_BUDGET_USD", "INT64"),
        SF("START_DATE", "DATE"), SF("END_DATE", "DATE"), SF("EST_CPC", "FLOAT64"),
    ]),
}


def _ensure_not_view(bq, ref):
    """A load job can't overwrite a VIEW. sql/06 + sql/10 may already exist as views of the
    destination seed name on a prior layout — drop any such view first. No-op once it's a table."""
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
