# clients/client_cloudflare/job/ — the Export Job (`cloudflare-export`)

> A **Cloud Run Job** that pulls Cloudflare's already-modelled data from Snowflake, lands a
> queryable copy in BigQuery, and writes one combined `cloudflare.json` to the private bucket.

**Plain English:** this is Cloudflare's *kitchen*. Unlike MongoDB (whose maths happens in our
warehouse), Cloudflare's reporting model already exists, finished, inside Snowflake. So this job
fetches those finished views, keeps a copy in BigQuery for consistency with every other client,
and packs the result into the single file the dashboard reads. It merges what Cloudflare used to
publish as **two separate public files** (`pacing.json` + `paid_media.json`) into **one private**
`cloudflare.json`.

**Where this sits:** Snowflake `CLOUDFLARE_SANDBOX.*` final-model views → **[this job]** lands
`src_*` + reads thin [`../sql/`](../sql/README.md) views → `cloudflare.json` →
[`../dash/`](../dash/README.md) serves it.

> **Why this differs from the MongoDB job:** see [the client README's "Deliberate divergence"](../README.md#deliberate-divergence-from-client_mongodb).
> Short version: don't re-derive in BigQuery a model that's already tested in Snowflake.

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. Connects to Snowflake (key-pair auth), **gates on freshness** (see below), runs 6 Snowflake pulls (5 final-model views + 1 creative-grain query over the `V_STG_*` staging views), lands them as `src_*` BigQuery tables, reads the thin views, queries the shared `raw_snowflake.linkedin_ads_apac` mirror for the three single-campaign LinkedIn dashboards, and uploads `cloudflare.json`. `CLIENT = "cloudflare"` drives all the names. |
| [`freshness.py`](freshness.py) | The freshness gate (vendored per job folder, like `sf_connect`). Probes `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` (metadata-only — no warehouse credits, never resumes compute), reads/writes the `_freshness.json` watermark sidecar in the bucket, and answers `is_stale()`. Reusable across clients: only the bucket, watermark key, and table list differ. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim`, non-root, `CMD python main.py`. Ships both `main.py` and `freshness.py`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run jobs deploy cloudflare-export` with the Snowflake secret + env vars wired in. |
| [`requirements.txt`](requirements.txt) | `snowflake-connector-python[pandas]`, `pandas`, `pyarrow`, BigQuery, Storage, cryptography, secret-manager. (Heavier than MongoDB's job because this one talks to Snowflake.) |
| `.dockerignore` | Keeps the build context lean. |

---

## What it pulls and lands

| Snowflake source | → BigQuery `src_*` | → thin view ([`../sql/`](../sql/README.md)) |
|---|---|---|
| `…PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL` | `src_paid_media` | `paid_media_model` |
| `…CS_REPORTING.V_PACING_FINAL_MODEL` | `src_pacing` | `pacing_model` |
| `…PAID_MEDIA_REPORTING.V_BENCHMARKS_CHANNEL` | `src_benchmarks_channel` | `benchmarks_channel` |
| `…PAID_MEDIA_REPORTING.V_BENCHMARKS_MARKET` | `src_benchmarks_market` | `benchmarks_market` |
| `…PAID_MEDIA_REPORTING.V_LI_WEEKLY_TARGETS` | `src_li_weekly` | `li_weekly_targets` |
| creative-grain query over `…PAID_MEDIA_REPORTING.V_STG_{LINKEDIN,TRADEDESK,REDDIT,LINE}_CF` | `src_paid_creatives` | `paid_creatives_model` |

(Three further **static** inputs — LINE spend, pacing targets, account tiers — are landed
separately and rarely by [`../seed_static.py`](../seed_static.py), not by this job.)

Separately, the job reads the shared **`raw_snowflake.linkedin_ads_apac`** mirror directly in
BigQuery (no Snowflake round-trip) to assemble the `campaigns` block — three single-campaign
LinkedIn dashboards (`peyc` = ANZ PEYC, `cf1_india` = CF1 India, `coles_hyper` = Coles Hyper).

---

## The JSON contract it produces

One object served at `/data.json`, with the two halves matching the old R2 files exactly so the
dashboard's `adaptPayload` / `rawRows` code is unchanged:

```jsonc
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",  // when THIS build ran (build time)
  "data_through": "YYYY-MM-DDTHH:MM:SSZ",  // newest LAST_ALTERED across the 4 gating tables (true data instant, UTC)
  "paid_media": {                          // == the old paid_media.json (+ creatives)
    "row_count": 0,
    "window": { "start": "…", "end": "…", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { channel, date, week_start, market, imps, clicks, spend_usd, leads,
                form_opens, link_clicks, action_clicks, video_starts, video_completions,
                spend_jpy, fx_usd_jpy } ],
    "creatives": [ { channel, market, creative, imps, clicks, spend_usd, leads } ],  // creative-grain, whole-window
    "benchmarks":        { "<channel>": { ctr, cpm, cpc } },   // TTD, LinkedIn, Reddit, LINE
    "benchmarks_market": { "<market>":  { ctr, cpm, cpc } },
    "li_weekly": [ { week, period, week_start, target, cum_target } ]
  },
  "pacing": { "row_count": 0, "rows": [ /* every V_PACING_FINAL_MODEL column, dates → ISO */ ] },
  "campaigns": {                           // three single-campaign LinkedIn dashboards
    "peyc":        { label, campaign_group, window, totals, daily: [...], by_campaign: [...] },
    "cf1_india":   { ... },                // from raw_snowflake.linkedin_ads_apac (BQ mirror)
    "coles_hyper": { ... }
  }
}
```

**Label contract (must match the dashboard):** `benchmarks`/`channel` keys are `TTD`,
`LinkedIn`, `Reddit`, `LINE`; markets are the seven in `all_markets`. These come straight from
the Snowflake views — if a view emits different strings, fix the mapping in
[`../sql/`](../sql/README.md) (the only place strings are mapped). JSON serialisation handles
`Decimal` → float and dates → ISO via the `_json_default` / `jval` helpers.

---

## Freshness gate — why most runs do nothing (and that's the point)

The job is scheduled **`*/10 * * * *`** (was a single daily `0 22 * * *`), but it is
**self-gating**: each tick it only rebuilds if the upstream data actually moved. Net effect —
the dashboard refreshes **within ~10 min of new Snowflake data** instead of lagging it up to a day.

**How the gate works** ([`freshness.py`](freshness.py)):

1. Probe `LAST_ALTERED` for the four dynamic PUBLIC base tables in `APAC_ALL_PLATFORM`
   (one `INFORMATION_SCHEMA.TABLES` query). This is **metadata-only**: no warehouse credits, and
   it does **not** resume `APAC_IN_WH`. Key-pair connect doesn't resume it either. So a
   "nothing changed" tick costs ~nothing and never wakes compute.
2. Compare against the watermark in `gs://…-cloudflare-dash/_freshness.json` (the last-seen
   `LAST_ALTERED` per table). Missing object/table ⇒ cold start ⇒ rebuild.
3. If **any** table advanced ⇒ full rebuild (this job can't rebuild one channel in isolation),
   then — **after** a successful `cloudflare.json` upload — write the new watermark. Upload first,
   watermark second, so a failed upload just retries next tick.

**The four gating tables** (everything else the job reads is static — not a freshness driver):

| PUBLIC base table | feeds | dashboard tab |
|---|---|---|
| `Salesforce_CS_APAC_ALL` | `V_SALESFORCE_LEADS_LIVE` → `V_PACING_FINAL_MODEL` | CS pacing |
| `TradeDesk_APAC ALL` | `V_STG_TRADEDESK_CF` → `V_PAID_ADS_FINAL_MODEL` | Paid Media |
| `LinkedIn Ads - APAC` | `V_STG_LINKEDIN_CF` → `V_PAID_ADS_FINAL_MODEL` | Paid Media |
| `Reddit Ads - APAC_ALL` | `V_STG_REDDIT_CF` → `V_PAID_ADS_FINAL_MODEL` | Paid Media |

These feeds land at different times each day, so the gate typically fires **~3 cheap rebuilds**
across the early-UTC window instead of one big daily one — fine at this volume. We watch the base
**tables**, not the model **views**: a view's `LAST_ALTERED` only moves on DDL.

**`data_through`** in the payload is the newest `LAST_ALTERED` across these four (the true data
instant); `last_updated` is the build time. The dashboard shows both.

**⚠️ Static-seed caveat.** The gate watches only those four dynamic tables. If you re-run
[`../seed_static.py`](../seed_static.py) (rare — it changes a static input like LINE spend, pacing
targets, or tiers), that change **won't trip the gate**, so kick the job once by hand:

```powershell
gcloud run jobs execute cloudflare-export --region australia-southeast1 --wait
```

**`FORCE_REBUILD=1`** bypasses the gate for a one-off manual rebuild:

```powershell
$env:FORCE_REBUILD = "1"; .\.venv\Scripts\python.exe client_cloudflare\job\main.py; $env:FORCE_REBUILD = $null
```

---

## ⚠️ Bootstrap behaviour (first run errors — expected)

The thin views read **from** the `src_*` tables this job lands, so on a fresh project they don't
exist yet. The **first run lands `src_*` and then errors on the view reads** — that's expected.
Then `python clients/client_cloudflare/create_views.py`, then re-run the job. (Same flow as MongoDB.)
See the [client README's deploy order](../README.md#one-time-replicate--deploy-order) for the
full two-run dance (there is no one-shot stand-up script for this client).

---

## Run & deploy

```powershell
# Local run (uses ADC for the Snowflake key + BigQuery):
.\.venv\Scripts\python.exe client_cloudflare\job\main.py

# Cloud run-now:
gcloud run jobs execute cloudflare-export --region australia-southeast1 --wait
```

**Config:** the runtime inputs `main.py` reads from the environment are the secret
`SNOWFLAKE_KEY=snowflake-bq-key:latest` (and locally, when it's absent, the key is read from
Secret Manager via ADC) and the optional `FORCE_REBUILD=1` (bypass the freshness gate — see
above). Everything else — `PROJECT`, `DATASET`, `BUCKET`, `SF_ACCOUNT`,
`SF_USER`, `SF_WAREHOUSE` — is **hardcoded as constants in `main.py`**, derived from
`CLIENT = "cloudflare"`, so they can't drift. The `GCP_PROJECT` / `BQ_DATASET` / `GCS_BUCKET` /
`SF_*` env vars that [`cloudbuild.yaml`](cloudbuild.yaml) sets are currently inert (the code
ignores them); they exist for parity with the MongoDB job's env-driven config.

## See also

- [`../README.md`](../README.md) — client overview, data contract, full deploy order, the divergence rationale.
- [`../sql/README.md`](../sql/README.md) — the thin views this job reads.
- [`../dash/README.md`](../dash/README.md) — serves the file this job writes.
- [`../../client_mongodb/job/README.md`](../../client_mongodb/job/README.md) — the template job (contrast: no Snowflake).
