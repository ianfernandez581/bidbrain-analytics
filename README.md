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
.\.venv\Scripts\python.exe ingest\windsor_data_pull\meta\meta_loader.py
```

**macOS / Linux (no `setup.ps1` needed — the code is cross-platform):**
```bash
git clone https://github.com/Bidbrain/bidbrain-analytics.git && cd bidbrain-analytics
gcloud auth login && gcloud auth application-default login   # one-time; ADC powers the client libs
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python ingest/windsor_data_pull/meta/meta_loader.py
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
copy-and-adjust, not start-from-scratch. **Eight client dashboards are now live** on this pattern —
**MongoDB**, **Cloudflare**, **STT (ST Telemedia GDC)**, **Schneider Electric**, **HireRight**,
**City Perfume**, **ResetData**, and **PropTrack** — plus a meta **Status dashboard**
(`status.bidbrain.ai`) that watches all the Snowflake-sourced ones. MongoDB is the original template;
**STT** became the archetype for the leaner clients that read straight from the shared raw layers with
no Snowflake final-model layer (Schneider, HireRight, City Perfume, ResetData and PropTrack all
descend from it).

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

1. **Shared ingest** pulls raw data once for everyone, into **five** shared `raw_*` datasets:
   [`ingest/windsor_data_pull/`](ingest/windsor_data_pull/) lands ad-platform performance (Meta, Trade Desk,
   Reddit, Google Ads) + GA4 into `raw_windsor`; [`ingest/snowflake_data_pull/`](ingest/snowflake_data_pull/)
   mirrors the Snowflake source tables into `raw_snowflake`; [`ingest/dts_data_pull/`](ingest/dts_data_pull/)
   lands Google Ads + GA4 via Google's native **BigQuery Data Transfer Service** into
   `raw_google_ads` + `raw_ga4`; and [`ingest/neto_data_pull/`](ingest/neto_data_pull/) mirrors Neto e-commerce
   orders into `raw_neto`.
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
| Data warehouse | **BigQuery**: five shared `raw_*` datasets (`raw_windsor`, `raw_snowflake`, `raw_google_ads`, `raw_ga4`, `raw_neto`) + one `client_*` dataset per client |
| Dashboard hosting | One **Cloud Run service per client** (a password-gated web app) |
| Data refresh | One **Cloud Run job per client** (reads views → builds the JSON), **self-gating on a `*/10` UTC schedule** — it rebuilds only when its upstream advanced |
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

