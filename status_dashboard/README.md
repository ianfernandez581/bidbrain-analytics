# status_dashboard — pipeline-status data + deploy plumbing

> **The UI now lives in the platform front-door**, not here. As of 2026-06-23 the standalone
> `status.bidbrain.ai` screen was retired and folded into [`bidbrain-platform/`](../bidbrain-platform/)
> (Overview health badges + a **Data Accuracy** tab at https://dashboards.bidbrain.ai). What remains in
> this folder is the **data + deploy plumbing** behind that tab: the **`status-export`** job (writes
> `status.json`) and the **`status-deploy`** job (the "Make this live" worker the platform triggers).
> The `dash/` folder (the old gated Flask screen + `deploy_status.ps1`'s service step) is **legacy /
> superseded** — kept for reference, no longer the access path.

For every Snowflake-sourced client (and now the BigQuery-native 100% Digital clients too — see
[BigQuery-native clients](#bigquery-native-clients-the-100-digital-agency)) it answers the two questions
that keep getting 100% Digital blamed for Transmission's stale data:

1. **Data Sync Status** — is a stale dashboard *Transmission's* fault (the Snowflake **source** hasn't
   updated) or *100% Digital's* (our pipeline hasn't ingested/rebuilt)?
2. **Data Accuracy** — does the number on each client dashboard equal the number pulled **straight from
   Snowflake**? (It shows the exact query so anyone can reproduce it.)

It is **not a client** — there is no BigQuery dataset and no SQL views. It reads other clients' resources
and writes one JSON (`status.json`) to its private bucket `bidbrain-analytics-status-dash`. The platform
front-door reads that JSON to render the merged Overview + Data Accuracy tabs.

Because CS verification queries are now **built from each client's `definitions.json`** (single source of
truth; LIVE copy at `gs://bidbrain-analytics-status-dash/definitions/<c>.json`), editing a client's
definitions from the platform's Data Accuracy tab changes BOTH the dashboard (via seed tables) and the
check. "Make this live" triggers the **`status-deploy`** job (`status_dashboard/deploy/`, SA
`status-deploy@`) — the privileged worker that applies a staged edit and re-runs the affected export jobs.

mongodb's *"Trade Desk · Delivery outside the seeded campaign scope"* check is built the same
runtime-splice way (`_build_mdb_scope_check`), but from the LIVE BigQuery seed table
`client_mongodb.seed_campaign_ids` (the committed `targets/campaign_ids.csv` mirror of Transmission's
campaign-reference sheet). It must read **0**: any MongoDB advertiser delivery whose normalised campaign
name is outside the seeded set turns it red (a campaign is live that the sheet/CSV doesn't know about,
and it is EXCLUDED from the dashboard until the seed is updated).

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

## Source data recency — is the source current to *today*?

`LAST_ALTERED` / `last_modified` say **when a table was last written**, which is not the same as **the
newest date the data actually covers** — a table re-written this morning can still only hold rows through
three days ago. So each client entry's `freshness` also carries, per source:

- **`source_dates`** — `[{source, data_through}]`, the newest DATE present in each source
  (`MAX(TO_DATE(DAY))` for the Snowflake tables, `MAX(metric_date)` for the BQ raw tables — `raw_neto` on
  `date_placed`; the HubSpot snapshot has no date series and is skipped).
- **`source_data_through`** — the freshest of those dates (a quick headline).

Probed under the **same freshness gate** as the accuracy counts (recomputed only when the client's source
advanced, else carried forward, and memoised per tick so a shared table is probed once), so an idle tick
adds no extra warehouse resumes. The **Data Accuracy tab** renders this as a **"Source data through
&lt;date&gt;"** strip per client with a per-source breakdown. The flag is computed **in the browser** (UTC
basis, matching the data), so a carried-forward date ages on its own with no rebuild.

### "behind" vs "idle" — a frozen source is only a fault if delivery was expected (2026-08-09)

