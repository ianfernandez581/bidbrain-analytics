r"""Load the committed LinkedIn ad-set TARGETING sheet into BigQuery (seed_adset_targeting).

WHY THIS EXISTS (read before "just use the API"):
LinkedIn's ad-set targeting configuration - job titles, seniorities, functions, industries, the
matched-audience / TAL attached, exclusions and the forecast audience size - is NOT in any feed this
repo has. It is absent from `raw_snowflake.linkedin_ads_apac` (33 columns, all delivery metrics) and
from Windsor's `perf_linkedin`. The only machine source is the LinkedIn Marketing API
(`GET /rest/adCampaigns/{id}` -> `targetingCriteria`, then `adTargetingEntities` to resolve each URN
to a human label), which needs a developer app provisioned with the **Advertising API** product AND a
member token with a VIEWER+ role on ad account 517045062 - that account belongs to Transmission, so
it is a grant we do not hold today.

Until that lands this is the repo-standard fallback: a COMMITTED CSV -> BQ seed table (the same
pattern as every client's targets - md/AGENTS.md "committed-CSV -> BQ"). The media buyer records each
ad set's audience ONCE, in version control, instead of re-screenshotting Campaign Manager every time
a client asks for the report.

    targeting/adset_targeting.csv  ->  client_schneidersecpwr.seed_adset_targeting
                                   ->  sql/05_linkedin_adsets.sql (LEFT JOIN on adset_id)
                                   ->  job/main.py  ->  dashboard.html "Reports" tab

THE CSV DOES NOT OWN THE AD-SET LIST. Which ad sets exist, their current names, phase, geo and
delivery all come from the data (`stg_linkedin`); the seed contributes ONLY the audience columns.
The `campaign` / `adset_name` / `phase` / `geo` columns in the CSV are REFERENCE ONLY - they exist so
a human can tell the rows apart, are rewritten by --scaffold, and are ignored by the view. That way a
LinkedIn rename can never orphan a filled-in row (the join key is the numeric adset_id, which is
stable - repo rule: "campaign names are NOT stable keys").

Run:
    # refresh the row list from live delivery, PRESERVING everything already filled in
    .\.venv\Scripts\python.exe clients\client_schneidersecpwr\load_targeting.py --scaffold

    # push the CSV to BigQuery (run BEFORE create_views.py - sql/05 joins this table)
    .\.venv\Scripts\python.exe clients\client_schneidersecpwr\load_targeting.py
"""
import csv
import os
import sys

from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
DATASET = "client_schneidersecpwr"
TABLE = "seed_adset_targeting"

CSV_PATH = os.path.join(os.path.dirname(__file__), "targeting", "adset_targeting.csv")

# Reference columns (rewritten by --scaffold, ignored by the view) then the payload columns a human
# fills in. Order is the CSV's column order.
REF_COLS = ["adset_id", "campaign", "adset_name", "phase", "geo"]
DATA_COLS = ["targeting_method", "job_titles", "job_seniorities", "job_functions",
             "industries", "company_list", "exclusions", "audience_size", "notes"]
COLS = REF_COLS + DATA_COLS

# Everything is STRING on purpose, audience_size included: Campaign Manager shows a forecast that is
# sometimes a number ("124,000") and sometimes a range ("50,000-100,000"). The Excel exporter writes
# it as a number when it parses as one and as text otherwise, so neither form is lost here.
SCHEMA = [bigquery.SchemaField(c, "STRING") for c in COLS]

SCAFFOLD_SQL = f"""
WITH latest AS (
  SELECT
    adset_id,
    ARRAY_AGG(STRUCT(adset_name, market) ORDER BY metric_date DESC, imps DESC LIMIT 1)[OFFSET(0)] AS cur,
    ANY_VALUE(campaign) AS campaign
  FROM `{PROJECT}.{DATASET}.stg_linkedin`
  WHERE adset_id IS NOT NULL
  GROUP BY adset_id
)
SELECT adset_id, campaign, cur.adset_name AS adset_name, cur.market AS geo
FROM latest
ORDER BY campaign, adset_name
"""

