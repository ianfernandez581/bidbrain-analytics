"""
Windsor -> BigQuery loader for GOOGLE ADS campaign-level delivery data.

Lives in:  windsor_data_pull/google_ads/google_ads_loader.py
Runtime artifacts (chunk cache, log, temp NDJSON) -> _run/ next to this script
(anchored to __file__, gitignored), so nothing scatters into the repo root.

Near-copy of ga4_loader.py's skeleton -- same config block, get_secret (Secret
Manager via ADC), chunk cache, retries/backoff + fail-fast on 4xx, staging->MERGE->
cleanup, _MERGE_KEY_COLS/_MERGE_SET_COLS as the single source of truth, two run
modes, --force, FlushingStreamHandler logging, date_bounds_per_account, backfill
resume. TWO deliberate simplifications vs ga4_loader:

  1. SINGLE-PASS FETCH. GA4's Data API caps a request at 9 dims / 10 metrics, so
     ga4_loader splits every chunk into two metric-group passes and merges them.
     The Windsor google_ads connector has NO such cap, so this is ONE request per
     chunk (the events_loader.py shape) -- no FIELDS_GROUP_A/B, no merge_metric_groups,
     no fetch_chunk_combined.
  2. CAMPAIGN GRAIN. One row per (customer_id x metric_date x campaign_id) -- plain
     campaign x date, no source/medium/channel split.

Grain: one row per
    (customer_id x metric_date x campaign_id)
campaign_type rides along as an ATTRIBUTE, not part of the key: it's functionally
determined by campaign_id (an advertising-channel-type property of the campaign,
not per-day), exactly like is_conversion_event rides along in perf_ga4_events.

MERGE key (see _MERGE_KEY_COLS -- the single source of truth for both the staging
dedup and the SQL ON clause):
    customer_id + metric_date + campaign_id
customer_id / campaign_id coalesced to '(not set)' so the key is never NULL.

FIELD-NAME / FORMAT (confirmed via probe_google_ads_fields.py):
  * Dedicated `google_ads` connector (NOT the blended /all endpoint).
  * BARE customer ids in select_accounts -- no prefix (the `google_ads__` prefix is
    only for /all; the dedicated endpoint returns HTTP 400 for it).
  * Windsor returns account_id HYPHENATED (105-440-7474); account_key() normalises to
    digits so SELECT_ACCOUNTS matches the stored customer_id either way.
  * All requested fields populate (incl. campaign_type / currency_code).

METRICS: ADDITIVE BASE ONLY -- impressions, clicks, spend, conversions,
conversions_value. CTR / CPC / CPM / CPA / CVR / ROAS are derived in client SQL,
NEVER stored. ONE cost field (spend); cost / cost_micros / totalcost ignored.
conversions / conversions_value are NUMERIC (Google Ads conversions are fractional).

Writes the EXISTING perf_google_ads table (created by create_google_ads_table.py) --
run that once first. This loader does not create or alter the table; it reads the live
schema at runtime so staging/MERGE can't drift from it.

MODES (identical to ga4_loader.py)
----------------------------------
1. INCREMENTAL PER-ACCOUNT (no date args) -- normal / scheduled. For each customer in
   SELECT_ACCOUNTS it looks up MAX(metric_date) in BigQuery:
     * has data -> forward-loads from (last day - INCREMENTAL_LOOKBACK_DAYS) to
                   yesterday (re-pulled boundary days recapture late-attributed
                   conversions; staging + MERGE dedup).
     * no data  -> full backfill via backward walk from yesterday until
                   STOP_AFTER_EMPTY_CHUNKS consecutive empty chunks (or MIN_DATE).

       python windsor_data_pull/google_ads/google_ads_loader.py

2. FIXED RANGE (two date args) -- all accounts together, targeted re-pull. Use this for
   periodic deep reconciliation of a trailing 30-90 days (see INCREMENTAL_LOOKBACK_DAYS).

       python windsor_data_pull/google_ads/google_ads_loader.py 2026-05-25 2026-05-30

--force re-fetches even cached chunks (MERGE is idempotent on the key).

RETRIES: transient errors (timeouts, 429, 5xx) retried with capped backoff up to
MAX_ATTEMPTS, then the chunk fails loudly; permanent 4xx (bad field / auth / slug) fails
fast with the response body.
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
MAIN_TABLE = "perf_google_ads"
STAGING_TABLE = "perf_google_ads_staging"
GCS_BUCKET = "bidbrain-analytics-staging"

# Dedicated Google Ads connector endpoint + BARE customer ids (the connector is in the
# path, so no prefix -- the `google_ads__` prefix is only for the blended /all endpoint
# and returns HTTP 400 here). Confirmed via probe_google_ads_fields.py.
WINDSOR_URL = "https://connectors.windsor.ai/google_ads"
ACCOUNT_PREFIX = ""
SELECT_ACCOUNTS = [
    "105-440-7474",
    "261-791-6504",
    "519-659-6415",
    "850-931-3407",
    # A 5th account "186-974-5895" is also configured in Windsor; add it here AND map it
    # in CUSTOMER_TO_CLIENT below if you want it loaded.
]

# --- Fields (single pass: no GA4 9/10 cap on this connector) ---
# account_id/account_name are connector-account metadata (the customer we selected),
# present on every row. campaign_type rides along as an attribute (see docstring).
# spend is the ONLY cost field (ignore cost/cost_micros/totalcost). Probe-confirmed set.
FIELDS = ("date,account_id,account_name,campaign_id,campaign,campaign_type,"
          "currency_code,impressions,clicks,spend,conversions,conversions_value")

# campaign x date is low-cardinality and single-pass, so large chunks are cheap and there
# is no GA4-style sampling risk. Tunable; drop it if Windsor times out on the backfill.
CHUNK_DAYS = 90
STOP_AFTER_EMPTY_CHUNKS = 5
MIN_DATE = date(2015, 1, 1)
TIMEOUT_SEC = 120
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60
MAX_ATTEMPTS = 30          # per-chunk retry cap; then fail loudly instead of hanging forever
INTER_CHUNK_SLEEP = 1
# Google Ads conversions settle as they're attributed back to the CLICK date, so re-pull a
# trailing 7 days each incremental run (staging + MERGE dedup).
# WARNING: these are B2B accounts with potentially long conversion windows; a 7-day rolling
# lookback will NOT recapture conversions that land >7 days after the click. For full
# reconciliation, periodically run a fixed-range re-pull of a trailing 30-90 days (the
# two-date-arg mode already supports this).
INCREMENTAL_LOOKBACK_DAYS = 7

# All runtime artifacts live under _run/ next to THIS script (not the cwd).
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "google_ads_loader.log"

# Map a Google Ads customer id straight to (client_slug, agency_slug). Checked FIRST in
# infer_slugs -- most reliable. Fill using the account_names the probe printed:
CUSTOMER_TO_CLIENT = {
    # "105-440-7474": ("resetdata", "100-digital"),   # Reset Data
    # "261-791-6504": ("cp", "100-digital"),          # City Perfume
    # "519-659-6415": (...),                           # (no rows in probe window -- name unknown)
    # "850-931-3407": (...),                           # (no rows in probe window -- name unknown)
    # "186-974-5895": (...),                           # 5th configured account, not in SELECT_ACCOUNTS
}

# Fallback keyword match on account name / campaign (same dict as the other loaders).
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
log = logging.getLogger("google_ads_loader")

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
    # 1) explicit customer -> client override (most reliable)
    override = CUSTOMER_TO_CLIENT.get(str(row.get("account_id") or ""))
    if override:
        return override
    # 2) keyword match on account name / campaign (raw Windsor fields)
    haystack = " ".join(str(row.get(k) or "").lower() for k in
                        ("account_name", "campaign"))
    for keyword, agency in CLIENT_TO_AGENCY.items():
        if keyword in haystack:
            return keyword, agency
    return slugify(row.get("account_name") or "unknown"), "unknown"

def account_key(connector_or_id):
    """Bare numeric customer id. Used to match SELECT_ACCOUNTS against the customer_id
    values stored in BigQuery, whether Windsor returns 105-440-7474 or 1054407474."""
    return re.sub(r"\D", "", str(connector_or_id or ""))

def date_bounds_per_account(bq):
    """(MIN, MAX) metric_date per customer_id in the main table. Absent if no rows. MAX
    drives the forward incremental window; MIN lets the backfill RESUME from below the
    earliest day we have, so an interrupted backfill continues on the next run instead
    of needing a truncate."""
    sql = f"""
        SELECT customer_id,
               MIN(metric_date) AS min_date,
               MAX(metric_date) AS max_date
        FROM `{PROJECT_ID}.{DATASET}.{MAIN_TABLE}`
        WHERE customer_id IS NOT NULL
        GROUP BY customer_id
    """
    out = {}
    for r in bq.query(sql).result():
        mn, mx = r["min_date"], r["max_date"]
        if mx is None:
            continue
        if isinstance(mn, str): mn = date.fromisoformat(mn[:10])
        if isinstance(mx, str): mx = date.fromisoformat(mx[:10])
        out[account_key(r["customer_id"])] = (mn, mx)
    return out

def chunk_filename(d_from, d_to, cache_tag):
    return CHUNKS_DIR / f"{cache_tag}_{d_from.isoformat()}_to_{d_to.isoformat()}.json"

def fetch_chunk(api_key, d_from, d_to, idx, total, select_accounts, cache_tag, force=False):
    """Fetch one chunk (single pass). Retries transient errors; fails fast on 4xx.
    total may be None (backward-walk mode, count unknown)."""
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
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} got permanent HTTP {status}. This will NOT recover "
                f"by retrying -- likely a bad field name, auth, connector slug, or account "
                f"prefix. Sent fields:\n{FIELDS}\nBody:\n{body}"
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
    cust = g("account_id") or "(not set)"
    camp_id = g("campaign_id") or "(not set)"
    client_slug, agency_slug = infer_slugs(row)
    return {
        "platform": "google_ads",
        "customer_id": cust,
        "account_name": g("account_name"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "metric_date": to_date_iso(g("date")),
        "campaign_id": camp_id,
        "campaign_name": g("campaign"),
        "campaign_type": g("campaign_type"),
        "currency_code": g("currency_code"),
        # additive base metrics -- missing == 0 at this grain.
        # spend/conversions/conversions_value are fractional -> to_num, NOT to_int.
        "impressions": to_int(g("impressions")) or 0,
        "clicks": to_int(g("clicks")) or 0,
        "spend": to_num(g("spend")) or 0,
        "conversions": to_num(g("conversions")) or 0,
        "conversions_value": to_num(g("conversions_value")) or 0,
        "ingested_at": ingested_at_iso,
        "source": "windsor.google_ads",
        "raw_row": json.dumps(row),
    }

# Single source of truth for the grain. Drives BOTH the staging dedup and the SQL MERGE
# ON clause, so they can never drift apart. campaign_type is NOT in the key (attribute).
_MERGE_KEY_COLS = ["customer_id", "metric_date", "campaign_id"]

# Non-key columns updated on MERGE match (everything that isn't a key column).
_MERGE_SET_COLS = [
    "platform", "account_name", "client_slug", "agency_slug",
    "campaign_name", "campaign_type", "currency_code",
    "impressions", "clicks", "spend", "conversions", "conversions_value",
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

    gcs_path = f"loads/google_ads/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
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
        log.info(f"GOOGLE ADS LOADER START (fixed range): {start_d} to {end_d}{'  (FORCE)' if force else ''}")
    else:
        end_d = date.today() - timedelta(days=1)
        log.info(f"GOOGLE ADS LOADER START (incremental per-account): refresh each customer "
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
        for account in SELECT_ACCOUNTS:
            key = account_key(account)
            first, last = bounds.get(key, (None, None))
            log.info("=" * 60)
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

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"GOOGLE ADS LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
