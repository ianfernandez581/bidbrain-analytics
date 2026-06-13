# CLAUDE.md — Bidbrain Analytics

Monorepo of self-hosted client marketing dashboards on GCP. One repeatable pattern, many clients:
**MongoDB is the template**; **STT** is the archetype every lean paid-media client is copied from.
**Eight client dashboards are live**, plus a meta **Status dashboard**. The root `README.md` is the
full human map — **this file (CLAUDE.md) is the canonical agent fast-path** and the single source of
truth for fixed facts + deploy commands. **Keep it current: see _Keep this file current_ at the
bottom — updating it is part of finishing a task, not an afterthought.**

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
  subdomain `<c>.bidbrain.ai`.
  (`<c>` ∈ {mongodb, cloudflare, stt, schneider, hireright, cityperfume, resetdata, proptrack})

## What's in the repo (so you don't have to go hunting)
**8 client dashboards** — each is `client_<c>/` with `sql/` + `job/` + `dash/`, dataset `client_<c>`,
job `<c>-export`, service `<c>-dash`. All LIVE and self-gating `*/10`. The non-derivable facts:

| `<c>` | Reports | Currency | Views | Watch out for |
|---|---|---|---|---|
| `mongodb` | TEMPLATE — Trade Desk paid media + Content Syndication (Salesforce, 3 DNB campaigns) | USD | 10 | CS map: Accepted/Rejected/New(=Unresponsive+New). KGA(IDC) campaign dropped from CS pull |
| `cloudflare` | TTD+LinkedIn+Reddit+LINE + CS + 3 single-campaign LinkedIn dashes | USD (LINE JPY→USD@155) | 6 | ONLY client modelled in Snowflake → job lands `src_*`, views are thin pass-throughs; CS map is OPPOSITE of mongodb |
| `stt` | ARCHETYPE — GA4 web traffic vs Google Ads+LinkedIn+DV360 | SGD (USD@1.34) | 24 | `client_Adriatic_Furniture/` is a separate OPEN sample dash — don't copy its no-auth pattern |
| `schneider` | Plan-vs-actual DV360+TTD+LinkedIn (seed tables) | AUD (USD@1.50, SGD@1.15) | 26 | GA4 disabled; 11/21 budgets seeded; FX rates are placeholders |
| `hireright` | Pure delivery DV360+TTD+LinkedIn | USD (AUD@0.65) | 14 | No GA4, no media plan |
| `cityperfume` | E-commerce — Neto `v_sales`=revenue truth + Google/Meta/TTD/GA4 | AUD (no FX) | 36 | Online-only incremental Margin ROAS ~2.6x; **aggregates-only JSON, no PII**; GA4 degraded since ~Oct 2025 |
| `resetdata` | B2B Google Ads+Meta+TTD vs GA4 (leads, **no revenue/ROAS**) | AUD (TTD USD@1.50) | 19 | agency = 100-digital; Meta account filter contains an EN-DASH |
| `proptrack` | Banking ABM — TTD (advertiser `PopTrack`) + LinkedIn | AUD (no FX) | 15 | TTD impressions come from `IMPRESSION` (singular); LinkedIn `PropTrack_TransmissionSG_AUD` |

**4 shared ingest units** fill the `raw_*` layers for everyone (no dashboard of their own):
- `snowflake_data_pull/` → `raw_snowflake` (7 tables, 1:1 mirror). **Self-gating `*/10`** — the exception
  that watermarks BQ `raw_snowflake._sync_state`, not a GCS `_freshness.json` sidecar.
- `windsor_data_pull/` → `raw_windsor` (Meta, Trade Desk, GA4 +events, Google Ads, Reddit). **Fixed daily**
  Cloud Run jobs (`windsor-meta-ingest`, `windsor-tradedesk-ingest`); Reddit not yet wired; TTD connector down.
- `dts_data_pull/` → `raw_google_ads` + `raw_ga4` via **native BigQuery DTS** (no job; daily, free). 3 bridge views.
- `neto_data_pull/` → `raw_neto.orders` (City Perfume sales). **Fixed daily** Cloud Run job `neto-orders-ingest`.

**`status_dashboard/`** — meta dash (`status.bidbrain.ai`), no dataset/views; reads the other clients'
resources, self-gating `*/15`. **`scripts/`** — `setup.ps1`, `start_day.ps1`, `deploy_ingest_jobs.ps1`
(deploys the 4 ingest jobs as `ingest-runner@`). For anything client-specific, open `client_<c>/README.md`.

## Dashboard edits — the common task. READ THIS FIRST.
Each client's UI is ONE big file: `client_<c>/dash/dashboard.html` (~1,300–2,400 lines).

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
something advanced. A job is **not "done"** until it satisfies 1–4.

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

## Keep this file current — definition of done (IMPORTANT)
Updating the docs is part of finishing the work, not an afterthought. **After ANY change, before you
report done, update whatever this change just made stale — in the SAME change.** This file (CLAUDE.md)
is the canonical agent doc; the per-folder `README.md`s carry the detail. Concretely:

- **Changed what a client reports / its currency / view count, or added a client or ingest unit?**
  Fix the row in **What's in the repo** above AND that folder's `README.md`.
- **Changed a deploy step, a script name, or a command?** Fix the matching block in **Redeploy after an
  edit** above — this file is the single source of truth for deploy commands; the READMEs only link here.
- **Changed the freshness mechanism** (gate source, watermark, schedule, `freshness.py` signature)?
  Update the **Freshness contract** above + the client's `job/README.md`.
- **Renamed or added a data key?** The 3-stage contract is matched BY NAME — fix `sql` → `job/main.py` →
  `dashboard.html` in the same change (renaming one stage breaks the next).
- **Hit a non-obvious gotcha** a future session would get wrong? Add ONE terse line to the right place —
  repo-wide here, single-client in `client_<c>/README.md`. **Volatile status (a date, a live URL,
  "verified on…") goes in a README, never in CLAUDE.md** (it rots, and a wrong instruction is worse than none).
- **Found a stale instruction** (a path/command/file that no longer exists)? Fix or delete it now.
- Edit in place and merge into the right section. **Do NOT create new summary / notes / changelog `.md`
  files** to record what you did — the git commit is the changelog. Keep this file lean (≈150 lines);
  push depth into the folder READMEs and link to them rather than inlining it here.

> Doc home, decided 2026-06-13: **CLAUDE.md is canonical** because Claude Code reads it natively (it does
> NOT read `AGENTS.md`). If a non-Claude agent (Cursor/Codex/Copilot) ever works this repo, move the
> shared rules into `AGENTS.md` and make `CLAUDE.md` a one-line `@AGENTS.md` pointer — do not symlink on
> Windows, and never keep two copies of the same prose.