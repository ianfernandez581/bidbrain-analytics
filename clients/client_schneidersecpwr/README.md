# client_schneidersecpwr — Schneider Electric "Secure Power"

The **THIRD** Schneider dashboard, and a lean sibling of `client_schneiderlqai` (same engines, same
aesthetic, same 3-stage pattern). It reports the **three Secure Power briefs** that are deliberately
OUT of `client_schneider`'s scope because **they have separate stakeholders** — a different group of
people views this dashboard:

| Campaign | Brief | Channels | Markets |
|---|---|---|---|
| **Enterprise IT Expansion** (`ent_it`) | 1958 | LinkedIn + Trade Desk | India · MEA · South America · Pacific |
| **Industrial Edge / Prefab** (`ind_edge`) | 2463 | LinkedIn + Trade Desk | Australia · New Zealand |
| **Software First EcoStruxure** (`software_first`) | 2305 | LinkedIn + Trade Desk | Australia · New Zealand · ANZ |

- **Paid media only.** No Salesforce / content syndication, no GA4, and no conversion COUNTS -
  LinkedIn's `CONVERSIONS` column is 0 on every Schneider row, so even a Conversion line item reports
  reach, clicks and cost (see "Line items"). The story is reach (impressions), clicks, CTR and cost
  efficiency (CPM / CPC) per brief, per **media-plan line item** (funnel stage), per market.
- **DELIVERY-ONLY — there are NO targets.** None of the three has a signed media plan, so there is no
  pacing card, no budget tile and no vs-plan column anywhere. Each campaign's flight is **observed**
  ("live since <first delivery day>"), never presented as a booked window.
- **Currency:** AUD (both channels native AUD; USD@1.50 / SGD@1.15 arms kept for robustness).

## Campaign scope is a SET of briefs (2026-09-02, ported from client_schneider)
The topbar `<select>` is now the same **multi-select tag control** as `client_schneider` (antd
`mode="tags"` pattern, built natively). The CSS block and the component were lifted from that
dashboard programmatically rather than retyped, so the two cannot drift - port a fix to both.

Same rules: tags with `x`, an `All campaigns` row, `only` on hover (or alt-click) to isolate, `+N`
collapse with the hidden briefs in its tooltip, draft + **Apply** (Cancel / Escape / outside click all
revert), the last brief un-removable, search that filters visibility only and never hides a selected
tag, and no keyboard highlight until the keyboard is used. `allCampaignsView()` keeps its name (it now
means "all three are selected"), so its four call sites did not move.

Three things differ because THIS dashboard is different:
- **Rows show the brief number** (1958 / 2463 / 2305) and **search matches it** - that is how these
  three get referred to in briefs and media plans.
- **The market and line-item rosters became UNIONS over the selection.** The three briefs run in
  different markets (ent_it is India/MEA/South America/Pacific, the other two AU/NZ) and buy different
  line items - and **ent_it has NO line items at all** (it names ad sets by vertical), so an
  INTERSECTION would empty the roster the moment ent_it joined a selection. Markets are unioned in the
  payload's own order so the chips keep their sequence.
- **Apply matters more here than the tick count suggests**: changing the scope also rebuilds both of
  those rosters, so an instant-commit control re-derived them on every click.

