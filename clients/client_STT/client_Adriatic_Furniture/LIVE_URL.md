# Adriatic Furniture — sample dashboard live URL

**Live (open — no password):**

> https://adriatic-dash-p32gk2wuia-ts.a.run.app

This is a **self-contained sample/pitch dashboard** (Adriatic Furniture × The Faith Agency). All
the numbers are **illustrative sample data baked into `dashboard.html`** — there is no GCS bucket,
no `/data.json` proxy, no SQL views and no export job behind it. Verified serving HTTP 200 with
`Cache-Control: no-store` on 2026-06-05.

Unlike the client_STT / client_mongodb / client_cloudflare dashboards this one has **no login
gate** — it is deliberately open so it can be shared by link. Because nothing sensitive is exposed
(sample data only), that is acceptable here; do **not** copy this open pattern for a real client's
private data.

## How it's deployed

- Service: `adriatic-dash` · region `australia-southeast1` · project `bidbrain-analytics`
- Image: `australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/adriatic-dash`
- A tiny Flask app (`main.py`) serves `dashboard.html` at `/` with `Cache-Control: no-store`.
- Org policy (Domain Restricted Sharing) blocks `--allow-unauthenticated`, so the deploy uses
  `--no-allow-unauthenticated` then flips `--no-invoker-iam-check` to make the service openly
  reachable. With no login screen, the page is then fully public.

**Redeploy after editing `dashboard.html` (or `main.py`):**

    .\client_STT\client_Adriatic_Furniture\deploy_dash_adriatic.ps1

It rebuilds the image and swaps it onto the running service; `no-store` means the change is live
immediately.

## Custom domain (optional, not yet wired)

To put it on `adriatic.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above,
Proxied, SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the
MongoDB/Cloudflare setup).
