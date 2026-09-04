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
def classify(acct: dict, probe: dict, newest: str | None, frozen_after: int, prev_state: str | None) -> tuple[str, str]:
    """-> (state, fix). The verdict + the plain-English next step the tab prints."""
    expected = acct.get("expected", "daily")
    today = today_utc()
    behind = None
    if newest:
        behind = (today - dt.date.fromisoformat(newest)).days - 1     # data through yesterday = 0 behind
        behind = max(behind, 0)
    v = probe["verdict"]

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

        if ds["ds"] == "tradedesk":
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
            "ds": ds["ds"], "label": ds["label"], "table": ds["table"], "loader_job": ds.get("loader_job"),
            "schedule": ds.get("schedule"), "loader_file": ds.get("loader_file"),
            "reauth_url": f"https://onboard.windsor.ai?datasource={ds['ds']}",
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
    newest = nd.get(a["id"]) if ds.get("key_col") else nd.get("hubspot")
    prev = prev_acc.get(f"{ds['ds']}:{a['id']}")
    prev_state = prev.get("state") if prev else None
    state, fix = classify(a, pr, newest, frozen_after, prev_state)
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
        "data": {"table": ds["table"], "newest_day": newest, "days_behind": behind, "sibling_newest_day": max(sib) if sib else None},
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

    if changes:
        out.append(dict(kind="change", **render_change_email(changes, red, doc, GRID_URL)))

    # digest: first run at/after digest_hour_utc while anything is still red, once per UTC day
    now = dt.datetime.now(dt.timezone.utc)
    if red and now.hour >= int(cfg.get("digest_hour_utc", 22)) and al.get("last_digest_day") != now.date().isoformat():
        out.append(dict(kind="digest", **render_digest_email(red, doc, GRID_URL)))
        al["last_digest_day"] = now.date().isoformat()

    # expiry warnings (estimate): once per (datasource, last_reauth)
    warn_days = int(cfg.get("expiry_warn_days", 14))
    warned = dict(al.get("expiry_warned") or {})
    for d in doc["datasources"]:
        g = d.get("grant") or {}
        est = g.get("expiry_estimate")
        if not est:
            continue
        days = (dt.date.fromisoformat(est) - today_utc()).days
        key = f"{d['ds']}@{g.get('last_reauth')}"
        if days <= warn_days and warned.get(key) is None:
            out.append(dict(kind="expiry", **render_expiry_email(d, days, GRID_URL)))
            warned[key] = now.date().isoformat()
    al["expiry_warned"] = warned
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="write the JSON here instead of the bucket (and read the previous run from here)")
    ap.add_argument("--no-email", action="store_true", help="decide alerts but do not send (logged + recorded as not sent)")
    ap.add_argument("--no-bq", action="store_true", help="skip the BigQuery newest-day read (connector-only verdicts)")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

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

    # alerts
    emails = decide_alerts(cfg, doc, prev)
    al = doc["alerts"]
    hist = list(al.get("history") or [])
    token = None if args.no_email else get_secret(GMAIL_SECRET)
    al["enabled"] = bool(token)
    if emails:
        from mailer import send_gmail
        for e in emails:
            sent, err = (False, "email disabled (--no-email)") if args.no_email else send_gmail(token, cfg["recipients"], e["subject"], e["html"], e["text"]) if token else (False, f"no Gmail token in Secret Manager ({GMAIL_SECRET})")
            hist.append({"sent_at": now_iso(), "kind": e["kind"], "subject": e["subject"], "to": cfg["recipients"], "sent": sent, "error": err})
            log(f"  EMAIL [{e['kind']}] {'SENT' if sent else 'NOT SENT - ' + str(err)}: {e['subject']}")
    al["history"] = hist[-50:]
    al["last_run_at"] = doc["generated_at"]
    doc["alerts"] = al
    doc.pop("_changes", None)

    payload = json.dumps(doc, indent=1)
    if args.local:
        with open(args.local, "w", encoding="utf-8") as f:
            f.write(payload)
        log(f"wrote {args.local} ({len(payload) // 1024} KB)")
    else:
        gcs.bucket(BUCKET).blob(OBJECT).upload_from_string(payload, content_type="application/json")
        log(f"wrote gs://{BUCKET}/{OBJECT} ({len(payload) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
