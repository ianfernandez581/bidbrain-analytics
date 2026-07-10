"""
Gmail -> GCS (-> BigQuery) intake job.

Purpose
-------
Schneider forwards their scheduled GA4 report emails (CSV attachments) to a
dedicated mailbox (schneiderreports01@gmail.com). This Cloud Run job:

  1. Logs into that mailbox with a stored OAuth token (Gmail API).
  2. Finds UNREAD messages that carry an allowed attachment (the GA4 CSVs).
  3. Archives every attachment into a private GCS bucket, organised by date.
  4. Best-effort parses each CSV and appends it to a BigQuery raw table.
  5. Marks a message read ONLY once its attachments are safely in GCS, so a
     failed run simply retries next tick and nothing is ever lost.

It is generic + config-driven (env vars) so other clients can reuse it; Schneider
is just the first consumer. Runs on a Cloud Scheduler tick (default every 2h),
mirroring the "check every 2 hours" cadence already used for Teams->ClickUp.

Design notes
------------
* No Cloud Functions in this repo - everything is Cloud Run jobs + Scheduler, so
  this is a job too (deploy_job.ps1).
* The OAuth token lives in Secret Manager (schneider-gmail-oauth), never on disk
  or in git - same convention as windsor-api-key / snowflake-bq-key.
* Self-gating is inherent: the Gmail `is:unread` query IS the watermark, and
  "mark read" advances it. No _freshness.json sidecar needed - if there are no
  unread report emails the job exits 0 without touching BigQuery.
* GCS is the durable copy. BigQuery load is best-effort: if it fails, the file is
  still archived and can be reprocessed from GCS. The message is only marked read
  once its attachments are safely in GCS.
"""

import base64
import io
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parseaddr

from google.cloud import secretmanager, storage
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ---- Configuration (env vars set on the job by deploy_job.ps1) ----
PROJECT = os.environ.get("PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "bidbrain-analytics")
TOKEN_SECRET = os.environ.get("GMAIL_TOKEN_SECRET", "schneider-gmail-oauth")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "bidbrain-analytics-schneider-intake")
GCS_PREFIX = os.environ.get("GCS_PREFIX", "ga4").strip("/")
GMAIL_QUERY = os.environ.get("GMAIL_QUERY", "is:unread has:attachment")
# Optional: only process mail whose From contains one of these (comma-separated).
# Set this to Schneider's forwarding address once we know it, to ignore any stray mail.
SENDER_ALLOWLIST = [s.strip().lower() for s in os.environ.get("SENDER_ALLOWLIST", "").split(",") if s.strip()]
ALLOWED_EXTENSIONS = tuple(
    e.strip().lower() for e in os.environ.get("ALLOWED_EXTENSIONS", ".csv").split(",") if e.strip()
)
LOAD_TO_BQ = os.environ.get("LOAD_TO_BQ", "true").lower() in ("1", "true", "yes")
BQ_DATASET = os.environ.get("BQ_DATASET", "raw_ga4")
BQ_TABLE = os.environ.get("BQ_TABLE", "schneider_ga4_email")

# gmail.modify = read messages + toggle the UNREAD label. That's all we need.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _gmail_service():
    """Authenticate to Gmail using the OAuth token stored in Secret Manager."""
    sm = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/{TOKEN_SECRET}/versions/latest"
    raw = sm.access_secret_version(name=name).payload.data.decode("utf-8")
    info = json.loads(raw)
    creds = Credentials.from_authorized_user_info(info, scopes=SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Gmail token is invalid and cannot be refreshed - regenerate it "
                "(see README: gen_gmail_token.py) and update the secret."
            )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _walk_parts(payload):
    """Yield every MIME part in a message tree (iterative, handles nesting)."""
    stack = [payload] if payload else []
    while stack:
        p = stack.pop()
        if not p:
            continue
        for child in p.get("parts", []) or []:
            stack.append(child)
        yield p


def _collect_attachments(payload):
    """Return [(filename, attachment_id, inline_data), ...] for allowed attachments."""
    out = []
    for p in _walk_parts(payload):
        filename = p.get("filename")
        if not filename or not filename.lower().endswith(ALLOWED_EXTENSIONS):
            continue
        body = p.get("body", {}) or {}
        out.append((filename, body.get("attachmentId"), body.get("data")))
    return out


