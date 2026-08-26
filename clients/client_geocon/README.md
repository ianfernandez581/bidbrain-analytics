# client_geocon — Gateway Braddon + Northbourne Gateway (multi-channel paid media)

Self-hosted paid-media dashboard for **Geocon's residential launches**, one development at a time
via the top-nav selector. Two developments today:

| Development | Channels | Budget | Flight | State |
|---|---|---|---|---|
| **Gateway Braddon** | Meta only | A$7,500 | 2026-06-21 -> 07-20 | live, delivering |
| **Northbourne Gateway** (558 apartments) | Meta / LinkedIn / Trade Desk / Google Ads (+ SEO) | **A$205,600** | 2026-08-13 -> 10-31 | **COMING SOON** - held by `status` in the seed, not by lack of data |

**Gateway Braddon is unchanged** by the 2026-08-24 multi-channel rebuild - verified as a strict
no-op, see "The multi-channel rebuild" below. No Snowflake / Salesforce / Content-Syndication lane
here.

## Multiple developments — the `property` selector (added 2026-08-12)

This dashboard covers a CLIENT (Geocon), not a single development. **Gateway Braddon** is
delivering; **Northbourne Gateway** shows in the top-nav selector as *"- coming soon"* and renders a
placeholder until it is deliberately switched live (see "the state of play" below).

**Why this exists is a safety rail, not a feature.** `sql/01_stg_meta.sql` scopes on
`STARTS_WITH(campaign_name,'Geocon_')` so any new Geocon campaign flows in AUTOMATICALLY. Without a
property split, Northbourne's delivery would have merged straight into Gateway Braddon's KPIs the
day it started spending — inflating spend, leads and CPL on a live client dashboard, with no error
anywhere to catch it.

**How the split works.** ONE seed table, `seed_property_map` (from `targets/property_map.csv`),
read by every staging view - so adding or widening a development is a CSV edit, never a SQL edit,
and the views cannot drift apart:

| Where | Why | Unmatched row falls to |
|---|---|---|
| `sql/01_stg_meta.sql` | drives `fact` -> `rows[]` -> every Meta KPI, chart, table, CSV | `'Gateway Braddon'` (safe - the account + `Geocon_` scope is exact) |
| `sql/05_breakdowns.sql` | drives the audience / placement charts | `'Gateway Braddon'`, same seed as `01`, so the charts can never disagree with the KPIs above them |
| `sql/07_stg_linkedin.sql` | LinkedIn delivery | **`'Unmapped'`** - the job ALARMS |
| `sql/08_stg_ttd.sql` | Trade Desk delivery | **`'Unmapped'`** - the job ALARMS |
| `sql/09_stg_google_ads.sql` | Google Ads delivery | **`'Unmapped'`** - the job ALARMS |

**Only Meta may fall back to a development.** Its scope is an exact ad account plus a campaign
prefix, so a catch-all is safe. The other three read tables shared with six-to-eleven other
clients, so they must match a development by NAME or be reported as Unmapped and excluded - a
Geocon campaign nobody told us about becomes a loud warning, not an invisible A$40k on a live
client's spend.

**The dashboard filters in ONE place** — `ROWS()` in `dash/dashboard.html` (plus `bdWithin` for the
breakdowns). Every rollup derives from those, so the whole page scopes together.

### Northbourne Gateway - the state of play (2026-08-24)

**It is deliberately COMING SOON, and it stays that way until someone says otherwise.** The
development is 558 apartments on a A$205,600 plan, flight 2026-08-13 -> 10-31, buying Meta,
LinkedIn, Trade Desk and Google Ads (plus an SEO retainer, which has no ad server and is therefore
never a dashboard platform). Trade Desk and Google can be in market and spending while the campaign
as a whole is still waiting on creative and client approval for the rest - and publishing a
one-platform view of a four-platform launch would misrepresent it. So the dashboard shows a
**coming-soon placeholder** and reports no performance at all.

**Going live is a one-word CSV edit.** `status` in `targets/property_map.csv`:

