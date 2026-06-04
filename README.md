# Bidbrain Analytics — Client Reporting Platform

> Secure, self-hosted marketing dashboards for Bidbrain clients, running entirely on Google Cloud.
> **One repository, one repeatable pattern, many client dashboards.**

This README is the **map of the whole repo**. It is written to do two jobs at once:

1. **Get an AI or engineer productive in minutes.** Every folder has its own detailed
   README; this page tells you which one to open for any task. If you're an AI picking
   this up cold, read [§3 Orientation](#3-orientation-for-an-ai-or-engineer) and the
   [Repo map](#5-repo-map-every-folder-and-its-readme), then jump straight to the
   folder you need.
2. **Be fully understandable by a non-technical reader.** Every section opens with a
   plain-English summary, and the [Glossary](#12-glossary-plain-english) explains every
   term. Read the whole thing top to bottom and you'll understand what we built and why.

---

## Quickstart

Everything in the repo is portable — nothing machine-specific is baked into the code. You only
need the **gcloud CLI authenticated** as a member of the `bidbrain-analytics` project (with
`secretmanager.secretAccessor` on the secrets the loaders read).

**Windows (PowerShell):**
```powershell
git clone https://github.com/Bidbrain/bidbrain-analytics.git
cd bidbrain-analytics
.\scripts\setup.ps1            # one-time: installs Python 3.12 + gcloud if missing, makes .venv, installs deps, logs in
.\scripts\start_day.ps1        # each session: verifies gcloud + ADC creds
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py
```

**macOS / Linux (no `setup.ps1` needed — the code is cross-platform):**
```bash
git clone https://github.com/Bidbrain/bidbrain-analytics.git && cd bidbrain-analytics
gcloud auth login && gcloud auth application-default login   # one-time; ADC powers the client libs
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python windsor_data_pull/meta/meta_loader.py
```

Secrets are read at runtime from Secret Manager via Application Default Credentials — no key
files, no gcloud-path hardcoding. See [`scripts/`](scripts/README.md) for what each step does.

---

## 1. What this is (plain English)

**In one sentence:** this project takes a client's raw marketing data, tidies it up, and
serves it as a private, password-protected web dashboard that only the right people can see.

Think of it like a **vending machine for reports**. Behind the scenes, ingredients (raw
data) get pulled in, processed into a finished product (a tidy data file), and put behind
glass. Out front, a customer has to enter a code (password) before the machine hands
anything over — and you can't reach around the back to grab the product either.

We built the first one for **MongoDB (APAC)**. The whole point of this repo is that **every
future client dashboard follows the exact same pattern**, so building the next one is mostly
copy-and-adjust, not start-from-scratch. We're now on our second (**Cloudflare**) and have a
third in intake (**STT**).

Everything lives on **Google Cloud** (one platform), in the GCP project
**`bidbrain-analytics`**, in the **Sydney region (`australia-southeast1`)**. The web
addresses (`*.bidbrain.ai`) are pointed at it by Cloudflare DNS.

---

## 2. How it works (the 60-second version)

**In plain terms:** data flows left to right, gets locked down at the end, and a person
needs a password to see it.

```
  SHARED INGEST (once, all clients)        PER-CLIENT (one set per client)         WHO SEES IT
 ┌─────────────────────────────┐
 │ Windsor.ai  ─► raw_windsor   │ ─┐
 │ (Trade Desk, Meta, GA4 data) │  │     ┌──────────────┐    ┌───────────────┐
 └─────────────────────────────┘  ├──►  │  Export Job  │ ─► │   BigQuery    │ ─┐
 ┌─────────────────────────────┐  │     │ (Cloud Run)  │    │  client views │  │ builds one
 │ Snowflake   ─► raw_snowflake │ ─┘     └──────────────┘    └───────────────┘  │ tidy file
 │ (Salesforce, ad platforms)   │              │                                 ▼
 └─────────────────────────────┘              │                       ┌────────────────────┐
                                              ▼                        │  <client>.json     │
                                     ┌──────────────────┐  ◄────────── │ (the finished data)│
                                     │ Private GCS bucket│              └────────────────────┘
                                     │ (locked storage)  │
                                     └──────────────────┘
                                              │  served ONLY to a logged-in user
                                              ▼
                                     ┌──────────────────┐              ┌────────────────────┐
                                     │ Dashboard Web App │  ◄────────── │  Password screen   │
                                     │   (Cloud Run)     │              │ (no password = no  │
                                     │ <client>.bidbrain │              │  access, no data)  │
                                     │       .ai         │              └────────────────────┘
                                     └──────────────────┘
                                              ▼
                                   👤 The team / client (after the password)
```

**The journey:**

1. **Shared ingest** pulls raw data once for everyone: [`windsor_data_pull/`](windsor_data_pull/)
   lands ad-platform performance and GA4 web analytics into BigQuery `raw_windsor`, and
   [`snowflake_data_pull/`](snowflake_data_pull/) mirrors the Snowflake source tables into
   BigQuery `raw_snowflake`.
2. Each client has an **Export Job** (Cloud Run) that runs the client's BigQuery **views**
   (which filter the shared raw data to *that* client and roll it up), packages the result
   into a single tidy file `<client>.json`, and saves it to a **private** storage bucket.
3. A small **Web App** (Cloud Run) shows a password screen. Enter the password and you see
   the dashboard; the app fetches the data file *on your behalf* from the private bucket.
   No password → you see nothing, and the data file can't be grabbed directly.
4. It's reachable at a friendly address, e.g. `mongodb.bidbrain.ai`.

> **The data file is never public.** That is the entire security model — see
> [§7 Security](#7-security-model-read-before-changing-hosting).

---

## 3. Orientation (for an AI or engineer)

**Fixed facts — memorize these:**

| Thing | Value |
|---|---|
| GCP project | `bidbrain-analytics` (project number `516554645957`) |
| Region (everything) | `australia-southeast1` (Sydney) |
| GitHub repo | `Bidbrain/bidbrain-analytics` (private) |
| Local dev machine | Windows + **PowerShell** (commands here are PowerShell) |
| Secrets store | GCP **Secret Manager** + a local-only folder `bidbrain-vault/` (never in git) |
| Data warehouse | **BigQuery**: two shared `raw_*` datasets + one `client_*` dataset per client |
| Dashboard hosting | One **Cloud Run service per client** (a password-gated web app) |
| Data refresh | One **Cloud Run job per client** (reads views → builds the JSON) |
| Deploys | **Manual today** (build image → update job/service). CD configs exist but triggers aren't active — see [§9](#9-operating-it-deploy-refresh-debug). |

**Golden rules (do not break these):**

- **Never commit secrets.** No private keys, passwords, or API tokens in the repo. They
  live in Secret Manager (cloud) and `bidbrain-vault/` (local). See [`.gitignore`](.gitignore).
- **Never make the data file public.** The whole security model depends on the JSON staying
  in a private bucket, served only by the authenticated web app. The *old* Cloudflare/R2
  system exposed it publicly — don't regress. See [§7](#7-security-model-read-before-changing-hosting).
- **Everything in `australia-southeast1`.** Mixed regions cause "missing resource"
  confusion and cross-region cost.
- **One client = its own dataset, job, bucket, web app, password, and subdomain.** Full
  isolation between clients.

**To add a new client:** copy [`client_mongodb/`](client_mongodb/) (the template), change
one line (`CLIENT = "..."`), point its views at the right filter, and follow the playbook in
[§10](#10-playbook-add-a-new-client). The shared `raw_*` layers usually already have the data.

---

## 4. Read this in the right order

**If you're an AI / engineer (fastest path to productive):**
1. This page → [§3 Orientation](#3-orientation-for-an-ai-or-engineer) and the [Repo map](#5-repo-map-every-folder-and-its-readme).
2. [`client_mongodb/README.md`](client_mongodb/README.md) — the canonical 3-stage pattern, end to end.
3. The folder you actually need to change (every folder's README is self-contained).

**If you're a non-technical stakeholder (full understanding):**
1. [§1](#1-what-this-is-plain-english) and [§2](#2-how-it-works-the-60-second-version) here.
2. [`client_mongodb/README.md`](client_mongodb/README.md) — a worked example in plain English.
3. The two ingest folders ([`windsor_data_pull/`](windsor_data_pull/),
   [`snowflake_data_pull/`](snowflake_data_pull/)) and the [Glossary](#12-glossary-plain-english).

---

## 5. Repo map (every folder and its README)

Each folder has a **detailed README of its own** — start there for anything inside it.

### Shared ingest — runs once, feeds every client

| Folder | What it does | Open its README |
|---|---|---|
| [`windsor_data_pull/`](windsor_data_pull/) | Pulls ad-platform performance (Trade Desk, Meta) and GA4 web-analytics outcomes from **Windsor.ai** into BigQuery `raw_windsor`. Incremental, idempotent loaders. | [README](windsor_data_pull/README.md) · [meta/](windsor_data_pull/meta/README.md) · [tradedesk/](windsor_data_pull/tradedesk/README.md) · [ga4/](windsor_data_pull/ga4/README.md) |
| [`snowflake_data_pull/`](snowflake_data_pull/) | Mirrors the **Snowflake** source tables (Salesforce CS + ad platforms) 1:1 into BigQuery `raw_snowflake`. Dumb full copy; clients filter in their views. | [README](snowflake_data_pull/README.md) |

### Clients — one folder per client (copy of the template)

| Folder | Status | What it is | Open its README |
|---|---|---|---|
| [`client_mongodb/`](client_mongodb/) | **Live** | The **template** every client copies. Models everything in BigQuery from `raw_snowflake`. Paid Media + Content Syndication (DNB / IDC). | [README](client_mongodb/README.md) · [job/](client_mongodb/job/README.md) · [dash/](client_mongodb/dash/README.md) · [sql/](client_mongodb/sql/README.md) |
| [`client_cloudflare/`](client_cloudflare/) | **Deploying** | Second client. Deliberately different: its model already lives in Snowflake, so the job pulls Snowflake's *final-model* views and BigQuery views are thin pass-throughs. | [README](client_cloudflare/README.md) · [job/](client_cloudflare/job/README.md) · [dash/](client_cloudflare/dash/README.md) · [sql/](client_cloudflare/sql/README.md) |
| [`client_STT/`](client_STT/) | **On hold** | Intake notes for ST Telemedia GDC. Data is already in `raw_snowflake`; waiting on the agency to confirm scope before building. | [README](client_STT/README.md) · [INTAKE.md](client_STT/INTAKE.md) |

### Operations & root

| Path | What it does | Open its README |
|---|---|---|
| [`scripts/`](scripts/) | Windows onboarding & per-session credential checks (`setup.ps1`, `start_day.ps1`). | [README](scripts/README.md) |
| [`requirements.txt`](requirements.txt) | Pinned deps for the loaders + one-time BigQuery setup scripts (dev superset). Each Cloud Run unit pins its own separately. | — |
| [`.gitignore`](.gitignore) / [`.gcloudignore`](.gcloudignore) / [`.gitattributes`](.gitattributes) | Keep secrets out of git, keep source uploads clean, force LF in container files. | — |

---

## 6. Architecture in detail

### 6.1 The layered BigQuery model

**In plain terms:** we mirror each upstream source into a shared "drawer" once, then each
client has its own drawer of saved calculations that pick out and reshape just their slice.

- **`raw_<source>`** — shared raw data mirrored from one upstream source, used by multiple
  clients. **Two exist:**
  - **`raw_windsor`** — Trade Desk (`perf_the_trade_desk`), Meta (`perf_meta`), and GA4
    (`perf_ga4`), loaded by [`windsor_data_pull/`](windsor_data_pull/).
  - **`raw_snowflake`** — the Snowflake APAC tables mirrored 1:1 (Salesforce CS + Trade Desk +
    LinkedIn + Reddit + DV360 + Google Ads), loaded by [`snowflake_data_pull/`](snowflake_data_pull/).
- **`client_<client>`** — one dataset per client, holding everything specific to that client:
  - **views** that filter the shared raw tables down to this client's slice (campaign IDs,
    advertiser name, business rules) and roll them up into dashboard-ready numbers.
  - optionally **`src_*` tables** for data that is genuinely client-specific (e.g. Cloudflare
    lands its Snowflake final-model views as `src_*` — see that client's README).

The per-client **filter is the main thing you change** when copying the template — and it
lives in the `sql/` views, not in the data pull. The pull stays dumb and shared.

### 6.2 The two moving parts per client: the Job and the Web App

Each client has **two** Cloud Run pieces. They're different things and easy to confuse:

| | **Export Job** (`<client>-export`) | **Web App** (`<client>-dash`) |
|---|---|---|
| Cloud Run type | **Job** (runs, finishes, stops) | **Service** (always-on, answers web requests) |
| What it does | reads BigQuery views → builds `<client>.json` → saves to the private bucket | shows password screen, serves the dashboard + data to logged-in users |
| When it runs | daily (Cloud Scheduler) and on demand | whenever someone visits the URL |
| Source folder | `client_<client>/job/` | `client_<client>/dash/` |
| Talks to | BigQuery + GCS (Cloudflare's job also reads Snowflake) | GCS (read-only) + Secret Manager |

**In plain terms:** the Job is the *kitchen* (makes the dish once a day); the Web App is the
*waiter behind a locked door* (checks your password, then brings you the dish).

### 6.3 Storage, secrets, identities

- **`bidbrain-analytics-<client>-dash`** — a **private** GCS bucket holding `<client>.json`.
- **`bidbrain-analytics-staging`** — shared bucket used by the Windsor loaders.
- **Secrets (Secret Manager — names only, values never in git):** `snowflake-bq-key` (read
  Snowflake), `windsor-api-key` (read Windsor), and per client `<client>-dash-password` +
  `<client>-dash-session-key`.
- **Service accounts (the "ID badges"), per client:** `<client>-dash-job@…` (the job: read
  Snowflake key, write BigQuery + bucket) and `<client>-dash-web@…` (the web app: read the
  bucket + the two dashboard secrets). Least privilege throughout.

### 6.4 The custom domain

- `bidbrain.ai` DNS is on **Cloudflare**; we add one subdomain per client (e.g.
  `mongodb.bidbrain.ai`). DNS/proxy only — no compute, no extra cost.
- A plain DNS record to a `…run.app` host returns **404** (Cloud Run routes by hostname).
  The fix is a Cloudflare **Host Header Override** (Origin Rule), record **Proxied (orange)**,
  SSL **Full (strict)**. Cloudflare provides the HTTPS cert for free.

---

## 7. Security model (read before changing hosting)

**This is the most important section.**

**The OLD system (legacy, being retired):** the previous dashboards put the data file at a
**public link** (`pub-….r2.dev/…json`). The password screen only handed back a hard-to-guess
URL — anyone with the link could grab the raw data **without any password**. That's *security
by obscurity*: hidden ≠ protected.

**The NEW system (this repo):** authentication sits in front of **both** the page and the data.
- The dashboard is a Cloud Run web app with a real password check. **No valid password → HTTP
  401 → nothing**, not the page and not the data.
- The data file lives in a **private bucket**. The browser never touches it directly; the app
  reads it server-side (with its own ID badge) and only returns it to a request that already
  passed the password.
- The public `…run.app` URL is harmless: hitting it just shows the password screen.

**Why we disable Cloud Run's built-in IAM check (`--no-invoker-iam-check`):** the org enforces
*Domain Restricted Sharing*, which blocks the usual "allow public" setting. Disabling the
invoker check is Google's recommended way to make a service publicly reachable under that
policy. It's safe **because our app does its own password auth** — we're removing a duplicate,
conflicting gate, not the protection.

**Non-negotiables:** ❌ never publish the JSON to a public URL/bucket · ❌ never rely on "the
link is hard to guess" · ✅ data is always served by the authenticated app from a private bucket.

---

## 8. Conventions & naming (follow exactly)

So every client looks the same and nothing can be pointed at the wrong client by a stale
variable, all names derive from the **client key**:

| Resource | Pattern | MongoDB example |
|---|---|---|
| Client key | lowercase, short | `mongodb` |
| BigQuery dataset | `client_<client>` | `client_mongodb` |
| Shared source datasets | `raw_<source>` | `raw_windsor`, `raw_snowflake` |
| GCS bucket | `bidbrain-analytics-<client>-dash` | `bidbrain-analytics-mongodb-dash` |
| Data object | `<client>.json` | `mongodb.json` |
| Export job (Cloud Run job) | `<client>-export` | `mongodb-export` |
| Web app (Cloud Run service) | `<client>-dash` | `mongodb-dash` |
| Job service account | `<client>-dash-job@…` | `mongodb-dash-job@…` |
| Web service account | `<client>-dash-web@…` | `mongodb-dash-web@…` |
| Password / session secrets | `<client>-dash-password` / `<client>-dash-session-key` | `mongodb-dash-password` |
| Subdomain | `<client>.bidbrain.ai` | `mongodb.bidbrain.ai` |
| Repo folder | `client_<client>/` (with `job/`, `dash/`, `sql/`) | `client_mongodb/` |

Other rules: everything in `australia-southeast1`; `snake_case` for BigQuery objects; the
Artifact Registry docker repo is `bidbrain` (shared); secrets only in Secret Manager +
`bidbrain-vault/`.

---

## 9. Operating it (deploy, refresh, debug)

> **Deploys are manual today.** Each `job/` and `dash/` ships a `cloudbuild.yaml` for a future
> push-to-`main` trigger, but those triggers aren't active. Running `gcloud builds submit
> --config cloudbuild.yaml` from a laptop fails on `iam.serviceaccounts.actAs` (Cloud Build's
> own account can't act as the runtime SA). **For now: build the image, then deploy as
> yourself.** Each client README has exact copy-paste commands.

**Refresh a client's data now (don't wait for the schedule):**
```powershell
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py            # refresh shared raw layer (all clients)
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait   # rebuild this client's JSON
```

**Redeploy the dashboard app after editing `dash/`:**
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-dash:$(git rev-parse --short HEAD)"
gcloud builds submit client_mongodb/dash --tag $IMG --region australia-southeast1
gcloud run services update mongodb-dash --image $IMG --region australia-southeast1
```

**See a job's logs:**
```powershell
gcloud logging read "resource.labels.job_name=mongodb-export" --project=bidbrain-analytics --limit=20 --freshness=1d --format="value(textPayload)" --order=asc
```

The everyday git loop and the full per-stage command set live in each client's README.
Cloudflare additionally ships a one-shot stand-up script — see
[`client_cloudflare/deploy_cloudflare.ps1`](client_cloudflare/deploy_cloudflare.ps1).

---

## 10. Playbook: add a new client

The reusable recipe (replace `acme` with the client key). Full detail is in the template's
README — this is the shape:

1. **Confirm the data exists** in a shared `raw_*` layer (or add one line to a loader's table
   list). Check [`client_STT/INTAKE.md`](client_STT/INTAKE.md) for how we scope a new client.
2. **Copy the template:** `client_mongodb/` → `client_acme/`. Change `CLIENT = "acme"` in
   `job/main.py`. Rewrite the filter in `sql/01_*`/`02_*` for this client's slice.
3. **Provision GCP:** private bucket, `client_acme` dataset, two service accounts + IAM,
   password + session secrets. (Cloudflare's [`deploy_cloudflare.ps1`](client_cloudflare/deploy_cloudflare.ps1)
   does all of this in one idempotent script — copy it.)
4. **Bootstrap BigQuery:** run the job once (lands any `src_*`, then errors on the
   not-yet-existing views — expected), `python client_acme/create_views.py`, re-run the job.
5. **Deploy the web app**, run `--no-invoker-iam-check`, drop in `dashboard.html`.
6. **Wire the daily refresh** (`scheduler.ps1`) and the **custom domain** (Cloudflare CNAME +
   Host Header Override).
7. **Commit.**

---

## 11. Current status & TODO

| Client | State |
|---|---|
| **MongoDB** | ✅ Live (BigQuery model, export job, gated web app). Finishing: `mongodb.bidbrain.ai` custom domain; confirming the daily Cloud Scheduler trigger. Retiring the legacy public-R2 path (and **rotating the leaked R2 keys**). |
| **Cloudflare** | ✅ Live (gated web app) at https://cloudflare-dash-p32gk2wuia-ts.a.run.app — verified HTTP 200 on 2026-06-04. "Core Demand Generation" story across TTD/LinkedIn/Reddit/LINE paid media + content syndication. See [`dash/LIVE_URL.md`](client_cloudflare/dash/LIVE_URL.md). Finishing: `cloudflare.bidbrain.ai` custom domain; confirming the daily Cloud Scheduler trigger. |
| **STT** | ✅ Live (gated web app). "Ads → website traffic" story: GA4 (`raw_windsor.perf_ga4`) vs LinkedIn + DV360 (`raw_snowflake`). 12 BigQuery views → `stt-export` job → `stt-dash` service, daily Scheduler. See [`client_STT/README.md`](client_STT/README.md). |

**Platform-wide TODO:** activate CD triggers (currently manual deploys); set up the Cloud
Scheduler daily run for each live client; rotate the legacy leaked credentials when retiring
the old R2 path.

---

## 12. Glossary (plain English)

- **GCP / Google Cloud** — Google's cloud platform; where all of this runs.
- **Project (`bidbrain-analytics`)** — the container that holds all our Google Cloud resources and billing.
- **Region (`australia-southeast1`)** — the physical location (Sydney) where our resources live.
- **BigQuery** — Google's data warehouse; a giant, fast database where we store and crunch data.
- **Dataset** — a labelled folder of tables/views inside BigQuery.
- **Table / View** — a table holds data; a view is a saved query that *calculates* a result from tables on demand.
- **Raw layer (`raw_windsor`, `raw_snowflake`)** — a 1:1 mirror of an upstream source, shared by all clients.
- **Cloud Run** — runs your code in the cloud without managing servers. A **job** runs and stops; a **service** stays on and answers web requests.
- **GCS bucket (Cloud Storage)** — cloud file storage. "Private" means not reachable from the internet.
- **Secret Manager** — a locked safe for passwords and keys, kept out of the code.
- **Service account** — a robot "user" with an ID badge and limited permissions, used by automated pieces.
- **IAM** — the system that controls who/what is allowed to do what.
- **Snowflake** — a separate data warehouse where much of the clients' raw ad/lead data originates.
- **Windsor.ai** — a connector tool that pulls marketing data from ad platforms.
- **JSON file** — a plain-text data file; here it's the finished, tidy dataset the dashboard reads.
- **Cloudflare** — (the company) manages the `bidbrain.ai` web address (DNS) and proxies traffic. Also one of our **clients** — context tells them apart.
- **Security by obscurity** — "protection" that only relies on something being hard to find (a hidden link). Not real protection — what the old system did, and what we replaced.

---

*Maintained by the Bidbrain team. When in doubt: follow the [MongoDB template](client_mongodb/README.md),
keep secrets out of git, and never make the data public.*
