# Cloudflare APAC dashboard — live URL

**Live (Cloud Run):** https://cloudflare-dash-p32gk2wuia-ts.a.run.app

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `cloudflare-dash-password`) to view it. Verified serving HTTP 200
(login page) on 2026-06-04.

**Intended friendly URL:** https://cloudflare.bidbrain.ai
Cloudflare CNAME → the `…run.app` host above, Proxied (orange), SSL Full (strict),
with a Host Header Override origin rule (same setup as `mongodb.bidbrain.ai`).
Use the `…run.app` link until the custom domain is confirmed live.

## Deployment coordinates

| | |
|---|---|
| GCP project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Cloud Run service | `cloudflare-dash` |

## Re-fetch the URL (it's stable, but in case the service is recreated)

```powershell
gcloud run services describe cloudflare-dash `
  --region australia-southeast1 --project bidbrain-analytics `
  --format="value(status.url)"
```
