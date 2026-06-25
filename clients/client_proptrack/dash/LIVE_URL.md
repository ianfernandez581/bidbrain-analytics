# PropTrack dashboard — live URL

**Live:** https://proptrack-dash-p32gk2wuia-ts.a.run.app
(canonical Cloud Run host: `https://proptrack-dash-516554645957.australia-southeast1.run.app`)

Service `proptrack-dash` in `australia-southeast1`. Redeploy a UI/serving edit with
`.\client_proptrack\dash\deploy_dash_proptrack.ps1`; the service serves `dashboard.html` with
`Cache-Control: no-store`, so changes are live immediately.

First-time stand-up (APIs, SAs, IAM, secrets, scheduler) is the one-shot
`.\client_proptrack\deploy_proptrack.ps1` — it prompts for the dashboard password, stored in Secret
Manager as `proptrack-dash-password`.

Password-gated: the page loads a login screen; enter the dashboard password to view it.
- Read the current password: `gcloud secrets versions access latest --secret=proptrack-dash-password`.
- Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add proptrack-dash-password --data-file=-` (no redeploy — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`proptrack.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly.

## How it's accessed — the platform front-door

The normal way in is the **platform front-door — https://dashboards.bidbrain.ai/d/proptrack/** (one
login over all dashboards; the front-door reverse-proxies this service and logs into it for you, so no
second password). The `…run.app` URL above is the upstream the proxy talks to and stays individually
password-gated for direct access. There is **no** `proptrack.bidbrain.ai` subdomain — the front-door is
the access path. See [`bidbrain-platform/README.md`](../../../bidbrain-platform/README.md).
