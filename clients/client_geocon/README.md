# client_geocon — Northbourne Gateway (multi-channel paid media)

Self-hosted paid-media dashboard for **Geocon's residential launches**, one development at a time
via the top-nav selector. Two developments exist in the pipeline; **only one is on the dashboard**:

| Development | Channels | Budget | Flight | State |
|---|---|---|---|---|
| **Northbourne Gateway** (558 apartments) | Meta / LinkedIn / Trade Desk / Google Ads (+ SEO) | **A$205,600** | 2026-08-13 -> 10-31 | **LIVE since 2026-08-28**; Meta + Trade Desk + Google Ads delivering |
| ~~Gateway Braddon~~ | Meta only | A$7,500 | 2026-06-21 -> 07-20 | **HIDDEN from the dashboard 2026-09-03** (client request; flight ended). Still built end to end and still in `geocon.json` - see "Hiding a finished development" |

**TWO CLIENT DECISIONS SHAPE WHAT THIS DASHBOARD SHOWS TODAY, and both are one-line reversals:**
- **Enquiries and cost-per-enquiry are WITHHELD** pending a Salesforce/CRM connection -
  `LEADS_REPORTABLE = false`. See "Enquiry reporting is paused".
- **Gateway Braddon is hidden** - `HIDDEN_PROPERTIES`. See "Hiding a finished development".

**Gateway Braddon is unchanged** by the 2026-08-24 multi-channel rebuild - verified as a strict
no-op, see "The multi-channel rebuild" below. No Snowflake / Salesforce / Content-Syndication lane
here.

## Multiple developments — the `property` selector (added 2026-08-12)

This dashboard covers a CLIENT (Geocon), not a single development. Both are live today: **Gateway
Braddon** (Meta lead-gen, flight ended 2026-07-20) and **Northbourne Gateway** (Trade Desk
awareness, in market). **Northbourne is now the DEFAULT landing development** - `initProperty()`
picks the first live-and-delivering entry in seed order and Northbourne is `seq 1`. That is the
current campaign, so it is the right landing view, but it IS a change from the Braddon-first default
the dashboard had until 2026-08-28.

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

### Northbourne Gateway - the state of play (LIVE 2026-08-28)

**It was deliberately COMING SOON until 2026-08-28, when it was switched live on request** with one
of its nine plan lines in market. The development is 558 apartments on a A$205,600 plan, flight
2026-08-13 -> 10-31, buying Meta, LinkedIn, Trade Desk and Google Ads (plus an SEO retainer, which
has no ad server and is therefore never a dashboard platform).

What is on screen today is the **Trade Desk High Impact** line (plan seq 1, A$40,000): 737,352
impressions / 637 clicks / A$3,848.90 over 2026-08-20 -> 08-26, reconciling exactly to `fact_all`.
The other eight lines have not started, which the page says in three places rather than leaving the
reader to infer it from a low bar - a "1 of 9 plan lines in market" pill on the pacing card, a
"Media-plan lines live" KPI carrying the A$40,000-of-A$188,500 split, and a "Plan lines in market"
insight card. **That context is load-bearing:** pacing runs against the whole A$188,500 measurable
budget from day one, so a launch performing exactly to plan still reads *Under pace* at 2% of budget
on day 15 of 80.

**Pacing runs against the budget that is IN MARKET, not the whole plan (2026-08-28).** A nine-line
plan with one line running paced its A$3,849 against the full A$188,500 and read 11% of pace on a
line performing to plan - the eight lines waiting on creative and approvals were being counted as a
shortfall against the one that launched. `job/main.py::_flight` now sums the budget of the plan
lines that have actually DELIVERED inside the flight (delivery-derived, never the plan's own dates,
and measured on the unfiltered fact so a platform chip cannot move it) and paces on that:
A$40,000, A$500/day, expected A$7,500 at day 15. It grows on its own as lines launch and needs no
edit. `budget_in_market` / `budget_measurable` / `budget_committed` all ship beside it, the pacing
card names which one the bar is drawn against, and a development with no seeded plan (Gateway
Braddon) is untouched - `pace_basis` is `flight` and it paces on its measurable budget exactly as
before.

