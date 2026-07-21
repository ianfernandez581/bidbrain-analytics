"""
Windsor -> BigQuery loader for LINKEDIN ADS creative-level delivery data.

Lives in:  windsor_data_pull/linkedin/linkedin_loader.py
Runtime artifacts (chunk cache, log, temp NDJSON) -> _run/ next to this script
(anchored to __file__, gitignored), so nothing scatters into the repo root.

Near-copy of reddit_loader.py's skeleton (blended /all endpoint + account prefix, per-account
incremental + backward-walk backfill, staging->MERGE, _MERGE_KEY_COLS single source of truth,
two run modes, --force, FlushingStreamHandler logging, AccountUnavailableError skip) PLUS the
GA4 two-pass merge (ga4_loader.py) -- because LinkedIn has two API limits Reddit didn't:

  1. 20-FIELD CAP. LinkedIn's adAnalytics API rejects a request with >20 fields. We want ~30
     columns, so each chunk is fetched in TWO passes (FIELDS_GROUP_A = delivery + leads +
     conversions, FIELDS_GROUP_B = engagement + video), each <=20 fields, sharing the key dims
     (account_id, campaign_id, creative_id, date). The two responses are merged on
     (account_id, creative_id, date) into one row per grain BEFORE transform/MERGE. Confirmed
     via probe_linkedin_fields.py.
  2. 92-DAY REACH CAP. `approximate_unique_impressions` (reach) is only available for windows
     <= 92 days. CHUNK_DAYS=30 keeps every request comfortably under it.

Two more LinkedIn realities (probe-confirmed):
  3. campaign_group_id comes back ALL NULL on /all; the group NAME populates. We store
     campaign_group_name and OMIT the id.
  4. Some accounts hard-fail server-side. One account (502299829) returns HTTP 500 "'start'"
     for EVERY request (a Windsor bug -- a campaign missing a start date breaks its adAnalytics
     pull); another can return 500 "Response ended prematurely" on a large window. The 'start'
     failure is treated like "account not available" (skipped per-account, logged loudly);
     "prematurely" is treated as transient (retried -- smaller CHUNK_DAYS avoids it).

Grain: one row per
    (account_id x creative_id x metric_date)
campaign_id / campaign_name / campaign_group_name / campaign_type / objective_type /
campaign_status / creative_status / landing_page / share_title ride along as ATTRIBUTES
(in _MERGE_SET_COLS, not the key) -- functionally determined by creative_id.

MERGE key (see _MERGE_KEY_COLS -- the single source of truth for both the staging dedup and
the SQL ON clause):
    account_id + creative_id + metric_date
account_id / creative_id coalesced to '(not set)' so the key is never NULL.

FIELD-NAME / FORMAT (confirmed via probe_linkedin_fields.py):
  * Blended `/all` endpoint with the `linkedin__` account prefix (NOT a dedicated /linkedin
    connector -- though that also works). Windsor returns account_id BARE (510177932).
  * `campaign` is the campaign NAME (there is no separate campaign_name field); stored as campaign_name.
  * spend is in the account's NATIVE currency (`currency`, AUD/SGD/USD across accounts) -- NOT USD.
    We store `currency` so client views can FX.
  * account_key normalises to DIGITS (LinkedIn ids are numeric) -- unlike Reddit's alphanumeric ids.

METRICS: ADDITIVE BASE ONLY -- impressions, clicks, spend, reach, landing_page_clicks,
engagement counts, lead-gen form counts (one_click_leads / lead_form_opens), the site-conversion
split, and the video funnel. CTR / CPC / CPM / CPL / *_rate / frequency are derived in client
SQL, NEVER stored. ONE cost field (spend); totalcost ignored. Site conversions are NUMERIC
(LinkedIn can report modeled/fractional); lead-form counts + engagement + video are INT64.

Writes the EXISTING perf_linkedin table (created by create_linkedin_table.py) -- run that once
first. This loader does not create or alter the table; it reads the live schema at runtime so
staging/MERGE can't drift from it.

MODES (identical to reddit_loader.py)
-------------------------------------
1. INCREMENTAL PER-ACCOUNT (no date args) -- normal / scheduled. For each account in
   SELECT_ACCOUNTS it looks up MAX(metric_date) in BigQuery:
     * has data -> forward-loads from (last day - INCREMENTAL_LOOKBACK_DAYS) to yesterday
                   (re-pulled boundary days recapture late-attributed leads/conversions;
                   staging + MERGE dedup), then resumes the backward backfill below the earliest day.
     * no data  -> full backfill via backward walk from yesterday until STOP_AFTER_EMPTY_CHUNKS
                   consecutive empty chunks (or MIN_DATE).

       python windsor_data_pull/linkedin/linkedin_loader.py

2. FIXED RANGE (two date args) -- all accounts together, targeted re-pull.

       python windsor_data_pull/linkedin/linkedin_loader.py 2026-05-25 2026-05-30

--force re-fetches even cached chunks (MERGE is idempotent on the key).

RETRIES: transient errors (timeouts, 429, 5xx incl. "Response ended prematurely") retried with
capped backoff up to MAX_ATTEMPTS, then the chunk fails loudly; permanent 4xx (bad field / auth)
fails fast with the response body. A Windsor 400 "not available" OR 500 "'start'" is raised as
AccountUnavailableError and SKIPPED per-account so one broken account never aborts the run.
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
MAIN_TABLE = "perf_linkedin"
STAGING_TABLE = "perf_linkedin_staging"
GCS_BUCKET = "bidbrain-analytics-staging"

# Blended /all endpoint + the `linkedin__` account prefix (applied at request time, Meta/Reddit
# style). Bare numeric ids in SELECT_ACCOUNTS; the prefix is added when building the request.
WINDSOR_URL = "https://connectors.windsor.ai/all"
ACCOUNT_PREFIX = "linkedin__"
SELECT_ACCOUNTS = [
    "502299829",   # BROKEN in Windsor (HTTP 500 "'start'"); skipped every run until Windsor fixes it.
    "504047196", "504606769", "504758918", "507224127", "507877947",
    "508673116", "508732444", "508766215", "508768204", "508768205", "508801607",
    "509003962", "509046900", "509091286", "509841591", "510177932", "510202977",
    "511313581", "511609128", "512344932", "512350710", "512810387", "513554482",
    "515691430", "516221072", "516746102", "516748074", "517045062", "517047078",
    "520254094", "547920275", "547920277", "547960230",
    # The full set granted on the 2026-07 LinkedIn connector. Add ids here AND (optionally) map
    # them in LINKEDIN_ACCOUNT_TO_CLIENT below. Find ids at https://onboard.windsor.ai?datasource=linkedin.
]

# --- Field groups (LinkedIn 20-field/request cap => two passes, shared key dims) ---
# Pass A: identity + delivery + lead-gen + site conversions (20 fields).
# `campaign` is the campaign NAME; `approximate_unique_impressions` is reach (<=92-day windows).
FIELDS_GROUP_A = (
    "account_id,account_name,currency,"
    "campaign_group_name,campaign_id,campaign,creative_id,"
    "campaign_type,objective_type,date,"
    "impressions,clicks,spend,approximate_unique_impressions,landingpageclicks,"
    "oneclickleads,oneclickleadformopens,"
    "externalwebsiteconversions,externalwebsitepostclickconversions,externalwebsitepostviewconversions"
)
# Pass B: shared key dims + creative attributes + engagement + video (19 fields).
FIELDS_GROUP_B = (
    "account_id,campaign_id,creative_id,date,"
    "campaign_status,creative_status,landing_page,share_title,"
    "engagements,likes,comments,shares,follows,"
    "video_views,video_starts,video_completions,quartile_1,quartile_2,quartile_3"
)

CHUNK_DAYS = 30            # creative x date over <=30 days: light per request; dodges the
                           # 500 "Response ended prematurely" seen on 90-day pulls for big accounts.
STOP_AFTER_EMPTY_CHUNKS = 5
MIN_DATE = date(2015, 1, 1)
# High-cardinality accounts (e.g. Cloudflare: ~3800 creative-rows / 30 days) can take Windsor
# ~400s to GENERATE the response, then serve it fast on the next attempt -- so give a single
# attempt a generous window before the (working) backoff-retry kicks in.
TIMEOUT_SEC = 300
RETRY_SLEEP_BASE = 5
RETRY_SLEEP_MAX = 60
MAX_ATTEMPTS = 30          # per-chunk retry cap; then fail loudly instead of hanging forever
INTER_CHUNK_SLEEP = 1
# LinkedIn lead-gen leads + pixel site-conversions settle as they're attributed, so re-pull a
# trailing 7 days each incremental run (staging + MERGE dedup). For deep reconciliation of a
# long conversion window, periodically run a fixed-range re-pull (the two-date-arg mode).
INCREMENTAL_LOOKBACK_DAYS = 7

# All runtime artifacts live under _run/ next to THIS script (not the cwd).
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "_run"
WORK_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR = WORK_DIR / "chunks"
LOG_FILE = WORK_DIR / "linkedin_loader.log"

# Map a LinkedIn account id straight to (client_slug, agency_slug). Checked FIRST in infer_slugs
# -- most reliable. Names confirmed via probe + raw_snowflake.linkedin_ads_apac cross-reference.
# NOTE: MongoDB's account is NOT yet identified (its AWS Immersion Day Q3 campaign had no
# delivery data at build time, and the one unreadable account 502299829 could not be probed) --
# but the campaign name starts 'MONGODB_', so the campaign-name keyword fallback below tags it
# correctly to ('mongodb','transmission') the moment any MongoDB row lands, whatever account it's in.
LINKEDIN_ACCOUNT_TO_CLIENT = {
    "517045062": ("schneider", "transmission"),   # SchneiderElectric_TransmissionSG_AUD
    "504047196": ("schneider", "transmission"),   # SchneiderElectric_TransmissionSG_USD
    "516221072": ("schneider", "transmission"),   # SchneiderElectric_TransmissionSG_SGD
    "515691430": ("stt", "transmission"),         # APAC - STT GDC - SGD
    "511609128": ("stt", "transmission"),         # STTGDC_TransmissionSG_USD
    "510177932": ("proptrack", "transmission"),   # PropTrack_TransmissionSG_AUD
    "513554482": ("hireright", "transmission"),   # HireRight_TransmissionSG_USD
    "520254094": ("cloudflare", "transmission"),  # Cloudflare APAC
    "516746102": ("resetdata", "100-digital"),    # ResetData (100-digital client)
    # 507877947 = 'APJC' (Cisco APJC) -- real spend but not one of our dashboards; left unmapped
    #             (-> slug 'apjc', agency 'unknown'). 502299829 = BROKEN (unreadable), unmapped.
}

# Fallback keyword match on account name / campaign name (lowercased). MongoDB is caught here via
# its 'MONGODB_' campaign prefix regardless of account id. Keep in lockstep as clients are added.
CLIENT_TO_AGENCY = {
    "mongodb": "transmission",
    "schneider": "transmission",
    "proptrack": "transmission",
    "hireright": "transmission",
    "cloudflare": "transmission",
    "stt": "transmission",
    "canon": "transmission",
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
log = logging.getLogger("linkedin_loader")

# ---------- Helpers ----------
def get_secret(name):
    """Read the latest version of a Secret Manager secret via Application Default Credentials --
    same ADC the BigQuery/Storage clients use. Runs identically locally (after
    `gcloud auth application-default login`) and on Cloud Run/Build."""
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
    override = LINKEDIN_ACCOUNT_TO_CLIENT.get(str(row.get("account_id") or ""))
    if override:
        return override
    # 2) keyword match on account name / campaign name (raw Windsor fields)
    haystack = " ".join(str(row.get(k) or "").lower() for k in ("account_name", "campaign"))
    for keyword, agency in CLIENT_TO_AGENCY.items():
        if keyword in haystack:
            return keyword, agency
    return slugify(row.get("account_name") or "unknown"), "unknown"

def account_key(connector_or_id):
    """Stable key for matching SELECT_ACCOUNTS against the account_id stored in BigQuery.
    LinkedIn account ids are NUMERIC, so digit-strip normalisation is safe (unlike Reddit's
    alphanumeric ids). Strips any leading linkedin__ prefix implicitly via \\D removal."""
    return re.sub(r"\D", "", str(connector_or_id or ""))

def date_bounds_per_account(bq):
    """(MIN, MAX) metric_date per account_id in the main table. Absent if no rows. MAX drives the
    forward incremental window; MIN lets the backfill RESUME from below the earliest day we have."""
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

def chunk_filename(d_from, d_to, cache_tag, group):
    return CHUNKS_DIR / f"{cache_tag}_{group}_{d_from.isoformat()}_to_{d_to.isoformat()}.json"

class AccountUnavailableError(Exception):
    """Windsor returned a permanent per-account error (400 'not available' = not granted/wrong
    id/revoked, OR 500 "'start'" = a campaign missing a start date breaks its adAnalytics pull).
    Not retryable, but skippable: per-account runs catch this and move on so one broken account
    never aborts the whole loader."""


def fetch_chunk(api_key, d_from, d_to, idx, total, select_accounts, cache_tag, fields, group, force=False):
    """Fetch one metric-group pass from /all with the linkedin__ prefix applied per account.
    Retries transient errors (incl. 500 'Response ended prematurely'); raises
    AccountUnavailableError for a 400 'not available' or 500 "'start'"; fails fast on other 4xx."""
    label = f"chunk {idx}/{total}" if total else f"chunk {idx}"
    label = f"{cache_tag} {label} [{group}]"
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
            # A 500 can be a hard per-account data bug ("'start'") OR a transient size/timeout
            # ("Response ended prematurely"). Inspect the body BEFORE raise_for_status so we can
            # route them differently.
            if r.status_code == 500:
                body = r.text[:500]
                low = body.lower()
                if "'start'" in body or '"start"' in low:
                    raise AccountUnavailableError(
                        f"Account(s) {accounts}: Windsor 500 \"'start'\" -- a campaign missing a "
                        f"start date breaks its adAnalytics pull (Windsor-side bug). Body:\n{body}")
                # else fall through to the transient retry path below
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
            body = (e.response.text[:500] if e.response is not None else "")
            if status == 400 and "not available" in body.lower():
                raise AccountUnavailableError(
                    f"Account(s) {accounts} not available in Windsor. Body:\n{body}")
            if status == 429 or (status is not None and status >= 500):
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"Chunk {d_from}..{d_to} [{group}]: gave up after {attempt} attempts "
                        f"on transient HTTP {status} (Windsor still failing). Body:\n{body}")
                sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
                log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} transient HTTP {status}; retrying in {sleep}s")
                time.sleep(sleep)
                continue
            raise RuntimeError(
                f"Chunk {d_from}..{d_to} [{group}] got permanent HTTP {status}. This will NOT "
                f"recover by retrying -- likely a bad field name, auth, or account prefix. Sent "
                f"fields:\n{fields}\nBody:\n{body}")
        except AccountUnavailableError:
            raise
        except requests.exceptions.RequestException as e:
            if attempt >= MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Chunk {d_from}..{d_to} [{group}]: gave up after {attempt} attempts "
                    f"({type(e).__name__}: {e}).")
            sleep = min(RETRY_SLEEP_BASE * attempt, RETRY_SLEEP_MAX)
            log.warning(f"    attempt {attempt}/{MAX_ATTEMPTS} FAILED ({type(e).__name__}); retrying in {sleep}s")
            time.sleep(sleep)

def _dim_key(row):
    """Raw-row key for merging the two metric-group passes -- the logical grain
    (account x creative x date). Final post-coalesce dedup happens in dedup_by_merge_key."""
    g = row.get
    return (g("account_id"), g("creative_id"), g("date"))

def merge_metric_groups(rows_a, rows_b):
    """Merge the two metric-group responses into one row per (account, creative, date). Pass A
    (delivery) is the superset at this grain; pass B (engagement/video) may omit a creative-day
    with zero engagement -- those metrics default to 0 in transform. Keyed on the grain so A + B
    metrics land on the same row; B's attribute columns (campaign_status/creative_status/
    landing_page/share_title) join in via dict.update."""
    by_key = {}
    for r in rows_a:
        by_key[_dim_key(r)] = dict(r)
    for r in rows_b:
        k = _dim_key(r)
        if k in by_key:
            by_key[k].update(r)
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
    """Windsor 'date' is usually YYYY-MM-DD; accept YYYYMMDD too. BQ DATE load needs YYYY-MM-DD."""
    if not v: return None
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]

def transform(row, ingested_at_iso):
    g = row.get
    acct = g("account_id") or "(not set)"
    creative = g("creative_id") or "(not set)"
    client_slug, agency_slug = infer_slugs(row)
    return {
        "platform": "linkedin",
        "account_id": acct,
        "account_name": g("account_name"),
        "currency": g("currency"),
        "campaign_group_name": g("campaign_group_name"),
        "campaign_id": g("campaign_id"),
        "campaign_name": g("campaign"),
        "campaign_type": g("campaign_type"),
        "objective_type": g("objective_type"),
        "campaign_status": g("campaign_status"),
        "creative_id": creative,
        "creative_status": g("creative_status"),
        "landing_page": g("landing_page"),
        "share_title": g("share_title"),
        "client_slug": client_slug,
        "agency_slug": agency_slug,
        "metric_date": to_date_iso(g("date")),
        # Delivery: additive base. impressions/clicks/spend always present -> default 0;
        # reach stays NULL-able (non-additive, partial from Windsor).
        "impressions": to_int(g("impressions")) or 0,
        "clicks": to_int(g("clicks")) or 0,
        "spend": to_num(g("spend")) or 0,
        "reach": to_int(g("approximate_unique_impressions")),
        "landing_page_clicks": to_int(g("landingpageclicks")),
        # Engagement (counts).
        "engagements": to_int(g("engagements")),
        "likes": to_int(g("likes")),
        "comments": to_int(g("comments")),
        "shares": to_int(g("shares")),
        "follows": to_int(g("follows")),
        # Lead-gen forms (counts).
        "one_click_leads": to_int(g("oneclickleads")),
        "lead_form_opens": to_int(g("oneclickleadformopens")),
        # Site conversions (NUMERIC -- LinkedIn can report modeled/fractional).
        "ext_website_conversions": to_num(g("externalwebsiteconversions")),
        "ext_website_post_click_conversions": to_num(g("externalwebsitepostclickconversions")),
        "ext_website_post_view_conversions": to_num(g("externalwebsitepostviewconversions")),
        # Video funnel (counts).
        "video_views": to_int(g("video_views")),
        "video_starts": to_int(g("video_starts")),
        "video_completions": to_int(g("video_completions")),
        "video_q25": to_int(g("quartile_1")),
        "video_q50": to_int(g("quartile_2")),
        "video_q75": to_int(g("quartile_3")),
        "ingested_at": ingested_at_iso,
        "source": "windsor.linkedin",
        "raw_row": json.dumps(row),
    }

# Single source of truth for the grain. Drives BOTH the staging dedup and the SQL MERGE ON
# clause, so they can never drift apart. campaign / creative attributes are NOT in the key.
_MERGE_KEY_COLS = ["account_id", "creative_id", "metric_date"]

# Non-key columns updated on MERGE match (everything that isn't a key column).
_MERGE_SET_COLS = [
    "platform", "account_name", "currency",
    "campaign_group_name", "campaign_id", "campaign_name", "campaign_type", "objective_type",
    "campaign_status", "creative_status", "landing_page", "share_title",
    "client_slug", "agency_slug",
    "impressions", "clicks", "spend", "reach", "landing_page_clicks",
    "engagements", "likes", "comments", "shares", "follows",
    "one_click_leads", "lead_form_opens",
    "ext_website_conversions", "ext_website_post_click_conversions", "ext_website_post_view_conversions",
    "video_views", "video_starts", "video_completions", "video_q25", "video_q50", "video_q75",
    "ingested_at", "source", "raw_row",
]

def dedup_by_merge_key(rows):
    """Guarantee exactly one row per MERGE key in the staging load. BigQuery MERGE errors if >1
    source row matches a target row. Last occurrence wins -- consistent with the MERGE's UPDATE."""
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

    gcs_path = f"loads/linkedin/{d_from.isoformat()}_to_{d_to.isoformat()}_{run_id}.ndjson"
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
        log.info(f"LINKEDIN LOADER START (fixed range): {start_d} to {end_d}{'  (FORCE)' if force else ''}")
    else:
        end_d = date.today() - timedelta(days=1)
        log.info(f"LINKEDIN LOADER START (incremental per-account): refresh each account "
                 f"from its last BQ day (lookback {INCREMENTAL_LOOKBACK_DAYS}d) up to {end_d}; "
                 f"accounts with no data get a full backward-walk backfill"
                 f"{'  (FORCE)' if force else ''}")
    log.info(f"Artifacts dir: {WORK_DIR}")
    log.info(f"Accounts: {len(SELECT_ACCOUNTS)} | chunk size: {CHUNK_DAYS}d | 2 metric passes/chunk")
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
            ins, upd = load_chunk_to_bq(bq, storage_client, schema, rows, ingested_at, d_from, d_to)
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
        log.info(f"Forward-loading {start_d}..{end_d} (per-account, so a broken account is skipped)")
        skipped = []
        for account in SELECT_ACCOUNTS:
            key = account_key(account)
            log.info("=" * 60)
            log.info(f"ACCOUNT {account}: fixed range {start_d}..{end_d}")
            try:
                process_forward_range(start_d, end_d, [account], key)
            except AccountUnavailableError as e:
                log.warning(f"SKIPPING account {account}: {e}")
                skipped.append(account)
        if skipped:
            log.warning(f"{len(skipped)} account(s) skipped (broken/unavailable in Windsor): {', '.join(skipped)}")
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
                    start = last - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
                    if start < MIN_DATE:
                        start = MIN_DATE
                    if start > end_d:
                        start = end_d
                    log.info(f"ACCOUNT {account}: last BQ day {last} -> incremental {start}..{end_d}")
                    process_forward_range(start, end_d, [account], key)
                    if first is not None and first > MIN_DATE:
                        log.info(f"ACCOUNT {account}: earliest BQ day {first} -> resume backward fill below it")
                        process_backward_walk(first - timedelta(days=1), [account], key)
            except AccountUnavailableError as e:
                log.warning(f"SKIPPING account {account}: {e}")
                skipped.append(account)
        if skipped:
            log.warning(f"{len(skipped)} account(s) skipped (broken/unavailable in Windsor): {', '.join(skipped)}")

    overall = (time.monotonic() - overall_start) / 60
    log.info("=" * 60)
    log.info(f"LINKEDIN LOADER DONE in {overall:.1f} min")
    log.info(f"  Rows fetched:  {grand_rows_fetched}")
    log.info(f"  Rows inserted: {grand_inserted}")
    log.info(f"  Rows updated:  {grand_updated}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
