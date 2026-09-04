r"""windsor-connections-probe - per-ACCOUNT health of every Windsor connector we ingest.

Why this exists
---------------
A lapsed Windsor grant does not fail anything. The loader stays green while at least one
account still resolves (its abort guard only fires at 100% skipped), the raw table keeps a
fresh last_modified from the surviving accounts, the export job rebuilds on schedule, and the
dashboards on the dead accounts silently serve last week's numbers with today's date on them.
The first person to notice has been the client, three times (Meta 2026-08-11, TTD 2026-08-21,
LinkedIn 30-of-34 since 2026-07-21).

What it does, every hour
------------------------
For each datasource x account in config.json:
  1. PROBE the connector directly (a 3-day request for that one account), exactly the way the
     loader would ask. Windsor's answer classifies the grant:
       200                       -> granted; row count tells us whether the platform reports delivery
       400 "not available"       -> NOT GRANTED (and the body names what the connector DOES hold,
                                    which is how the 484->569 seat change would have shown itself)
       500 "'start'" (LinkedIn)  -> ERROR, Windsor-side bug on that account
       anything else / timeout   -> ERROR
  2. READ BigQuery for the newest day that account has landed in its raw table (per account /
     advertiser / property). This is the half the connector cannot tell us: a grant that is fine
     while the loader is not landing the rows (TTD 2026-08-19: seat re-granted under a new id,
     loader pinned to the old one, nightly job exiting 0).
  3. CLASSIFY:
       ok           granted, and the raw table is current
       frozen       granted AND Windsor still returns rows for the window, but BigQuery is behind
                    -> a LOADER fault, ours to fix. Alerts.
       quiet        granted, Windsor returns NO rows for the window, BigQuery is behind
                    -> the platform reports no delivery: paused/finished campaign or an upstream
                    problem. Shown, NOT emailed (paused campaigns are normal).
       not_granted  Windsor no longer holds the account. Alerts.
       error        the connector answered with an error twice in a row. Alerts.
       idle         expected to be quiet (ended flight, retired account, standby path). Never alerts.
  4. WRITE windsor_connections.json to the status bucket (the Grid's Connections tab reads it),
     carrying per-account "since" (state first seen) forward from the previous run.
  5. EMAIL ian@ + charles@ via the Gmail API on a STATE CHANGE for any account with alerts:true
     (one email per run listing every change), a morning digest while anything is still red,
     and an estimated-expiry warning 14 days before a connector's typical token lifetime runs
     out. Never one email per probe.

Windsor exposes NO token expiry. The "expiry_estimate" is last_reauth + the platform's typical
token lifetime, both maintained by hand in config.json, and the UI labels it an estimate.

Runs as a Cloud Run job (deploy_job_connections.ps1), hourly via Cloud Scheduler. Locally:
    $env:CLOUDSDK_ACTIVE_CONFIG_NAME='personal'
    .\.venv\Scripts\python.exe ingest\windsor_data_pull\connections\probe.py --local out.json --no-email
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import time

import requests
from google.cloud import bigquery, secretmanager, storage

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.environ.get("PROJECT", "bidbrain-analytics")
LOCATION = "australia-southeast1"
BUCKET = os.environ.get("CONNECTIONS_BUCKET", "bidbrain-analytics-status-dash")
OBJECT = os.environ.get("CONNECTIONS_OBJECT", "windsor_connections.json")
WINDSOR_SECRET = os.environ.get("WINDSOR_SECRET", "windsor-api-key")
GMAIL_SECRET = os.environ.get("GMAIL_TOKEN_SECRET", "windsor-alerts-gmail-oauth")
GRID_URL = os.environ.get("GRID_URL", "https://dashboards.bidbrain.ai/d/central/#view=connections")
TIMEOUT = int(os.environ.get("PROBE_TIMEOUT_SEC", "150"))
WORKERS = int(os.environ.get("PROBE_WORKERS", "6"))

_CONFIGURED_RE = re.compile(r"configured accounts? (?:is|are):\s*([A-Za-z0-9_\-,\s]+)", re.I)
_UNPUBLISHED_RE = re.compile(r"not provide report data|must be yesterday or earlier", re.I)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_secret(name: str) -> str | None:
    try:
        sm = secretmanager.SecretManagerServiceClient()
        return sm.access_secret_version(
            request={"name": f"projects/{PROJECT}/secrets/{name}/versions/latest"}
        ).payload.data.decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        log(f"secret {name} unavailable: {type(e).__name__}: {str(e)[:120]}")
        return None


# ----------------------------------------------------------------------------- probe
def probe_account(api_key: str, ds: dict, acct_id: str, window: int) -> dict:
    """One request for one account, shaped like the loader's own. Returns a dict describing
    Windsor's answer - never raises."""
    end = today_utc() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=window - 1)
    if ds["ds"] == "tradedesk":          # TTD refuses days it has not finalised
        end = today_utc() - dt.timedelta(days=2)
        start = end - dt.timedelta(days=window - 1)
    params = {
        "api_key": api_key,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "fields": ds["fields"],
    }
    if acct_id != "hubspot":
        params["select_accounts"] = f"{ds.get('prefix', '')}{acct_id}"
    t0 = time.time()
    out = {"http": None, "ms": None, "rows": None, "by_key": {}, "verdict": "error", "note": "", "configured": None}
    try:
        r = requests.get(ds["endpoint"], params=params, timeout=TIMEOUT)
        out["http"] = r.status_code
        out["ms"] = int((time.time() - t0) * 1000)
        body = r.text or ""
        low = body.lower()
        if r.status_code == 200:
            try:
                data = r.json().get("data", [])
            except ValueError:
                data = []
            out["rows"] = len(data)
            key = ds.get("key_col") or ""
            probe_key = {"advertiser_id": "advertiser_id", "account_id": "account_id", "property_id": "account_id"}.get(key)
            if probe_key:
                for row in data:
                    k = str(row.get(probe_key) or "")
                    if k:
                        out["by_key"][k] = out["by_key"].get(k, 0) + 1
            out["verdict"] = "granted"
        elif r.status_code == 400 and "not available" in low:
            out["verdict"] = "not_granted"
            m = _CONFIGURED_RE.search(body)
            out["configured"] = sorted({s.strip() for s in m.group(1).split(",") if s.strip()}) if m else []
            out["note"] = body[:300]
        elif r.status_code == 400 and _UNPUBLISHED_RE.search(body):
            out["verdict"] = "granted"           # the day is simply not finalised yet - the grant is fine
            out["rows"] = None
            out["note"] = "Windsor: report day not published yet"
        elif r.status_code == 500 and "'start'" in body:
            out["verdict"] = "error"
            out["note"] = "Windsor 500 on 'start' - a Windsor-side bug on this account (a campaign with no start date)"
        else:
            out["verdict"] = "error"
            out["note"] = f"HTTP {r.status_code}: {body[:240]}"
    except requests.Timeout:
        out["ms"] = int((time.time() - t0) * 1000)
        out["note"] = f"timed out after {TIMEOUT}s"
    except Exception as e:  # noqa: BLE001
        out["ms"] = int((time.time() - t0) * 1000)
        out["note"] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


