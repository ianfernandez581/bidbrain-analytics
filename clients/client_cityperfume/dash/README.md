# clients/client_cityperfume/dash/ — the web app (stage 3)

A Cloud Run **Service** (`cityperfume-dash`): a thin password gate + static server. It renders a
City Perfume-branded login screen, and once a session is authenticated it serves `dashboard.html` and
proxies the private `cityperfume.json` from GCS at `/data.json`. All charts/tabs/branding live in
`dashboard.html`; `main.py` only decides *who* may see it, not *what* it shows. Auth/serve/proxy logic
is **byte-for-byte** the proven [`client_STT`](../../client_STT/dash/README.md) app — only the login
branding and the default data object differ.

| File | What it is |
|---|---|
| `main.py` | Flask app: login gate (STT auth/serve/proxy logic), City Perfume-branded login page (logo inlined as base64), serves `dashboard.html` with `Cache-Control: no-store` + `/data.json`. `SameSite=None; Secure` so the session cookie survives the cross-origin iframe on `dashboards.bidbrain.ai`. |
| `dashboard.html` | The dashboard UI — **6 tabs** (Overview · Paid Media · Website & GA4 · Sales & Products · Ads → Revenue · Year on Year), Chart.js, charcoal + champagne/gold palette, both logos (100% Digital + City Perfume) inlined in the topbar. Reads `/data.json`. |
| `requirements.txt` | `Flask`, `gunicorn`, `google-cloud-storage`. |
| `Dockerfile` | `python:3.12.13-slim`, non-root, gunicorn (`--timeout 0`; Cloud Run enforces the request timeout). |
| `cloudbuild.yaml` | Build → push → `run deploy` (future trigger; deploy as yourself from a laptop). |
| `deploy_dash_cityperfume.ps1` | Rebuild + image-swap **only** the service after a `dashboard.html` / `main.py` edit (env/secrets/job/views/IAM untouched). |
| `LIVE_URL.md` | The live URL + how to read/rotate the password. |
| `checker.py` | Local BigQuery reconciliation validator: prints the source-of-truth totals the dashboard must match + PASS/FAIL consistency checks across the same views the export job reads. Run with the repo venv. |

**Filters & ranges (client-side).** The topbar carries a global **Date range** picker (Looker-style,
DAY-grained — it clips every `*_daily` array and buckets trends by span), **Platform** + searchable
**Campaign** filters (rescale the ad side), and **Sales channel** chips (Website / Marketplace — scope
the online revenue side). The dashboard is **online-only** (in-store POS excluded); there is no
All/Online toggle and no Country filter. It shows `last_updated` + `data_through` from the JSON, never
a hardcoded refresh time.

**Security:** the data bucket is private; the browser never touches it. `/data.json` returns 401 unless
the session passed the password, and the JSON is **aggregates only** (no `email` / `customer_id`). The
public `…run.app` URL just shows the login page. The service runs `--no-invoker-iam-check` (org policy
blocks `--allow-unauthenticated`); the app's own password gate is the only door. See the
[root security model](../../../README.md#7-security-model-read-before-changing-hosting).

**Runtime SA** `cityperfume-dash-web@bidbrain-analytics.iam.gserviceaccount.com`:
`roles/storage.objectViewer` on the bucket + `secretAccessor` on `cityperfume-dash-password` and
`cityperfume-dash-session-key`. Env: `GCS_BUCKET`, `DATA_OBJECT=cityperfume.json`; secrets:
`DASH_PASSWORD`, `SESSION_SECRET`.

Redeploy after editing: `./deploy_dash_cityperfume.ps1` (rebuilds the image, then
`gcloud run services update cityperfume-dash --image …`). Because the service serves `dashboard.html`
with `Cache-Control: no-store` and always reads whatever JSON is currently in the bucket, the change is
live immediately.