**The projection follows the DELIVERING window when a line started late.** Northbourne's flight
opened 08-13 and its line began 08-20; averaging spend over the seven dead days projected A$20.5k
of a A$40k line that is in fact running slightly ABOVE plan rate. It now projects A$35,121 (88%).
A projection that contradicts the campaign's own run-rate is worse than none - it argues for topping
up a line that needs nothing.

**The switch is still a one-word CSV edit, in both directions.** `status` in `targets/property_map.csv`:

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

No code change, no deploy - and it reverts the same way. **This is deliberately NOT automatic** -
it used to be (a development switched itself on the moment its first row landed), and the decision
to publish a one-line view of a nine-line plan should be a person's, which is exactly what happened
here.

### Enquiry reporting is paused (2026-09-03, client instruction)

**The client asked for no enquiry count and no cost per enquiry until Salesforce is connected.**
What the platforms hand us is a Meta lead-FORM submit count with nothing behind it, and the tile
stacked on top of it - `Qualified leads (modelled)` - was that count x an assumed 20% qualification
rate. Two figures a reader can reasonably take for pipeline when neither has been near a CRM.

**One flag does it, because the page already knew how to be an awareness dashboard.** Awareness mode
(next section) was built in August for Northbourne's Trade Desk lane, which has no lead form. So the
withheld state re-uses that exact code path rather than adding a second, half-stripped one:

```js
const LEADS_REPORTABLE = false;                       // dash/dashboard.html - the ONE knob
const leadsMeasured = () => reports('leads') || bench('lead_target') != null;
const leadsWithheld = () => !LEADS_REPORTABLE && leadsMeasured();   // measured, not reported
const leadShaped    = () =>  LEADS_REPORTABLE && leadsMeasured();   // render the lead surfaces?
```

What comes off, all together, from that one flag: the enquiry / CPL / modelled-qualified KPI tiles
(the band swaps to Impressions / CPM / Clicks / Spend), the enquiry and qualified funnel steps, the
`On track to goal?` chart, the efficiency map, the CPL trend, the day-of-week card, budget burn, the
enquiry-type split, and every `.c-lead` column in the stage / platform / benchmark / ad tables.

**`leadsWithheld()` exists because the COPY has to tell the truth.** Awareness mode says *"no lead
form, so there is no enquiry to report"* - true of Trade Desk, and plainly FALSE here: Meta is
running a lead-form line (plan line 9, A$90,000) and reporting enquiries. That sentence would have
been the one line on the page a client could catch us out on, so the withheld state gets its own
wording in `renderNote()` and `introCopy` - *"enquiry reporting is paused while the CRM connection
is being built"*. **This is the only place the dashboard says anything about it** (4 mentions in the
how-to-read note, 1 in the intro). Nothing else on the page uses the words enquiry, lead or CPL -
asserted by the render check below.

**It reaches the surfaces that outlive the page, too**, because a client-facing number is not only
what is on screen:
- **CSV exports** (`exportAllData`, `exportThisTab`) drop the lead columns - otherwise the file
  hands back the exact figure the page withholds, with no caption explaining it.
- **The AI deck** (`buildReportPayload`) DELETES the lead keys rather than sending them with an
  instruction not to use them. A model handed `leads: 56` and `cpl: 201.52` will write a headline
  about them however firmly the prompt says not to: the prompt is a request, an absent key is a
  fact. `report.py` then builds a reach-and-delivery brief (`leads_reported: false`), and
  `_scope_directive()` appends an authoritative block to BOTH system prompts, both providers -
  which is also where the stale *"single-engine Meta account for Gateway Braddon"* wording in those
  static prompts gets corrected with the payload's real channel list.
- **The GA4 `Website enquiries` tile** is gated on the same flag, or the number removed from every
  paid surface would reappear on the tab next door under a different heading.

**Turning it back on is `LEADS_REPORTABLE = true` and a dash deploy.** Nothing upstream changed:
`sql/*`, `job/main.py` and `geocon.json` still carry `leads` in full, so there is no re-seed and no
forced export, and no history is lost in the meantime.

**Follow-up not done here:** `report.py`'s two static system prompts still read as a single-engine
Meta lead-gen template for Gateway Braddon. `_scope_directive()` overrides the wrong parts at
runtime, but the prompts themselves want a proper multi-channel re-template.

