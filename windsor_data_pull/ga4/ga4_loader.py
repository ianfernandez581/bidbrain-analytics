"""
Windsor -> BigQuery loader for GA4 (Google Analytics 4) Traffic Acquisition data.

Lives in:  windsor_data_pull/ga4/ga4_loader.py
Runtime artifacts (chunk cache, log, temp NDJSON) -> _run/ next to this script
(anchored to __file__, gitignored), so nothing scatters into the repo root.

Grain: one row per
    (property_id x date x source x medium x campaign x default_channel_group)
stored in the columns session_source / session_medium / session_campaign_name /
session_default_channel_group. (Windsor's plain `source`/`medium`/`campaign`
fields are session-scoped per its schema -- "attributed to the session" -- so
the session_* column names stay accurate.)

MERGE key (see _MERGE_KEY_COLS -- the single source of truth for both the dedup
and the SQL ON clause):
    property_id + metric_date + session_source + session_medium +
    session_campaign_name + session_default_channel_group
all coalesced to '(not set)' so the key is never NULL. channel_group IS in the
key on purpose: Windsor can return source/medium/campaign NULL for some rows,
and without channel_group in the key those rows all collapse to one key and the
MERGE fails on the next incremental run with "matched multiple source rows".

FIELD-NAME GOTCHA (learned the hard way): Windsor's GA4 connector populates the
PLAIN `source`/`medium`/`campaign` request fields, NOT the `session_source` /
`session_medium` / `session_campaign_name` variants (those exist in the field
reference but come back NULL). The channel group, however, is requested as
`session_default_channel_group`. The blended `/all` endpoint silently nulls ALL
of these GA4-native dims -- use the dedicated `googleanalytics4` connector.

TWO-PASS FETCH (the GA4-specific bit vs meta_loader / tradedesk_loader)
----------------------------------------------------------------------
GA4's Data API caps a single request at 9 dimensions / 10 metrics. We want 12
metrics, so each chunk is fetched in TWO passes with IDENTICAL dimensions and a
6-metric subset each (FIELDS_GROUP_A / FIELDS_GROUP_B -- 5 dims + 6 metrics =
safe under both caps). The two responses are merged on the dimension key into
one row per grain BEFORE transform/MERGE. Correct whether or not Windsor batches
metric groups internally. A dim combo with traffic but zero conversions/revenue
may be absent from pass B -- those outcome metrics default to 0 in transform
(missing == 0 at this grain).

CHUNK_DAYS=3 also keeps each request small, which minimises GA4 sampling / the
"(other)" row at high cardinality.

MODES (same as meta_loader.py)
------------------------------
1. INCREMENTAL PER-PROPERTY (no date args) -- normal / scheduled. For each
   property in SELECT_ACCOUNTS it looks up MAX(metric_date) in BigQuery:
     * has data -> forward-loads from (last day - INCREMENTAL_LOOKBACK_DAYS) up
                   to yesterday. The re-pulled boundary days recapture GA4's
                   late-arriving / modeled conversions; staging + MERGE dedup.
     * no data  -> full backfill via backward walk from yesterday until
                   STOP_AFTER_EMPTY_CHUNKS consecutive empty chunks (or MIN_DATE).

       python windsor_data_pull/ga4/ga4_loader.py

2. FIXED RANGE (two date args) -- all properties together, targeted re-pull.

       python windsor_data_pull/ga4/ga4_loader.py 2026-05-25 2026-05-30

--force re-fetches even cached chunks (MERGE is idempotent on the key).

RETRIES: transient errors (timeouts, 429, 5xx) retried with capped backoff up to
MAX_ATTEMPTS, then the chunk fails loudly; permanent 4xx (bad field / auth /
slug) fails fast with the response body.
"""
import json
import logging
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from google.cloud import bigquery, secretmanager, storage

# ---------- Config ----------
PROJECT_ID = "bidbrain-analytics"
DATASET = "raw_windsor"
MAIN_TABLE = "perf_ga4"
STAGING_TABLE = "perf_ga4_staging"
GCS_BUCKET = "bidbrain-analytics-staging"

