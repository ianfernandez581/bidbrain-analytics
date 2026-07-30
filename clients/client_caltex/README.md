# client_caltex — Caltex Star Card (100% Digital) — The Trade Desk display, QLD+WA

> **Status (2026-07-30): LIVE on real data.** Campaign **"Caltex Star Card | QLD+WA | Jul-Oct 2026"**
> (`campaign_id` `85k1vmm`, TTD advertiser **`0lw3hp6`**), AUD, all three ad groups delivering.
> The tile is **active** on the 100% Digital portal (`bidbrain-platform/dash/set_caltex_tile.py`),
> the export self-gates `*/10`, and the dashboard is in `status_dashboard` BQ_CLIENTS (5 accuracy
> checks) and `SLIDES_CLIENTS` (AI deck enabled: Vertex IAM + 900s timeout via
> `dash/enable_report_caltex.ps1`).
>
> **First delivery was 2026-07-28.** The shared TTD loader walks back from *yesterday*, so its
> 07-28 21:35 UTC run stopped at 07-27 and the raw table briefly looked empty — that was NOT a
> Windsor grant problem (the advertiser is granted; verified against the API). It self-heals nightly;
> force a range with `tradedesk_loader.py <from> <to>` (TTD refuses same-day dates).
> `job/main.py` also REFUSES to upload an empty fact, so a premature run can never blank the
> dashboard. Runbook: [`dash/LIVE_URL.md`](dash/LIVE_URL.md).

## What the conversion pixel can and cannot measure (read before promising numbers)

The only tag installed is a **sitewide TTD Universal Pixel** (`z3eu6oa` on advertiser `0lw3hp6`):

```html
ttdConversionEvents("init",  { advertiserId: "0lw3hp6", pixelIds: ["z3eu6oa"] });
ttdConversionEvents("event", { advertiserId: "0lw3hp6", pixelIds: ["z3eu6oa"] });
```

That `event` call carries **no** `value`, `orderid`, or `td1`-`td10` custom data and **no distinct
event name**, so it fires identically on every page. Consequences:

- What we CAN report: **ad-attributed site visits** — post-view (saw an ad, later landed) and
  post-click. The whole UI and the AI report say "site visits" for exactly this reason.
- What we CANNOT report: **Star Card applications / sign-ups.** The application-container tag is
  not installed. The client has agreed to attribute post-launch applications to the campaign in
  their own reporting, but that is a commercial agreement, **not** a measurement we hold — never
  surface an application count, rate or cost from this dashboard.
- When the application tag IS installed it will appear as a **new numbered slot** in Windsor's
  anonymous conversion slots; split it out in `sql/01_stg_ttd.sql` (and mirror the split in the
  status-dash check) to report applications as their own metric.
- `conversion_touch_*` stays unused: it counts ALL pixel fires, which this base pixel makes large
  and emphatically not ad-attributed.
- Slots are summed across all 12 per kind. **When they first fire, verify the layout** — TTD can
  export one tracker as a duplicate column pair (the VMCH `{01,03,05}` case); if so, switch both
  `sql/01_stg_ttd.sql` and the status-dash check to one column per pair.

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
