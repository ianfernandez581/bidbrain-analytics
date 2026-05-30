"""
Windsor -> BigQuery loader for Meta / Facebook Ads performance data.

Lives in:  windsor_data_pull/meta/meta_loader.py
All runtime artifacts (chunk cache, log, temp NDJSON) are written to _run/
NEXT TO THIS SCRIPT -- anchored to the file, not the working directory -- so
they never scatter into the repo root no matter where you launch from. _run/
is gitignored.

Same per-chunk pipeline as tradedesk_loader.py. Grain: one row per (ad_id x
date). MERGE key = ad_id + metric_date.

TWO MODES
---------
1. BACKWARD WALK (no date args) -- initial backfill when you DON'T know when
   the account started. Walks from yesterday backwards in CHUNK_DAYS windows,
   loading as it goes, until STOP_AFTER_EMPTY_CHUNKS consecutive empty chunks
   (so short activity gaps don't end it early) or the MIN_DATE floor.

       python windsor_data_pull/meta/meta_loader.py

2. FIXED RANGE (two date args) -- daily / targeted runs.

       python windsor_data_pull/meta/meta_loader.py 2026-05-25 2026-05-30

--force re-fetches even cached chunks (MERGE is idempotent on ad_id+date).

RETRIES: transient errors (timeouts, 429, 5xx) retried FOREVER with capped
backoff. Permanent 4xx (bad field / auth) fails fast with the response body.
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
DATASET = "raw_windsor"
MAIN_TABLE = "perf_meta"
STAGING_TABLE = "perf_meta_staging"
GCS_BUCKET = "bidbrain-analytics-staging"

# Blended endpoint + explicit account selection -- matches the URL you proved
# works. Add a client by appending their "facebook__<account_id>" here.
WINDSOR_URL = "https://connectors.windsor.ai/all"
SELECT_ACCOUNTS = [
    "facebook__1126027130805483",
    "facebook__1302148091859257",
    "facebook__3754165911553001",
    "facebook__465058559225771",
    "facebook__910485528634664",
    "facebook__927205350157043",
]

WINDSOR_FIELDS = (
    "account_id,account_name,campaign_id,campaign,objective,"
    "adset_id,adset_name,ad_id,ad_name,effective_status,date,account_currency,"
    "campaign_spend_cap,"
    "impressions,reach,frequency,spend,cpc,cpm,cpp,"
    "clicks,unique_clicks,"
    "link_clicks,actions_link_click,unique_actions_link_click,unique_link_clicks_ctr,"
    "cost_per_action_type_link_click,cost_per_unique_action_type_link_click,"
    "outbound_clicks_outbound_click,unique_outbound_clicks_outbound_click,"
    "outbound_clicks_ctr_outbound_click,unique_outbound_clicks_ctr_outbound_click,"
    "cost_per_outbound_click_outbound_click,cost_per_unique_outbound_click_outbound_click,"
    "actions_post_engagement,unique_actions_post_engagement,actions_page_engagement,"
    "actions_post_reaction,actions_comment,actions_post,"
    "actions_onsite_conversion_post_save,actions_video_view,"
    "estimated_ad_recallers,estimated_ad_recall_rate,instagram_profile_visits,"
    "actions_lead,actions_offsite_conversion_fb_pixel_lead,"
    "actions_onsite_conversion_lead_grouped,unique_actions_lead,cost_per_action_type_lead,"
    "actions_landing_page_view,actions_add_to_cart,actions_initiate_checkout,"
    "actions_omni_purchase,actions_complete_registration,action_values_omni_purchase,"
    "purchase_roas_omni_purchase,website_purchase_roas_offsite_conversion_fb_pixel_purchase,"
    "video_play_actions_video_view,video_p25_watched_actions_video_view,"
    "video_p50_watched_actions_video_view,video_p75_watched_actions_video_view,"
    "video_p95_watched_actions_video_view,video_p100_watched_actions_video_view,"
    "video_thruplay_watched_actions_video_view,video_avg_time_watched_actions_video_view,"
    "quality_ranking,engagement_rate_ranking,conversion_rate_ranking,"
    "creative_id,thumbnail_url,effective_instagram_media__thumbnail_url,"
    "placement_ad_thumbnail_url,title,body,link_url,link,"
    "datasource,source"
)

CHUNK_DAYS = 3
STOP_AFTER_EMPTY_CHUNKS = 5
MIN_DATE = date(2015, 1, 1)
TIMEOUT_SEC = 120
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60
INTER_CHUNK_SLEEP = 1
GCLOUD = r"C:\Users\ianfe\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"

# All runtime artifacts live under _run/ next to THIS script (not the cwd), so
# nothing ever lands in the repo root. _run/ is gitignored.
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "meta_loader.log"

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
log = logging.getLogger("meta_loader")

# ---------- Helpers ----------
def get_secret(name):
    log.info(f"Fetching secret '{name}' from Secret Manager...")
    r = subprocess.run(
        [GCLOUD, "secrets", "versions", "access", "latest",
         "--secret", name, "--project", PROJECT_ID],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gcloud secret fetch failed for '{name}':\n{r.stderr.strip()}")
    val = r.stdout.strip()
    log.info(f"  got secret (length {len(val)})")
    return val

def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"

def infer_slugs(row):
    haystack = " ".join(str(row.get(k) or "").lower() for k in
                        ("account_name", "campaign", "adset_name", "ad_name"))
    for keyword, agency in CLIENT_TO_AGENCY.items():
        if keyword in haystack:
            return keyword, agency
    return slugify(row.get("account_name") or "unknown"), "unknown"

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
        "select_accounts": ",".join(SELECT_ACCOUNTS),
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
                sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
                log.warning(f"    attempt {attempt} transient HTTP {status}; retrying in {sleep}s")
                time.sleep(sleep)
                continue
            body = (e.response.text[:500] if e.response is not None else "")
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} got permanent HTTP {status}. This will NOT "
                f"recover by retrying -- likely a bad field name or auth. Body:\n{body}"
            )
        except requests.exceptions.RequestException as e:
            sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
            log.warning(f"    attempt {attempt} FAILED ({type(e).__name__}); retrying in {sleep}s")
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
        "platform": "meta",
        "account_id": g("account_id"),
        "account_name": g("account_name"),
        "campaign_id": g("campaign_id"),
        "campaign_name": g("campaign"),
        "objective": g("objective"),
        "adset_id": g("adset_id"),
        "adset_name": g("adset_name"),
        "ad_id": g("ad_id"),
        "ad_name": g("ad_name"),
        "effective_status": g("effective_status"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "metric_date": g("date"),
        "currency": g("account_currency"),
        "campaign_spend_cap": to_num(g("campaign_spend_cap")),
        "impressions": to_int(g("impressions")) or 0,
        "reach": to_int(g("reach")),
        "frequency": to_num(g("frequency")),
        "cost": to_num(g("spend")) or 0,
        "cpc": to_num(g("cpc")),
        "cpm": to_num(g("cpm")),
        "cpp": to_num(g("cpp")),
        "clicks": to_int(g("clicks")) or 0,
        "unique_clicks": to_int(g("unique_clicks")),
        "link_clicks": to_int(g("link_clicks")),
        "link_clicks_actions": to_int(g("actions_link_click")),
        "unique_link_clicks": to_int(g("unique_actions_link_click")),
        "unique_link_clicks_ctr": to_num(g("unique_link_clicks_ctr")),
        "cost_per_link_click": to_num(g("cost_per_action_type_link_click")),
        "cost_per_unique_link_click": to_num(g("cost_per_unique_action_type_link_click")),
        "outbound_clicks": to_int(g("outbound_clicks_outbound_click")),
        "unique_outbound_clicks": to_int(g("unique_outbound_clicks_outbound_click")),
        "outbound_ctr": to_num(g("outbound_clicks_ctr_outbound_click")),
        "unique_outbound_ctr": to_num(g("unique_outbound_clicks_ctr_outbound_click")),
        "cost_per_outbound_click": to_num(g("cost_per_outbound_click_outbound_click")),
        "cost_per_unique_outbound_click": to_num(g("cost_per_unique_outbound_click_outbound_click")),
        "post_engagement": to_int(g("actions_post_engagement")),
        "unique_post_engagement": to_int(g("unique_actions_post_engagement")),
        "page_engagement": to_int(g("actions_page_engagement")),
        "reactions": to_int(g("actions_post_reaction")),
        "comments": to_int(g("actions_comment")),
        "shares": to_int(g("actions_post")),
        "saves": to_int(g("actions_onsite_conversion_post_save")),
        "video_3s_views": to_int(g("actions_video_view")),
        "est_ad_recall_lift": to_num(g("estimated_ad_recallers")),
        "est_ad_recall_rate": to_num(g("estimated_ad_recall_rate")),
        "instagram_profile_visits": to_int(g("instagram_profile_visits")),
        "leads": to_int(g("actions_lead")),
        "leads_website": to_int(g("actions_offsite_conversion_fb_pixel_lead")),
        "leads_onfacebook": to_int(g("actions_onsite_conversion_lead_grouped")),
        "unique_leads": to_int(g("unique_actions_lead")),
        "cost_per_lead": to_num(g("cost_per_action_type_lead")),
        "landing_page_views": to_int(g("actions_landing_page_view")),
        "add_to_cart": to_int(g("actions_add_to_cart")),
        "initiate_checkout": to_int(g("actions_initiate_checkout")),
        "purchases": to_int(g("actions_omni_purchase")),
        "registrations": to_int(g("actions_complete_registration")),
        "purchase_value": to_num(g("action_values_omni_purchase")),
        "purchase_roas": to_num(g("purchase_roas_omni_purchase")),
        "purchase_roas_website": to_num(g("website_purchase_roas_offsite_conversion_fb_pixel_purchase")),
        "video_starts": to_int(g("video_play_actions_video_view")),
        "video_25": to_int(g("video_p25_watched_actions_video_view")),
        "video_50": to_int(g("video_p50_watched_actions_video_view")),
        "video_75": to_int(g("video_p75_watched_actions_video_view")),
        "video_95": to_int(g("video_p95_watched_actions_video_view")),
        "video_completes": to_int(g("video_p100_watched_actions_video_view")),
        "thruplays": to_int(g("video_thruplay_watched_actions_video_view")),
        "video_avg_watch_time": to_num(g("video_avg_time_watched_actions_video_view")),
        "quality_ranking": g("quality_ranking"),
        "engagement_rate_ranking": g("engagement_rate_ranking"),
        "conversion_rate_ranking": g("conversion_rate_ranking"),
        "creative_id": g("creative_id"),
        "creative_thumbnail_url": g("thumbnail_url"),
        "ig_thumbnail_url": g("effective_instagram_media__thumbnail_url"),
        "placement_thumbnail_url": g("placement_ad_thumbnail_url"),
        "creative_title": g("title"),
        "creative_body": g("body"),
        "creative_link_url": g("link_url"),
        "destination_url": g("link"),
        "ingested_at": ingested_at_iso,
        "source": "windsor.facebook",
        "raw_row": json.dumps(row),
    }

_MERGE_SET_COLS = [
    "platform","account_id","account_name","campaign_id","campaign_name","objective",
    "adset_id","adset_name","ad_name","effective_status","client_slug","agency_slug",
    "currency","campaign_spend_cap","impressions","reach","frequency","cost","cpc","cpm","cpp",
    "clicks","unique_clicks","link_clicks","link_clicks_actions","unique_link_clicks",
    "unique_link_clicks_ctr","cost_per_link_click","cost_per_unique_link_click",
    "outbound_clicks","unique_outbound_clicks","outbound_ctr","unique_outbound_ctr",
    "cost_per_outbound_click","cost_per_unique_outbound_click","post_engagement",
    "unique_post_engagement","page_engagement","reactions","comments","shares","saves",
    "video_3s_views","est_ad_recall_lift","est_ad_recall_rate","instagram_profile_visits",
    "leads","leads_website","leads_onfacebook","unique_leads","cost_per_lead",
    "landing_page_views","add_to_cart","initiate_checkout","purchases","registrations",
    "purchase_value","purchase_roas","purchase_roas_website","video_starts","video_25",
    "video_50","video_75","video_95","video_completes","thruplays","video_avg_watch_time",
    "quality_ranking","engagement_rate_ranking","conversion_rate_ranking","creative_id",
    "creative_thumbnail_url","ig_thumbnail_url","placement_thumbnail_url","creative_title",
    "creative_body","creative_link_url","destination_url","ingested_at","source","raw_row",
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

    gcs_path = f"loads/meta/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
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
    ON  T.ad_id       = S.ad_id
    AND T.metric_date = S.metric_date
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
        log.info(f"META LOADER START (fixed range): {start_d} to {end_d}{'  (FORCE)' if force else ''}")
    else:
        end_d = date.today() - timedelta(days=1)
        log.info(f"META LOADER START (backward walk): from {end_d} back until "
                 f"{STOP_AFTER_EMPTY_CHUNKS} consecutive empty chunks (floor {MIN_DATE})"
                 f"{'  (FORCE)' if force else ''}")
    log.info(f"Artifacts dir: {WORK_DIR}")
    log.info(f"Accounts: {len(SELECT_ACCOUNTS)} | chunk size: {CHUNK_DAYS}d")
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
    log.info(f"META LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