# Dedicated GA4 connector endpoint + bare property IDs (the connector is in the
# path, so no prefix is needed -- the `googleanalytics4__` prefix is only for the
# blended /all endpoint). Confirmed working.
WINDSOR_URL = "https://connectors.windsor.ai/googleanalytics4"
ACCOUNT_PREFIX = ""
SELECT_ACCOUNTS = [
    "318963196",
    "413451542",
    "413487460",
    "413490347",
    "413491455",
    "413495845",
    "434829327",
    "434839993",
    "434852571",
    "434854278",
    "434905821",
    "516276493",
    "254028250",
    "358885683",
    "506931798",
    "468621509",
    "273098216",
    "341827046",
    "341832593",
    "287370621",
]

# --- Field groups (GA4 10-metric cap => two passes, identical dims) ---
# account_id/account_name are connector-account metadata (the property we
# selected), present on every row in both passes. NOTE: request the PLAIN
# source/medium/campaign (Windsor populates these; the session_* variants come
# back NULL). Do NOT request `measurement_id` -- it's stream-scoped and
# fragments multi-stream properties.
METADATA_FIELDS = "account_id,account_name"
# 5 GA4 dimensions (session_source_medium is DERIVED in transform, not requested).
# source/medium/campaign are session-scoped in Windsor; channel group is the
# session_* variant because THAT is the one Windsor populates for the group.
DIMENSIONS = (
    "date,"
    "source,medium,campaign,"
    "session_default_channel_group"
)
# Group A: traffic / engagement base metrics (6).
METRICS_A = (
    "sessions,engaged_sessions,totalusers,newusers,"
    "screen_page_views,user_engagement_duration"
)
# Group B: outcome base metrics (6). totalrevenue is one word in Windsor.
METRICS_B = (
    "event_count,conversions,totalrevenue,"
    "purchase_revenue,ecommerce_purchases,transactions"
)
FIELDS_GROUP_A = ",".join([METADATA_FIELDS, DIMENSIONS, METRICS_A])
FIELDS_GROUP_B = ",".join([METADATA_FIELDS, DIMENSIONS, METRICS_B])

CHUNK_DAYS = 3
STOP_AFTER_EMPTY_CHUNKS = 5
MIN_DATE = date(2015, 1, 1)
TIMEOUT_SEC = 120
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60
MAX_ATTEMPTS = 30          # per-chunk retry cap; then fail loudly instead of hanging forever
INTER_CHUNK_SLEEP = 1
# GA4 conversions / modeled data settle over ~24-48h, so re-pull this many days
# before each property's last BQ day on every incremental run (staging + MERGE
# dedup). Higher than Meta's 0 on purpose.
INCREMENTAL_LOOKBACK_DAYS = 3

# All runtime artifacts live under _run/ next to THIS script (not the cwd).
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "ga4_loader.log"

# Optional: map a GA4 property ID straight to (client_slug, agency_slug). Checked
# FIRST in infer_slugs -- most reliable for GA4, since property names are often
# generic ("GA4 - example.com") and won't carry the client keyword. Fill as needed.
PROPERTY_TO_CLIENT = {
    # "318963196": ("wehi", "ad-assembly"),
}

# Fallback keyword match on property name / campaign (same dict as the other loaders).
CLIENT_TO_AGENCY = {
    "wehi": "ad-assembly",
    "altech": "100-digital",
    "vmch": "100-digital",
    "rac": "100-digital",
    "sah": "100-digital",
    "rl": "100-digital",
    "tlm": "100-digital",
    "resetdata": "100-digital",
    "cairns": "100-digital",
    "cp": "100-digital",
    "buyerx": "100-digital",
}

# ---------- Logging ----------
class FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8"),
        FlushingStreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ga4_loader")

# ---------- Helpers ----------
def get_secret(name):
    """Read the latest version of a Secret Manager secret via Application
    Default Credentials -- same ADC the BigQuery/Storage clients use. No gcloud
    CLI or machine-specific path required, so this runs identically locally
    (after `gcloud auth application-default login`) and on Cloud Run/Build."""
    log.info(f"Fetching secret '{name}' from Secret Manager...")
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    val = client.access_secret_version(name=path).payload.data.decode("utf-8").strip()
    log.info(f"  got secret (length {len(val)})")
    return val

def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"

def infer_slugs(row):
    # 1) explicit property -> client override (most reliable for GA4)
    override = PROPERTY_TO_CLIENT.get(str(row.get("account_id") or ""))
    if override:
        return override
    # 2) keyword match on property name / campaign (raw Windsor fields)
    haystack = " ".join(str(row.get(k) or "").lower() for k in
                        ("account_name", "campaign"))
    for keyword, agency in CLIENT_TO_AGENCY.items():
        if keyword in haystack:
            return keyword, agency
    return slugify(row.get("account_name") or "unknown"), "unknown"

