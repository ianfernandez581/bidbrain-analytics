# clients/client_proptrack/dash/ — the web app (stage 3)

A Cloud Run **Service** (`proptrack-dash`): a thin password gate + static server. It renders a
PropTrack-branded login screen, and once a session is authenticated it serves `dashboard.html` and
proxies the private `proptrack.json` from GCS at `/data.json`. All charts/tabs/branding live in
`dashboard.html`; `main.py` only decides *who* may see it.

| File | What it is |
|---|---|
| `main.py` | Flask app: login gate (byte-for-byte the proven `client_STT` auth/serve/proxy logic), PropTrack-branded login page, serves `dashboard.html` + `/data.json`. |
| `dashboard.html` | The dashboard UI — 3 tabs (Overview · Programmatic/Trade Desk · Paid Social/LinkedIn), Chart.js, PropTrack brand palette (near-black canvas + white + vivid blue `#1F6FEB`, Inter), real PropTrack + Transmission logos in the topbar, AUD. Reads `/data.json`. |
| `requirements.txt` | `Flask`, `gunicorn`, `google-cloud-storage`. |
| `Dockerfile` | `python:3.12-slim`, non-root, gunicorn. |
| `cloudbuild.yaml` | Build → push → `run deploy` → `--no-invoker-iam-check` (future trigger). |
| `LIVE_URL.md` | The live URL + password reference. |

**Security:** the data bucket is private; the browser never touches it. `/data.json` returns 401 unless
the session passed the password. The public `…run.app` URL just shows the login page. The service runs
`--no-invoker-iam-check` (org policy blocks `--allow-unauthenticated`); the app's own password gate is the
only door.

**Runtime SA** `proptrack-dash-web@…`: `roles/storage.objectViewer` on the bucket + `secretAccessor` on
`proptrack-dash-password` and `proptrack-dash-session-key`. Env: `GCS_BUCKET`, `DATA_OBJECT=proptrack.json`;
secrets: `DASH_PASSWORD`, `SESSION_SECRET`.

Redeploy after editing: `.\client_proptrack\dash\deploy_dash_proptrack.ps1` (build the image, then
`gcloud run services update proptrack-dash --image …`).
