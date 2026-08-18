# Sophiie AI Dashboard — status

> **PREVIEW (as of 2026-08-18).** `client_sophiie/` is a full, Sophiie AI-branded dashboard cloned
> from `client_geyervalmont` (itself the geocon Meta template) and re-skinned onto **the aurora
> design** — the estate's only animated background. Sophiie's Meta campaigns are still being built,
> so there is **no Windsor/BigQuery data for this client** and, by design, **no `sql/`, no `job/`, no
> dataset, no scheduler** in this folder. The dashboard renders a baked-in SAMPLE payload
> (`dash/placeholder.json`, flagged `meta.placeholder=true`) behind the "Data coming soon — sample
> data" banner.

**Service URL (once deployed):** https://sophiie-dash-516554645957.australia-southeast1.run.app
**Password (once created):** Secret Manager secret `sophiie-dash-password`.
**Portal:** 100% Digital agency, tile status `coming_soon` → clients see the "COMING SOON" chip and
the note "Dashboard isn't live yet - the structure is ready."; a super admin gets **Open preview →**.

## Stand up the preview

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"          # charles@ has no deploy perms
.\clients\client_sophiie\deploy_sophiie.ps1
# Portal tile (surgical upsert into the LIVE registry; no full re-seed):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\set_sophiie_tile.py --yes
```

After an edit to `dash/dashboard.html` or `dash/main.py`, redeploy just the service with
`dash\deploy_dash_sophiie.ps1` (image swap only; env/secrets preserved). After an edit to
`targets/*.csv` re-run `gen_placeholder.py` first; after a change to the mark re-run `gen_logo.py`.

## Going live

There is no `-WithData` switch on this client's deploy script, because the pipeline does not exist
yet. The full ordered checklist — media plan, channel confirmation, ingest, `sql/`, `job/`, the
freshness gate, scheduler, status-dashboard registration, the platform sync button, password and the
tile flip — is in [`../README.md`](../README.md) under **FLIPPING PREVIEW → LIVE**. Follow it there;
do not improvise a partial standup from this file.
