# clients/client_schneider/dash/ — the web app (stage 3)

A Cloud Run **Service** (`schneider-dash`): a thin password gate + static server. It renders a
Schneider-branded login screen, and once a session is authenticated it serves `dashboard.html` and
proxies the private `schneider.json` from GCS at `/data.json`. All charts/tabs/branding live in
`dashboard.html`; `main.py` only decides *who* may see it.

| File | What it is |
|---|---|
| `main.py` | Flask app: login gate (byte-for-byte the proven `client_STT` auth/serve/proxy logic), Schneider-branded login page, serves `dashboard.html` + `/data.json`. |
| `dashboard.html` | The dashboard UI — 5 tabs (Portfolio Overview · Spend & Pacing · Delivery & Funnel · Channel Comparison · Geography), Chart.js, Schneider green palette, the searchable internal-Campaign dropdown, CSV export. Reads `/data.json`. |
| `requirements.txt` | `Flask`, `gunicorn`, `google-cloud-storage`. |
| `Dockerfile` | `python:3.12-slim`, non-root, gunicorn. |
| `cloudbuild.yaml` | Build → push → `run deploy` → `--no-invoker-iam-check` (future trigger). |
| `LIVE_URL.md` | The live `…run.app` URL + how to read/rotate the password (service is live as of 2026-06-04). |

**Security:** the data bucket is private; the browser never touches it. `/data.json` returns 401
unless the session passed the password. The public `…run.app` URL just shows the login page. The
service runs `--no-invoker-iam-check` (org policy blocks `--allow-unauthenticated`); the app's own
password gate is the only door. See the [root security model](../../../README.md#7-security-model-read-before-changing-hosting).

**Runtime SA** `schneider-dash-web@…`: `roles/storage.objectViewer` on the bucket + `secretAccessor`
on `schneider-dash-password` and `schneider-dash-session-key`. Env: `GCS_BUCKET`,
`DATA_OBJECT=schneider.json`; secrets: `DASH_PASSWORD`, `SESSION_SECRET`.

Redeploy after editing: build the image, then `gcloud run services update schneider-dash --image …`
(see the [client README](../README.md#deploy--refresh-copy-paste-powershell)).
