# MongoDB APAC dashboard — live URL

**Live (Cloud Run):** https://mongodb-dash-p32gk2wuia-ts.a.run.app

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `mongodb-dash-password`) to view it. Verified serving HTTP 200
(login page) on 2026-05-30.

**How it's accessed — the platform front-door:** the normal way in is
**https://dashboards.bidbrain.ai/d/mongodb/** (one login over all dashboards; the front-door
reverse-proxies this service and logs into it for you, so no second password). The `…run.app` URL above
is the upstream the proxy talks to and stays individually password-gated for direct access. There is
**no** `mongodb.bidbrain.ai` subdomain — the front-door is the access path. See
[`bidbrain-platform/README.md`](../../../bidbrain-platform/README.md).

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