### Hiding a finished development (2026-09-03, client request)

The client asked to see the live launch only. Gateway Braddon's flight ended 2026-07-20; a finished
campaign never moves again, so every visit after this one would have opened on a choice between the
live work and an archive.

```js
const HIDDEN_PROPERTIES = new Set(['Gateway Braddon']);   // dash/dashboard.html
```

**There is no second edit for the dropdown.** `initProperty()` renders the selector only for two or
more developments, so removing one leaves a single development and the control hides itself. That is
what the client meant by "make it one tab".

**It is applied at the ROOT, once, in `load()` before anything reads `DATA`** -
`dropHiddenProperties()` filters `DATA.properties`, `DATA.rows` and `DATA.breakdowns`, then REBUILDS
`meta.date_min` / `date_max` from what survives. Filtering only the selector would have left its 291
rows in `DATA.rows`, and **the date picker is built from `meta.date_min`**: Gateway Braddon delivered
from 2026-05-05 and Northbourne from 2026-08-20, so "All time" would have opened on three empty
months of lead-in on every chart.

**GA4 is deliberately NOT filtered.** The Website tab's site figures are whole-site and say so on
screen; dropping rows by `property` would quietly turn a whole-site number into a campaign-scoped one
under a caption still promising the whole site. Its one development-scoped card already filters
itself.

**Two things the shorter window then exposed, both fixed here:**
- **The date picker read "Last 14 days" while showing everything.** Every relative preset is clamped
  to `[MIN,MAX]`, so on a 13-day dataset one of them coincides with the whole window and won by
  position (`all` is last in `PRESETS`, because that is where it belongs in the menu). `detectPreset`
  now tests `all` FIRST. A control claiming a filter that is not applied is worse than no label, and
  it would have flipped to "Last 28 days" and on as the flight grew.
- **The trend chart defaulted to WEEK grain over 13 days** - three buckets, two of them part-weeks,
  so the lines dived toward zero at both ends and read as a campaign collapsing when nothing had
  happened but the calendar. `syncGrainDefault()` now picks the opening grain from the window
  length (<=35 days -> day, <=400 -> week, else month). It sets the starting position only; the
  VIEW BY toggle is untouched.

