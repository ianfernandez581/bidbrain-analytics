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
  --client <client>   full sync fetch for ONE validated client only (case-insensitive) —
                      every other client is skipped and its BQ is never queried. A name
                      that matches no validated client is reported on stderr (the server
                      pre-validates, so this is belt-and-braces).
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
# CENTRAL_CLIENTS_PATH lets the server point the fetcher at the same config file it writes
# (and lets a validation dry-run use a temp copy). Defaults to the committed config.
CONFIG = Path(os.environ.get("CENTRAL_CLIENTS_PATH") or (Path(__file__).resolve().parents[1] / "config" / "central-clients.json"))


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


# which Central channel a raw table represents (for tagging fetched rows/names)
TABLE_CHANNEL = {
    "tradedesk_apac_all": "Trade Desk", "perf_the_trade_desk": "Trade Desk",
    "linkedin_ads_apac": "LinkedIn", "google_ads_apac": "Google Ads", "perf_google_ads": "Google Ads",
    "perf_meta": "Meta", "reddit_ads_apac_all": "Reddit", "perf_reddit": "Reddit", "dv360_apac": "DV360",
}


def _channel_of(t):
    return t.get("channel") or TABLE_CHANNEL.get(t.get("table")) or t.get("table")


def _source(spec):
    return spec.get("source") or ("view" if spec.get("bq") else "none")


def _q(v):
    """single-quote-escape a SQL string literal (no double quotes — shell quoting)."""
    return str(v).replace("'", "''")


def fetch_client_rows(spec):
    """Totals per BQ campaign name — impressions + media spend. Two modes:
      view : a pm_delivery view (Schneider) — group by `program` (imps/spend_aud).
      raw  : one or more raw platform tables — group by the configured campaign column,
             filtered to the advertiser; MULTIPLE tables merge by campaign name (a
             campaign that spans platforms sums; distinct names stay separate)."""
    src = _source(spec)
    if src == "none":
        return []
    if src == "view":
        ref = _table_ref(spec)
        sql = ("SELECT program AS bqName, CAST(SUM(imps) AS INT64) AS impressions, "
               "ROUND(SUM(spend_aud), 2) AS mediaSpend, CAST(MAX(metric_date) AS STRING) AS last_date "
               f"FROM {ref} GROUP BY 1")
        return [{"bqName": r.get("bqName"), "impressions": int(_num(r.get("impressions")) or 0),
                 "mediaSpend": _num(r.get("mediaSpend")), "lastDate": r.get("last_date") or None}
                for r in _bq_csv(sql)]
    if src == "raw":
        # per-campaign rows, TAGGED with advertiserName + channel (NOT merged) so the sync
        # path can apply the per-row match rule (exact/contains/rollup) — see src/central/match.js.
        rows = []
        for t in spec.get("tables", []):
            adv, advVal, camp = t["advertiserColumn"], t["advertiserValue"], t["campaignColumn"]
            imp, cost, date = t.get("impressionColumn"), t.get("costColumn"), t.get("dateColumn")
            channel = _channel_of(t)
            sel_imp = f"CAST(SUM(SAFE_CAST({imp} AS FLOAT64)) AS INT64)" if imp else "0"
            sel_cost = f"ROUND(SUM(SAFE_CAST({cost} AS FLOAT64)), 2)" if cost else "0"
            where = f"WHERE {adv} = '{_q(advVal)}'"
            fs, fe = t.get("flightStart"), t.get("flightEnd")
            if date and fs and fe:
                where += f" AND {date} BETWEEN '{_q(fs)}' AND '{_q(fe)}'"
            sql = (f"SELECT CAST({camp} AS STRING) AS bqName, {sel_imp} AS impressions, {sel_cost} AS mediaSpend "
                   f"FROM `{PROJECT}.{t['dataset']}.{t['table']}` {where} GROUP BY 1")
            for r in _bq_csv(sql):
                nm = r.get("bqName")
                if not nm:
                    continue
                # dataset/table are additive tags (readiness bqSource); the sync path + match.js
                # read only bqName/advertiserName/channel/impressions/mediaSpend and ignore them.
                rows.append({"bqName": nm, "advertiserName": advVal, "channel": channel,
                             "dataset": t["dataset"], "table": t["table"],
                             "impressions": int(_num(r.get("impressions")) or 0), "mediaSpend": _num(r.get("mediaSpend"))})
        return rows
    raise RuntimeError(f"unknown source '{src}'")