def fetch_held(api_key: str) -> dict | None:
    """Windsor's OWN list of what each connector currently holds:
    GET onboard.windsor.ai/api/common/ds-accounts?datasource=all -> [{account_id: 'facebook__123',
    account_name: 'facebook__Name', datasource: 'facebook'}, ...]. It carries NO status and NO
    expiry (verified 2026-09-04: the only keys are account_id / account_name / datasource), but it
    is authoritative for "granted right now", it names the accounts, and diffing it run-to-run is
    how a re-grant or a lapse is OBSERVED without anyone editing config.json. Returns
    {ds: {bare_id: name}} or None if the call failed (callers fall back to the 400-text parse)."""
    try:
        r = requests.get("https://onboard.windsor.ai/api/common/ds-accounts",
                         params={"datasource": "all", "api_key": api_key}, timeout=90)
        if r.status_code != 200:
            log(f"ds-accounts HTTP {r.status_code}: {r.text[:120]}")
            return None
        out: dict[str, dict[str, str]] = {}
        for o in r.json():
            ds = o.get("datasource") or ""
            aid = str(o.get("account_id") or "")
            nm = str(o.get("account_name") or "")
            pre = ds + "__"
            if aid.startswith(pre):
                aid = aid[len(pre):]
            if nm.startswith(pre):
                nm = nm[len(pre):]
            out.setdefault(ds, {})[aid] = nm
        return out
    except Exception as e:  # noqa: BLE001
        log(f"ds-accounts failed: {type(e).__name__}: {str(e)[:120]}")
        return None


def observe_grant(ds: dict, held_now: dict | None, prev_ds: dict | None, changes_for_ds: list) -> dict:
    """Carry the OBSERVED re-auth / lapse dates forward and advance them when the evidence says so:
    a re-grant is when the connector holds ids it did not hold last run, or an account flips
    not_granted -> granted; a lapse is when it stops holding ids it held. These dates need no human
    - Calvin re-grants, the next hourly probe sees it, the countdown resets itself."""
    prev_g = (prev_ds or {}).get("grant") or {}
    obs = dict(prev_g.get("observed") or {})
    today = today_utc().isoformat()
    prev_held = prev_g.get("held_ids")
    now_ids = sorted(held_now.keys()) if held_now is not None else None
    if now_ids is not None and prev_held is not None:
        gained = sorted(set(now_ids) - set(prev_held))
        lost = sorted(set(prev_held) - set(now_ids))
        if gained:
            obs["reauth"] = today
            obs["reauth_evidence"] = f"connector gained {len(gained)} account(s): {', '.join(gained[:6])}"
        if lost:
            obs["lapse"] = today
            obs["lapse_evidence"] = f"connector lost {len(lost)} account(s): {', '.join(lost[:6])}"
    for c in changes_for_ds:
        if c["old"] == "not_granted" and c["new"] != "not_granted":
            obs["reauth"] = today
            obs["reauth_evidence"] = f"{c['account']} went from not granted to granted"
        if c["new"] == "not_granted" and c["old"] != "not_granted" and c.get("expected", "daily") == "daily":
            obs["lapse"] = today
            obs["lapse_evidence"] = f"{c['account']} lost its grant"
    return {"observed": obs, "held_ids": now_ids}


