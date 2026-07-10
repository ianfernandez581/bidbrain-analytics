# ingest/gmail_data_pull — Gmail attachment intake (Schneider GA4)

Pulls report attachments out of a dedicated Gmail mailbox and lands them in
BigQuery, so a client who can't/won't grant us API access can instead **email us
their reports** and still get a live dashboard.

First (and currently only) consumer: **Schneider GA4** — Schneider schedules their
GA4 reports as CSV, forwards them to `schneiderreports01@gmail.com`, and this job
ingests them. It's config-driven (env vars) so other clients can reuse it.

## Flow

```
Schneider GA4 report (scheduled CSV email)
   -> Schneider inbox (has GA4 property access)
   -> auto-forward rule
   -> schneiderreports01@gmail.com
   -> [this job, every 2h]  Gmail API -> GCS archive -> BigQuery raw table
   -> clients/client_schneider/sql/40_stg_ga4.sql (repointed) -> dashboard
```

Why the forwarder: GA4 only sends scheduled reports to addresses that already
have property access, so Schneider sends to their own inbox and forwards on. Our
mailbox needs no GA4 access.

## Pieces

| File | What |
|---|---|
| `main.py` | The job: unread mail -> attachments -> GCS -> BigQuery, then mark read. |
| `gen_gmail_token.py` | One-time LOCAL script to mint the Gmail OAuth token. |
| `deploy_job.ps1` | Build + deploy the Cloud Run job + a `*/2h` scheduler. |
| `Dockerfile`, `requirements.txt` | Container. |

## Design

- **Cloud Run job**, not a Cloud Function (this repo has no Functions).
- **Token in Secret Manager** (`schneider-gmail-oauth`), read at runtime — same
  convention as `windsor-api-key`. Never on disk / in git.
- **Self-gating for free:** the Gmail `is:unread` query is the watermark; "mark
  read" advances it. No unread mail -> exits 0 without touching BigQuery. (This is
  why it doesn't use the standard `freshness.py` sidecar — the inbox IS the gate.)
- **Never loses data:** GCS is the durable archive. A message is marked read only
  after its attachments are safely in GCS. BigQuery load is best-effort; if it
  fails the file is still in GCS and can be reprocessed.

## Config (env vars on the job)

| Var | Default | Notes |
|---|---|---|
| `GMAIL_TOKEN_SECRET` | `schneider-gmail-oauth` | Secret Manager secret with the OAuth token JSON. |
| `GCS_BUCKET` | `bidbrain-analytics-schneider-intake` | Archive bucket (private). |
| `GCS_PREFIX` | `ga4` | Key prefix inside the bucket. |
| `GMAIL_QUERY` | `is:unread has:attachment` | Gmail search that selects report mail. |
| `SENDER_ALLOWLIST` | *(empty)* | Comma-sep. Set to Schneider's forwarding address to ignore stray mail. |
| `ALLOWED_EXTENSIONS` | `.csv` | Comma-sep attachment types to keep. |
| `LOAD_TO_BQ` | `true` | Set `false` to archive to GCS only. |
| `BQ_DATASET` / `BQ_TABLE` | `raw_ga4` / `schneider_ga4_email` | Where parsed rows land. |

## One-time setup

1. **OAuth client (console — gcloud can't do this):** enable the Gmail API; set up
   the OAuth consent screen and add `schneiderreports01@gmail.com` as a Test user;
   create an OAuth client ID of type **Desktop app** and download it as
   `client_secret.json` into this folder.
2. **Mint the token (local):**
   ```
   ..\..\.venv\Scripts\python.exe gen_gmail_token.py
   ```
   A browser opens — log in **as schneiderreports01@gmail.com** and approve.
3. **Store it in Secret Manager, then delete the local copies:**
   ```
   gcloud secrets create schneider-gmail-oauth --project bidbrain-analytics --data-file=token.json
   del token.json client_secret.json
   ```
4. **Deploy:**
   ```
   .\deploy_job.ps1
   ```
5. **Test end to end:** forward a sample GA4 CSV into the mailbox, then
   ```
   gcloud run jobs execute gmail-ga4-ingest --region australia-southeast1 --project bidbrain-analytics
   ```
   and check `gs://bidbrain-analytics-schneider-intake/ga4/...` and
   `raw_ga4.schneider_ga4_email`.

> **Token lifetime gotcha:** consumer-Gmail OAuth refresh tokens expire after 7
> days while the OAuth consent screen is in **Testing**. Publish the app (consent
> screen -> "Publish app") to get a long-lived refresh token. If the job ever
> errors with an invalid-token message, re-run steps 2–3.

## Still TODO (needs a real sample)

- `main.py._load_csv_to_bq` handles the common **single-table** GA4 CSV (skips the
  `#` preamble). Confirm/adjust against Schneider's **first real export** — GA4 can
  put several report cards in one CSV.
- Repoint `clients/client_schneider/sql/40_stg_ga4.sql` from its placeholder
  Snowflake source to `raw_ga4.schneider_ga4_email`, then wire the `41–46` GA4
  arrays into `clients/client_schneider/job/main.py` and render in the dashboard.
  (The GA4 view scaffold already exists there, shipped disabled.)
