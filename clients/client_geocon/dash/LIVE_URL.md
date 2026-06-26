# Geocon Dashboard — Live URL

**Service:** https://geocon-dash-516554645957.australia-southeast1.run.app

**Password:** stored in Secret Manager secret `geocon-dash-password`.

## What's deployed

| Thing | Value |
|---|---|
| Project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Raw source | `raw_windsor.perf_meta` (Windsor, self-refreshing) |
| Views dataset | `client_geocon` (10 views) |
| Export Job | `geocon-export` (self-gating `*/10` UTC via scheduler `geocon-export-daily`) |
| Dash Service | `geocon-dash` |
| Data bucket / file | `bidbrain-analytics-geocon-dash` / `geocon.json` |
| Job SA | `geocon-dash-job@…` (BQ dataEditor + jobUser, Storage objectAdmin on bucket) |
| Web SA | `geocon-dash-web@…` (Storage objectViewer on bucket, Secret accessor) |
| Secrets | `geocon-dash-password`, `geocon-dash-session-key` |
| Images | `…/bidbrain/geocon-export:3ea13b4`, `…/bidbrain/geocon-dash:3ea13b4` |

## To refresh data

```powershell
# Self-gating: a plain execute rebuilds only if raw_windsor.perf_meta advanced.
gcloud run jobs execute geocon-export --region australia-southeast1 --wait
# To force: --update-env-vars FORCE_REBUILD=1