# ----------------------------------------------------------------------------- bigquery
def newest_days(bq: bigquery.Client, ds: dict) -> dict:
    """{key: newest metric_date iso} for the datasource's raw table. Snapshot tables
    (hubspot) return {'hubspot': newest _pulled_at day}. Never raises."""
    # NATIVE DTS datasources are shaped differently: Google runs them, there is no Windsor
    # connector to probe, and each account gets its OWN table rather than a shared one keyed
    # by account_id. So freshness is the only signal, and it is one query per account.
    #
    # Each family also needs its own date expression, and NEVER __TABLES__.last_modified:
    # a DTS run that loads nothing still TOUCHES the table, so last_modified advances
    # straight through an outage and reports green. That is exactly how the MCC Google Ads
    # failure stayed invisible (md/AGENTS.md).
    #   Google Ads  segments_date    the reported ad date, on the row
    #   GA4         _PARTITIONTIME   p_ga4_* carries no date column at all (16 columns, none
    #                                a date), so the ingestion partition is the only per-row
    #                                time that exists
    if ds.get("source") == "dts":
        out: dict = {}
        for a in ds.get("accounts", []):
            tbl = ds["table_template"].format(id=a["id"])
            sql = f"SELECT MAX({ds['date_expr']}) AS d FROM `{PROJECT}.{tbl}`"
            try:
                for r in bq.query(sql, location=LOCATION).result():
                    if r["d"] is not None:
                        d = r["d"]
                        out[a["id"]] = (d.date() if hasattr(d, "date") else d).isoformat()
            except Exception as e:  # noqa: BLE001
                # A missing table is a REAL finding, not a probe failure: eight GA4 properties
                # have failing transfers and no table at all. Recorded per account so one
                # absent table cannot hide the other accounts' freshness.
                log(f"DTS newest-day failed for {tbl}: {type(e).__name__}: {str(e)[:120]}")
                out[f"_error:{a['id']}"] = str(e)[:200]
        return out

    table = f"`{PROJECT}.{ds['table']}`"
    try:
        if ds.get("key_col"):
            sql = f"SELECT CAST({ds['key_col']} AS STRING) AS k, MAX(metric_date) AS d FROM {table} WHERE {ds['key_col']} IS NOT NULL GROUP BY k"
            rows = bq.query(sql, location=LOCATION).result()
            return {r["k"]: r["d"].isoformat() for r in rows if r["d"]}
        col = ds.get("snapshot_col", "_pulled_at")
        sql = f"SELECT MAX(DATE({col})) AS d FROM {table}"
        for r in bq.query(sql, location=LOCATION).result():
            return {"hubspot": r["d"].isoformat()} if r["d"] else {}
    except Exception as e:  # noqa: BLE001
        log(f"BQ newest-day query failed for {ds['table']}: {type(e).__name__}: {str(e)[:160]}")
        return {"_error": str(e)[:200]}
    return {}


