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
- **`ingest_latest`** = newest BigQuery mirror `last_modified` (all clients now read the `raw_snowflake`
  mirrors — cloudflare included since 2026-06-17, when BQ took over its model; the `reads_direct` /
  build-`data_through` path is retained but currently unused).
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

The accuracy tab now carries the **comprehensive** list of every important query that feeds each dashboard —
**one check per source pull**, grouped by data domain (Trade Desk / LinkedIn / DV360 / GA4 / Content
Syndication / single-campaign dashboards / "All paid channels"). **~77 checks across the 6 clients.** Each
was extracted from that client's `sql/` views + `job/main.py` + dashboard JS, and reproduces the SAME view
filters (advertiser/account/campaign IDs, lead-status sets, singular-vs-plural columns) so the Snowflake
query is a true like-for-like. Each card shows an `n/n match` summary in its header. Principles:

- **Separated, not blended.** Distinct source pulls each get their own row (per platform; mongodb's DNB
  programmes vs KGA(IDC); proptrack's click vs view-through conversions). A genuinely *combined* metric —
  the "All paid channels" rollup — stays as ONE combined check (cross-table sum) since decomposing it adds
  nothing the per-platform rows don't already cover.
- **Spend is deliberately never equality-checked.** Most clients FX-convert it (AUD/SGD/JPY→USD) and even
  native spend is a float, so a rounded equality would read as a false ✗. Checks use un-transformed
  integers only: lead **counts**, **impressions**, **clicks**, **conversions**, **leads**, **sessions**,
  **key events**.
- **Compared against un-scoped JSON values** (the whole-flight `kpi.*` block, or the raw `rows[]`/`pacing`
  arrays for mongodb/cloudflare), never the on-screen KPI — those are scoped by the campaign/market/date
  pickers, whereas the JSON is the faithful pass-through.
- **mongodb Content Syndication — DNB and KGA(IDC) are now SEPARATE groups** (previously KGA/IDC was
  invisible; only one combined DNB check existed):
  - **DNB** = the 3 programme campaigns (`701RG00001DtQczYAF`/`HcDIVYA3`/`GvvrDYAR`), which carry a non-null
    programme label in `cs_by_programme`. Broken out into **Total** (`COUNT(*)`), **Accepted**, **New**
    (Unresponsive + New — NO 'Do Not Contact'), and **Rejected**.
  - **KGA(IDC)** = campaign `701RG00001NKKwQYAX`, whose `PROGRAMME_LABEL` is NULL (the only null-programme
    rows). Its **Delivered leads** = `Unresponsive + Do Not Contact + New` ONLY (no Accepted/Rejected
    lifecycle) — which is why its stored `total` is that 3-status count, NOT `COUNT(*)`.
  - **Mutable-source caveat:** mongodb **and cloudflare** CS both read the **BQ mirror**, and the Salesforce
    lead table is mutable (leads continuously added / re-statused), so the CS rows can sit a few leads off the
    **live** source even when the pipeline is healthy — a normal mirror lag, not a fault. The delta's magnitude
    is the signal; the **Sync tab** is the authority on pipeline health. Paid-media counts are append-only and
    match exactly.
- **cloudflare** — **BQ owns its model since 2026-06-17** (it used to read Snowflake modelled views directly;
  now it reads the `raw_snowflake.*` mirrors like everyone else). The accuracy SQL still queries Snowflake's
  modelled views as the independent **source of truth** — paid media against
  `…PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL` (per channel: TTD/LinkedIn/Reddit/LINE; LinkedIn is the only
  channel with leads), CS against `…CS_REPORTING.V_PACING_FINAL_MODEL` (Accepted = Accepted+Replied+
  Unresponsive — OPPOSITE of mongodb) — so a green check validates the whole chain (mirror sync + BQ port).
  The 3 single-campaign LinkedIn dashboards check their exact `CAMPAIGN_GROUP_NAME` slices of the
  `raw_snowflake.linkedin_ads_apac` mirror.
- **proptrack** TradeDesk impressions come from the **singular** `IMPRESSION` column (plural is NULL for that
  advertiser) while LinkedIn uses the plural `IMPRESSIONS`; the advertiser is spelled **`PopTrack`** on
  TradeDesk vs **`PropTrack`** on LinkedIn — the blended-impressions check mixes both columns deliberately.
- **schneider** only its **ACTUAL** delivery is Snowflake-checkable; the plan/budget/target numbers
  (`seed_*` tables) and the Pacific portfolio tag are seed-side and have no Snowflake source. TradeDesk imps
  use `COALESCE(IMPRESSIONS, IMPRESSION)`; blended conversions key is `kpi.ad_conversions` (DV360 + TradeDesk;
  LinkedIn's outcome is leads).

Clients covered (Snowflake-sourced): **mongodb, cloudflare, stt, hireright, schneider, proptrack**.
(cityperfume + resetdata + tlm + vmch read Windsor/GA4/Neto/Google-Ads natively — no Snowflake source to
compare against — so they're out of scope here.)

> **Not Snowflake-checkable** (shown nowhere in the accuracy tab, by design): FX-converted spend; derived
> ratios (CTR/CPM/CPC/ROAS/VCR — recompute from the checked components); mongodb's Universal-Pixel section
> (a static CSV seed, not in `raw_snowflake`); and all seed/plan/budget/target tables.

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