The original flat rule (**red at 2+ days behind**) could not tell a broken pipeline from a finished one, so
it cried wolf on three non-faults: a campaign that had **ended**, a CRM over a **weekend**, and a dormant
**fallback** path whose primary was current. Each source now carries a delivery expectation —
`SOURCE_EXPECTATIONS` in `job/main.py`, emitted every tick as `freshness.source_expectations` (static
config, so it is never subject to the `source_dates` carry-forward) and applied by `freshFlag()` in
`bidbrain-platform/dash/templates/_status_merge.html`:

| mode | meaning | verdict |
|---|---|---|
| `daily` (default, omit) | expect data through yesterday | **behind at 3+ calendar days** (`STALE_DAYS`) |
| `weekdays` | business days only — a CRM gets no leads at the weekend | **behind at 3+ *business* days** (Fri→Mon is 1, not 3) |
| `ended` | the flight is over, the source is *supposed* to be frozen | **idle**, always |
| `fallback` | standby path, read only for dates its primary lacks | **idle**, always |

An **idle** source is neutral: excluded from the "N sources behind" tally **and** from the headline
"source data through" date (a finished campaign must not make a healthy client read stale), and shown
dimmed in the per-source strip with its reason on hover. Live entries today: Salesforce CS = `weekdays`
(mongodb / cloudflare / schneider); cloudflare's `Reddit Ads - APAC_ALL` = `ended` (Q2-only lane, wrapped
2026-06-30 — **flip it back to `daily` the day Reddit is re-booked, or the restart won't be flagged**);
vmch's `raw_windsor.perf_ga4` = `fallback` (the DTS primary `raw_ga4.perf_ga4` is the real signal).
**`DV360 - APAC` is deliberately NOT listed** — it is frozen at 2026-07-01 with live campaigns still
running, a genuine upstream fault at Transmission, and must keep reading behind.

## BigQuery-native clients (the 100% Digital agency)

The 6 clients above are **Snowflake-sourced** (Transmission's warehouse). The **100% Digital agency**
clients — **cityperfume, resetdata, tlm, geocon, vmch** — have **no Snowflake in their path**: their
source is the **BigQuery raw layer** (`raw_windsor` / `raw_neto` / `raw_ga4` / `raw_google_ads`) that our
OWN ingest jobs land (Windsor.ai connectors, the Neto job, native BigQuery DTS). They're a separate
`BQ_CLIENTS` spec in `job/main.py` and produce the SAME `status.json` shape, with two differences:

- **Accuracy queries run against BigQuery** (`scalar_bq`), not Snowflake. The `snowflake_query` /
  `snowflake_value` fields carry the **BigQuery** query/result; each client entry sets
  `source_label: "BigQuery"` and the front-end relabels the column + the "show the … query" toggle. The
  query reproduces the raw-layer aggregate the export job wrote into `<client>.json`, so a mismatch
  localises the fault to **our transform/export**, and a stale raw table localises it to the **upstream
  API or its ingest job** ("Windsor is down / a DTS transfer is out"). **46 checks** across the 5 clients.
- **Verdict is 100%-Digital-only** (`_verdict_bq`): `ingest_latest` = newest raw-table `last_modified`;
  `build_at` = `<client>.json last_updated`. `digital_behind` = raw advanced but our export didn't rebuild;
  new **`source_stale`** = the raw layer itself is > 2 days old (upstream/ingest down); `ok` = build current.

Whatever the query can't reproduce exactly is flagged in its note: **spend is usually not checked** (FX /
float); **native-AUD money** (City Perfume revenue, TLM revenue) and **counts** are. **ResetData's Reddit
spend IS checked since 2026-08-27** - removing the hardcoded ×2 markup from `stg_reddit` is what made it
checkable, which was one of the reasons for removing it. Two
documented non-exact cases: **VMCH** headline TTD imps/clicks add a **modelled-April** overlay with no raw
source (so the check validates the *measured* delivery instead), and any GA4/HubSpot metric noted with its
own floor/slug. Filters transcribed line-by-line from each client's `sql/` + `job/main.py` (watch: the
ResetData Meta account name has a **U+2013 en-dash**; the VMCH TTD advertiser has a **trailing space**;
TTD `conversions` is a **double-encoded JSON** summed over distinct pixels `{01,03,05}`).