def _gcs_path(sender_email, msg_id, filename):
    """intake key: <prefix>/YYYY-MM-DD/<sender>/<msg_id>/<filename>."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe_sender = (sender_email or "unknown").replace("/", "_")
    safe_name = filename.replace("/", "_")
    prefix = f"{GCS_PREFIX}/" if GCS_PREFIX else ""
    return f"{prefix}{today}/{safe_sender}/{msg_id}/{safe_name}"


def _safe_col(name):
    """Make a CSV header a BigQuery-safe column identifier."""
    s = re.sub(r"[^0-9a-zA-Z_]", "_", str(name).strip().lower()).strip("_")
    if not s or s[0].isdigit():
        s = "c_" + s
    return s[:300]


def _load_csv_to_bq(bq, file_bytes, filename, sender_email, subject, msg_id, gcs_path):
    """
    Best-effort parse of a GA4 report CSV -> append to a raw BigQuery table.

    GA4 report CSVs carry '#'-comment preamble lines + blank lines before the
    actual table. `comment="#"` + `skip_blank_lines` handles the common
    single-table export. Multi-table exports (several report cards in one file)
    will need per-report tuning once we see Schneider's first real sample - the
    file is archived in GCS either way, so nothing is lost.
    """
    import pandas as pd  # lazy: keep the no-op tick light
    from google.cloud import bigquery

    df = pd.read_csv(io.BytesIO(file_bytes), comment="#", skip_blank_lines=True)
    if df.empty:
        print(f"  (parsed 0 rows from {filename}; skipping BQ)")
        return

    df.columns = [_safe_col(c) for c in df.columns]
    # Land everything as STRING for a messy report CSV; type it later in sql/40.
    df = df.astype("string")
    df["_source_file"] = gcs_path
    df["_from"] = sender_email
    df["_subject"] = subject
    df["_message_id"] = msg_id
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat()

    table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        autodetect=True,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )
    bq.load_table_from_dataframe(df, table_id, job_config=job_config).result()
    print(f"  loaded {len(df)} row(s) -> {table_id}")


def _mark_read(service, msg_id):
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def process_intake(request=None):
    """Entry point: pull unread report emails -> GCS -> BigQuery, then mark read."""
    service = _gmail_service()
    gcs = storage.Client(project=PROJECT)
    bucket = gcs.bucket(GCS_BUCKET)

    bq = None
    if LOAD_TO_BQ:
        from google.cloud import bigquery  # lazy
        bq = bigquery.Client(project=PROJECT)

    # List all matching messages (paginate).
    resp = service.users().messages().list(userId="me", q=GMAIL_QUERY).execute()
    messages = resp.get("messages", [])
    while resp.get("nextPageToken"):
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=GMAIL_QUERY, pageToken=resp["nextPageToken"])
            .execute()
        )
        messages.extend(resp.get("messages", []))

    if not messages:
        print("No unread report emails to process.")
        return ("No new emails", 200)

    saved_total, msg_done = 0, 0
    for ref in messages:
        msg_id = ref["id"]
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender_email = parseaddr(headers.get("from", ""))[1].lower()
        subject = headers.get("subject", "")

        if SENDER_ALLOWLIST and not any(a in sender_email for a in SENDER_ALLOWLIST):
            print(f"Skip {msg_id}: sender {sender_email!r} not in allowlist.")
            continue

        attachments = _collect_attachments(msg.get("payload", {}))
        if not attachments:
            # Matched has:attachment but nothing of an allowed type - mark read so
            # we don't rescan it forever.
            print(f"Skip {msg_id}: no allowed attachments; marking read.")
            _mark_read(service, msg_id)
            continue

        all_ok = True
        saved_this = 0
        for filename, att_id, inline in attachments:
            try:
                data = inline
                if att_id:
                    att = (
                        service.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=msg_id, id=att_id)
                        .execute()
                    )
                    data = att.get("data")
                if not data:
                    print(f"  ! {filename}: no attachment data")
                    all_ok = False
                    continue

                file_bytes = base64.urlsafe_b64decode(data)
                path = _gcs_path(sender_email, msg_id, filename)
                bucket.blob(path).upload_from_string(file_bytes)
                print(f"  saved gs://{GCS_BUCKET}/{path} ({len(file_bytes)} bytes)")
                saved_this += 1
                saved_total += 1

                if bq is not None:
                    try:
                        _load_csv_to_bq(bq, file_bytes, filename, sender_email, subject, msg_id, path)
                    except Exception as e:  # best-effort; GCS is the durable copy
                        print(f"  ! BQ load failed for {filename}: {e} (archived in GCS, reprocess later)")
            except Exception as e:
                print(f"  ! failed {filename}: {e}")
                all_ok = False

        # Mark read only when every attachment is safely archived.
        if saved_this > 0 and all_ok:
            _mark_read(service, msg_id)
            msg_done += 1
            print(f"  message {msg_id} done ({saved_this} file(s)), marked read.")
        else:
            print(f"  message {msg_id} left UNREAD for retry (saved {saved_this}, ok={all_ok}).")

    summary = f"Processed {msg_done}/{len(messages)} email(s), saved {saved_total} file(s)."
    print(summary)
    return (summary, 200)


if __name__ == "__main__":
    process_intake()