def account_key(connector_or_id):
    """Bare numeric property id (GA4 property IDs are already digits; this just
    normalises away any prefix). Used to match SELECT_ACCOUNTS against the
    property_id values stored in BigQuery."""
    return re.sub(r"\D", "", str(connector_or_id or ""))

def latest_dates_per_account(bq):
    """MAX(metric_date) already in the main table, keyed by numeric property id.
    Properties with no rows are simply absent from the returned dict."""
    sql = f"""
        SELECT property_id, MAX(metric_date) AS max_date
        FROM `{PROJECT_ID}.{DATASET}.{MAIN_TABLE}`
        WHERE property_id IS NOT NULL
        GROUP BY property_id
    """
    out = {}
    for r in bq.query(sql).result():
        md = r["max_date"]
        if md is None:
            continue
        if isinstance(md, str):          # column may be DATE or STRING; normalise
            md = date.fromisoformat(md[:10])
        out[account_key(r["property_id"])] = md
    return out

def chunk_filename(d_from, d_to, cache_tag, group):
    return CHUNKS_DIR / f"{cache_tag}_{group}_{d_from.isoformat()}_to_{d_to.isoformat()}.json"

def fetch_chunk(api_key, d_from, d_to, idx, total, select_accounts, cache_tag, fields, group, force=False):
    """Fetch one metric-group pass for a chunk. Retries transient errors; fails
    fast on 4xx. total may be None (backward-walk mode, count unknown)."""
    label = f"chunk {idx}/{total}" if total else f"chunk {idx}"
    if cache_tag != "all":
        label = f"{cache_tag} {label}"
    label = f"{label} [grp {group}]"
    cache_file = chunk_filename(d_from, d_to, cache_tag, group)
    if cache_file.exists() and not force:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        log.info(f"  [{label}] CACHED {d_from}..{d_to}: {len(rows)} rows")
        return rows

    accounts = ",".join(f"{ACCOUNT_PREFIX}{a}" for a in select_accounts)
    params = {
        "api_key": api_key,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "fields": fields,
        "select_accounts": accounts,
    }
    log.info(f"  [{label}] Fetching {d_from}..{d_to}{' (FORCE)' if force else ''}")
    start = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        attempt_start = time.monotonic()
        try:
            r = requests.get(WINDSOR_URL, params=params, timeout=TIMEOUT_SEC)
            elapsed = time.monotonic() - attempt_start
            log.info(f"    attempt {attempt}: HTTP {r.status_code} in {elapsed:.1f}s")
            r.raise_for_status()
            payload = r.json()
            rows = payload.get("data", [])
            if "data" not in payload:
                log.warning(f"    no 'data' key (keys: {list(payload)[:5]}) -- treating as 0 rows")
            total_elapsed = time.monotonic() - start
            log.info(f"  [{label}] SUCCESS: {len(rows)} rows in {total_elapsed:.1f}s")
            cache_file.write_text(json.dumps(rows), encoding="utf-8")
            return rows
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429 or (status is not None and status >= 500):
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"Chunk {d_from}..{d_to} [grp {group}]: gave up after {attempt} attempts "
                        f"on transient HTTP {status} (Windsor still failing)."
                    )
                sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
                log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} transient HTTP {status}; retrying in {sleep}s")
                time.sleep(sleep)
                continue
            body = (e.response.text[:500] if e.response is not None else "")
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} [grp {group}] got permanent HTTP {status}. This will NOT "
                f"recover by retrying -- likely a bad field name, auth, connector slug, or account "
                f"prefix. Sent fields:\n{fields}\nBody:\n{body}"
            )
        except requests.exceptions.RequestException as e:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Chunk {d_from}..{d_to} [grp {group}]: gave up after {attempt} attempts "
                    f"({type(e).__name__}: {e})."
                )
            sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
            log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} FAILED ({type(e).__name__}); retrying in {sleep}s")
            time.sleep(sleep)