**Deploy note:** the status SA (`status-dash-job@`) needs `bigquery.jobUser` + `bigquery.dataViewer` and
`objectViewer` on the 5 client buckets — `job/deploy_job_status.ps1` grants these idempotently on deploy.

## Data Accuracy — provenance

The accuracy tab now carries the **comprehensive** list of every important query that feeds each dashboard —
**one check per source pull**, grouped by data domain (Trade Desk / LinkedIn / DV360 / GA4 / Content
Syndication / single-campaign dashboards / "All paid channels"). **~77 checks across the 6 clients**
(incl. cloudflare's Korea / RIG / Others CS region buckets + CF1 Double-Touch CS lane, and schneider's
per-program Content-Syndication leads — the latter two added 2026-06-22). Each
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
- **Both sides must be the SAME snapshot, or the check is `pending`, not `off` (2026-08-09).** A check
  equates a source aggregate with a value in `<client>.json`, which only means anything if that build SAW
  that source data. Two things break that, and both used to render as a red ✗ against numbers that were
  perfectly correct:
  1. **Read order.** The source aggregates take minutes (Snowflake resumes; BQ scans) and every client
     export job rebuilds on its own `*/10` tick, so reading the client JSON *before* them compared an OLD
     build against a NEW source read. The job now collects the source values FIRST, then **re-reads
     `<client>.json`** (`reread_build`) so a rebuild that landed mid-run is picked up.
  2. **The rebuild window.** The nightly Windsor loaders bump a raw table's `last_modified` **several times
     per run** (`perf_the_trade_desk` landed at 21:49:57, 21:50:05 *and* 21:52:03 on 2026-08-09), so for a
     few minutes the source legitimately holds rows the build does not. When the build provably predates
     the source snapshot AND that source landed within `REBUILD_GRACE` (60 min), the check is emitted with
     `match: null` + `pending: "rebuild"` and the tab renders **"⏳ rebuild pending"** / a `N rebuilding`
     header count. **Past the grace we assert again** — a permanently-behind export job must not be able to
     silence its own accuracy checks (and the Sync tab is already red by then).
  The tell for this class of false alarm is that the diff is always ONE load's worth of rows and always in
  the same direction (**source > dashboard**) across every append-only count at once. It self-heals on the
  next tick. On 2026-08-09 this was 8 red checks across resetdata/tlm/vmch that were all exactly right.
  Related: the BQ carry-forward gate is its own `accuracy_gate` field, NOT `freshness.ingest_latest` — the
  re-probe advances the reported ingest time, and gating on that would carry forward source numbers never
  computed against the final table state (a mismatch in the OPPOSITE direction once the client rebuilds).
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
  now it reads the `raw_snowflake.*` mirrors like everyone else). The accuracy SQL queries the **raw Snowflake
  source tables** as the independent **source of truth**, re-stating each channel's scope the way the staging
  views do (TTD `ADVERTISER_NAME='Cloudflare'` + a parseable `MARKET_L3`; LinkedIn `ACCOUNT_NAME='Cloudflare
  APAC'` + `CLOUD_ACQ_%`; Reddit `ACCOUNT_NAME='Transmission_Cloudflare'`; LinkedIn is the only channel with
  leads) — so a green check validates the whole chain (mirror sync + BQ port).
  **2026-08-04:** these 7 paid-media checks were repointed **off** `CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.
  V_PAID_ADS_FINAL_MODEL`. That schema is Cloudflare's/Transmission's legacy model — nothing in our pipeline
  has read it since the BQ port, we cannot change it, and it drifts on their schedule (LINE already froze
  there and its checks had to be deleted), so it could only ever produce a false ✗ against a correct
  dashboard. Values verified identical on the swap.
  - **The 2 Trade Desk checks query the WHOLE advertiser with NO campaign-name parsing, deliberately.**
    Later the same day a *parsing* break was found (a `"<brief>_"` prefix shifted every name token, hiding
    34% of TTD delivery — see `clients/client_cloudflare/sql/README.md`). The old check mirrored the view's
    parse on both sides, so it went **circular and stayed green** through the whole incident. Advertiser
    total vs dashboard total is the only shape that catches a parsing regression. This holds while every
    Cloudflare TTD campaign belongs on the dashboard (true today, 0 rows off-chip); if that stops being
    true, scope by campaign **and** add a separate orphan-token check. Post-fix values: TTD 36,053,269 imps
    / 106,208 clicks, LinkedIn 3,746,467 / 16,908 / 487 leads, Reddit 5,811,169 / 7,294.
  - LinkedIn checks match on the brief-number-stripped name, in lockstep with `stg_linkedin.CAMPAIGN_NAME_NORM`.
  The 3 single-campaign LinkedIn dashboards check their exact `CAMPAIGN_GROUP_NAME` slices of the
  `raw_snowflake.linkedin_ads_apac` mirror.
  - **Core CS counts (Total / Accepted / Rejected / New)** now query the **raw source**
    `APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"` on the canonical **13-campaign filter** (sql/10) with
    **NO region filter** — so they span every region **including the ~55-lead OTHER residual** (Accepted =
    Accepted+Replied+Unresponsive, OPPOSITE of mongodb). Note the dashboard's *displayed*
    CS total excludes OTHER (its totals sum over the 11 market chips), so it runs ~55 below this whole-universe
    count. This replaces the old
    `…CS_REPORTING.V_PACING_FINAL_MODEL` query (V_PACING carries Cloudflare's legacy geographic model — no
    longer our source of truth). Compared against the count over all non-dummy `pacing.rows[]`.
  - **Korea / RIG / OTHER-residual CS region buckets (2026-06-19; KR reverted to the 6 El\* rule 2026-07-02)** —
    three checks for the dashboard's special region buckets. Their SQL goes **straight to the raw source** (the
    modelled `V_PACING`/`V_SALESFORCE_LEADS_LIVE` carry the OLD geographic region logic and can't verify these).
    The query **is** the canonical definition — **Korea** = Country `'Korea, Republic of'` + the 6 El\* campaigns
    (~164; **reverted 2026-07-02** at the client's request — between 2026-06-25 and 2026-07-02 KR was ALL Korea in
    the 12 campaigns); **RIG** = non-Korea + `ASSET_2 IN ('A-MAM-2','A-MAM-3')` (gaming Modernize-Apps asset; only
    `A-MAM-3` populated) + the 3 Final Funnel campaigns (~180); **OTHER** = the residual the named markets
    don't claim (Korea outside the 6 El\* + any unmapped country, ~55 live 2026-07-02). OTHER is **not a dashboard chip** (those
    leads are excluded from the dash); this check just reconciles the dash's OTHER count to the source (it is no
    longer a *must-be-0* assertion). Compared against the count of `pacing.rows[]` with `MARKET_REGION = 'KR'` /
    `'RIG'` / `'OTHER'`. A green check proves the BQ view buckets equal the source definition.
  - **CF1 Double-Touch CS lane (2026-06-22)** — the "CF1 India" single-campaign view gained a `cs` block
    (Double Touch MQLs) from `sql/14_cf1_cs`. Four checks (Accepted / Rejected / New / Total) hit the **raw
    source** `APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"` on the 2 CF1 CS campaign IDs
    (`701RG00001NJd6NYAT` / `701RG00001NIYRKYA5`) — the same IDs are also in the core 13-campaign filter, but
    this is a separate CF1-scoped lane. **Accepted** = the delivered double-touch MQL count (vs the 110
    target); the client's headline **Total** = New + Accepted (excludes Rejected, so NOT `COUNT(*)`).
    Compared against `campaigns.cf1_india.cs.*`.