**The Reports tab's workbook title had to follow the scope.** `repScopeBrief()` feeds the `.xlsx`
filename AND its header, and for a two-brief selection it would have produced a file called
"Secure Power - all campaigns" containing two of the three - the kind of thing that gets forwarded to
a client. It now names the briefs it actually contains.

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
There is **no TARGET seed and no `data/` dir** (no targets). The one seed is `seed_adset_targeting`
(the Reports tab's hand-recorded audience, `targeting/adset_targeting.csv`); the stated line-item
overrides live INLINE in `sql/01_stg_linkedin` (two rows, ID-keyed), not in a seed.

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

**Top-N control (2026-09-11, client: "which accounts are the Top 25-50 engagers"):** a `Top 25 /
Top 50 / All` selector above the table, defaulting to **25**. It drives the **workbook as well as the
screen** - a report headed "Top 25" that shipped every matched company is exactly the kind of file
that gets forwarded to a client - so `talPayload()` sends `talRows()`, the `.xlsx` filename carries
`_Top25`, and the cover subtitle states the selection and the full matched total. `TAL_ONSCREEN` (250)
survives as a hard DOM ceiling under `All`, so a 1,629-row export cannot paint 1,629 rows. The rows
arrive already sorted by paid impressions, so top-N is a slice, not a re-sort.

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

### CAMPAIGN_NAME wins; CAMPAIGN_GROUP_NAME is a FALLBACK (2026-09-02)
LinkedIn's group names are mislabelled here in **both** directions: a group named
`2305_SE_ANZ Industrial Edge W3 Prefab` holds campaigns named `2463_SE_Industrial Edge Wave3_*`,
and a group named `2463_SE_Software First EcoStruxure_AWR_ANZ_static` holds campaigns named
`2305_SE Software First EcoStruxure - AWR AU`. **The group may never overrule a name that already
carries a brief token** - that is what would cross-tag two briefs.

But the name ALONE silently dropped a live 2305 line. Transmission's A/B test
`2305_Software First_A/B test (Expert Webpage vs Interactive Demo Page) Test` (LinkedIn campaign
group **1191212126**, live **2026-08-20**) names its two ad sets `ANZ Ad Set A - Expert Page` and
`ANZ Ad Set B - Interactive Demo`. Those carry no brief number, no `Software First` and no
`EcoStruxureIT` - **the brief is stated only on the group** - so **1,333 imps / 5 clicks /
A$1,633.56** reached no KPI, table, chart, CSV or deck. Silent, because a row rejected at the
scope gate never reaches the market or tactic parsers either, so no `Unmapped` chip could flag it.
No name token could have caught these without being recklessly generic (`ANZ Ad Set` would claim
any future brief that happens to name an ad set that way).

So `01_stg_linkedin` resolves the brief in **two tiers, in this order and no other** (a `COALESCE`
of two CASE ladders over the same token sets):

| Tier | Read from | When |
|---|---|---|
| 1 | `CAMPAIGN_NAME` | always - authoritative, identical to the original predicate |
| 2 | `CAMPAIGN_GROUP_NAME` | **only** when tier 1 resolves to NULL |

A campaign that names its own brief is therefore never re-tagged by its group (both mislabelled
groups above still resolve by name), and a campaign silent about its brief is read from the only
place that states it.

**Verified by what it ADMITS, not by a before/after total.** `md/AGENTS.md`: *a scope fix meant to
admit rows must be verified by what it admits* - a no-op check is the wrong test for a widening,
and signing one off is exactly how geocon shipped a Meta gate that still dropped 100% of the
delivery it was written to rescue. The old-vs-new transition matrix across every
`SchneiderElectric_TransmissionSG%` row:

| was | now | imps | clicks |
|---|---|---|---|
| dropped | **`software_first`** | **1,333** | **5** |
| dropped | dropped | 7,711,677 | 21,338 |
| `ent_it` | `ent_it` | 1,292,637 | 3,265 |
| `ind_edge` | `ind_edge` | 223,359 | 438 |
| `software_first` | `software_first` | 75,259 | 221 |

Exactly the two A/B ad sets admitted; **no row changed brief**; the 7.7M imps of Pacific-book and
LQAIDC delivery in the same account still correctly excluded. Re-run that matrix before widening
a token again.

One knock-on fact that is **true of the buy, not a parse failure**: the A/B ad sets read market
**`ANZ`** (a genuine combined-ANZ line, never named per-country - see the rename-artefact section
below for why that is *not* the phantom ANZ), so `software_first` shows a third market chip. Their
LINE ITEM was the opposite case: the names carry no funnel-stage token, so they read `Unspecified`
until 2026-09-03, when the agency confirmed the test IS brief 2305's LinkedIn **Conversion** line -
now stated by an ID-keyed override, see "Stated line items" under Line items below.

**The status-dashboard accuracy check mirrors this predicate and had to move in the same change.**
`_SECPWR_SCOPE_LI` in `status_dashboard/job/main.py` applies the same token set to
`CAMPAIGN_GROUP_NAME` as well; without it the two LinkedIn checks go red, because the dashboard
carries 1,333 imps the check's own predicate refuses to count. Trade Desk keeps the name-only
`_SECPWR_SCOPE` (`TradeDesk_APAC ALL` has no campaign-group column, and 2305's Trade Desk line
already matches by name).

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
> Scope note: this is about `ind_edge`'s **phantom** ANZ. `software_first`'s ANZ chip (the 2305 A/B
> test, from 2026-09-02) is a **real** combined-ANZ line and is correctly left alone by the
> reconciliation below, because those ad sets have never been named per-country.

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

### Channel phase is ONE label on screen (2026-09-11, client)
The client reads the plan as a single dimension - "LinkedIn Awareness", "Trade Desk Consideration",
"LinkedIn Retargeting" - so the **Channel phase performance** table (Overview) and **Campaign x
channel phase** (Campaigns) print `<channel> - <line item>` in one column instead of two. It is a
**presentation change only**: `tactic` and `platform` stay two separate dimensions in `sql/`,
`job/main.py`, the payload, both CSV exports and the deck's `paid.by_line_item`, and every filter,
chip and chart keys off them unchanged. The labels are built from aggregate keys that exist in the
filtered rows, so a channel-phase combination with no delivery is never printed.

`phaseLabel()` / `phasePill()` in `dash/dashboard.html` are the single definition; the pill takes the
**line item's** colour so a row still reads against the line-item chips and the stacked chart.

Enterprise IT's `Unspecified` rows now carry their explanation on BOTH tables, not just Campaigns:
`tacticFootnotes()` is keyed on campaign, so the Overview table builds a campaign-grain aggregate
(`ctCamp`) purely to feed it. The note names the verticals (Healthcare, Finance, Retail, Education,
Manufacturing, Generic, Hero), because "Unspecified" without that reads as missing data.

### Every Reports-tab fetch must be RELATIVE (2026-09-17)
The platform proxy serves this dashboard at `/d/schneidersecpwr/` and rewrites exactly THREE absolute
strings in the HTML it passes through (`bidbrain-platform/dash/main.py`): `/data.json`, `'/report'`
and `/creative-img/`. **Anything else absolute resolves against the PLATFORM root and never reaches
this service.**

All three Reports-tab routes were absolute, so the ENTIRE tab was dead through the front door:

| was | now |
|---|---|
| `fetch('/internal/reports.json')` | `fetch('internal/reports.json')` |
| `fetch('/reports/tal/parse')` | `fetch('reports/tal/parse')` |
| `fetch('/reports/xlsx')` | `fetch('reports/xlsx')` |

Not just the targeting data - the TAL upload and **the `.xlsx` download, which is the actual client
deliverable**, both failed too. It worked when tested on the raw `*.run.app` URL and failed for every
real user, which is the worst possible failure shape and is exactly why it survived.

Relative is correct in BOTH contexts: the proxy's base route is `/d/<client>/` WITH a trailing slash
(`@app.route("/d/<client>/", defaults={"subpath": ""})`), so `internal/reports.json` resolves to
`/d/schneidersecpwr/internal/reports.json` behind the proxy and `/internal/reports.json` direct, and
the proxy forwards arbitrary subpaths (`@app.route("/d/<client>/<path:subpath>")`).

`fetch('/report')` (the AI deck) stays ABSOLUTE on purpose - the proxy rewrites the literal
`'/report'` INCLUDING its quotes, so making it relative would break the rewrite.

**The audit is one grep:** `grep "fetch('/" dash/dashboard.html` should return exactly ONE line, the
`/report` POST. Anything else it lists is broken behind the proxy.

### The Reports tab says on its face that it is internal (2026-09-11)
The tab is gated on `window.BB_INTERNAL`, but **a gate stops a client SESSION rendering it and does
nothing about a staff SCREENSHOT** - which was indistinguishable from a client-facing one. The
section heading now carries `internal - not shown to client` (the exact wording `client_cloudflare`
uses on its internal cards, deliberately not a second phrase) plus a banner naming who the tab is
for and noting the targeting comes from a separate staff-only object, not `data.json`.

This is a LABEL, not a permission. The underlying gap is unchanged and still open: the
`/internal/reports.json` route authenticates but does not authorise by role, because the `bb_sso`
cookie carries the allowed-CLIENT list and not the role. Closing that means putting the role in the
SSO token in `platform_sso.py`, which is vendored into every dashboard.

### Creative-tab axis labels are computed, never hardcoded (2026-09-11)
The four Creative charts were unreadable on real data: `crLiConcept` plotted FULL AD COPY sentences
as rotated x-axis labels that overlapped into a smear, `crTtdConcept` lost its distinguishing tail
because every Enterprise IT creative shares the prefix `SE_EntIT_2026_`, and `crTopCtr` truncated
from the FRONT, chopping off the brief and market - the worst end to cut.

One shared helper set fixes all three: `labelPrefix()` computes the LONGEST COMMON PREFIX over the
labels **in the current selection**, cut back to a `_`/`-`/space boundary and only applied when it
is >=8 chars and every label keeps >=4 chars of tail; `clipEnd()` truncates the TAIL; `axisLabelSet()`
combines them; `fullTitleCb()` restores the untruncated string via `plugins.tooltip.callbacks.title`
(the ONLY safe home for a function - see the Chart.js v4 scriptable-option trap in `md/AGENTS.md`).
**Never hardcode the prefix.** It is derived per render because 2463 and 2305 name their creatives
completely differently, so a literal `SE_EntIT_2026_` would do nothing for them; when labels share
no meaningful prefix, nothing is stripped. `labelNote()` names the removed prefix in the card hint
so a shortened label is not mistaken for the real creative name.

`crLiConcept` is now `indexAxis:'y'` (ad copy needs its own line; a prefix strip buys nothing on a
sentence) with the wrap at 360px. `autoSkip:false` is set on the category axis of all three - Chart.js
defaults it ON and will drop every other LABEL while still drawing every BAR, which is the same
defect `md/AGENTS.md` records for `client_schneider`'s flight gantt. `crTtdFormat` was left alone:
banner sizes are short labels with no shared prefix.

### Stated line items - when no name carries the stage (2026-09-03, agency)
Brief 2305's LinkedIn **Conversion** line is the landing-page A/B test
`2305_Software First_A/B test (Expert Webpage vs Interactive Demo Page) Test` (group **1191212126**;
ad sets `ANZ Ad Set A - Expert Page` 868044926 and `ANZ Ad Set B - Interactive Demo` 868134606).
Nothing in the feed says so: the ad-set names carry no stage token, the group name carries none
either, and the mirror has no objective column - so the ladder read `Unspecified` and the dashboard
showed **no Conversion line for 2305 at all**, which is what the agency noticed. No parse rule could
fix it honestly (`A/B test` => Conversion is false in general - a test can sit on any stage), so the
plan line is **stated**, in `line_item_overrides` at the top of `sql/01_stg_linkedin.sql`, **keyed on
the ad-set ID** (LinkedIn's `CAMPAIGN_ID`, a STRING) - never the name. Rules it encodes:
- **An override WINS over the parsed ladder.** It is a statement about the media plan; a trafficker
  renaming the ad set does not change what was bought.
- **It can only re-label, never admit.** It is joined AFTER the brief gate, so it cannot let a row
  into scope; a new ad set in the same test lands on `Unspecified` (a visible chip) until a row is
  added. Adding one = one `STRUCT` + `sql/deploy_views_schneidersecpwr.ps1`.
- **Both readers of `tactic` see it** (`03_delivery` / `04_creative` and `05_linkedin_adsets.phase`),
  so the delivery tables, the Creative tab and the staff Reports tab agree. `load_targeting.py
  --scaffold` now copies `phase` straight from `stg_linkedin.tactic` instead of re-deriving it with
  its own token list, which would have written `Unspecified` back into the CSV's reference column on
  every refresh.
- **It reports reach, clicks and cost - never a conversion count.** The test has no lead form
  (`leads` / `lead_form_opens` are 0, so the campaign x line-item table prints `-`, not a false 0),
  and LinkedIn's `CONVERSIONS` column is 0 on every Schneider row (Insight Tag outcomes do not reach
  this feed). The Campaigns-tab footnote says exactly that under the line, only while it is on screen
  and only while the line shows no lead-form activity; `report.py` and the deck's `line_item_note`
  forbid asserting a conversion count for it.
- **The Campaigns-tab footnote is per brief now** (`tacticFootnotes()`). It used to blame Enterprise
  IT for ANY `Unspecified` row on screen - wrong whenever the only Unspecified line was Software
  First's - and each sentence now names the brief it is about.

Through 2026-09-02 the line holds **1,434 imps / 5 clicks / A$1,767.05** (media cost), both arms
delivering: Expert Page 681 / 3 / A$911.50, Interactive Demo 753 / 2 / A$855.55.

**`Unspecified` is a true answer, not a gap.** Enterprise IT names its ad sets by VERTICAL
(Hero / Generic / Manufacturing / Healthcare / Finance / Retail / Education), not by funnel stage, so
all of its delivery lands there — and the UI says so, hiding the line-item chips, table and chart
entirely when a single stage is in play rather than drawing a one-row "breakdown" of the totals above
it. The AI-deck payload carries the same warning in `paid.line_item_note`.

What each brief runs today: **ind_edge** Awareness (LinkedIn + Trade Desk) · Consideration · Conversion;
**software_first** Awareness (both) · Consideration · Retargeting · Conversion (the 2305 A/B test,
stated - see above); **ent_it** Unspecified only.

**Lead-form leads** appear as a column on the campaign × line-item table only when a line shows lead
form ACTIVITY (`leads > 0 OR lead_form_opens > 0`), never merely a non-null count: LinkedIn reports
`leads = 0` on every ad set, awareness ones included, and a `0` there reads as "this line was asked
for leads and got none". Form opens separate the two, so a Conversion line that genuinely converted
nobody still prints a real `0` while an Awareness line prints `-`. Trade Desk always prints `-`.

## Industrial Edge's Awareness line spans a TARGETING CHANGE, so a blended rate describes neither side

Shipped 2026-09-18 as a footnote on both line-item tables (`tacticFootnotes()` in
`dash/dashboard.html`). The finding is MEASURED, not inferred, and it took three passes to reach -
the first two readings were wrong in ways worth recording, because both were plausible.

**What happened.** On **2026-08-02** the audience on LinkedIn ad set **859128356** (`ind_edge` /
Awareness / AU) went from **~7.3 million to ~130,000**, a ~56x cut. Measured, not estimated:
LinkedIn reports `approximate_unique_impressions` (reach) and `audience_penetration`
(reach / target audience size), so **reach / penetration IS the audience size**. Four July days
agree within 1.3%, seven August days within 0.8%. ~7.3M is approximately the entire Australian
professional base, i.e. a geo-only audience with no title filter; ~130K is "Australia + nine job
titles", which is what that ad set's current `targeting_include_titles` actually holds.

**It was a job-title filter, applied across the brief, and NOT the other candidates.**
- **TAL swap is ruled out twice over**: 30 of the top 30 July companies also appear in August (BHP,
  Woolworths, Rio Tinto, Coles, Fortescue, Woodside...), and `targeting_include_employers` is NULL,
  so there is no account list on the ad set at all.
- **Audience expansion does not survive the 7.3M figure**: expansion broadens toward lookalikes, it
  does not converge on a national population, and July's delivered mix carried Healthcare Services,
  Education, Retail, Accounting and Marketing at real share - not lookalikes of nine industrial job
  titles. No expansion flag exists in the connector, so this one is inference from magnitude and
  composition rather than from a field.
- **BRIEF-WIDE, not one ad set**: both Conversion ad sets stepped the same day (860493666 ~24x,
  859158326 ~79x). An earlier reading attributed their drop to budget moving to the two Consideration
  ad sets launched 02-03 Aug. That was wrong.

**Two corrections to keep, because the wrong readings were the natural ones.**
1. **The audience network was NOT switched off.** OFFSITE delivery continues every single day after
   the cut, at a CPM climbing A$5 -> A$177. That is frequency saturation on a tiny pool, not a
   placement toggle - and a placement toggle CANNOT explain it, because LAN is a placement setting
   while `audience_penetration`'s denominator derives from targeting criteria. Switching LAN cannot
   move the audience size at all.
2. **The post-change CPM is TOP of range, not "expensive but normal."** A$207-488 sits above every
   sibling on the brief (A$68 NZ Conversion, A$92 AU Conversion) and above the ANZ spread (A$16-138).

**The strongest argument is internal to the account, so it needs no external benchmark**: the
account's other cheap ad sets (India / MEA / SAM at A$7-16 CPM) all have NORMAL CTR of 0.24-0.36%.
859128356 at A$5.96 with **0.047%** CTR is the only ad set in the account pairing bottom-of-range
cost with dead engagement. That is the tell, and it is defensible without quoting a market rate.

**Why a footnote and not a hidden figure.** The line's two halves are **178,745 imps at A$5.72 CPM
/ 0.06% CTR** before, **10,014 at A$206.75 / 0.34%** after. Whole-flight that is 59% of the BRIEF's
impressions on 7.6% of its spend, so including it roughly halves both the reported CPM (A$46.63 vs
A$105.34) and the reported CTR (0.220% vs 0.454%). Hiding it would break the rule that parts sum to
the whole; the honest fix is to keep every number and say what was bought. The note states the
SPLIT and never a cause - we can measure that the audience changed, not which control was moved.

**Three things the implementation gets right and must keep:**
- It splits on **02-08, the day the AUDIENCE changed**, not 03-08 when delivery fell. That day's
  impressions were already bought against the old audience, which is why penetration spikes on 02-08
  while volume is still flat.
- Figures are **scoped to the line the sentence names** (ind_edge / linkedin / Awareness), not to
  the brief. The prose quotes them, so they have to be that line's own or the words and the numbers
  describe different things.
- It is computed from **`pmRows()`** - the one filtered-rows accessor both footnote callers derive
  from - and requires BOTH sides present plus a >=10% July share, so it **retires itself** when the
  date range excludes either period. Do not re-key it on the date picker: a caveat that outlives its
  own evidence is worse than none.

**`fmtPct()` MULTIPLIES BY 100 ITSELF** (`(v*100).toFixed(d)`), so it takes a FRACTION via `pct()`.
The first cut of this note handed it an already-multiplied CTR, which would have printed every
figure 100x high on a client-facing surface. Every other CTR on this page goes through
`fmtPct(pct(a,b),2)` - match it.

**THE POST-CUTOVER FIGURE IS LINE GRAIN, AND THAT IS A CONSTRAINT RATHER THAN A CHOICE.**
`delivery` is aggregated and carries **no `adset_id`**, so the dashboard cannot isolate the ad set
that was actually narrowed. The note's "after" figure therefore POOLS two ad sets:

| ad set | imps | spend | CPM |
|---|---|---|---|
| 859128356 (the one narrowed on 02-08) | 7,851 | A$1,626.99 | A$207.23 |
| 864925616 (launched **18 Aug**, sixteen days AFTER) | 2,163 | A$443.44 | A$205.01 |
| **pooled - what the note prints** | **10,014** | A$2,070.43 | **A$206.75** |

The two CPMs land within A$2 of each other, so the pooled figure is not misleading. **The SENTENCE
is what had to change**: it now says the line *"spans"* a narrowing rather than asserting the line's
audience was narrowed, because only one of its ad sets was and the other did not exist yet. Shipped
with the wrong wording on 2026-09-18 and corrected the same day - if a footnote quotes figures, the
grain of the prose and the grain of the figures have to match.

**AND ONE AD SET IS ATTRIBUTED TO TWO MARKETS AT ONCE. NOT FIXABLE HERE.**
`864925616` is named `2463_SE_Industrial Edge Wave3_AWR_NZ_image` but **delivers to Australia** -
verified, not inferred, from LinkedIn's `member_country` pivot (a metric pivot, so retrospective):

- **864925616: Australia 2,014 imps (98.2%), New Zealand 36 (1.8%), all 8 clicks Australian.**
  Region detail: Greater Sydney 493 / Melbourne 472 / Perth 439 / Brisbane 316 / Adelaide 93 against
  Auckland 16 / Hamilton 5 / Christchurch 4. 94.8% of its impressions are classified.
- **Controls confirm the field discriminates** (this is what makes the test worth anything): the two
  genuine NZ ad sets, 859158326 and 865104866, return **New Zealand and nothing else**.
- Its current `targeting_include_locations` is the same geo URN all three AU-named ad sets use, while
  the real NZ ad sets use a different one - but that field is current-state, which is exactly why the
  `member_country` measurement was needed before raising it with the agency.

`01_stg_linkedin` resolves market from the ad set NAME. It already defers a COARSE token (`ANZ`) to
the ad set's current country by ID, which is why 859128356 correctly reads Australia despite an ANZ
name - but 864925616's name is SPECIFIC (`_NZ_`), so no deferral happens and the wrong name is
trusted. The repo's own rule, applied to coarse tokens and not to specific ones.

**Consequence: A$443.44 sits inside the client-facing AU-awareness CPM above AND inside the
dashboard's New Zealand market spend** (13.3% of the brief's reported NZ spend: A$3,341.03 reported
vs A$2,897.59 if that ad set is AU). One ad set, two contradictory attributions, both on screen.
**Do NOT "fix" this with a market override or an alias map** - that hides a real trafficking error,
the same trap `client_geocon` records for its GATEWAY-BRADDON-named Northbourne creatives. It needs
the ad set RENAMED or RE-GEOED at source. Until then the inconsistency is documented, not patched.

