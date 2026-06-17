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
| [`main.py`](main.py) | The Flask app: login, session, the gated routes, and the `POST /report` endpoint (auth + GCS cache, delegates generation to `report.py`). |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — all tabs, charts, filters, the CSV export, and the **AI report** (button + on-screen preview + a client-side **4-slide Google Slides** `.pptx` download via PptxGenJS). Baked into the container; fetches `/data.json` on load. |
| [`report.py`](report.py) | **AI report generator** (vendored, like `platform_sso.py`). Two Claude Opus 4.8 calls — Stage A researches the "why" with **live web search**, Stage B structures it into the strict slide JSON. See [§ AI report](#ai-report-download-slides--google-slides). |
| [`platform_sso.py`](platform_sso.py) | Cross-subdomain SSO verifier (trusts the platform's `bb_sso` cookie in addition to the local password). |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim` + gunicorn, non-root, copies `main.py` + `platform_sso.py` + `report.py` + `dashboard.html`. |
| [`enable_report_mongodb.ps1`](enable_report_mongodb.ps1) | **One-time** setup for the AI report: creates the `anthropic-api-key` secret, grants the runtime SA secret-read + bucket-write, mounts the key, and bumps the service `--timeout`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → `gcloud run deploy mongodb-dash` → re-apply `--no-invoker-iam-check` (so a redeploy never silently drops public reachability). |
| [`requirements.txt`](requirements.txt) | `Flask`, `gunicorn`, `google-cloud-storage`, `anthropic` (the report generator). Kept out of the dev venv on purpose. |
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
| `POST /report` | **AI report.** 401 unless authenticated. The browser POSTs the current view's numbers; the route serves a cached report (keyed by view + data version) or calls `report.py` to generate one, caches it in `gs://…/reports/`, and returns the slide JSON. See [§ AI report](#ai-report-download-slides--google-slides). |
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
multi-select **region chips**, **Download slides** (the AI Google Slides deck — see [§ AI report](#ai-report-download-slides--google-slides)),
and CSV export ("this tab" / "all data"). Three tabs:

1. **Paid Media** — Trade Desk delivery. KPI tiles (spend, impressions/CPM, clicks/CTR, blended
   CPC), a strategy-performance table vs benchmarks, daily imps/clicks/CTR (mixed chart),
   spend-by-strategy (doughnut), daily stacked spend, spend-by-market, a CTR/clicks/CPC
   efficiency trio, market-stacked-by-strategy, and a market summary table. **Then a
   filter-independent "Content engagement" section** (the `pixel` payload): content-asset LP
   views, plus spend by device / ad-environment and impressions by creative size — see the
   [client README](../README.md#content-engagement-trade-desk-universal-pixel--a-static-seed).
2. **Content Syndication** — Salesforce lead pacing. Snapshot (target, leads, pacing, outlook),
   leads-vs-target and time-progress bars, weekly pacing, leads by market, leads by programme
   (doughnut), a per-region mini-card grid, and a programme×market table.
3. **CS Comparison** — two side-by-side region panels (target, leads, outlook, targets and
   weekly-pacing charts).

It fetches **one** payload from `/data.json` and renders everything client-side — see the JSON
contract in [`../job/README.md`](../job/README.md).

---

## AI report (Download slides → Google Slides)

The control bar's **Download slides** button generates a branded, **4-slide** account deck —
**1) Cover (client + agency logos) · 2) What happened? · 3) Why did it happen? · 4) What should we
do?** — for the *current* campaign + region over the **full flight** (campaign start → latest data,
ignoring any on-screen date sub-range), shows an on-screen preview of the three analytical slides,
then **downloads an editable `.pptx`** you open in Google Slides (drag into Drive → opens as native
Google Slides). The deck is built **client-side** with **PptxGenJS** (pinned `4.0.1`, loaded from
jsDelivr like Chart.js — no new GCP infra) in `buildSlidesDeck()`; the MongoDB wordmark is rasterized
from the live DOM SVG to a PNG so brand typography survives the Slides import (Arial everywhere else,
the only Google-Slides-safe face). It's Transmission-branded (MongoDB is a Transmission client). This
is the **sample/first build** of a feature intended for every client dashboard.

Because the deck always reports the full flight, the `/report` cache key (view + data version) is
stable across the day, so the AI deck regenerates **at most once per campaign/region per day** — it
"runs once a day" as data advances, and re-downloads are instant from cache.

**How it works (two Claude calls — the split is forced):** structured outputs are incompatible
with the citations web search emits, so [`report.py`](report.py) does:
1. **Stage A — research.** Claude **Opus 4.8** + **web search/fetch** (streamed, adaptive
   thinking) reads the numbers and researches *why* they moved — programmatic-display and B2B
   content-syndication benchmarks, APAC category/seasonality context — with cited sources.
2. **Stage B — structure.** Opus 4.8 (no tools) turns the notes + numbers into the strict slide
   JSON (`output_config` `json_schema`) the page renders.

**Numbers vs narrative:** slide-1 KPI values come **verbatim from the figures the browser POSTs**
(the same aggregations the dashboard renders — `buildReportPayload()`), so the report and the
dashboard can't disagree. The model writes the *narrative*, the "why", and the actions — never the
numbers. The honesty/anti-injection/no-PII guardrails live in the system prompts in `report.py`.

**Gemini fallback (Claude unusable):** if the Claude call fails because Claude is unusable for an
infra/account reason — **429/529** (rate/capacity), a **400 "credit balance is too low"** (unfunded
account), or **401/403** (bad/disabled key) — *and* a `GEMINI_API_KEY` is configured, `report.py`
(`_should_fallback`) regenerates the whole report on **Google Gemini** (`GEMINI_MODEL`, default
`gemini-2.5-pro`) — same prompts + brief + slide schema, with web research via **Google Search
grounding** instead of Anthropic web search (plain REST through the bundled `httpx`, no extra
dependency). The deck footer + status pill show which model actually generated it (e.g.
`gemini-2.5-flash (Claude fallback)`). Any *genuine* Claude error (a real 400 validation bug, our own
RuntimeErrors) still propagates (so real bugs aren't masked). This is what lets the report work even while the Claude org is on a low tier;
removing the `gemini-api-key` secret disables the fallback. **Note:** Anthropic Tier 1 (10k input
tokens/min) is too low for a single web-grounded Opus report — raise the tier at
`console.anthropic.com/settings/limits` to use Claude as the primary, or rely on the Gemini fallback.

**The data contract** (matched by name, like the rest of the pipeline):
`buildReportPayload()` / `buildDeckPayload()` (dashboard.html) → `_fmt_brief()` keys (report.py) →
`REPORT_SCHEMA` (report.py) → `renderReportDeck()` (on-screen preview) **and** `buildSlidesDeck()`
(the downloaded Google Slides `.pptx`) (dashboard.html). Rename a key in one place → fix all the rest.

**Caching & cost.** The route caches each generated report in `gs://bidbrain-analytics-mongodb-dash/reports/`,
keyed by **view identity + `data_through`** — so re-downloading the same view is instant and free,
and it only regenerates when the underlying data advances. Cost is ~a few Opus calls + web-search
units per *distinct* (view × data-version). Bump `REPORT_CACHE_VERSION` in `main.py` to invalidate
all cached reports after a prompt/schema change.

**One-time setup** (needs an Anthropic API key; the key never enters git — it lives in Secret
Manager / `bidbrain-vault/`):
```powershell
# provide the key via -Key, $env:ANTHROPIC_API_KEY, or bidbrain-vault\anthropic-api-key.txt
.\clients\client_mongodb\dash\enable_report_mongodb.ps1 -Key "sk-ant-..."
```
That creates the `anthropic-api-key` secret, grants the runtime SA `mongodb-dash-web@`
secret-read **and** bucket object-write (for the cache), mounts `ANTHROPIC_API_KEY`, and sets the
Cloud Run `--timeout` to 900s (the two-stage call can take 20-60s). Then redeploy the image
(below) so `report.py` + the new `dashboard.html` ship. The mount + timeout persist across image
swaps.

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