**Elsewhere the same change corrected three first-client string literals** (the repo-wide "grep for
the first client's name before shipping a second lane" rule): the browser tab title, the AI deck's
`client` / `brand` / `filePrefix` (a Northbourne deck carried a GATEWAY BRADDON cover and filename),
and the login page's development list in `dash/main.py`.

**KNOWN DATA-QUALITY ISSUE, NOT FIXED HERE AND NOT OURS TO FIX IN CODE:** 100% of Northbourne's Meta
delivery (A$11,283 / 424,313 impressions at 2026-09-01) sits under correctly-named campaigns
(`0201_GG_..._Northboune Gateway_..._CNV`) whose ADS are named `GateWayBraddon_<market>_Statics` -
the old development's naming convention applied to the new campaign's ads. The property tagging is
right (the campaign name wins), but the creative gallery, the top-creative insight and the ad table
all print "GateWayBraddon" on a dashboard that has just had Gateway Braddon removed from it. **The
fix is a rename in Meta by whoever traffics these ads**; aliasing it in the UI would hide a real
naming error rather than correct it.

**Restoring the development** is emptying the Set and redeploying the dash. No re-seed, no forced
export - `geocon.json` still carries it in full.

### Verifying a change like this

Both changes are pure frontend, so they are verifiable in a real browser before deploying: serve
`dash/` over a tiny Node server answering `/data.json` with the real payload from
`gs://bidbrain-analytics-geocon-dash/geocon.json`, append a probe script to a COPY of
`dashboard.html`, and dump the DOM with headless Edge. The 2026-09-03 change was signed off on 16
assertions against that dump - among them: zero occurrences of "Gateway Braddon", "CPL" or "lead" in
`body.innerText`; the property selector `display:none`; `date_min` 2026-08-20; no `Leads`/`CPL`
header in any of the four tables; no lead key in the deck payload; and `scrollWidth - clientWidth`
equal to 0.

### Awareness mode - a development renders what it MEASURES (2026-08-28)

Switching Northbourne live exposed that this dashboard was built entirely around Meta lead-gen.
Gateway Braddon reports enquiries, landing-page views, reach and frequency; **Trade Desk reports
none of the four**. Rendered unchanged, the Northbourne tab would have shown a funnel dead-ending at
0, an "on track to goal?" chart against no goal, a CPL column of dashes, empty Meta audience and
placement charts, and - the worst of them - every Trade Desk creative watermarked **GATEWAY
BRADDON** (two hardcoded literals in `renderCreative` / `openCreative`; the CDN-expiry path
`ccFallback()` had always used the selected development).

So the page now derives what to render from what the development's platforms actually report:

```js
const reports = f => ROWS().some(r => r[f] != null);   // is this measured at all?
const hasAny  = f => ROWS().some(r => n(r[f])  > 0);   // measured, and non-zero
const leadShaped = () => reports('leads') || bench('lead_target') != null;
```

**The test is NULLNESS, not magnitude, and the staging views are what make that work.**
`sql/08_stg_ttd` sets `leads` / `reach` / `landing_page_views` to `CAST(NULL AS INT64)` with the
comment "no lead form, not zero starts". A metric a platform does not report is NULL; a metric it
reports as zero is 0. `hasAny` is the second test, for a feed that sends a column it cannot fill -
Trade Desk returns video columns on a display buy, all zeros, and a video chart of zero bars reads
as a failed campaign rather than an absent format.

`renderMeasureScope()` applies the decision in one place, before every other renderer:

| What is missing | What the page does |
|---|---|
| leads | Hides the goal chart, efficiency map, CPL trend, day-of-week and budget-burn cards; drops the Leads / CPL columns from all four tables; swaps the KPI band, hero trend, funnel, goal bars, insights, creative metrics and the ad table's *Read* verdict to their awareness form |
| reach | Hides reach & frequency + creative fatigue; drops the Freq. column |
| landing-page views | Drops the LPV / Cost-per-LPV columns and the LP-views funnel step |
| video (all-zero) | Hides the video card |
| Meta breakdowns | Hides the whole "Who & where we reached" section |

Column hiding is CSS (`body.no-leads .c-lead{display:none}`), set once from `renderMeasureScope()`,
so every table follows one decision. Hidden cards collapse their `.grid` row via `syncGrids()` - a
fixed `1fr 1fr` track would otherwise leave a 50% hole.

**Awareness mode is not a Northbourne special case.** Adding a platform needs nothing here: the
panels it can feed appear the day it delivers, the ones it cannot stay hidden, and Northbourne
becomes lead-shaped on its own the moment the Meta line (seq 9, A$90,000) starts reporting leads.

**Verified a strict no-op on Gateway Braddon** - rendered headless before and after against the real
payload: its `<body>` carries no measure classes, all twelve gateable cards stay shown, the funnel
keeps all five steps, and the KPI band still reads "Meta enquiries 176 / CPL A$91 / Qualified 35 /
A$16,076".

**The PLAN side is no longer grossed by the billed multiplier (2026-08-31).** `bbApplySpendMult`
grossed `budget` and `pace_expected` along with the actuals. That preserved the pacing RATIO - both
sides moved together - while printing a budget that matches nothing: Northbourne's **A$142,000** of
in-market lines displayed as **A$220,421**, the blended delivery-mix factor applied to a plan figure.
The media plan is what the client signed and pays; it is ALREADY the client-billed number, so
grossing it bills them twice on paper. **CONFIRMED by the client 2026-08-31: the plan's A$205,600 is
the BILLED figure**, so billed-spend-vs-plan is the correct comparison and the pacing card is right
as it stands. Only `spend_to_date` and `projected_spend` are grossed now -
billed spend against the signed billed budget. **This moves the displayed pacing % wherever a
multiplier is set:** Gateway Braddon's flight now reads against its true signed A$7,500 rather than a
doubled A$15,000. A ratio that is right for a reason nobody can reconstruct from the numbers on
screen is not right.

**The client-billed multiplier was channel-blind, and missed pacing entirely (fixed 2026-08-28).**
Two bugs in `bbApplySpendMult`, both introduced by the multi-channel rebuild rather than by any one
change:

1. **It read a single `meta` factor and applied it to every row.** Correct while geocon was
   Meta-only; silently wrong from the day Trade Desk landed. The registry entry is `{meta: 2.0}` and
   nothing else, so **every Trade Desk row was grossed by META's billed rate** - A$550.21 of real
   25-Aug delivery reported as A$1,100, while impressions and clicks stayed raw. That asymmetry is
   the tell: a doubled *dataset* doubles the counts too, a doubled *rate* only moves the money. It
   now grosses per row by that row's own channel (`BB_CHAN_KEY` -> the platform's `SPEND_CHANNELS`
   vocabulary), so an undefined channel stays at 1 = raw.
