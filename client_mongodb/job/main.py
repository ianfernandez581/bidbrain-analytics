import json, datetime
from google.cloud import bigquery, storage

# --- Project-wide constants ---------------------------------------------------
# One GCP project -> identical for EVERY client, so hardcoded here.
PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"

# --- The ONE line that differs per client -------------------------------------
# Copy this folder for a new client and change ONLY this (e.g. "acme").
# Dataset / bucket / output object all follow from it via the naming convention.
CLIENT = "mongodb"

DATASET     = f"client_{CLIENT}"                    # client_mongodb
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-mongodb-dash
DATA_OBJECT = f"{CLIENT}.json"                      # mongodb.json

# This job no longer touches Snowflake. The Snowflake source tables are mirrored
# into BigQuery (raw_snowflake.*) by the shared snowflake_data_pull/ unit, and
# this client's views filter + transform them (see client_mongodb/sql/). So the
# refresh is TWO steps now:
#   1. python snowflake_data_pull/loader.py     (refresh the shared raw layer)
#   2. run this job                             (BigQuery views -> mongodb.json)
# The per-client filter (campaign IDs) and the LEAD_STATUS != 'New' rule live in
# the stg_salesforce view, not here.


def iso(v):
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return str(v)


def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def main():
    bq = bigquery.Client(project=PROJECT)

    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    pm  = rows(bq, f"SELECT * FROM {t('paid_media_model')}")
    win = rows(bq, f"SELECT MIN(d.DATE) AS s, MAX(d.DATE) AS e, "
                   f"DATE_DIFF(MAX(d.DATE),MIN(d.DATE),DAY)+1 AS days FROM {t('paid_media_model')} d")[0]
    tgt = rows(bq, f"SELECT * FROM {t('targets')}")
    bs  = rows(bq, f"SELECT * FROM {t('benchmarks_strategy')}")
    bm  = rows(bq, f"SELECT * FROM {t('benchmarks_market')}")
    bud = rows(bq, f"SELECT * FROM {t('budget')}")
    cso = rows(bq, f"SELECT * FROM {t('cs_leads')}")
    csp = rows(bq, f"SELECT * FROM {t('cs_leads_by_programme')}")

    env = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_count": len(pm),
        "window": {"start": iso(win["s"]), "end": iso(win["e"]), "days": win["days"]},
        "all_markets": ["ANZ","ASEAN","INDIA","KR-HK-TW"],
        "all_programmes": ["IDE","IDC"],
        "rows": [{"channel": r["CHANNEL"], "date": iso(r["DATE"]), "week_start": iso(r["WEEK_START"]),
                  "programme": r["PROGRAMME"], "market": r["MARKET"], "strategy": r["STRATEGY"],
                  "objective": r["OBJECTIVE"], "imps": r["IMPS"], "clicks": r["CLICKS"],
                  "spend_usd": r["SPEND_USD"], "conversions": r["CONVERSIONS"], "leads": r["LEADS"]} for r in pm],
        "targets": [{"programme": r["PROGRAMME_LABEL"], "market": r["MARKET"],
                     "target": r["TARGET_LEADS"], "delivered": r["DELIVERED_LEADS_SNAPSHOT"]} for r in tgt],
        "benchmarks_strategy": {r["STRATEGY"]: {"cpm": r["CPM"], "ctr": r["CTR"],
                     "frequency": r["FREQUENCY_CAP"], "weight": r["BUDGET_WEIGHT"]} for r in bs},
        "benchmarks_market": {r["MARKET"]: {"budget_weight": r["BUDGET_WEIGHT"]} for r in bm},
        "budget": [{"programme": r["PROGRAMME_LABEL"], "tradedesk_code": r["TRADEDESK_CODE"],
                    "gross_usd": r["GROSS_BUDGET_USD"], "net_usd": r["NET_BUDGET_USD"],
                    "start": iso(r["START_DATE"]), "end": iso(r["END_DATE"])} for r in bud],
        "cs": [{"market": r["MARKET"], "total": r["TOTAL_LEADS"], "accepted": r["ACCEPTED"],
                "rejected": r["REJECTED"], "unresponsive": r["UNRESPONSIVE"],
                "do_not_contact": r["DO_NOT_CONTACT"], "last_lead_day": iso(r["LAST_LEAD_DAY"])} for r in cso],
        "cs_by_programme": [{"programme": r["PROGRAMME_LABEL"], "market": r["MARKET"], "total": r["TOTAL_LEADS"],
                "accepted": r["ACCEPTED"], "unresponsive": r["UNRESPONSIVE"],
                "do_not_contact": r["DO_NOT_CONTACT"], "last_lead_day": iso(r["LAST_LEAD_DAY"])} for r in csp],
    }

    storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT).upload_from_string(
        json.dumps(env), content_type="application/json")
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {len(env['rows'])} rows, "
          f"{sum(c['total'] for c in env['cs'])} leads")


if __name__ == "__main__":
    main()
