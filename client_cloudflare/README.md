# client_cloudflare — Cloudflare APAC dashboard on the MongoDB GCP pattern

This folder ports the **Cloudflare** dashboard onto the same Google Cloud
architecture as `client_mongodb`:

```
Snowflake (CLOUDFLARE_SANDBOX.* final-model views)
  -> Cloud Run JOB  (client_cloudflare/job)      pull -> land BigQuery src_* -> read BQ views -> cloudflare.json
  -> GCS (private)  gs://bidbrain-analytics-cloudflare-dash/cloudflare.json
  -> Cloud Run SERVICE (client_cloudflare/dash)  password gate + serves dashboard.html + proxies /data.json
  -> Cloudflare CNAME  cloudflare.bidbrain.ai (proxied) -> *.run.app
Cloud Build = CD on push to main (one trigger per unit, like MongoDB §11).
```

This replaces Cloudflare's current setup (Snowflake **tasks** writing
`pacing.json` + `paid_media.json` to a **public** R2 bucket, read by a static
page). The two payloads are merged into one `cloudflare.json`, served behind the
same Flask password gate MongoDB uses.

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
  "paid_media": {
    "row_count": 0,
    "window": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { "channel","date","week_start","market","imps","clicks","spend_usd",
                "leads","form_opens","link_clicks","action_clicks","video_starts",
                "video_completions","spend_jpy","fx_usd_jpy" } ],
    "benchmarks":        { "<channel>": { "ctr","cpm","cpc" } },
    "benchmarks_market": { "<market>":  { "ctr","cpm","cpc" } },
    "li_weekly": [ { "week","period","week_start","target","cum_target" } ]
  },
  "pacing": {
    "row_count": 0,
    "rows": [ /* every column of V_PACING_FINAL_MODEL, dates as ISO strings */ ]
  }
}
```

`dashboard.html` reads `paid_media` exactly like the old `paid_media.json`
(`adaptPayload` is unchanged) and `pacing.rows` exactly like the old
`pacing.json` (`rawRows`). See `dash/DASHBOARD.md`.

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

# 9. Deploy the service (build/push/deploy via Cloud Build)
gcloud builds submit --config client_cloudflare/dash/cloudbuild.yaml --project $PROJECT .

#10. Deploy the job the same way (or just keep running it locally while testing)
gcloud builds submit --config client_cloudflare/job/cloudbuild.yaml --project $PROJECT .
```

Then, mirroring MongoDB:
- **CD** — wire two Cloud Build triggers (push to `^main$`): one with included
  files `client_cloudflare/job/**` -> `client_cloudflare/job/cloudbuild.yaml`,
  one with `client_cloudflare/dash/**` -> `client_cloudflare/dash/cloudbuild.yaml`.
- **Daily run** — Cloud Scheduler trigger executing the `cloudflare-export` job.
- **Friendly URL** — Cloudflare CNAME `cloudflare.bidbrain.ai` -> the service's
  `*.run.app` host, Proxied, SSL Full (strict), Host Header Override. See
  `dash/LIVE_URL.md`.
