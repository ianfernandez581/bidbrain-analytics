r"""
client_geocon/seed_static.py -- load the VERSION-CONTROLLED target CSVs in targets/ into
BigQuery `client_geocon.seed_*` tables.

Geocon's targets are a flat key/value model (flight_budget_aud, cpl_target_aud, ctr_target,
monthly_lead_target, ...) loaded to seed_targets; the budget/flight window is loaded to
seed_budget. The views sql/03_targets + sql/04_budget SELECT from these seed tables. Edit the
CSV, re-run this, then run the export job with FORCE_REBUILD=1 (a seed change is invisible to
the freshness gate). targets/ is version-controlled (NOT the gitignored data/).

Rows with status='PENDING' are placeholders needing client sign-off; the UI renders them with a
"target pending confirmation" marker so nobody mistakes an assumption for an agreed KPI.

Run:  .\.venv\Scripts\python.exe clients\client_geocon\seed_static.py
"""
import os
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
DATASET = "client_geocon"
TARGETS_DIR = os.path.join(os.path.dirname(__file__), "targets")

SF = bigquery.SchemaField
# CSV file (in targets/) -> (BigQuery table, explicit schema in CSV COLUMN ORDER).
SEEDS = {
    # Both target seeds are keyed by DEVELOPMENT (property_key, the same key seed_property_map
    # uses) since 2026-08-24. Gateway Braddon and Northbourne Gateway carry different budgets,
    # flights and benchmarks; one flat set would have paced each against the other's plan.
    "targets.csv": ("seed_targets", [
        SF("property_key", "STRING"),
        SF("key", "STRING"), SF("value", "STRING"), SF("status", "STRING"),
    ]),
    "budget.csv": ("seed_budget", [
        SF("property_key", "STRING"), SF("budget_aud", "FLOAT64"),
        SF("measurable_budget_aud", "FLOAT64"),
        SF("flight_start", "DATE"), SF("flight_end", "DATE"),
    ]),
    # The signed media plan, one row per BOUGHT LINE. Northbourne Gateway buys nine lines across
    # five channels, each with its own impression / click / CPM / CTR target, so a single blended
    # benchmark would be meaningless (a search line's plan CPM is ~A$1,178, a Trade Desk line's is
    # A$15). `measurable` = FALSE marks a line no ad server will ever report -- the SEO retainer
    # and the Google management fee -- which is why the dashboard paces on the measurable budget.
    # `match_pattern` attributes delivery back to the line that bought it (three Trade Desk lines
    # share one advertiser); see sql/06_media_plan.sql and sql/10_fact_all.sql.
    "media_plan.csv": ("seed_media_plan", [
        SF("property_key", "STRING"), SF("seq", "INT64"), SF("phase", "STRING"),
        SF("line_name", "STRING"), SF("media", "STRING"), SF("channel", "STRING"),
        SF("description", "STRING"), SF("targeting", "STRING"), SF("geo", "STRING"),
        SF("imp_target", "INT64"), SF("video_view_target", "INT64"),
        SF("reach_target", "INT64"), SF("freq_cap", "FLOAT64"),
        SF("cpm_target", "FLOAT64"), SF("cpv_target", "FLOAT64"),
        SF("ctr_target", "FLOAT64"), SF("click_target", "INT64"),
        SF("budget_aud", "FLOAT64"), SF("cost_type", "STRING"),
        SF("measurable", "BOOL"), SF("match_pattern", "STRING"),
    ]),
    # PROPERTY (development) map - the client_schneider seed_campaign_map pattern, scaled down.
    # `seq` is MATCH PRECEDENCE (lowest wins, exactly like schneider's first-match-wins idOf join);
    # `match_pattern` is '|'-separated case-insensitive SUBSTRING tokens matched against the Meta
    # campaign name. The CATCH-ALL row carries an EMPTY pattern and the HIGHEST seq, so anything
    # unmatched lands there - that is what keeps Gateway Braddon's numbers stable when a new
    # development appears. `status` drives the dashboard selector: `coming_soon` renders disabled
    # until real rows arrive, then it enables itself.
    #
    # ADDING A DEVELOPMENT IS NOW A CSV EDIT, NOT A SQL EDIT: add a row, run this script, re-run
    # the export. Simulate the pattern first, exactly as the schneider README instructs:
    #     SELECT DISTINCT campaign_name, property FROM `...client_geocon.stg_meta` ORDER BY 1;
    "property_map.csv": ("seed_property_map", [
        SF("seq", "INT64"), SF("property_key", "STRING"), SF("display_name", "STRING"),
        SF("match_pattern", "STRING"), SF("status", "STRING"),
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