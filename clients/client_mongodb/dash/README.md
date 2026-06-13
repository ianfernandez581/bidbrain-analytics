# clients/client_mongodb/dash/ — the Web App (stage 3: password gate + dashboard)

> A **Cloud Run Service** (`mongodb-dash`) that's always on. It shows a login screen, and once
> you're authenticated it serves the dashboard and the data — and nothing otherwise.

**Plain English:** this is the *waiter behind a locked door*. A visitor sees a password box;
enter the right password and the dashboard appears, with the app fetching the data file from
locked storage on your behalf. No password → you get nothing, and the data file can't be
reached directly. All the charts and tabs you see live in one HTML file; this Python file only
decides **who** may see it, not **what** it shows.

**Where this sits:** [`../job/`](../job/README.md) writes `mongodb.json` to the private bucket →
**[this app]** authenticates the user and serves it at `/data.json` → `dashboard.html` draws
the charts.

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The Flask app: login, session, and the gated routes. ~135 lines, mostly the login page. |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — all tabs, charts, filters, and the CSV export. Baked into the container; fetches `/data.json` on load. ~1,660 lines (HTML + CSS + inline JS). |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim` + gunicorn, non-root, copies `main.py` + `dashboard.html`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run deploy mongodb-dash` → re-apply `--no-invoker-iam-check` (so a redeploy never silently drops public reachability). |
| [`requirements.txt`](requirements.txt) | `Flask`, `gunicorn`, `google-cloud-storage` (pinned older than the job's — kept out of the dev venv on purpose). |
| [`LIVE_URL.md`](LIVE_URL.md) | The live `…run.app` URL, the intended `mongodb.bidbrain.ai`, and how to re-fetch the URL. |
| `.dockerignore` | Keeps the build context lean. |

---

## Routes (`main.py`)

| Route | Behaviour |
|---|---|
| `GET /` | Not logged in → the login page. Logged in → `dashboard.html` (sent `Cache-Control: no-store` so a redeploy is picked up immediately). |
| `POST /login` | Constant-time (`hmac.compare_digest`) password check against `DASH_PASSWORD`. Success → session cookie; wrong → 401. |
| `GET /logout` | Clears the session. |
| `GET /data.json` | **The only data path.** 401 unless authenticated; then streams `mongodb.json` from the private bucket (also `no-store`). The bucket itself stays private — the browser never touches it. |
| `GET /healthz` | Liveness check. |

**Security details:** session cookies are `HttpOnly`, `Secure`, `SameSite=None`, 12-hour
lifetime. `SameSite=None` (which requires `Secure`) is deliberate: the dash is embedded as a
**cross-origin iframe** on `dashboards.bidbrain.ai`, and a `Lax` cookie would be dropped on that
third-party request. The cookie is also **not pinned to a domain** so login works through the
Cloudflare proxy. Config (`GCS_BUCKET`, `DATA_OBJECT`) and secrets (`DASH_PASSWORD`,
`SESSION_SECRET`) are injected by Cloud Run.

---

## What the dashboard shows (`dashboard.html`)

Branding: "MongoDB APAC — Live Dashboard" (Transmission + MongoDB logos; MongoDB greens). One
external library: Chart.js 4.5.0. **Sticky control bar:** a **DNB ↔ KGA (IDC)** campaign toggle,
multi-select **region chips**, and CSV export ("this tab" / "all data"). Three tabs:

1. **Paid Media** — Trade Desk delivery. KPI tiles (spend, impressions/CPM, clicks/CTR, blended
   CPC), a strategy-performance table vs benchmarks, daily imps/clicks/CTR (mixed chart),
   spend-by-strategy (doughnut), daily stacked spend, spend-by-market, a CTR/clicks/CPC
   efficiency trio, market-stacked-by-strategy, and a market summary table.
2. **Content Syndication** — Salesforce lead pacing. Snapshot (target, leads, pacing, outlook),
   leads-vs-target and time-progress bars, weekly pacing, leads by market, leads by programme
   (doughnut), a per-region mini-card grid, and a programme×market table.
3. **CS Comparison** — two side-by-side region panels (target, leads, outlook, targets and
   weekly-pacing charts).

It fetches **one** payload from `/data.json` and renders everything client-side — see the JSON
contract in [`../job/README.md`](../job/README.md).

---

## Deploy (manual today)

```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_mongodb/dash --tag $IMG --region australia-southeast1
gcloud run services update mongodb-dash --image $IMG --region australia-southeast1
```
The service goes live as soon as the new revision is ready (no "run" step) and serves whatever
JSON is currently in the bucket. To change the password, add a new version of the
`mongodb-dash-password` secret and redeploy (it picks up `:latest` on next start).

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../job/README.md`](../job/README.md) — stage 2 (produces the JSON this app serves).
- [Root README §7](../../../README.md#7-security-model-read-before-changing-hosting) — why the gate is the whole security model.
