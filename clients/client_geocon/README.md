# client_geocon — Gateway Braddon + Northbourne Gateway (multi-channel paid media)

Self-hosted paid-media dashboard for **Geocon's residential launches**, one development at a time
via the top-nav selector. Two developments today:

| Development | Channels | Budget | Flight | State |
|---|---|---|---|---|
| **Gateway Braddon** | Meta only | A$7,500 | 2026-06-21 -> 07-20 | live, delivering |
| **Northbourne Gateway** (558 apartments) | Meta / LinkedIn / Trade Desk / Google Ads (+ SEO) | **A$205,600** | 2026-08-13 -> 10-31 | **plan seeded, NOT yet delivering** |

**Gateway Braddon is unchanged** by the 2026-08-24 multi-channel rebuild - verified as a strict
no-op, see "The multi-channel rebuild" below. No Snowflake / Salesforce / Content-Syndication lane
here.

## Multiple developments — the `property` selector (added 2026-08-12)

This dashboard covers a CLIENT (Geocon), not a single development. **Gateway Braddon** is live;
**Northbourne Gateway** is being set up and shows in the top-nav selector as *"- coming soon"*.

**Why this exists is a safety rail, not a feature.** `sql/01_stg_meta.sql` scopes on
`STARTS_WITH(campaign_name,'Geocon_')` so any new Geocon campaign flows in AUTOMATICALLY. Without a
property split, Northbourne's delivery would have merged straight into Gateway Braddon's KPIs the
day it started spending — inflating spend, leads and CPL on a live client dashboard, with no error
anywhere to catch it.

**How the split works.** One regex, duplicated in exactly two places that MUST stay identical:

| Where | Why |
|---|---|
| `sql/01_stg_meta.sql` → `property` | drives `fact` → `rows[]` → every KPI, chart, table, CSV |
| `sql/05_breakdowns.sql` → `property` | drives the audience / placement charts |

If they drift, the breakdown charts will disagree with the KPIs above them. Everything not matching
Northbourne falls to `'Gateway Braddon'` via the `ELSE`, so no existing number can move.

**The dashboard filters in ONE place** — `ROWS()` in `dash/dashboard.html` (plus `bdWithin` for the
breakdowns). Every rollup derives from those, so the whole page scopes together.

### Northbourne Gateway - the state of play (2026-08-24)

**The signed media plan is seeded and on screen.** `targets/media_plan.csv` -> `seed_media_plan` ->
`sql/06_media_plan.sql` -> the job's `properties[].plan` -> the dashboard's **Media Plan** tab.
Nine bought lines across five channels, A$205,600 committed, flight 2026-08-13 -> 10-31.

| # | Phase | Line | Channel | Budget | Imps | Clicks | Measurable |
|---|---|---|---|---|---|---|---|
| 1 | Awareness | High Impact (rich media) | Trade Desk | A$40,000 | 2,666,667 | 1,333 | yes |
| 2 | Awareness | YouTube Video | Google Ads | A$12,000 | 266,667 | 133 | yes |
| 3 | Awareness | SEO | - | A$9,600 | - | - | **no** |
| 4 | Demand Gen | LinkedIn | LinkedIn | A$6,000 | 75,000 | 68 | yes |
| 5 | Conversion | Canberra Investors (search) | Google Ads | A$16,500 | 14,000 | 350 | yes |
| 6 | Conversion | Search Management Fee | - | A$7,500 | - | - | **no** |
| 7 | Conversion | Retargeting | Trade Desk | A$12,000 | 800,000 | 720 | yes |
| 8 | Conversion | Lookalike | Trade Desk | A$12,000 | 800,000 | 720 | yes |
| 9 | Conversion | Leads | Meta | A$90,000 | 4,500,000 | 4,050 | yes |

Totals tie to the plan sheet exactly: **A$205,600, 9,122,334 imps, 7,374 clicks, 824,000 video
views**. The one figure NOT carried verbatim is the YouTube line's **reach estimate**: the sheet's
cell reads `11.11`, which is a broken formula (266,667 imps / a freq cap of 10 would be ~26,667),
so it is seeded NULL rather than shown to anyone as a target of eleven people.

