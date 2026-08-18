# clients/client_sophiie/dash/ — the web app (password gate + the dashboard)

A **Cloud Run service** (`sophiie-dash`) that is always on. It shows a login screen, and once you are
authenticated it serves the dashboard and the data — and nothing otherwise.

**Plain English:** this is the *waiter behind a locked door*. A visitor sees a password box; enter the
right password and the dashboard appears, with the app fetching the data file from locked storage on
your behalf. No password → you get nothing, and the data file cannot be reached directly. All the
charts and tabs live in one HTML file; this Python file decides **who** may see it, not **what** it
shows.

**Where this sits:** this client is in **PREVIEW** — there is no `../job/` yet, so `/data.json` serves
the baked-in `placeholder.json` and `dashboard.html` draws every chart from that. Once an export job
exists it will write `sophiie.json` to the private bucket, which `/data.json` prefers automatically
and the sample banner clears itself. See [`../README.md`](../README.md) → FLIPPING PREVIEW → LIVE.

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The Flask app: login, session, the gated routes, and `POST /report`. Its `LOGIN_HTML` carries a **CSS-only** aurora (orbs + diagonal bands, no canvas) so the login renders instantly. |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — the three-layer aurora background, all three tabs, charts, filters, the date picker, CSV export and the headless slide-deck path. Baked into the container; fetches `/data.json` on load. |
| [`placeholder.json`](placeholder.json) | The SAMPLE payload (`meta.placeholder=true`). **Generated** by `../gen_placeholder.py` — never hand-edit. |
| [`logo.png`](logo.png) | Sophiie's **supplied mark** (the headset), a copy of `../creatives/sophiie_logo.png`. Served at `/logo.png` for the login page, the favicon and the AI deck. |
| [`report.py`](report.py) | AI deck generator (two-stage: research then structure), prompts written for Sophiie's AI-receptionist business. **Dormant** until `/report` is enabled. |
| [`platform_sso.py`](platform_sso.py) | Cross-subdomain SSO verifier (trusts the platform's `bb_sso` cookie in addition to the local password). Vendored, unchanged. |
| [`bb_deck.js`](bb_deck.js) | Shared, theme-driven `.pptx` builder. Vendored, unchanged — canonical copy in `clients/client_mongodb/dash/`. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim` + gunicorn, non-root. COPYs `main.py`, `report.py`, `platform_sso.py`, `dashboard.html`, `placeholder.json`, `bb_deck.js`, `logo.png`. |
| [`requirements.txt`](requirements.txt) | `Flask`, `gunicorn`, `google-cloud-storage`, `anthropic`, `httpx`. Kept out of the dev venv on purpose. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run deploy sophiie-dash` → re-apply `--no-invoker-iam-check` (so a redeploy never silently drops public reachability). |
| [`deploy_dash_sophiie.ps1`](deploy_dash_sophiie.ps1) | Redeploy just this service after a UI edit (image swap only; env/secrets/IAM preserved). |
| [`enable_report_sophiie.ps1`](enable_report_sophiie.ps1) | **One-time** setup for the AI deck: keys/secrets, `roles/aiplatform.user`, bucket write for the report cache, and `--timeout 900`. |
| [`LIVE_URL.md`](LIVE_URL.md) | The service URL, the portal tile state, and the standup commands. |

## Routes (`main.py`)

| Route | Behaviour |
|---|---|
| `GET /` | Not logged in → the login page. Logged in → `dashboard.html` (sent `Cache-Control: no-store`, so a redeploy is picked up immediately). |
| `POST /login` | Constant-time (`hmac.compare_digest`) check against `DASH_PASSWORD`. Success → session cookie; wrong → 401. |
| `GET /logout` | Clears the session. |
| `GET /data.json` | **The only data path.** 401 unless authenticated; then streams `sophiie.json` from the private bucket, falling back to the baked-in `placeholder.json` while the bucket is empty. The bucket stays private — the browser never touches it. |
| `GET /logo.png` | The mark. **Public** — the login page is itself unauthenticated and renders it. |
| `GET /creative-img/<id>` | A Meta creative image cached in our bucket by the export job (a permanent copy that outlives Meta's signed CDN URL). Same auth as `/data.json`. Unused until the pipeline exists. |
| `POST /report` | **AI deck.** 401 unless authenticated; serves a cached report keyed by data version or calls `report.py`. Dormant until `enable_report_sophiie.ps1` has run. |
| `GET /bb_deck.js` | The slide builder. Auth-gated (the deck reveals report content). |
| `GET /healthz` | Liveness check. |

**Security details:** session cookies are `HttpOnly`, `Secure`, `SameSite=None`, 12-hour lifetime.
`SameSite=None` (which requires `Secure`) is deliberate: the dash is embedded as a **cross-origin
iframe** on `dashboards.bidbrain.ai`, and a `Lax` cookie would be dropped on that third-party
request. Config (`GCS_BUCKET`, `DATA_OBJECT`) and secrets (`DASH_PASSWORD`, `SESSION_SECRET`) are
injected by Cloud Run.

## What the dashboard shows (`dashboard.html`)

Sophiie AI's brand blues on **the aurora skin** — three fixed animated background layers with solid
white cards floating over them. Read the aurora section of [`../README.md`](../README.md) before
touching the styling: there are four rules that break the design if ignored, and one tuned animation
constant. One external chart library: Chart.js 4.5.0.

**Sticky control bar:** the tab rail, a Looker-style date-range picker, funnel-stage chips, a search
box, and CSV export ("this tab" / "all data"). Three tabs:

1. **Overview** — the north-star KPI row (Meta enquiries · cost/enquiry · **qualified leads
   (modelled)**, which wears the aurora gradient border · ad spend) over a delivery-quality row
   (impressions/CPM · CTR · LP views · reach/frequency); delivery over time with axis + grain
   toggles; budget pacing and progress-to-goal; the cumulative on-track-to-goal chart; the enquiry
   funnel and spend-by-stage; audience and placement breakdowns; and an insight strip.
2. **Paid Media** — performance vs targets by campaign, the cost-per-enquiry vs CTR efficiency map,
   CPL over time, reach & frequency, video engagement, day-of-week, spend by ad set, budget burn,
   the per-ad table with a thin-volume guard, and the creative-fatigue watch.
3. **Creative** — the top 10 creatives by spend with real headline, copy and performance, and a
   branded fallback tile for any ad whose Meta thumbnail link has expired.

It fetches **one** payload from `/data.json` and renders everything client-side — see the JSON
contract in [`../README.md`](../README.md) (and `../gen_placeholder.py`, which is that contract
written down as a working example until the job exists).

Every dashboard also carries the **spend-multiplier shim** (`bbMultFor`/`bbApplySpendMult`), which
grosses RAW spend by `window.BB_SPEND_MULT` per channel so the client sees what they were billed.
Sophiie is Meta-only, so a single `meta` factor covers every row. Any new spend field or aggregate
must be grossed too, and CSV exports must keep filtering out the `_`-prefixed stash keys — they leak
raw pre-markup spend otherwise.
