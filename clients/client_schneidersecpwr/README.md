# client_schneidersecpwr — Schneider Electric "Secure Power"

The **THIRD** Schneider dashboard, and a lean sibling of `client_schneiderlqai` (same engines, same
aesthetic, same 3-stage pattern). It reports the **three Secure Power briefs** that are deliberately
OUT of `client_schneider`'s scope because **they have separate stakeholders** — a different group of
people views this dashboard:

| Campaign | Brief | Channels | Markets |
|---|---|---|---|
| **Enterprise IT Expansion** (`ent_it`) | 1958 | LinkedIn + Trade Desk | India · MEA · South America · Pacific |
| **Industrial Edge / Prefab** (`ind_edge`) | 2463 | LinkedIn + Trade Desk | Australia · New Zealand |
| **Software First EcoStruxure** (`software_first`) | 2305 | LinkedIn + Trade Desk | Australia · New Zealand |

- **Paid media only.** No Salesforce / content syndication, no GA4, no conversions. The story is
  reach (impressions), clicks, CTR and cost efficiency (CPM / CPC) per brief, per **media-plan line
  item** (funnel stage), per market.
- **DELIVERY-ONLY — there are NO targets.** None of the three has a signed media plan, so there is no
  pacing card, no budget tile and no vs-plan column anywhere. Each campaign's flight is **observed**
  ("live since <first delivery day>"), never presented as a booked window.
- **Currency:** AUD (both channels native AUD; USD@1.50 / SGD@1.15 arms kept for robustness).

## Relationship to the other two Schneider dashboards
| | Scope |
|---|---|
| `client_schneider` | The multi-program Pacific dashboard — the 8 programs on the client's own intake sheet. These three are explicitly excluded (client, 2026-08-10). |
| `client_schneiderlqai` | Single campaign: Liquid AI Data Center (brief 2306). |
| **`client_schneidersecpwr`** | **These three briefs. Separate stakeholders.** |

All three read the same shared raw mirrors but are **fully self-contained** — this dashboard does NOT
read `client_schneider`'s views, so a scope change there cannot move numbers here.