2. **It grossed only the legacy top-level `DATA.flight`.** `flight()` has read `propDef().flight`
   since the multi-development rebuild, so **every pacing figure was raw while every KPI beside it
   was billed** - on Gateway Braddon the KPI band read A$32,151 and the pacing bar A$3,694, on one
   screen. It now grosses `properties[].flight` too, by that development's own blended
   grossed-over-raw rate across its rows inside its flight window (the same clamp the job used).

Whether the Trade Desk line should carry a billed markup at all is a COMMERCIAL decision, not a code
one: add `ttd` in the super-admin Multiplier panel and it applies with no deploy. Note also that the
shim grosses `budget` and `pace_expected` as well as spend, so Gateway Braddon's signed A$7,500
displays as A$15,000 through the platform. The pacing *ratio* is right either way (both sides
grossed), but if the signed plan figure is already the client-billed number then the plan side
should not be grossed - unresolved, flagged rather than changed.

#### Google Ads is a PLATFORM, not a tab (settled 2026-08-31)

A Google Ads **tab** was built on 2026-08-31 and **removed the same day** on the client's
clarification: Google Ads belongs in the shared multi-platform surfaces, and the tab the boss wanted
is **Google Analytics** (see below). Nothing about the Google Ads data path changed - it is in
`PM_CHANS`, `sql/09_stg_google_ads` -> `10_fact_all`, the platform chips, the `Performance by
platform` table and the per-row billed multiplier - so it appears on its own the day the three
campaigns are un-paused. The conversions surface (KPI tile + `Conv.` / `Cost/conv` columns) stays and
is what carries the search lines' outcome.

What the removed tab did that the shared tables still cannot: split **Search from Video**. The plan
buys Google Ads as two different things - a YouTube reach line and two search conversion lines -
whose click-through rates are an order of magnitude apart, so any blended Google Ads CTR describes
neither. If that split is wanted later it belongs as a section on Paid Media rather than a tab, and
the removed implementation is in the git history for 2026-08-31.

**Google Analytics: BLOCKED on a grant.** There is no Geocon GA4 property in either source - not in
the DTS export (`ingest/dts_data_pull/create_views.py` -> `PROPERTY_NAMES`, 20 properties, none
Geocon) and not in `raw_windsor.perf_ga4`. Standing it up needs, in order: Geocon grants our service
account Viewer on the property; the numeric property id goes into `PROPERTY_NAMES`; its DTS transfer
is created in the console; then views + job + tab. Same path `client_schneider` documents for
Schneider Electric, whose placeholder is still commented out in that same map.

**The Website tab shows NO enquiry figure while the site tracking is unverified (2026-09-01).**
GA4 reports 63 `form_start` events on the Gateway Braddon site and **no `form_submit` at all**.
`form_submit` is GA4 **enhanced measurement**, which does not fire on a form that submits by AJAX,
calls `preventDefault()`, or sits in an **iframe** - which is how most property enquiry forms are
embedded - so this is far more likely a tracking gap than a failing form. Any figure there, `0` or a
dash, invites a conclusion the data cannot support, so the KPI is **omitted entirely** and returns on
its own the moment either a GA4 **key event** is configured on the property or a real `form_submit`
arrives. No edit needed when that happens.

**It is NOT our pipeline, and that was checked before saying so:** `form_start` flows normally, and
one `form_submit` DOES come through on the other property - a pipeline that carried a count of 1 is
not truncating or filtering. The absence is a fact about the source data.

