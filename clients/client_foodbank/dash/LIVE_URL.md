# foodbank-dash - live URL + runbook

**Service:** `foodbank-dash` (Cloud Run, `australia-southeast1`, project `bidbrain-analytics`)
**URL:** https://foodbank-dash-p32gk2wuia-ts.a.run.app
(deterministic form: https://foodbank-dash-516554645957.australia-southeast1.run.app)

**Deployed:** 2026-09-03 by `deploy/deploy_foodbank.ps1` (revision `foodbank-dash-00001-zw4`), then
redeployed the same day by `deploy/deploy_dash_foodbank.ps1` with the premium restyle + motion kit
(revision `foodbank-dash-00002-k7n`), then again with the per-channel line chart + clickable metric
cards (revision `foodbank-dash-00003`), then with the approved countdown login from
`design/login_reference.html` (revision `foodbank-dash-00004-hvc`). Serving the SAMPLE payload
(`DATA_MODE = "sample"`).

**Password:** Secret Manager `foodbank-dash-password` (injected as `DASH_PASSWORD`). Reveal or
rotate it from the super-admin console once the client is registered on the platform; until then
`gcloud secrets versions access latest --secret foodbank-dash-password --project bidbrain-analytics`.
Session key: `foodbank-dash-session-key`. Web SA: `foodbank-dash-web@bidbrain-analytics.iam.gserviceaccount.com`.
Bucket `gs://bidbrain-analytics-foodbank-dash` exists and is EMPTY (only used once DATA_MODE is live).

**Redeploy after a UI edit:** `.\clients\client_foodbank\deploy\deploy_dash_foodbank.ps1`
(pin the window: `$env:CLOUDSDK_ACTIVE_CONFIG_NAME="personal"`; needs ian@100.digital).

**Not yet done:** no platform registry tile / Think HQ agency entry (so not reachable at
dashboards.bidbrain.ai/d/foodbank/ yet), not in `status_dashboard` monitoring, no `md/AGENTS.md` row.