# Phase tokens, longest/most specific first. Retargeting before Conversion before Consideration
# before Awareness: 'Conversion' CONTAINS 'Con', so a naive Consideration-first test mislabels every
# conversion ad set. Kept identical to the CASE in sql/05_linkedin_adsets.sql - if you change one,
# change both (the view is the source of truth on screen; this only pre-fills the CSV's hint column).
PHASE_TOKENS = [
    ("Retargeting",   ["RTG", "RT1", "RT2", "RETARGET"]),
    ("Conversion",    ["CNV", "CONVERSION"]),
    ("Consideration", ["CNS", "CONSIDERATION", "- CON ", "_CON_", " CON "]),
    ("Awareness",     ["AWR", "AWARENESS"]),
]


def phase_of(name):
    up = f" {(name or '').upper()} "
    for label, toks in PHASE_TOKENS:
        if any(t in up for t in toks):
            return label
    return "Unspecified"


def read_csv():
    if not os.path.exists(CSV_PATH):
        return {}
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return {r.get("adset_id", "").strip(): r for r in csv.DictReader(f)
                if (r.get("adset_id") or "").strip()}


def scaffold():
    """Rewrite the CSV's row list from live delivery, preserving every filled-in value."""
    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    live = list(bq.query(SCAFFOLD_SQL).result())
    existing = read_csv()

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    kept = added = 0
    rows = []
    for r in live:
        aid = str(r["adset_id"])
        prev = existing.get(aid, {})
        if prev:
            kept += 1
        else:
            added += 1
        row = {c: (prev.get(c) or "") for c in COLS}
        # Reference columns always follow the data, never the stale CSV.
        row.update(adset_id=aid, campaign=r["campaign"], adset_name=r["adset_name"],
                   phase=phase_of(r["adset_name"]), geo=r["geo"] or "")
        rows.append(row)

    # An ad set that stopped delivering is NOT dropped - its report row is still historically true and
    # re-deriving hand-entered targeting would be lost work. It is parked at the end, flagged.
    for aid, prev in existing.items():
        if not any(x["adset_id"] == aid for x in rows):
            row = {c: (prev.get(c) or "") for c in COLS}
            row["notes"] = (row.get("notes") or "").strip()
            if "no longer delivering" not in row["notes"].lower():
                row["notes"] = (row["notes"] + " | " if row["notes"] else "") + "no longer delivering"
            rows.append(row)

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    filled = sum(1 for r in rows if any((r.get(c) or "").strip() for c in DATA_COLS))
    print(f"scaffolded {CSV_PATH}: {len(rows)} ad sets ({added} new, {kept} preserved), "
          f"{filled} with targeting filled in")


def load():
    if not os.path.exists(CSV_PATH):
        raise SystemExit(f"missing {CSV_PATH} - run with --scaffold first")
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{CSV_PATH} is missing column(s): {', '.join(missing)}")
        rows = [{c: (r.get(c) or "").strip() for c in COLS} for r in reader
                if (r.get("adset_id") or "").strip()]
    if not rows:
        raise SystemExit(f"{CSV_PATH} has no rows - refusing to publish an empty seed")

    dupes = {r["adset_id"] for r in rows if [x["adset_id"] for x in rows].count(r["adset_id"]) > 1}
    if dupes:
        raise SystemExit(f"duplicate adset_id in {CSV_PATH}: {', '.join(sorted(dupes))} "
                         "- the view joins on it, so it must be unique")

    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    job = bq.load_table_from_json(
        rows, table_id,
        job_config=bigquery.LoadJobConfig(
            schema=SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
    )
    job.result()
    filled = sum(1 for r in rows if any(r[c] for c in DATA_COLS))
    print(f"loaded {len(rows)} rows into {table_id} ({filled} with targeting filled in, "
          f"{len(rows) - filled} still blank)")


if __name__ == "__main__":
    if "--scaffold" in sys.argv:
        scaffold()
    else:
        load()