**Related, and also not a dashboard fault:** Northbourne's Meta ads carry **Gateway Braddon's ad
copy** ("Gateway Braddon balances the energy of Braddon...") under campaign
`0201_GG_ACT Northboune Gateway_statics_CNV`. The campaign name is unambiguously Northbourne and the
property map resolves it correctly; that body text is what Meta returns for the ad. A
creative-trafficking question for the agency - but it reads like a scoping bug, so it is recorded here.

**Google Ads conversions now have a surface (2026-08-28).** `conversions` and
`view_through_conversions` have flowed `sql/09_stg_google_ads` -> `10_fact_all` -> `job/main.py` ->
the payload since 2026-08-24, and **nothing rendered them** - so the day the A$16,500 "Canberra
Investors" search line starts, the conversions that are the whole point of a conversion buy would
have landed invisible. There is now a `Conversions` KPI tile and a `Conv. / Cost per conv` pair on
the platform table, both gated on `hasConversions()` (any non-NULL `conversions` row) so they stay
hidden until Google Ads delivers - a strict no-op on today's Trade-Desk-only payload.

Three rules it encodes:
- **A conversion is never a lead.** `hasConversions()` is deliberately NOT part of `leadShaped()`:
  a development delivering search conversions with no lead form must not flip the page into its
  lead-gen shape and start drawing an enquiry funnel. The tile names the reporting platform
  ("Google Ads-reported") for the same reason - a Google conversion and a Meta lead form can be the
  same human enquiring twice, so they must never read as one number a client could add up.
- **Cost per conversion divides by the spend of the channels that REPORT conversions**, not by all
  spend. Blended, Trade Desk's awareness dollars land in the numerator and make search look worse:
  on a mixed set that read **A$302** against Google Ads' true **A$88**. A rate needs a numerator and
  a denominator describing the same rows.
- **Trade Desk shows `-`, not 0**, in the conversions column - the awareness-mode nullness rule.

Two smaller fixes came with it, both general:

- **CTR precision follows the number** (`pctr()`). At a fixed 1dp, programmatic display CTR printed
  `0.1%` for every creative, every campaign AND the target - so the vs-target column read
  "0.1% vs 0.1%" with a `+8%` delta between two identical-looking numbers, and the best and worst
  creative on the page were indistinguishable. Under 1% it now shows three decimals
  (`0.086% vs 0.080%`); a Meta CTR of 1.4% is untouched.
- **DERIVED targets are labelled** `(derived)`, the caltex rule. Northbourne's CPM and CPC targets
  are implied by the plan's budget / impressions / clicks, not committed by it, so an unlabelled red
  delta would accuse the campaign of missing a KPI nobody agreed to.

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

#### Go-live blockers - three, and none of them are code

| Blocker | Detail |
|---|---|
| **Trade Desk** | **RESOLVED, LIVE and ON THE DASHBOARD.** Advertiser `Geocon Group` is granted on the shared Windsor seat. The **High Impact** line (plan seq 1) has delivered since **2026-08-20**: 71 rows, **A$3,848.90 / 737,352 imps / 637 clicks** at 2026-08-26, resolving to `property = Northbourne Gateway` and `plan_line = High Impact` with zero Unmapped. Published to the Northbourne tab on **2026-08-28** (see "Awareness mode"). **Retargeting (seq 7) and Lookalike (seq 8), A$12,000 each, have not started.** |
| **Meta** | **Feed RESOLVED, campaigns not built.** The Windsor Meta grant was re-authed 2026-08-25 and Gateway Braddon is current to 08-25, so the pipe is healthy - but the ad account holds **no Northbourne campaign at all** yet. The A$90,000 `Leads` line (seq 9) is waiting on campaign build, not on a grant. Its plan row has a NULL `match_pattern` **by design** - it is the Meta channel catch-all, and Meta has exactly one line. |
| **Google Ads** | **Wired, PAUSED.** All three campaigns exist and are correctly named; they flow the moment they are un-paused. Nothing is needed from us. |
| **LinkedIn** | **STILL BLOCKED - the only outstanding grant.** The connector carries APJC / STT / Cloudflare / Schneider / PropTrack / HireRight / ResetData and nothing else; there is no Geocon account on it. `sql/07_stg_linkedin.sql` is written and returns zero rows. A$6,000 (seq 4). |

