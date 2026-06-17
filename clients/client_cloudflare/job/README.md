# clients/client_cloudflare/job/ — the Export Job (`cloudflare-export`)

> A **Cloud Run Job** that reads the BigQuery model views and writes one combined
> `cloudflare.json` to the private bucket. **No Snowflake** — same pattern as MongoDB.

**Plain English:** this is Cloudflare's *kitchen*, and as of 2026-06-17 the maths happens in
**our** warehouse (BigQuery), like every other client. The job just reads the finished
[`../sql/`](../sql/README.md) views and packs the result into the single file the dashboard reads.
It merges what Cloudflare used to publish as **two separate public files** (`pacing.json` +
`paid_media.json`) into **one private** `cloudflare.json`.

**Where this sits:** `raw_snowflake.*` mirrors (shared `ingest/snowflake_data_pull`) +
`client_cloudflare.seed_*` static tables → [`../sql/`](../sql/README.md) BigQuery views →
**[this job]** → `cloudflare.json` → [`../dash/`](../dash/README.md) serves it.

> **History:** this job used to connect to Snowflake (key-pair), pull six pre-modelled
> `CLOUDFLARE_SANDBOX.*` views, and land them as `src_*` pass-throughs. That was the lone
> deviation from the repo pattern; it was ported to BigQuery modelling on 2026-06-17. See
> [the client README](../README.md#bigquery-owns-the-model-was-the-snowflake-modelled-exception).

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. **Gates on freshness** (BQ `__TABLES__.last_modified`, see below), reads the six final views (`paid_media_model`, `pacing_model`, `benchmarks_channel`, `benchmarks_market`, `li_weekly_targets`, `paid_creatives_model`), reads `raw_snowflake.linkedin_ads_apac` for the three single-campaign LinkedIn dashboards, and uploads `cloudflare.json`. `CLIENT = "cloudflare"` drives all the names. No Snowflake connection. |
| [`freshness.py`](freshness.py) | The shared freshness gate (vendored per job folder). Uses `probe_bq_last_modified()` here. Reads/writes the `_freshness.json` watermark sidecar in the bucket; answers `is_stale()`. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim`, non-root, `CMD python main.py`. Ships `main.py` + `freshness.py`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run jobs deploy cloudflare-export` (future push-to-main trigger; redeploy manually with [`deploy_job_cloudflare.ps1`](deploy_job_cloudflare.ps1)). |
| [`requirements.txt`](requirements.txt) | Just `google-cloud-bigquery` + `google-cloud-storage` (BQ-only now — matches MongoDB's job; the heavy Snowflake/pandas deps are gone). |

## What it reads

| BigQuery view ([`../sql/`](../sql/README.md)) | → `cloudflare.json` |
|---|---|
| `paid_media_model` | `paid_media.rows` |
| `paid_creatives_model` | `paid_media.creatives` |
| `benchmarks_channel` / `benchmarks_market` | `paid_media.benchmarks` / `benchmarks_market` |
| `li_weekly_targets` | `paid_media.li_weekly` |
| `pacing_model` | `pacing.rows` |
| `raw_snowflake.linkedin_ads_apac` (read directly) | `campaigns` (peyc / cf1_india / coles_hyper) |

(The static inputs the views read — `seed_real_targets`, `seed_tiers`, `seed_line_cf` — are loaded
separately and rarely by [`../seed_static.py`](../seed_static.py), not by this job.)

---

## The JSON contract it produces

One object served at `/data.json`, with the two halves matching the old R2 files exactly so the
dashboard's `adaptPayload` / `rawRows` code is unchanged:

```jsonc
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",  // when THIS build ran (build time)
  "data_through": "YYYY-MM-DDTHH:MM:SSZ",  // newest last_modified across the 4 gating mirrors (UTC)
  "paid_media": {
    "row_count": 0,
    "window": { "start": "…", "end": "…", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { channel, date, week_start, market, imps, clicks, spend_usd, leads,
                form_opens, link_clicks, action_clicks, video_starts, video_completions,
                spend_jpy, fx_usd_jpy } ],
    "creatives": [ { channel, market, creative, imps, clicks, spend_usd, leads } ],
    "benchmarks":        { "<channel>": { ctr, cpm, cpc } },
    "benchmarks_market": { "<market>":  { ctr, cpm, cpc } },
    "li_weekly": [ { week, period, week_start, target, cum_target } ]
  },
  "pacing": { "row_count": 0, "rows": [ /* every pacing_model column, dates → ISO */ ] },
  "campaigns": {
    "peyc":        { label, campaign_group, window, totals, daily: [...], by_campaign: [...] },
    "cf1_india":   { ... },                // from raw_snowflake.linkedin_ads_apac (BQ mirror)
    "coles_hyper": { ... }
  }
}
```

**Label contract (must match the dashboard):** `benchmarks`/`channel` keys are `TTD`,
`LinkedIn`, `Reddit`, `LINE`; markets are the seven in `all_markets`. These come from the
[`../sql/`](../sql/README.md) views — if you need different strings, fix them there. JSON
serialisation handles `Decimal` → float and dates → ISO via the `_json_default` / `jval` helpers.

---

## Freshness gate — why most runs do nothing (and that's the point)

The job is scheduled **`*/10 * * * *`** but is **self-gating**: each tick it only rebuilds if an
upstream `raw_snowflake` mirror actually moved. Net effect — the dashboard refreshes **within
~10 min of the shared ingest mirroring new data**.

**How the gate works** ([`freshness.py`](freshness.py)):

1. Probe `__TABLES__.last_modified_time` for the four mirror tables (metadata-only BQ read).
2. Compare against the watermark in `gs://…-cloudflare-dash/_freshness.json`. Missing ⇒ cold start ⇒ rebuild.
3. If **any** advanced ⇒ full rebuild, then — **after** a successful upload — write the new watermark
   (upload first, watermark second, so a failed upload just retries).

**The four gating tables** (the static `seed_*` tables are NOT freshness drivers — re-seeding needs
a manual `FORCE_REBUILD=1` kick, per CLAUDE.md):

| BQ mirror | feeds | dashboard tab |
|---|---|---|
| `raw_snowflake.salesforce_cs_apac_all` | `salesforce_leads_live` → `pacing_model` | CS pacing |
| `raw_snowflake.tradedesk_apac_all` | `stg_tradedesk` → `paid_media_model` | Paid Media |
| `raw_snowflake.linkedin_ads_apac` | `stg_linkedin` → `paid_media_model` (+ the `campaigns` block) | Paid Media |
| `raw_snowflake.reddit_ads_apac_all` | `stg_reddit` → `paid_media_model` | Paid Media |