def _dim_key(row):
    """Raw-row key for merging the two metric-group passes. Matches the logical
    grain (channel group included). Final post-coalesce dedup happens later in
    dedup_by_merge_key, so None vs '' edge cases are caught there too."""
    g = row.get
    return (
        g("account_id"),
        g("date"),
        g("source"),
        g("medium"),
        g("campaign"),
        g("session_default_channel_group"),
    )

def merge_metric_groups(rows_a, rows_b):
    """Merge the two metric-group responses into one row per dimension key.
    Pass A (traffic) is effectively a superset at this grain; pass B (outcomes)
    may omit dim combos with zero conversions/revenue -- those default to 0 in
    transform. Keyed on dims so A-metrics + B-metrics land on the same row."""
    by_key = {}
    for r in rows_a:
        by_key[_dim_key(r)] = dict(r)
    for r in rows_b:
        k = _dim_key(r)
        if k in by_key:
            by_key[k].update(r)        # adds B metrics; shared dims/metadata identical
        else:
            by_key[k] = dict(r)
    return list(by_key.values())

def fetch_chunk_combined(api_key, d_from, d_to, idx, total, select_accounts, cache_tag, force=False):
    rows_a = fetch_chunk(api_key, d_from, d_to, idx, total, select_accounts, cache_tag,
                         FIELDS_GROUP_A, "a", force=force)
    rows_b = fetch_chunk(api_key, d_from, d_to, idx, total, select_accounts, cache_tag,
                         FIELDS_GROUP_B, "b", force=force)
    combined = merge_metric_groups(rows_a, rows_b)
    log.info(f"    merged groups: A={len(rows_a)} B={len(rows_b)} -> {len(combined)} rows")
    return combined

def to_int(v):
    if v in (None, "", "null"): return None
    try: return int(float(v))
    except (TypeError, ValueError): return None

def to_num(v):
    if v in (None, "", "null"): return None
    try: return float(v)
    except (TypeError, ValueError): return None

def to_date_iso(v):
    """GA4 'date' is YYYYMMDD; BQ DATE load needs YYYY-MM-DD. Accept either."""
    if not v: return None
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]

