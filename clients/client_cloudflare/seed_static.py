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
DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
TARGETS_DIR = os.path.join(os.path.dirname(__file__), "targets")
# Targets are the per-client "committed CSV -> BQ" source of truth: they live in the
# version-controlled targets/ dir (NOT gitignored data/), so anyone who clones the repo can
# reproduce client_cloudflare.seed_real_targets. tiers.csv / line_cf.csv stay in data/ (pulled
# snapshots / manual paid-media drops, not targets). SRC_DIR routes each CSV to its dir.
SRC_DIR = {"real_targets.csv": TARGETS_DIR, "cs_targets_q3.csv": TARGETS_DIR}

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
    # Core DG Content-Syndication Q3 lead targets, long format (theatre x vendor x market
    # x week), APAC + EMEA. Source of truth for the "Pacing detail" section's pacing;
    # loaded once per quarter from the client's pacing sheet, and the ONLY non-live input
    # on that section - which is why the dashboard warns in Admin View when the latest
    # WEEK_START falls behind the current week (last quarter this failed silently and the
    # model returned zero targets for seven weeks).
    # MARKET_SEQ is the chart's market DISPLAY ORDER: re-order the CSV, re-seed, and the
    # chart follows - no code change, no deploy. Totals: APAC 2,290 / EMEA 830.
    "cs_targets_q3.csv": ("seed_cs_targets_q3", [
        SF("THEATRE", "STRING"), SF("VENDOR", "STRING"), SF("MARKET", "STRING"),
        SF("MARKET_SEQ", "INT64"), SF("WEEK_NUMBER", "INT64"),
        SF("WEEK_START", "DATE"), SF("TARGET", "INT64"),
    ]),
    "line_cf.csv": ("seed_line_cf", [
        SF("DAY", "DATE"), SF("AD_NAME", "STRING"), SF("IMPRESSIONS", "INT64"),
        SF("CLICKS", "INT64"), SF("COST", "INT64"), SF("VIDEO_STARTS", "INT64"),
        SF("VIDEO_100_WATCHED", "INT64"),
    ]),
}


def main():
    bq = bigquery.Client(project=PROJECT)
    missing = []
    for fname, (dest, schema) in SEEDS.items():
        path = os.path.join(SRC_DIR.get(fname, DATA_DIR), fname)
        ref = f"{PROJECT}.{DATASET}.{dest}"
        # A CSV that lives in gitignored data/ is absent on a fresh checkout until
        # pull_static.py runs. SKIP it with a warning instead of aborting: the committed
        # targets/ seeds must still load, and the existing BQ table for a skipped CSV is
        # left ALONE (never truncated to empty). Anything under targets/ is version
        # controlled, so if one of those is missing that is a real error - say so loudly.
        if not os.path.exists(path):
            tracked = SRC_DIR.get(fname) == TARGETS_DIR
            if tracked:
                raise SystemExit(
                    f"MISSING TRACKED SEED {path}\n"
                    f"  {fname} lives in the version-controlled targets/ dir and should be in "
                    f"the checkout. Restore it before seeding."
                )
            missing.append(fname)
            print(f"SKIP   (not in checkout) | {fname}  ->  {ref} left unchanged")
            continue
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
    if missing:
        print(f"\nNOTE: skipped {len(missing)} gitignored CSV(s) absent from this checkout: "
              f"{', '.join(missing)}")
        print("      Their BigQuery tables were NOT modified. Run pull_static.py (needs the "
              "Snowflake key) or drop the file in data/ if you need to refresh them.")
    print("done.")


if __name__ == "__main__":
    main()