**Do not re-read the old "A$64,000 Trade Desk blocker" line anywhere - it is dead.** That grant landed
with the estate-wide Trade Desk re-auth on 2026-08-25, which also issued a NEW seat id (484 -> 569).

#### The Meta scope: `GG_` is the prefix Northbourne actually uses (FIXED 2026-08-31)

**The 2026-08-27 fix below was necessary but NOT sufficient, and it certified itself green.** It
stripped a leading `^[0-9]+_` and re-tested `Geocon_`, which is right for Trade Desk and Google Ads
(`0201_Geocon_NGW558_*`). **Meta does not use that naming.** Its campaigns are
`0201_GG_ACT Northboune Gateway_statics_CNV` - brief number, then **GG** for Geocon Group. Strip the
number and you get `GG_ACT ...`, which still fails `STARTS_WITH('Geocon_')`.

So 100% of Northbourne's Meta delivery was still being dropped: **220,812 impressions, 3,997 clicks,
A$6,328.65 and 29 enquiries across 6 live campaigns**, on the plan's LARGEST line (seq 9, A$90,000).

**The tell was in the sign-off.** That fix was verified as *"a strict no-op: 285 rows under both
predicates, 0 newly admitted campaigns"* - and a no-op is exactly what a scope fix that admits
nothing looks like. **When a scope change is meant to ADMIT rows, "no change" is a FAILURE, not a
pass.** Assert the new names are in; never only that the old ones still are.

Both gates now accept `Geocon_` OR `GG_` after the brief number is stripped:

| File | Predicate |
|---|---|
| `sql/01_stg_meta.sql` | `REGEXP_CONTAINS(REGEXP_REPLACE(TRIM(campaign_name), r'^[0-9]+_', ''), r'^(Geocon_\|GG_)')` |
| `ingest/meta_breakdown_pull.py` | `_GEOCON_CAMPAIGN = re.compile(r"^\s*(?:[0-9]+_)?(?:Geocon_\|GG_)")` |

**Re-pulled 2026-08-31, so Northbourne's audience + placement charts are live** (462 age/gender and
377 placement rows in range; 25-34 male is its largest band, and Feed / FB Reels overlay are neck
and neck at ~99k impressions each). Two things to know before running it again:

- **`bq load --replace` rewrites the WHOLE table, so always pull the FULL range**, not just the new
  development's window. Pulling only 2026-08-24 onward would have silently deleted Gateway Braddon's
  entire breakdown history. Baseline the row count first and confirm the new file is a superset.
- **Windsor returns each campaign's CURRENT name for every historical date.** `Geocon_Leads_MayJune2026`
  came back as `Geocon_Leads_MayJuneJulyAugust2026` - the same campaign, renamed in Meta. Nothing is
  lost (the property map resolves both to Gateway Braddon), but a name-keyed diff against the old
  table will look like one campaign vanished and another appeared. The repo-wide "campaign names are
  not stable keys" rule, in its reporting form.

```powershell
# the full range, every time - see above
$env:WINDSOR_API_KEY = (gcloud secrets versions access latest --secret=windsor-api-key)
.\.venv\Scripts\python.exe clients\client_geocon\ingest\meta_breakdown_pull.py 2026-05-01 <today> out.ndjson
bq load --replace --source_format=NEWLINE_DELIMITED_JSON raw_windsor.geocon_meta_breakdown out.ndjson `
  date:DATE,campaign:STRING,breakdown:STRING,seg1:STRING,seg2:STRING,impressions:INTEGER,reach:INTEGER,clicks:INTEGER,link_clicks:INTEGER,spend:FLOAT,leads:INTEGER
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

`Cairns Awareness` - another client on the same shared ad account - matches neither, so the split
still holds and the property map's catch-all `ELSE` stays safe. **Gateway Braddon is byte-identical**
(288 rows / 1,105,062 imps / A$16,275.14 / 178 leads before and after).

Two related traps this exposed:
- **The campaign names misspell the development** - "Northboune", no `r`. The property map matched
  them only through the `0201_` token; `Northboune` has been added so a rename that drops the brief
  number cannot silently reroute them to Gateway Braddon.