**Measurable A$188,500 of A$205,600.** SEO is an organic-search retainer with no ad server and the
Google management fee is an agency fee. Pacing against the committed figure would report a
permanent 8.3% shortfall that no delivery could ever close, so the dashboard paces on the
measurable budget and shows the committed total beside it.

#### Go-live blockers - three, and none of them are code

| Blocker | Detail | Who |
|---|---|---|
| **No Geocon LinkedIn account in Windsor** | The connector carries APJC / STT / Cloudflare / Schneider / PropTrack / HireRight / ResetData and nothing else. `sql/07_stg_linkedin.sql` is written and returns zero rows. | needs the account granted + a Windsor connector |
| **No Geocon Trade Desk advertiser on the shared seat** | The seat carries VMCH / ResetData / WEHI / TLM / Altech / ACRS / City Perfume / Qtopia / Caltex / Peaches & Cream / BigAds. `sql/08_stg_ttd.sql` is written and returns zero rows. **This is the largest single block of the plan - A$64,000 across three lines.** | needs the advertiser granted to the Windsor seat |
| **Meta is frozen at 2026-08-10** | The Windsor Meta grant lapsed 2026-08-11, estate-wide. Northbourne's A$90,000 Meta line cannot report until it is re-authed. | needs a human re-auth |

**Google Ads is the one channel already wired end to end.** Geocon Group (customer `5457742070`)
is linked under the DTS MCC `3451896252`, and the three Northbourne campaigns already exist:

```
0201_Geocon_NGW558_ANZ_YouTube_AWR              VIDEO   PAUSED
0201_Geocon_NGW558_National_SearchBrand_CNV     SEARCH  PAUSED
0201_Geocon_NGW558_National_SearchNonBrand_CNV  SEARCH  PAUSED
```

They flow in the moment they are un-paused, with no change here. That naming is also **what the
property tokens were written against** - `NGW558` / `NGW` / `0201_` in `targets/property_map.csv`.
The original placeholder tokens (`Northbourne|North Bourne|NBG`) would have matched **none** of
them, so every Northbourne row would have fallen through to Gateway Braddon.

#### One measurement gap worth raising now

**Google Ads reports no video metric at all.** Neither `p_ads_CampaignBasicStats`,
`p_ads_CampaignStats` nor the (empty) `p_ads_VideoStats` carries views, view rate or quartiles, and
`raw_windsor.perf_google_ads` has no video columns either. So the YouTube line's **24,000-view
target and A$0.50 CPV cannot be measured** - the dashboard says so on the Media Plan tab rather
than reporting zero. Fixing it means extending the DTS export (or adding a video-capable feed)
before the line goes live; afterwards the history is not recoverable.

#### Day one of each channel - the one thing to check

Campaign names must match. Everything else is automatic.

```sql
SELECT DISTINCT channel, campaign_name, property, plan_line
FROM `bidbrain-analytics.client_geocon.fact_all` ORDER BY 1,2;
```

- `property = 'Unmapped'` -> the name missed the property tokens. **The export job already prints a
  WARNING naming the offenders**; widen `targets/property_map.csv`, re-seed, `FORCE_REBUILD=1`.
- `plan_line` NULL on a non-Meta row -> the name missed its media-plan token. Delivery is still
  counted, but it paces against nothing; widen that line's `match_pattern` in
  `targets/media_plan.csv`. The job prints a WARNING for this too.

Neither failure can silently corrupt a live development: an unmatched non-Meta row is excluded from
every KPI rather than absorbed into Gateway Braddon.

### Still to decide

Northbourne's **lead targets are PENDING with no value** - the signed plan commits impressions,
clicks and budget but no lead number, so `monthly_lead_target` / `qualified_lead_target` /
`cpl_target_aud` are seeded empty and render as `-` rather than as a target of zero. Get a lead
commitment from the client and seed it in `targets/targets.csv`.

