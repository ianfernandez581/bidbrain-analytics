# STT GDC APAC dashboard — live URL

**Live (password-gated):**

> https://stt-dash-p32gk2wuia-ts.a.run.app

**Password:** `STT-GDC-Always-On-2026`
(stored in Secret Manager as `stt-dash-password`; rotate with
`printf '%s' 'NEW' | gcloud secrets versions add stt-dash-password --data-file=-` then redeploy the service).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`stt.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly. See the [root security model](../../README.md#7-security-model-read-before-changing-hosting).

## Custom domain (optional, not yet wired)

To put it on `stt.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above, Proxied,
SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the MongoDB/Cloudflare
setup).