**Still open, and worth one narrow question:** which control was moved on 02-08 (a targeting edit,
audience expansion being disabled, or a TAL swap). The 18 `targeting_include_*` /
`targeting_exclude_*` fields Windsor exposes are **current-state only** - identical on every July
date - so nothing available to us adjudicates. Also open and NOT resolvable: whether July's
demographic profile reflects targeting or off-platform audience characteristics, since the API will
not cross `placement_name` with the `member_*` pivots.

## Media-plan pacing: WIRED AND DORMANT (2026-09-18)

The whole chain exists and carries real targets. **The dashboard shows nothing**, because the global
switch is off. This is the `client_hireright` pattern - pacing wired end to end with `has_targets`
false so the UI hides the section rather than drawing 0/0 cards - and it is deliberate, not
half-finished work.

    targets/media_plan.csv  ->  load_media_plan.py  ->  seed_media_plan
                            ->  job/main.py  ->  campaigns[].plan + campaigns[].has_targets
                            ->  (dashboard render: NOT BUILT YET)

**Why it is dark.** The impression targets are OURS, not the client's. They are the client's own
cost and CPM figures divided correctly - 10x above what their sheet prints, because column I used
`cost/CPM*100` where the stated formula is `*1000`. Publishing pacing against 859,999 while the plan
document in their inbox says 85,999 would put the dashboard in conflict with the client's own
paperwork, on the very brief that error was found in. **Flip it when the client reissues the sheet or
confirms the corrected figures in writing** - that is one word in `job/main.py` plus a forced run.