- **Northbourne is now LEAD-SHAPED**, so the dashboard leaves awareness mode on its own and the full
  enquiry funnel, CPL, goal and audience surfaces come back. That transition needed no code - it is
  what `leadShaped()` was built for.

#### The earlier, insufficient fix (2026-08-27) - kept for the reasoning

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

## Website analytics (GA4) — the Website tab (2026-08-31)

Google Analytics is CONNECTED. Two Geocon GA4 properties were connected to the Windsor connector
in late August 2026 (both are brand-new — that is the full history, not a gap):

| GA4 property | name in GA4 | what it actually is |
|---|---|---|
| `550962241` | GEOCON | the geocon.com.au brand site (organic/direct traffic) |
| `551838402` | Gatewaybraddon | the campaign LANDING site — carries almost exclusively **Northbourne Gateway** campaign traffic (verified 2026-08-31: 3,767 of its first 3,975 sessions arrive from `0201_*` campaigns) |

**The property names do not name the development the traffic belongs to** — so `sql/11_stg_ga4`
resolves the DEVELOPMENT from the GA4 **session campaign name** via the same `seed_property_map`
tokens every delivery view uses, and the on-screen site figures stay whole-site and say so. Events
(`sql/12_stg_ga4_events`) carry no campaign dimension, so they are site-level only. **Web enquiry
tracking is thin**: the sites record `form_start` but no form-submit key event is configured in
GA4 — worth asking the client for one; until then nothing on the Website tab is an enquiry count.

Pipe: `windsor-ga4-ingest` (scheduled 21:25 UTC daily, `scripts/deploy_ingest_jobs.ps1`) runs both
GA4 loaders **pinned to these two properties** via `GA4_ACCOUNTS` → `raw_windsor.perf_ga4` +
`perf_ga4_events` → views 11/12 → job `ga4` block → the **Website** tab (auto-hides on an older
JSON). GA4 **DTS transfers for both properties exist and FAIL on permissions** — they self-heal
the day the client grants `ian@100.digital` Viewer on the two properties, and the views can then
move DTS-first (the VMCH pattern) and the Windsor job can retire.

The job prints a per-site audit line each run (`ga4 <site>: N sessions, M attributed…`) — an
all-zero "attributed" figure under paid delivery means the seed tokens stopped matching the GA4
utm campaign names (the same class of break as the delivery scope, and just as silent).

### Channel connection status (verified 2026-08-31)

- **LinkedIn — still blocked on the Windsor grant.** No Geocon LinkedIn ad account exists in the
  connector (probed via the Windsor API, not the table). The socket (`sql/07`) is ready; when the
  account is connected at onboard.windsor.ai, add its id to `SELECT_ACCOUNTS` +
  `LINKEDIN_ACCOUNT_TO_CLIENT` (→ `('geocon','100-digital')`) in
  `ingest/windsor_data_pull/linkedin/linkedin_loader.py` and redeploy `windsor-linkedin-ingest`.
- **Google Ads — the live campaigns are OUTSIDE our mirror.** The three campaigns under MCC
  3451896252 (customer 5457742070) are still PAUSED with zero stats, yet GA4 records `google/cpc`
  sessions from those exact campaign names since 2026-08-27 (plus a `..._SearchNonBrand_CNV`
  name variant) — someone rebuilt/launched them in a DIFFERENT Google Ads account. Ask the
  agency/client for the delivering CID and link it under MCC 3451896252; `sql/09` then needs that
  `customer_id` added. Until then the Google Ads lane correctly shows nothing.

## Freshness

`geocon-export` is **self-gating** on a Cloud Scheduler `*/10` UTC tick (`scheduler.ps1`): each tick
cheaply probes whether any of its **six** upstream tables advanced (`__TABLES__.last_modified`
vs the `_freshness.json` watermark) and rebuilds only when one did: `raw_windsor.perf_meta`,
`raw_windsor.perf_linkedin`, `raw_windsor.perf_the_trade_desk`, `raw_windsor.perf_ga4`,
`raw_windsor.perf_ga4_events` and the Google Ads DTS base table
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
