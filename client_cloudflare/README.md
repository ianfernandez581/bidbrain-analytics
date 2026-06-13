# client_cloudflare — Cloudflare APAC dashboard on the MongoDB GCP pattern

**Status: LIVE.** The gated web app is deployed and serving (HTTP 200 verified
2026-06-04). See [`dash/LIVE_URL.md`](dash/LIVE_URL.md) for the URL.

This folder ports the **Cloudflare** dashboard onto the same Google Cloud
architecture as `client_mongodb`:

```
Snowflake (CLOUDFLARE_SANDBOX.* final-model views)
  -> Cloud Run JOB  (client_cloudflare/job)      pull -> land BigQuery src_* -> read BQ views -> cloudflare.json
  -> GCS (private)  gs://bidbrain-analytics-cloudflare-dash/cloudflare.json
  -> Cloud Run SERVICE (client_cloudflare/dash)  password gate + serves dashboard.html + proxies /data.json
  -> Cloudflare CNAME  cloudflare.bidbrain.ai (proxied) -> *.run.app
```

The `cloudbuild.yaml` files are a **future** push-to-main CD trigger (one per
unit, like MongoDB §11) — **not active**. This client was stood up, and is
redeployed, by the manual order below.

This replaces Cloudflare's current setup (Snowflake **tasks** writing
`pacing.json` + `paid_media.json` to a **public** R2 bucket, read by a static
page). The two payloads are merged into one `cloudflare.json`, served behind the
same Flask password gate MongoDB uses.

## What's in this folder

| Path | What it is |
|---|---|
| [`job/`](job/README.md) | **Export Job** (`cloudflare-export`): pulls Snowflake final-model views → lands `src_*` → reads thin BigQuery views → writes `cloudflare.json`. [Guide →](job/README.md) |
| [`dash/`](dash/README.md) | **Web App** (`cloudflare-dash`): password gate + serves `dashboard.html` + proxies `/data.json`. [Guide →](dash/README.md) |
| [`sql/`](sql/README.md) | The **thin** BigQuery pass-through views that lock the JSON column contract. [Guide →](sql/README.md) |
| [`create_views.py`](create_views.py) | Applies every `sql/*.sql` view (runner). |
| [`seed_static.py`](seed_static.py) | One-time copy of Cloudflare's three **static** Snowflake inputs (LINE JP spend, pacing targets, account tiers) into `src_*`. Re-run only when those manual uploads change. |
| [`scheduler.ps1`](scheduler.ps1) | Creates/refreshes the Cloud Scheduler trigger for `cloudflare-export` (default `*/10` UTC; pass `-Cron` to override). The job self-gates, so most ticks no-op. Idempotent. |

