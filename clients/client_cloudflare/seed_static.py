r"""
client_cloudflare/seed_static.py -- load the local static CSV snapshots in data/
into BigQuery `client_cloudflare.seed_*` tables. (data/ is gitignored per
clients/*/data/; regenerate it with pull_static.py if absent.)

These are Cloudflare's STATIC inputs (pacing targets, account->tier mapping, the
LINE JP manual upload). They are NOT in the shared `raw_snowflake` mirror (that
layer carries only the dynamic ad-platform tables), so they get a simple seed:
    data/real_targets.csv -> client_cloudflare.seed_real_targets   (V_TARGETS_V2_NORM source)
    data/tiers.csv        -> client_cloudflare.seed_tiers           (V_TIER_MAPPING_CLEANED source)
    data/line_cf.csv      -> client_cloudflare.seed_line_cf         (LINE JP paid-media source)

The CSVs are produced by the one-time `pull_static.py` (Snowflake -> data/). This
loader reads ONLY the local CSVs -- no Snowflake connection. The `sql/` views then
model everything in BigQuery over these seeds + the `raw_snowflake` mirrors, so the
export job never touches Snowflake (true MongoDB parity).

Explicit BigQuery schemas lock the column types the views depend on (notably the
DATE columns used in the pacing week-join). Re-run after pull_static.py refreshes a
CSV, then kick the export job once with FORCE_REBUILD=1 (a seed change is invisible
to the freshness gate -- see CLAUDE.md).

Run:  .\.venv\Scripts\python.exe clients\client_cloudflare\seed_static.py
"""
import os
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
DATASET = "client_cloudflare"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

SF = bigquery.SchemaField
# CSV file -> (BigQuery table, explicit schema in CSV COLUMN ORDER).
# (BQ maps columns by position when a schema is given + header is skipped.)
SEEDS = {
    "real_targets.csv": ("seed_real_targets", [
        SF("WEEK", "INT64"), SF("DATE", "DATE"), SF("TIER", "STRING"),
        SF("REGION", "STRING"), SF("COUNTRY", "STRING"), SF("TARGET", "INT64"),
    ]),
    "tiers.csv": ("seed_tiers", [
        SF("ACCOUNT_NAME", "STRING"), SF("WEBSITE", "STRING"), SF("L1", "STRING"),
        SF("L2", "STRING"), SF("BILLING_COUNTRY", "STRING"), SF("INDUSTRY", "STRING"),
        SF("COHORT", "STRING"), SF("PRIORITY", "STRING"), SF("TIER", "STRING"),
    ]),
    "line_cf.csv": ("seed_line_cf", [
        SF("DAY", "DATE"), SF("AD_NAME", "STRING"), SF("IMPRESSIONS", "INT64"),
        SF("CLICKS", "INT64"), SF("COST", "INT64"), SF("VIDEO_STARTS", "INT64"),
        SF("VIDEO_100_WATCHED", "INT64"),
    ]),
}


def main():
    bq = bigquery.Client(project=PROJECT)
    for fname, (dest, schema) in SEEDS.items():
        path = os.path.join(DATA_DIR, fname)
        ref = f"{PROJECT}.{DATASET}.{dest}"
        cfg = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            schema=schema,
            write_disposition="WRITE_TRUNCATE",
            # TIERS account-name/website fields contain embedded newlines (quoted by
            # pandas), so the CSV reader must honour quoted newlines.
            allow_quoted_newlines=True,
        )
        with open(path, "rb") as f:
            job = bq.load_table_from_file(f, ref, job_config=cfg, location=LOC)
        job.result()
        n = bq.get_table(ref).num_rows
        print(f"loaded {n:>6} rows | {fname}  ->  {ref}")
    print("done.")


if __name__ == "__main__":
    main()