def transform(row, ingested_at_iso):
    g = row.get
    # Windsor's plain source/medium/campaign are session-scoped; coalesce so the
    # MERGE-key columns are never NULL.
    src = g("source") or "(not set)"
    med = g("medium") or "(not set)"
    camp = g("campaign") or "(not set)"
    chan = g("session_default_channel_group") or "(not set)"
    client_slug, agency_slug = infer_slugs(row)
    return {
        "platform": "ga4",
        "property_id": g("account_id"),
        "account_name": g("account_name"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "metric_date": to_date_iso(g("date")),
        "session_source": src,
        "session_medium": med,
        "session_source_medium": f"{src} / {med}",
        "session_campaign_name": camp,
        "session_default_channel_group": chan,
        # additive base metrics -- missing == 0 at this grain
        "sessions": to_int(g("sessions")) or 0,
        "engaged_sessions": to_int(g("engaged_sessions")) or 0,
        "total_users": to_int(g("totalusers")) or 0,
        "new_users": to_int(g("newusers")) or 0,
        "screen_page_views": to_int(g("screen_page_views")) or 0,
        "user_engagement_duration": to_num(g("user_engagement_duration")) or 0,
        "event_count": to_int(g("event_count")) or 0,
        "conversions": to_num(g("conversions")) or 0,
        "total_revenue": to_num(g("totalrevenue")) or 0,
        "purchase_revenue": to_num(g("purchase_revenue")) or 0,
        "ecommerce_purchases": to_int(g("ecommerce_purchases")) or 0,
        "transactions": to_int(g("transactions")) or 0,
        "ingested_at": ingested_at_iso,
        "source": "windsor.ga4",
        "raw_row": json.dumps(row),
    }

# Single source of truth for the grain. Drives BOTH the staging dedup and the
# SQL MERGE ON clause, so they can never drift apart. channel_group is in the
# key on purpose (see module docstring).
_MERGE_KEY_COLS = [
    "property_id", "metric_date", "session_source", "session_medium",
    "session_campaign_name", "session_default_channel_group",
]

# Non-key columns updated on MERGE match (everything in the row that isn't a key
# column). Names / derived fields ARE refreshed; metrics ARE overwritten.
_MERGE_SET_COLS = [
    "platform", "account_name", "client_slug", "agency_slug",
    "session_source_medium",
    "sessions", "engaged_sessions", "total_users", "new_users", "screen_page_views",
    "user_engagement_duration", "event_count", "conversions", "total_revenue",
    "purchase_revenue", "ecommerce_purchases", "transactions",
    "ingested_at", "source", "raw_row",
]

def dedup_by_merge_key(rows):
    """Guarantee exactly one row per MERGE key in the staging load. BigQuery
    MERGE errors if >1 source row matches a target row, and Windsor can emit rows
    that collapse to the same key after coalescing (e.g. NULL vs '(not set)'
    source). Last occurrence wins -- consistent with the MERGE's own UPDATE."""
    by_key = {}
    for r in rows:
        by_key[tuple(r[c] for c in _MERGE_KEY_COLS)] = r
    return list(by_key.values())

def load_chunk_to_bq(bq, storage_client, main_table_schema, rows, ingested_at, d_from, d_to):
    if not rows:
        log.info(f"  (no rows for {d_from}..{d_to}, skipping BQ load)")
        return 0, 0

    transformed = [transform(r, ingested_at) for r in rows]
    before = len(transformed)
    transformed = dedup_by_merge_key(transformed)
    if len(transformed) != before:
        log.info(f"  deduped {before} -> {len(transformed)} rows on MERGE key")

    run_id = uuid.uuid4().hex[:8]
    local_path = WORK_DIR / f"load_{run_id}.ndjson"
    with local_path.open("w", encoding="utf-8") as f:
        for row in transformed:
            f.write(json.dumps(row) + "\n")
    size_kb = local_path.stat().st_size / 1024
    log.info(f"  Wrote {len(transformed)} rows ({size_kb:.1f} KB) to {local_path.name}")

    gcs_path = f"loads/ga4/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(str(local_path))
    gcs_uri = f"gs://{GCS_BUCKET}/{gcs_path}"
    log.info(f"  Uploaded to {gcs_uri}")

    staging_ref = f"{PROJECT_ID}.{DATASET}.{STAGING_TABLE}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=main_table_schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
    )
    load_job = bq.load_table_from_uri(gcs_uri, staging_ref, job_config=job_config)
    log.info(f"  Load job {load_job.job_id} started, waiting...")
    load_job.result()
    log.info(f"  Loaded {load_job.output_rows} rows into staging")

    on_clause = "\n    AND ".join(f"T.{c} = S.{c}" for c in _MERGE_KEY_COLS)
    set_clause = ",\n        ".join(f"{c} = S.{c}" for c in _MERGE_SET_COLS)
    merge_sql = f"""
    MERGE `{PROJECT_ID}.{DATASET}.{MAIN_TABLE}` T
    USING `{staging_ref}` S
    ON  {on_clause}
    WHEN MATCHED THEN UPDATE SET
        {set_clause}
    WHEN NOT MATCHED THEN INSERT ROW
    """
    job = bq.query(merge_sql)
    job.result()
    stats = job.dml_stats
    log.info(f"  MERGE: inserted {stats.inserted_row_count}, updated {stats.updated_row_count}")

    bq.delete_table(staging_ref, not_found_ok=True)
    local_path.unlink(missing_ok=True)
    return stats.inserted_row_count, stats.updated_row_count

