"""
Windsor → BigQuery loader for The Trade Desk performance data.

Per-chunk pipeline: each 3-day chunk is fetched, uploaded, loaded, and
MERGEd independently. Data starts appearing in BQ after the first chunk.

Run:
    python loader.py                          # YTD, newest first
    python loader.py 2026-05-01 2026-05-31    # custom range, newest first

Verbose logging to stdout AND loader.log.
Chunks cached on disk under chunks/ — re-runs skip already-fetched chunks.
"""
import json
import logging
import re
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from google.cloud import bigquery, storage

# ---------- Config ----------
PROJECT_ID = "bidbrain-analytics"
DATASET = "raw_windsor"   # was "reports"
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
MAX_ATTEMPTS = 50
TIMEOUT_SEC = 10
RETRY_SLEEP_SEC = 5
CHUNKS_DIR = Path("chunks")
GCLOUD = r"C:\Users\ianfe\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"

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
        logging.FileHandler("loader.log", mode="a", encoding="utf-8"),
        FlushingStreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("loader")

# ---------- Helpers ----------
def get_secret(name):
    log.info(f"Fetching secret '{name}' from Secret Manager...")
    r = subprocess.run(
        [GCLOUD, "secrets", "versions", "access", "latest", "--secret", name],
        capture_output=True, text=True, check=True,
    )
    val = r.stdout.strip()
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

def chunked_range(start, end, days=CHUNK_DAYS):
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)

def chunk_filename(d_from, d_to):
    return CHUNKS_DIR / f"{d_from.isoformat()}_to_{d_to.isoformat()}.json"

