# MongoDB APAC dashboard — live URL

**Live (Cloud Run):** https://mongodb-dash-p32gk2wuia-ts.a.run.app

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `mongodb-dash-password`) to view it. Verified serving HTTP 200
(login page) on 2026-05-30.

**Intended friendly URL:** https://mongodb.bidbrain.ai
Cloudflare CNAME → the `…run.app` host above, Proxied (orange), SSL Full (strict),
with a Host Header Override origin rule. See README §4.5 and §13 — being finished;
use the `…run.app` link until it's confirmed live.

## Deployment coordinates

| | |
|---|---|
| GCP project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Cloud Run service | `mongodb-dash` |

## Re-fetch the URL (it's stable, but in case the service is recreated)

```powershell
gcloud run services describe mongodb-dash `
  --region australia-southeast1 --project bidbrain-analytics `
  --format="value(status.url)"
```