# ----------------------------------------------------------------------------- classify
def classify(acct: dict, probe: dict, newest: str | None, frozen_after: int, prev_state: str | None,
             kind: str = "windsor") -> tuple[str, str]:
    """-> (state, fix). The verdict + the plain-English next step the tab prints.

    kind="dts" means a native BigQuery Data Transfer: nobody probed a connector, so the only
    evidence is freshness and every "re-grant in Windsor" instruction would be wrong. The fix
    text has to point at the transfer instead.
    """
    expected = acct.get("expected", "daily")
    today = today_utc()
    behind = None
    if newest:
        behind = (today - dt.date.fromisoformat(newest)).days - 1     # data through yesterday = 0 behind
        behind = max(behind, 0)
    v = probe["verdict"]

    # ---- native DTS: freshness is the whole story -----------------------------
    if kind == "dts":
        if newest is None:
            # No table at all. Eight GA4 properties are in exactly this state - their
            # transfers fail on "User does not have permission to access the Google Analytics
            # property", so nothing was ever created. A freshness check alone would stay
            # silent forever on these, which is why absence is stated as a finding.
            if expected in ("ended", "retired", "standby"):
                return "idle", f"No transfer data, and that is expected - {acct.get('why') or expected}."
            return "not_granted", ("This transfer has never landed a table. Check its run log in "
                                   "BigQuery Data Transfers - a permission error on the upstream "
                                   "property looks exactly like this. The transfer state alone is "
                                   "not enough: a DTS run can report SUCCEEDED while loading nothing.")
        if expected in ("ended", "retired"):
            return "idle", f"Quiet by design - {acct.get('why') or expected}."
        if behind is not None and behind <= frozen_after:
            return "ok", ""
        if expected == "standby":
            return "idle", f"Behind, but nothing reads it - {acct.get('why') or 'standby path'}."
        return "frozen", (f"The transfer has stopped advancing (last data {newest}). Read its RUN LOG, "
                          "not just its state - a DTS run reports SUCCEEDED while loading nothing, and "
                          "the real cause sits in the per-run log. A lost upstream permission is the "
                          "usual reason.")

    if v == "not_granted":
        if expected in ("ended", "retired"):
            return "idle", f"Not granted in Windsor, and that is expected - {acct.get('why') or expected + ' account'}."
        if expected == "standby":
            # a dead standby path is worth SEEING, not worth a red tile: nobody reads it
            return "idle", f"Not granted in Windsor. Standby path, so nothing is affected today - {acct.get('why') or 'no dashboard reads this account from Windsor'}. Re-grant only if it is about to be needed."
        held = probe.get("configured") or []
        fix = "Re-grant this connector in Windsor as the account owner (Re-grant link on the card)."
        if held:
            fix += f" Windsor currently holds: {', '.join(held[:8])}{'...' if len(held) > 8 else ''}."
            fix += " If the re-grant comes back under a NEW id, update the loader's account list - do not assume the old id."
        fix += " Then run the loader once to backfill the gap."
        return "not_granted", fix

    if v == "error":
        # one transient error is not news; two consecutive probes are
        if prev_state == "error" or "'start'" in (probe.get("note") or ""):
            return "error", f"Windsor answered with an error: {probe.get('note') or 'unknown'}. If it repeats, raise it with Windsor support - the grant itself may be fine."
        return ("ok" if (behind is not None and behind <= frozen_after) else "quiet"), f"Windsor answered with an error on this probe ({(probe.get('note') or '')[:90]}); watching for a repeat before calling it."

    # granted
    if expected == "snapshot":
        if behind is None or behind > frozen_after:
            return "frozen", "The connector answers but the snapshot has not been re-pulled. Check the loader job's executions."
        return "ok", ""
    if expected in ("ended", "retired"):
        return "idle", f"Granted; quiet by design - {acct.get('why') or expected}."
    if expected == "standby":
        if behind is not None and behind <= frozen_after:
            return "ok", ""
        return "idle", f"Granted; standby path - {acct.get('why') or 'no dashboard reads this account from Windsor'}."

    # daily
    if behind is not None and behind <= frozen_after:
        return "ok", ""
    rows = probe.get("rows")
    if rows is None:
        # unpublished day / unknown: judge on BQ alone
        return ("frozen", "BigQuery is behind and Windsor could not confirm delivery for the window. Check the loader job's executions first.")
    if rows > 0:
        return "frozen", (f"Windsor still returns {rows} row(s) for the last few days, so the grant is fine - the loader is not landing them. "
                          "Check the loader job's executions and whether its account list still matches what Windsor holds.")
    return "quiet", ("Windsor reports no rows for the last few days and BigQuery is behind. A paused or finished campaign looks exactly like this - "
                     "confirm on the platform before chasing a grant. If it should be live, the problem is upstream of Windsor.")


def effective_reauth(grant: dict) -> tuple[str | None, str]:
    """(date, source): the later of the hand-recorded last_reauth and the OBSERVED one."""
    cfg = grant.get("last_reauth")
    obs = (grant.get("observed") or {}).get("reauth")
    if obs and (not cfg or obs > cfg):
        return obs, "observed"
    return cfg, "config"


def expiry_estimate(grant: dict) -> str | None:
    lr, _ = effective_reauth(grant)
    life = grant.get("token_lifetime_days")
    if not lr or not life:
        return None
    return (dt.date.fromisoformat(lr) + dt.timedelta(days=int(life))).isoformat()


