# Geyer Valmont Dashboard — status

> **PREVIEW (as of 2026-08-08).** `client_geyervalmont/` is a full, Geyer Valmont-branded dashboard
> scaffold cloned from `client_bellshakespeare` (itself the geocon Meta template). Geyer Valmont's
> campaigns have not launched, so there is **no Snowflake/Windsor/BigQuery data for this client** and,
> by design, **no `sql/`, no `job/`, no dataset, no scheduler** in this folder. The dashboard renders a
> baked-in SAMPLE payload (`dash/placeholder.json`, flagged `meta.placeholder=true`) behind the
> "Data coming soon — sample data" banner.

**Service URL (once deployed):** https://geyervalmont-dash-516554645957.australia-southeast1.run.app
**Password (once created):** Secret Manager secret `geyervalmont-dash-password`.
**Portal:** 100% Digital agency, tile status `coming_soon` → clients see the "COMING SOON" chip and
the note "Dashboard isn't live yet - the structure is ready."; a super admin gets **Open preview →**.

## Stand up the preview

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"          # charles@ has no deploy perms
.\clients\client_geyervalmont\deploy_geyervalmont.ps1
# Portal tile (surgical upsert into the LIVE registry; no full re-seed):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\set_geyervalmont_tile.py --yes
```

After an edit to `dash/dashboard.html` or `dash/main.py`, redeploy just the service with
`dash\deploy_dash_geyervalmont.ps1` (image swap only; env/secrets preserved).

## Going live

There is no `-WithData` switch on this client's deploy script, because the pipeline does not exist
yet. The full ordered checklist — media plan, channel confirmation, ingest, `sql/`, `job/`, the
freshness gate, scheduler, status-dashboard registration, password and the tile flip — is in
[`../README.md`](../README.md) under **FLIPPING PREVIEW → LIVE**. Follow it there; do not improvise
a partial standup from this file.
