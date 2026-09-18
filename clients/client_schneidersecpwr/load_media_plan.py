r"""Load the committed media-plan targets into BigQuery (seed_media_plan) - Schneider Secure Power.

    targets/media_plan.csv  ->  client_schneidersecpwr.seed_media_plan
                            ->  job/main.py (read directly - NO sql view, the lqai pattern)
                            ->  campaigns[].plan  ->  dashboard.html pacing section

Same loader contract as `client_schneiderlqai/load_seeds.py`: read every column as text, '' -> NULL,
coerce per schema, WRITE_TRUNCATE. Deliberately SEPARATE from `load_targeting.py` (the Reports tab's
hand-recorded ad-set audience) - two seeds with different owners and different refresh cadences, so
one loader doing both would couple a monthly plan edit to an ad-set scaffold refresh.

Run:  .\.venv\Scripts\python.exe clients\client_schneidersecpwr\load_media_plan.py

THREE THINGS THIS SEED ENCODES THAT ARE EASY TO GET WRONG
---------------------------------------------------------
1. **THE IMPRESSION TARGETS ARE CORRECTED x10 AND ARE NOT WHAT THE CLIENT'S SHEET PRINTS.**
   "2463 Final media plan - SEE Industrial Edge Wave 3", tab "Media Plan + CPL", column I rows 14-17
   was calculated as `cost / CPM * 100` where the intended formula is `cost / CPM * 1000` - the
   client stated that formula herself (2026-09-18) and all four lines reproduce to the decimal under
   the x100 form, so it is one bad cell copied down, not four typos. Cost and CPM are correct (they
   tie to the stated A$52,150 with Direct IT), so cost and CPM are the trustworthy inputs and
   impressions are a derived OUTPUT. Seeding the sheet as printed would publish this brief at
   **337% of target** when it is really at **34%**.
   -> Because these figures are OURS and not yet reissued by the client, the job keeps the global
      `has_targets` FALSE. The whole chain is wired and DORMANT (the `client_hireright` pattern).
      Flip it when the client reissues the sheet or confirms the corrected figures in writing -
      until then the dashboard would contradict the plan document sitting in their inbox.

2. **`measurable` IS THE PACING DENOMINATOR GATE, and it is data rather than code.**
   The Direct IT line is A$23,000 of a A$52,150 budget - 44% - and is an OFFLINE LEAD VENDOR with no
   media delivery in any warehouse. Pacing against the committed figure would report a permanent 44%
   shortfall that no amount of delivery could close (md/AGENTS.md "pace against the budget that can
   actually spend"). So it is carried with `measurable=0`: it counts toward the COMMITTED budget the
   client signed and is excluded from every pacing denominator. Do not delete the row to "fix"
   pacing - the committed figure is what the client recognises, and dropping it would make the
   dashboard's budget disagree with their plan.

3. **REACH, CLICKS AND CTR ARE DELIBERATELY NOT SEEDED.**
   The sheet derives them FROM the impression column, so they inherited the same x10 error, and no
   corrected values have been confirmed. Seeding a derived-from-wrong figure is worse than having no
   target: a missing target hides its card, a wrong one paces against a number nobody agreed. Add
   them only when the client states them.

Columns are in CSV header order. `campaign` is the internal brief key (`ind_edge`), which is what
makes targets PER BRIEF - ent_it (1958) and software_first (2305) have no plan, and a single global
flag would promise pacing on two briefs that cannot deliver it.
"""
import os
import pandas as pd
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
DATASET = "client_schneidersecpwr"
DATA_DIR = os.path.join(os.path.dirname(__file__), "targets")

SEED_SCHEMAS = {
    "media_plan": ("seed_media_plan", [
        ("campaign", "STRING"), ("channel", "STRING"), ("channel_key", "STRING"),
        ("tactic", "STRING"), ("geo", "STRING"),
        ("flight_start", "DATE"), ("flight_end", "DATE"),
        ("imp_target", "INTEGER"), ("spend_target", "FLOAT"), ("cpm_target", "FLOAT"),
        ("measurable", "INTEGER"), ("live", "INTEGER"), ("note", "STRING")]),
}


def _ensure_table(bq, ref):
    """A load job cannot overwrite a VIEW, so drop one if it is sitting on the name."""
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
    missing = [c for c, _ in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"{path}: missing declared column(s) {missing}")
    df = df[[c for c, _ in cols]]
    for c, t in cols:
        if t in ("FLOAT", "INTEGER"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
            if t == "INTEGER":
                df[c] = df[c].astype("Int64")
        elif t == "DATE":
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        else:
            df[c] = df[c].astype("string")

    # Guard the two invariants the job relies on, HERE rather than downstream: a silently malformed
    # seed is how a pacing denominator goes wrong without anything going red.
    if df["campaign"].isna().any():
        raise SystemExit(f"{path}: every row needs a `campaign` brief key - targets are PER BRIEF")
    bad = df[(df["measurable"] == 1) & (df["spend_target"].isna())]
    if len(bad):
        raise SystemExit(f"{path}: {len(bad)} measurable row(s) carry no spend_target - a pacing "
                         f"denominator cannot be built from them")

    schema = [bigquery.SchemaField(c, t) for c, t in cols]
    ref = f"{PROJECT}.{DATASET}.{table}"
    _ensure_table(bq, ref)
    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema)
    bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
    print(f"loaded {len(df):>3} rows -> {ref}")
    for camp, g in df.groupby("campaign"):
        meas = g[g["measurable"] == 1]
        print(f"  {camp}: {len(g)} line(s), committed A${g['spend_target'].sum():,.0f}, "
              f"measurable A${meas['spend_target'].sum():,.0f}, "
              f"imp target {int(meas['imp_target'].fillna(0).sum()):,}")


def main():
    bq = bigquery.Client(project=PROJECT)
    for stem, (table, cols) in SEED_SCHEMAS.items():
        load_one(bq, stem, table, cols)
    print("seed load complete.")


if __name__ == "__main__":
    main()
