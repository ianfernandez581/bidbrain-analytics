"""
Windsor -> BigQuery loader for GEOCON SALESFORCE LEADS.

Lives in:  windsor_data_pull/salesforce/salesforce_loader.py
Runtime artifacts (log, temp NDJSON) -> _run/ next to this script (anchored to __file__,
gitignored), so nothing scatters into the repo root.

Writes the EXISTING raw_windsor.geocon_salesforce_leads table (created by
create_salesforce_table.py -- run that once first). This loader does not create or alter the
table; it reads the live schema at runtime so staging/MERGE can't drift from it.

HOW THIS DIFFERS FROM THE AD LOADERS (reddit/meta/linkedin) -- read before copying either way
---------------------------------------------------------------------------------------------
 1. RECORDS, NOT DAILY METRICS. An ad loader's grain is (account x ad x date) and its measures
    are additive. A lead is a RECORD: the grain is the lead id alone, and there is nothing to
    sum. So there is no account loop, no per-account date bounds, and no measure columns.
 2. THE ROWS MUTATE. A lead's Status moves (Assigned -> Engaged -> Qualified/Lost) long after
    it was created, so the incremental run re-pulls a WIDE trailing window (90 days) and MERGEs
    on lead_id, restating status in place. Ad spend settles in days; a sales funnel does not.
 3. ONE CONNECTION, NO select_accounts. Windsor holds a single Salesforce grant
    (salesforce__calvin@100.digital = Geocon's org), so there is no account dimension to pin and
    no prefix to apply. If a second org is ever granted this MUST gain an account filter, or two
    clients' leads silently merge into one table -- the shared-mirror trap in AGENTS.md.
 4. NO PII. Seven columns, every one of them a count-able dimension. See
    create_salesforce_table.py for why, and do not widen it.

DATE SEMANTICS (verified against the live API, 2026-09-17)
----------------------------------------------------------
date_from / date_to filter on the lead's CREATED date, not its last-modified date: a 32-day
request returned rows whose min/max created dates were exactly the requested bounds, and 32
single-day requests summed to precisely the same total as one 32-day request (198), so the
window is honoured exactly and nothing is capped or paginated away.

created_at comes back UTC (+0000). created_date is derived in AUSTRALIA/SYDNEY, because the
enquiry happened in Canberra and a UTC date files a 9am local enquiry under the previous day for
ten hours out of every twenty-four. Every consumer reads created_date so they cannot disagree.

WHAT THIS LOADER CANNOT SEE
---------------------------
Across three years and 7,918 leads, ZERO are returned with IsConverted, IsDeleted or
MasterRecordId set. For a live CRM that is implausible, so Windsor is almost certainly excluding
converted, deleted and merged leads. The effect is a level shift, not a trend break -- the same
exclusion applied in 2024 -- but it means a count here is "open leads Windsor can see", not
"every lead Salesforce holds". Reconcile against a Salesforce report before quoting it as the
latter.

MODES
-----
1. INCREMENTAL (no date args) -- normal / scheduled.
     re-pulls the trailing INCREMENTAL_LOOKBACK_DAYS (90) so status changes restate, and
     forward-loads anything newer. On an EMPTY table it falls back to MIN_DATE (full backfill).
2. FIXED RANGE (two date args) -- backfill / reconciliation:
     python salesforce_loader.py 2024-01-01 2026-09-17

Exit codes: 0 on success (including a legitimately empty window), 1 on a hard failure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from google.cloud import bigquery, secretmanager

# ---------- Config ----------
PROJECT_ID = "bidbrain-analytics"
DATASET = "raw_windsor"
MAIN_TABLE = "geocon_salesforce_leads"
STAGING_TABLE = "geocon_salesforce_leads_staging"
LOCATION = "australia-southeast1"

# Dedicated connector (NOT the blended /all endpoint -- Salesforce is not on it).
WINDSOR_URL = "https://connectors.windsor.ai/salesforce"
WINDSOR_SECRET = "windsor-api-key"

CLIENT_SLUG = "geocon"
AGENCY_SLUG = "100-digital"
SOURCE = "windsor_salesforce"

LOCAL_TZ = ZoneInfo("Australia/Sydney")

# The seven columns we ingest. Deliberately narrow -- see the module docstring.
FIELDS = (
    "lead_id,"
    "lead_created_date,"
    "lead_project_of_interest__c,"
    "lead_project_of_interest_text__c,"
    "lead_development_name__c,"
    "lead_lead_source,"
    "lead_status"
)

# A lead's STATUS mutates for months after creation, so the routine run restates a wide trailing
# window rather than the 7 days an ad loader needs for conversion settling.
INCREMENTAL_LOOKBACK_DAYS = int(os.environ.get("SF_LOOKBACK_DAYS", "90"))
# Record volume is tiny (~7.9k rows over 3 years), so the whole history fits one request
# comfortably. Chunking exists only to bound a pathological backfill.
CHUNK_DAYS = int(os.environ.get("SF_CHUNK_DAYS", "365"))
MIN_DATE = dt.date(2023, 1, 1)
TIMEOUT_SEC = int(os.environ.get("SF_TIMEOUT_SEC", "300"))
MAX_ATTEMPTS = int(os.environ.get("SF_MAX_ATTEMPTS", "6"))
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = WORK_DIR / "salesforce_loader.log"


# ---------- Logging ----------
class FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[FlushingStreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("salesforce_loader")


# ---------- Helpers ----------
def get_secret(name: str) -> str:
    env = os.environ.get("WINDSOR_API_KEY")
    if env:
        return env.strip()
    sm = secretmanager.SecretManagerServiceClient()
    path = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return sm.access_secret_version(request={"name": path}).payload.data.decode().strip()


def clean(v):
    """Windsor sends an empty string for an empty text field. Store NULL, never '' -- otherwise a
    COUNT or a GROUP BY silently gains an empty-string bucket that looks like a real category."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_created(v):
    """Turn Windsor's created timestamp into (utc iso, LOCAL date iso). Returns (None, None) on
    anything unparseable so one malformed row cannot abort a whole chunk."""
    s = clean(v)
    if not s:
        return None, None
    txt = s.replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            d = dt.datetime.strptime(txt, fmt)
            return (d.astimezone(dt.timezone.utc).isoformat(),
                    d.astimezone(LOCAL_TZ).date().isoformat())
        except ValueError:
            continue
    try:  # bare date, no clock
        d = dt.date.fromisoformat(txt[:10])
        return None, d.isoformat()
    except ValueError:
        log.warning("unparseable created date %r - row kept with NULL date", s)
        return None, None