## Tabs
1. **Overview** — delivery KPIs (spend / impressions / clicks / CTR + CPM/CPC), a **campaign
   comparison** table (which replaces LQAI's pace-to-plan card, since there are no targets), a
   delivery-over-time hero chart with grain + Relative/Absolute toggles, a LinkedIn-vs-Trade-Desk
   channel table, a **Line item performance** table (line item × channel — see "Line items" below),
   spend by channel + by market, and a market summary.
2. **Campaigns** — one card per brief (spend / imps / clicks / CTR, channels, markets, live-since,
   and LinkedIn lead-form leads where a brief runs Lead Generation ad sets), plus campaign × channel,
   **campaign × line item** (with a stacked impressions-by-line-item chart) and campaign × market
   breakdowns, and a spend-by-campaign / impressions-by-region pair of charts.
3. **Creative** — concepts, formats, best creatives by CTR, and a sortable/searchable detail table
   carrying a **Line item** column (the same creative is often reused across funnel stages).
4. **Reports** — two client-ready documents Campaign Manager cannot export in one click, rendered on
   screen and downloadable as formatted `.xlsx`. See "The Reports tab" below.

**Channel chips (2026-08-15):** a coloured chip per engine, next to the Campaign dropdown, honoured
by every delivery and creative figure via `platOk()`. **Only engines the SELECTED campaign actually
ran are rendered** (client rule - never advertise a channel a campaign does not have); the roster is
derived from the data ignoring the channel filter itself, the last engine cannot be unticked, and the
whole group hides when one engine is left. Same rule now applies on `client_cloudflare`,
`client_schneider` and `client_schneiderlqai`.

Filters: a **Campaign dropdown in the top nav bar** (the `client_schneider` / Cloudflare pattern -
`#campSelect` + `setCampaign()`), plus **Line item** chips, **Market** chips and a **date range**
(Overview + Campaigns; the Creative feed carries no date column, so the picker is hidden there).

**Line-item chips (2026-08-18)** follow the channel-chip rules: only line items the SELECTED campaign
actually bought are rendered, and the whole group hides when there is nothing to choose between -
Enterprise IT names its ad sets by vertical rather than funnel stage, so it has a single `Unspecified`
line and a lone chip there would imply a filter that cannot change anything. Switching campaign
re-opens every line-item chip as well as every market chip, for the same reason given below for
markets: the three briefs buy DIFFERENT line items.

**The Campaign dropdown is single-select** and leads with **"All campaigns"** - unlike
`client_schneider`, whose portfolio option was retired, the combined three-brief view is the whole
point of this dashboard, so it is the default. Switching campaign **re-opens every market chip**
(`setCampaign` resets `activeMarkets` from `marketRoster()`): the three briefs run in DIFFERENT
markets, so carrying a market selection across would silently zero the incoming campaign's numbers.
**`.dash-select` must keep a SOLID background** - Chrome paints the native `<option>` list from the
select's own background, so a translucent value makes every option invisible on the dark nav bar.

## Architecture (standard 3-stage pattern)
```
raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}      (shared mirrors, filled by ingest/)
  -> sql/01_stg_linkedin, 02_stg_tradedesk                 (scope: 3 briefs; campaign + market +
                                                           line-item/tactic tagging)
  -> sql/03_delivery (campaign x platform x tactic         + sql/04_creative (whole-flight,
                      x market x day)                         carries tactic too)
     + sql/05_linkedin_adsets (one row per ad set; JOINs seed_adset_targeting)
  -> job/main.py -> gs://...-schneidersecpwr-dash/schneidersecpwr.json           (client payload)
                 -> gs://...-schneidersecpwr-dash/schneidersecpwr_internal.json  (STAFF ONLY: adsets)
  -> dash/main.py (Flask password gate) serves dashboard.html + /data.json
```
There is **no seed table and no `data/` dir** — nothing to seed, because there are no targets.

## The Reports tab
Two documents the media buyer used to assemble by hand.

### Who can see it — STAFF ONLY
**This tab is for 100% Digital and the owning agency. The end client must never see it.** Three
layers, because hiding a tab in a browser is not on its own worth anything:

1. **The tab only exists when `window.BB_INTERNAL` is set** — injected into `<head>` by the platform
   proxy for **superadmin / admin / owning-agency** sessions only (the same `_internal_allowed`
   predicate that decides whether the staff Internal Notes widget is injected;
   `client_cloudflare` gates its notes card on it the same way). A client session, and any raw
   `*.run.app` URL, never receives it — so the tab is not built, its pane stays hidden, and a
   `#reports` deep link falls back to Overview. `STAFF_TABS` / `tabAllowed()` in `dashboard.html`.
2. **The targeting data is not in the client's payload.** `adsets` lives in its own bucket object,
   `schneidersecpwr_internal.json`, served by `GET /internal/reports.json` and fetched lazily only
   when the tab is opened. `data.json` carries nothing about ad-set targeting.
3. **The two builder routes hold no client data** — they are pure functions over what the caller
   posts, and return nothing the caller did not already send.

**Known limit, deliberate:** layer 1 is a UI gate, not an authorization boundary. This service cannot
yet distinguish a staff session from a client one by itself — the `bb_sso` cookie carries the
allowed-client list, not the role — so `/internal/reports.json` authenticates (401 without a
session) but does not authorize by role. Closing that means adding the role to the SSO token in
`platform_sso.py`, which is **vendored into every dashboard** and signed by the platform, so it is a
platform + all-dashboards change rather than a local one. Until then, treat the ad-set targeting as
"not shown to the client" rather than "cryptographically withheld from the client".

Both reports are scoped by the **top-nav Campaign dropdown only** — the market, channel and date filters are hidden there, because a targeting setup
and a matched-company list are whole-account facts and filtering them would produce a document that
quietly disagrees with Campaign Manager.

Workbooks are built **server-side** (`dash/xlsx_reports.py`, openpyxl) rather than in the browser:
the free browser-side spreadsheet libraries write values but not fonts or fills, and here the
formatting *is* the deliverable. House style — grey `D9D9D9` headers, Calibri 9, alternating `F7F7F7`
rows, `#,##0`, frozen header, auto-filter — lives in one STYLE block at the top of that file and was
matched against the reference workbooks the client supplied. Change it there and both reports move.

### 1. Targeting Breakdown
One row per LinkedIn ad set: Phase · Ad Set · Geo · Targeting Method · Include Criteria · Industries ·
Company List/TAL · Exclude Criteria · Audience Size, plus a "Job Titles Summary" sheet grouping every
targeted title by funnel phase.

**The rows are always real, the criteria are seeded.** Which ad sets exist, their current name, phase
and geo come from live delivery (`sql/05_linkedin_adsets`), so the report can never invent an ad set
or miss one. The audience columns come from `targeting/adset_targeting.csv`, because **LinkedIn's
ad-set targeting is in no feed this repo has** — `raw_snowflake.linkedin_ads_apac` is 33 columns of
delivery metrics and Windsor's `perf_linkedin` is the same shape. The only machine source is the
Marketing API (`GET /rest/adCampaigns/{id}` -> `targetingCriteria`, then `adTargetingEntities` to
turn each URN into a label), which needs a developer app carrying the **Advertising API** product and
a member token with a VIEWER+ role on ad account **517045062** — Transmission's account.

Recording the targeting:
```powershell
# 1. refresh the ad-set list from live delivery (preserves everything already filled in)
.\.venv\Scripts\python.exe clients\client_schneidersecpwr\load_targeting.py --scaffold
# 2. fill in the audience columns in clients\client_schneidersecpwr\targeting\adset_targeting.csv
# 3. push it to BigQuery and rebuild the JSON
.\clients\client_schneidersecpwr\sql\deploy_views_schneidersecpwr.ps1
```
The CSV's `campaign` / `adset_name` / `phase` / `geo` columns are **reference only** — rewritten by
`--scaffold`, ignored by the view. The join key is the numeric `adset_id`, so a LinkedIn rename can
never orphan a filled-in row. An ad set that stops delivering is parked at the end of the CSV with a
`no longer delivering` note rather than deleted, so hand-entered work is never silently lost.

Until a row is filled in, the tab says **"Audience criteria not recorded yet"** and prints *not
recorded* in each empty cell — never a convincing-looking blank. A **"Preview with sample data"**
toggle fills illustrative criteria so the layout can be checked; everything it produces is watermarked
`SAMPLE` in the banner, the workbook subtitle *and* the file name.

### 2. Matched TAL Audience
Drop the Campaign Manager export (**Plan > Companies**, filtered by the campaign's company list) onto
the tab. The service parses it, builds the summary (total matched, the five-level engagement split
with percentages, reached vs not-yet-reached by paid), sorts by paid impressions and returns the
formatted workbook. The upload is parsed in memory and never stored.

**Why this one is an upload and not an API call:** the matching endpoint is LinkedIn's **Company
Intelligence API** (`GET /rest/accountIntelligence`) — whose response fields are a 1:1 match for this
report's 13 columns — and it is documented as *"a private API available only to previously approved
developers. We are not currently accepting new applications."* It is reachable only through
LinkedIn's certified attribution partners, so no app configuration on our side unlocks it. That one
export stays manual; everything after it does not. If access is ever granted, keep
`tal_parse.normalise()` and swap the caller — the API's field names are already accepted as aliases.

The parser (`dash/tal_parse.py`) is deliberately tolerant: it accepts `.csv` and `.xlsx`, finds the
header row by content (Campaign Manager prefixes a variable number of metadata lines), matches
headers on a squashed key so "Paid Impressions" / "paid impressions" / "paidImpressions" all land in
the same column, drops any trailing Total row, and reports unrecognised columns on screen instead of
dropping them silently. Verified against both reference exports: 197 and 1,629 companies, summaries
reproducing the supplied workbooks exactly.

## Campaign tagging — the part to get right
Every match is a **substring token on CAMPAIGN_NAME**, never a fixed offset, because Transmission is
progressively prefixing campaign names with the brief number and the SAME campaign appears under both
`SE_*` and `<brief>_SE_*` forms (repo-wide rule in `md/AGENTS.md`). The three token sets are disjoint,
verified against every Schneider campaign before the views were written.

| Campaign | Tokens | Why |
|---|---|---|
| `ent_it` | `EntIT` | catches `SE_EntIT_2026_*` and `1958_SE_EntIT_2026_*` |
| `ind_edge` | `SE_Industrial Edge_`, `Industrial Edge Wave3`, `Industrial Edge W3`, `2463_` | **WAVE 3 ONLY.** The bare `Industrial Edge` token also sweeps in the 2025 `1839_Schneider_Electric_Pacific_*` wave (~A$8.7k) — a different brief. Widen only on an explicit instruction. |
| `software_first` | `Software First`, `EcoStruxureIT`, `2305_` | **`2305_` alone is NOT enough** — the Trade Desk line ran as `SE_EcoStruxureIT_AWR_2026` from 2026-06-17 and only gained the prefix on 07-06, so a prefix-only token silently drops ~A$2.3k. |

**Match on CAMPAIGN_NAME, never CAMPAIGN_GROUP_NAME.** LinkedIn's group names are mislabelled here: a
group named `2305_SE_ANZ Industrial Edge W3 Prefab` holds campaigns named
`2463_SE_Industrial Edge Wave3_*`. Keying on the group would cross-tag two different briefs.

## Markets — NOT folded to AU/NZ
`client_schneider`'s `pm_delivery` folds everything to Australia / New Zealand. **This dashboard must
not**, because Enterprise IT genuinely runs across India / MEA / South America / Pacific and only
~12% of it is Pacific — folding would report the rest as Australia. The staging views therefore keep
the market the parser resolved, and `03_delivery` adds a `region` rollup (Pacific covers Australia,
New Zealand, the combined `ANZ` residual and Enterprise IT's own `Pacific` token). Anything
unparseable lands in `Unmapped` and shows as a loud trailing chip rather than being absorbed silently.

Parser: ad-group first then campaign name on Trade Desk (Industrial Edge and Software First carry
their country only in the ad-group name); campaign name on LinkedIn. Country tokens beat coarse
region tokens, ANZ beats Pacific, first match wins — the same proven parser `client_schneider` uses.

### ...but a rename artefact is not a third market (2026-08-18, client)
Industrial Edge displayed **Australia, New Zealand *and* ANZ**, and the client rightly asked why a
two-market campaign had three market lines. It never ran a combined-ANZ line. Transmission renamed
five LinkedIn ad sets from `SE_Industrial Edge_<Phase>_{AU,NZ}` to `2463_..._<PH>_ANZ_<fmt>` on
**2026-08-07** and back to the per-country form on **08-13**, so six days of each ad set's delivery
(5,619 imps / A$855) parsed as a phantom `ANZ` market. **The ad set ID never moved.**

`01_stg_linkedin` now reconciles this: when a row's OWN name resolves to a coarse token but that ad
set's **current** name (the most recent day it delivered) names a specific country, the row takes the
ad set's current country. Deliberately narrow in both directions:

- a row whose own name already names a country is **never** rewritten, so genuine per-country history
  is not retro-relabelled if an ad set really does change geo later;
- an ad set **still** named with a coarse token keeps it — Enterprise IT's `_PAC_` ad sets stay
  `Pacific` — so a genuinely combined-market line is never invented into a country it never had.

Same principle `05_linkedin_adsets` already applied to the ad-set name: the **ad set is the key, the
name is not** (md/AGENTS.md). Verified a strict **no-op on ent_it and software_first** — it moves
exactly the six ind_edge rows, and the campaign's totals are unchanged (229,595 imps / A$6,156;
AU 219,086 / NZ 10,509, was AU 214,535 / NZ 9,441 / ANZ 5,619). The `ANZ` arm stays in
`03_delivery`'s region rollup as a defensive residual.

**Trade Desk needed no change** — its ad-group-first parse already split the `..._AWR_ANZ_display`
campaign into `Awareness_Premium IT_AU` / `_NZ`, which is why only LinkedIn showed the phantom.

## Line items (media-plan tactics)
The 2463 media plan is bought as **line items** — Awareness on Programmatic *and* on LinkedIn,
Consideration (retargeting), Conversion (lead-gen form) — but the dashboard could only break delivery
down by **channel**, so an Awareness-vs-Consideration-vs-Conversion view was impossible. The client
asked for it on 2026-08-18. `tactic` is now a first-class dimension the whole way through:

    sql/01+02 (tactic)  ->  sql/03_delivery + sql/04_creative  ->  job/main.py (tactic, tactics)
                        ->  dashboard.html (Line item chips, tables, chart, CSV, deck payload)

Vocabulary and display order: **Awareness -> Consideration -> Retargeting -> Conversion ->
Unspecified** (`TACTIC_ORDER` in `job/main.py`, `TACTICS` in `dashboard.html` — keep them in step).
Each stage has a **fixed** colour, not one assigned by index, so Conversion does not change colour
when a campaign without a Consideration line is selected.

Parsed from the ad-set name (LinkedIn) or **ad group first then campaign name** (Trade Desk), matching
most-specific token first: **Retargeting before Conversion before Consideration before Awareness**,
because `CONVERSION` contains `CON` and a Consideration-first ladder mislabels every conversion ad
set. Short tokens are delimiter-anchored so `CON` cannot match inside a word. The retargeting arm
accepts the numbered forms Transmission actually uses (`RTG` / `RTG1` / `RT1`) — the previous
`RTG|RT1|RT2` set could not match `..._RTG1_ANZ_image` at all, because the digit sits between `RTG`
and the delimiter, so Software First's retargeting ad set was reported as `Unspecified`.

`stg_linkedin.tactic` is the **single definition**: `05_linkedin_adsets` reads its `phase` from it
rather than re-deriving the ladder, so the staff Reports tab and the delivery tables can never
disagree about which stage an ad set sits in.

**`Unspecified` is a true answer, not a gap.** Enterprise IT names its ad sets by VERTICAL
(Hero / Generic / Manufacturing / Healthcare / Finance / Retail / Education), not by funnel stage, so
all of its delivery lands there — and the UI says so, hiding the line-item chips, table and chart
entirely when a single stage is in play rather than drawing a one-row "breakdown" of the totals above
it. The AI-deck payload carries the same warning in `paid.line_item_note`.

What each brief runs today: **ind_edge** Awareness (LinkedIn + Trade Desk) · Consideration · Conversion;
**software_first** Awareness (both) · Consideration · Retargeting; **ent_it** Unspecified only.

**Lead-form leads** appear as a column on the campaign × line-item table only when a line shows lead
form ACTIVITY (`leads > 0 OR lead_form_opens > 0`), never merely a non-null count: LinkedIn reports
`leads = 0` on every ad set, awareness ones included, and a `0` there reads as "this line was asked
for leads and got none". Form opens separate the two, so a Conversion line that genuinely converted
nobody still prints a real `0` while an Awareness line prints `-`. Trade Desk always prints `-`.

## Monitoring
In the status pipeline's `CLIENTS` roster (`status_dashboard/job/main.py`) since 2026-08-17, with
**4 accuracy checks** — LinkedIn and Trade Desk impressions + clicks, each comparing the dashboard
JSON against Snowflake. Spend is deliberately NOT checked (the staging views apply an FX CASE per
account currency). The scope predicate uses Snowflake `CONTAINS` / `STARTSWITH`, never `LIKE`:
`_` is a LIKE wildcard and the ind_edge token is literally `SE_Industrial Edge_`.

Because the three briefs are a SUBSET of the Schneider advertiser (which also carries the Pacific
book and LQAIDC), the check necessarily re-states the view's own scope — so it catches an **ingest or
build** regression, not a scope-token regression. For that, compare the live campaign list against
"Campaign tagging" above. Verified against the mirror on 2026-08-17: LinkedIn 1,359,802 imps / 3,202
clicks, Trade Desk 2,424,557 imps / 5,876 clicks — all four exact.

Not in `SLIDES_CLIENTS` (the platform's "Open slides" roster) on purpose: `/report` is wired but not
enabled here — see Known follow-ups.

## Freshness
Self-gating `*/10` UTC (`schneidersecpwr-export-daily`). The gate watches
`raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}` `__TABLES__.last_modified`; watermark =
`gs://...-schneidersecpwr-dash/_freshness.json`. Any **view-only change needs a forced run**
(`FORCE_REBUILD=1`) — the gate does not watch views.

The job **refuses to publish an empty fact**: if the delivery view returns 0 rows it aborts rather
than overwriting a good JSON, so a scope regression (a renamed campaign no token matches) surfaces as
a failed run instead of a dashboard that reads "campaign stopped".

## Deploy / edit (root CLAUDE.md is the canonical command source)
- Edited `dash/dashboard.html` or `dash/main.py` -> `dash/deploy_dash_schneidersecpwr.ps1`
- Edited `job/main.py` -> `job/deploy_job_schneidersecpwr.ps1`
- Edited a `sql/*.sql` view -> `sql/deploy_views_schneidersecpwr.ps1` (reapplies + forces a job run)
- First-time standup (idempotent) -> `deploy_schneidersecpwr.ps1`
- Sanity-check the dashboard JS before deploying:
  `.\.venv\Scripts\python.exe scripts\_validate_dash_js.py clients\client_schneidersecpwr\dash\dashboard.html`

## GCP facts
- Project `bidbrain-analytics`, region `australia-southeast1`.
- Dataset `client_schneidersecpwr` · bucket `bidbrain-analytics-schneidersecpwr-dash` ·
  job `schneidersecpwr-export` · service `schneidersecpwr-dash`.
- SAs `schneidersecpwr-dash-job@` (BQ read + bucket write) · `schneidersecpwr-dash-web@` (bucket read
  + secretAccessor). Secrets `schneidersecpwr-dash-password`, `schneidersecpwr-dash-session-key`.
- **NEW-CLIENT GOTCHA (md/AGENTS.md):** grant `platform-dash-web@` `secretAccessor` on
  `schneidersecpwr-dash-password`, or the front-door tile's Open button returns a bare **500** with
  nothing in this service's own log. Also add `schneidersecpwr` to `$CLIENTS` in
  `scripts/enable_super_admin.ps1` so god-mode reveal/rotate works.

## Known follow-ups
- ~~AI slide deck dormant~~ — **ENABLED 2026-08-15.** `dash/enable_report_schneidersecpwr.ps1` was
  created and run (grants `roles/aiplatform.user` + bucket write for the report cache, mounts
  `GEMINI_MODEL=gemini-2.5-pro`, bumps the Cloud Run timeout to **900s** for the two-stage
  research + structuring call), and `dash/report.py`'s `CONFIG` block was **re-templated off LQAI's
  single-campaign awareness language** onto this dashboard's reality. The three things the prompt now
  enforces, because getting any of them wrong would put a falsehood in a client deck:
  1. **THREE separate briefs**, never one blended programme — and Enterprise IT is **multi-region**
     (India/MEA/South America/Pacific, only ~1/8 Pacific), so it must not be called an ANZ campaign.
  2. **NO TARGETS EXIST** — the guardrail forbids any target, budget, quota, "% to plan",
     "on track" or "ahead/behind" language, and tells the model to write a delivery/efficiency KPI
     wherever it would normally write a pacing one. `plan.has_targets:false` in the payload backs it.
  3. **Flights are OBSERVED** ("live since <date>", never "x days remaining"), and any LinkedIn
     lead-form count is a **paid platform metric, not a qualified/Salesforce lead**.
  Runs on **Vertex Gemini** (no Anthropic key supplied); re-run the enable script with `-Key` to add
  Claude. `buildReportPayload()` already emits the three-campaign shape (`paid.by_campaign`).
- **LinkedIn Marketing API access** would make the Reports tab fully automatic. Two separate asks,
  and only the first is obtainable: (a) the **Advertising API** product on a LinkedIn developer app
  plus a token with a VIEWER+ role on ad account 517045062 (Transmission's) would replace the
  hand-recorded `targeting/adset_targeting.csv` with a real loader; (b) the **Company Intelligence
  API** would replace the Companies-export upload, but it is private and **closed to new
  applications**, so treat the upload as permanent unless LinkedIn reopens it or Schneider already
  work with one of the certified partners (Dreamdata, Factors.ai, Channel99, Octane11, Fibbler).
- **A MEDIA PLAN NOW EXISTS FOR ind_edge (2463) — and is deliberately NOT wired up yet.** The client
  supplied *"2463 Final media plan - SEE Industrial Edge Wave 3 Media Plan.xlsx"* on 2026-08-18 as the
  reference for the line-item split (that is all the 2026-08-18 change used it for). It carries real
  targets: flight **2026-07-01 -> 10-31**, budget **A$52,150**, 85,999 planned impressions, and per-line
  targets — Awareness/Programmatic 61,000 imps @ A$9,150 (CPM A$15) · Awareness/LinkedIn 9,333 @ A$7,000
  (CPM A$75) · Consideration/LinkedIn 7,333 @ A$5,500 · Conversion/LinkedIn lead-gen 8,333 @ A$7,500 ·
  plus a **Direct IT** line (40 HQLs @ A$575 CPL, A$23,000) that is an **offline lead vendor with no
  media delivery** and therefore has no row in this warehouse at all.
  Wiring it means turning this dashboard from delivery-only into partly-paced, which touches more than
  a view: `has_targets` is `false` today and the **AI-deck guardrail in `dash/report.py` forbids all
  target / pacing / "on track" language** on that basis. So it needs, in one change: a committed
  `data/media_plan.csv` -> `seed_media_plan` via a `load_seeds.py` read by `job/main.py`; `paceBar()` /
  `renderPacing()` ported from `client_schneiderlqai/dash/dashboard.html`; **per-brief** `has_targets`
  (ent_it and software_first still have no plan, so a single global flag would promise pacing the other
  two cannot deliver); the report prompt re-templated; and a decision on how to present the Direct IT
  line, which will otherwise read as a 0%-delivered line item. Do not hardcode targets, and do not
  half-wire it — a plan on one of three briefs is exactly the case the current copy ("no media plan has
  been supplied for any of them") would start lying about.
