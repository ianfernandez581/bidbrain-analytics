# City Perfume dashboard — live URL

**Live (password-gated):**

> https://cityperfume-dash-p32gk2wuia-ts.a.run.app

(also reachable at `https://cityperfume-dash-516554645957.australia-southeast1.run.app`)

Deployed + verified **2026-06-06**: login page serves HTTP 200; `/data.json` returns 401 unauthenticated
and 200 once logged in (**no PII**); wrong password → 401, correct password → 302 → dashboard.
Refresh is **self-gating on a `*/10 * * * *` UTC scheduler** (`cityperfume-export-daily`): the export job
probes its upstream BigQuery tables each tick and rebuilds `cityperfume.json` only when one advanced, so
the dashboard tracks new data within ~10 min instead of on a fixed daily cron. The dashboard shows
`last_updated` (build time) and `data_through` (newest upstream `last_modified`, UTC) rather than a fixed
refresh time. Adjust the cadence with `..\..\scheduler.ps1 -Schedule "<cron>"`.

Password-gated — the page loads a login screen; enter the dashboard password
(Secret Manager: `cityperfume-dash-password`) to view it.

Read the current password: `gcloud secrets versions access latest --secret=cityperfume-dash-password`.
Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add cityperfume-dash-password --data-file=-`
(no redeploy needed — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`cityperfume.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly. It contains **aggregates only**: no `email`/`customer_id` or any
row-level PII from `v_sales` ever leaves BigQuery. See the
[root security model](../../../README.md#7-security-model-read-before-changing-hosting).

## Custom domain (optional, not yet wired)

To put it on `cityperfume.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above,
Proxied, SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the
MongoDB/Cloudflare/STT setup).