# ----------------------------------------------------------------------------- main
def build(cfg: dict, api_key: str, bq: bigquery.Client | None, prev: dict | None) -> dict:
    window = int(cfg.get("probe_window_days", 3))
    frozen_after = int(cfg.get("frozen_after_days", 3))
    prev_acc = {}
    prev_ds_map = {}
    for d in (prev or {}).get("datasources", []):
        prev_ds_map[d["ds"]] = d
        for a in d.get("accounts", []):
            prev_acc[f"{d['ds']}:{a['id']}"] = a
    today = today_utc().isoformat()
    held_all = fetch_held(api_key)            # Windsor's own held-accounts list (names included)
    if held_all is not None:
        log("ds-accounts: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(held_all.items())))

    # 1. every (ds, id) to probe - configured accounts + TTD's single seat + LinkedIn extras
    jobs: list[tuple[dict, str, dict | None]] = []
    for ds in cfg["datasources"]:
        # Native DTS has no Windsor connector to ask. Skipped here; judged on freshness alone.
        if ds.get("source") == "dts":
            continue
        if ds["ds"] == "tradedesk":
            jobs.append((ds, ds["seat"], None))
            continue
        for a in ds["accounts"]:
            jobs.append((ds, a["id"], a))
        for x in ds.get("extra_configured_ids", []):
            jobs.append((ds, x, {"id": x, "name": "Transmission account (unmapped)", "client": None,
                                 "label": "Unmapped (Transmission)", "expected": "standby", "alerts": False, "_extra": True}))

    log(f"probing {len(jobs)} account(s) across {len(cfg['datasources'])} datasource(s), {WORKERS} workers")
    results: dict[tuple[str, str], dict] = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(probe_account, api_key, ds, aid, window): (ds["ds"], aid) for ds, aid, _ in jobs}
        for f in cf.as_completed(futs):
            results[futs[f]] = f.result()

    # 2. newest day per key from BigQuery
    newest: dict[str, dict] = {}
    for ds in cfg["datasources"]:
        newest[ds["ds"]] = newest_days(bq, ds) if bq else {}

    # 3. assemble
    out_ds = []
    counts = {"ok": 0, "frozen": 0, "quiet": 0, "not_granted": 0, "error": 0, "idle": 0}
    changes = []       # for the email: (ds_label, acct, old, new)
    for ds in cfg["datasources"]:
        nd = newest.get(ds["ds"], {})
        accts_out = []
        connector = {"state": "ok", "latency_ms": None, "note": "", "configured_in_windsor": None}
        latencies = []

        if ds.get("source") == "dts":
            # Nothing was probed, so there is no connector verdict to report. A synthetic
            # "granted" is honest here: the transfer is Google's to run, and the only question
            # we can answer is whether data arrived. rows=None keeps classify() out of the
            # Windsor row-count branches entirely.
            connector = {"state": "n/a", "latency_ms": None, "configured_in_windsor": None,
                         "note": "Native BigQuery Data Transfer - no Windsor connector to probe. "
                                 "Judged on table freshness alone."}
            synthetic = {"http": None, "ms": None, "rows": None, "by_key": {},
                         "verdict": "granted", "note": "", "configured": None}
            for a in ds["accounts"]:
                accts_out.append(_account_row(ds, a, synthetic, nd, frozen_after, prev_acc, today, changes, counts))
        elif ds["ds"] == "tradedesk":
            seat = results[(ds["ds"], ds["seat"])]
            latencies.append(seat["ms"])
            if seat["verdict"] == "not_granted":
                connector = {"state": "denied", "latency_ms": seat["ms"], "configured_in_windsor": seat.get("configured"),
                             "note": f"Seat {ds['seat']} is not granted. " + (f"Windsor holds: {', '.join(seat['configured'])}." if seat.get("configured") else "")}
            elif seat["verdict"] == "error":
                connector = {"state": "error", "latency_ms": seat["ms"], "note": seat["note"], "configured_in_windsor": None}
            else:
                connector["latency_ms"] = seat["ms"]
            for a in ds["accounts"]:
                per = dict(seat)
                per["rows"] = seat["by_key"].get(a["id"], 0) if seat["verdict"] == "granted" and seat["rows"] is not None else seat["rows"]
                accts_out.append(_account_row(ds, a, per, nd, frozen_after, prev_acc, today, changes, counts))
        else:
            for a in ds["accounts"] + [{"id": x, "name": "Transmission account (unmapped)", "client": None, "label": "Unmapped (Transmission)",
                                        "expected": "standby", "alerts": False, "_extra": True} for x in ds.get("extra_configured_ids", [])]:
                pr = results[(ds["ds"], a["id"])]
                if pr["ms"] is not None:
                    latencies.append(pr["ms"])
                if pr.get("configured") is not None and connector["configured_in_windsor"] is None:
                    connector["configured_in_windsor"] = pr["configured"]
                accts_out.append(_account_row(ds, a, pr, nd, frozen_after, prev_acc, today, changes, counts))
            granted = [x for x in accts_out if x["state"] not in ("not_granted",)]
            if ds["accounts"] and not any(r["verdict"] == "granted" for (k, r) in results.items() if k[0] == ds["ds"]):
                connector["state"] = "denied" if any(r["verdict"] == "not_granted" for (k, r) in results.items() if k[0] == ds["ds"]) else "error"
                connector["note"] = "No configured account resolves on this connector - the whole grant has lapsed." if connector["state"] == "denied" else "Every probe on this connector errored."
            connector["latency_ms"] = int(sum(latencies) / len(latencies)) if latencies else None

        # Windsor's own held list is authoritative when we have it; the 400-text parse is the fallback
        held_now = (held_all or {}).get(ds["ds"]) if held_all is not None else None
        if held_now is not None:
            connector["configured_in_windsor"] = sorted(held_now.keys())
            connector["held_source"] = "ds-accounts"
        else:
            connector["held_source"] = "400-text" if connector.get("configured_in_windsor") else None

        # accounts Windsor holds that the loader does not list -> surface them (the 484->569 lesson)
        held = connector.get("configured_in_windsor") or []
        known = {a["id"] for a in accts_out}
        for extra in held:
            if extra not in known and not (ds["ds"] == "hubspot"):
                prev_u = prev_acc.get(f"{ds['ds']}:{extra}")
                since_u = prev_u.get("since") if (prev_u and prev_u.get("state") == "idle" and prev_u.get("since")) else today
                accts_out.append({
                    "id": extra, "name": (held_now or {}).get(extra) or "granted in Windsor, not in the loader", "client": None, "client_label": "Unconfigured",
                    "consumers": [], "state": "idle", "alerts": False, "expected": "unconfigured", "extra": False,
                    "probe": {}, "data": {"table": ds["table"], "newest_day": nd.get(extra), "days_behind": None, "sibling_newest_day": None},
                    "since": since_u, "since_days": (today_utc() - dt.date.fromisoformat(since_u)).days,
                    "fix": f"Windsor holds account {extra} on this connector but {ds['loader_file']} does not list it. "
                           "If it is a re-grant that came back under a new id, this is the row to act on."
                })
                counts["idle"] += 1

        grant = dict(ds.get("grant") or {})
        ds_changes = [c for c in changes if c["ds"] == ds["label"]]
        grant.update(observe_grant(ds, held_now, prev_ds_map.get(ds["ds"]), ds_changes))
        grant["effective_reauth"], grant["effective_reauth_source"] = effective_reauth(grant)
        grant["expiry_estimate"] = expiry_estimate(grant)
        out_ds.append({
            # DTS has one table per account, so the datasource-level value is the template.
            "ds": ds["ds"], "label": ds["label"],
            "table": ds.get("table") or ds.get("table_template"), "loader_job": ds.get("loader_job"),
            "schedule": ds.get("schedule"), "loader_file": ds.get("loader_file"),
            "source": ds.get("source", "windsor"),
            # A Windsor re-auth link is meaningless for a DTS feed - the fix is in the BigQuery
            # transfer, and offering the wrong button is how someone re-authorises the wrong thing.
            "reauth_url": (None if ds.get("source") == "dts"
                           else f"https://onboard.windsor.ai?datasource={ds['ds']}"),
            "grant": grant, "connector": connector,
            "bq_error": nd.get("_error"),
            "accounts": accts_out,
        })

    worst = next((s for s in ("not_granted", "error", "frozen", "quiet", "ok") if counts[s]), "ok")
    doc = {
        "generated_at": now_iso(),
        "probe_version": 1,
        "summary": dict(counts, total=sum(counts.values()), worst=worst),
        "datasources": out_ds,
        "alerts": dict((prev or {}).get("alerts") or {}, recipients=cfg["recipients"]),
        "notes": [
            "States are decided here, by the probe, once an hour. The tab renders them; the alert emails quote them. Both always agree.",
            "'Frozen' means Windsor still has rows we are not landing (our loader). 'Quiet' means Windsor itself reports no delivery - check the platform, not the grant.",
            "Expiry is an ESTIMATE: last re-authorisation date + the platform's typical token lifetime, both kept by hand in config.json. Windsor publishes no expiry.",
        ],
        "_changes": changes,      # consumed by the mailer, stripped before upload
    }
    return doc


