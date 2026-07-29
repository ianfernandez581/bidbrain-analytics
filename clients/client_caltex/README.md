# client_caltex — Caltex (100% Digital) — The Trade Desk display, QLD+WA

> **Status (2026-07-29): REBUILT for The Trade Desk, awaiting data verification.** Originally
> scaffolded (2026-07-04) from `client_geocon` as a Meta placeholder; the real brief arrived as a
> **Trade Desk campaign** (advertiser **`0lw3hp6`**, desk.thetradedesk.com URL), so the whole
> pipeline was repointed: `raw_windsor.perf_the_trade_desk` → `stg_ttd`/`fact` →
> `caltex-export` → `caltex-dash`. The dashboard serves a baked-in TTD-shaped SAMPLE payload
> (`dash/placeholder.json`, `meta.placeholder=true`) behind a loud banner until the export job
> writes the real `caltex.json`. **Go-live steps + the data-verification runbook:
> [`dash/LIVE_URL.md`](dash/LIVE_URL.md).**

Self-hosted paid-media dashboard. **Single channel** (The Trade Desk programmatic display),
**mixed awareness + consideration** brand campaign for Caltex fuel retail across **QLD+WA**,
bought via three tactics = the three TTD ad groups:

| Ad group | Tactic | Funnel stage (assumption — revisit with the media plan) |
|---|---|---|
| `Display Standard \| QLD+WA` | Display Standard | **Awareness** (broad, cheap reach — judged on CPM + volume) |
| `AI Contextual \| QLD+WA` | AI Contextual | **Consideration** (contextually-relevant moments — judged on CTR/CPC/actions) |
| `Attention-Optimised \| QLD+WA` | Attention-Optimised | **Consideration** (paying for engaged attention — judged on engagement quality, not raw CPM) |

The tactic + market are **parsed from the ad group name** (`"Tactic | Market"`) in
`sql/01_stg_ttd.sql`; a new ad group flows in automatically (unmatched tactics default to
Awareness). The stage mapping is a one-line CASE — change it there if the client disagrees.

## Architecture — one fact table, rolled up in the browser

The MongoDB/geocon pattern: the export ships ONE compact per-(date × campaign × ad group ×
creative) **fact table** (`rows[]`) and the dashboard rolls EVERYTHING up **client-side** — KPIs,
by-stage / by-tactic / by-creative, the daily trend, the vs-target Δ table — filtered by the
chosen **date range** + **stage chips**. Ratios (CTR/CPM/CPC/cost-per-action/video completion)
are never stored, always recomputed from summed components, so any sub-range is exact.

```
 raw_windsor.perf_the_trade_desk   sql: 01_stg_ttd -> 02_fact      job/main.py            dash/dashboard.html
 (Windsor TTD connector, shared →  advertiser 0lw3hp6 slice,   →   reads fact+targets, →  fetches /data.json, rolls
  windsor-tradedesk-ingest job)    tactic/market/stage parse,      writes fact + flight    up rows[] per the date/stage
        │                          conversion-slot sums            + benchmarks            filter; draws everything
   (stage-1 loader is shared)      + 03_targets / 04_budget            │                          │
                                        │                    caltex-export JOB (2)      caltex-dash SERVICE (3)
```

| I want to change… | Edit |
|---|---|
| Advertiser filter / tactic parse / stage mapping / conversion slots | `sql/01_stg_ttd.sql` |
| The fact grain / fields shipped to the browser | `sql/02_fact.sql` + `job/main.py` `rows[]` |
| CPM / CTR / CPC / impression / budget **targets** (all `PENDING` until the media plan lands) | `targets/targets.csv` · `targets/budget.csv` → `seed_static.py` → export `FORCE_REBUILD=1` |
| Flight / pacing math | `job/main.py` (`flight = {...}`) |
| Charts, tabs, glow, CSV export, the AI deck payload | `dash/dashboard.html` |
| AI-report framing | `dash/report.py` (retemplated for TTD awareness+consideration) |

## Honesty rules baked in

- **Site actions = TTD pixel-attributed** (post-view + post-click), summed from Windsor's
  anonymous conversion slots. `conversion_touch_*` (total pixel fires, mostly not ad-attributed)
  is never used. Post-view dominating is *normal* for display and the UI says so.
- **Conversion-slot caveat:** once Caltex pixels actually fire, verify the slot layout — TTD can
  export one tracker as a duplicate column pair (VMCH's did; see `sql/01_stg_ttd.sql` header).
- **No reach/frequency** exists in the Windsor TTD feed → creative wear-out is read from weekly
  **CTR decay** (≥5k impressions/week), not frequency.
- **Targets marked `PENDING`** (all of them today, incl. the flight window 2026-07-14→09-30 and
  the A$30k budget — placeholders) render with a "pending" marker so nobody mistakes an
  assumption for an agreed KPI. Update `targets/*.csv` when the signed media plan arrives.

## The dashboard (`dash/dashboard.html`)

Caltex red (`#E4002B`) on the dark petrol-teal Bidbrain canvas, with the **2026-07 glow package**
(animated north-star KPI bloom, halos on active controls, lit pacing bar, card hover bloom;
disabled under `prefers-reduced-motion`). Three tabs — **Overview · Delivery · Creative** — all
honouring the shared Looker date-range picker, Awareness/Consideration stage chips and search;
time-series charts carry **VIEW BY Month/Week/Day + AXIS Relative/Absolute** (default Relative +
Week). Ships the house helpers: `bbApplySpendMult` (channel **`ttd`**), `bb-sortable` tables,
`bbDonutCenter`. Full tab-by-tab detail in [`dash/README.md`](dash/README.md).

Login password lives in Secret Manager `caltex-dash-password`; agency = **100% Digital**.

## Deploy (PowerShell; project `bidbrain-analytics`, region `australia-southeast1`)

```powershell
# edited dash/* → rebuild + swap the SERVICE:
.\clients\client_caltex\dash\deploy_dash_caltex.ps1

# edited a sql/*.sql view → reapply views + re-run the JOB (FORCE_REBUILD bypasses the gate):
.\.venv\Scripts\python.exe clients\client_caltex\create_views.py
gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# edited job/main.py → rebuild + swap + run the JOB:
.\clients\client_caltex\job\deploy_job_caltex.ps1

# first-time standup (APIs/SAs/IAM/secrets/service, then -WithData for views+job+scheduler):
.\clients\client_caltex\deploy_caltex.ps1            # placeholder service
.\clients\client_caltex\deploy_caltex.ps1 -WithData  # once TTD data is verified in raw_windsor
```

## Freshness

`caltex-export` is **self-gating** on a `*/10` UTC tick (`scheduler.ps1`): probes
`raw_windsor.perf_the_trade_desk` (`__TABLES__.last_modified` vs the `_freshness.json`
watermark) and rebuilds only when it advanced. Seed changes (targets/budget) and view-only edits
need `FORCE_REBUILD=1`.

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.perf_the_trade_desk` (shared Windsor TTD connector; TTD advertiser **`0lw3hp6`**) |
| Views | `client_caltex.{stg_ttd, fact, targets, budget}` (+ `seed_targets` / `seed_budget` tables) |
| Job / Service | `caltex-export` / `caltex-dash` |
| Data bucket / file | `bidbrain-analytics-caltex-dash` / `caltex.json` (report cache in `reports/`) |
| Dash runtime SA | `caltex-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | Vertex Gemini via ADC (default) · `anthropic-api-key` (optional Claude) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/LIVE_URL.md`](dash/LIVE_URL.md) — **status + the go-live / data-verification runbook.**
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
