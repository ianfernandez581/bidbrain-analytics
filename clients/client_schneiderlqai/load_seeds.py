r"""Load the human-editable seed CSVs into BigQuery seed_* tables (Schneider Liquid AI dashboard).

STANDARDISED across clients: same loader + CSV contract. Each <stem>.csv -> client_schneiderlqai.
seed_<stem> per SEED_SCHEMAS. Read all as text, '' -> NULL, coerce per schema, WRITE_TRUNCATE.
Run BEFORE create_views.py (though the LQAI views don't read the seed — the job does).
Run: .\.venv\Scripts\python.exe clients\client_schneiderlqai\load_seeds.py

TARGETS standard (committed CSV -> BQ): the media-plan targets live in data/media_plan.csv, which is
version-controlled via an explicit !exception in the root .gitignore, so it is the source of truth in
BQ and travels with the repo. It carries the full brief media plan (7 lines: LinkedIn / Trade Desk /
Search / Reddit across Awareness + Retargeting); `live=1` flags the channels currently delivering
(LinkedIn Awareness + both Trade Desk Awareness lines), which the job sums into per-channel targets.
"""
import os
import pandas as pd
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
DATASET = "client_schneiderlqai"                     # the ONE per-client line
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# csv stem -> (bq table, [(column, BQ type)])  — column order = CSV header order
SEED_SCHEMAS = {
    "media_plan": ("seed_media_plan", [
        ("channel", "STRING"), ("channel_key", "STRING"), ("phase", "STRING"),
        ("geo", "STRING"), ("flight_start", "DATE"), ("flight_end", "DATE"),
        ("imp_target", "INTEGER"), ("reach_target", "INTEGER"), ("click_target", "INTEGER"),
        ("ctr_target", "FLOAT"), ("spend_target", "FLOAT"), ("live", "INTEGER"),
        ("note", "STRING")]),
}


def _ensure_table(bq, ref):
    """If `ref` currently exists as a VIEW, drop it so the load job can create a TABLE in its place —
    a load job cannot overwrite a view. No-op once it's already a table (or absent)."""
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
    _ensure_table(bq, ref)
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
