# Cloudflare APAC dashboard — live URL

**Live (Cloud Run):** _TBD — fill in after the first deploy_ (run the command below).

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `cloudflare-dash-password`) to view it.

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

## Fetch the URL (stable once created; re-fetch if the service is recreated)

```powershell
gcloud run services describe cloudflare-dash `
  --region australia-southeast1 --project bidbrain-analytics `
  --format="value(status.url)"
```

Paste the result in at the top of this file once it's deployed.