# ---------- Main ----------
def main():
    overall_start = time.monotonic()
    pos = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    fixed_range = len(pos) == 2

    log.info("=" * 60)
    if fixed_range:
        start_d = date.fromisoformat(pos[0])
        end_d = date.fromisoformat(pos[1])
        log.info(f"GA4 LOADER START (fixed range): {start_d} to {end_d}{'  (FORCE)' if force else ''}")
    else:
        end_d = date.today() - timedelta(days=1)
        log.info(f"GA4 LOADER START (incremental per-property): refresh each property "
                 f"from its last BQ day (lookback {INCREMENTAL_LOOKBACK_DAYS}d) up to {end_d}; "
                 f"properties with no data get a full backward-walk backfill"
                 f"{'  (FORCE)' if force else ''}")
    log.info(f"Artifacts dir: {WORK_DIR}")
    log.info(f"Properties: {len(SELECT_ACCOUNTS)} | chunk size: {CHUNK_DAYS}d | 2 metric passes/chunk")
    log.info("=" * 60)

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    api_key = get_secret("windsor-api-key")
    ingested_at = datetime.now(timezone.utc).isoformat()

    bq = bigquery.Client(project=PROJECT_ID, location="australia-southeast1")
    storage_client = storage.Client(project=PROJECT_ID)
    main_table = bq.get_table(f"{PROJECT_ID}.{DATASET}.{MAIN_TABLE}")
    schema = main_table.schema
    log.info(f"BQ ready. Main table: {main_table.full_table_id}")

    grand_inserted = grand_updated = grand_rows_fetched = 0

    def run_chunk(d_from, d_to, idx, total, select, cache_tag):
        nonlocal grand_inserted, grand_updated, grand_rows_fetched
        log.info("-" * 60)
        rows = fetch_chunk_combined(api_key, d_from, d_to, idx, total, select, cache_tag, force=force)
        grand_rows_fetched += len(rows)
        try:
            ins, upd = load_chunk_to_bq(bq, storage_client, schema, rows,
                                        ingested_at, d_from, d_to)
            grand_inserted += ins
            grand_updated += upd
        except Exception as e:
            log.error(f"  BQ LOAD FAILED for {d_from}..{d_to}: {type(e).__name__}: {e}")
            log.error("  Chunk JSON is cached; re-run to retry just the BQ side.")
        elapsed_min = (time.monotonic() - overall_start) / 60
        log.info(f"  RUNNING TOTAL: fetched={grand_rows_fetched}, "
                 f"inserted={grand_inserted}, updated={grand_updated}, elapsed={elapsed_min:.1f} min")
        return len(rows)

    def process_forward_range(d_start, d_end, select, cache_tag):
        chunks = []
        cur = d_start
        while cur <= d_end:
            ce = min(cur + timedelta(days=CHUNK_DAYS - 1), d_end)
            chunks.append((cur, ce))
            cur = ce + timedelta(days=1)
        chunks.reverse()
        total = len(chunks)
        log.info(f"  {total} chunk(s), newest first: {d_start}..{d_end}")
        for i, (d_from, d_to) in enumerate(chunks, start=1):
            run_chunk(d_from, d_to, i, total, select, cache_tag)
            time.sleep(INTER_CHUNK_SLEEP)

    def process_backward_walk(d_end, select, cache_tag):
        consecutive_empty = 0
        idx = 0
        cur_to = d_end
        while True:
            idx += 1
            cur_from = cur_to - timedelta(days=CHUNK_DAYS - 1)
            floor_hit = cur_from <= MIN_DATE
            if floor_hit:
                cur_from = MIN_DATE
            n = run_chunk(cur_from, cur_to, idx, None, select, cache_tag)

            if n == 0:
                consecutive_empty += 1
                log.info(f"  empty chunk #{consecutive_empty} of {STOP_AFTER_EMPTY_CHUNKS} before stopping")
                if consecutive_empty >= STOP_AFTER_EMPTY_CHUNKS:
                    log.info(f"  >>> {STOP_AFTER_EMPTY_CHUNKS} consecutive empty chunks. "
                             f"Assuming start of history. Stopping.")
                    break
            else:
                consecutive_empty = 0

            if floor_hit:
                log.info(f"  >>> Reached MIN_DATE floor ({MIN_DATE}). Stopping.")
                break
            cur_to = cur_from - timedelta(days=1)
            time.sleep(INTER_CHUNK_SLEEP)

    if fixed_range:
        log.info(f"Forward-loading {start_d}..{end_d} (all {len(SELECT_ACCOUNTS)} properties together)")
        process_forward_range(start_d, end_d, SELECT_ACCOUNTS, "all")
    else:
        last_dates = latest_dates_per_account(bq)
        log.info(f"Existing data in {MAIN_TABLE} for {len(last_dates)}/{len(SELECT_ACCOUNTS)} configured property(ies)")
        for account in SELECT_ACCOUNTS:
            key = account_key(account)
            last = last_dates.get(key)
            log.info("=" * 60)
            if last is None:
                log.info(f"PROPERTY {account}: no rows in BQ -> full backfill (backward walk)")
                process_backward_walk(end_d, [account], key)
            else:
                start = last - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
                if start < MIN_DATE:
                    start = MIN_DATE
                if start > end_d:          # already current; still re-pull its last day
                    start = end_d
                log.info(f"PROPERTY {account}: last BQ day {last} -> incremental {start}..{end_d}")
                process_forward_range(start, end_d, [account], key)

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"GA4 LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()