#!/usr/bin/env python
"""
central_sync.py — Central's BQ metrics fetcher (grid-core ADAPTER).

This is an adapter, NOT an edit of scripts/live_metrics.py. It reuses that script's
PROVEN query approach (the `client_schneider.pm_delivery` pattern; the `bq` CLI
authenticated locally as ian@100.digital — metadata quoting + CSV parse copied
verbatim) but is driven entirely by grid-core/config/central-clients.json so Central
never couples to the shared script.

Modes:
  (default)           full sync fetch — one JSON doc for all validated clients.
  --names <client>    reconcile mode — distinct BQ campaign names for ONE client
                      (validated or not), for the human-in-the-loop mapping panel.

Full-sync output (stdout):
  { "fetchedAt": "...", "clients": { "<client>": { "rows": [ {bqName, impressions,
    mediaSpend} ], "errors": [] } }, "skipped": [ {client, reason} ] }
Per-client failures are captured in errors, never crash the run: exit 0 with partial
data; exit non-zero ONLY if there was ≥1 validated client and EVERY one errored.
"""
import csv
import datetime
import io
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = os.environ.get("CENTRAL_BQ_PROJECT", "bidbrain-analytics")
ACCOUNT = os.environ.get("CENTRAL_BQ_ACCOUNT", "ian@100.digital")
CONFIG = Path(__file__).resolve().parents[1] / "config" / "central-clients.json"


def _bq_csv(sql):
    """Run a query via the bq CLI, return list[dict] (CSV parsed). shell=True because
    on Windows `bq` is a .cmd wrapper; the SQL is collapsed to one line and must not
    contain double quotes (shell quoting). Copied from live_metrics._bq_csv."""
    env = dict(os.environ, CLOUDSDK_CORE_ACCOUNT=ACCOUNT)
    one_line = " ".join(sql.split())
    assert '"' not in one_line, "SQL must not contain double quotes (shell quoting)"
    cmd = (f'bq --project_id={PROJECT} --format=csv query '
           f'--use_legacy_sql=false --max_rows=100000 "{one_line}"')
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, shell=True)
    if out.returncode != 0:
        raise RuntimeError(f"bq query failed: {out.stderr.strip()[:600]}")
    return list(csv.DictReader(io.StringIO(out.stdout)))


def _load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _table_ref(spec):
    bq = spec.get("bq") or {}
    ds, tbl = bq.get("dataset"), bq.get("table")
    if not ds or not tbl:
        raise RuntimeError("client has no bq.dataset/table configured")
    return f"`{PROJECT}.{ds}.{tbl}`"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch_client_rows(spec):
    """Totals per BQ campaign name (pm_delivery `program`) — impressions + media spend
    (spend_aud, the raw media cost pm_delivery exposes; it does not split partner vs
    client, so mediaSpend carries the partner/media figure). All-time per program; a
    map entry may carry flightStart/flightEnd to scope it, else all-time."""
    ref = _table_ref(spec)
    sql = (f"SELECT program AS bqName, CAST(SUM(imps) AS INT64) AS impressions, "
           f"ROUND(SUM(spend_aud), 2) AS mediaSpend, CAST(MAX(metric_date) AS STRING) AS last_date "
           f"FROM {ref} GROUP BY 1")
    rows = []
    for r in _bq_csv(sql):
        rows.append({
            "bqName": r.get("bqName"),
            "impressions": int(_num(r.get("impressions")) or 0),
            "mediaSpend": _num(r.get("mediaSpend")),
            "lastDate": r.get("last_date") or None,
        })
    return rows


def fetch_names(spec):
    ref = _table_ref(spec)
    sql = f"SELECT DISTINCT program AS bqName FROM {ref} WHERE program IS NOT NULL ORDER BY 1"
    return [r.get("bqName") for r in _bq_csv(sql) if r.get("bqName")]


def run_full_sync():
    cfg = _load_config()
    clients, skipped = {}, []
    validated_total = validated_ok = 0
    for spec in cfg.get("clients", []):
        name = spec.get("client")
        if not spec.get("validated"):
            skipped.append({"client": name, "reason": "not validated"})
            continue
        validated_total += 1
        entry = {"rows": [], "errors": []}
        try:
            entry["rows"] = fetch_client_rows(spec)
            validated_ok += 1
        except Exception as e:  # noqa: BLE001 — capture, never crash the whole run
            entry["errors"].append(str(e)[:600])
        clients[name] = entry
    doc = {"fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "clients": clients, "skipped": skipped}
    print(json.dumps(doc))
    # exit non-zero ONLY if there was work to do and all of it failed
    return 1 if (validated_total > 0 and validated_ok == 0) else 0


def run_names(client):
    cfg = _load_config()
    spec = next((c for c in cfg.get("clients", []) if c.get("client") == client), None)
    out = {"client": client, "bqNames": [], "error": None}
    if not spec:
        out["error"] = f"client '{client}' is not in central-clients.json"
    else:
        try:
            out["bqNames"] = fetch_names(spec)
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:600]
    print(json.dumps(out))
    return 0


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--names":
        sys.exit(run_names(sys.argv[2]))
    sys.exit(run_full_sync())


if __name__ == "__main__":
    main()
