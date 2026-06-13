# clients/client_hireright/dash/ — the web app (stage 3)

A Cloud Run **Service** (`hireright-dash`): a thin password gate + static server. It renders a
HireRight-branded login screen, and once a session is authenticated it serves `dashboard.html` and
proxies the private `hireright.json` from GCS at `/data.json`. All charts/tabs/branding live in
`dashboard.html`; `main.py` only decides *who* may see it.

| File | What it is |
|---|---|
| `main.py` | Flask app: login gate (byte-for-byte the proven `client_STT` auth/serve/proxy logic), HireRight-branded login page, serves `dashboard.html` + `/data.json`. |
| `dashboard.html` | The dashboard UI — 2 tabs (Overview · Paid Media), Chart.js, HireRight wordmark (HIRE black · RIGHT red) + red/black/grey palette. Reads `/data.json`. |
| `requirements.txt` | `Flask`, `gunicorn`, `google-cloud-storage`. |
| `Dockerfile` | `python:3.12-slim`, non-root, gunicorn. |
| `cloudbuild.yaml` | Build → push → `run deploy` → `--no-invoker-iam-check` (future trigger). |
| `LIVE_URL.md` | The live URL + password. |

> The HireRight wordmark in both the topbar (`dashboard.html`) and the login page (`main.py`) is an
> inline SVG recreation (HIRE black · RIGHT red + corner-bracket motif + ®) in the brand red `#ED1C24`.
> If you have the official vector logo, drop it in to replace the inline SVG.

**Security:** the data bucket is private; the browser never touches it. `/data.json` returns 401 unless
the session passed the password. The public `…run.app` URL just shows the login page. The service runs
`--no-invoker-iam-check` (org policy blocks `--allow-unauthenticated`); the app's own password gate is the
only door. See the [root security model](../../../README.md#7-security-model-read-before-changing-hosting).

**Runtime SA** `hireright-dash-web@…`: `roles/storage.objectViewer` on the bucket + `secretAccessor` on
`hireright-dash-password` and `hireright-dash-session-key`. Env: `GCS_BUCKET`, `DATA_OBJECT=hireright.json`;
secrets: `DASH_PASSWORD`, `SESSION_SECRET`.

Redeploy after editing: build the image, then `gcloud run services update hireright-dash --image …`
(see the [client README](../README.md#deploy--refresh-copy-paste-powershell)).
