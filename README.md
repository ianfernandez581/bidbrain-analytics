# Bidbrain Analytics — Client Reporting Platform

> Secure, self-hosted marketing dashboards for Bidbrain clients, running entirely on Google Cloud.
> **One repository, one repeatable pattern, many client dashboards.**

This README is written to do two jobs at once:

1. **Get anyone up to speed fast** — including an AI assistant (Claude, etc.) handed this repo cold. If that's you, read sections **3, 9, and 10** first.
2. **Be understandable by non-technical people.** Every technical section starts with a plain-English summary, and there's a [Glossary](#14-glossary-plain-english) at the bottom that explains every term.

---

## Quickstart (clone & run)

Everything in the repo is portable — nothing machine-specific is baked into the code. You only need the **gcloud CLI authenticated** as a member of the `bidbrain-analytics` project, with `secretmanager.secretAccessor` on the `windsor-api-key` secret.

**Windows (PowerShell):**
```powershell
git clone https://github.com/Bidbrain/bidbrain-analytics.git
cd bidbrain-analytics
.\scripts\setup.ps1            # one-time: installs Python 3.12 + gcloud if missing, makes .venv, installs deps, logs in
.\scripts\start_day.ps1        # each session: verifies gcloud + ADC creds
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py
```

**macOS / Linux (no setup.ps1 needed — the code is cross-platform):**
```bash
git clone https://github.com/Bidbrain/bidbrain-analytics.git && cd bidbrain-analytics
gcloud auth login && gcloud auth application-default login   # one-time; ADC powers the client libs
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python windsor_data_pull/meta/meta_loader.py
```

Secrets are read at runtime from Secret Manager via Application Default Credentials — no key files, no gcloud-path hardcoding.

---

## Table of contents