## The multi-channel rebuild (2026-08-24) - and why Gateway Braddon did not move

Northbourne needed four channels where the dashboard had one. Rather than fork the page per
development, the Meta path was left **exactly** as it was and everything new was added beside it:

- `sql/02_fact.sql` is untouched and **deliberately kept**. `sql/10_fact_all.sql`'s Meta arm is
  `fact` verbatim with a `channel` label bolted on, so the identity is a one-view diff.
- The job still emits the **legacy top-level** `flight` / `benchmarks` / `targets` (the default
  development's), so a job deploy landing ahead of a dashboard deploy changes nothing on screen.
- Every new dashboard control hides itself at one channel / one development: the channel chips
  need >=2 delivering channels, the Media Plan tab needs a seeded plan.

**Verified, not assumed.** `fact` and `fact_all` reconcile exactly (273 rows, A$14,456.60,
1,053,133 imps, 166 leads), and the old dashboard on the live payload was rendered head-to-head
against the new dashboard on the new payload: **0 differences across all 15 rendered sections** -
both KPI strips, the stage / bench / ad / fatigue tables, the funnel, burn, goal, pacing bars,
insights, creative grid, chart set and stage chips.

### What a development with a plan and no delivery shows

The old rule was "a development is selectable once it has rows". That was right while "not
delivering" and "nothing to show" were the same thing; the signed plan makes them different. A
development now opens if it has **delivery or a plan**, and the two states look different:

- **Selector** reads `Northbourne Gateway - media plan` (vs `- coming soon` for one with neither).
- **Boots onto the Media Plan tab**, and the topbar reads **Planned**, not Live.
- **Every delivery figure reads `-`, never `0`.** A zeroed KPI strip beside "target 0.080%" states
  that a campaign delivered nothing; the truth is that it has not started. Same reason the per-line
  pace column reads **not started** rather than `-100%`, and the pacing card drops its
  "behind pace" pill when nothing has run.
- The delivery tabs stay reachable but **dimmed**, under a banner pointing at the plan.

### The three-stage contract, extended

A value on screen still traces `sql view column -> job/main.py key -> dashboard.html data.* key`.
The 2026-08-24 additions:

| sql | job | dashboard |
|---|---|---|
| `fact_all.channel` | `rows[].channel` | `chanOf()` / channel chips / `deliveredChans()` |
| `fact_all.plan_line` / `.plan_seq` | `rows[].plan_line` / `.plan_seq` | `planActual()` -> the plan-vs-delivered table |
| `media_plan.*` | `properties[].plan[]` | `planLines()` -> the whole Media Plan tab |
| `targets.property_key` | `properties[].targets` / `.benchmarks` | `propDef()` -> `bench()` / `targetItem()` |
| `budget.measurable_budget_aud` | `flight.budget_measurable` / `.budget_committed` | the plan pacing card |
| `stg_google_ads.conversions` | `rows[].conversions` | carried and labelled, **never** summed into leads |

## Architecture — one fact table, rolled up in the browser (rebuilt 2026-06)

This client uses the **MongoDB pattern**: the export ships ONE compact per-(date × campaign × adset ×
ad) **fact table** (`rows[]`, ~200 rows) and the dashboard rolls EVERYTHING up **client-side** — KPIs,
by-campaign / by-stage / by-creative, the daily trend, the vs-benchmark Δ table, the segment
breakdown — filtered by the chosen **date range**. That is what makes the date-range filter and the
CSV "export all data" exact and free. The old per-rollup views (overview / by_campaign / by_ad /
daily / by_stage / fatigue) were removed — the browser computes them now.

```
 raw_windsor.perf_meta        sql: 01_stg_meta -> 02_fact      job/main.py           dash/dashboard.html
 (Windsor Meta connector,  →  client slice + funnel_stage,  →  reads fact+targets,→  fetches /data.json, rolls
  self-refreshing; shared)     one row per date x ad (fact);    writes fact + flight    up rows[] per the date
                               + 03_targets / 04_budget         + benchmarks            filter; draws everything
        │                             │                              │                          │
   (no stage-1 loader)         geocon-export JOB (stage 2)                          geocon-dash SERVICE (3)
```

The contract: `fact column → job rows[].key → dashboard rollups (agg / byStage / byCampaign / byAd /
dailyOf / fatigueOf)`. The JSON carries `meta`, `flight` (pacing context), `benchmarks` (numeric
targets), `targets` (raw + status), and `rows[]` (the fact). Ratios (CTR/CPM/CPC/CPL) are NEVER stored
— always recomputed from summed components client-side, so any date sub-range is exact. Reach is
summed across days (Meta reach is a deduped audience, not truly additive — kept summed for continuity;
frequency = impressions ÷ summed-reach).

| I want to change… | Edit |
|---|---|
| Campaign filter / funnel-stage mapping | `sql/01_stg_meta.sql` |
| The fact grain / fields shipped to the browser | `sql/02_fact.sql` + `job/main.py` `rows[]` |
| Lead / CPL / CTR / CPM / CPC / budget **targets + benchmarks** | `targets/targets.csv` · `targets/budget.csv` → `seed_static.py` → export `FORCE_REBUILD=1` |
| Flight / pacing math | `job/main.py` (`flight = {...}`, from the budget seed + today) |
| Charts, views, Δ table, segment breakdown, CSV export, the AI report deck | `dash/dashboard.html` |
| Login / how the JSON + `/report` are served | `dash/main.py` (rarely needed) |
| The **login page** look (Geocon corporate skin) | `dash/main.py` `LOGIN_HTML` + `dash/geocon-mark.png` |

## The dashboard (`dash/dashboard.html`)

**Rebuilt 2026-07 into the Bidbrain dark house style, branded to Gateway Braddon** (deep forest-green
canvas + a terracotta accent and the shared soft glow; modelled on `client_resetdata`). One file,
**two topic tabs**: **Overview · Paid Media** (the standalone "Creative" tab was merged into Paid Media
on 2026-07-16 — see the Top-creatives note below). Everything honours the shared **Looker
date-range picker**, **stage chips**, and search; time-series charts carry **VIEW BY Month/Week/Day +
AXIS Relative/Absolute** toggles (default Relative + Month).

- **North-star = qualified leads (MODELLED).** Meta reports RAW enquiries only, so qualified leads =
  `enquiries × qualification_rate_target` (0.20, PENDING) — shown with a "modelled · no CRM feed" badge
  and an explainer note, **never as a measured actual**. Wire a CRM feed to report true qualified leads.
  Green is reserved for that goal metric (house rule: green = goal/good only); enquiries=gold,
  spend=sage, cost=terracotta, CTR=amber.
- **Overview** — clickable KPI dot-cards (**Qualified · Enquiries · Spend** toggle their series on the
  hero), the delivery hero (spend bars + enquiries + modelled-qualified lines), budget pacing,
  spend-by-stage donut, the enquiry funnel, money-flow, and insight cards.
- **Paid Media** — **opens with the Top-5 creatives** (see the note below), then a **Performance vs
  Targets Δ table** (CPL/CTR/CPM/CPC per campaign), spend-by-ad-set,
  budget burn, the per-ad table (thin-volume guard: ⚠ under 15k impressions or <8 leads), and a
  **fatigue watch** (weekly WoW frequency/CTR, ≥1,000-impression guard).
- **Top creatives (at the top of Paid Media, 2026-07-16; was a standalone "Creative" tab + top 10)** —
  the **top 5 creatives by spend** (`renderCreative` → `#creativeGrid`, `slice(0,5)`; `render()` populates
  it regardless of active tab): real ad headline + body copy + metrics, with the
  real Meta ad image, a lightbox showing the full copy + a landing-page link. **Meta signs
  `thumbnail_url` with only a ~4-day validity**, so we cache the image bytes to our own bucket and serve
  them durably: the export job (`job/main.py` → `cache_creative_images`) downloads each top creative's
  thumbnail — using the **freshest** (latest-date) signed URL per creative — to
  `gs://bidbrain-analytics-geocon-dash/creatives/<creative_id>` (skips ones already cached), and the dash
  serves them at **`/creative-img/<creative_id>`** (same auth as `/data.json`). The gallery `<img>` falls
  back **cache → live CDN URL → branded tile** (`ccImgErr` in `dashboard.html`). Because the URL is only
  fetchable for a few days, the *export must run while it's live* — the freshness gate fires the export
  within ~10 min of the Windsor loader re-pulling `perf_meta` (which re-signs the URL), so active
  creatives get a permanent copy on that next run. A creative that's paused before it was ever cached
  can't be recovered (its URL is dead); a one-off backfill (pull fresh URLs from Windsor →
  `gcloud storage cp` into `creatives/`) can seed those.

