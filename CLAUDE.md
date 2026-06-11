# CLAUDE.md — Bidbrain Analytics

Monorepo of self-hosted client marketing dashboards on GCP. One repeatable pattern,
many clients: **MongoDB is the template**; **Cloudflare** and **STT** are copies of it.
The root `README.md` is the full map — this file is the fast-path for the edits we do most.

**`status_dashboard/`** is the odd one out: a *meta* dashboard (status.bidbrain.ai) that monitors
all Snowflake-sourced clients — proves whether a stale dashboard is Transmission's fault (Snowflake
source not updating) or 100% Digital's (our pipeline behind), and that each dashboard number equals
Snowflake. Same serving pattern, but no dataset/views; service `status-dash`, job `status-export`,
bucket `bidbrain-analytics-status-dash`, SA `status-dash-job@` (needs `snowflake-bq-key` + objectViewer
on every client bucket). See `status_dashboard/README.md`.

## Fixed facts (memorize; never re-derive)
- GCP project: `bidbrain-analytics` (project # 516554645957)
- Region: `australia-southeast1` — **EVERYTHING**, never another region.
- Artifact Registry docker repo: `bidbrain` (shared by all clients)
- Local dev: Windows + PowerShell. Use the repo venv: `.\.venv\Scripts\python.exe`
- Per client `<c>` everything derives from the key: dataset `client_<c>`,
  bucket `bidbrain-analytics-<c>-dash`, export job `<c>-export`, web service `<c>-dash`,
  subdomain `<c>.bidbrain.ai`. (`<c>` ∈ {mongodb, cloudflare, stt})

## Dashboard edits — the common task. READ THIS FIRST.
Each client's UI is ONE big file: `client_<c>/dash/dashboard.html` (~1,300–1,700 lines).

- **Do NOT read, reformat, or edit the logo blocks.** They are static, enormous, and never
  change: a wall of `<svg … aria-label="…"><path …></svg>` (STT, MongoDB) or an inline
  `<img src="data:image/jpeg;base64,…">` (Cloudflare). The STT logo SVG is **duplicated** in
  `client_STT/dash/main.py` (LOGIN_HTML) — same rule there.
- **grep to the target** (a chart canvas `id`, a KPI element `id`, a render function name)
  and edit in place. Don't slurp the whole file to change a colour/label/card.
- Pure visual tweaks (colours, labels, spacing, a new card) live entirely in `dashboard.html`.
  Colours are CSS vars in `:root` at the top.

## The data contract — when an edit needs NEW data, not just layout
A value on screen traces through three files, matched **by name**:

    sql/*.sql view column  →  job/main.py (the env={…} dict key)  →  dashboard.html (data.* key)

So "add metric X" is usually three edits: surface it in the right `sql/*.sql` view, expose it
in `job/main.py`, THEN render it in `dashboard.html`. Editing only the HTML renders nothing.
Renaming a key anywhere breaks the next stage — fix both ends.

## Redeploy after an edit — manual. Do NOT use cloudbuild from a laptop.
`gcloud builds submit --config .../cloudbuild.yaml` FAILS from a laptop
(`iam.serviceaccounts.actAs` — Cloud Build's SA can't act as the runtime SA). Those configs
are for a future push-to-main trigger. Build the image, deploy as yourself.

**Prefer the per-stage scripts** — each now lives in the stage subfolder it deploys and wraps
exactly the commands below (self-contained, paths resolve from `$PSScriptRoot`, idempotent).
Reach for the matching one by edit:
- `dash/deploy_dash_<c>.ps1`   — edited `dash/dashboard.html` or `dash/main.py` → rebuild + update SERVICE
- `job/deploy_job_<c>.ps1`     — edited `job/main.py` (JSON shape) → rebuild + deploy + run JOB
- `sql/deploy_views_<c>.ps1`   — edited a `sql/*.sql` view → reapply views (`create_views.py`) + run JOB

The one-shot `deploy_<c>.ps1` (still at the `client_<c>/` root) is only for first-time standup (APIs, SAs, IAM, secrets,
scheduler). The raw commands each stage script runs, for reference:

    # edited dashboard.html or dash/main.py → rebuild + redeploy the SERVICE:
    $IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/<c>-dash:$(git rev-parse --short HEAD)"
    gcloud builds submit client_<c>/dash --tag $IMG --region australia-southeast1
    gcloud run services update <c>-dash --image $IMG --region australia-southeast1

    # edited a sql/*.sql view → reapply views + re-run the JOB (no service redeploy):
    .\.venv\Scripts\python.exe client_<c>\create_views.py
    gcloud run jobs execute <c>-export --region australia-southeast1 --wait

    # edited job/main.py (the JSON shape) → rebuild + deploy + run the JOB:
    $IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/<c>-export:$(git rev-parse --short HEAD)"
    gcloud builds submit client_<c>/job --tag $IMG --region australia-southeast1
    gcloud run jobs deploy <c>-export --image $IMG --region australia-southeast1 `
      --service-account <c>-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
    gcloud run jobs execute <c>-export --region australia-southeast1 --wait

The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy shows
immediately. The service always reads whatever JSON is currently in the bucket.

## Freshness contract (binding — definition-of-done for every export job + `snowflake_data_pull`)
Every dashboard must refresh **within ~10 min of its upstream data updating**, NOT on a fixed daily
cron. The mechanism is a SELF-GATING job: on a frequent (`*/10` UTC) Cloud Scheduler tick it cheaply
checks whether the upstream it reads has new data and only does the full rebuild + upload when
something advanced. A job is **not "done"** until it satisfies 1–4. (Mirrored in `.claude/CLAUDE.md`.)

1. **Self-gating.** Probe upstream freshness; rebuild + upload ONLY when an upstream object advanced
   past its stored watermark — otherwise exit 0 without pulling or uploading. Honor `FORCE_REBUILD=1`
   to bypass the gate for manual runs.
2. **Gate source = whatever the job READS** (derive from the code, never guess):
   - **Snowflake-direct** (`client_cloudflare`, `snowflake_data_pull`) → probe Snowflake PUBLIC
     `INFORMATION_SCHEMA.TABLES.LAST_ALTERED`. Metadata-only — **no warehouse credits, never resumes
     `APAC_IN_WH`**.
   - **BigQuery-reading** (every other client, via `raw_snowflake` / `raw_windsor` / `raw_ga4` /
     `raw_google_ads` / `raw_neto` mirrors) → probe `__TABLES__.last_modified_time`.
   Never watermark a **VIEW** (its `LAST_ALTERED` only moves on DDL) — watermark the base/mirror
   TABLES the views read.
3. **Watermark** = a tiny JSON sidecar in the client's own GCS bucket (`_freshness.json`).
   `snowflake_data_pull` instead keeps a per-table BQ `raw_snowflake._sync_state` (refresh table T
   iff T advanced). Order matters: **upload first, write watermark second**, so a failed upload
   simply retries next tick.
4. **Schedule** = Cloud Scheduler `*/10 * * * *` UTC (tunable; parameterize the scheduler script). No
   dashboard may hardcode a fixed refresh time in its copy — show `last_updated` (build time) and
   `data_through` (newest upstream `LAST_ALTERED`/`last_modified`, UTC) instead.
5. **New clients inherit this by copying the template:** vendor `freshness.py` into `job/` (add it to
   the Dockerfile `COPY`), set `GATING_TABLES` + `WATERMARK_OBJECT`, add the gate to the top of
   `main()`, write the watermark after a successful upload, and flip the scheduler to `*/10`.

**Helper:** `freshness.py` (vendored per job folder, like `sf_connect`) —
`probe_snowflake_last_altered(cn, names)`, `probe_bq_last_modified(bq, ["dataset.table", …])`,
`read_watermark`/`write_watermark` (GCS sidecar), `is_stale(observed, watermark)`. It does **no heavy
top-level imports**; keep `pandas`/`pyarrow` off the no-op tick's import path (lazy-import on the
rebuild path) so an idle tick stays a light, fast container.

**Cost:** the driver is rebuild WAKE episodes + `APAC_IN_WH`'s 600s auto-suspend idle tail, NOT the
`*/10` polling (metadata probes never resume the warehouse; BQ-reading jobs never touch it). If the
idle tail ever becomes material, an optional dedicated XS export warehouse at `auto_suspend=60s`
would cut it (needs SYSADMIN; do **not** change `APAC_IN_WH`'s shared 600s auto-suspend).

**Static re-seeds** (e.g. `seed_static.py`) change inputs the gate does NOT watch — kick the job once
by hand afterwards: `gcloud run jobs execute <c>-export --region australia-southeast1 --wait`.

## Never
- Never commit secrets/keys (`*.p8`, `*credentials*.json`, `.env`, bare `*_key`). They live in
  Secret Manager + the local `bidbrain-vault/` (gitignored).
- Never make the data JSON public. The private bucket + the Flask password gate IS the security
  model — don't regress to the old public-R2 pattern.
- Never edit views in the BigQuery console. `sql/*.sql` is the source of truth or they drift.