def _account_row(ds, a, pr, nd, frozen_after, prev_acc, today, changes, counts):
    is_dts = ds.get("source") == "dts"
    if is_dts:
        newest = nd.get(a["id"])
    else:
        newest = nd.get(a["id"]) if ds.get("key_col") else nd.get("hubspot")
    prev = prev_acc.get(f"{ds['ds']}:{a['id']}")
    prev_state = prev.get("state") if prev else None
    state, fix = classify(a, pr, newest, frozen_after, prev_state, "dts" if is_dts else "windsor")
    behind = None
    if newest:
        behind = max((today_utc() - dt.date.fromisoformat(newest)).days - 1, 0)
    sib = [v for k, v in nd.items() if k != a["id"] and not k.startswith("_")]
    since = prev.get("since") if (prev and prev_state == state and prev.get("since")) else today
    since_days = (today_utc() - dt.date.fromisoformat(since)).days
    row = {
        "id": a["id"], "name": a.get("name"), "client": a.get("client"), "client_label": a.get("label") or a.get("client"),
        "consumers": a.get("consumers", []), "expected": a.get("expected", "daily"), "alerts": bool(a.get("alerts")),
        "state": state, "since": since, "since_days": since_days, "fix": fix, "why": a.get("why"),
        "extra": bool(a.get("_extra")),
        "probe": {"http": pr.get("http"), "ms": pr.get("ms"), "rows": pr.get("rows"), "verdict": pr.get("verdict"), "note": (pr.get("note") or "")[:300]},
        "data": {"table": (ds["table_template"].format(id=a["id"]) if is_dts else ds["table"]),
                 "newest_day": newest, "days_behind": behind, "sibling_newest_day": max(sib) if sib else None},
    }
    counts[state] = counts.get(state, 0) + 1
    if prev_state and prev_state != state:
        changes.append({"ds": ds["label"], "account": a.get("name") or a["id"], "id": a["id"], "client": row["client_label"],
                        "old": prev_state, "new": state, "alerts": row["alerts"], "fix": fix, "newest_day": newest,
                        "expected": a.get("expected", "daily")})
    return row