1. [What this is (start here — no tech background needed)](#1-what-this-is)
2. [How it works (the 60-second version)](#2-how-it-works)
3. [For an AI or engineer picking this up](#3-for-an-ai-or-engineer-picking-this-up)
4. [Architecture in detail](#4-architecture-in-detail)
5. [Security model — old vs new](#5-security-model)
6. [Repository structure](#6-repository-structure)
7. [GCP resource inventory (exact names)](#7-gcp-resource-inventory)
8. [The data contract (the JSON file the dashboard reads)](#8-the-data-contract)
9. [Conventions & naming rules](#9-conventions--naming-rules)
10. [Playbook: add a new client dashboard](#10-playbook-add-a-new-client-dashboard)
11. [Operating it: deploy, update, run, debug](#11-operating-it)
12. [Gotchas & lessons learned](#12-gotchas--lessons-learned)
13. [Current status & TODO](#13-current-status--todo)
14. [Glossary (plain English)](#14-glossary-plain-english)

---

## 1. What this is

**In one sentence:** this project takes a client's raw marketing data, tidies it up, and serves it as a private, password-protected web dashboard that only the right people can see.

Think of it like a **vending machine for reports**. Behind the scenes, ingredients (raw data) get pulled in, processed into a finished product (a tidy data file), and put behind glass. Out front, a customer has to enter a code (password) before the machine will hand them anything. No code, nothing comes out — and you can't reach around the back to grab the product either.

We built the first one for **MongoDB (APAC)**. The whole point of this repo is that **every future client dashboard follows the exact same pattern**, so building the next one is mostly copy-and-adjust, not start-from-scratch.

Everything lives on **Google Cloud** (one platform), under the GCP project **`bidbrain-analytics`**, in the **Sydney region (`australia-southeast1`)**. The domain stays on Cloudflare (just for DNS — pointing the web address at Google).

---

## 2. How it works

**In plain terms:** data flows left to right, gets locked down at the end, and a person needs a password to see it.

```
  RAW DATA SOURCES                 PROCESS (Google Cloud)                 WHO SEES IT
 ┌────────────────┐
 │ Snowflake      │ ─┐
 │ (ad + lead     │  │     ┌─────────────┐     ┌──────────────┐
 │  data)         │  ├──▶  │  Export Job │ ──▶ │  BigQuery    │ ──┐
 └────────────────┘  │     │ (Cloud Run) │     │ (warehouse)  │   │
 ┌────────────────┐  │     └─────────────┘     └──────────────┘   │
 │ Windsor.ai     │ ─┘            │                               │  builds one
 │ (shared perf)  │               │                               │  tidy file
 └────────────────┘               ▼                               ▼
                          ┌──────────────────┐          ┌────────────────────┐
                          │ Private GCS bucket│ ◀─────── │  mongodb.json      │
                          │ (locked storage)  │          │ (the finished data)│
                          └──────────────────┘          └────────────────────┘
                                   │
                                   │ served ONLY to a logged-in user
                                   ▼
                          ┌──────────────────┐          ┌────────────────────┐
                          │ Dashboard Web App │  ◀────── │  Password screen   │
                          │   (Cloud Run)     │          │  (no password =    │
                          │  mongodb.bidbrain │          │   no access)       │
                          │       .ai         │          └────────────────────┘
                          └──────────────────┘
                                   │
                                   ▼
                              👤 The team / client (after entering the password)
```

**The journey:**

1. Raw data lives in **Snowflake** (each client's ad + lead data) and **Windsor.ai** (shared Trade Desk performance data).
2. A scheduled **Export Job** pulls that data, lands it in **BigQuery** (Google's data warehouse), runs calculations, and packages the result into a single tidy file called `mongodb.json`.
3. That file is saved to a **private** storage bucket — not reachable by anyone on the internet.
4. A small **Web App** shows a password screen. Enter the password and you see the dashboard; the app fetches the data file *on your behalf* from the private bucket. No password → you see nothing, and the data file can't be grabbed directly.
5. It's reachable at a friendly web address (e.g. `mongodb.bidbrain.ai`).

---

## 3. For an AI or engineer picking this up

If you've just been handed this repo and asked to extend it, here's your orientation.

**Fixed facts (memorize these):**

| Thing | Value |
|---|---|
| GCP project | `bidbrain-analytics` (project number `516554645957`) |
| Region (everything) | `australia-southeast1` (Sydney) |
| GitHub repo | `Bidbrain/bidbrain-analytics` (private) |
| Local dev machine | Windows + **PowerShell** (commands below are PowerShell) |
| Secrets store | GCP **Secret Manager** + a local-only folder `bidbrain-vault/` (never in git) |
| Data warehouse | **BigQuery**, layered: shared `raw_*` datasets + per-client `client_*` datasets |
| Dashboard hosting | One **Cloud Run service per client** (a tiny password-gated web app) |
| Data refresh | One **Cloud Run job per client** (pulls data → builds the JSON) |

**To add a new client dashboard:** follow the [Playbook in section 10](#10-playbook-add-a-new-client-dashboard). It generalizes everything we did for MongoDB.

**Golden rules (do not break these):**

- **Never commit secrets.** No private keys, passwords, or API tokens in the repo. They live in Secret Manager (cloud) and `bidbrain-vault/` (local). See [.gitignore](#6-repository-structure).
- **Never make the data file public.** The whole security model depends on the JSON staying in a private bucket, served only by the authenticated web app. (The *old* system exposed it publicly — see [section 5](#5-security-model). Don't regress.)
- **Everything in `australia-southeast1`.** Mixed regions cause "missing resource" confusion and cross-region cost.
- **One client = its own dataset, job, bucket object, web app, password, and subdomain.** Full isolation between clients.

---

## 4. Architecture in detail

### 4.1 The layered data model (BigQuery)

**In plain terms:** we keep each client's data in its own labelled drawer, plus a shared drawer for data that everyone uses.

We use a standard multi-tenant layout:

- **`raw_<source>`** — shared raw data from a single upstream source, used by multiple clients. Example: **`raw_windsor`** holds Trade Desk (`perf_the_trade_desk`) and Meta/Facebook (`perf_meta`) performance data, loaded by the two Windsor loaders in `windsor_data_pull/` (Windsor.ai → BigQuery). Shared data is exposed to client datasets via *authorized views*.
- **`client_<client>`** — one dataset per client, holding everything specific to that client:
  - **`src_*` tables** — raw per-client feeds landed straight from Snowflake (single-consumer, so they live inside the client dataset). Example: `client_mongodb.src_tradedesk`, `client_mongodb.src_salesforce`.
  - **views** — the calculations that shape raw data into dashboard-ready numbers (staging → model → rollups).

For MongoDB, `client_mongodb` contains:

| Object | Type | Purpose |
|---|---|---|
| `src_tradedesk` | table | raw TradeDesk rows pulled from Snowflake (filtered to MongoDB) |
| `src_salesforce` | table | raw Salesforce lead rows (4 campaign IDs: 3 DNB IDE + 1 KGA/IDC) |
| `stg_tradedesk` | view | parses campaign names into programme / market / strategy |
| `stg_salesforce` | view | maps countries to the 4-market bucket, labels programmes (DNB IDE ×3 → `IDE`; KGA campaign `701RG00001NKKwQYAX` → `IDC`) |
| `paid_media_model` | view | unified paid-media delivery model |
| `cs_leads` | view | lead counts by market |
| `cs_leads_by_programme` | view | lead counts by programme × market |
| `targets` | view | lead targets (from a spreadsheet snapshot) |
| `targets_by_programme` | view | target rollups |
| `benchmarks_strategy` | view | CPM/CTR plan benchmarks |
| `benchmarks_market` | view | budget-weight benchmarks per market |
| `budget` | view | programme budget envelopes |

> **Note:** these view definitions still need to be exported from BigQuery into version control. The folder (`client_mongodb/sql/`) and an apply-runner (`infra/create_views.py`) now exist — export the live DDL per [`client_mongodb/sql/README.md`](client_mongodb/sql/README.md) so the data model is fully reproducible. See [TODO](#13-current-status--todo).

### 4.2 The two moving parts: the Job and the Web App

Each client has **two** Cloud Run pieces. They are different things and easy to confuse:

| | **Export Job** (`<client>-export`) | **Web App** (`<client>-dash`) |
|---|---|---|
| Cloud Run type | **Job** (runs, finishes, stops) | **Service** (always-on, answers web requests) |
| What it does | pulls data → BigQuery → builds `<client>.json` → saves to private bucket | shows password screen, serves the dashboard + data to logged-in users |
| When it runs | on a daily schedule (and on demand) | whenever someone visits the URL |
| Source folder | `client_<client>/job/` | `client_<client>/dash/` |
| Talks to | Snowflake + BigQuery + GCS | GCS (read-only) + Secret Manager |

**In plain terms:** the Job is the *kitchen* (makes the dish once a day); the Web App is the *waiter behind a locked door* (checks your password, then brings you the dish).

### 4.3 Storage

- **`bidbrain-analytics-<client>-dash`** — a **private** GCS bucket holding the finished JSON for that client. For MongoDB: `bidbrain-analytics-mongodb-dash`, object `mongodb.json`.
- **`bidbrain-analytics-staging`** — shared bucket used by the Windsor loader.
- Buckets are **private** (no public access). Only the relevant service accounts can read/write them.

### 4.4 Secrets & identities (IAM)

**In plain terms:** every automated piece has its own "ID badge" (service account) with the *minimum* keys it needs, and all passwords/keys are kept in a locked safe (Secret Manager).

**Secrets (in Secret Manager — names only, values never in this repo):**

| Secret | Used by | What it is |
|---|---|---|
| `snowflake-bq-key` | the export job | private key to read Snowflake (key-pair auth) |
| `<client>-dash-password` | the web app | the dashboard password (e.g. `mongodb-dash-password`) |
| `<client>-dash-session-key` | the web app | random key used to sign login sessions |
| `windsor-api-key` | the Windsor loaders (`windsor_data_pull/*`) | API key for Windsor.ai. The identity running the loaders (your ADC locally, or the CI/Cloud Build SA) needs `secretmanager.secretAccessor` on it. |

**Service accounts (the "ID badges"):**

| Service account | Used by | Permissions |
|---|---|---|
| `<client>-dash-job@…` | export job | `secretAccessor` (Snowflake key), `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin` on the client bucket |
| `<client>-dash-web@…` | web app | `storage.objectViewer` on the client bucket, `secretAccessor` on the two dashboard secrets |

(For MongoDB these are `mongodb-dash-job@bidbrain-analytics.iam.gserviceaccount.com` and `mongodb-dash-web@bidbrain-analytics.iam.gserviceaccount.com`.)

### 4.5 The custom domain

**In plain terms:** the friendly web address points at the app; Cloudflare just does the pointing.

- `bidbrain.ai` DNS is hosted on **Cloudflare**. We add one subdomain per client (e.g. `mongodb.bidbrain.ai`).
- Because Cloud Run services answer at an ugly `…run.app` URL and route by hostname, a plain DNS record returns a **404**. The fix is a **Cloudflare "Host Header Override"** (Origin Rule) that rewrites the host to the `…run.app` name. The DNS record is **Proxied (orange cloud)**, SSL mode **Full (strict)**, and Cloudflare provides the HTTPS certificate for free.
- This is **DNS/proxy only** — no compute, no cost beyond the existing Cloudflare plan. (The alternative, a GCP load balancer, costs ~$18/mo and is only worth it at larger scale; documented but not used.)

---

## 5. Security model

**This is the most important section. Read it before changing anything about hosting or data access.**

### The OLD system (legacy, being retired)

The previous dashboards (hosted on Cloudflare, gated by a `dashboards-unlock` Worker) used **security by obscurity**:

- The password screen didn't actually guard the data — it just handed back a hard-to-guess "slug" (a secret URL).
- The dashboard and its **data file sat at a public link** (`pub-….r2.dev/mongodb.json`). Anyone who had the link — or who opened the dashboard once and copied it — could grab the raw data **without any password**.
- The "lock" was really just a hidden address. Hidden ≠ protected.

### The NEW system (this repo)

Real protection, because authentication sits in front of **both** the page and the data:

- The dashboard is a **Cloud Run web app** with a real password check. **No valid password → HTTP 401 → nothing**, not the page and not the data.
- The data file lives in a **private bucket**. The browser never touches it directly. The app reads it server-side (with its own ID badge) and only returns it to a request that already passed the password.
- The app's public `…run.app` URL is harmless: hitting it just shows the password screen.
- Cloudflare is only DNS/proxy.

**Why we disabled Cloud Run's built-in IAM check (`--no-invoker-iam-check`):** the org enforces *Domain Restricted Sharing*, which blocks the usual "allow public" (`allUsers`) setting. Disabling the invoker IAM check is Google's recommended way to make a service publicly reachable under that policy. It's safe here **because our app does its own password auth** — we're removing a duplicate, conflicting gate, not the protection.

### Non-negotiables

- ❌ Never publish the JSON to a public URL or public bucket.
- ❌ Never rely on "the link is hard to guess" as protection.
- ✅ Data is always served by the authenticated app from a private bucket.

---

## 6. Repository structure

```
bidbrain-analytics/                   <- the git repo (== GitHub, nothing secret)
|- README.md                          <- this file
|- .gitignore
|- .gcloudignore                      <- what gcloud must NOT upload on source deploys
|- requirements.txt                   <- deps for the loaders + infra scripts (pinned)
|
|- scripts/                           <- clone-and-run entrypoint (Windows)
|   |- setup.ps1 / setup.cmd          <- one-time machine setup (Python, gcloud, .venv, login)
|   \- start_day.ps1 / start_day.cmd  <- each-session credential preflight
|
|- infra/                             <- one-time BigQuery provisioning (idempotent)
|   |- _config.py                     <- shared PROJECT / LOCATION / RAW_DATASET constants
|   |- create_dataset.py              <- creates the raw_windsor dataset
|   |- create_trade_desk__tables.py   <- creates raw_windsor.perf_the_trade_desk
|   |- create_meta_table.py           <- creates raw_windsor.perf_meta
|   \- create_views.py                <- applies client_mongodb view DDL from sql/
|
|- windsor_data_pull/                 <- Windsor.ai -> BigQuery loaders (fill raw_windsor)
|   |- meta/meta_loader.py            <- Meta/Facebook -> raw_windsor.perf_meta  (incremental per-account; + _run/, gitignored)
|   \- tradedesk/tradedesk_loader.py  <- Trade Desk   -> raw_windsor.perf_the_trade_desk  (+ _run/)
|
|- client_mongodb/                    <- the MongoDB client (template for new clients)
|   |- job/                           <- Export Job (Cloud Run JOB)
|   |   \- main.py, requirements.txt, Dockerfile, cloudbuild.yaml, .dockerignore
|   |- dash/                          <- Web App (Cloud Run SERVICE)
|   |   \- main.py, dashboard.html, requirements.txt, Dockerfile, cloudbuild.yaml, .dockerignore
|   \- sql/                           <- version-controlled BigQuery view DDL (see its README)
|
\- client_cloudflare/                 <- placeholder for the next client (.gitkeep)
```

**Naming convention for new clients:** each client gets a `client_<client>/` folder containing `job/` and `dash/`. The MongoDB build is the template — see the [Playbook](#10-playbook-add-a-new-client-dashboard).

**Lives OUTSIDE the repo (local only, never committed)** — the Snowflake private key, kept in a sibling folder `bidbrain-vault/`:

```
bidbrain-vault/          (NOT in git)
\- keys/                 <- snowflake_bq_key.p8 + .pub (the Snowflake private key)
```

Loader runtime artifacts (cached Windsor chunk JSON, logs, temp NDJSON) live in a `_run/` folder **next to each loader**, anchored to the script via `__file__` — not in a vault, not in the repo root. `.gitignore` covers all of it (`*.p8 *.pem *.key *credentials*.json .env _run/ chunks/ *.log *.ndjson __pycache__ .venv`; see the file for the full list).

**Windsor loader run modes** (both loaders, run with the `.venv` Python):

- **`meta_loader.py` with no args — incremental per-account (the normal/scheduled run).** For each configured Facebook account it reads `MAX(metric_date)` already in `perf_meta` and only fetches forward from there to yesterday (re-pulling the boundary day so Meta's metric revisions are caught — duplicates are absorbed by the staging table + MERGE on `ad_id + metric_date`). An account with **no** rows yet is backfilled from scratch via a backward walk, so adding a new account never re-pulls history for accounts that are already current. Widen the re-pull window for late conversions by setting `INCREMENTAL_LOOKBACK_DAYS` in the script (default `0`).
- **`tradedesk_loader.py` with no args — backward walk.** Auto-discovers how far back data exists, walking from yesterday until several consecutive empty chunks.
- **Either loader with two date args — fixed range**, all accounts together, e.g. `… meta\meta_loader.py 2026-05-25 2026-05-30`. Append `--force` to re-fetch even cached chunks (the MERGE stays idempotent).

---

## 7. GCP resource inventory

Exact names of everything that exists today (project `bidbrain-analytics`, region `australia-southeast1`):

**BigQuery datasets**
- `raw_windsor` — tables `perf_the_trade_desk`, `perf_meta` (shared Windsor data; the `*_staging` tables are transient MERGE scratch)
- `client_mongodb` — tables `src_tradedesk`, `src_salesforce` + the 10 views in [4.1](#41-the-layered-data-model-bigquery)
- `client_cloudflare` — empty (next client)

**Cloud Storage buckets** (both private)
- `bidbrain-analytics-mongodb-dash` — holds `mongodb.json`
- `bidbrain-analytics-staging` — Windsor loader staging

**Secret Manager**
- `snowflake-bq-key`, `mongodb-dash-password`, `mongodb-dash-session-key`, `windsor-api-key`

**Service accounts**
- `mongodb-dash-job@bidbrain-analytics.iam.gserviceaccount.com`
- `mongodb-dash-web@bidbrain-analytics.iam.gserviceaccount.com`

**Cloud Run**
- Job: `mongodb-export`
- Service: `mongodb-dash` (deployed with `--no-invoker-iam-check`)

**Snowflake (read-only source — for the MongoDB pipeline)**
- Account `ZGKGHOH-ISA98947`, warehouse `APAC_IN_WH`
- User `BQ_SYNC_USER`, role `BQ_SYNC_ROLE` (key-pair auth; SELECT on the two source tables)
- Source tables: `APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL"` (filtered to `ADVERTISER_NAME = 'MongoDB'`) and `APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"` (4 campaign IDs: 3 DNB IDE + the KGA/IDC programme `701RG00001NKKwQYAX`, live in Snowflake since May 2026)

**Cloudflare**
- Account `Admin@100.digital`, zone `bidbrain.ai`
- (Legacy, to retire for MongoDB: the `dashboards-unlock` Worker + R2 bucket `cf-apac-dashboard`)

---

## 8. The data contract

**In plain terms:** the dashboard expects the data file to be shaped a very specific way. If you change the shape, you must change the dashboard too.

The export job writes one JSON object (`<client>.json`) with this envelope. The dashboard reads it from `/data.json`:

```jsonc
{
  "last_updated": "2026-05-29T22:00:00Z",  // UTC ISO-8601 (Z-suffixed)
  "row_count": 1234,
  "window": { "start": "2026-04-01", "end": "2026-06-30", "days": 91 },
  "all_markets":    ["ANZ", "ASEAN", "INDIA", "KR-HK-TW"],
  "all_programmes": ["IDE", "IDC"],
  "rows": [ /* per-day paid-media: channel, date, week_start, programme, market, strategy, objective, imps, clicks, spend_usd, conversions, leads */ ],
  "targets": [ /* programme, market, target, delivered */ ],
  "benchmarks_strategy": { /* keyed by strategy: { cpm, ctr, frequency, weight } */ },
  "benchmarks_market":   { /* keyed by market:   { budget_weight } */ },
  "budget": [ /* programme, tradedesk_code, gross_usd, net_usd, start, end */ ],
  "cs": [ /* market, total, accepted, rejected, new_pending, unresponsive, do_not_contact, last_lead_day */ ],
  "cs_by_programme": [ /* programme, market, total, accepted, new_pending, unresponsive, do_not_contact, last_lead_day (note: no 'rejected') */ ]
}
```

The dashboard (`dashboard.html`) is the client's existing design with a **single change**: its data URL is set to `/data.json` (same origin), so the logged-in user's session is automatically used to fetch the data.

---

## 9. Conventions & naming rules

Follow these exactly so every client looks the same.

| Resource | Pattern | MongoDB example |
|---|---|---|
| Client key | lowercase, short | `mongodb` |
| BigQuery dataset | `client_<client>` | `client_mongodb` |
| Shared source dataset | `raw_<source>` | `raw_windsor` |
| Per-client source table | `src_<source>` | `src_tradedesk` |
| Views | `snake_case`, no prefixes | `paid_media_model` |
| GCS bucket | `bidbrain-analytics-<client>-dash` | `bidbrain-analytics-mongodb-dash` |
| Data object | `<client>.json` | `mongodb.json` |
| Export job (Cloud Run job) | `<client>-export` | `mongodb-export` |
| Web app (Cloud Run service) | `<client>-dash` | `mongodb-dash` |
| Job service account | `<client>-dash-job@…` | `mongodb-dash-job@…` |
| Web service account | `<client>-dash-web@…` | `mongodb-dash-web@…` |
| Password secret | `<client>-dash-password` | `mongodb-dash-password` |
| Session secret | `<client>-dash-session-key` | `mongodb-dash-session-key` |
| Subdomain | `<client>.bidbrain.ai` | `mongodb.bidbrain.ai` |
| Repo folders | `client_<client>/job/`, `client_<client>/dash/` | `client_mongodb/job/`, `client_mongodb/dash/` |

Other rules: everything in `australia-southeast1`; `snake_case` for BigQuery objects; secrets only in Secret Manager + `bidbrain-vault/`.

---

## 10. Playbook: add a new client dashboard

This is the reusable recipe. It generalizes the MongoDB build. Replace `acme` with the client key. (Commands are PowerShell.)

> **0. Prereqs:** the client's source data must be reachable — either a Snowflake feed (like MongoDB) or already in `raw_windsor`. Decide the client key and confirm the names from [section 9](#9-conventions--naming-rules).

**1. BigQuery — dataset + views**
- Create `client_acme`.
- Build the `src_*` tables (the export job will populate them) and the views that produce the [JSON envelope](#8-the-data-contract) inputs.
- Port any Snowflake SQL to BigQuery dialect (see [gotchas](#12-gotchas--lessons-learned)).

**2. Private bucket**
```powershell
gcloud storage buckets create gs://bidbrain-analytics-acme-dash --location=australia-southeast1 --uniform-bucket-level-access
```

**3. Service accounts + secrets + permissions**
```powershell
$P="bidbrain-analytics"
gcloud iam service-accounts create acme-dash-job --display-name="ACME export job"
gcloud iam service-accounts create acme-dash-web --display-name="ACME dashboard web app"

# password + session key (prompted / random — never typed into history)
$pw = Read-Host "ACME dashboard password"
$t=New-TemporaryFile; [IO.File]::WriteAllText($t,$pw); gcloud secrets create acme-dash-password --data-file="$t" --replication-policy="automatic"; Remove-Item $t
$k = -join ((1..64)|%{'{0:x}' -f (Get-Random -Max 16)}); $t=New-TemporaryFile; [IO.File]::WriteAllText($t,$k); gcloud secrets create acme-dash-session-key --data-file="$t" --replication-policy="automatic"; Remove-Item $t

# job badge: read Snowflake key, write BigQuery + bucket
gcloud secrets add-iam-policy-binding snowflake-bq-key --member="serviceAccount:acme-dash-job@$P.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding $P --member="serviceAccount:acme-dash-job@$P.iam.gserviceaccount.com" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding $P --member="serviceAccount:acme-dash-job@$P.iam.gserviceaccount.com" --role="roles/bigquery.jobUser"
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-acme-dash --member="serviceAccount:acme-dash-job@$P.iam.gserviceaccount.com" --role="roles/storage.objectAdmin"

# web badge: read bucket + the two dashboard secrets
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-acme-dash --member="serviceAccount:acme-dash-web@$P.iam.gserviceaccount.com" --role="roles/storage.objectViewer"
gcloud secrets add-iam-policy-binding acme-dash-password    --member="serviceAccount:acme-dash-web@$P.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding acme-dash-session-key --member="serviceAccount:acme-dash-web@$P.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

**4. Export job** — copy `client_mongodb/job/` → `client_acme/job/`, adjust the Snowflake queries, the BigQuery dataset, and the JSON assembly. Deploy:
```powershell
cd client_acme/job
gcloud run jobs deploy acme-export --source . --region australia-southeast1 `
  --service-account acme-dash-job@bidbrain-analytics.iam.gserviceaccount.com `
  --set-secrets "SNOWFLAKE_KEY=snowflake-bq-key:latest" `
  --set-env-vars "GCP_PROJECT=bidbrain-analytics,BQ_DATASET=client_acme,GCS_BUCKET=bidbrain-analytics-acme-dash,SF_ACCOUNT=ZGKGHOH-ISA98947,SF_USER=BQ_SYNC_USER,SF_WAREHOUSE=APAC_IN_WH" `
  --memory 1Gi
gcloud run jobs execute acme-export --region australia-southeast1   # run it once; confirm acme.json lands in the bucket
```

**5. Web app** — copy `client_mongodb/dash/` → `client_acme/dash/`, drop in the client's `dashboard.html` (set its data URL to `/data.json`). Deploy + make public + check:
```powershell
cd client_acme/dash
# NOTE: do NOT pass --allow-unauthenticated -- the org's Domain Restricted Sharing
# rejects it (see gotchas, section 12). The app does its own password auth, and the
# services-update below removes the conflicting invoker gate.
gcloud run deploy acme-dash --source . --region australia-southeast1 `
  --service-account acme-dash-web@bidbrain-analytics.iam.gserviceaccount.com `
  --set-env-vars "GCS_BUCKET=bidbrain-analytics-acme-dash,DATA_OBJECT=acme.json" `
  --set-secrets "DASH_PASSWORD=acme-dash-password:latest,SESSION_SECRET=acme-dash-session-key:latest" `
  --memory 512Mi
gcloud run services update acme-dash --region=australia-southeast1 --no-invoker-iam-check   # public reach under org policy
```
Test the `…run.app` URL: password page appears, password loads the dashboard, `/data.json` returns 401 without a session.

**6. Custom domain (Cloudflare, free)**
- DNS → CNAME `acme` → the service's `…run.app` host, **Proxied (orange)**.
- SSL/TLS → **Full (strict)**.
- Rules → Origin Rules → when hostname = `acme.bidbrain.ai`, set **Host header** → the `…run.app` host.

**7. Daily refresh (Cloud Scheduler)** — in the Cloud Run **job → Triggers tab → Add Scheduler Trigger** (it creates the schedule and enables the API). Standard cadence: `0 22 * * *` (22:00 UTC).

**8. Commit**
```powershell
git add . ; git commit -m "Add ACME client dashboard" ; git push
```

---

## 11. Operating it

**In plain terms:** how to run, update, and troubleshoot the existing pieces.

**Run the data refresh now (don't wait for the schedule):**
```powershell
gcloud run jobs execute mongodb-export --region australia-southeast1
```

**Confirm the data file updated:**
```powershell
gcloud storage ls -l gs://bidbrain-analytics-mongodb-dash/mongodb.json   # check the timestamp
```

**See the job's logs (what happened during a run):**
```powershell
gcloud logging read "resource.labels.job_name=mongodb-export" --project=bidbrain-analytics --limit=20 --freshness=1d --format="value(textPayload)" --order=asc
```

**Update the dashboard or app code** — edit files in `client_mongodb/dash/`, then redeploy:
```powershell
cd client_mongodb/dash ; gcloud run deploy mongodb-dash --source . --region australia-southeast1
```
(Existing env vars/secrets/SA stick across redeploys.)

**Change the password:** add a new version of the secret, then redeploy (or it picks up `:latest` on next start):
```powershell
$pw = Read-Host "New password"; $t=New-TemporaryFile; [IO.File]::WriteAllText($t,$pw)
gcloud secrets versions add mongodb-dash-password --data-file="$t"; Remove-Item $t
```

**The everyday git loop:**
```powershell
git add . ; git commit -m "what changed" ; git push
```

### Continuous deployment (GitHub → Cloud Build → Cloud Run)

The manual `gcloud run deploy --source .` above is fine for one-offs. For push-to-deploy, each deployable unit ships a `cloudbuild.yaml`:

- `client_mongodb/dash/cloudbuild.yaml` — builds the image, deploys the **service** `mongodb-dash`, and re-applies `--no-invoker-iam-check` (so a redeploy never silently drops public reachability under the org policy).
- `client_mongodb/job/cloudbuild.yaml` — builds the image and deploys the **job** `mongodb-export` (`gcloud run jobs deploy`, which the console's Service-only wizard cannot do).

**One-time wiring:**
```powershell
# 1. Artifact Registry repo the builds push to
gcloud artifacts repositories create bidbrain --repository-format=docker `
  --location=australia-southeast1 --project bidbrain-analytics

# 2. Connect the GitHub repo, then create ONE trigger per unit (push to main),
#    each scoped by included-files so only the changed unit rebuilds:
gcloud builds triggers create github --name=deploy-mongodb-dash `
  --repo-name=bidbrain-analytics --repo-owner=Bidbrain --branch-pattern=^main$ `
  --included-files="client_mongodb/dash/**" --build-config=client_mongodb/dash/cloudbuild.yaml
gcloud builds triggers create github --name=deploy-mongodb-export `
  --repo-name=bidbrain-analytics --repo-owner=Bidbrain --branch-pattern=^main$ `
  --included-files="client_mongodb/job/**" --build-config=client_mongodb/job/cloudbuild.yaml
```

**Trigger service-account roles** (grant once): `roles/run.admin`, `roles/artifactregistry.writer`, `roles/cloudbuild.builds.builder`, and `roles/iam.serviceAccountUser` on the two runtime SAs (`mongodb-dash-web@…`, `mongodb-dash-job@…`). The daily data refresh is a separate **Cloud Scheduler** trigger on the job (section 10 step 7), independent of CD.

---

## 12. Gotchas & lessons learned

Hard-won, in no particular order. These will save the next build hours.

**PowerShell**
- No `grep`/`tr`/`sed` — use `Select-String`, `Where-Object`, `-replace`.
- Comma-separated `gcloud` flag values **must be quoted**, or PowerShell splits them: `--set-env-vars "A=1,B=2"` (a missing env var → `KeyError`).
- You **can't rename a folder you're standing in** — `cd` out first.
- **Variables don't survive a new terminal.** Re-set `$repo`, `$app`, etc. each session.
- Writing secrets: use a temp file with `[IO.File]::WriteAllText` (no trailing newline) so the password is exact.
- **`$ErrorActionPreference = "Stop"` + a redirected native stderr = silent script death.** Under `Stop`, redirecting a native command's stderr (e.g. `gcloud … 2>$null`) wraps each stderr line in a *terminating* `NativeCommandError` — so an "expected to fail" probe like the not-logged-in `gcloud auth print-access-token` check aborts the whole script instead of falling through to the login step. Run such probes through the `Test-Probe` helper in `scripts/setup.ps1` (drops to `Continue`, judges success by `$LASTEXITCODE`) rather than testing the redirected output directly.

**BigQuery / Snowflake**
- `bq` and BigQuery jobs need an explicit `--location=australia-southeast1` (defaults to US otherwise).
- Snowflake → BigQuery SQL dialect ports: `SPLIT_PART(x,'_',3)` → `SPLIT(x,'_')[SAFE_OFFSET(2)]`; `(VALUES …) AS t(...)` → `UNNEST([STRUCT(...)])`; `TRUNC(d,'WEEK')` → `DATE_TRUNC(d, WEEK(MONDAY))`; `SUM(CASE WHEN … )` → `COUNTIF(…)`; `::STRING` → `CAST(... AS STRING)`. Snowflake's `OBJECT_CONSTRUCT`/`OBJECT_AGG` JSON builders → build the JSON **in Python** in the job instead (cleaner than BigQuery `EXPORT DATA`, which shards files and forces a different shape).

**Cloud Run**
- Source deploys build via the **compute default service account**, which needs `roles/cloudbuild.builds.builder` (one-time grant per project).
- The org enforces **Domain Restricted Sharing**, so `--allow-unauthenticated` (which sets `allUsers`) is rejected with *"do not belong to a permitted customer."* Fix: `gcloud run services update <svc> --no-invoker-iam-check` (the app does its own auth).

**Cloudflare + custom domain**
- A plain CNAME to a `…run.app` URL returns a **404** (Cloud Run routes by Host header). Fix: **Host Header Override** (Origin Rule) + **Proxied (orange)** + SSL **Full (strict)**.
- The web app's session cookie is intentionally **not pinned to a domain**, so login works through the Cloudflare proxy.

**Security**
- Don't reintroduce a public data URL. The old `pub-….r2.dev` link and the `dashboards-unlock` slug system were obscurity, not security.
- The legacy Snowflake build script (`CREATE_MONGO_DB_DASH`) contained **live R2 credentials** in plaintext — keep that file out of git and **rotate those keys** when retiring R2.

---

## 13. Current status & TODO

**This first dashboard was built fast to prove the pattern works.** Status:

**✅ Done**
- BigQuery layered model + MongoDB views
- Snowflake read-only sync user (key-pair)
- Export job (`mongodb-export`) — builds `mongodb.json`, ran successfully
- Private bucket + secrets + service accounts
- Gated web app (`mongodb-dash`) deployed, public-reachable, password-protected

**🚧 In progress / pending**
- **Custom domain** `mongodb.bidbrain.ai` (Cloudflare CNAME + Host Header Override) — finishing.
- **Daily auto-refresh** (Cloud Scheduler trigger on the `mongodb-export` job, `0 22 * * *`) — **not set up yet**; the job has only been run manually. Add via the job's Triggers tab.
- **Retire the legacy MongoDB path:** turn off the old Snowflake `DAILY_MONGODB_EXPORT` task and delete the public R2 `mongodb.json` so the old public link goes dead. **Rotate the leaked R2 keys.** (Other clients' `dashboards-unlock` dashboards are untouched.)
- **Export the BigQuery view DDL:** the runner (`infra/create_views.py`) and folder (`client_mongodb/sql/`) now exist, but the actual `CREATE OR REPLACE VIEW` files still need to be exported from the live project (steps in `client_mongodb/sql/README.md`). Until then a from-scratch rebuild can't recreate the views.
- **Finish the KGA/IDC content-syndication integration:** the export job now pulls the IDC campaign `701RG00001NKKwQYAX` from Snowflake into `src_salesforce`. Still pending in BigQuery (views are not yet in the repo): update `stg_salesforce` to map this campaign ID to programme `IDC`, and confirm `cs_leads` / `cs_leads_by_programme` split DNB vs IDC correctly. Then build out the dashboard per the latest direction — separate **Paid Media** and **Content Syndication** tabs, each with a DNB↔IDC toggle and no cumulative cross-campaign totals (the CS section currently reads "three DNB IDE programmes"). Paid-media metrics (spend / impressions / CTR, excluding CS leads) to be confirmed with Calvin; the Cloudflare `Rig` (regulated + iGaming) industry scope with Surabhi/Jade.

> **Already done** (previously listed here): the Windsor loaders are on `raw_windsor` + `australia-southeast1`, read secrets via ADC (no gcloud-path hardcoding), and cache to `_run/`; `infra/` provisions `raw_windsor` consistently; CD configs (`cloudbuild.yaml`) exist for both units; and `dashboard.html` now reads "BigQuery", not "Snowflake".

---

## 14. Glossary (plain English)

- **GCP / Google Cloud** — Google's cloud platform; where all of this runs.
- **Project (`bidbrain-analytics`)** — the container that holds all our Google Cloud resources and billing.
- **Region (`australia-southeast1`)** — the physical location (Sydney) where our resources live.
- **BigQuery** — Google's data warehouse; a giant, fast database where we store and crunch data.
- **Dataset** — a labelled folder of tables/views inside BigQuery.
- **Table / View** — a table holds data; a view is a saved query that *calculates* a result from tables on demand.
- **Cloud Run** — a service that runs your code in the cloud without managing servers. A **job** runs and stops; a **service** stays on and answers web requests.
- **GCS bucket (Cloud Storage)** — cloud file storage. "Private" means not reachable from the internet.
- **Secret Manager** — a locked safe for passwords and keys, kept out of the code.
- **Service account** — a robot "user" with an ID badge and limited permissions, used by automated pieces.
- **IAM** — the system that controls who/what is allowed to do what.
- **Snowflake** — a separate data warehouse where the client's raw ad/lead data originates.
- **Windsor.ai** — a tool that pulls marketing data and loads it into BigQuery.
- **JSON file** — a plain-text data file; here it's the finished, tidy dataset the dashboard reads.
- **Cloudflare** — manages the `bidbrain.ai` web address (DNS) and proxies traffic to our app.
- **DNS** — the internet's address book; turns a name like `mongodb.bidbrain.ai` into the right destination.
- **Basic Auth / password gate** — the login screen that blocks access until you enter the password.
- **Security by obscurity** — "protection" that only relies on something being hard to find (a hidden link). Not real protection — what the old system did, and what we replaced.

---

*Maintained by the Bidbrain team. When in doubt: follow the [MongoDB example](#10-playbook-add-a-new-client-dashboard), keep secrets out of git, and never make the data public.*