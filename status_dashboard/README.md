# status_dashboard — the meta / pipeline-status dashboard

One gated screen (**status.bidbrain.ai**) that answers, for every Snowflake-sourced client, the two
questions that keep getting 100% Digital blamed for Transmission's stale data:

1. **Data Sync Status** — is a stale dashboard *Transmission's* fault (the Snowflake **source** hasn't
   updated) or *100% Digital's* (our pipeline hasn't ingested/rebuilt)?
2. **Data Accuracy** — does the number on each client dashboard equal the number pulled **straight from
   Snowflake**? (It shows the exact query so anyone can reproduce it.)

It is **not a client** — there is no BigQuery dataset and no SQL views. It reads other clients' resources
and writes one JSON. But it rides the exact same serving pattern as every client dash (gated Flask service
+ private bucket + Cloud Run export job + Cloud Scheduler).

## How it decides who's to blame

For each client the export job probes three stages and compares them:

```
   TRANSMISSION                100% DIGITAL ───────────────────────────────►
   Snowflake source            BigQuery raw mirror            Dashboard build
   INFORMATION_SCHEMA          raw_snowflake.* __TABLES__     <client>.json
   .LAST_ALTERED               .last_modified                 last_updated / data_through
```

- **`transmission_latest`** = newest `LAST_ALTERED` across the client's source tables (probed live; metadata
  only, never resumes the warehouse).
- **`ingest_latest`** = newest BigQuery mirror `last_modified` (mirror clients), or the build's `data_through`
  (cloudflare, which reads Snowflake modelled views directly — no mirror in its CS path).
- **caught_up** = `ingest_latest >= transmission_latest − 45 min` (the tolerance absorbs the normal */10–*/15
  ingest cadence).

Verdict:

| verdict | meaning | who |
|---|---|---|
| `ok` | caught up, source fresh | — |
| `transmission_stale` | **caught up**, but the Snowflake source itself is old | **Transmission** |
| `digital_behind` | Snowflake moved, we haven't ingested past it | **100% Digital** |
| `no_data` | client JSON missing / probe failed | — |

The headline case: when we're **caught up** and the data still looks old, the verdict is
`transmission_stale` — *our pipeline is green, the source is what's behind.*

## Data Accuracy — provenance

Every accuracy query was extracted from each client's `sql/` views + `job/main.py` and **adversarially
verified** against the live view filters (so the dashboard never shows a false ✗). Key points per the
verification:

- **Spend is never used for an equality check** — most clients FX-convert it (AUD/SGD/JPY→USD), so it
  wouldn't match. Checks use un-transformed integers: lead **counts**, **impressions**, **clicks**, **leads**.
- **Compared against un-scoped JSON sums**, not the on-screen KPI. On the client dashboards the headline
  KPIs are scoped by campaign/market/date pickers; the raw JSON arrays are the faithful pass-through.
- **mongodb CS** — validated over **all 4** CS `CAMPAIGN_ID`s (3 DNB `701RG00001DtQczYAF`/`HcDIVYA3`/`GvvrDYAR`
  **+ the funded KGA/IDC `701RG00001NKKwQYAX`**) across **4 buckets** — Total / Accepted (`= 'Accepted'`) /
  Rejected (`= 'Rejected'`) / New (`IN ('Unresponsive','Do Not Contact','New')`) — matching the `cs_leads` view byte-for-byte,
  each compared to the un-scoped `sum(cs[].<bucket>)` in the JSON. **KGA/IDC (NULL programme) is the largest
  CS campaign — ~479 leads, almost all New/unprocessed — so it must be counted**; the live `02_stg_salesforce.sql`
  view filters all 4 IDs and `cs_leads` groups by market with no programme filter, giving **881 total / 353
  accepted / 0 rejected / 527 new**. (Excluding KGA/IDC would drop Total to 402 and New to 49 and read RED.)
- **cloudflare CS** reads Snowflake modelled views directly, so its accuracy query hits the very view the
  dashboard was built from — bulletproof regardless of mirror sync.
- **proptrack** TradeDesk impressions come from the **singular** `IMPRESSION` column (plural is NULL for that
  advertiser); the advertiser is spelled **`PopTrack`** on TradeDesk.

Clients covered (Snowflake-sourced): **mongodb, cloudflare, stt, hireright, schneider, proptrack**.
(cityperfume + resetdata read Windsor/GA4/Neto/Google-Ads natively — no Snowflake — so they're out of scope.)

## Cost

The `LAST_ALTERED` freshness probe is metadata-only and never resumes `APAC_IN_WH`, so it runs every */15
tick for free. The accuracy `COUNT`/`SUM` queries **do** resume the warehouse, so they **self-gate**: a
client's numbers are only recomputed when that client's Snowflake source advanced since the last
`status.json` (otherwise the previous numbers are carried forward). Set `FORCE_REBUILD=1` to recompute all.

## Files

```
status_dashboard/
  deploy_status.ps1            one-shot, idempotent stand-up (APIs, bucket, SAs, IAM, secrets, job, scheduler, service)
  scheduler.ps1                create/refresh the */15 Cloud Scheduler trigger
  job/
    main.py                    the CLIENTS spec + freshness probe + gated accuracy + status.json writer
    freshness.py               vendored probe helpers (identical to the client jobs')
    requirements.txt  Dockerfile  deploy_job_status.ps1
  dash/
    main.py                    gated Flask service (login + /data.json proxy), serves dashboard.html no-store
    dashboard.html             the two tabs (Data Sync Status, Data Accuracy) — pure HTML/CSS/JS, no chart libs
    requirements.txt  Dockerfile  deploy_dash_status.ps1
```

## Deploy

First-time stand-up (provisions everything; idempotent — safe to re-run):

```powershell
.\status_dashboard\deploy_status.ps1        # prompts for a dashboard password (or set $env:DASH_PASSWORD)
.\status_dashboard\scheduler.ps1            # */15 trigger
```

Then point **status.bidbrain.ai** at the `status-dash` service in Cloudflare DNS (same as the client dashboards).

After an edit (manual, build-as-yourself — same rule as the rest of the repo; cloudbuild-from-laptop fails on
`iam.serviceaccounts.actAs`):

- edited `dash/dashboard.html` or `dash/main.py` → `.\status_dashboard\dash\deploy_dash_status.ps1`
- edited `job/main.py` (CLIENTS spec / queries / verdict) → `.\status_dashboard\job\deploy_job_status.ps1`

The job's runtime SA (`status-dash-job@`) needs: BigQuery `jobUser`+`dataViewer`, `objectViewer` on each client
bucket, `objectAdmin` on the status bucket, and `secretAccessor` on the shared `snowflake-bq-key`. The stand-up
script grants all of these.
