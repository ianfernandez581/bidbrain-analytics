# ResetData dashboard — live URL

**Live (password-gated):**

> https://resetdata-dash-p32gk2wuia-ts.a.run.app

Verified serving HTTP 200 (login page) on 2026-06-08; `/data.json` returns 401 without a session,
200 to an authenticated session (28,265 sessions / A$19,286 ad spend in the payload).

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `resetdata-dash-password`) to view it.

Read the current password: `gcloud secrets versions access latest --secret=resetdata-dash-password`.
Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add resetdata-dash-password --data-file=-` (no redeploy needed — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`resetdata.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly. See the [root security model](../../../README.md#7-security-model-read-before-changing-hosting).

## How it's accessed — the platform front-door

The normal way in is the **platform front-door — https://dashboards.bidbrain.ai/d/resetdata/** (one
login over all dashboards; the front-door reverse-proxies this service and logs into it for you, so no
second password). The `…run.app` URL above is the upstream the proxy talks to and stays individually
password-gated for direct access. There is **no** `resetdata.bidbrain.ai` subdomain — the front-door is
the access path. See [`bidbrain-platform/README.md`](../../../bidbrain-platform/README.md).
