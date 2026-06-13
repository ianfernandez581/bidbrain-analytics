"""
Windsor -> BigQuery loader for REDDIT ADS ad-level delivery data.

Lives in:  windsor_data_pull/reddit/reddit_loader.py
Runtime artifacts (chunk cache, log, temp NDJSON) -> _run/ next to this script
(anchored to __file__, gitignored), so nothing scatters into the repo root.

Near-copy of google_ads_loader.py's skeleton -- same config block, get_secret (Secret
Manager via ADC), chunk cache, retries/backoff + fail-fast on 4xx, staging->MERGE->
cleanup, _MERGE_KEY_COLS/_MERGE_SET_COLS as the single source of truth, two run modes,
--force, FlushingStreamHandler logging, date_bounds_per_account, backfill resume. Three
deliberate differences vs google_ads_loader:

  1. BLENDED /all ENDPOINT, NOT a dedicated /reddit connector. Reddit is requested through
     https://connectors.windsor.ai/all with a `reddit__` account prefix applied at request
     time (same mechanics as meta_loader.py). Confirmed via probe_reddit_fields.py.
  2. ALPHANUMERIC ACCOUNT IDS. Reddit account ids are opaque alphanumeric strings
     (a2_igd0szmw7roq). The siblings' account_key = re.sub(r"\\D","",...) strips to digits and
     would collapse a2_igd0szmw7roq -> "2", merging every account. So account_key() here is a
     STRING normaliser (strip a leading reddit__ prefix, lowercase, trim) that keeps the full
     a2_... body intact. Campaign / ad-group / ad ids are likewise treated as opaque strings.
  3. AD GRAIN BY ID. The probe proved /all returns the full Reddit hierarchy
     (campaign_id / ad_group_id / ad_id all populated -- NOT the GA4 nulling pattern), so the
     key is the finest grain (ad_id); campaign / ad-group ride along as attributes.

Grain: one row per
    (account_id x ad_id x metric_date)
campaign_id / campaign_name / campaign_objective / ad_group_id / ad_group_name ride along as
ATTRIBUTES (in _MERGE_SET_COLS, not the key) -- functionally determined by ad_id.

MERGE key (see _MERGE_KEY_COLS -- the single source of truth for both the staging dedup and
the SQL ON clause):
    account_id + ad_id + metric_date
account_id / ad_id coalesced to '(not set)' so the key is never NULL.

FIELD-NAME / FORMAT (confirmed via probe_reddit_fields.py):
  * Blended `/all` endpoint with the `reddit__` account prefix (NOT a dedicated /reddit
    connector). Windsor returns account_id BARE (a2_igd0szmw7roq -- strips the reddit__
    prefix); account_key() normalises so SELECT_ACCOUNTS matches the stored account_id.
  * campaign and campaign_name are identical; we keep campaign_name.
  * spend is in the account's NATIVE currency (account_currency, AUD for ResetData) -- NOT USD.
    We store account_currency so client views can FX.
  * upvotes / downvotes / comment_submissions come back NULL (Windsor doesn't surface Reddit
    engagement for the account); the columns stay (additive, reversible via raw_row).

METRICS: ADDITIVE BASE ONLY -- impressions, clicks, spend, reach, engagement counts, video
funnel counts, and the conversion click/view split + values. CTR / CPC / CPM / CPL / CVR /
frequency / video_completion_rate are derived in client SQL, NEVER stored. ONE cost field
(spend); totalcost ignored. Conversion counts/values are NUMERIC (Reddit conversions are
fractional under modeling / attribution).

Writes the EXISTING perf_reddit table (created by create_reddit_table.py) -- run that once
first. This loader does not create or alter the table; it reads the live schema at runtime so
staging/MERGE can't drift from it.

MODES (identical to google_ads_loader.py)
------------------------------------------
1. INCREMENTAL PER-ACCOUNT (no date args) -- normal / scheduled. For each account in
   SELECT_ACCOUNTS it looks up MAX(metric_date) in BigQuery:
     * has data -> forward-loads from (last day - INCREMENTAL_LOOKBACK_DAYS) to yesterday
                   (re-pulled boundary days recapture late-attributed conversions; staging +
                   MERGE dedup), then resumes the backward backfill below the earliest day.
     * no data  -> full backfill via backward walk from yesterday until
                   STOP_AFTER_EMPTY_CHUNKS consecutive empty chunks (or MIN_DATE).

       python windsor_data_pull/reddit/reddit_loader.py

2. FIXED RANGE (two date args) -- all accounts together, targeted re-pull. Use this for
   periodic deep reconciliation of a trailing 30-90 days (see INCREMENTAL_LOOKBACK_DAYS).

       python windsor_data_pull/reddit/reddit_loader.py 2026-05-25 2026-05-30

--force re-fetches even cached chunks (MERGE is idempotent on the key).

RETRIES: transient errors (timeouts, 429, 5xx) retried with capped backoff up to MAX_ATTEMPTS,
then the chunk fails loudly; permanent 4xx (bad field / auth) fails fast with the response
body. A Windsor 400 "account not available" is raised as AccountUnavailableError and SKIPPED
per-account (Reddit access can be revoked per-account, like TTD's was) so one revoked account
never aborts the run.
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
MAIN_TABLE = "perf_reddit"
STAGING_TABLE = "perf_reddit_staging"
GCS_BUCKET = "bidbrain-analytics-staging"

# Blended /all endpoint + the `reddit__` account prefix (applied at request time, Meta-style).
# NOT a dedicated /reddit connector. Bare ids in SELECT_ACCOUNTS (Google Ads style); the prefix
# is added when building the request. Confirmed via probe_reddit_fields.py.
WINDSOR_URL = "https://connectors.windsor.ai/all"
ACCOUNT_PREFIX = "reddit__"
SELECT_ACCOUNTS = [
    "a2_igd0szmw7roq",   # ResetData Ad Account (100Digital)
    # Add more bare Reddit account ids here AND map them in REDDIT_ACCOUNT_TO_CLIENT below.
    # Find ids at https://onboard.windsor.ai?datasource=reddit.
]

# --- Fields (single pass: no GA4 9/10 cap on /all) ---
# Curated additive-base set, probe-confirmed. We request campaign_name (identical to
# `campaign`; keep one) and do NOT request Windsor's `datasource` (we set our own `source`).
# ad_id is the finest grain; campaign/ad-group fields ride along as attributes. spend is the
# ONLY cost field (ignore totalcost). Conversion fields are the click/view split + values.
FIELDS = (
    "account_id,account_name,account_currency,"
    "campaign_id,campaign_name,campaign_objective,"
    "ad_group_id,ad_group_name,ad_id,ad_name,date,"
    "impressions,clicks,spend,reach,"
    "upvotes,downvotes,comment_submissions,"
    "video_started,video_watched_25_percent,video_watched_50_percent,"
    "video_watched_75_percent,video_watched_100_percent,"
    "conversion_lead_clicks,conversion_lead_views,"
    "conversion_sign_up_clicks,conversion_sign_up_views,"
    "conversion_page_visit_clicks,conversion_page_visit_views,"
    "lead_total_value,signup_total_value"
)

# Ad x date is higher cardinality than Google Ads' campaign grain, so start conservative.
# Single-pass with no GA4-style sampling risk. Tunable; drop it if Windsor times out on backfill.
CHUNK_DAYS = 30
STOP_AFTER_EMPTY_CHUNKS = 5
MIN_DATE = date(2015, 1, 1)
TIMEOUT_SEC = 120
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60
MAX_ATTEMPTS = 30          # per-chunk retry cap; then fail loudly instead of hanging forever
INTER_CHUNK_SLEEP = 1
# Reddit conversions settle as they're attributed back to the CLICK date, so re-pull a trailing
# 7 days each incremental run (staging + MERGE dedup).
# WARNING: B2B lead-gen accounts can have long conversion windows; a 7-day rolling lookback will
# NOT recapture conversions that land >7 days after the click. For full reconciliation,
# periodically run a fixed-range re-pull of a trailing 30-90 days (the two-date-arg mode does this).
INCREMENTAL_LOOKBACK_DAYS = 7

# All runtime artifacts live under _run/ next to THIS script (not the cwd).
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "reddit_loader.log"

# Map a Reddit account id straight to (client_slug, agency_slug). Checked FIRST in infer_slugs --
# most reliable. Fill using the account_names the probe printed:
REDDIT_ACCOUNT_TO_CLIENT = {
    "a2_igd0szmw7roq": ("resetdata", "100-digital"),   # ResetData Ad Account (100Digital)
}

# Fallback keyword match on account name / campaign (same dict as the other loaders -- keep in
# lockstep when a client is added/renamed).
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
log = logging.getLogger("reddit_loader")

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
    # 1) explicit account -> client override (most reliable)
    override = REDDIT_ACCOUNT_TO_CLIENT.get(str(row.get("account_id") or ""))
    if override:
        return override
    # 2) keyword match on account name / campaign name (raw Windsor fields)
    haystack = " ".join(str(row.get(k) or "").lower() for k in
                        ("account_name", "campaign_name"))
    for keyword, agency in CLIENT_TO_AGENCY.items():
        if keyword in haystack:
            return keyword, agency
    return slugify(row.get("account_name") or "unknown"), "unknown"

def account_key(connector_or_id):
    """Stable key for matching SELECT_ACCOUNTS against the account_id stored in BigQuery.

    THE REDDIT LANDMINE: Reddit account ids are ALPHANUMERIC (a2_igd0szmw7roq). The siblings'
    re.sub(r"\\D","",...) strips to digits and would collapse a2_igd0szmw7roq -> "2", merging
    every account and breaking SELECT_ACCOUNTS matching + date_bounds_per_account. So this is a
    STRING normaliser: strip a leading reddit__ connector prefix, lowercase, trim -- keep the
    full a2_... body intact. Works on the bare id, the prefixed handle, and the stored value."""
    s = str(connector_or_id or "").strip().lower()
    if s.startswith(ACCOUNT_PREFIX):
        s = s[len(ACCOUNT_PREFIX):]
    return s

def date_bounds_per_account(bq):
    """(MIN, MAX) metric_date per account_id in the main table. Absent if no rows. MAX drives the
    forward incremental window; MIN lets the backfill RESUME from below the earliest day we have,
    so an interrupted backfill continues on the next run instead of needing a truncate."""
    sql = f"""
        SELECT account_id,
               MIN(metric_date) AS min_date,
               MAX(metric_date) AS max_date
        FROM `{PROJECT_ID}.{DATASET}.{MAIN_TABLE}`
        WHERE account_id IS NOT NULL
        GROUP BY account_id
    """
    out = {}
    for r in bq.query(sql).result():
        mn, mx = r["min_date"], r["max_date"]
        if mx is None:
            continue
        if isinstance(mn, str): mn = date.fromisoformat(mn[:10])
        if isinstance(mx, str): mx = date.fromisoformat(mx[:10])
        out[account_key(r["account_id"])] = (mn, mx)
    return out

def chunk_filename(d_from, d_to, cache_tag):
    return CHUNKS_DIR / f"{cache_tag}_{d_from.isoformat()}_to_{d_to.isoformat()}.json"

class AccountUnavailableError(Exception):
    """Windsor returned a 400 saying a requested account is not available (not granted / wrong
    id / revoked). Not retryable, but skippable: per-account runs catch this and move on so one
    misconfigured or revoked account never aborts the whole loader."""


def fetch_chunk(api_key, d_from, d_to, idx, total, select_accounts, cache_tag, force=False):
    """Fetch one chunk (single pass) from /all with the reddit__ prefix applied per account.
    Retries transient errors; fails fast on 4xx (raising AccountUnavailableError for a 400
    'not available'). total may be None (backward-walk mode, count unknown)."""
    label = f"chunk {idx}/{total}" if total else f"chunk {idx}"
    if cache_tag != "all":
        label = f"{cache_tag} {label}"
    cache_file = chunk_filename(d_from, d_to, cache_tag)
    if cache_file.exists() and not force:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        log.info(f"  [{label}] CACHED {d_from}..{d_to}: {len(rows)} rows")
        return rows

    accounts = ",".join(f"{ACCOUNT_PREFIX}{a}" for a in select_accounts)
    params = {
        "api_key": api_key,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "fields": FIELDS,
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
                        f"Chunk {d_from}..{d_to}: gave up after {attempt} attempts "
                        f"on transient HTTP {status} (Windsor still failing)."
                    )
                sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
                log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} transient HTTP {status}; retrying in {sleep}s")
                time.sleep(sleep)
                continue
            body = (e.response.text[:500] if e.response is not None else "")
            if status == 400 and "not available" in body.lower():
                # Windsor 400: a requested account isn't granted/available to this connector.
                # Skippable (handled per-account by the caller), not a hard failure.
                raise AccountUnavailableError(
                    f"Account(s) {accounts} not available in Windsor. Body:\n{body}"
                )
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} got permanent HTTP {status}. This will NOT recover "
                f"by retrying -- likely a bad field name, auth, or account prefix. Sent "
                f"fields:\n{FIELDS}\nBody:\n{body}"
            )
        except requests.exceptions.RequestException as e:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Chunk {d_from}..{d_to}: gave up after {attempt} attempts "
                    f"({type(e).__name__}: {e})."
                )
            sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
            log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} FAILED ({type(e).__name__}); retrying in {sleep}s")
            time.sleep(sleep)

def to_int(v):
    if v in (None, "", "null"): return None
    try: return int(float(v))
    except (TypeError, ValueError): return None

def to_num(v):
    if v in (None, "", "null"): return None
    try: return float(v)
    except (TypeError, ValueError): return None

def to_date_iso(v):
    """Windsor 'date' is usually YYYY-MM-DD; accept YYYYMMDD too. BQ DATE load needs
    YYYY-MM-DD."""
    if not v: return None
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]

def transform(row, ingested_at_iso):
    g = row.get
    # Coalesce the string MERGE-key columns so the key is never NULL.
    acct = g("account_id") or "(not set)"
    ad = g("ad_id") or "(not set)"
    client_slug, agency_slug = infer_slugs(row)
    return {
        "platform": "reddit",
        "account_id": acct,
        "account_name": g("account_name"),
        "account_currency": g("account_currency"),
        "campaign_id": g("campaign_id"),
        "campaign_name": g("campaign_name"),
        "campaign_objective": g("campaign_objective"),
        "ad_group_id": g("ad_group_id"),
        "ad_group_name": g("ad_group_name"),
        "ad_id": ad,
        "ad_name": g("ad_name"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "metric_date": to_date_iso(g("date")),
        # Delivery: additive base. impressions/clicks/spend are always present -> default 0;
        # reach/engagement/video stay NULL-able (upvotes etc come back NULL from Windsor).
        "impressions": to_int(g("impressions")) or 0,
        "clicks": to_int(g("clicks")) or 0,
        "spend": to_num(g("spend")) or 0,
        "reach": to_int(g("reach")),
        # Engagement (counts -> to_int).
        "upvotes": to_int(g("upvotes")),
        "downvotes": to_int(g("downvotes")),
        "comment_submissions": to_int(g("comment_submissions")),
        # Video funnel (counts -> to_int).
        "video_starts": to_int(g("video_started")),
        "video_25": to_int(g("video_watched_25_percent")),
        "video_50": to_int(g("video_watched_50_percent")),
        "video_75": to_int(g("video_watched_75_percent")),
        "video_completes": to_int(g("video_watched_100_percent")),
        # Conversions: click/view split + values, NUMERIC (Reddit conversions are fractional).
        "lead_clicks": to_num(g("conversion_lead_clicks")),
        "lead_views": to_num(g("conversion_lead_views")),
        "signup_clicks": to_num(g("conversion_sign_up_clicks")),
        "signup_views": to_num(g("conversion_sign_up_views")),
        "page_visit_clicks": to_num(g("conversion_page_visit_clicks")),
        "page_visit_views": to_num(g("conversion_page_visit_views")),
        "lead_total_value": to_num(g("lead_total_value")),
        "signup_total_value": to_num(g("signup_total_value")),
        "ingested_at": ingested_at_iso,
        "source": "windsor.reddit",
        "raw_row": json.dumps(row),
    }

# Single source of truth for the grain. Drives BOTH the staging dedup and the SQL MERGE
# ON clause, so they can never drift apart. campaign/ad-group fields are NOT in the key
# (attributes) -- functionally determined by ad_id.
_MERGE_KEY_COLS = ["account_id", "ad_id", "metric_date"]

# Non-key columns updated on MERGE match (everything that isn't a key column).
_MERGE_SET_COLS = [
    "platform", "account_name", "account_currency",
    "campaign_id", "campaign_name", "campaign_objective",
    "ad_group_id", "ad_group_name", "ad_name", "client_slug", "agency_slug",
    "impressions", "clicks", "spend", "reach",
    "upvotes", "downvotes", "comment_submissions",
    "video_starts", "video_25", "video_50", "video_75", "video_completes",
    "lead_clicks", "lead_views", "signup_clicks", "signup_views",
    "page_visit_clicks", "page_visit_views", "lead_total_value", "signup_total_value",
    "ingested_at", "source", "raw_row",
]

def dedup_by_merge_key(rows):
    """Guarantee exactly one row per MERGE key in the staging load. BigQuery MERGE errors
    if >1 source row matches a target row. Last occurrence wins -- consistent with the
    MERGE's own UPDATE."""
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

    gcs_path = f"loads/reddit/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
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
        log.info(f"REDDIT LOADER START (fixed range): {start_d} to {end_d}{'  (FORCE)' if force else ''}")
    else:
        end_d = date.today() - timedelta(days=1)
        log.info(f"REDDIT LOADER START (incremental per-account): refresh each account "
                 f"from its last BQ day (lookback {INCREMENTAL_LOOKBACK_DAYS}d) up to {end_d}; "
                 f"accounts with no data get a full backward-walk backfill"
                 f"{'  (FORCE)' if force else ''}")
    log.info(f"Artifacts dir: {WORK_DIR}")
    log.info(f"Accounts: {len(SELECT_ACCOUNTS)} | chunk size: {CHUNK_DAYS}d | single fetch/chunk")
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
        rows = fetch_chunk(api_key, d_from, d_to, idx, total, select, cache_tag, force=force)
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
        log.info(f"Forward-loading {start_d}..{end_d} (all {len(SELECT_ACCOUNTS)} accounts together)")
        process_forward_range(start_d, end_d, SELECT_ACCOUNTS, "all")
    else:
        bounds = date_bounds_per_account(bq)
        log.info(f"Existing data in {MAIN_TABLE} for {len(bounds)}/{len(SELECT_ACCOUNTS)} configured account(s)")
        skipped = []
        for account in SELECT_ACCOUNTS:
            key = account_key(account)
            first, last = bounds.get(key, (None, None))
            log.info("=" * 60)
            try:
                if last is None:
                    log.info(f"ACCOUNT {account}: no rows in BQ -> full backfill (backward walk)")
                    process_backward_walk(end_d, [account], key)
                else:
                    # 1) Forward: re-pull the trailing lookback so late-attributed conversions firm up.
                    start = last - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
                    if start < MIN_DATE:
                        start = MIN_DATE
                    if start > end_d:
                        start = end_d
                    log.info(f"ACCOUNT {account}: last BQ day {last} -> incremental {start}..{end_d}")
                    process_forward_range(start, end_d, [account], key)
                    # 2) Backward: continue the backfill from below the earliest day we have.
                    #    Complete history -> hits empty chunks and stops after STOP_AFTER_EMPTY_CHUNKS.
                    #    Interrupted backfill -> resumes here. No truncate needed.
                    if first is not None and first > MIN_DATE:
                        log.info(f"ACCOUNT {account}: earliest BQ day {first} -> resume backward fill below it")
                        process_backward_walk(first - timedelta(days=1), [account], key)
            except AccountUnavailableError as e:
                # One account not granted/revoked in Windsor must not abort the others (or the
                # scheduled Cloud Run job). Log loudly and continue; grant access in Windsor or
                # drop it from SELECT_ACCOUNTS to silence.
                log.warning(f"SKIPPING account {account}: {e}")
                skipped.append(account)
        if skipped:
            log.warning(f"{len(skipped)} account(s) skipped (unavailable in Windsor): {', '.join(skipped)}")

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"REDDIT LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
