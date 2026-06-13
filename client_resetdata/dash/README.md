# client_resetdata/dash/ — the web app (stage 3)

A Cloud Run **Service** (`resetdata-dash`): a thin password gate + static server. It renders a
ResetData-branded login screen, and once a session is authenticated it serves `dashboard.html` and
proxies the private `resetdata.json` from GCS at `/data.json`. All charts/tabs/branding live in
`dashboard.html`; `main.py` only decides *who* may see it, not *what* it shows.

| File | What it is |
|---|---|
| `main.py` | Flask app: login gate (byte-for-byte the proven `client_STT` / `client_mongodb` auth/serve/proxy logic), ResetData-branded login page (`LOGIN_HTML`, with the 100% Digital agency mark + ResetData wordmark inline as base64), serves `dashboard.html` + `/data.json`. Session cookie is `SameSite=None; Secure` (cross-site iframe on dashboards.bidbrain.ai). `DATA_OBJECT` defaults to `resetdata.json`. |
| `dashboard.html` | The dashboard UI — 4 tabs (Overview · Paid Media · Website Traffic · Ads → Traffic), Chart.js, crimson-pink (`#E84A6F`) on deep-navy palette, ResetData wordmark topbar. Two filters: **Platform** (Google / Meta / TTD) and **Campaign** (searchable multi-select). Reads `/data.json`. |
| `requirements.txt` | `Flask`, `gunicorn`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12.13-slim`, non-root, gunicorn (2 workers × 8 threads). |
| `cloudbuild.yaml` | Build → push → `run deploy` → `--no-invoker-iam-check` (future push-to-main trigger). |
| `deploy_dash_resetdata.ps1` | Rebuild + swap the image onto the running service after editing `dashboard.html` or `main.py`. The fast path (leaves env/secrets/job/views/IAM untouched). |
| `LIVE_URL.md` | The live URL + how to read/rotate the password. |

**Security:** the data bucket is private; the browser never touches it. `/data.json` returns 401 unless
the session passed the password. The public `…run.app` URL just shows the login page. The service runs
`--no-invoker-iam-check` (org policy blocks `--allow-unauthenticated`); the app's own password gate is the
only door. See the [root security model](../../README.md#7-security-model-read-before-changing-hosting).

**Runtime SA** `resetdata-dash-web@…`: `roles/storage.objectViewer` on the bucket + `secretAccessor` on
`resetdata-dash-password` and `resetdata-dash-session-key`. Env: `GCS_BUCKET`, `DATA_OBJECT=resetdata.json`;
secrets: `DASH_PASSWORD`, `SESSION_SECRET`.

Redeploy after editing: `.\client_resetdata\dash\deploy_dash_resetdata.ps1`
(or build the image, then `gcloud run services update resetdata-dash --image …` — see the
[client README](../README.md#deploy--refresh-powershell-project-bidbrain-analytics-region-australia-southeast1)
section).
The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy shows immediately.
