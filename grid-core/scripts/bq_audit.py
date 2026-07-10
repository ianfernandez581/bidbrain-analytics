#!/usr/bin/env python
"""
bq_audit.py — READ-ONLY BigQuery discovery for Central coverage mapping.

Lists tables in raw_snowflake + raw_windsor (and discovers client_* datasets with a
pm_delivery view), reads each table's SCHEMA, discovers the real advertiser / campaign /
impression / cost / date column names (never guessed — matched against the actual schema),
then queries advertiser → (campaign count, impressions). Emits one JSON report to stdout.

Uses the bq CLI as ian@100.digital (same auth as live_metrics.py / central_sync.py). No
writes, no warehouse resumes beyond metadata + the grouped counts.

Run:  python grid-core/scripts/bq_audit.py > audit.json
"""
import csv
import io
import json
import os
import subprocess
import sys

PROJECT = os.environ.get("CENTRAL_BQ_PROJECT", "bidbrain-analytics")
ACCOUNT = os.environ.get("CENTRAL_BQ_ACCOUNT", "ian@100.digital")
DATASETS = ["raw_snowflake", "raw_windsor"]

# column-name discovery priorities (matched case-insensitively against the real schema)
ADV_PRI = ["advertiser_name", "advertiser", "account_name", "account", "client", "brand", "advertisername"]
CAMP_PRI = ["campaign_name", "campaign", "campaignname", "campaign_id"]
IMP_PRI = ["impressions", "impression", "imps", "impression_count", "impression"]
COST_PRI = ["advertiser_cost_adv_currency", "costs", "cost", "spend", "spend_aud", "spend_usd",
            "media_cost", "cost_usd", "cost_aud", "total_cost"]
DATE_PRI = ["metric_date", "date", "day", "report_date"]


def _run(cmd, timeout=150):
    env = dict(os.environ, CLOUDSDK_CORE_ACCOUNT=ACCOUNT)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, env=env, shell=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timed out after {timeout}s")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:500])
    return out.stdout


def _bq_csv(sql):
    one = " ".join(sql.split())
    assert '"' not in one, "no double quotes in SQL (shell quoting)"
    out = _run(f'bq --project_id={PROJECT} --format=csv query --use_legacy_sql=false --max_rows=100000 "{one}"')
    return list(csv.DictReader(io.StringIO(out)))


def list_tables(dataset):
    out = _run(f'bq ls --format=prettyjson --max_results=1000 {PROJECT}:{dataset}')
    return [t["tableReference"]["tableId"] for t in json.loads(out)]


def list_datasets():
    out = _run(f'bq ls -d --format=prettyjson --max_results=1000 {PROJECT}:')
    return [d["datasetReference"]["datasetId"] for d in json.loads(out)]


def schema_cols(dataset, table):
    out = _run(f'bq show --schema --format=prettyjson {PROJECT}:{dataset}.{table}')
    return [c["name"] for c in json.loads(out)]


def pick(cols, priorities):
    low = {c.lower(): c for c in cols}
    for p in priorities:
        if p in low:
            return low[p]
    # loose contains-match fallback
    for p in priorities:
        for c in cols:
            if p in c.lower():
                return c
    return None


def audit_table(dataset, table):
    info = {"schema": [], "advCol": None, "campCol": None, "impCol": None, "costCol": None, "dateCol": None, "advertisers": [], "error": None}
    try:
        cols = schema_cols(dataset, table)
        info["schema"] = cols
        adv = pick(cols, ADV_PRI); camp = pick(cols, CAMP_PRI)
        imp = pick(cols, IMP_PRI); cost = pick(cols, COST_PRI); date = pick(cols, DATE_PRI)
        info.update(advCol=adv, campCol=camp, impCol=imp, costCol=cost, dateCol=date)
        # only run the (slow) grouped query on real delivery tables — need an advertiser
        # AND a campaign AND some metric. Skips GA4/Salesforce/HubSpot/_sync_state etc.
        if not (adv and camp and (imp or cost)):
            info["error"] = "skipped (not a delivery table: missing advertiser/campaign/metric column)"
            return info
        sel_imp = f"SUM(CAST({imp} AS FLOAT64))" if imp else "0"
        sel_camp = f"COUNT(DISTINCT {camp})" if camp else "0"
        sql = (f"SELECT CAST({adv} AS STRING) AS advertiser, {sel_camp} AS campaigns, {sel_imp} AS impressions "
               f"FROM `{PROJECT}.{dataset}.{table}` GROUP BY 1 ORDER BY impressions DESC")
        for r in _bq_csv(sql):
            info["advertisers"].append({
                "name": r.get("advertiser"),
                "campaigns": int(float(r.get("campaigns") or 0)),
                "impressions": int(float(r.get("impressions") or 0)),
            })
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)[:400]
    return info


def _progress(msg):
    print(msg, file=sys.stderr, flush=True)


def main():
    report = {"tables": {}, "clientViews": [], "errors": []}
    for ds in DATASETS:
        try:
            _progress(f"ls {ds} ...")
            tables = list_tables(ds)
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"ls {ds}: {str(e)[:200]}")
            continue
        for t in tables:
            _progress(f"  audit {ds}.{t} ...")
            report["tables"][f"{ds}.{t}"] = audit_table(ds, t)
    # client_* datasets with a pm_delivery view — enumerating ALL datasets is slow, so only
    # probe the known client datasets directly (targeted `bq show`, fast).
    for c in ["schneider", "mongodb", "cloudflare", "stt", "hireright", "cityperfume", "resetdata", "proptrack", "tlm", "vmch"]:
        try:
            _progress(f"  probe client_{c}.pm_delivery ...")
            schema_cols(f"client_{c}", "pm_delivery")
            report["clientViews"].append(f"client_{c}.pm_delivery")
        except Exception:
            pass
    _progress("done.")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
