# client_cloudflare/job/ — the Export Job (`cloudflare-export`)

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
| [`main.py`](main.py) | The job. Connects to Snowflake (key-pair auth), pulls 5 final-model views, lands them as `src_*` BigQuery tables, reads the thin views, and uploads `cloudflare.json`. `CLIENT = "cloudflare"` drives all the names. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim`, non-root, `CMD python main.py`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run jobs deploy cloudflare-export` with the Snowflake secret + env vars wired in. |
| [`requirements.txt`](requirements.txt) | `snowflake-connector-python[pandas]`, `pandas`, `pyarrow`, BigQuery, Storage, cryptography, secret-manager. (Heavier than MongoDB's job because this one talks to Snowflake.) |
| `.dockerignore` | Keeps the build context lean. |

---

## What it pulls and lands

| Snowflake source view | → BigQuery `src_*` | → thin view ([`../sql/`](../sql/README.md)) |
|---|---|---|
| `…PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL` | `src_paid_media` | `paid_media_model` |
| `…CS_REPORTING.V_PACING_FINAL_MODEL` | `src_pacing` | `pacing_model` |
| `…PAID_MEDIA_REPORTING.V_BENCHMARKS_CHANNEL` | `src_benchmarks_channel` | `benchmarks_channel` |
| `…PAID_MEDIA_REPORTING.V_BENCHMARKS_MARKET` | `src_benchmarks_market` | `benchmarks_market` |
| `…PAID_MEDIA_REPORTING.V_LI_WEEKLY_TARGETS` | `src_li_weekly` | `li_weekly_targets` |

(Three further **static** inputs — LINE spend, pacing targets, account tiers — are landed
separately and rarely by [`../seed_static.py`](../seed_static.py), not by this job.)

---

## The JSON contract it produces

One object served at `/data.json`, with the two halves matching the old R2 files exactly so the
dashboard's `adaptPayload` / `rawRows` code is unchanged:

```jsonc
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",
  "paid_media": {                          // == the old paid_media.json
    "row_count": 0,
    "window": { "start": "…", "end": "…", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { channel, date, week_start, market, imps, clicks, spend_usd, leads,
                form_opens, link_clicks, action_clicks, video_starts, video_completions,
                spend_jpy, fx_usd_jpy } ],
    "benchmarks":        { "<channel>": { ctr, cpm, cpc } },   // TTD, LinkedIn, Reddit, LINE
    "benchmarks_market": { "<market>":  { ctr, cpm, cpc } },
    "li_weekly": [ { week, period, week_start, target, cum_target } ]
  },
  "pacing": { "row_count": 0, "rows": [ /* every V_PACING_FINAL_MODEL column, dates → ISO */ ] }
}
```

**Label contract (must match the dashboard):** `benchmarks`/`channel` keys are `TTD`,
`LinkedIn`, `Reddit`, `LINE`; markets are the seven in `all_markets`. These come straight from
the Snowflake views — if a view emits different strings, fix the mapping in
[`../sql/`](../sql/README.md) (the only place strings are mapped). JSON serialisation handles
`Decimal` → float and dates → ISO via the `_json_default` / `jval` helpers.

---

## ⚠️ Bootstrap behaviour (first run errors — expected)

The thin views read **from** the `src_*` tables this job lands, so on a fresh project they don't
exist yet. The **first run lands `src_*` and then errors on the view reads** — that's expected.
Then `python client_cloudflare/create_views.py`, then re-run the job. (Same flow as MongoDB.)
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

**Config:** the only runtime input `main.py` actually reads from the environment is the secret
`SNOWFLAKE_KEY=snowflake-bq-key:latest` (and locally, when it's absent, the key is read from
Secret Manager via ADC). Everything else — `PROJECT`, `DATASET`, `BUCKET`, `SF_ACCOUNT`,
`SF_USER`, `SF_WAREHOUSE` — is **hardcoded as constants in `main.py`**, derived from
`CLIENT = "cloudflare"`, so they can't drift. The `GCP_PROJECT` / `BQ_DATASET` / `GCS_BUCKET` /
`SF_*` env vars that [`cloudbuild.yaml`](cloudbuild.yaml) sets are currently inert (the code
ignores them); they exist for parity with the MongoDB job's env-driven config.

## See also

- [`../README.md`](../README.md) — client overview, data contract, full deploy order, the divergence rationale.
- [`../sql/README.md`](../sql/README.md) — the thin views this job reads.
- [`../dash/README.md`](../dash/README.md) — serves the file this job writes.
- [`../../client_mongodb/job/README.md`](../../client_mongodb/job/README.md) — the template job (contrast: no Snowflake).
