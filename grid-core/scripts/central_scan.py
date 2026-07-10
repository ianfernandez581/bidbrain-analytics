#!/usr/bin/env python
"""
central_scan.py — FULL-PROJECT READ-ONLY BigQuery discovery for Central coverage.

Superset of bq_audit.py (which only scanned raw_snowflake + raw_windsor). This enumerates
EVERY dataset in the project, and within each finds tables/views with the shape of delivery
data (advertiser/account col + campaign col + impressions|cost + date), then lists the distinct
advertiser names present. Goal: no live client's spend sits in an un-scanned dataset (Section 6
flagged raw_google_ads / DTS holding The Little Marionette's Google Ads spend).

Efficiency: one INFORMATION_SCHEMA.COLUMNS query per dataset (fast) to discover columns for all
its tables at once, then the (slower) advertiser GROUP BY only on real delivery tables. Per-call
subprocess timeout; progress to stderr; nothing hangs the whole run.

Auth: bq CLI as ian@100.digital (Section 6 phase 1), local run. READ-ONLY — no writes.
Run:  python grid-core/scripts/central_scan.py > scan.json 2> scan.err
"""
import csv
import io
import json
import os
import subprocess
import sys

PROJECT = os.environ.get("CENTRAL_BQ_PROJECT", "bidbrain-analytics")
ACCOUNT = os.environ.get("CENTRAL_BQ_ACCOUNT", "ian@100.digital")

ADV_PRI = ["advertiser_name", "advertiser", "account_name", "account", "client", "brand", "advertisername", "client_slug"]
CAMP_PRI = ["campaign_name", "campaign", "campaignname", "campaign_id"]
IMP_PRI = ["impressions", "impression", "imps", "impression_count"]
COST_PRI = ["advertiser_cost_adv_currency", "media_cost_advertiser_currency", "costs", "cost", "spend",
            "spend_aud", "spend_usd", "media_cost", "cost_usd", "cost_aud", "total_cost"]
DATE_PRI = ["metric_date", "date", "day", "report_date"]


def _run(cmd, timeout=150):
    env = dict(os.environ, CLOUDSDK_CORE_ACCOUNT=ACCOUNT)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, env=env, shell=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timed out after {timeout}s")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:400])
    return out.stdout


def _bq_csv(sql, timeout=150):
    one = " ".join(sql.split())
    assert '"' not in one, "no double quotes in SQL (shell quoting)"
    return list(csv.DictReader(io.StringIO(_run(
        f'bq --project_id={PROJECT} --format=csv query --use_legacy_sql=false --max_rows=100000 "{one}"', timeout))))


def _progress(m):
    print(m, file=sys.stderr, flush=True)


def list_datasets():
    out = _run(f'bq ls -d --format=prettyjson --max_results=10000 {PROJECT}:')
    return sorted(d["datasetReference"]["datasetId"] for d in json.loads(out))


def columns_by_table(ds):
    """One INFORMATION_SCHEMA query → {table_name: [column_name,...]} for the whole dataset."""
    rows = _bq_csv(f"SELECT table_name, column_name FROM `{PROJECT}.{ds}.INFORMATION_SCHEMA.COLUMNS` ORDER BY table_name, ordinal_position")
    out = {}
    for r in rows:
        out.setdefault(r["table_name"], []).append(r["column_name"])
    return out


def pick(cols, pri):
    low = {c.lower(): c for c in cols}
    for p in pri:
        if p in low:
            return low[p]
    for p in pri:
        for c in cols:
            if p in c.lower():
                return c
    return None


def advertisers(ds, table, adv, camp, imp):
    sel_imp = f"SUM(SAFE_CAST({imp} AS FLOAT64))" if imp else "0"
    sel_camp = f"COUNT(DISTINCT {camp})" if camp else "0"
    sql = (f"SELECT CAST({adv} AS STRING) AS advertiser, {sel_camp} AS campaigns, {sel_imp} AS impressions "
           f"FROM `{PROJECT}.{ds}.{table}` GROUP BY 1 ORDER BY impressions DESC")
    out = []
    for r in _bq_csv(sql):
        out.append({"name": r.get("advertiser"),
                    "campaigns": int(float(r.get("campaigns") or 0)),
                    "impressions": int(float(r.get("impressions") or 0))})
    return out


def main():
    report = {"project": PROJECT, "datasets": [], "tables": {}, "errors": []}
    try:
        datasets = list_datasets()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"list datasets failed: {e}"}))
        return 1
    report["datasets"] = datasets
    _progress(f"{len(datasets)} datasets: {', '.join(datasets)}")
    for ds in datasets:
        _progress(f"scan {ds} ...")
        try:
            cbt = columns_by_table(ds)
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"{ds}: columns query failed: {str(e)[:200]}")
            continue
        for table, cols in cbt.items():
            adv, camp = pick(cols, ADV_PRI), pick(cols, CAMP_PRI)
            imp, cost, date = pick(cols, IMP_PRI), pick(cols, COST_PRI), pick(cols, DATE_PRI)
            key = f"{ds}.{table}"
            info = {"advCol": adv, "campCol": camp, "impCol": imp, "costCol": cost, "dateCol": date,
                    "delivery": bool(adv and camp and (imp or cost)), "advertisers": [], "error": None}
            if info["delivery"]:
                _progress(f"  advertisers {key} (adv={adv}) ...")
                try:
                    info["advertisers"] = advertisers(ds, table, adv, camp, imp)
                except Exception as e:  # noqa: BLE001
                    info["error"] = str(e)[:300]
            report["tables"][key] = info
    _progress("done.")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