| `status` | What the dashboard does |
|---|---|
| `coming_soon` | The placeholder owns the page - tabs, filters and footer hidden - **however much delivery has landed** |
| `live` | The real dashboard |

```powershell
# flip Northbourne live when every platform is approved and in market
#   targets/property_map.csv:  ...,coming_soon   ->   ...,live
.\.venv\Scripts\python.exe clients\client_geocon\seed_static.py
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

No code change, no deploy. **This is deliberately NOT automatic** - it used to be (a development
switched itself on the moment its first row landed), and that is exactly the behaviour that would
have published Northbourne off the back of its Trade Desk line alone.

### The platform toggle - the resetdata pattern

The point of the rebuild. A **PLATFORM** chip row sits in the control bar beside the date range, and
ticking a platform off re-renders **the whole page** without it - KPIs, the delivery trend, the
stage donut, the funnel, the campaign and ad tables, the creative gallery, the CSV export and the
AI deck payload. It works because every rollup derives from `ROWS()`, which applies `chanOk`, so
there is exactly one place the filter is enforced and nothing can be accidentally left unfiltered.

Copied from `client_resetdata`'s PLATFORM chips, with the same rules - all on by default, the last
chip cannot be unticked (an empty selection is an empty dashboard, which is never what the click
meant) - and one difference this client forces: resetdata's roster is a fixed four, whereas a
Geocon development runs whatever its plan bought, so **the roster is built from delivery**. A
platform appears as a chip only once it has actually spent or served inside the current date range.
A planned-but-dark platform is not a chip, because a permanent zero row reads as a platform that
failed rather than one that has not started.

**It hides itself at one platform**, which is why Gateway Braddon's control bar is untouched. Same
for the **Performance by platform** table on Paid Media (the side-by-side the toggle needs to be
worth using) - a one-row comparison table is not a comparison.

Verified against a synthetic four-platform payload: with all four on, A$15,873 / 176 enquiries /
344 rows in scope; ticking each platform off moved spend, enquiries, the donut total, the campaign
table, the ad table and the row scope by exactly that platform's contribution, and the last chip
refused to untick. That test also caught a real defect - see below.

#### `Number(null)` is `0`, so an absent target was rendering as a target of zero

Northbourne's plan commits impressions, clicks and budget but **no lead number**, so
`monthly_lead_target` / `qualified_lead_target` / `cpl_target_aud` are seeded PENDING with an empty
value. `bench()` coerced those with `Number(...)`, and in JavaScript both `Number(null)` and
`Number('')` are `0` - not `NaN` - so `Number.isFinite` accepted them and the page printed
**"pending target 0"**, **"target A$0"** and **"0% of goal"**. Both accessors now reject
null/undefined/empty *before* coercing (`numOrNull`), so an unset target reads "no target set".
Worth remembering repo-wide: `Number.isFinite(Number(x))` is not a null guard.

#### Go-live blockers - ONE grant left as of 2026-08-27 (was three)

| Channel | State (verified 2026-08-27) |
|---|---|
| **Trade Desk** | **RESOLVED and LIVE.** Advertiser `Geocon Group` is granted on the shared Windsor seat. The **High Impact** line (plan seq 1) has delivered since **2026-08-20**: 55 rows, **A$3,298.67 / 638,709 imps / 525 clicks**, resolving to `property = Northbourne Gateway` and `plan_line = High Impact` with zero Unmapped. **Retargeting (seq 7) and Lookalike (seq 8), A$12,000 each, have not started.** |
| **Meta** | **Feed RESOLVED, campaigns not built.** The Windsor Meta grant was re-authed 2026-08-25 and Gateway Braddon is current to 08-25, so the pipe is healthy - but the ad account holds **no Northbourne campaign at all** yet. The A$90,000 `Leads` line (seq 9) is waiting on campaign build, not on a grant. Its plan row has a NULL `match_pattern` **by design** - it is the Meta channel catch-all, and Meta has exactly one line. |
| **Google Ads** | **Wired, PAUSED.** All three campaigns exist and are correctly named; they flow the moment they are un-paused. Nothing is needed from us. |
| **LinkedIn** | **STILL BLOCKED - the only outstanding grant.** The connector carries APJC / STT / Cloudflare / Schneider / PropTrack / HireRight / ResetData and nothing else; there is no Geocon account on it. `sql/07_stg_linkedin.sql` is written and returns zero rows. A$6,000 (seq 4). |

**Do not re-read the old "A$64,000 Trade Desk blocker" line anywhere - it is dead.** That grant landed
with the estate-wide Trade Desk re-auth on 2026-08-25, which also issued a NEW seat id (484 -> 569).

#### The Meta scope did NOT survive Northbourne's brief prefix (FIXED 2026-08-27)

`01_stg_meta` scoped the client slice with `STARTS_WITH(campaign_name, 'Geocon_')`. Northbourne names
every campaign **`0201_Geocon_NGW558_*`** - confirmed on its live Trade Desk line and all three Google
Ads campaigns - so that test returns FALSE and **100% of its Meta delivery would have been dropped**.
It is the worst kind of silent: the rows never reach the property map, so the export job's `Unmapped`
WARNING cannot fire for them either, and the A$90,000 line - the plan's largest - would simply have
read zero on a dashboard that looked healthy.

Both gates now strip a leading brief number before the prefix test, and they **must stay in step**:

| File | Fix |
|---|---|
| `sql/01_stg_meta.sql` | `STARTS_WITH(REGEXP_REPLACE(TRIM(campaign_name), r'^[0-9]+_', ''), 'Geocon_')` |
| `ingest/meta_breakdown_pull.py` | `_GEOCON_CAMPAIGN = re.compile(r"^\s*(?:[0-9]+_)?Geocon_")` - the audience / placement table has its own copy of this filter, and left alone it would have rendered those charts EMPTY underneath populated KPIs |

Still exact enough to split geocon from bellshakespeare / nextsmile on the shared ad account, so the
catch-all `ELSE` in the property map stays safe. **Verified a strict no-op** on today's data: 285 rows
under both predicates, 0 newly admitted campaigns. This is the repo-wide rule in `md/AGENTS.md` -
campaign names are NOT stable keys, and `STARTS_WITH` is the shape that breaks outright on a prefix.

#### The bare `RT` plan token was a live mis-tagging trap (narrowed 2026-08-27)

Plan line 7 (Retargeting) matched on `Retargeting|RTG|RT`, and plan-line attribution is **first-match-wins
by `seq`** over a plain `STRPOS` substring test. `RT` is two characters: **"Property" contains "rt"**, and
this is a property developer. Any Lookalike campaign (seq 8) whose name happened to contain those letters
would have been tagged **Retargeting** and booked against the wrong A$12,000 line. Narrowed to
`Retargeting|RTG|_RT_`, delimiter-anchored to Geocon's underscore convention. No current name matched it
either way, so this too is a no-op today and pure forward protection - but both those lines are unstarted,
which is exactly when it would have bitten.

**Google Ads is the one channel already wired end to end.** Geocon Group (customer `5457742070`) is
linked under the DTS MCC `3451896252`, and the three campaigns already exist:

```
0201_Geocon_NGW558_ANZ_YouTube_AWR              VIDEO   PAUSED
0201_Geocon_NGW558_National_SearchBrand_CNV     SEARCH  PAUSED
0201_Geocon_NGW558_National_SearchNonBrand_CNV  SEARCH  PAUSED
```

They flow the moment they are un-paused. That naming is also **what the property tokens were written
against** - `NGW558` / `NGW` / `0201_` in `targets/property_map.csv`. The original placeholder
tokens (`Northbourne|North Bourne|NBG`) matched **none** of them, so every Northbourne row would
have fallen through to Gateway Braddon.

#### One measurement gap worth raising now

**Google Ads reports no video metric at all.** Neither `p_ads_CampaignBasicStats`,
`p_ads_CampaignStats` nor the (empty) `p_ads_VideoStats` carries views, view rate or quartiles, and
`raw_windsor.perf_google_ads` has no video columns either. The YouTube line's 24,000-view target and
A$0.50 CPV therefore **cannot be measured**. Fixing it means extending the DTS export before that
line goes live - afterwards the history is not recoverable.

#### Day one of each platform - the one thing to check

Campaign names must match. Everything else is automatic.

```sql
SELECT DISTINCT channel, campaign_name, property, plan_line
FROM `bidbrain-analytics.client_geocon.fact_all` ORDER BY 1,2;
```

`property = 'Unmapped'` means the name missed the property tokens - **the export job already prints
a WARNING naming the offenders**. Widen `targets/property_map.csv`, re-seed, `FORCE_REBUILD=1`. An
unmatched non-Meta row is excluded from every KPI rather than absorbed into a live development, so
this can never silently corrupt Gateway Braddon.

### There is no Media Plan tab

One was built on 2026-08-24 and **removed the same day on request** - the ask was a platform toggle,
not a plan view. The plan itself is still seeded (`targets/media_plan.csv` -> `seed_media_plan` ->
`sql/06_media_plan` -> `properties[].plan`) and still flows into the payload, because it is where
the per-platform impression / click / CPM / CTR targets live and that is what the platform lanes get
measured against once they go live. **Nothing renders it today** except `plan_channels`, which the
coming-soon placeholder uses to list the platforms the campaign bought.

## The multi-channel rebuild (2026-08-24) - and why Gateway Braddon did not move

Northbourne needed four platforms where the dashboard had one. Rather than fork the page per
development, the Meta path was left **exactly** as it was and everything new was added beside it:

- `sql/02_fact.sql` is untouched and **deliberately kept**. `sql/10_fact_all.sql`'s Meta arm is
  `fact` verbatim with a `channel` label bolted on, so the identity is a one-view diff.
- The job still emits the **legacy top-level** `flight` / `benchmarks` / `targets` (the default
  development's), so a job deploy landing ahead of a dashboard deploy changes nothing on screen.
- Every new control hides itself at one platform / one development: the platform chips and the
  platform table need >=2 delivering platforms.

**Verified, not assumed.** `fact` and `fact_all` reconcile exactly (273 rows / A$14,456.60 /
1,053,133 imps / 166 leads), and the old dashboard on the live payload was rendered head-to-head
against the new dashboard on the new payload: **0 differences across all 15 rendered sections** -
both KPI strips, the stage / bench / ad / fatigue tables, the funnel, burn, goal, pacing bars,
insights, creative grid, chart set and stage chips.

### The three-stage contract, extended

A value on screen still traces `sql view column -> job/main.py key -> dashboard.html data.* key`.
The 2026-08-24 additions:

| sql | job | dashboard |
|---|---|---|
| `fact_all.channel` | `rows[].channel` | `chanOf()` / the PLATFORM chips / `deliveredChans()` / `renderPlatformTable()` |
| `fact_all.plan_line` / `.plan_seq` | `rows[].plan_line` / `.plan_seq` | carried, not rendered (see "There is no Media Plan tab") |
| `media_plan.*` | `properties[].plan[]` / `.plan_channels` | `planChannels()` -> the coming-soon placeholder only |
| `seed_property_map.status` | `properties[].status` | `comingSoonProp()` -> the placeholder gate |
| `targets.property_key` | `properties[].targets` / `.benchmarks` | `propDef()` -> `bench()` / `targetItem()` |
| `budget.measurable_budget_aud` | `flight.budget_measurable` / `.budget_committed` | the Ad-spend KPI's "% of flight" |
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
 raw_windsor.perf_linkedin      + 07/08/09 stg_* -> 10_fact_all
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
| Campaign filter / funnel-stage mapping (Meta) | `sql/01_stg_meta.sql` |
| Which development a campaign belongs to | `targets/property_map.csv` -> `seed_static.py` |
| The **media plan** (lines, budgets, imp/click/CPM/CTR targets, line matching) | `targets/media_plan.csv` -> `seed_static.py` -> export `FORCE_REBUILD=1` |
| A new channel's scope / column mapping | `sql/07_stg_linkedin.sql` · `08_stg_ttd.sql` · `09_stg_google_ads.sql` |
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

## The motion layer (2026-08-26)

Presentation only. No sql, job, payload or export path is touched, and the rendered TEXT of the
dashboard is unchanged - it is `dash/dashboard.html` + `dash/main.py` and nothing else, so
`deploy_dash_geocon.ps1` covers it.

**Client-specific motion sits ABOVE the `BB-MOTION-KIT` / `BB-LOGIN-KIT` blocks, never inside
them.** `scripts/apply_motion_kit.py` rewrites those blocks in place, so an edit made inside one
is silently lost on its next run. Because the client block sits EARLIER in the file, its selectors
carry one extra level of specificity (`body .bb-lgfx .o1`, not `.bb-lgfx .o1`) or the kit wins the
cascade at equal weight.

**The kit already owns `translate` and `scale`** (its hover lift, its press state, and the
`--bb-rev`/`--bb-hov` composition behind the scroll reveal). Nothing added here touches either
property - the polish is pseudo-elements, `box-shadow`, colour and `filter` only. Two rules over
one geometry property is a fight the more specific one wins silently, which is exactly how a hover
lift can stop firing with no error.

**Charts** were running on bare Chart.js defaults (everything arrived at once, hover snapped).
`initChartDefaults()` now sets three separate things: a staggered ENTRY (`animation.delay` as a
function of `dataIndex`, capped at 260ms - past about a third of a second the last bar reads as lag,
and these charts can hold 100+ points), eased HOVER (`animations.colors`/`numbers`), and a SHORT
`transitions.active` (180ms; any longer and the tooltip visibly trails the cursor) plus
`transitions.resize` at 0 so a window drag does not replay the entry. Donuts get `hoverOffset`.
**`animation.delay` is scriptable and safe; a function under `options.plugins.*` is NOT** - it is
treated as a scriptable option, auto-invoked, throws, and silently blanks the whole chart.

**The login's drafting sheet drifts on a seamless loop.** Its grid periods are 26px and 130px, and
130 is exactly 5x26, so translating the layer by 130px in each axis lands the pattern back on
itself and the loop point is invisible - change that number and a seam appears. The layer is
inflated (`inset:-150px`) so the drift can never expose an uncovered edge, and it is transform-only
rather than `background-position`, which would repaint. The original design note stands - a
property developer brand should not bounce - so this is a 96s drift and a 300s rotation, not
animation. Everything stops under `prefers-reduced-motion`.

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
cheaply probes whether any of its **four** upstream tables advanced (`__TABLES__.last_modified`
vs the `_freshness.json` watermark) and rebuilds only when one did: `raw_windsor.perf_meta`,
`raw_windsor.perf_linkedin`, `raw_windsor.perf_the_trade_desk` and the Google Ads DTS base table
`raw_google_ads.p_ads_CampaignBasicStats_3451896252` (the BASE table, never the frozen bridge
view). The three added in 2026-08 are shared with other clients, so their delivery also trips this
gate and geocon rebuilds more often than its own data strictly changes - the alternative, gating on
Meta alone, would leave a new channel's first day invisible for up to 24h. Static re-seeds (targets/budget) don't move
the gate, so force them with `FORCE_REBUILD=1`. (Pacing is time-relative — `pace_expected` / projection
are computed from the wall clock at build time, so a no-data day leaves them a day stale until the next
rebuild; this is inherent to the gate and matches the other clients.)

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.{perf_meta, perf_linkedin, perf_the_trade_desk}` (shared Windsor connectors) + `raw_google_ads.p_ads_*_3451896252` (native DTS, customer `5457742070`) — no stage-1 loader here |
| Views | `client_geocon.{stg_meta, fact, targets, budget, breakdowns, media_plan, stg_linkedin, stg_ttd, stg_google_ads, fact_all}` (+ `seed_targets` / `seed_budget` / `seed_media_plan` / `seed_property_map` tables) |
| Job / Service | `geocon-export` / `geocon-dash` |
| Data bucket / file | `bidbrain-analytics-geocon-dash` / `geocon.json` (report cache in `reports/`) |
| Dash runtime SA | `geocon-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | `anthropic-api-key` (required) · `gemini-api-key` (optional fallback) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
