"""Adversarial cross-check of the Python idOf() port (run_eda.py) against an INDEPENDENT
re-derivation done entirely in BigQuery SQL.

- SQL side uses SPLIT()/STRPOS() (not Python str.split/in) and an id->ord ordering typed
  by hand from the data/campaign_map.csv `seq` order (NOT from Python's fetch),
  so a substring/precedence/lowercasing bug in either implementation surfaces as a diff.
- Compares per-campaign mapped id. Exit non-zero (and list diffs) if they disagree.

Run: ./.venv/Scripts/python.exe clients/client_schneider/_eda/verify_mapping.py
"""
import json
import os
import sys

from google.cloud import bigquery

PROJECT, DS, LOC = "bidbrain-analytics", "client_schneider", "australia-southeast1"
HERE = os.path.dirname(os.path.abspath(__file__))
bq = bigquery.Client(project=PROJECT)

# Seed array order typed independently from data/campaign_map.csv `seq` column (match precedence).
# Updated 2026-06-16 for the Pacific carve-out (eba split in after eae; airset + 4 placeholders added);
# 2026-06-22 added `nel` (seq 27) when the seeds moved to data/campaign_map.csv.
ORD = ["eae", "eba", "aveva", "ai_lc", "csp", "ent_it", "water_env", "ind_edge", "mcset",
       "ia_services", "impact_maker", "iof", "mea_seg", "power_products", "digital_bldg",
       "digital_power", "ecocare", "modernisation", "active_kpx", "pac_hybrid_it",
       "airset", "heavy", "ecoconsult", "global_rebrand", "healthcare", "microgrid",
       "enterprise_software", "nel"]
ord_values = ",".join(f"STRUCT('{i}' AS id,{n} AS ord)" for n, i in enumerate(ORD))

sql = f"""
WITH ord_map AS (SELECT * FROM UNNEST([{ord_values}])),
seed AS (
  SELECT s.internal_campaign_id AS id, s.match_pattern, o.ord
  FROM `{PROJECT}.{DS}.seed_campaign_map` s JOIN ord_map o ON o.id = s.internal_campaign_id
),
camp AS (SELECT DISTINCT campaign FROM `{PROJECT}.{DS}.ad_campaigns`),
matches AS (
  SELECT c.campaign, s.id, s.ord
  FROM camp c CROSS JOIN seed s
  WHERE (SELECT COUNT(1) FROM UNNEST(SPLIT(s.match_pattern,'|')) t
         WHERE TRIM(t) != '' AND STRPOS(LOWER(c.campaign), LOWER(TRIM(t))) > 0) > 0
),
ranked AS (
  SELECT campaign, id, ROW_NUMBER() OVER(PARTITION BY campaign ORDER BY ord) rn FROM matches
)
SELECT c.campaign, COALESCE(r.id,'(unmapped)') AS sql_id
FROM camp c LEFT JOIN ranked r ON r.campaign=c.campaign AND r.rn=1
"""
sql_map = {r["campaign"]: r["sql_id"] for r in bq.query(sql, location=LOC).result()}

with open(os.path.join(HERE, "eda_summary.json"), encoding="utf-8") as f:
    summ = json.load(f)
py_map = {r["campaign"]: r["id"] for r in summ["inventory"]}

diffs = [(c, py_map[c], sql_map.get(c, "<<missing>>"))
         for c in py_map if py_map[c] != sql_map.get(c)]
missing = set(py_map) ^ set(sql_map)

print(f"campaigns: python={len(py_map)} sql={len(sql_map)} | set-symmetric-diff={len(missing)}")
if missing:
    print("  CAMPAIGN-SET MISMATCH:", list(missing)[:10])
if diffs:
    print(f"MAPPING DISAGREEMENTS ({len(diffs)}):")
    for c, p, s in diffs:
        print(f"  py={p:>14}  sql={s:>14}  {c}")
    sys.exit(1)
print("VERIFIED: Python idOf() == independent BigQuery SQL re-derivation on all "
      f"{len(py_map)} delivering campaigns. No disagreements.")