def fetch_names(spec):
    """Distinct BQ campaign names for reconcile, TAGGED with channel + advertiserName so
    the panel/approve can write the per-row match schema. Returns [{bqName, channel, advertiserName}]."""
    src = _source(spec)
    if src == "none":
        return []
    if src == "view":
        ref = _table_ref(spec)
        return [{"bqName": r.get("bqName"), "channel": None, "advertiserName": None}
                for r in _bq_csv(f"SELECT DISTINCT program AS bqName FROM {ref} WHERE program IS NOT NULL ORDER BY 1") if r.get("bqName")]
    out, seen = [], set()
    for t in spec.get("tables", []):
        adv, advVal, camp = t["advertiserColumn"], t["advertiserValue"], t["campaignColumn"]
        channel = _channel_of(t)
        sql = (f"SELECT DISTINCT CAST({camp} AS STRING) AS bqName FROM `{PROJECT}.{t['dataset']}.{t['table']}` "
               f"WHERE {adv} = '{_q(advVal)}' AND {camp} IS NOT NULL")
        for r in _bq_csv(sql):
            nm = r.get("bqName")
            if not nm:
                continue
            key = (channel, advVal, nm)
            if key in seen:
                continue
            seen.add(key)
            out.append({"bqName": nm, "channel": channel, "advertiserName": advVal})
    return out


def run_full_sync(only=None):
    """only: canonical/CI-insensitive client name — scope the fetch to that ONE validated
    client (Phase 4 ?client= fix: other clients' BQ is never even queried)."""
    cfg = _load_config()
    clients, skipped = {}, []
    validated_total = validated_ok = 0
    only_lc = only.lower() if only else None
    matched_only = False
    for spec in cfg.get("clients", []):
        name = spec.get("client")
        if only_lc and str(name).lower() != only_lc:
            skipped.append({"client": name, "reason": "not requested (client filter)"})
            continue
        if only_lc:
            matched_only = True
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
    if only_lc and not matched_only:
        print(f"--client '{only}' matches no client in central-clients.json", file=sys.stderr)
    elif only_lc and validated_total == 0:
        print(f"--client '{only}' matches a client but it is not validated — nothing fetched", file=sys.stderr)
    doc = {"fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "clients": clients, "skipped": skipped}
    print(json.dumps(doc))
    # exit non-zero ONLY if there was work to do and all of it failed
    return 1 if (validated_total > 0 and validated_ok == 0) else 0


def run_readiness():
    """Readiness preview: per-client tagged rows for EVERY client with a BQ source
    (source != 'none'), validated OR not — unlike run_full_sync which fetches only
    validated clients. READ-ONLY. The grid-core readiness builder (src/central/
    readiness.js) turns this into the live-coverage table. Per-client failures are
    captured, never crash the run (exit 0)."""
    cfg = _load_config()
    clients = {}
    for spec in cfg.get("clients", []):
        name = spec.get("client")
        if _source(spec) == "none":
            continue
        entry = {"rows": [], "errors": [], "source": _source(spec), "validated": bool(spec.get("validated"))}
        try:
            entry["rows"] = fetch_client_rows(spec)
        except Exception as e:  # noqa: BLE001 — capture, never crash the whole run
            entry["errors"].append(str(e)[:600])
        clients[name] = entry
    doc = {"fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "clients": clients}
    print(json.dumps(doc))
    return 0


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
    if len(sys.argv) >= 2 and sys.argv[1] == "--readiness":
        sys.exit(run_readiness())
    if len(sys.argv) >= 3 and sys.argv[1] == "--client":
        sys.exit(run_full_sync(only=sys.argv[2]))
    sys.exit(run_full_sync())


if __name__ == "__main__":
    main()
