# clients/client_sophiie/dash/ — the web app (password gate + the dashboard)

A **Cloud Run service** (`sophiie-dash`) that is always on. It shows a login screen, and once you are
authenticated it serves the dashboard and the data — and nothing otherwise.

**Plain English:** this is the *waiter behind a locked door*. A visitor sees a password box; enter the
right password and the dashboard appears, with the app fetching the data file from locked storage on
your behalf. No password → you get nothing, and the data file cannot be reached directly. All the
charts and tabs live in one HTML file; this Python file decides **who** may see it, not **what** it
shows.

**Where this sits:** the pipeline EXISTS and is deployed (`../sql/`, `../job/`, the `sophiie-export`
job and its `*/10` scheduler). `/data.json` prefers the real `sophiie.json` in the private bucket and
falls back to the baked-in `placeholder.json` while that bucket is empty - which it still is, because
the Trade Desk advertiser `gjcl0pp` has not been granted to the Windsor connector yet. The export job
refuses to publish an empty fact, so the sample stays up and the banner clears ITSELF on the first
tick after real rows land. See [`../README.md`](../README.md) → GO-LIVE.

## TRY FREE CLICKS ARE OFF THE DASHBOARD (client request, 2026-09-11) - read this first

**Every client-facing Try free click and CPA surface is withheld behind ONE flag**,
`SIGNUPS_REPORTABLE` in [`dashboard.html`](dashboard.html). It is a **client instruction, not a
measurement judgement** - do not re-add a surface because the numbers look right. Set the flag back
to `true` and every one of them returns, correctly labelled; that is a dash deploy and nothing else.

**This sits ON TOP of the Try free relabel, not instead of it.** The relabel (246e0d3, same day)
established what the metric actually is; this withholds it while the tagging is settled. Every
string behind the flag says "Try free click", so flipping it on reveals the CORRECT label rather
than restoring the old "sign-ups" wording. Keep it that way if you edit either.

**Do NOT put the reason on the page.** The withheld copy says only what the dashboard *does* report.
No surface, caption, footnote, CSV or deck may mention tagging, tracking, pixels, a pause or a
pending fix, and `report.py` is instructed not to speculate about the absence either.

**The data path is deliberately UNTOUCHED.** `sql/*`, `job/main.py` and the published `sophiie.json`
still carry `pv_conv` / `pc_conv` in full, and they MUST: the two status-pipeline accuracy checks
(`Trade Desk - Sign-ups post-view` / `post-click`, `status_dashboard/job/main.py`) compare
`rows[].pv_conv` / `pc_conv` against BigQuery, so stripping the pipeline would turn the accuracy
monitor red. This is the caltex site-visits precedent, built as geocon's one-flag pattern.

### The two predicates, and why there are two

| Predicate | Gates | Meaning |
|---|---|---|
| `signupsMeasured()` | nothing directly | what the FEED reports (`pv_conv`/`pc_conv` non-zero) |
| `signupsReported()` | RENDERING | measured AND publishable - the old gate, semantics unchanged |
| `signupsWithheld()` | COPY | the flag is off, so the wording must not imply "not yet attributed" |

The copy gate exists because the pre-existing not-yet-attributed wording ("none attributed yet",
"it switches ... on the first one") is **true of an early flight and false here** - The Trade Desk
*is* attributing these, we are simply not publishing them. Reusing it would put a false claim on
screen.

### What the flag moves

`renderSignupScope()` is the single application point: it toggles `body.no-signups` (one CSS rule
hides every `.c-sign` table cell), hides the attribution donut and the weekly card, and rewrites the
five captions that name the metric in prose. Beyond that -

- **KPI band** - the outcome pair is REPLACED by impressions + CTR (a two-tile band reads as a
  broken page); click-to-Try-free leaves the context row.
- **Overview** - the goal bar, the third funnel step and the signal insight card go; pace-to-goal
  runs on impressions with its own third wording branch.