# ----------------------------------------------------------------------------- alerts
def decide_alerts(cfg: dict, doc: dict, prev: dict | None) -> list[dict]:
    """Which emails this run sends. Returns a list of {kind, subject, html, text}."""
    from mailer import render_change_email, render_digest_email, render_expiry_email  # local module

    out = []
    al = doc["alerts"]
    red = [(d, a) for d in doc["datasources"] for a in d["accounts"] if a["alerts"] and a["state"] in ("not_granted", "frozen", "error")]
    changes = [c for c in doc["_changes"] if c["alerts"] and (c["new"] in ("not_granted", "frozen", "error") or c["old"] in ("not_granted", "frozen", "error"))]

    # FLAP DAMPING. A change email fires on every transition, which is right for a real
    # ok -> not_granted and wrong for an account that cannot make up its mind. The realistic
    # oscillator here is frozen <-> quiet: those two differ only by whether Windsor returned
    # rows for the 3-day window, and a connector whose row count flickers between 0 and >0
    # flips state every hour. Measured undamped: 24 flips in a day produced 25 emails.
    #
    # After flap_limit transitions in one UTC day an account stops earning change emails for
    # the rest of that day. It is NOT hidden: it still shows on the Grid tab and still appears
    # in the daily digest, so a flapping feed is reported once rather than hourly.
    flap_limit = int(cfg.get("flap_limit_per_day", 4))
    flaps = dict(al.get("flaps") or {})
    today_iso = today_utc().isoformat()
    kept = []
    for c in changes:
        fk = f"{c['ds']}:{c['id']}"
        rec = flaps.get(fk) or {}
        n = (int(rec.get("n", 0)) + 1) if rec.get("day") == today_iso else 1
        flaps[fk] = {"day": today_iso, "n": n}
        if n <= flap_limit:
            kept.append(c)
        elif n == flap_limit + 1:
            log(f"  FLAPPING: {c['ds']} / {c['account']} has changed state {n} times today - "
                f"further change emails suppressed until tomorrow (still on the tab + digest)")
    # Only today's counters are kept, so this cannot grow without bound in the payload.
    al["flaps"] = {k: v for k, v in flaps.items() if v.get("day") == today_iso}

    if kept:
        out.append(dict(kind="change", **render_change_email(kept, red, doc, GRID_URL)))

    # digest: first run at/after digest_hour_utc while anything is still red, once per UTC day
    now = dt.datetime.now(dt.timezone.utc)
    if red and now.hour >= int(cfg.get("digest_hour_utc", 22)) and al.get("last_digest_day") != now.date().isoformat():
        out.append(dict(kind="digest", **render_digest_email(red, doc, GRID_URL)))
        al["last_digest_day"] = now.date().isoformat()

    # expiry warnings (estimate): ESCALATING - once per milestone per (datasource, last_reauth).
    #
    # This was one email at expiry_warn_days and then silence, including on the expiry day
    # itself. The brief is 2 weeks, then 1 week, then daily - because a single warning two
    # weeks out is one deferred email away from the exact silent expiry this job exists to
    # prevent. Milestones are matched as "days <= m", so a probe that misses a day (a failed
    # run, a paused scheduler) still fires the next one down rather than skipping it.
    #
    # Past expiry it keeps firing daily: the estimate can be days out either way, and going
    # quiet at the moment the token is most likely already dead is the worst possible timing.
    warn_days = int(cfg.get("expiry_warn_days", 14))
    # ASCENDING matters. With `days <= m` over a descending list, T-7 matches 14 first - which
    # is already marked from the T-14 email - and every milestone after the first goes silent.
    # Ascending picks the SMALLEST milestone at or above days, so each fires on its own day.
    milestones = sorted({int(x) for x in (cfg.get("expiry_milestones") or [warn_days, 7, 3, 2, 1])})
    warned = dict(al.get("expiry_warned") or {})
    for d in doc["datasources"]:
        g = d.get("grant") or {}
        est = g.get("expiry_estimate")
        if not est:
            continue
        days = (dt.date.fromisoformat(est) - today_utc()).days
        key = f"{d['ds']}@{g.get('last_reauth')}"
        # Per key we remember two separate things, because they de-duplicate differently:
        #   milestones  the countdown marks already sent (each fires at most ONCE)
        #   expired_on  the last day an at-or-past-expiry mail went out (fires once a DAY)
        # Keeping the expired case as a single date rather than an accumulating mark matters:
        # a connector left expired for months would otherwise grow one entry per day forever.
        prev_marks = warned.get(key)
        if isinstance(prev_marks, dict):
            seen = {int(m) for m in (prev_marks.get("milestones") or [])}
            expired_on = prev_marks.get("expired_on")
        elif isinstance(prev_marks, list):
            seen, expired_on = {int(m) for m in prev_marks}, None
        else:
            # Pre-escalation state file: the value was a single ISO date string meaning
            # "the one warn_days mail has been sent". Treat that mark as already spent.
            seen, expired_on = ({warn_days} if prev_marks else set()), None

        today_iso = today_utc().isoformat()
        if days <= 0:
            fire = expired_on != today_iso
            if fire:
                expired_on = today_iso
        else:
            due = next((m for m in milestones if days <= m), None)
            fire = due is not None and due not in seen
            if fire:
                seen.add(due)

        if fire:
            out.append(dict(kind="expiry", **render_expiry_email(d, days, GRID_URL)))
        warned[key] = {"milestones": sorted(seen), "expired_on": expired_on}
    al["expiry_warned"] = warned
    return out