**Verified on load (the seed loader prints this every run):**

| | |
|---|---|
| committed budget | **A$52,150** - ties EXACTLY to the plan's own stated Overall Budget |
| measurable budget | **A$29,150** |
| excluded | Direct IT A$23,000 |
| impression target | **859,999** (610,000 + 93,333 + 73,333 + 83,333) |
| flight | 2026-07-01 -> **2026-11-30** |

That committed figure tying to the client's stated total is the strongest single check that cost and
CPM are the trustworthy inputs and impressions are the derived output.

**TARGETS ARE PER BRIEF, and that is the point.** Only ind_edge has a plan. `campaigns[].plan` is
None and `campaigns[].has_targets` false for ent_it (1958) and software_first (2305), so the
dashboard must hide pacing for those rather than draw a zero target - the `client_schneider` lesson
where a lead-gen-shaped card printed "0 / 0 leads" at 0% over an awareness play. **The render must
require BOTH the global `has_targets` AND the brief's own.** And decide what a MIXED selection does
before building it: ind_edge + ent_it selected together is one brief with targets and one without, so
render for the brief that has them and say so - never sum, never hide.

**TWO BUDGETS, and the UI must NAME which one the bar is drawn against.** `committed_budget` is every
line the client signed; `measurable_budget` is only the lines that can report delivery.
`pace_basis: "measurable"` says which was used and `excluded[]` names what was left out with a
reason, so a reader is never left guessing which of two figures the bar refers to.