- **Delivery** - the Try free clicks / CPA / delta columns hide; `readFor()` drops its two CPA
  verdict arms ("Scale it", "No Try free clicks yet") because a verdict states the count in words.
- **CSV** - all four exports drop the columns and SWAP in delivery ones, so none is left thin.
- **AI deck** - `signFields()` DELETES the keys from every payload object rather than asking the
  model not to use them (the prompt is a request, an absent key is a fact), and `_scope_directive()`
  in [`report.py`](report.py) appends an authoritative block to BOTH system prompts on BOTH
  providers. `signups_reported` crosses to the server and defaults `True` there, so a stale cached
  client build still renders correctly.

### `syncGrids()` - a hidden card must not strand its partner

Cards hide for several independent reasons (metric withheld, no video on a display buy, no
attribution data), and each left its two-column row half empty, which reads as a panel that failed
to load. `syncGrids()` collapses any `.grid.cols-2` down to one column when a single card survives.
It runs LAST in `render()` **and again on every tab switch** - a card inside a `display:none` pane
computes `display:none` itself, so a grid measured while its tab was hidden reports zero visible
cards and would never be collapsed. This also fixes the pre-existing ragged row left by the
auto-hiding video card.

Verified headless against data carrying 123 Try free clicks: zero occurrences of "Try free", "CPA"
or "sign-up" across all three tabs, zero ragged grids, all four CSV headers clean, every deck object
stripped, and flipping the flag back restores all of it under the correct label.

## Pacing is measured to the DATA date, not to today (2026-09-11)

`pace_expected` is `daily_pace * days_covered`, where `days_covered` runs from the flight start to
**the last day the delivery data covers** (`flight.pace_through`). It is deliberately NOT
`days_elapsed`, which still counts to today and drives the "Day N of M" chip.

Why: this feed is structurally 1-2 days behind (TTD refuses same-day data, the Windsor loader walks
back from yesterday), so dividing spend-to-date by an expectation that includes days no data exists
for reported **58% of pace - "Under pace"** on a campaign running at **105% of plan rate**. The two
figures measured different windows. A Windsor read pause on 2026-09-10 had frozen the feed one
extra day, which widened the gap but did not cause it.

`days_covered` starts at the FLIGHT START, not first delivery - the campaign's flight opened 09-03
and first delivered 09-04, and that missed day is a genuine shortfall that must stay counted. It is
why the corrected reading is 87%, not 105%.

`projected_spend` was already correct (it divides by `delivering_days`) and is unchanged.

**`meta.data_through` now states DATA COVERAGE** (max fact date). It used to be the max of the
freshness-probe timestamps, which advance on any run that touches the mirror - including the failed
Windsor run of 2026-09-10, which pushed it to 09-10 while the newest delivery was 09-08. The probe
timestamp is still emitted as `meta.upstream_checked_at`.

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The Flask app: login, session, the gated routes, and `POST /report`. Its `LOGIN_HTML` carries a **CSS-only** aurora (orbs + diagonal bands, no canvas) so the login renders instantly. |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — the three-layer aurora background, all three tabs, charts, filters, the date picker, CSV export and the headless slide-deck path. Baked into the container; fetches `/data.json` on load. |
| [`placeholder.json`](placeholder.json) | The SAMPLE payload (`meta.placeholder=true`). **Generated** by `../gen_placeholder.py` — never hand-edit. |
| `marble-band.jpg` / `marble-cell.jpg` / `marble-tile.jpg` | The Chronicle texture. Baked into the image, served from a name whitelist by `main.py`, referenced RELATIVELY in CSS so they resolve behind the proxy. |
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
| `GET /<name>.jpg` | The three marble textures, by exact-name whitelist (never an arbitrary file read). **Public** - decorative, no client data. Cached a week. |
| `GET /logo.png` | The mark. **Public** — the login page is itself unauthenticated and renders it. |
| `GET /creative-img/<id>` | Inherited from the Meta template. **Permanently unused on this client**: The Trade Desk reports creative NAMES and formats, never images, so the export job caches nothing and the Creative tab renders branded tiles instead. Kept only so the route does not 404 if an old link is followed. |
| `POST /report` | **AI deck.** 401 unless authenticated; serves a cached report keyed by data version or calls `report.py`. Dormant until `enable_report_sophiie.ps1` has run. |
| `GET /bb_deck.js` | The slide builder. Auth-gated (the deck reveals report content). |
| `GET /healthz` | Liveness check. |

