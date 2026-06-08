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
`/data.json` — never publicly. See the [root security model](../../README.md#7-security-model-read-before-changing-hosting).

## Custom domain (optional, not yet wired)

To put it on `resetdata.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above, Proxied,
SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the MongoDB/Cloudflare/STT setup).