**Direct IT is A$23,000 of A$52,150 - 44% - and reaches no ad server.** An offline lead vendor
(40 HQLs @ A$575 CPL) with no media delivery in any warehouse. Pacing on the committed figure would
publish a permanent 44% shortfall no delivery could ever close (the repo-wide "pace against the
budget that can actually spend" rule). It is carried with `measurable=0` rather than deleted, because
the committed total is what the client recognises and dropping the row would make our budget disagree
with their plan. **`measurable` is a CSV column, not code**, so a new non-reporting line needs no
deploy.

**REACH, CLICKS AND CTR ARE DELIBERATELY NOT SEEDED.** The sheet derives them from the impression
column, so they inherited the same 10x error and no corrected values have been confirmed. A missing
target hides its card; a wrong one paces against a number nobody agreed to. Add them only when the
client states them.

**`seed_media_plan` is NOT in `GATING_TABLES`** - the freshness gate deliberately does not watch seed
tables, so a plan edit needs `FORCE_REBUILD=1`. And the seed read carries **no tolerant
try/except**: a swallowed exception around one stage of the 3-stage name-matched contract turns a
rename into silence (`client_geocon` published `0 CRM leads` against a view holding 9,779 exactly
that way). If the table goes missing this job should fail loudly.

**Deploy order when you light it up:** `load_media_plan.py` FIRST, then the job, then the dash.

**Still to build:** `paceBar()` / `renderPacing()` ported from `client_schneiderlqai`, and
`dash/report.py`'s guardrail re-templated - it currently forbids ALL target and pacing language on
the basis that no plan exists, which stops being true for ind_edge the moment the switch flips. That
guardrail must go per-brief too, or the deck will narrate targets for the two briefs that have none.

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
  targets: flight **2026-07-01 -> 11-30**, budget **A$52,150**, and per-line targets.
  **THE SHEET'S OWN IMPRESSION COLUMN IS 10x LOW AND MUST NOT BE SEEDED AS PRINTED (confirmed with
  the client, 2026-09-18).** Column I on rows 14-17 was calculated as `cost / CPM * 100` where the
  intended formula is `cost / CPM * 1000` - the client stated that formula herself, and all four
  lines reproduce to the decimal under the x100 form, so it is one bad cell copied down rather than
  four typos. **Cost and CPM are correct** (they tie to the stated A$52,150 once the Direct IT line
  is added), so cost and CPM are the trustworthy inputs and impressions are a derived OUTPUT; REACH
  and CLICKS in the sheet are themselves derived from impressions and inherit the same error. Seed
  the CORRECTED figures: Awareness/Programmatic **610,000** imps @ A$9,150 (CPM A$15) ·
  Awareness/LinkedIn **93,333** @ A$7,000 (CPM A$75) · Consideration/LinkedIn **73,333** @
  A$5,500 · Conversion/LinkedIn lead-gen **83,333** @ A$7,500 - so **859,999 planned
  impressions**, not 85,999. Seeding the sheet as printed would report Industrial Edge **10x better
  than it is running** - the whole difference between a campaign that looks finished and one about a
  third of the way through. **Quote the RATIO, not a percentage**: at 2026-09-18 its 304,087
  delivered impressions read as **354%** of the printed target and **35%** of the corrected one, and
  both of those move every day while the 10x does not. (An earlier draft of this README froze
  "337% vs 34%" from a 290,416-impression snapshot; it was stale within days.) **The flight END is 2026-11-30** (client,
  2026-09-18) - the sheet contradicts itself, row 6 reading 31-Oct while rows 14-17 read
  1 July - 30 Nov, and the client confirmed the line items. ·
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