> There is **no** one-shot `deploy_cloudflare.ps1` for this client — it was stood
> up via the manual order in [One-time replicate / deploy order](#one-time-replicate--deploy-order)
> below. (Only STT has a one-shot stand-up script, `client_STT/deploy_stt.ps1`.)

## Deliberate divergence from client_mongodb

MongoDB does its modelling **in BigQuery** (raw Snowflake -> `src_*` ->
BigQuery views that derive everything). Cloudflare's model already lives in
**Snowflake** (`V_PAID_ADS_FINAL_MODEL`, `V_PACING_FINAL_MODEL`, the
`V_BENCHMARKS_*` / `V_LI_WEEKLY_TARGETS` views). Re-deriving that in BigQuery
would mean porting a lot of tested Snowflake SQL (and the upstream views aren't
in this repo). So here the job pulls Snowflake's **final-model** views, lands
them as BigQuery `src_*` tables (a queryable per-client copy, uniform with every
other client folder), and the `sql/` views are **thin pass-throughs** that
expose them in the shape the dashboard expects.

If you later want BigQuery to own the model (true MongoDB parity), port the
Snowflake DDL from the four `CREATE …` scripts into `sql/` and have the job pull
the raw `APAC_ALL_PLATFORM.PUBLIC.*` tables instead of the CF views.

## The data contract (`cloudflare.json` -> `/data.json`)

```json
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",
  "data_through": "YYYY-MM-DDTHH:MM:SSZ",
  "paid_media": {
    "row_count": 0,
    "window": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { "channel","date","week_start","market","imps","clicks","spend_usd",
                "leads","form_opens","link_clicks","action_clicks","video_starts",
                "video_completions","spend_jpy","fx_usd_jpy" } ],
    "creatives": [ { "channel","market","creative","imps","clicks","spend_usd","leads" } ],
    "benchmarks":        { "<channel>": { "ctr","cpm","cpc" } },
    "benchmarks_market": { "<market>":  { "ctr","cpm","cpc" } },
    "li_weekly": [ { "week","period","week_start","target","cum_target" } ]
  },
  "pacing": {
    "row_count": 0,
    "rows": [ /* every column of V_PACING_FINAL_MODEL, dates as ISO strings */ ]
  },
  "campaigns": {
    "peyc":        { "label","campaign_group","window","totals","daily":[…],"by_campaign":[…] },
    "cf1_india":   { … },
    "coles_hyper": { … }
  }
}
```

`dashboard.html` reads `paid_media` exactly like the old `paid_media.json`
(`adaptPayload` is unchanged) and `pacing.rows` exactly like the old
`pacing.json` (`rawRows`). The `paid_media.creatives[]` array (creative-grain
delivery) powers the "Top & bottom performing creatives" tables; `campaigns`
powers the three single-campaign LinkedIn dashboards selectable in the top-bar
dropdown (read from the shared `raw_snowflake.linkedin_ads_apac` mirror, not from
Snowflake directly). `data_through` is the newest source `LAST_ALTERED` (true
data instant); `last_updated` is the build time. See `dash/DASHBOARD.md`.

**Channel / market labels must match the dashboard:** `benchmarks` keys must be
`TTD`, `LinkedIn`, `Reddit`, `LINE`; row `channel` must be one of
`LinkedIn`/`LI`, `TTD`/`TradeDesk`, `Reddit`, `LINE`; markets must be the seven
in `all_markets`. These come straight from the Snowflake views — if your view
emits different strings, fix it in `sql/` (the only place that maps them).

---

## One-time replicate / deploy order

Prereqs: `gcloud` authenticated; APIs enabled (`run`, `cloudbuild`,
`artifactregistry`, `bigquery`, `storage`, `secretmanager`); the Artifact
Registry docker repo `bidbrain` exists; the shared Snowflake key secret
`snowflake-bq-key` exists (same one MongoDB uses).

```bash
PROJECT=bidbrain-analytics
REGION=australia-southeast1

# 1. Private data bucket
gcloud storage buckets create gs://bidbrain-analytics-cloudflare-dash \
  --project $PROJECT --location $REGION --uniform-bucket-level-access

# 2. BigQuery dataset
bq --location=$REGION mk --dataset $PROJECT:client_cloudflare

# 3. Runtime service accounts
gcloud iam service-accounts create cloudflare-dash-job --project $PROJECT
gcloud iam service-accounts create cloudflare-dash-web --project $PROJECT
#   job: read/write its dataset + bucket, read the Snowflake key
bq update --dataset --source <(echo '{}') $PROJECT:client_cloudflare  # (or grant via IAM policy)
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-cloudflare-dash \
  --member="serviceAccount:cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
#   (also grant cloudflare-dash-job roles/bigquery.dataEditor on the client_cloudflare dataset)
#   web: read the bucket + its two secrets
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-cloudflare-dash \
  --member="serviceAccount:cloudflare-dash-web@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# 4. Secrets
printf 'choose-a-dashboard-password' | gcloud secrets create cloudflare-dash-password --data-file=- --project $PROJECT
python -c "import secrets;print(secrets.token_urlsafe(48),end='')" | gcloud secrets create cloudflare-dash-session-key --data-file=- --project $PROJECT
#   grant both secrets to cloudflare-dash-web (roles/secretmanager.secretAccessor)
#   grant snowflake-bq-key to cloudflare-dash-job (roles/secretmanager.secretAccessor)

# 5. Bootstrap the BigQuery src_* tables (lands them, then errors reading the not-yet-existing
#    views — expected, same as MongoDB §10). Run locally with ADC:
python client_cloudflare/job/main.py    # lands src_*, then raises on the view reads — fine

# 6. Apply the (thin) BigQuery views
python client_cloudflare/create_views.py

# 7. Re-run the job — now it produces cloudflare.json in GCS
python client_cloudflare/job/main.py

# 8. Build dashboard.html from your existing index.html (see dash/DASHBOARD.md)

# 9. Deploy the SERVICE — build the image, then deploy as yourself.
#    (Do NOT `gcloud builds submit --config .../cloudbuild.yaml` from a laptop: it fails
#     with iam.serviceaccounts.actAs because Cloud Build's SA can't act as the runtime SA.
#     The cloudbuild.yaml files are for a future push-to-main trigger only.)
IMG=australia-southeast1-docker.pkg.dev/$PROJECT/bidbrain/cloudflare-dash:$(git rev-parse --short HEAD)
gcloud builds submit client_cloudflare/dash --tag $IMG --region $REGION
gcloud run services update cloudflare-dash --image $IMG --region $REGION \
  --service-account cloudflare-dash-web@$PROJECT.iam.gserviceaccount.com \
  --set-env-vars=GCS_BUCKET=bidbrain-analytics-cloudflare-dash,DATA_OBJECT=cloudflare.json \
  --set-secrets=DASH_PASSWORD=cloudflare-dash-password:latest,SESSION_SECRET=cloudflare-dash-session-key:latest \
  --memory=512Mi
gcloud run services update cloudflare-dash --region $REGION --no-invoker-iam-check  # org policy: app does its own auth

#10. Deploy the JOB the same way (or just keep running it locally while testing)
IMG=australia-southeast1-docker.pkg.dev/$PROJECT/bidbrain/cloudflare-export:$(git rev-parse --short HEAD)
gcloud builds submit client_cloudflare/job --tag $IMG --region $REGION
gcloud run jobs deploy cloudflare-export --image $IMG --region $REGION \
  --service-account cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com --memory 1Gi
```

Then, mirroring MongoDB:
- **Freshness-gated run** — Cloud Scheduler trigger executing the `cloudflare-export`
  job every `*/10` (UTC). Run [`scheduler.ps1`](scheduler.ps1). The job is **self-gating**:
  each tick it cheaply probes `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` for its four upstream
  Snowflake tables (metadata-only — no warehouse credits) and only does the full rebuild +
  upload when one advanced, recording a `_freshness.json` watermark in the bucket. So the
  dashboard refreshes **within ~10 min of new data** instead of at a fixed 22:00 UTC, while
  most ticks are a ~3s no-op. The payload carries both `last_updated` (build time) and
  `data_through` (newest source `LAST_ALTERED`). Re-running [`seed_static.py`](seed_static.py)
  changes a *static* input that the gate doesn't watch, so kick the job once by hand after it
  (`gcloud run jobs execute cloudflare-export --region australia-southeast1 --wait`). See
  [`job/README.md`](job/README.md#freshness-gate--why-most-runs-do-nothing-and-thats-the-point).
- **Friendly URL** — Cloudflare CNAME `cloudflare.bidbrain.ai` -> the service's
  `*.run.app` host, Proxied, SSL Full (strict), Host Header Override. See
  `dash/LIVE_URL.md`.
- **CD (future, not active)** — the per-unit `cloudbuild.yaml` files are wiring
  for two push-to-`^main$` Cloud Build triggers (included files
  `client_cloudflare/job/**` and `client_cloudflare/dash/**`). Not enabled yet;
  redeploys today use the manual build-then-deploy steps above.

## See also

- [Root README](../README.md) — the whole-platform map, security model, and naming conventions.
- [`../client_mongodb/`](../client_mongodb/README.md) — the template this client is based on (and diverges from).
- [`../snowflake_data_pull/`](../snowflake_data_pull/README.md) — the shared raw layer (note: this client does **not** use it; it pulls its own Snowflake schema directly — see [Deliberate divergence](#deliberate-divergence-from-client_mongodb)).