def fetch(api_key: str, d_from: dt.date, d_to: dt.date) -> list:
    """One Windsor request. Retries on 5xx/network; fails fast on 4xx (a bad field name or a
    revoked grant will never fix itself by waiting)."""
    params = {"api_key": api_key, "date_from": d_from.isoformat(),
              "date_to": d_to.isoformat(), "fields": FIELDS}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.get(WINDSOR_URL, params=params, timeout=TIMEOUT_SEC)
            if r.status_code == 200:
                body = r.json()
                data = body.get("data", body) if isinstance(body, dict) else body
                if not isinstance(data, list):
                    raise RuntimeError("unexpected payload shape: " + str(body)[:300])
                return data
            if 400 <= r.status_code < 500:
                raise RuntimeError("HTTP %s (not retryable): %s" % (r.status_code, r.text[:400]))
            log.warning("HTTP %s attempt %s/%s: %s", r.status_code, attempt, MAX_ATTEMPTS,
                        r.text[:200])
        except requests.RequestException as e:
            log.warning("network error attempt %s/%s: %s", attempt, MAX_ATTEMPTS, str(e)[:200])
        if attempt == MAX_ATTEMPTS:
            raise RuntimeError("giving up after %s attempts on %s..%s" % (MAX_ATTEMPTS, d_from, d_to))
        time.sleep(min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX))
    return []


def transform(row: dict, ingested_at: str):
    lead_id = clean(row.get("lead_id"))
    if not lead_id:
        return None  # no key -> cannot MERGE; dropped and counted by the caller
    created_at, created_date = parse_created(row.get("lead_created_date"))
    return {
        "lead_id": lead_id,
        "created_at": created_at,
        "created_date": created_date,
        "project_id": clean(row.get("lead_project_of_interest__c")),
        "project_name": clean(row.get("lead_project_of_interest_text__c")),
        "development_name": clean(row.get("lead_development_name__c")),
        "lead_source": clean(row.get("lead_lead_source")),
        "lead_status": clean(row.get("lead_status")),
        "client_slug": CLIENT_SLUG,
        "agency_slug": AGENCY_SLUG,
        "source": SOURCE,
        "ingested_at": ingested_at,
    }


_MERGE_KEY_COLS = ["lead_id"]
_MERGE_SET_COLS = ["created_at", "created_date", "project_id", "project_name",
                   "development_name", "lead_source", "lead_status",
                   "client_slug", "agency_slug", "source", "ingested_at"]


def dedup(rows: list) -> list:
    """BigQuery's MERGE refuses a source with duplicate keys (UPDATE/MERGE must match at most one
    source row). Overlapping chunks can hand us the same lead twice, so keep the last seen."""
    seen = {}
    for r in rows:
        seen[r["lead_id"]] = r
    return list(seen.values())


