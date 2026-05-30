"""
Windsor -> BigQuery loader for The Trade Desk performance data.

Lives in:  windsor_data_pull/tradedesk/tradedesk_loader.py
Runtime artifacts (chunk cache, log, temp NDJSON) -> _run/ next to this script
(anchored to __file__, gitignored), so nothing scatters into the repo root.

Same per-chunk pipeline + modes as meta_loader.py. Grain: one row per
(campaign x date x ad_format). MERGE key = campaign_id + metric_date + ad_format.

MODES
-----
1. BACKWARD WALK (no date args) -- walks from yesterday back in CHUNK_DAYS
   windows, loading as it goes, until STOP_AFTER_EMPTY_CHUNKS consecutive empty
   chunks or the MIN_DATE floor. Auto-discovers how far back data exists.

       python windsor_data_pull/tradedesk/tradedesk_loader.py

2. FIXED RANGE (two date args):

       python windsor_data_pull/tradedesk/tradedesk_loader.py 2026-05-01 2026-05-31

--force re-fetches even cached chunks (MERGE is idempotent on the key).

RETRIES: transient errors (timeouts, 429, 5xx) retried with capped backoff up
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
WINDSOR_FIELDS = (
    "advertiser,advertiser_id,date,campaign_id,campaign,ad_format,"
    "impressions,clicks,advertiser_cost_adv_currency,"
    "player_starts,player_25_complete,player_50_complete,"
    "player_75_complete,player_completed_views"
)

CHUNK_DAYS = 3
STOP_AFTER_EMPTY_CHUNKS = 5
MIN_DATE = date(2015, 1, 1)
TIMEOUT_SEC = 120
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60
MAX_ATTEMPTS = 30          # per-chunk retry cap; then fail loudly instead of hanging forever
INTER_CHUNK_SLEEP = 1

# All runtime artifacts live under _run/ next to THIS script (not the cwd).
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "loader.log"

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

def chunk_filename(d_from, d_to):
    return CHUNKS_DIR / f"{d_from.isoformat()}_to_{d_to.isoformat()}.json"

def fetch_chunk(api_key, d_from, d_to, idx, total, force=False):
    """Fetch one chunk. Retries transient errors forever; fails fast on 4xx.
    total may be None (backward-walk mode where the count is unknown)."""
    tag = f"chunk {idx}/{total}" if total else f"chunk {idx}"
    cache_file = chunk_filename(d_from, d_to)
    if cache_file.exists() and not force:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        log.info(f"  [{tag}] CACHED {d_from}..{d_to}: {len(rows)} rows")
        return rows

    params = {
        "api_key": api_key,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "fields": WINDSOR_FIELDS,
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
                    raise RuntimeError(
                        f"Chunk {d_from}..{d_to}: gave up after {attempt} attempts on "
                        f"transient HTTP {status} (Windsor still failing)."
                    )
                sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
                log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} transient HTTP {status}; retrying in {sleep}s")
                time.sleep(sleep)
                continue
            body = (e.response.text[:500] if e.response is not None else "")
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} got permanent HTTP {status}. This will NOT "
                f"recover by retrying -- likely a bad field name or auth. Body:\n{body}"
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

def transform(row, ingested_at_iso):
    client_slug, agency_slug = infer_slugs(row)
    g = row.get
    return {
        "platform": "the_trade_desk",
        "advertiser_id": g("advertiser_id"),
        "advertiser_name": g("advertiser"),
        "campaign_id": g("campaign_id"),
        "campaign_name": g("campaign"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "ad_format": g("ad_format") or "unknown",
        "metric_date": g("date"),
        "impressions": to_int(g("impressions")) or 0,
        "clicks": to_int(g("clicks")) or 0,
        "cost": to_num(g("advertiser_cost_adv_currency")) or 0,
        "currency": "AUD",
        "video_starts": to_int(g("player_starts")),
        "video_25": to_int(g("player_25_complete")),
        "video_50": to_int(g("player_50_complete")),
        "video_75": to_int(g("player_75_complete")),
        "video_completes": to_int(g("player_completed_views")),
        "ingested_at": ingested_at_iso,
        "source": "windsor.tradedesk",
        "raw_row": json.dumps(row),
    }

# Non-key columns updated on MERGE match (keys: campaign_id, metric_date, ad_format)
_MERGE_SET_COLS = [
    "platform","advertiser_id","advertiser_name","campaign_name",
    "client_slug","agency_slug","impressions","clicks","cost","currency",
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
def main():
    overall_start = time.monotonic()
    pos = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    fixed_range = len(pos) == 2

    log.info("=" * 60)
    if fixed_range:
        start_d = date.fromisoformat(pos[0])
        end_d = date.fromisoformat(pos[1])
        log.info(f"TRADEDESK LOADER START (fixed range): {start_d} to {end_d}{'  (FORCE)' if force else ''}")
    else:
        end_d = date.today() - timedelta(days=1)
        log.info(f"TRADEDESK LOADER START (backward walk): from {end_d} back until "
                 f"{STOP_AFTER_EMPTY_CHUNKS} consecutive empty chunks (floor {MIN_DATE})"
                 f"{'  (FORCE)' if force else ''}")
    log.info(f"Artifacts dir: {WORK_DIR}")
    log.info(f"Chunk size: {CHUNK_DAYS}d")
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

    def run_chunk(d_from, d_to, idx, total):
        nonlocal grand_inserted, grand_updated, grand_rows_fetched
        log.info("-" * 60)
        rows = fetch_chunk(api_key, d_from, d_to, idx, total, force=force)
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

    if fixed_range:
        chunks = []
        cur = start_d
        while cur <= end_d:
            ce = min(cur + timedelta(days=CHUNK_DAYS - 1), end_d)
            chunks.append((cur, ce))
            cur = ce + timedelta(days=1)
        chunks.reverse()
        total = len(chunks)
        log.info(f"Will process {total} chunks (newest first)")
        for i, (d_from, d_to) in enumerate(chunks, start=1):
            run_chunk(d_from, d_to, i, total)
            time.sleep(INTER_CHUNK_SLEEP)
    else:
        consecutive_empty = 0
        idx = 0
        cur_to = end_d
        while True:
            idx += 1
            cur_from = cur_to - timedelta(days=CHUNK_DAYS - 1)
            floor_hit = cur_from <= MIN_DATE
            if floor_hit:
                cur_from = MIN_DATE
            n = run_chunk(cur_from, cur_to, idx, None)

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

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"TRADEDESK LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()