**Security details:** session cookies are `HttpOnly`, `Secure`, `SameSite=None`, 12-hour lifetime.
`SameSite=None` (which requires `Secure`) is deliberate: the dash is embedded as a **cross-origin
iframe** on `dashboards.bidbrain.ai`, and a `Lax` cookie would be dropped on that third-party
request. Config (`GCS_BUCKET`, `DATA_OBJECT`) and secrets (`DASH_PASSWORD`, `SESSION_SECRET`) are
injected by Cloud Run.

## What the dashboard shows (`dashboard.html`)

**"Chronicle - marble"** over a toned-down aurora: rounded tiles lifted on shadow (no borders
anywhere), figures on `tabular-nums`, everything set in **Inter Variable** (2026-08-19 - the original
editorial Fraunces + IBM Plex Mono pairing was rejected by the client), and a very
pale marble texture on five surfaces. Read the skin section of [`../README.md`](../README.md) **before touching the styling**:
it records where the marble may and may not go, why the legacy colour tokens must not be renamed, the
two cascade traps that bit this restyle, and the rule that toning the aurora down is done with alpha
and strip count, never by darkening. One external chart library: Chart.js 4.5.0.

**Sticky control bar:** the tab rail, a Looker-style date-range picker, funnel-stage chips, a search
box, and CSV export ("this tab" / "all data"). Three tabs:

1. **Overview** — the KPI row (Try free clicks · cost per Try free click · clicks · ad spend) over a
   delivery-quality row (impressions · CTR · CPM · click to Try free); delivery over time with axis
   and grain toggles; budget pacing and progress-to-goal; the cumulative on-track-to-goal chart
   (which shows IMPRESSIONS until the first Try free click is attributed, then switches itself); the
   response funnel; spend by audience tier; performance by funnel stage; creative formats; and an
   insight strip.
2. **Paid Media** — performance vs targets by ad group, the CPC vs CTR efficiency map, CPC over
   time, engagement over time, Try free clicks over time (hidden until the first one - a chart of zero
   bars under a CPA target line reads as a failed campaign), day-of-week, spend by ad group, spend
   vs delivery share, the per-creative table with a thin-volume guard, and the wear-out watch.
   The four period charts follow the window via `trendPeriod()`, and their captions are written
   from the same function so none can say "Weekly" over daily buckets.
3. **Creative** — the top 10 creatives by spend as branded tiles carrying the real numbers.
   **A creative serves across several ad groups** (all four, on this campaign), so the ad group
   beside it is the one that carried most of its delivery and is labelled `+N more`; the same
   resolution feeds the Paid Media tables, the CSV and the AI deck, so nothing on the page can
   name a different ad group for the same creative.

It fetches **one** payload from `/data.json` and renders everything client-side — see the JSON
contract in [`../README.md`](../README.md) (and `../gen_placeholder.py`, which is that contract
written down as a working example until the job exists).

Every dashboard also carries the **spend-multiplier shim** (`bbMultFor`/`bbApplySpendMult`), which
grosses RAW spend by `window.BB_SPEND_MULT` per channel so the client sees what they were billed.
Sophiie is Trade Desk-only, so the single `ttd` factor covers every row (`bbMultFor('ttd')` - NOT
`meta`, which is what the Meta template it was cloned from used). Any new spend field or aggregate
must be grossed too, and CSV exports must keep filtering out the `_`-prefixed stash keys — they leak
raw pre-markup spend otherwise.
