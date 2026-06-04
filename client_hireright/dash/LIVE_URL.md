# HireRight paid-media dashboard — live URL

**Live (password-gated):**

> https://hireright-dash-p32gk2wuia-ts.a.run.app

(also reachable at `https://hireright-dash-516554645957.australia-southeast1.run.app`)

Verified serving HTTP 200 (login page) and `/data.json` 401-gated / 200-after-login on 2026-06-04.

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `hireright-dash-password`) to view it.

Read the current password: `gcloud secrets versions access latest --secret=hireright-dash-password`.
Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add hireright-dash-password --data-file=-` (no redeploy needed — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`hireright.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly. See the [root security model](../../README.md#7-security-model-read-before-changing-hosting).

## Custom domain (optional, not yet wired)

To put it on `hireright.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above, Proxied,
SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the MongoDB/Cloudflare/STT
setup).