def fetch_chunk(api_key, d_from, d_to, chunk_idx, total_chunks):
    cache_file = chunk_filename(d_from, d_to)
    if cache_file.exists():
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        log.info(f"  [chunk {chunk_idx}/{total_chunks}] CACHED {d_from}..{d_to}: {len(rows)} rows (from {cache_file.name})")
        return rows

    params = {
        "api_key": api_key,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "fields": WINDSOR_FIELDS,
    }
    log.info(f"  [chunk {chunk_idx}/{total_chunks}] Fetching {d_from}..{d_to}")
    start = time.monotonic()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_start = time.monotonic()
        try:
            r = requests.get(WINDSOR_URL, params=params, timeout=TIMEOUT_SEC)
            elapsed = time.monotonic() - attempt_start
            log.info(f"    attempt {attempt}: HTTP {r.status_code} in {elapsed:.1f}s")
            r.raise_for_status()
            rows = r.json().get("data", [])
            total_elapsed = time.monotonic() - start
            log.info(f"  [chunk {chunk_idx}/{total_chunks}] SUCCESS: {len(rows)} rows in {total_elapsed:.1f}s")
            cache_file.write_text(json.dumps(rows), encoding="utf-8")
            return rows
        except requests.exceptions.RequestException as e:
            elapsed = time.monotonic() - attempt_start
            log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} FAILED in {elapsed:.1f}s: {type(e).__name__}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_SLEEP_SEC)
    raise RuntimeError(f"Chunk {d_from}..{d_to} failed after {MAX_ATTEMPTS} attempts")

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
    return {
        "platform": "the_trade_desk",
        "advertiser_id": row.get("advertiser_id"),
        "advertiser_name": row.get("advertiser"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "ad_format": row.get("ad_format") or "unknown",
        "metric_date": row.get("date"),
        "impressions": to_int(row.get("impressions")) or 0,
        "clicks": to_int(row.get("clicks")) or 0,
        "cost": to_num(row.get("advertiser_cost_adv_currency")) or 0,
        "currency": "AUD",
        "video_starts": to_int(row.get("player_starts")),
        "video_25": to_int(row.get("player_25_complete")),
        "video_50": to_int(row.get("player_50_complete")),
        "video_75": to_int(row.get("player_75_complete")),
        "video_completes": to_int(row.get("player_completed_views")),
        "ingested_at": ingested_at_iso,
        "source": "windsor.tradedesk",
        "raw_row": json.dumps(row),
    }

def load_chunk_to_bq(bq, storage_client, main_table_schema, rows, ingested_at, d_from, d_to):
    """Upload one chunk's rows to GCS, load to staging, MERGE into main, cleanup."""
    if not rows:
        log.info(f"  (no rows for {d_from}..{d_to}, skipping BQ load)")
        return 0, 0

    transformed = [transform(r, ingested_at) for r in rows]
    run_id = uuid.uuid4().hex[:8]
    local_path = Path(f"load_{run_id}.ndjson")
    with local_path.open("w", encoding="utf-8") as f:
        for row in transformed:
            f.write(json.dumps(row) + "\n")
    size_kb = local_path.stat().st_size / 1024
    log.info(f"  Wrote {len(transformed)} rows ({size_kb:.1f} KB) to {local_path.name}")

    gcs_path = f"loads/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
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

    merge_sql = f"""
    MERGE `{PROJECT_ID}.{DATASET}.{MAIN_TABLE}` T
    USING `{staging_ref}` S
    ON  T.campaign_id = S.campaign_id
    AND T.metric_date = S.metric_date
    AND T.ad_format   = S.ad_format
    WHEN MATCHED THEN UPDATE SET
        platform        = S.platform,
        advertiser_id   = S.advertiser_id,
        advertiser_name = S.advertiser_name,
        campaign_name   = S.campaign_name,
        client_slug     = S.client_slug,
        agency_slug     = S.agency_slug,
        impressions     = S.impressions,
        clicks          = S.clicks,
        cost            = S.cost,
        currency        = S.currency,
        video_starts    = S.video_starts,
        video_25        = S.video_25,
        video_50        = S.video_50,
        video_75        = S.video_75,
        video_completes = S.video_completes,
        ingested_at     = S.ingested_at,
        source          = S.source,
        raw_row         = S.raw_row
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
    if len(sys.argv) == 3:
        start_d = date.fromisoformat(sys.argv[1])
        end_d = date.fromisoformat(sys.argv[2])
    else:
        start_d = date(2026, 1, 1)
        end_d = date.today() - timedelta(days=1)

    log.info("=" * 60)
    log.info(f"LOADER START: {start_d} to {end_d}")
    log.info("Per-chunk pipeline: each chunk loads to BQ before next fetch.")
    log.info("Chunks processed NEWEST FIRST.")
    log.info("=" * 60)

    CHUNKS_DIR.mkdir(exist_ok=True)
    api_key = get_secret("windsor-api-key")
    ingested_at = datetime.now(timezone.utc).isoformat()

    bq = bigquery.Client(project=PROJECT_ID, location="asia-southeast1")
    storage_client = storage.Client(project=PROJECT_ID)
    main_table = bq.get_table(f"{PROJECT_ID}.{DATASET}.{MAIN_TABLE}")
    main_table_schema = main_table.schema
    log.info(f"BQ ready. Main table: {main_table.full_table_id}")

    # Build chunks list, newest-first
    chunks = list(chunked_range(start_d, end_d))
    chunks.reverse()
    total_chunks = len(chunks)
    log.info(f"Will process {total_chunks} chunks of {CHUNK_DAYS} days each (newest first)")

    grand_inserted = 0
    grand_updated = 0
    grand_rows_fetched = 0

    for i, (d_from, d_to) in enumerate(chunks, start=1):
        log.info("-" * 60)
        try:
            rows = fetch_chunk(api_key, d_from, d_to, i, total_chunks)
            grand_rows_fetched += len(rows)
        except RuntimeError as e:
            log.error(f"  GIVING UP on chunk {d_from}..{d_to}: {e}")
            log.error(f"  Continuing. Re-run later to retry.")
            continue

        try:
            ins, upd = load_chunk_to_bq(bq, storage_client, main_table_schema,
                                         rows, ingested_at, d_from, d_to)
            grand_inserted += ins
            grand_updated += upd
        except Exception as e:
            log.error(f"  BQ LOAD FAILED for {d_from}..{d_to}: {type(e).__name__}: {e}")
            log.error(f"  Chunk JSON is cached on disk; re-run to retry just the BQ side.")
            continue

        elapsed_min = (time.monotonic() - overall_start) / 60
        log.info(f"  RUNNING TOTAL: fetched={grand_rows_fetched}, inserted={grand_inserted}, updated={grand_updated}, elapsed={elapsed_min:.1f} min")

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()