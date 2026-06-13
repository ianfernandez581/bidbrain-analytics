# status_dashboard/dash/ — the web app (stage 3)

A Cloud Run **Service** (`status-dash`): a thin password gate + static server. It renders a login screen,
and once a session is authenticated it serves `dashboard.html` and proxies the private `status.json` from
GCS at `/data.json`. All presentation logic lives in `dashboard.html`; `main.py` only decides *who* may
see it, not *what* it shows. The JSON is assembled by [`../job/`](../job/README.md) (the `status-export`
Cloud Run job).

| File | What it is |
|---|---|
| `main.py` | Flask app: login gate (byte-for-byte the proven `client_mongodb`/`client_STT` auth/serve/proxy logic), serves `dashboard.html` + `/data.json`. Session cookie is `SameSite=None; Secure` so it works inside the cross-site `dashboards.bidbrain.ai` iframe. |
| `dashboard.html` | The dashboard UI — 2 tabs (**Data Sync Status**, **Data Accuracy**), pure HTML/CSS/JS, no chart libs. Reads `/data.json` (`DATA.generated_at`, `DATA.clients[].freshness.{verdict, transmission_latest, ingest_latest, build_at, data_through, caught_up}`, `DATA.clients[].accuracy[].{snowflake_value, dashboard_value, match, snowflake_query, note, computed_at}`). |
| `requirements.txt` | `Flask`, `gunicorn`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12.13-slim`, non-root (`appuser`), gunicorn (2 workers, 8 threads). |
| `deploy_dash_status.ps1` | Rebuild the image + `gcloud run services update status-dash --image …` (env/secrets/job/IAM untouched). The common, fast path after a UI edit. |

There is **no `cloudbuild.yaml`** in this folder; redeploy with `deploy_dash_status.ps1` (build-as-yourself,
the same manual rule as the rest of the repo — cloudbuild-from-laptop fails on `iam.serviceaccounts.actAs`).

**Security:** the data bucket is private; the browser never touches it. `/data.json` returns 401 unless the
session passed the password. The public `…run.app` URL just shows the login page. The service runs
`--no-invoker-iam-check` (org policy blocks `--allow-unauthenticated`); the app's own password gate is the
only door. `dashboard.html` is served with `Cache-Control: no-store`, so a redeploy shows immediately.

**Runtime SA** `status-dash-web@…`: `roles/storage.objectViewer` on `bidbrain-analytics-status-dash` +
`secretAccessor` on `status-dash-password` and `status-dash-session-key`. Env: `GCS_BUCKET`,
`DATA_OBJECT=status.json`; secrets: `DASH_PASSWORD`, `SESSION_SECRET`.

Redeploy after editing `dashboard.html` or `main.py`: `.\status_dashboard\dash\deploy_dash_status.ps1`.
Then point **status.bidbrain.ai** at the `status-dash` service in Cloudflare DNS (same as the client
dashboards).
