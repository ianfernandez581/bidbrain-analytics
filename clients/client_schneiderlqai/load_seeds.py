r"""Load the human-editable seed CSVs into BigQuery seed_* tables (Schneider Liquid AI dashboard).

STANDARDISED across clients: same loader + CSV contract. Each <stem>.csv -> client_schneiderlqai.
seed_<stem> per SEED_SCHEMAS. Read all as text, '' -> NULL, coerce per schema, WRITE_TRUNCATE.
Run BEFORE create_views.py - this is now BINDING, not advisory. It used to be that no LQAI view read
a seed (only the job did); since 2026-09-14 the content-syndication views DO: sql/07_stg_salesforce
INNER JOINs seed_cs_campaign_map (it is the lane's only scope key) and sql/11_cs_pacing reads
seed_cs_targets. Applying views against a missing seed table fails the whole run.
Run: .\.venv\Scripts\python.exe clients\client_schneiderlqai\load_seeds.py

TARGETS standard (committed CSV -> BQ): the seed CSVs live in data/ and are version-controlled via
an explicit !exception in the root .gitignore, so they are the source of truth in BQ and travel with
the repo.
  * media_plan.csv      - the full media plan, reseeded 2026-09-14 from the signed plan's
                          "Media Plan_updated 2508" tab (12 lines; was the 16 Jul brief's 7).
                          `live=1` flags the channels currently delivering, which the job sums into
                          per-channel targets; `budget_group` selects the paid-media lines the
                          pace-to-plan card measures against.
  * cs_campaign_map.csv - the Salesforce campaign id(s) for the content-syndication lane.
  * cs_targets.csv      - Pangea's per-region lead allocation.
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
        ("note", "STRING"),
        # spend_target_eur: the media plan's OWN EUR figure, NOT a conversion of spend_target.
        # The client reads budgets off the plan's EUR column, so the board must carry those exact
        # numbers - routing AUD through the dashboard's FX constant lands ~3% out and was the
        # cause of the 2026-09-13 "total budget should be EUR281,274" report. EUR-native: it must
        # never be passed through bbApplyFx() in dashboard.html.
        # budget_group: which lines constitute "the budget". paid_media = the 10 media lines the
        # client paces against (sums to EUR 281,274.31); reinvestment = the unallocated
        # New/Reinvestment bucket; lead_gen = the Pangea content-syndication line. The last two are
        # in the plan's EUR 300,000 total but are NOT paid media and are excluded from pacing.
        ("spend_target_eur", "FLOAT"), ("budget_group", "STRING")]),
    # Content syndication (2026-09-14). The campaign map is the ONLY scope key for the CS lane:
    # Schneider's Salesforce uploads carry a blank campaign NAME, so the shared mirror cannot be
    # filtered any other way - see sql/07_stg_salesforce.sql.
    # `confirmed` is 0 while the campaign id is provisional; the job carries it through and the
    # dashboard shows a pending banner rather than presenting unverified leads as settled.
    "cs_campaign_map": ("seed_cs_campaign_map", [
        ("salesforce_campaign_id", "STRING"), ("vendor", "STRING"),
        ("flight_start", "DATE"), ("flight_end", "DATE"),
        ("confirmed", "INTEGER"), ("note", "STRING")]),
    # Pangea's per-region lead allocation, reworked 2026-07-31 (ANZ 68 / India 235 / MEA 18 /
    # SAM 79 = 400 at A$60 CPL). Source: the media plan workbook's "CSVendor Costs & Lead Avails".
    "cs_targets": ("seed_cs_targets", [
        ("vendor", "STRING"), ("region", "STRING"), ("lead_target", "INTEGER"),
        ("cpl_aud", "FLOAT"), ("cost_aud", "FLOAT"), ("note", "STRING")]),
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
