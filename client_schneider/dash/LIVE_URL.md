# Schneider Electric APAC dashboard — live URL

**Status: not yet stood up.** Run [`../deploy_schneider.ps1`](../deploy_schneider.ps1) once to
provision everything; it prints the live `…run.app` URL at the end. Record it here after stand-up:

> https://schneider-dash-XXXXXXXXX-ts.a.run.app   _(fill in after first deploy)_

Password-gated — the page loads a login screen; enter the dashboard password (Secret Manager:
`schneider-dash-password`) to view it.

Read the current password: `gcloud secrets versions access latest --secret=schneider-dash-password`.
Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add schneider-dash-password --data-file=-`
(no redeploy needed — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`schneider.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly. See the [root security model](../../README.md#7-security-model-read-before-changing-hosting).

## Custom domain (optional, not yet wired)

To put it on `schneider.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above,
Proxied, SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the
MongoDB / Cloudflare / STT setup).
