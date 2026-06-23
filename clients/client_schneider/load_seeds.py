r"""Load the human-editable seed CSVs in data/ into BigQuery seed_* tables.

STANDARDISED across clients: same loader + same data/ CSV contract. Each
data/<stem>.csv -> client_<c>.seed_<stem-mapped> per SEED_SCHEMAS. Read all as
text, '' -> NULL, coerce per schema, WRITE_TRUNCATE. Run BEFORE create_views.py
(stg_salesforce + lead_* views read seed_salesforce_map).
Run: .\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py

VIEW->TABLE MIGRATION (automatic): seed_campaign_map / seed_plan_budget /
seed_plan_flighting / seed_targets / seed_channel_split previously existed as
VIEWS (old sql/30-34). A load job cannot overwrite a VIEW, so load_one() first
drops any pre-existing VIEW of the destination name (_ensure_table) before
loading. This is generic / client-agnostic and a no-op once the names are
TABLES, so WRITE_TRUNCATE re-runs stay idempotent.
"""
import os
import pandas as pd
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
DATASET = "client_schneider"                         # the ONE per-client line
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# csv stem -> (bq table, [(column, BQ type)])  — column order = CSV header order
SEED_SCHEMAS = {
    "campaign_map": ("seed_campaign_map", [
        ("seq", "INTEGER"), ("internal_campaign_id", "STRING"), ("display_name", "STRING"),
        ("brief_job_no", "STRING"), ("objective_type", "STRING"), ("primary_kpi", "STRING"),
        ("pillar", "STRING"), ("primary_region", "STRING"), ("match_pattern", "STRING"),
        ("portfolio", "STRING")]),
    "plan_budget": ("seed_plan_budget", [
        ("internal_campaign_id", "STRING"), ("budget_aud", "FLOAT"), ("budget_basis", "STRING"),
        ("flight_start", "DATE"), ("flight_end", "DATE")]),
    "plan_flighting": ("seed_plan_flighting", [
        ("internal_campaign_id", "STRING"), ("period", "STRING"), ("weight_pct", "FLOAT")]),
    "targets": ("seed_targets", [
        ("internal_campaign_id", "STRING"), ("kpi", "STRING"), ("target_value", "FLOAT")]),
    "channel_split": ("seed_channel_split", [
        ("internal_campaign_id", "STRING"), ("stage", "STRING"), ("channel", "STRING"),
        ("budget_aud", "FLOAT")]),
    "media_plan": ("seed_media_plan", [
        ("internal_campaign_id", "STRING"), ("channel", "STRING"), ("line_type", "STRING"),
        ("flight_start", "DATE"), ("flight_end", "DATE"), ("spend_aud", "FLOAT"),
        ("imp_target", "INTEGER"), ("reach_target", "INTEGER"), ("click_target", "INTEGER"),
        ("lead_target", "INTEGER"), ("sf_campaign_id", "STRING"), ("note", "STRING")]),
    "salesforce_map": ("seed_salesforce_map", [
        ("salesforce_campaign_id", "STRING"), ("internal_campaign_id", "STRING"),
        ("pillar_label", "STRING")]),
}


def _ensure_table(bq, ref):
    """If `ref` currently exists as a VIEW (e.g. a pre-migration seed_* view from the old
    sql/30-34), drop it so the load job can create a TABLE in its place — a load job cannot
    overwrite a view. No-op once it's already a table (or absent). Generic / client-agnostic."""
    from google.api_core.exceptions import NotFound
    try:
        t = bq.get_table(ref)
    except NotFound:
        return
    if t.table_type == "VIEW":
        bq.delete_table(ref)
        print(f"dropped pre-existing VIEW {ref} (migrating view -> table)")


def load_one(bq, stem, table, cols):
    path = os.path.join(DATA_DIR, f"{stem}.csv")
    if not os.path.exists(path):
        print(f"skip {stem}: no {path}")
        return
    df = pd.read_csv(path, dtype=str, keep_default_na=False).replace("", None)
    df = df[[c for c, _ in cols]]                    # declared columns, in order
    for c, t in cols:
        if t in ("FLOAT", "INTEGER"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
            if t == "INTEGER":
                df[c] = df[c].astype("Int64")
        elif t == "DATE":
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        else:
            df[c] = df[c].astype("string")
    schema = [bigquery.SchemaField(c, t) for c, t in cols]
    ref = f"{PROJECT}.{DATASET}.{table}"
    _ensure_table(bq, ref)                           # drop a pre-existing view of this name
    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema)
    bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
    print(f"loaded {len(df):>3} rows -> {ref}")


def main():
    bq = bigquery.Client(project=PROJECT)
    for stem, (table, cols) in SEED_SCHEMAS.items():
        load_one(bq, stem, table, cols)
    print("seed load complete.")


if __name__ == "__main__":
    main()