def load_and_merge(bq: bigquery.Client, schema, rows: list) -> int:
    staging_id = "%s.%s.%s" % (PROJECT_ID, DATASET, STAGING_TABLE)
    main_id = "%s.%s.%s" % (PROJECT_ID, DATASET, MAIN_TABLE)

    tmp = WORK_DIR / "staging.ndjson"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    job_cfg = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with open(tmp, "rb") as f:
        bq.load_table_from_file(f, staging_id, job_config=job_cfg, location=LOCATION).result()
    log.info("staged %s rows -> %s", len(rows), STAGING_TABLE)

    on = " AND ".join("T.%s = S.%s" % (c, c) for c in _MERGE_KEY_COLS)
    setc = ", ".join("T.%s = S.%s" % (c, c) for c in _MERGE_SET_COLS)
    cols = _MERGE_KEY_COLS + _MERGE_SET_COLS
    ins_cols = ", ".join(cols)
    ins_vals = ", ".join("S.%s" % c for c in cols)
    sql = ("MERGE `%s` T USING `%s` S ON %s "
           "WHEN MATCHED THEN UPDATE SET %s "
           "WHEN NOT MATCHED THEN INSERT (%s) VALUES (%s)"
           % (main_id, staging_id, on, setc, ins_cols, ins_vals))
    job = bq.query(sql, location=LOCATION)
    job.result()
    affected = job.num_dml_affected_rows or 0
    log.info("merged: %s rows affected", affected)

    bq.delete_table(staging_id, not_found_ok=True)
    tmp.unlink(missing_ok=True)
    return affected


def max_created_date(bq: bigquery.Client):
    sql = "SELECT MAX(created_date) AS d FROM `%s.%s.%s`" % (PROJECT_ID, DATASET, MAIN_TABLE)
    for r in bq.query(sql, location=LOCATION).result():
        return r["d"]
    return None


# ---------- Main ----------
def main() -> int:
    ap = argparse.ArgumentParser(description="Windsor Salesforce -> BigQuery (Geocon leads)")
    ap.add_argument("date_from", nargs="?", help="YYYY-MM-DD (fixed-range mode)")
    ap.add_argument("date_to", nargs="?", help="YYYY-MM-DD (fixed-range mode)")
    args = ap.parse_args()

    bq = bigquery.Client(project=PROJECT_ID)
    main_id = "%s.%s.%s" % (PROJECT_ID, DATASET, MAIN_TABLE)
    try:
        schema = bq.get_table(main_id).schema
    except Exception as e:
        log.error("table %s missing - run create_salesforce_table.py first (%s)", main_id, e)
        return 1

    today_local = dt.datetime.now(LOCAL_TZ).date()
    if args.date_from and args.date_to:
        d_from = dt.date.fromisoformat(args.date_from)
        d_to = dt.date.fromisoformat(args.date_to)
        mode = "fixed-range"
    else:
        newest = max_created_date(bq)
        if newest:
            d_from = newest - dt.timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
        else:
            d_from = MIN_DATE
            log.info("table empty -> full backfill from %s", MIN_DATE)
        d_to = today_local
        mode = "incremental"
    if d_from > d_to:
        d_from = d_to
    log.info("mode=%s window=%s..%s lookback=%sd", mode, d_from, d_to, INCREMENTAL_LOOKBACK_DAYS)

    api_key = get_secret(WINDSOR_SECRET)
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()

    raw = []
    cur = d_from
    while cur <= d_to:
        chunk_to = min(cur + dt.timedelta(days=CHUNK_DAYS - 1), d_to)
        got = fetch(api_key, cur, chunk_to)
        log.info("  %s..%s -> %s rows", cur, chunk_to, len(got))
        raw.extend(got)
        cur = chunk_to + dt.timedelta(days=1)

    shaped = [t for t in (transform(r, ingested_at) for r in raw) if t]
    dropped = len(raw) - len(shaped)
    if dropped:
        log.warning("%s row(s) dropped for a missing lead_id", dropped)

    rows = dedup(shaped)
    if len(rows) != len(shaped):
        log.info("deduped %s -> %s on lead_id", len(shaped), len(rows))

    if not rows:
        # A window with no leads is legitimate (a quiet fortnight), so this is NOT a failure. The
        # caltex "refuse to publish an empty fact" rule guards a JSON the client SEES; here we are
        # simply not MERGEing anything and the existing table is left untouched.
        log.info("no rows in window - nothing to merge (table left as-is)")
        return 0

    affected = load_and_merge(bq, schema, rows)

    dates = [r["created_date"] for r in rows if r["created_date"]]
    projects = {}
    for r in rows:
        k = r["project_name"] or "(blank)"
        projects[k] = projects.get(k, 0) + 1
    top = sorted(projects.items(), key=lambda kv: -kv[1])[:6]
    log.info("window %s..%s | %s leads | affected %s", min(dates, default="-"),
             max(dates, default="-"), len(rows), affected)
    log.info("by project: %s", ", ".join("%s=%s" % (k, v) for k, v in top))

    # The scope audit: anything reaching the Geocon dashboard must resolve to a development, and
    # the only project that does is 'Gateway'. Print the rest by name so a NEW Geocon development
    # announces itself here instead of being silently absent from the dashboard.
    unmapped = sum(v for k, v in projects.items() if k != "Gateway")
    if unmapped:
        log.info("scope: %s of %s leads are NOT 'Gateway' (other developments; expected)",
                 unmapped, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
