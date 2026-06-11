"""
Windsor -> BigQuery loader for The Trade Desk performance data.

Lives in:  windsor_data_pull/tradedesk/tradedesk_loader.py
Runtime artifacts (chunk cache, log, temp NDJSON) -> _run/ next to this script
(anchored to __file__, gitignored), so nothing scatters into the repo root.

Same per-chunk pipeline + modes as meta_loader.py. Grain: one row per
(campaign x ad_group x creative x date x ad_format).
MERGE key = campaign_id + ad_group_id + creative_id + metric_date + ad_format.

All fields below are from Windsor's "Ad Group Performance" report (verified
against the TTD field reference), so they're all queryable in a single request.

CONVERSIONS / "PIXEL FIRES": Windsor exposes TTD conversions only as anonymous
numbered slots (click_conversion_01..12, view_through_conversion_01..12,
conversion_touch_01..12). There is NO pixel name / pixel ID dimension in this
connector. We pull the slots and store the populated ones as a compact JSON map
in the `conversions` column. A "Pixel -> Event" table with real pixel names is
NOT possible from Windsor alone -- it needs a slot->pixel mapping you maintain,
or the TTD API directly.

MODES
-----
1. BACKWARD WALK (no date args) -- walks from yesterday back in CHUNK_DAYS
   windows, loading as it goes, until STOP_AFTER_EMPTY_CHUNKS consecutive empty
   chunks or the MIN_DATE floor. Auto-discovers how far back data exists.

       python windsor_data_pull/tradedesk/tradedesk_loader.py

2. FIXED RANGE (two date args):

       python windsor_data_pull/tradedesk/tradedesk_loader.py 2026-05-01 2026-05-31

--force re-fetches even cached chunks (MERGE is idempotent on the key).

RETRIES: transient errors (timeouts, 429, 5xx) retried with a fixed 5s delay up
to MAX_ATTEMPTS times, then the chunk fails loudly (so an unattended/scheduled
run can't hang forever); permanent 4xx (bad field / auth) fails fast with the
response body.
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
MAIN_TABLE = "perf_the_trade_desk"
STAGING_TABLE = "perf_the_trade_desk_staging"
GCS_BUCKET = "bidbrain-analytics-staging"
WINDSOR_URL = "https://connectors.windsor.ai/tradedesk"

# Windsor TTD ACCOUNT IDs we pull, ONE request per account. These are numeric account
# ids, NOT advertiser names -- the /tradedesk `select_accounts` param takes the id; an
# advertiser name like "City Perfume" 400s as "not available". Pulling per-account
# (instead of the old "all accounts in one blended call") is what makes the loader
# resilient: if we lose Windsor access to one account it is skipped with a warning and
# every OTHER account still updates, instead of one revoked account aborting the whole
# table (which froze perf_the_trade_desk at 2026-05-31 for everyone).
#
# Windsor currently reports exactly one configured account: 484 (the City Perfume TTD
# seat). The former Altech / WEHI accounts are no longer granted by Windsor and were
# removed here on 2026-06-11. To (re)add one: grant it at
# https://onboard.windsor.ai?datasource=tradedesk then append its id below.
SELECT_ACCOUNTS = ["484"]

# Conversion slots we pull (all in the Ad Group Performance report). These are
# stored compactly in the `conversions` JSON column (only populated slots kept).
# To also capture time-weighted-decay or revenue/currency variants, extend the
# `kinds` tuple below -- they follow the same _NN naming.
_CONVERSION_KINDS = ("click_conversion", "view_through_conversion", "conversion_touch")
_CONVERSION_SLOTS = [
    f"{kind}_{i:02d}" for kind in _CONVERSION_KINDS for i in range(1, 13)
]

WINDSOR_FIELDS = ",".join([
    # Dimensions
    "advertiser", "advertiser_id", "date",
    "campaign_id", "campaign",
    "ad_group_id", "ad_group_name",         # verified field IDs (no bare "ad_group")
    "creative_id", "creative",              # "creative" = creative name in this report
    "ad_format", "advertiser_currency_code",
    # Core metrics
    "impressions", "clicks", "advertiser_cost_adv_currency",
    # Video
    "player_starts", "player_25_complete", "player_50_complete",
    "player_75_complete", "player_completed_views",
    # Conversion slots (anonymous; see module docstring)
    *_CONVERSION_SLOTS,
])

CHUNK_DAYS = 3
STOP_AFTER_EMPTY_CHUNKS = 5
MAX_FETCH_FAILURES = 5     # consecutive fetch failures before abandoning an account (Windsor down)
MIN_DATE = date(2015, 1, 1)
TIMEOUT_SEC = 120
RETRY_SLEEP_SEC = 5        # fixed delay between retry attempts (no backoff)
MAX_ATTEMPTS = 30          # per-chunk retry cap; then fail loudly instead of hanging forever
INTER_CHUNK_SLEEP = 1

# All runtime artifacts live under _run/ next to THIS script (not the cwd).
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "loader.log"

CLIENT_TO_AGENCY = {
    # wehi / altech removed 2026-06-11 -- Windsor no longer grants their TTD accounts.
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
log = logging.getLogger("tradedesk_loader")

# ---------- Helpers ----------
def get_secret(name):
    """Read the latest version of a Secret Manager secret via Application
    Default Credentials -- the same ADC the BigQuery/Storage clients use. No
    gcloud CLI or machine-specific path required, so this runs identically on
    Windows/macOS/Linux locally (after `gcloud auth application-default login`)
    and on Cloud Run/Cloud Build under a service account."""
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
    advertiser = (row.get("advertiser") or "").lower()
    campaign = (row.get("campaign") or "").lower()
    for keyword, agency in CLIENT_TO_AGENCY.items():
        if keyword in advertiser or keyword in campaign:
            return keyword, agency
    return slugify(row.get("advertiser") or "unknown"), "unknown"

def chunk_filename(d_from, d_to, account):
    return CHUNKS_DIR / f"{account}_{d_from.isoformat()}_to_{d_to.isoformat()}.json"


class AccountUnavailableError(Exception):
    """Windsor 400: the requested account isn't granted to this connector (lost /
    never-had access). Not retryable, but skippable -- the per-account caller logs
    it and moves on so one revoked account never aborts the whole loader. Carries
    the set of accounts Windsor says ARE configured (parsed from the message)."""
    def __init__(self, account, available, body):
        self.account = account
        self.available = available          # set[str] of still-configured account ids
        super().__init__(
            f"TTD account {account} not available in Windsor "
            f"(still configured: {sorted(available) or 'none'}). Body: {body[:200]}")


class ChunkFetchError(Exception):
    """Transient fetch failed after MAX_ATTEMPTS (Windsor data endpoint dropping the
    connection / 429 / 5xx). The caller skips the chunk rather than crashing; too many
    in a row for an account means Windsor's TTD data path is down and that account is
    abandoned for this run."""


_CONFIGURED_RE = re.compile(r"configured accounts? (?:is|are):\s*([0-9,\s]+)", re.I)


def parse_available_accounts(body):
    """Pull the '... The configured accounts are: 484, 512 ...' id list out of Windsor's
    400 body so we can report exactly what access remains. Empty set if not present."""
    m = _CONFIGURED_RE.search(body or "")
    return {a.strip() for a in m.group(1).split(",") if a.strip()} if m else set()


def fetch_chunk(api_key, d_from, d_to, idx, total, account, force=False):
    """Fetch one chunk for ONE account. Retries transient errors up to MAX_ATTEMPTS
    then raises ChunkFetchError; raises AccountUnavailableError on a 'not available'
    400; fails fast on any other permanent 4xx. total may be None (backward-walk)."""
    tag = f"{account} chunk {idx}/{total}" if total else f"{account} chunk {idx}"
    cache_file = chunk_filename(d_from, d_to, account)
    if cache_file.exists() and not force:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        log.info(f"  [{tag}] CACHED {d_from}..{d_to}: {len(rows)} rows")
        return rows

    params = {
        "api_key": api_key,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "fields": WINDSOR_FIELDS,
        "select_accounts": account,
    }
    log.info(f"  [{tag}] Fetching {d_from}..{d_to}{' (FORCE)' if force else ''}")
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
            log.info(f"  [{tag}] SUCCESS: {len(rows)} rows in {total_elapsed:.1f}s")
            cache_file.write_text(json.dumps(rows), encoding="utf-8")
            return rows
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429 or (status is not None and status >= 500):
                if attempt >= MAX_ATTEMPTS:
                    raise ChunkFetchError(
                        f"Chunk {d_from}..{d_to}: gave up after {attempt} attempts on "
                        f"transient HTTP {status} (Windsor still failing)."
                    )
                sleep = RETRY_SLEEP_SEC
                log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} transient HTTP {status}; retrying in {sleep}s")
                time.sleep(sleep)
                continue
            body = (e.response.text[:500] if e.response is not None else "")
            if status == 400 and "not available" in body.lower():
                # Account isn't granted to this Windsor connector -- skippable per-account.
                raise AccountUnavailableError(account, parse_available_accounts(body), body)
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} got permanent HTTP {status}. This will NOT "
                f"recover by retrying -- likely a bad field name or auth. Body:\n{body}"
            )
        except requests.exceptions.RequestException as e:
            # Includes ConnectionError/RemoteDisconnected -- Windsor dropping the
            # connection on a real data pull (its TTD data endpoint timing out/crashing).
            if attempt >= MAX_ATTEMPTS:
                raise ChunkFetchError(
                    f"Chunk {d_from}..{d_to}: gave up after {attempt} attempts "
                    f"({type(e).__name__}: {e})."
                )
            sleep = RETRY_SLEEP_SEC
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

def extract_conversions(row):
    """Collapse the numbered conversion slots into a compact dict of only the
    populated (non-zero) slots, e.g. {"click_conversion_01": 5.0}. Returns a
    JSON string, or None if nothing fired. Full fidelity is still in raw_row."""
    out = {}
    for slot in _CONVERSION_SLOTS:
        v = to_num(row.get(slot))
        if v:  # skip None and 0
            out[slot] = v
    return json.dumps(out) if out else None

def transform(row, ingested_at_iso):
    client_slug, agency_slug = infer_slugs(row)
    g = row.get
    return {
        "platform": "the_trade_desk",
        "advertiser_id": g("advertiser_id"),
        "advertiser_name": g("advertiser"),
        "campaign_id": g("campaign_id"),
        "campaign_name": g("campaign"),
        # IDs coalesced to "unknown" so they're never NULL in the MERGE key
        # (NULL != NULL in SQL would break idempotency) -- same as ad_format.
        "ad_group_id": g("ad_group_id") or "unknown",
        "ad_group_name": g("ad_group_name"),
        "creative_id": g("creative_id") or "unknown",
        "creative_name": g("creative"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "ad_format": g("ad_format") or "unknown",
        "metric_date": g("date"),
        "impressions": to_int(g("impressions")) or 0,
        "clicks": to_int(g("clicks")) or 0,
        "cost": to_num(g("advertiser_cost_adv_currency")) or 0,
        # Real per-advertiser currency now (was hardcoded "AUD").
        "currency": g("advertiser_currency_code") or "AUD",
        "conversions": extract_conversions(row),
        "video_starts": to_int(g("player_starts")),
        "video_25": to_int(g("player_25_complete")),
        "video_50": to_int(g("player_50_complete")),
        "video_75": to_int(g("player_75_complete")),
        "video_completes": to_int(g("player_completed_views")),
        "ingested_at": ingested_at_iso,
        "source": "windsor.tradedesk",
        "raw_row": json.dumps(row),
    }

# Non-key columns updated on MERGE match.
# Keys are: campaign_id, ad_group_id, creative_id, metric_date, ad_format
# -- so those are NOT in this list. Names (which can change while the ID is
# stable) ARE updated.
_MERGE_SET_COLS = [
    "platform","advertiser_id","advertiser_name","campaign_name",
    "ad_group_name","creative_name",
    "client_slug","agency_slug","impressions","clicks","cost","currency",
    "conversions",
    "video_starts","video_25","video_50","video_75","video_completes",
    "ingested_at","source","raw_row",
]

def load_chunk_to_bq(bq, storage_client, main_table_schema, rows, ingested_at, d_from, d_to):
    if not rows:
        log.info(f"  (no rows for {d_from}..{d_to}, skipping BQ load)")
        return 0, 0

    transformed = [transform(r, ingested_at) for r in rows]
    run_id = uuid.uuid4().hex[:8]
    local_path = WORK_DIR / f"load_{run_id}.ndjson"
    with local_path.open("w", encoding="utf-8") as f:
        for row in transformed:
            f.write(json.dumps(row) + "\n")
    size_kb = local_path.stat().st_size / 1024
    log.info(f"  Wrote {len(transformed)} rows ({size_kb:.1f} KB) to {local_path.name}")

    gcs_path = f"loads/tradedesk/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
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

    set_clause = ",\n        ".join(f"{c} = S.{c}" for c in _MERGE_SET_COLS)
    merge_sql = f"""
    MERGE `{PROJECT_ID}.{DATASET}.{MAIN_TABLE}` T
    USING `{staging_ref}` S
    ON  T.campaign_id = S.campaign_id
    AND T.ad_group_id = S.ad_group_id
    AND T.creative_id = S.creative_id
    AND T.metric_date = S.metric_date
    AND T.ad_format   = S.ad_format
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
def process_account(account, fixed_range, start_d, end_d, run_chunk):
    """Walk ONE account's chunks. Returns 'ok' if it completed (even with 0 new rows)
    or 'failed' if abandoned after MAX_FETCH_FAILURES consecutive fetch failures (Windsor
    data endpoint down). Raises AccountUnavailableError if the account isn't granted, so
    the caller can skip it and keep going with the others."""
    log.info("=" * 60)
    log.info(f"ACCOUNT {account}: "
             + (f"fixed range {start_d}..{end_d}" if fixed_range
                else f"backward walk from {end_d}"))
    consecutive_fetch_fail = 0

    def guarded(d_from, d_to, idx, total):
        """run_chunk, but a ChunkFetchError becomes a None sentinel + bumps the
        consecutive-failure counter (so we abandon a down account instead of walking
        back to MIN_DATE on every window). AccountUnavailableError propagates out."""
        nonlocal consecutive_fetch_fail
        try:
            n = run_chunk(d_from, d_to, idx, total, account)
            consecutive_fetch_fail = 0
            return n
        except ChunkFetchError as e:
            consecutive_fetch_fail += 1
            log.error(f"  FETCH FAILED ({consecutive_fetch_fail}/{MAX_FETCH_FAILURES}) {d_from}..{d_to}: {e}")
            return None

    if fixed_range:
        chunks = []
        cur = start_d
        while cur <= end_d:
            ce = min(cur + timedelta(days=CHUNK_DAYS - 1), end_d)
            chunks.append((cur, ce))
            cur = ce + timedelta(days=1)
        chunks.reverse()
        total = len(chunks)
        for i, (d_from, d_to) in enumerate(chunks, start=1):
            guarded(d_from, d_to, i, total)
            if consecutive_fetch_fail >= MAX_FETCH_FAILURES:
                log.error(f"  >>> ACCOUNT {account}: {MAX_FETCH_FAILURES} consecutive fetch failures "
                          f"-- Windsor TTD data endpoint down. Abandoning this account.")
                return "failed"
            time.sleep(INTER_CHUNK_SLEEP)
        return "ok"

    # backward walk
    consecutive_empty = 0
    idx = 0
    cur_to = end_d
    while True:
        idx += 1
        cur_from = cur_to - timedelta(days=CHUNK_DAYS - 1)
        floor_hit = cur_from <= MIN_DATE
        if floor_hit:
            cur_from = MIN_DATE
        n = guarded(cur_from, cur_to, idx, None)

        if n is None:                       # fetch failed -- distinct from an empty 200
            if consecutive_fetch_fail >= MAX_FETCH_FAILURES:
                log.error(f"  >>> ACCOUNT {account}: {MAX_FETCH_FAILURES} consecutive fetch failures "
                          f"-- Windsor TTD data endpoint down. Abandoning this account.")
                return "failed"
        elif n == 0:
            consecutive_empty += 1
            log.info(f"  empty chunk #{consecutive_empty} of {STOP_AFTER_EMPTY_CHUNKS} before stopping")
            if consecutive_empty >= STOP_AFTER_EMPTY_CHUNKS:
                log.info(f"  >>> {STOP_AFTER_EMPTY_CHUNKS} consecutive empty chunks. "
                         f"Assuming start of history. Stopping.")
                return "ok"
        else:
            consecutive_empty = 0

        if floor_hit:
            log.info(f"  >>> Reached MIN_DATE floor ({MIN_DATE}). Stopping.")
            return "ok"
        cur_to = cur_from - timedelta(days=1)
        time.sleep(INTER_CHUNK_SLEEP)