Login password lives in Secret Manager `geocon-dash-password` (mounted `DASH_PASSWORD`); agency = **100% Digital**.

**The login page is GEOCON CORPORATE, not Gateway Braddon (re-skinned 2026-08-18 from the client's
own website).** Warm light-grey canvas `#EDEDEB`, near-black heavy condensed uppercase display type
(**Anton** via Google Fonts), a hairline outlined rounded CTA with the site's diagonal arrow, and the
site's dotted divider rule. **One CENTRED cell since 2026-08-19** (estate uniformity - every other
dashboard login is a single centred card), over a four-layer pure-CSS "drafting sheet" background:
masked hairline grid, faint oversized plan geometry, two dotted horizons and a breathing vignette
(disabled under `prefers-reduced-motion`). The **dashboard behind it deliberately stays dark Gateway Braddon** - two
brands, two jobs; do not unify them without asking. The corporate wordmark is served from
`dash/geocon-mark.png` at the public route `/geocon-mark.png` (public because the login page renders
it before anyone is authenticated), and it is a **cropped** copy of `creatives/geoconlogo.png` that
must live in `dash/`: `creatives/` is not in that folder's Docker build context, and the Dockerfile's
COPY list is explicit, so a new asset must be added there too. The artwork is white type on an opaque
black square, so the CSS pairs `filter:invert(1)` with `mix-blend-mode:multiply` to set it as black
type straight onto the grey - **both properties are required**. Full detail: `dash/README.md`.