- **proptrack** TradeDesk impressions come from the **singular** `IMPRESSION` column (plural is NULL for that
  advertiser) while LinkedIn uses the plural `IMPRESSIONS`; the advertiser is spelled **`PopTrack`** on
  TradeDesk vs **`PropTrack`** on LinkedIn — the blended-impressions check mixes both columns deliberately.
- **schneider** **RESTRUCTURED 2026-06-22** from a 6-tab Pacific paid-media dashboard into a
  `client_mongodb`-style Content-Syndication clone scoped to 5 lead-gen programs — so the old `kpi.*`
  delivery checks are GONE (the block no longer exists) and the accuracy tab now checks **Content
  Syndication leads per program**: one check per program (water_env / eba / heavy / global_rebrand / airset)
  plus a combined total, each hitting the **raw source** `Salesforce_CS_APAC_ALL` on that program's SF
  campaign IDs (`data/salesforce_map.csv`) and **reproducing the view's flight clamp** (`TO_DATE(DAY)` within
  each program's `seed_plan_budget` flight from `data/plan_budget.csv`) so it's an exact like-for-like — e.g.
  the clamp drops EBA's ~4 pre-flight spillover leads, matching the dashboard's 46 not 50. **Paid delivery
  (`pm_delivery`) is intentionally NOT equality-checked**: it's now seed-scoped via `seed_campaign_map`'s
  match_pattern first-match-wins join, which has no independent Snowflake definition to compare against.
  DV360 / LinkedIn / TradeDesk stay in `sources` (and `Salesforce_CS_APAC_ALL` is added) so the **Sync tab**
  still tracks every upstream the dashboard reads. **Flight-bound maintenance:** the hardcoded flight dates
  mirror `data/plan_budget.csv` — if the client changes a flight, update the dates in the schneider checks.

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
  deploy_status.ps1            one-shot, idempotent stand-up (APIs, bucket, SAs, IAM, secrets, job, scheduler;
                               its standalone-service step is legacy — the UI is now in the platform)
  scheduler.ps1                create/refresh the */15 Cloud Scheduler trigger for status-export
  job/                         the status-export job (writes status.json)
    main.py                    the CLIENTS spec + freshness probe + gated accuracy + status.json writer
    freshness.py               vendored probe helpers (identical to the client jobs')
    requirements.txt  Dockerfile  deploy_job_status.ps1
  deploy/                      the status-deploy job — the platform's "Make this live" worker (SA status-deploy@)
    main.py                    applies a staged definitions edit + re-runs the affected export jobs
    definitions_seed.py        seed/refresh definitions.json
    grant_dataset_writer.py    grant the deploy SA dataset-level write on the clients it deploys
    Dockerfile  requirements.txt  deploy_job_status_deploy.ps1
  dash/                        LEGACY — the retired standalone status.bidbrain.ai screen (superseded by the
                               platform front-door's merged tabs); kept for reference
    main.py  dashboard.html  requirements.txt  Dockerfile  deploy_dash_status.ps1
```

## Deploy

First-time stand-up (provisions the data + deploy plumbing; idempotent — safe to re-run):

```powershell
.\status_dashboard\deploy_status.ps1                       # bucket, SAs, IAM, secrets, status-export job, scheduler
.\status_dashboard\scheduler.ps1                           # */15 trigger for status-export
.\status_dashboard\deploy\deploy_job_status_deploy.ps1     # the status-deploy "Make this live" worker + platform IAM
```

The **UI is the platform front-door** — there is no `status.bidbrain.ai` to point DNS at anymore. The
front-door reads `status.json` from the status bucket and renders the Overview + Data Accuracy tabs. (The
`deploy_status.ps1` script still contains a legacy step that deploys the standalone `status-dash` service;
it's superseded and can be skipped.)

After an edit (manual, build-as-yourself — same rule as the rest of the repo; cloudbuild-from-laptop fails on
`iam.serviceaccounts.actAs`):

- edited `job/main.py` (CLIENTS spec / queries / verdict) → `.\status_dashboard\job\deploy_job_status.ps1`
- edited `deploy/main.py` (the "Make this live" worker) → `.\status_dashboard\deploy\deploy_job_status_deploy.ps1`
- the merged UI itself lives in `bidbrain-platform/` → redeploy with `bidbrain-platform\dash\deploy_dash_platform.ps1`

The job's runtime SA (`status-dash-job@`) needs: BigQuery `jobUser`+`dataViewer`, `objectViewer` on each client
bucket, `objectAdmin` on the status bucket, and `secretAccessor` on the shared `snowflake-bq-key`. The stand-up
script grants all of these.
