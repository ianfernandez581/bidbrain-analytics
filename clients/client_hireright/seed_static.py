r"""
client_hireright/seed_static.py -- load the VERSION-CONTROLLED target CSV in targets/ into the
BigQuery `client_hireright.seed_*` table(s).

Per the cross-client "targets live in BQ from a committed CSV" standard (see md/AGENTS.md):
HireRight's media plan is `targets/media_plan.csv` (the source of truth, tracked in git), loaded
here to `seed_media_plan`; `sql/18_targets.sql` is a thin view over it and `sql/19_pacing.sql`
joins it to actual delivery.

STATUS: the CSV is currently EMPTY of values (HireRight has no signed media plan in this repo).
That is a supported state, not a broken one -- every numeric column is NULLABLE, the load succeeds
with three all-blank rows, `targets.has_targets` resolves to FALSE and the dashboard hides its
pacing section entirely. Fill the CSV in and re-run to turn pacing on. See targets/README.md.

Edit the CSV, re-run this, then run the export job with FORCE_REBUILD=1 -- a seed change is
invisible to the freshness gate (which watches the three raw Snowflake tables), so without the
force the new targets sit unpublished until the next upstream change.

Run:  .\.venv\Scripts\python.exe clients\client_hireright\seed_static.py
"""
import os

from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
DATASET = "client_hireright"
TARGETS_DIR = os.path.join(os.path.dirname(__file__), "targets")

SF = bigquery.SchemaField
# CSV file (in targets/) -> (BigQuery table, explicit schema in CSV COLUMN ORDER).
# Every target column is NULLABLE on purpose: a blank cell means "the plan does not commit to
# this", which is NOT the same as a target of zero. The views and the dashboard both treat NULL
# as "no commitment" and omit the metric rather than reporting a miss against it.
SEEDS = {
    "media_plan.csv": ("seed_media_plan", [
        SF("PLATFORM", "STRING"), SF("LINE_ITEM", "STRING"),
        SF("FLIGHT_START", "DATE"), SF("FLIGHT_END", "DATE"),
        SF("BUDGET_USD", "FLOAT64"),
        SF("IMP_TARGET", "INT64"), SF("CLICK_TARGET", "INT64"), SF("LEAD_TARGET", "INT64"),
        SF("CTR_TARGET", "FLOAT64"), SF("CPM_TARGET_USD", "FLOAT64"), SF("CPC_TARGET_USD", "FLOAT64"),
    ]),
}


def _ensure_not_view(bq, ref):
    """A load job can't overwrite a VIEW. Drop any view sitting on the destination name first.
    No-op once it's a table."""
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
    # Say plainly whether this actually turns pacing on, so an empty load isn't mistaken for a
    # successful one. (An all-blank CSV loads fine and changes nothing on screen.)
    q = (f"SELECT COUNTIF(BUDGET_USD IS NOT NULL OR IMP_TARGET IS NOT NULL "
         f"OR CLICK_TARGET IS NOT NULL OR LEAD_TARGET IS NOT NULL) AS n "
         f"FROM `{PROJECT}.{DATASET}.seed_media_plan`")
    n = list(bq.query(q, location=LOC).result())[0].n
    if n:
        print(f"\n{n} line item(s) carry a real target -> the dashboard's pacing section WILL render.")
        print("Next: create_views.py, then the export job with FORCE_REBUILD=1.")
    else:
        print("\nNo targets set (every value cell is blank) -> pacing stays HIDDEN on the dashboard.")
        print("That is the expected state until a signed media plan lands. See targets/README.md.")
    print("done.")


if __name__ == "__main__":
    main()