Two MongoDB/STT-grade capabilities every dashboard carries:
- **Performance-over-time chart** with **View by Month/Week/Day** grain + **Relative/Absolute axis**
  toggles (default Relative — lines indexed to peak=100; tooltips always show true values).
- **AI "Download report"** → a board-ready **3-slide deck** (What happened · Why · Recommended
  actions) previewed on-screen + a **Download Google Slides** `.pptx` export (PptxGenJS). KPI figures
  come VERBATIM from the live numbers; the model writes only the narrative. See below.

**CSV exports:** *Export tab* (the current view's table, honouring the date/stage/search filters) and
*Export all* (the full per-day, per-ad fact table).

## AI report (`dash/report.py` + `/report` in `dash/main.py`)

Two-stage Claude Opus 4.8 call (Stage A web-grounded analyst notes, Stage B strict-schema slide JSON),
re-templated for **Meta paid-social lead-gen**: single engine, funnel-stage framing, honest
"Meta-reported enquiries" labelling, the `area` taxonomy (`reach/traffic/leads/efficiency/budget` ·
`creative/audience/budget_pacing/landing_page/funnel`), no-PII / anti-injection guardrails. Falls back
to **Gemini** (`gemini-2.5-pro`) if Claude rate-limits / runs out of credit. The browser POSTs the
**whole-account** numbers (independent of the date filter), so the deck is stable and **cached per data
refresh** (`gs://…-geocon-dash/reports/…`, keyed by `client + data_through`).

- **One-time standup:** `dash/enable_report_geocon.ps1` (provisions IAM, mounts the `anthropic-api-key`
  + optional `gemini-api-key` secrets, sets the 900s timeout). After standup, normal redeploys keep it.

## Deploy (PowerShell; project `bidbrain-analytics`, region `australia-southeast1`)

Build the image, deploy as yourself — **do not** `gcloud builds submit --config cloudbuild.yaml` from a
laptop (its deploy step fails `iam.serviceaccounts.actAs`).

```powershell
# edited dash/dashboard.html, dash/main.py, or dash/report.py → rebuild + swap the SERVICE:
.\clients\client_geocon\dash\deploy_dash_geocon.ps1

# edited a sql/*.sql view → reapply views + re-run the JOB (FORCE_REBUILD bypasses the freshness gate):
.\.venv\Scripts\python.exe clients\client_geocon\create_views.py
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# edited job/main.py (the fact / JSON shape) → rebuild + swap + run the JOB:
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/geocon-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients\client_geocon\job --tag $IMG --region australia-southeast1
gcloud run jobs update  geocon-export --image $IMG --region australia-southeast1
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

## Meta breakdowns — audience (age×gender) + placement (`ingest/meta_breakdown_pull.py`)

The **Audience** and **Placement** charts read `client_geocon.breakdowns` (view over the ISOLATED table
`raw_windsor.geocon_meta_breakdown`). This is a **separate, geocon-only** pull — it does **NOT** touch the
shared `raw_windsor.perf_meta` loader/table (Windsor breakdowns multiply the row grain: age×gender×placement).
Region was pulled but is ~100% ACT (single market) so it isn't charted. It's a **manual refresh** (not
scheduled) — re-run when you want fresh audience/placement data:

```powershell
# scratchpad path for the NDJSON is arbitrary
$env:WINDSOR_API_KEY = (gcloud secrets versions access latest --secret=windsor-api-key)
.\.venv\Scripts\python.exe clients\client_geocon\ingest\meta_breakdown_pull.py 2026-05-01 <today> out.ndjson
bq load --replace --source_format=NEWLINE_DELIMITED_JSON raw_windsor.geocon_meta_breakdown out.ndjson `
  date:DATE,campaign:STRING,breakdown:STRING,seg1:STRING,seg2:STRING,impressions:INTEGER,reach:INTEGER,clicks:INTEGER,link_clicks:INTEGER,spend:FLOAT,leads:INTEGER
# then re-run the export job so geocon.json picks it up (FORCE_REBUILD as above)
```
The `geocon-export` job tolerates the table's absence (`breakdowns` → `[]`), so the dashboard never breaks
if the pull hasn't run. **Real qualified leads** still need a client CRM feed (the north-star is modelled ×20%).


The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy is live immediately;
it always reads whatever `geocon.json` is currently in the bucket.

## Freshness

`geocon-export` is **self-gating** on a Cloud Scheduler `*/10` UTC tick (`scheduler.ps1`): each tick
cheaply probes whether `raw_windsor.perf_meta` advanced (`__TABLES__.last_modified` vs the
`_freshness.json` watermark) and rebuilds only when it did. Static re-seeds (targets/budget) don't move
the gate, so force them with `FORCE_REBUILD=1`. (Pacing is time-relative — `pace_expected` / projection
are computed from the wall clock at build time, so a no-data day leaves them a day stale until the next
rebuild; this is inherent to the gate and matches the other clients.)

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.perf_meta` (shared Windsor connector — no stage-1 loader here) |
| Views | `client_geocon.{stg_meta, fact, targets, budget}` (+ `seed_targets` / `seed_budget` tables) |
| Job / Service | `geocon-export` / `geocon-dash` |
| Data bucket / file | `bidbrain-analytics-geocon-dash` / `geocon.json` (report cache in `reports/`) |
| Dash runtime SA | `geocon-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | `anthropic-api-key` (required) · `gemini-api-key` (optional fallback) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