def main():
    overall_start = time.monotonic()
    pos = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    fixed_range = len(pos) == 2
    start_d = end_d = None
    if fixed_range:
        start_d = date.fromisoformat(pos[0])
        end_d = date.fromisoformat(pos[1])
    else:
        end_d = date.today() - timedelta(days=1)

    log.info("=" * 60)
    mode = (f"fixed range {start_d}..{end_d}" if fixed_range
            else f"backward walk from {end_d} (stop after {STOP_AFTER_EMPTY_CHUNKS} empty, floor {MIN_DATE})")
    log.info(f"TRADEDESK LOADER START ({mode}){'  (FORCE)' if force else ''}")
    log.info(f"Accounts: {SELECT_ACCOUNTS} | chunk {CHUNK_DAYS}d | "
             f"{len(WINDSOR_FIELDS.split(','))} fields ({len(_CONVERSION_SLOTS)} conversion slots)")
    log.info(f"Artifacts dir: {WORK_DIR}")
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

    def run_chunk(d_from, d_to, idx, total, account):
        nonlocal grand_inserted, grand_updated, grand_rows_fetched
        log.info("-" * 60)
        rows = fetch_chunk(api_key, d_from, d_to, idx, total, account, force=force)
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

    completed, skipped, failed = [], [], []
    for account in SELECT_ACCOUNTS:
        try:
            status = process_account(account, fixed_range, start_d, end_d, run_chunk)
        except AccountUnavailableError as e:
            # Lost (or never had) Windsor access to this account: skip it, keep the rest.
            log.warning(f"SKIPPING account {account}: {e}")
            skipped.append((account, e.available))
            continue
        (completed if status == "ok" else failed).append(account)

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"TRADEDESK LOADER DONE in {overall:.1f} min")
    log.info(f"  Accounts: {len(completed)} ok, {len(skipped)} unavailable, {len(failed)} failed")
    log.info(f"  Rows fetched: {grand_rows_fetched} | inserted: {grand_inserted} | updated: {grand_updated}")
    if skipped:
        still = sorted(set().union(*[a for _, a in skipped])) or "none"
        log.warning(f"  Unavailable (lost Windsor access): {[a for a, _ in skipped]}. "
                    f"Windsor still grants: {still}. "
                    f"Re-grant at https://onboard.windsor.ai?datasource=tradedesk")
    if failed:
        log.error(f"  Failed (Windsor TTD data endpoint down): {failed}")
    log.info("=" * 60)

    # Non-zero exit only when NOTHING updated, so a scheduled run goes red and alerts.
    # A run where some accounts lost access but others still loaded is a success --
    # that per-account resilience is the whole point of this rewrite.
    if not completed:
        if failed:
            raise SystemExit("Windsor TTD data endpoint is down -- no account could be fetched; "
                             "perf_the_trade_desk not updated this run.")
        raise SystemExit("No TTD accounts available in Windsor -- nothing updated. Re-grant "
                         "access at https://onboard.windsor.ai?datasource=tradedesk")


if __name__ == "__main__":
    main()