# Schneider Electric Pacific dashboard — live URL

**Status: live (stood up 2026-06-04).** The `schneider-dash` service is deployed and password-gated.
Branded **"Pacific"** (a sibling SE-region dashboard is planned). Live URL:

> https://schneider-dash-516554645957.australia-southeast1.run.app

(re-read any time with
`gcloud run services describe schneider-dash --region australia-southeast1 --format='value(status.url)'`)

Password-gated — the page loads a login screen; enter the dashboard password (Secret Manager:
`schneider-dash-password`) to view it.

Read the current password: `gcloud secrets versions access latest --secret=schneider-dash-password`.
Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add schneider-dash-password --data-file=-`
(no redeploy needed — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`schneider.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly. See the [root security model](../../../README.md#7-security-model-read-before-changing-hosting).

## How it's accessed — the platform front-door

The normal way in is the **platform front-door — https://dashboards.bidbrain.ai/d/schneider/** (one
login over all dashboards; the front-door reverse-proxies this service and logs into it for you, so no
second password). The `…run.app` URL above is the upstream the proxy talks to and stays individually
password-gated for direct access. There is **no** `schneider.bidbrain.ai` subdomain — the front-door is
the access path. See [`bidbrain-platform/README.md`](../../../bidbrain-platform/README.md).