**To add a new client:** copy [`clients/client_mongodb/`](clients/client_mongodb/) (the template), change
one line (`CLIENT = "..."`), point its views at the right filter, and follow the playbook in
[§10](#10-playbook-add-a-new-client). For a **lean paid-media client** with no Snowflake
final-model layer, copy [`clients/client_STT/`](clients/client_STT/) instead — the archetype Schneider and
HireRight were built from. The shared `raw_*` layers usually already have the data.

---

## 4. Read this in the right order

**If you're an AI / engineer (fastest path to productive):**
1. This page → [§3 Orientation](#3-orientation-for-an-ai-or-engineer) and the [Repo map](#5-repo-map-every-folder-and-its-readme).
2. [`clients/client_mongodb/README.md`](clients/client_mongodb/README.md) — the canonical 3-stage pattern, end to end.
3. The folder you actually need to change (every folder's README is self-contained).

**If you're a non-technical stakeholder (full understanding):**
1. [§1](#1-what-this-is-plain-english) and [§2](#2-how-it-works-the-60-second-version) here.
2. [`clients/client_mongodb/README.md`](clients/client_mongodb/README.md) — a worked example in plain English.
3. The two ingest folders ([`ingest/windsor_data_pull/`](ingest/windsor_data_pull/),
   [`ingest/snowflake_data_pull/`](ingest/snowflake_data_pull/)) and the [Glossary](#12-glossary-plain-english).

---

## 5. Repo map (every folder and its README)

Each folder has a **detailed README of its own** — start there for anything inside it.

> **Layout:** everything is grouped under two top-level folders — **`clients/`** (one `client_<c>/`
> sub-folder per client dashboard) and **`ingest/`** (the shared raw-layer loaders) — plus
> **`status_dashboard/`** (the meta dashboard) and **`scripts/`** (operator tooling) at the root.

### Shared ingest — runs once, feeds every client

| Folder | What it does | Open its README |
|---|---|---|
| [`ingest/windsor_data_pull/`](ingest/windsor_data_pull/) | Pulls ad-platform performance (Meta, Trade Desk, Reddit, Google Ads) and GA4 web analytics from **Windsor.ai** into BigQuery `raw_windsor`. Incremental, idempotent loaders; Meta + Trade Desk run as fixed-daily Cloud Run jobs. | [README](ingest/windsor_data_pull/README.md) · [meta/](ingest/windsor_data_pull/meta/README.md) · [tradedesk/](ingest/windsor_data_pull/tradedesk/README.md) · [ga4/](ingest/windsor_data_pull/ga4/README.md) · [google_ads/](ingest/windsor_data_pull/google_ads/README.md) · [reddit/](ingest/windsor_data_pull/reddit/README.md) |
| [`ingest/snowflake_data_pull/`](ingest/snowflake_data_pull/) | Mirrors the **Snowflake** source tables (Salesforce CS + ad platforms) 1:1 into BigQuery `raw_snowflake`. Dumb full copy; clients filter in their views. **Self-gating `*/10`** (per-table `_sync_state` watermark — the one ingest unit that self-gates). | [README](ingest/snowflake_data_pull/README.md) |
| [`ingest/dts_data_pull/`](ingest/dts_data_pull/) | Lands **Google Ads + GA4** into `raw_google_ads` + `raw_ga4` via Google's native **BigQuery Data Transfer Service** (free, daily). `create_views.py` builds 3 flattening bridge views that UNION the Windsor history while the native backfill catches up. | [README](ingest/dts_data_pull/README.md) |
| [`ingest/neto_data_pull/`](ingest/neto_data_pull/) | Mirrors **Neto / Maropost** e-commerce orders 1:1 into `raw_neto.orders` (City Perfume's sales truth). Fixed-daily Cloud Run job. | [README](ingest/neto_data_pull/README.md) · [orders/](ingest/neto_data_pull/orders/README.md) |

### Clients — one folder per client (copy of the template)

| Folder | Status | What it is | Open its README |
|---|---|---|---|
| [`clients/client_mongodb/`](clients/client_mongodb/) | **Live** | The **template** every client copies (MongoDB APAC, via Transmission). Models everything in BigQuery from `raw_snowflake`: Trade Desk paid media + Content Syndication (Salesforce, DNB). USD. 10 views. | [README](clients/client_mongodb/README.md) · [job/](clients/client_mongodb/job/README.md) · [dash/](clients/client_mongodb/dash/README.md) · [sql/](clients/client_mongodb/sql/README.md) |
| [`clients/client_cloudflare/`](clients/client_cloudflare/) | **Live** | Cloudflare APAC (via Transmission). The one client modelled **in Snowflake**: the job pulls Snowflake's *final-model* views into `src_*` tables and the BigQuery views are thin pass-throughs. TTD + LinkedIn + Reddit + LINE + CS. USD. 6 views. | [README](clients/client_cloudflare/README.md) · [job/](clients/client_cloudflare/job/README.md) · [dash/](clients/client_cloudflare/dash/README.md) · [sql/](clients/client_cloudflare/sql/README.md) |
| [`clients/client_STT/`](clients/client_STT/) | **Live** | STT GDC (ST Telemedia, via Transmission) — the **archetype** for the lean clients below. "Ads → website traffic": GA4 web analytics vs Google Ads + LinkedIn + DV360, all from `raw_snowflake`. SGD. 24 views. | [README](clients/client_STT/README.md) · [job/](clients/client_STT/job/README.md) · [dash/](clients/client_STT/dash/README.md) · [sql/](clients/client_STT/sql/README.md) · [INTAKE.md](clients/client_STT/INTAKE.md) |
| [`clients/client_schneider/`](clients/client_schneider/) | **Live** | Schneider Electric APAC (via Transmission). **Plan-vs-actual** portfolio across DV360 + Trade Desk + LinkedIn; seed tables (campaign map / budget / flighting / targets / channel split) joined to live delivery. **AUD**. GA4 ships disabled until SE's property id is known. 26 views. | [README](clients/client_schneider/README.md) · [job/](clients/client_schneider/job/README.md) · [dash/](clients/client_schneider/dash/README.md) · [sql/](clients/client_schneider/sql/README.md) · [INTAKE.md](clients/client_schneider/INTAKE.md) |
| [`clients/client_hireright/`](clients/client_hireright/) | **Live** | HireRight. Pure paid-media **delivery** baseline — no GA4, no media plan — across DV360 + Trade Desk + LinkedIn. **USD**. 14 views. | [README](clients/client_hireright/README.md) · [job/](clients/client_hireright/job/README.md) · [dash/](clients/client_hireright/dash/README.md) · [sql/](clients/client_hireright/sql/README.md) · [INTAKE.md](clients/client_hireright/INTAKE.md) |
| [`clients/client_cityperfume/`](clients/client_cityperfume/) | **Live** | City Perfume (AU e-commerce, via 100 Digital). "Ads → actual profit": first-party **Neto `v_sales`** revenue/margin truth vs Google Ads + Meta + Trade Desk + GA4. Single incremental **Margin ROAS**; aggregates-only JSON (no PII). **AUD**. 36 views. | [README](clients/client_cityperfume/README.md) · [job/](clients/client_cityperfume/job/README.md) · [dash/](clients/client_cityperfume/dash/README.md) · [sql/](clients/client_cityperfume/sql/README.md) |
| [`clients/client_resetdata/`](clients/client_resetdata/) | **Live** | ResetData (AU sovereign-AI / data-centre, via 100 Digital). Copied from STT: B2B "ads → traffic / leads" across **Google Ads + Meta + The Trade Desk** vs GA4 — reading three raw layers (`raw_google_ads`, `raw_windsor`, `raw_ga4`). **No revenue/ROAS** (B2B). **AUD** (TTD USD→AUD @1.50). 19 views. | [README](clients/client_resetdata/README.md) · [job/](clients/client_resetdata/job/README.md) · [dash/](clients/client_resetdata/dash/README.md) · [sql/](clients/client_resetdata/sql/README.md) |
| [`clients/client_proptrack/`](clients/client_proptrack/) | **Live** | PropTrack (REA Group, via Transmission). "Banking ABM": always-on LinkedIn + a concentrated Trade Desk programmatic burst, from `raw_snowflake`. **AUD** (no FX). 15 views. | [README](clients/client_proptrack/README.md) · [job/](clients/client_proptrack/job/README.md) · [dash/](clients/client_proptrack/dash/README.md) · [sql/](clients/client_proptrack/sql/README.md) |

### Operations & root

| Path | What it does | Open its README |
|---|---|---|
| [`status_dashboard/`](status_dashboard/) | **Meta dashboard** at `status.bidbrain.ai` — for every Snowflake-sourced client it shows whether a stale number is Transmission's fault (Snowflake source) or ours (pipeline behind), and that each dashboard figure equals Snowflake. No dataset/views; reads the other clients' resources. | [README](status_dashboard/README.md) · [job/](status_dashboard/job/README.md) · [dash/](status_dashboard/dash/README.md) |
| [`scripts/`](scripts/) | Windows onboarding + per-session credential checks (`setup.ps1`, `start_day.ps1`) **and `deploy_ingest_jobs.ps1`** (builds / deploys / schedules the 4 shared ingest Cloud Run jobs as `ingest-runner@`). | [README](scripts/README.md) |
| [`requirements.txt`](requirements.txt) | Pinned deps for the loaders + one-time BigQuery setup scripts (dev superset). Each Cloud Run unit pins its own separately. | — |
| [`.gitignore`](.gitignore) / [`.gcloudignore`](.gcloudignore) / [`.gitattributes`](.gitattributes) | Keep secrets out of git, keep source uploads clean, force LF in container files. | — |

---

## 6. Architecture in detail

### 6.1 The layered BigQuery model

**In plain terms:** we mirror each upstream source into a shared "drawer" once, then each
client has its own drawer of saved calculations that pick out and reshape just their slice.

- **`raw_<source>`** — shared raw data mirrored from one upstream source, used by multiple
  clients. **Five exist:**
  - **`raw_windsor`** — Meta (`perf_meta`), Trade Desk (`perf_the_trade_desk`), Reddit
    (`perf_reddit`), Google Ads (`perf_google_ads`) and GA4 (`perf_ga4` / `perf_ga4_events`),
    loaded by [`ingest/windsor_data_pull/`](ingest/windsor_data_pull/).
  - **`raw_snowflake`** — the Snowflake APAC tables mirrored 1:1 (Salesforce CS + Trade Desk +
    LinkedIn + Reddit + DV360 + Google Ads + GA4), loaded by [`ingest/snowflake_data_pull/`](ingest/snowflake_data_pull/).
  - **`raw_google_ads`** + **`raw_ga4`** — Google Ads and GA4 landed by Google's native
    **BigQuery Data Transfer Service** via [`ingest/dts_data_pull/`](ingest/dts_data_pull/) (free, daily); its
    `perf_*` views bridge the native rows with the Windsor history.
  - **`raw_neto`** — Neto / Maropost e-commerce orders (`orders`), City Perfume's sales truth,
    loaded by [`ingest/neto_data_pull/`](ingest/neto_data_pull/).
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
| When it runs | every ~10 min on a `*/10` UTC Cloud Scheduler tick — **self-gating** (rebuilds only when its upstream advanced), plus on demand | whenever someone visits the URL |
| Source folder | `clients/client_<client>/job/` | `clients/client_<client>/dash/` |
| Talks to | BigQuery + GCS (Cloudflare's job also reads Snowflake) | GCS (read-only) + Secret Manager |

**In plain terms:** the Job is the *kitchen* (makes the dish once a day); the Web App is the
*waiter behind a locked door* (checks your password, then brings you the dish).

### 6.3 Storage, secrets, identities

- **`bidbrain-analytics-<client>-dash`** — a **private** GCS bucket holding `<client>.json`.
- **`bidbrain-analytics-staging`** — shared bucket used by the Windsor loaders.
- **Secrets (Secret Manager — names only, values never in git):** `snowflake-bq-key` (read
  Snowflake), `windsor-api-key` (read Windsor), `neto-api-key` (read Neto), and per client
  `<client>-dash-password` + `<client>-dash-session-key`.
- **Service accounts (the "ID badges"), per client:** `<client>-dash-job@…` (the job: read
  Snowflake key, write BigQuery + bucket) and `<client>-dash-web@…` (the web app: read the
  bucket + the two dashboard secrets). The four shared ingest jobs run as one `ingest-runner@`
  service account. Least privilege throughout.

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
| Repo folder | `clients/client_<client>/` (with `job/`, `dash/`, `sql/`) | `clients/client_mongodb/` |

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
.\.venv\Scripts\python.exe ingest/snowflake_data_pull\loader.py            # refresh shared raw layer (all clients)
# the export job self-gates, so a plain execute rebuilds only if upstream advanced.
# to force a rebuild regardless, run the job with env FORCE_REBUILD=1 (see CLAUDE.md).
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait   # rebuild this client's JSON
```

**Redeploy the dashboard app after editing `dash/`:**
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_mongodb/dash --tag $IMG --region australia-southeast1
gcloud run services update mongodb-dash --image $IMG --region australia-southeast1
```

**See a job's logs:**
```powershell
gcloud logging read "resource.labels.job_name=mongodb-export" --project=bidbrain-analytics --limit=20 --freshness=1d --format="value(textPayload)" --order=asc
```

The **canonical deploy commands live in [`CLAUDE.md`](CLAUDE.md)** (single source of truth). Each
stage also ships a wrapper script in its subfolder — `dash/deploy_dash_<c>.ps1`,
`job/deploy_job_<c>.ps1`, `sql/deploy_views_<c>.ps1` — and `scheduler.ps1` sets the `*/10`
self-gating Cloud Scheduler trigger. Each client also ships a one-shot, idempotent stand-up script
`clients/client_<c>/deploy_<c>.ps1` (provisions a whole client — bucket, dataset, service accounts, IAM,
secrets, both Cloud Run units, the scheduler) — e.g.
[`clients/client_STT/deploy_stt.ps1`](clients/client_STT/deploy_stt.ps1),
[`clients/client_schneider/deploy_schneider.ps1`](clients/client_schneider/deploy_schneider.ps1); copy the
nearest one for a new client. *(`scheduler.ps1` can also re-point an existing client's Cloud
Scheduler to `*/10` — useful for any client stood up before the scripts defaulted to it.)*

---

## 10. Playbook: add a new client

The reusable recipe (replace `acme` with the client key). Full detail is in the template's
README — this is the shape:

1. **Confirm the data exists** in a shared `raw_*` layer (or add one line to a loader's table
   list). Check [`clients/client_STT/INTAKE.md`](clients/client_STT/INTAKE.md) for how we scope a new client.
2. **Copy the template:** `clients/client_mongodb/` → `clients/client_acme/`. Change `CLIENT = "acme"` in
   `job/main.py`. Rewrite the filter in `sql/01_*`/`02_*` for this client's slice.
3. **Provision GCP:** private bucket, `client_acme` dataset, two service accounts + IAM,
   password + session secrets. (STT's [`deploy_stt.ps1`](clients/client_STT/deploy_stt.ps1)
   does all of this in one idempotent script — copy it.)
4. **Bootstrap BigQuery:** run the job once (lands any `src_*`, then errors on the
   not-yet-existing views — expected), `python clients/client_acme/create_views.py`, re-run the job.
5. **Deploy the web app**, run `--no-invoker-iam-check`, drop in `dashboard.html`.
6. **Wire the daily refresh** (`scheduler.ps1`) and the **custom domain** (Cloudflare CNAME +
   Host Header Override).
7. **Commit.**

---

## 11. Current status & TODO

All eight client dashboards are **live** (Cloud Run service + export job + a `*/10` UTC
**self-gating** Cloud Scheduler that rebuilds only when its upstream advanced), each served on its
`…run.app` URL pending a custom domain. The meta **Status dashboard** is live at `status.bidbrain.ai`.

| Client | State |
|---|---|
| **MongoDB** | ✅ Live at https://mongodb-dash-p32gk2wuia-ts.a.run.app — the BigQuery template. 10 views → `mongodb-export` → `mongodb-dash`, self-gating `*/10` Scheduler `mongodb-export-daily`. Finishing: `mongodb.bidbrain.ai` custom domain; retiring the legacy public-R2 path (**rotate the leaked R2 keys**). |
| **Cloudflare** | ✅ Live at https://cloudflare-dash-p32gk2wuia-ts.a.run.app — verified HTTP 200 on 2026-06-13. TTD/LinkedIn/Reddit/LINE + CS + 3 single-campaign LinkedIn dashboards; models in Snowflake (`src_*`). USD, 6 views, self-gating `*/10` (Snowflake `LAST_ALTERED` probe). See [`dash/LIVE_URL.md`](clients/client_cloudflare/dash/LIVE_URL.md). |
| **STT** | ✅ Live at https://stt-dash-p32gk2wuia-ts.a.run.app. "Ads → website traffic": GA4 vs Google Ads + LinkedIn + DV360, all from `raw_snowflake`. SGD, 24 views → `stt-export` → `stt-dash`, self-gating `*/10`. The **archetype** for the lean clients. See [`clients/client_STT/README.md`](clients/client_STT/README.md). |
| **Schneider** | ✅ Live at https://schneider-dash-p32gk2wuia-ts.a.run.app. **Plan-vs-actual** (DV360 + Trade Desk + LinkedIn), **AUD**, seed-driven. 26 views, self-gating `*/10`. GA4 disabled until SE's property id is known; 11/21 campaign budgets seeded. See [`clients/client_schneider/README.md`](clients/client_schneider/README.md). |
| **HireRight** | ✅ Live at https://hireright-dash-p32gk2wuia-ts.a.run.app — verified HTTP 200 on 2026-06-04. Pure **delivery** baseline (DV360 + Trade Desk + LinkedIn), **USD**; no GA4, no plan. 14 views, self-gating `*/10`. See [`clients/client_hireright/README.md`](clients/client_hireright/README.md). |
| **City Perfume** | ✅ Live at https://cityperfume-dash-p32gk2wuia-ts.a.run.app. E-commerce "ads → profit": Neto `v_sales` truth + Google/Meta/TTD/GA4, **AUD**. 36 views, 6 tabs (incl. Year-on-Year), self-gating `*/10`. Single incremental Margin ROAS; aggregates-only JSON (no PII). See [`clients/client_cityperfume/README.md`](clients/client_cityperfume/README.md). |
| **ResetData** | ✅ Live at https://resetdata-dash-p32gk2wuia-ts.a.run.app — verified HTTP 200 on 2026-06-08. B2B "ads → traffic / leads" (Google Ads + Meta + Trade Desk vs GA4), three raw layers, **AUD** (TTD USD→AUD @1.50); no revenue/ROAS. 19 views, self-gating `*/10`. Branding wired (100 Digital). See [`clients/client_resetdata/README.md`](clients/client_resetdata/README.md). |
| **PropTrack** | ✅ Live at https://proptrack-dash-p32gk2wuia-ts.a.run.app. "Banking ABM": always-on LinkedIn + a Trade Desk programmatic burst, from `raw_snowflake`. **AUD** (no FX), 15 views, self-gating `*/10`. See [`clients/client_proptrack/README.md`](clients/client_proptrack/README.md). |
| **Status** (meta) | ✅ Live at https://status.bidbrain.ai — monitors the 6 Snowflake-sourced clients (data-sync verdict + accuracy vs Snowflake). No dataset/views; self-gating `*/15`. See [`status_dashboard/README.md`](status_dashboard/README.md). |

**Platform-wide TODO:** activate CD triggers (deploys are manual today — see [§9](#9-operating-it-deploy-refresh-debug));
wire each client's custom domain (`<client>.bidbrain.ai` — most still served on their `…run.app`
URLs); rotate the legacy leaked R2 credentials when retiring the old public-R2 path; confirm each
live Cloud Scheduler is on `*/10` (the stand-up scripts now seed it, but any client stood up earlier
may need `scheduler.ps1` re-run); re-grant the Windsor **Trade Desk** connector
(`windsor-tradedesk-ingest` exits non-zero until then).

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

*Maintained by the Bidbrain team. When in doubt: follow the [MongoDB template](clients/client_mongodb/README.md),
keep secrets out of git, and never make the data public.*
