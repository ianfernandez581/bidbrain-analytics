# Sophiie AI Dashboard - status

> **LIVE (as of 2026-09-05, main `7167bb9`).** `client_sophiie/` is a full Sophiie AI dashboard on
> **The Trade Desk programmatic display** - one AU campaign
> `SOPHIIE_2026-Q3_TTD_AU_DISPLAY_PROSPECTING` (advertiser `gjcl0pp`), three prospecting audience
> tiers plus retargeting. It was cloned from `client_geyervalmont` (the geocon **Meta** template) and
> rebuilt end to end onto TTD; the skin is unchanged and is still the estate's only animated one.
>
> **It is still serving SAMPLE data.** Advertiser `gjcl0pp` is not yet in
> `raw_windsor.perf_the_trade_desk`, so `client_sophiie.fact` is empty, the export job exits 0
> without uploading (the empty-fact guard), and the dashboard renders its baked-in
> `dash/placeholder.json` behind the "This is sample data" banner. The banner clears ITSELF on the
> first `*/10` tick after the grant lands - no edit, no redeploy.

**Live URL (share this one):** <https://dashboards.bidbrain.ai/d/sophiie/> - one sign-in at the
platform front door, no second password.
**Direct service (fallback when a client's network cannot resolve the custom domain):**
<https://sophiie-dash-516554645957.australia-southeast1.run.app>
**Password:** Secret Manager secret `sophiie-dash-password`. Do NOT hand out the 100% Digital agency
password - it opens every other 100% Digital client. Set this client's own password in the
super-admin console (it reveals and rotates), or grant their Google/Microsoft email there.
**Portal:** 100% Digital agency, tile status `active`, campaign row "Trade Desk Display".

## What is deployed

| Piece | Name |
|---|---|
| Dash service | `sophiie-dash` |
| Export job | `sophiie-export` (self-gating on `raw_windsor.perf_the_trade_desk`) |
| Scheduler | `sophiie-export-daily`, `*/10 * * * *` UTC |
| BigQuery | dataset `client_sophiie`: views `stg_ttd` / `fact` / `targets` / `budget`, tables `seed_targets` / `seed_budget` |
| Bucket | `gs://bidbrain-analytics-sophiie-dash` (holds `sophiie.json` + the `_freshness.json` watermark; empty until the grant) |
| Monitoring | `sophiie` in `BQ_CLIENTS` (`status_dashboard/job/main.py`), 5 accuracy checks |
| Sync button | `sophiie-export` in `_SYNC_EXPORT_JOBS` (`bidbrain-platform/dash/main.py`) |

## Redeploying after an edit

```powershell
$env:CLOUDSDK_ACTIVE_CONFIG_NAME="personal"           # this window's on-disk config is `agora`
.\clients\client_sophiie\dash\deploy_dash_sophiie.ps1  # dash/dashboard.html or dash/main.py
.\clients\client_sophiie\sql\deploy_views_sophiie.ps1  # any sql/*.sql view (reapplies + forces a run)
.\clients\client_sophiie\job\deploy_job_sophiie.ps1    # job/main.py (JSON shape)
```

`/ship` and `/go` deploy all three automatically from the path map in `scripts/merge-branches.ps1`.
After an edit to `targets/*.csv`, re-run `seed_static.py` AND `gen_placeholder.py`, then force a job
run - a seed change is invisible to the freshness gate:

```powershell
.\.venv\Scripts\python.exe clients\client_sophiie\seed_static.py
.\.venv\Scripts\python.exe clients\client_sophiie\gen_placeholder.py
gcloud run jobs execute sophiie-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

## Full standup from scratch

`deploy_sophiie.ps1` is idempotent and has a `-WithData` switch that stands up the whole pipeline
(dataset, seeds, views, export job, scheduler) on top of the dash service:

```powershell
.\clients\client_sophiie\deploy_sophiie.ps1            # dash service only
.\clients\client_sophiie\deploy_sophiie.ps1 -WithData  # + dataset, seeds, views, job, scheduler
```

## What is left

The **Windsor Trade Desk grant for advertiser `gjcl0pp`** - nothing else. The ordered checklist, the
verification query and the traps (a TTD re-grant can issue a NEW seat id, so a working re-auth can
look like a failure) are in [`../README.md`](../README.md) under **GO-LIVE**. Follow it there; do not
improvise a partial standup from this file.