def write_payload(args, gcs, doc, quiet: bool = False) -> None:
    """Publish the doc (which doubles as the alert ledger - see main())."""
    payload = json.dumps(doc, indent=1)
    if args.local:
        with open(args.local, "w", encoding="utf-8") as f:
            f.write(payload)
        if not quiet:
            log(f"wrote {args.local} ({len(payload) // 1024} KB)")
    else:
        gcs.bucket(BUCKET).blob(OBJECT).upload_from_string(payload, content_type="application/json")
        if not quiet:
            log(f"wrote gs://{BUCKET}/{OBJECT} ({len(payload) // 1024} KB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="write the JSON here instead of the bucket (and read the previous run from here)")
    ap.add_argument("--no-email", action="store_true", help="decide alerts but do not send (logged + recorded as not sent)")
    ap.add_argument("--no-bq", action="store_true", help="skip the BigQuery newest-day read (connector-only verdicts)")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    # --to exists so a real test send never requires editing config.json. Editing the
    # recipient list to test delivery is how a one-person test list ends up deployed: the
    # edit is invisible in review and the team silently stops being told anything.
    ap.add_argument("--to", default="", metavar="ADDR[,ADDR]",
                    help="override recipients for THIS RUN only (local delivery test); "
                         "config.json is left untouched")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    if args.to:
        cfg["recipients"] = [a.strip() for a in args.to.split(",") if a.strip()]
        # Loud on purpose. A run that quietly mails one person instead of the team looks
        # identical in the logs to a healthy run, so say which it was.
        log(f"RECIPIENT OVERRIDE (--to): this run mails {', '.join(cfg['recipients'])} "
            f"ONLY. config.json is unchanged.")

    api_key = os.environ.get("WINDSOR_API_KEY") or get_secret(WINDSOR_SECRET)
    if not api_key:
        log("FATAL: no Windsor API key (env WINDSOR_API_KEY or Secret Manager windsor-api-key)")
        return 2

    # previous run -> 'since' carry-forward + change detection + alert bookkeeping
    prev = None
    gcs = None
    if args.local:
        if os.path.exists(args.local):
            with open(args.local, encoding="utf-8") as f:
                prev = json.load(f)
    else:
        gcs = storage.Client(project=PROJECT)
        blob = gcs.bucket(BUCKET).blob(OBJECT)
        if blob.exists():
            prev = json.loads(blob.download_as_text())

    bq = None if args.no_bq else bigquery.Client(project=PROJECT, location=LOCATION)
    doc = build(cfg, api_key, bq, prev)
    s = doc["summary"]
    log(f"summary: ok={s['ok']} frozen={s['frozen']} quiet={s['quiet']} not_granted={s['not_granted']} error={s['error']} idle={s['idle']} worst={s['worst']}")
    for c in doc["_changes"]:
        log(f"  CHANGE {c['ds']} / {c['client']} / {c['account']}: {c['old']} -> {c['new']}{'' if c['alerts'] else ' (no alert - account not on a critical path)'}")

    # ---- decide -------------------------------------------------------------
    emails = decide_alerts(cfg, doc, prev)
    al = doc["alerts"]
    hist = list(al.get("history") or [])
    token = None if args.no_email else get_secret(GMAIL_SECRET)
    al["enabled"] = bool(token)

    # ---- PERSIST BEFORE SENDING --------------------------------------------
    # This published JSON *is* the state file: the alert ledger (last_digest_day,
    # expiry_warned, flap counters) rides inside it, and `prev` is simply the last run's copy.
    #
    # So the write is what makes de-duplication real, and it MUST happen before the send.
    # Sending first was a storm waiting to happen: decide_alerts() marks the ledger, then if
    # the upload failed the marks died with the process, and the next hourly run re-decided
    # from scratch and re-sent. Measured at 26 emails a day, every day, for as long as the
    # write kept failing - and a bucket permission or quota problem does keep failing.
    #
    # Ordering it this way makes the failure loud instead: the exception propagates, the Cloud
    # Run execution goes RED, and NOTHING is emailed. Losing one alert while the job is
    # visibly broken is a far better trade than mailing the team hourly forever.
    hist_placeholder = list(hist)
    al["history"] = hist_placeholder[-50:]
    al["last_run_at"] = doc["generated_at"]
    doc["alerts"] = al
    doc.pop("_changes", None)
    write_payload(args, gcs, doc)

    # ---- send ---------------------------------------------------------------
    # A send failure is recorded in `history` (sent:false + the error) and surfaces on the
    # Grid tab. It is deliberately NOT retried: the ledger is already committed, and anything
    # still wrong is picked up by tomorrow's digest.
    if emails:
        from mailer import send_gmail
        for e in emails:
            sent, err = (False, "email disabled (--no-email)") if args.no_email else send_gmail(token, cfg["recipients"], e["subject"], e["html"], e["text"]) if token else (False, f"no Gmail token in Secret Manager ({GMAIL_SECRET})")
            hist.append({"sent_at": now_iso(), "kind": e["kind"], "subject": e["subject"], "to": cfg["recipients"], "sent": sent, "error": err})
            log(f"  EMAIL [{e['kind']}] {'SENT' if sent else 'NOT SENT - ' + str(err)}: {e['subject']}")
        # Re-publish so the tab shows what actually went out. Best-effort: the ledger is
        # already safely written above, so a failure here costs a history line, not a storm.
        al["history"] = hist[-50:]
        doc["alerts"] = al
        try:
            write_payload(args, gcs, doc, quiet=True)
        except Exception as e:  # noqa: BLE001
            log(f"  (send history not republished: {type(e).__name__}: {str(e)[:120]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
