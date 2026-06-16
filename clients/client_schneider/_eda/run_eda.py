"""Phase-1 EDA for the Schneider Electric -> PACIFIC carve-out.

READ-ONLY. Replicates the live dashboard's delivery->internal-campaign join EXACTLY
(dash/dashboard.html idOf(): lowercase the platform CAMPAIGN_NAME, iterate seed_campaign_map
rows in array order, first row whose ANY '|'-token is a substring wins, else '(unmapped)').

Run:  ./.venv/Scripts/python.exe clients/client_schneider/_eda/run_eda.py
Emits readable tables to stdout + a machine summary at _eda/eda_summary.json.
Changes NOTHING in BigQuery.
"""
import json
import os
import sys
from collections import defaultdict

from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
DS = "client_schneider"
LOC = "australia-southeast1"
HERE = os.path.dirname(os.path.abspath(__file__))

# Redirect the full readable report to a UTF-8 file (campaign names carry en-dashes that the
# Windows cp1252 console can't encode). Read _eda/eda_report.txt for the full output.
_orig_stdout = sys.stdout
sys.stdout = open(os.path.join(HERE, "eda_report.txt"), "w", encoding="utf-8")

bq = bigquery.Client(project=PROJECT)


def q(sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


# ---------------------------------------------------------------- seed map (same fetch as job)
seed = q(f"SELECT * FROM `{PROJECT}.{DS}.seed_campaign_map`")  # array order = match precedence
SEED_ORDER = [s["internal_campaign_id"] for s in seed]


def id_of(name):
    """EXACT port of dashboard idOf(): first seed row whose any |-token is a substring wins."""
    n = (name or "").lower()
    for m in seed:
        pats = [p.strip().lower() for p in (m["match_pattern"] or "").split("|") if p.strip()]
        if any(p in n for p in pats):
            return m["internal_campaign_id"]
    return "(unmapped)"


META = {s["internal_campaign_id"]: s for s in seed}

# ---------------------------------------------------------------- 1. platform campaign inventory
# ad_campaigns already = SE slice across the 3 platforms, AUD-converted, delivering only.
inv = q(f"""
  SELECT platform, campaign, imps, clicks, spend_aud, start_date, end_date
  FROM `{PROJECT}.{DS}.ad_campaigns` ORDER BY spend_aud DESC
""")
for r in inv:
    r["id"] = id_of(r["campaign"])

# Cross-check: raw SE slice straight from the mirrors (does the view drop anything?)
raw_counts = q(f"""
  SELECT 'dv360' platform, COUNT(DISTINCT CAMPAIGN_NAME) camps,
         SUM(IMPRESSIONS) imps, SUM(CLICKS) clicks, MIN(DATE(DAY)) mn, MAX(DATE(DAY)) mx
  FROM `{PROJECT}.raw_snowflake.dv360_apac` WHERE ADVERTISER_NAME LIKE 'APAC | Schneider Electric%'
  UNION ALL
  SELECT 'tradedesk', COUNT(DISTINCT CAMPAIGN_NAME),
         SUM(COALESCE(IMPRESSIONS,IMPRESSION)), SUM(CLICKS), MIN(DATE(DAY)), MAX(DATE(DAY))
  FROM `{PROJECT}.raw_snowflake.tradedesk_apac_all` WHERE ADVERTISER_NAME = 'Schneider Electric'
  UNION ALL
  SELECT 'linkedin', COUNT(DISTINCT CAMPAIGN_NAME),
         SUM(IMPRESSIONS), SUM(CLICKS), MIN(DATE(DAY)), MAX(DATE(DAY))
  FROM `{PROJECT}.raw_snowflake.linkedin_ads_apac` WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'
""")

# ---------------------------------------------------------------- 5. currency per platform (raw)
cur = q(f"""
  SELECT 'dv360' platform, CURRENCY, COUNT(*) nrows, SUM(IMPRESSIONS) imps
  FROM `{PROJECT}.raw_snowflake.dv360_apac` WHERE ADVERTISER_NAME LIKE 'APAC | Schneider Electric%'
  GROUP BY CURRENCY
  UNION ALL
  SELECT 'tradedesk', CURRENCY, COUNT(*), SUM(COALESCE(IMPRESSIONS,IMPRESSION))
  FROM `{PROJECT}.raw_snowflake.tradedesk_apac_all` WHERE ADVERTISER_NAME = 'Schneider Electric'
  GROUP BY CURRENCY
  UNION ALL
  SELECT 'linkedin (acct suffix)', REGEXP_EXTRACT(ACCOUNT_NAME, r'_([A-Z]{{3}})$'), COUNT(*), SUM(IMPRESSIONS)
  FROM `{PROJECT}.raw_snowflake.linkedin_ads_apac` WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'
  GROUP BY 2
  ORDER BY platform, imps DESC
""")

# ---------------------------------------------------------------- 4. geography reality check
mkt = q(f"""
  SELECT platform, market, SUM(imps) imps, SUM(spend_aud) spend
  FROM `{PROJECT}.{DS}.stg_ad_delivery` GROUP BY platform, market ORDER BY platform, imps DESC
""")
dv_country = q(f"""
  SELECT COUNTRY_NAME, SUM(IMPRESSIONS) imps
  FROM `{PROJECT}.raw_snowflake.dv360_apac` WHERE ADVERTISER_NAME LIKE 'APAC | Schneider Electric%'
  GROUP BY COUNTRY_NAME ORDER BY imps DESC LIMIT 25
""")

# ---------------------------------------------------------------- 3/6. program substring search
# Look for each Pacific (and excluded) program's likely tokens across ALL delivering campaign names,
# independent of the current seed map, so we can see what exists vs what's mapped.
PROGRAM_PROBES = {
    "Heavy Industries": ["heavy indust", "heavy_indust"],
    "AirSeT": ["airset"],
    "EBA / Building Activate": ["building activate", "eba", "bldg activate"],
    "Water & Environment": ["water", "waterenv", "water & env", "water and env"],
    "Global Rebrand": ["rebrand", "global rebrand"],
    "MCSeT & EvoPacT": ["mcset", "evopact", "cooling solutions"],
    "EcoConsult": ["ecoconsult", "eco consult"],
    "Healthcare": ["healthcare", "health care"],
    "Microgrid": ["microgrid", "micro grid"],
    "EcoCare BMS": ["ecocare", "bms"],
    "Enterprise Software": ["enterprise software", "ent software", "entsoftware"],
    "Industrial Edge": ["industrial edge", "ind edge", "prefab"],
    "EAE / Automation Expert": ["automation expert", "ecostructure", "ecostruxure"],
    "IA Services": ["ia services", "ai services"],
    # excluded books of work:
    "AI & Liquid Cooling [EXCLUDE]": ["ai in dc", "lqaidc", "liquid cooling"],
    "Enterprise IT Expansion [EXCLUDE]": ["entit", "enterprise it"],
    "C&SP [EXCLUDE]": ["c&sp", "csp"],
    # drive-present, maybe unmapped:
    "New Energy Landscape/NEL": ["new energy", "nel"],
    "Cisco Powered Unified Edge": ["cisco", "unified edge"],
    "AVEVA": ["aveva"],
    "Alliance Partner Program": ["alliance partner"],
}
all_camps = q(f"""
  SELECT DISTINCT platform, campaign FROM `{PROJECT}.{DS}.ad_campaigns`
""")
probe_hits = {}
for prog, toks in PROGRAM_PROBES.items():
    hits = []
    for c in all_camps:
        nm = c["campaign"].lower()
        if any(t in nm for t in toks):
            hits.append((c["platform"], c["campaign"], id_of(c["campaign"])))
    probe_hits[prog] = hits

# ---------------------------------------------------------------- roster roll-up by internal id
roster = defaultdict(lambda: {"spend": 0.0, "imps": 0, "clicks": 0, "nCamp": 0,
                              "platforms": set(), "start": None, "end": None, "names": []})
for r in inv:
    e = roster[r["id"]]
    e["spend"] += float(r["spend_aud"] or 0)
    e["imps"] += int(r["imps"] or 0)
    e["clicks"] += int(r["clicks"] or 0)
    e["nCamp"] += 1
    e["platforms"].add(r["platform"])
    e["names"].append(f'{r["platform"]}:{r["campaign"]}')
    s, en = str(r["start_date"]), str(r["end_date"])
    if e["start"] is None or s < e["start"]:
        e["start"] = s
    if e["end"] is None or en > e["end"]:
        e["end"] = en

# ============================================================================ PRINT
def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


hr("RAW SE SLICE vs ad_campaigns VIEW (completeness cross-check)")
for r in raw_counts:
    print(f'{r["platform"]:>10} | raw distinct campaigns={r["camps"]:>4} | imps={int(r["imps"] or 0):>12,} '
          f'| clicks={int(r["clicks"] or 0):>10,} | {r["mn"]} -> {r["mx"]}')
view_by_plat = defaultdict(lambda: [0, 0])
for r in inv:
    view_by_plat[r["platform"]][0] += 1
    view_by_plat[r["platform"]][1] += int(r["imps"] or 0)
print("-- ad_campaigns view (delivering only): " +
      " | ".join(f'{p}={n[0]}c/{n[1]:,}imps' for p, n in sorted(view_by_plat.items())))

hr("1. PLATFORM CAMPAIGN INVENTORY (every delivering campaign, by spend) -> mapped id")
print(f'{"platform":>10} {"id":>16} {"imps":>12} {"clk":>8} {"spend_AUD":>12}  {"start":>10} {"end":>10}  campaign')
for r in inv:
    print(f'{r["platform"]:>10} {r["id"]:>16} {int(r["imps"] or 0):>12,} {int(r["clicks"] or 0):>8,} '
          f'{float(r["spend_aud"] or 0):>12,.0f}  {str(r["start_date"]):>10} {str(r["end_date"]):>10}  {r["campaign"]}')

hr("2. ROSTER by internal id (what the dashboard shows in the campaign filter)")
print(f'{"id":>16} {"display":>34} {"#camp":>5} {"spend_AUD":>12} {"imps":>12}  platforms  window')
for rid, e in sorted(roster.items(), key=lambda kv: -kv[1]["spend"]):
    disp = (META.get(rid, {}) or {}).get("display_name", rid if rid != "(unmapped)" else "(unmapped)")
    print(f'{rid:>16} {str(disp)[:34]:>34} {e["nCamp"]:>5} {e["spend"]:>12,.0f} {e["imps"]:>12,}  '
          f'{",".join(sorted(e["platforms"])):<22} {e["start"]} -> {e["end"]}')

hr("2b. UNMAPPED platform campaigns (fell through to '(unmapped)')")
unmapped = [r for r in inv if r["id"] == "(unmapped)"]
if not unmapped:
    print("  (none — every delivering campaign matched a seed row)")
for r in sorted(unmapped, key=lambda r: -float(r["spend_aud"] or 0)):
    print(f'  {r["platform"]:>10} | {int(r["imps"] or 0):>10,} imps | {float(r["spend_aud"] or 0):>10,.0f} AUD | {r["campaign"]}')

hr("3/6. PROGRAM PROBE — does any delivering campaign name contain each program's tokens?")
for prog, hits in probe_hits.items():
    if hits:
        print(f'\n  ## {prog}: {len(hits)} hit(s)')
        for plat, nm, mid in hits:
            print(f'       [{plat}] -> id={mid}   {nm}')
    else:
        print(f'\n  ## {prog}: NO delivering campaign name matches {PROGRAM_PROBES[prog]}')

hr("4. GEOGRAPHY — market split per platform (org 'Pacific' vs geo 'Pacific' distinction)")
for r in mkt:
    print(f'{r["platform"]:>10} {str(r["market"]):>16} | imps={int(r["imps"] or 0):>12,} | spend={float(r["spend"] or 0):>12,.0f}')
print("\n-- DV360 raw COUNTRY_NAME (top 25) — confirms ANZ dominance & whether geo-Pacific countries appear:")
for r in dv_country:
    print(f'   {str(r["COUNTRY_NAME"]):>6} | {int(r["imps"] or 0):>12,} imps')

hr("5. CURRENCY per platform (validates the FX CASE branches)")
for r in cur:
    print(f'{str(r["platform"]):>22} | {str(r["CURRENCY"]):>5} | rows={int(r["nrows"] or 0):>8,} | imps={int(r["imps"] or 0):>12,}')

hr("SEED MAP — current rows in match precedence (array) order")
for i, s in enumerate(seed):
    print(f'  {i:>2}. {s["internal_campaign_id"]:>16} | job={str(s["brief_job_no"]):>6} | {str(s["objective_type"]):>12} '
          f'| region={str(s["primary_region"]):>8} | pat="{s["match_pattern"]}"')

# ---------------------------------------------------------------- machine summary
summary = {
    "seed_order": SEED_ORDER,
    "inventory": [{"platform": r["platform"], "campaign": r["campaign"], "id": r["id"],
                   "imps": int(r["imps"] or 0), "clicks": int(r["clicks"] or 0),
                   "spend_aud": round(float(r["spend_aud"] or 0), 2),
                   "start": str(r["start_date"]), "end": str(r["end_date"])} for r in inv],
    "roster": {rid: {"display": (META.get(rid, {}) or {}).get("display_name", rid),
                     "nCamp": e["nCamp"], "spend_aud": round(e["spend"], 2), "imps": e["imps"],
                     "platforms": sorted(e["platforms"]), "start": e["start"], "end": e["end"],
                     "names": e["names"]} for rid, e in roster.items()},
    "unmapped": [r["campaign"] for r in unmapped],
    "program_probe": {p: [{"platform": a, "campaign": b, "id": c} for a, b, c in h]
                      for p, h in probe_hits.items()},
    "currency": [{"platform": r["platform"], "currency": r["CURRENCY"],
                  "rows": int(r["nrows"] or 0), "imps": int(r["imps"] or 0)} for r in cur],
    "market": [{"platform": r["platform"], "market": r["market"], "imps": int(r["imps"] or 0),
                "spend_aud": round(float(r["spend"] or 0), 2)} for r in mkt],
}
with open(os.path.join(HERE, "eda_summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
print(f'\n\n[wrote {os.path.join(HERE, "eda_summary.json")}]')
sys.stdout.flush()
sys.stdout = _orig_stdout
print("EDA complete -> _eda/eda_report.txt + _eda/eda_summary.json")
