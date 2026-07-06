# Schneider Electric Pacific Dashboard: Complete Guide

> **Purpose of this document.** A single, self-contained reference that explains what the Schneider
> Electric Pacific dashboard is, every number on it and how it is calculated, where the data comes
> from, and exactly how it lines up (or does not) with everything the client has sent us. It is
> written so that you, or the client, or a chatbot loaded with this file, can answer essentially any
> question that comes up in a review meeting.
>
> **Reporting currency:** AUD. **Built by:** 100% Digital, for the agency **Transmission**, on behalf
> of **Schneider Electric (Pacific / ANZ)**. **Live snapshot in this doc:** data through **2 July
> 2026** (the dashboard refreshes itself continuously, so live figures move; the structure does not).

---

## Table of contents
1. [What this dashboard is, in one minute](#1-what-this-dashboard-is-in-one-minute)
2. [How to open it](#2-how-to-open-it)
3. [The five programs at a glance](#3-the-five-programs-at-a-glance)
4. [Where every number comes from (data sources)](#4-where-every-number-comes-from-data-sources)
5. [How the screen is organised (filters and tabs)](#5-how-the-screen-is-organised-filters-and-tabs)
6. [Tab by tab: every card, chart and table](#6-tab-by-tab-every-card-chart-and-table)
7. [The "Download slides" AI report](#7-the-download-slides-ai-report)
8. [Definitions and formulas (glossary)](#8-definitions-and-formulas-glossary)
9. [Campaign IDs and the Salesforce mapping](#9-campaign-ids-and-the-salesforce-mapping)
10. [Does the dashboard reflect everything the client gave us?](#10-does-the-dashboard-reflect-everything-the-client-gave-us)
11. [Inventory of the client source files](#11-inventory-of-the-client-source-files)
12. [Live numbers snapshot (as of 2 July 2026)](#12-live-numbers-snapshot-as-of-2-july-2026)
13. [Frequently asked questions](#13-frequently-asked-questions)
14. [Things to say carefully in the meeting](#14-things-to-say-carefully-in-the-meeting)
15. [Technical appendix (for engineers)](#15-technical-appendix-for-engineers)

---

## 1. What this dashboard is, in one minute

Schneider Electric runs a set of **lead-generation ("content syndication") programs** in Australia and
New Zealand through the agency Transmission. Each program pays media vendors to put gated Schneider
content in front of a target account list, and the people who download that content become **leads in
Schneider's Salesforce CRM**.

This dashboard answers three questions per program:

1. **Are we hitting the lead target?** (the **Content Syndication** tab): live Salesforce leads versus
   the media-plan lead target, with pacing.
2. **What paid media delivered those leads?** (the **Paid Media** tab): the Trade Desk, LinkedIn and
   DV360 spend, impressions and clicks behind the program.
3. **How do the markets compare?** (the **CS Comparison** tab): Australia versus New Zealand side by
   side.

A fourth tab, **Other Channels**, lists media-plan lines that have no live data feed (search,
publisher sponsorships, trade press, email) so the full plan is visible even where we cannot measure
delivery automatically.

It is one web page, password protected, that reads a single data file refreshed from BigQuery. It
looks and behaves like the MongoDB dashboard (same layout family), skinned in Schneider green.

---

## 2. How to open it

- **Normal way in (recommended):** the platform front door at
  **https://dashboards.bidbrain.ai/d/schneider/**. Log in once to the platform and the Schneider
  dashboard opens with no second password.
- **Direct URL (for testing):** `https://schneider-dash-516554645957.australia-southeast1.run.app`.
  This shows a login screen and needs the dashboard password.
- **Password:** stored in Google Secret Manager (`schneider-dash-password`). The data file itself sits
  in a **private** bucket and is only served to a logged-in session, never publicly.

The dashboard is branded **"Pacific"** because a sibling Schneider dashboard for another region is
planned; this is explicitly the Pacific book of work.

---

## 3. The five programs at a glance

The dashboard is scoped to **five lead-generation programs**. You select one at a time from the
**Campaign** dropdown in the top bar; it opens on the first program. (The combined **"All campaigns"**
view was removed on 3 Jul 2026 at the client's request — the figures below are still the arithmetic
sum across the five, for reference.)

| Program (Campaign) | What it is | Flight window | Lead target (MQL + HQL) | Live leads (2 Jul) | Committed CS budget | Paid media budget | Tabs shown |
|---|---|---|---|---|---|---|---|
| **Heavy Industries** | Awareness + lead gen across Mining/Metals, Energy & Chemicals, Food & Beverage, Life Sciences | 1 May to 31 Oct 2026 | **619** (571 MQL + 48 HQL) | **152** | A$22,865 | A$34,330 | Paid, CS, Compare, Other |
| **EcoStruxure Building Activate (EBA)** | Building-management lead gen to SMB retail, logistics, hotels, aged care, education | 25 May to 31 Aug 2026 | **157** MQL | **83** | A$12,500 | A$20,000 | Paid, CS, Compare |
| **Water & Environment** | 3-pillar awareness + lead gen for water and environment infrastructure | 30 Apr 2026 to 31 Jan 2027 | **184** MQL | **54** | A$21,923 | A$59,111 | Paid, CS, Compare |
| **AirSeT** | SF6-free medium-voltage product launch, awareness plus retargeting lead gen | 11 Jun to 31 Dec 2026 | **157** MQL | **7** (fixed 3 Jul; see §10 gap 1) | A$40,000 | A$50,000 | Paid, CS, Compare |
| **Advancing Energy Technology (Global Rebrand)** | Brand / thought-leadership awareness for the new energy-technology positioning | from 1 Jul 2026 | **0** (awareness, no lead line seeded) | **0** | A$0 (see gap in §10) | A$0 (see gap in §10) | Paid, Other |

Portfolio totals (arithmetic sum across the five; no longer a selectable view):

- **Total lead goal: 1,117** (sum of the five targets).
- **Live leads: 296** (as of 3 Jul, after the AirSeT fix), which is about **27%** of the total goal
  and comfortably **ahead** of the time-to-date pace (see §8 for what "time-to-date" means). The AI
  sample deck was generated on 1 Jul at 289 leads, before the AirSeT fix.
- **Committed content-syndication budget: A$97,288.**
- **Planned paid-media budget: A$163,441.**
- **Total planned budget (all lines): A$270,729.**

A sixth program the client mentions, **New Energy Landscape (NEL)**, is awareness only with no
Salesforce leads and is **not** currently a selectable campaign (see §10, gap 6).

---

## 4. Where every number comes from (data sources)

Everything on screen is produced from five data feeds, all mirrored into Google BigQuery. The
dashboard never talks to the ad platforms or Salesforce directly; it reads the mirrors.

| Feed | What it powers | How Schneider's slice is identified |
|---|---|---|
| **The Trade Desk** (programmatic display) | Paid Media impressions / clicks / spend | Advertiser is exactly `Schneider Electric` |
| **LinkedIn** | Paid Media impressions / clicks / spend | Account name starts with `SchneiderElectric_TransmissionSG` (three ad accounts) |
| **DV360** (programmatic display) | Paid Media (currently none of the five programs run on DV360, see below) | Advertiser name starts with `APAC \| Schneider Electric` |
| **Salesforce** (CRM leads) | Content Syndication leads | The nine Schneider campaign IDs (see §9) |
| **GA4** (website) | Not used yet (built but disabled, no Schneider property id supplied) | placeholder |

Key facts about the data:

- **Currency.** All spend is converted to AUD. USD is multiplied by 1.50 and SGD by 1.15. These two FX
  rates are **placeholders** agreed for now and can be updated. Trade Desk spend is already in AUD
  today, so the multiplier does not change it.
- **DV360 for the five programs.** Schneider does run DV360, but every current DV360 campaign belongs
  to a **different** APAC program (for example MEA Segment, AI in Data Centres, Power Products, C&SP).
  None of the five Pacific lead-gen programs runs on DV360 today, so the Paid Media platform table
  correctly shows zero for DV360. In-scope paid delivery is Trade Desk plus LinkedIn.
- **Freshness.** The dashboard checks its sources every 10 minutes and rebuilds within about 10
  minutes of new data arriving. It shows a `data through` timestamp rather than a fixed daily refresh
  time. Most 10-minute checks find nothing new and do nothing.
- **Leads are clamped to each program's flight window.** A lead only counts from the program's start
  date onward. For example EBA had four leads land a few days before its 25 May start; those are
  treated as pre-flight spillover and excluded, which is why EBA shows 83 rather than 87.

---

## 5. How the screen is organised (filters and tabs)

### Three global filters (top of the page)

1. **Campaign dropdown** (top nav bar). Pick one of the five programs; the dashboard opens on the
   first one. (The old **"All campaigns"** portfolio aggregate was removed on 3 Jul 2026 — you now
   always view one program at a time.)
2. **Region chips** (Australia / New Zealand). Toggle either or both. Everything on the current tab
   filters to the selected markets. Buttons "All" and "Clear" are provided.
3. **Date range picker.** Applies **only to the Paid Media tab** (a note on the control bar says so,
   and the date control is hidden on the other tabs). Content Syndication and its comparison always
   show the whole flight, because leads are about pacing to a target over the full window.

### The tab bar adapts per program

Each program only shows the tabs for the channels it actually uses. The system reads the program's
media-plan channels and buckets each into **paid** (Programmatic or LinkedIn), **cs** (lead-gen), or
**other** (search, publishers, trade press, email). Result:

- EBA and Water & Environment: Paid, CS, Compare.
- AirSeT: Paid, CS.
- Heavy: Paid, CS, Compare, Other (the Trade Publication line).
- Advancing Energy Technology: Paid, Other (Search, Capital Brief, Energy Magazine, Innovation Aus).

Switching campaign snaps you to the first valid tab for that campaign.

---

## 6. Tab by tab: every card, chart and table

### 6.1 Paid Media tab ("Paid Media: Delivery")

Filters that apply: campaign, region, and date range. If the program has no paid delivery (Heavy and
Advancing Energy Technology today), a banner explains it is leads-only or pre-launch and points to the
Content Syndication tab.

**Four KPI cards:**

| Card | What it shows | How it is calculated |
|---|---|---|
| **Total spend** | Paid spend in AUD | Sum of `spend_aud` across the filtered paid rows |
| **Impressions** | Total impressions; sub-label shows CPM | CPM = spend / impressions x 1000 |
| **Clicks** | Total clicks; sub-label shows CTR | CTR = clicks / impressions |
| **Blended CPC** | Cost per click | spend / clicks (read-only, does not toggle the chart) |

The first three cards are clickable: clicking one shows or hides that series on the chart below.
(The **CS Leads** card was removed from Paid Media on 3 Jul 2026 — CS leads now live only on the
Content Syndication tab.)

**"Spend vs budget" card — hidden as of 3 Jul 2026** at the client's request (the code is retained, so
it can be switched back on later). When shown, it compares **measured** paid spend against the
**planned** paid-media budget for the program, whole-flight and all-markets, independent of the region
and date filters.

**Hero chart "Media spend over time."** A combined chart with Spend (bars), Impressions (line),
Clicks (line) and CTR% (dashed line). Two toggles:

- **View by:** Month / Week / Day.
- **Axis:** Relative or Absolute. "Relative" indexes each series to its own peak = 100 on a shared
  0 to 100 axis so shapes can be compared; "Absolute" shows true values on separate axes. Tooltips
  always show the true value regardless of mode. Default is Week + Relative.

**Platform comparison table.** One row per platform (DV360 / Trade Desk / LinkedIn) with Spend, Imps,
Clicks, CTR, CPM, CPC, plus a Combined total row.

**Spend by platform** (doughnut) and **Spend by market** (bar), plus a **market summary table** (Spend
/ Imps / Clicks / CTR per market).

**Flight windows Gantt.** A horizontal timeline of all five programs' flight windows so overlapping
flights (a cannibalisation risk) are visible at a glance. The selected program's bar is green, the
others grey.

### 6.2 Content Syndication tab ("Content Syndication: Lead Pacing")

This is the heart of the dashboard. It compares live Salesforce leads to the media-plan lead target.
A header caveat states that leads are **CRM-raw**: today every lead is status **New** (the CRM has not
yet graded them to MQL / SQL / HQL), so this is total leads versus target, not "MQLs achieved."

**Snapshot strip (four groups):**

- **Overall:** Target, Total leads, Plan CPL (with committed spend).
- **Pacing:** Current pacing (leads versus the time-to-date pro-rata target, colour-coded), Overall
  pacing (leads versus the full target), and a verdict badge (Ahead of plan / Slightly behind /
  Behind plan).
- **Delivery:** paid Impressions, Clicks and CTR behind this program (all dates, current region).
- **Outlook:** Leads remaining to hit target, and Days left in the flight.

**"Leads vs target" goal bar.** A green fill showing the percentage of target delivered, with a "pace"
marker at the fraction of the flight that has elapsed. Below it, an "approximately A$X spent of the
A$Y committed CS budget" note: this is an **estimate** equal to delivered leads x plan CPL, because
content syndication bills per lead.

**"Progress" panel.** The verdict badge plus two bars: Leads delivered and Time elapsed, so you can
see whether leads are keeping up with the clock.

**"Weekly pacing: target vs actual" chart.** Bars per week: a flat grey **target pace** (total target
divided evenly across the weeks) and the coloured **actual leads** per week from Salesforce. The chart
and the grey pace both **start at the campaign's first actual lead week, not its booked flight_start**,
and the target is re-spread over that first-lead-to-flight_end window. This is deliberate: the paid media
often runs for weeks before the first Content-Syndication lead lands (water_env spent from its Apr 30
flight start but produced no lead until Jun 8), and charging target pace against those dead pre-lead weeks
made every campaign look behind at the start. (Note: the target pace here is an even spread; the client's
own Lead Pacing files use an uneven weekly target, see §10, gap 4.)

**Leads by market** (bar), **Leads by programme** (doughnut; the "programme" is the Salesforce pillar
within a program, for example Heavy's four pillars), a **by-market summary grid**, and a **programme x
market table** (Programme, Market, Leads, Status, Share, Last lead date).

A footnote repeats the CRM-raw caveat and notes that some plan lines (Trade Publication, IDE emails,
Search CTR, Innovation Aus) have no warehouse source and are not shown here.

### 6.3 CS Comparison tab ("Side-by-side comparison")

Two panels, A and B, each with a market dropdown (typically Australia versus New Zealand). Each panel
shows Total leads, Share of program and Last lead date, a Leads-by-programme doughnut, and a Weekly
pacing bar. Clicking a programme in a doughnut legend removes it and the panel's totals update to
match. This is where you tell the Australia versus New Zealand story for a single program.

### 6.4 Other Channels tab ("Other Channels: plan only")

A table of the media-plan lines that have **no automatic data feed**: search, publisher sponsorships,
trade press, email. Columns: Channel, Type, Plan impressions, Plan clicks, Plan leads, Plan spend, and
a "Plan only, no feed" badge. This exists so the full media plan is visible even where we cannot
measure delivery. It is a per-program tab.

---

## 7. The "Download slides" AI report

From the agency portal there is an **"Open slides"** button that generates a three-slide board report
for the selected program (or all campaigns): **What happened**, **Why it happened**, **Recommended
actions**. You can open it in Google Slides or download a PowerPoint.

How it works:

- The dashboard assembles the live numbers into a payload and sends them to a report generator.
- The generator runs **Claude Opus 4.8** in two stages: first a web-research pass (it can search and
  read the public web for context on Schneider and the market), then a strict "turn this into three
  slides" pass. If Claude is unavailable it falls back to Google's Gemini 2.5 Pro.
- **Crucially, the numbers on the slides come verbatim from the dashboard payload.** The AI writes the
  narrative and recommendations; it does not invent or recompute the figures, and it cannot fabricate
  a source URL. So the deck and the dashboard can never disagree on the numbers.
- The deck is styled in Schneider green with the brand line "TRANSMISSION x Schneider Electric
  Pacific."

The sample deck the client has (`Schneider_Pacific_All_campaigns_2026-07-01`) is exactly this output,
generated on 1 July 2026. It reported 289 leads, 12% ahead of the time-to-date target, blended plan
CPL about A$87, and A$97,288 committed content-syndication budget, all of which match the dashboard.

---

## 8. Definitions and formulas (glossary)

- **Program / Campaign.** One of the five lines of work (Heavy, EBA, Water & Environment, AirSeT,
  Advancing Energy Technology). Selected from the top dropdown.
- **Programme (Salesforce pillar).** A sub-line within a program, for example Heavy's four pillars
  (TAL, whitespace, Operational Automation & Intelligence, Industrial Modernisation). Used by the
  "Leads by programme" doughnut.
- **Market.** Australia or New Zealand. Content-syndication leads are AU/NZ native. Paid delivery is
  resolved to AU or NZ, folding any small unsplittable cross-market residual into Australia.
- **Lead.** One row in Salesforce for a person who downloaded gated content. Today every lead is
  status **New** (not yet graded).
- **MQL / HQL.** Marketing Qualified Lead / Highly Qualified Lead. These are the **target** categories
  from the media plan. The live leads are not yet graded into them, so we report total leads versus
  the combined MQL+HQL target.
- **Target.** Media-plan MQL + HQL lead target for the program.
- **Committed spend (CS).** The sum of the program's lead-gen line spends from the media plan. Content
  syndication bills per lead, so this is the committed content-syndication budget.
- **Plan CPL.** Committed spend / target. The planned cost per lead. Blended plan CPL across the
  portfolio is A$97,288 / 1,117 which is about A$87.
- **Blended CPL (Paid Media tab).** Paid spend / leads in range. A different, delivery-side view of
  cost per lead.
- **CPM.** Cost per thousand impressions = spend / impressions x 1000.
- **CPC.** Cost per click = spend / clicks.
- **CTR.** Click-through rate = clicks / impressions.
- **Time-to-date (TTD) target / pro-rata target.** The target scaled to how much of the flight has
  elapsed. If 23% of the flight has passed, the time-to-date target is 23% of the full target. "12%
  ahead" means live leads are 12% above this pro-rata figure. (Note: "TTD" here means time-to-date,
  not The Trade Desk.)
- **Committed vs planned budget.** "Paid-media budget" (A$163,441) is the awareness/programmatic and
  LinkedIn spend; "committed CS budget" (A$97,288) is the lead-gen spend; the "total planned budget"
  (A$270,729) also includes Heavy's A$10,000 Trade Publication line. All are media-plan ex-fees.
- **Relative vs Absolute (charts).** Relative indexes each line to its own peak (=100) so shapes line
  up; Absolute shows true values. Tooltips always show the true value.

---

## 9. Campaign IDs and the Salesforce mapping

The user pointed to **`Schneider Campaigns.pdf`** as the list of IDs to pull from the database. Here is
the canonical list from that file, mapped to each program, and whether the dashboard actually pulls it.

| Program | Salesforce campaign ID | In `Schneider Campaigns.pdf`? | Wired into the dashboard? | Live leads in the raw feed |
|---|---|---|---|---|
| Water & Environment | `701RG00001RTyAQYA1` (Pillar 1) | Yes | **Yes** | 0 (Pillar 1 leads start in July, not begun) |
| Water & Environment | `701RG00001RUkTfYAL` (Pillar 2) | Yes | **Yes** | 54 |
| EBA | `701RG00001OwE65YAF` | Yes | **Yes** | 87 (83 after flight clamp) |
| Heavy Industries | `701RG00001KhQEcYAN` (Demand AI / TAL / HQL) | Yes | **Yes** | 36 |
| Heavy Industries | `701RG00001T4zGfYAJ` (whitespace) | Yes | **Yes** | 18 |
| Heavy Industries | `701RG00001KhQL4YAN` (Operational Automation & Intelligence) | Yes | **Yes** | 57 |
| Heavy Industries | `701RG00001KhOntYAF` (Industrial Modernisation) | Yes | **Yes** | 41 |
| Advancing Energy Technology | `701RG00001VHiiJYAT` (Global Rebrand Activation) | Yes | **Yes** | 0 (awareness, pre-launch) |
| AirSeT | `701RG00001VI10DYAT` | Yes | **Yes** | **0** |
| AirSeT | `701RG00001VbvbTYAR` (Final Funnel) | Yes | **Yes (added 3 Jul)** | 0 |
| AirSeT | `701RG00001VbxRrYAJ` (Roverpath) | **No** (this ID is only in the `SE ANZ Dashboard` xlsx) | **Yes (added 3 Jul)** | **7** (5 AU + 2 NZ, dated 1 Jul) |

**Bottom line (updated 3 Jul, now fixed):** the dashboard now wires **all** the AirSeT IDs. The real
AirSeT leads were filed under `VbxRrYAJ` (Roverpath), which appears in the client's `SE ANZ Dashboard`
spreadsheet but not in `Schneider Campaigns.pdf`, so it had not been mapped and AirSeT showed 0. We
have added `VbxRrYAJ` (and `VbvbTYAR`, Final Funnel, for completeness), so **AirSeT now correctly shows
7 leads**. **To flag to the client:** their two source files disagree on AirSeT's Salesforce IDs
(`Schneider Campaigns.pdf` says `VI10DYAT` + `VbvbTYAR`; the `SE ANZ Dashboard` xlsx says `VbxRrYAJ` +
`VbvbTYAR`), and the actual leads landed under a third combination. Please confirm which AirSeT IDs are
canonical so the mapping stays correct as more leads arrive.

The IDs that show 0 for Water & Environment Pillar 1 and Advancing Energy Technology are **correct**:
those lead lines have not started delivering yet.

---

## 10. Does the dashboard reflect everything the client gave us?

Short answer: **the core lead and paid-delivery reporting for the five programs is accurate and ties
out exactly**, but there are **six gaps** between what the client has sent and what the dashboard
currently shows. None of them break the dashboard; they are items to confirm or fix with the client.

### What ties out exactly (verified against live BigQuery)

- **Live leads: 289** (Heavy 152, EBA 83, Water & Environment 54). Matches the served data and the
  sample deck.
- **Every target:** Heavy 619 (571 MQL + 48 HQL), EBA 157, Water & Environment 184, AirSeT 157,
  Advancing Energy Technology 0. Portfolio total 1,117. All match the media plan.
- **Committed CS spend:** Heavy 22,865, EBA 12,500, Water & Environment 21,923, AirSeT 40,000.
  Portfolio 97,288. All match.
- **Planned paid-media budget:** 163,441 across the five. Matches the media-plan paid lines.
- **Total planned budget:** 270,729 (= 163,441 paid + 97,288 CS + 10,000 Heavy Trade Publication).
- **Flight-window lead clamping** works (EBA 87 raw becomes 83 after excluding four pre-flight leads).
- **Market normalisation** works (raw feed uses AU, AUSTRALIA, NZ, NEW ZEALAND; all resolve correctly).

### The six gaps

**Gap 1 (FIXED 3 Jul; still flag to the client): AirSeT leads were not being counted.**
The client's two files disagree on AirSeT's Salesforce IDs. The dashboard had mapped only `VI10DYAT`
(0 leads); the seven real AirSeT leads sit under `VbxRrYAJ` (Roverpath), which is in the `SE ANZ
Dashboard` spreadsheet but was not mapped. Result: AirSeT showed 0 instead of 7.
**Fix applied:** `VbxRrYAJ` and `VbvbTYAR` were added to the Salesforce mapping
(`data/salesforce_map.csv`) and the dashboard rebuilt, so **AirSeT now shows 7 leads** (5 AU + 2 NZ)
and total portfolio leads are 296.
**To flag to the client:** their source files disagree on the canonical AirSeT IDs
(`Schneider Campaigns.pdf` = `VI10DYAT` + `VbvbTYAR`; `SE ANZ Dashboard` xlsx = `VbxRrYAJ` +
`VbvbTYAR`), and the live leads arrived under `VbxRrYAJ`. Please confirm the canonical set so the map
stays correct as volume grows.

**Gap 2: Advancing Energy Technology (Global Rebrand) is under-budgeted in the dashboard.**
The client's `2061` media plan for this program is about **A$257,000** across eight channels (three
LinkedIn lines, Search, Energy Magazine, ECD Online, Sustainability Matters, Innovation Aus, Capital
Brief). The dashboard currently carries **no spend** for it (committed A$0, no paid budget) and is
missing two channels entirely (ECD Online and Sustainability Matters). The Other Channels tab shows
Capital Brief, Energy Magazine and Innovation Aus with impression and click targets but no spend.
**Cause:** this program launches 1 July 2026 and the detailed plan was digested after the initial
build. **Fix:** seed the 2061 budget and the two missing channels.
**Related:** its paid delivery may not auto-tag once it launches, because the campaign is named
"Advancing Energy Technology" / "New Energy Technology Brand" while the tagging pattern looks for
"Rebrand." The pattern should be updated when the live campaign names are known.

**Gap 3: Trade-publication performance actuals are not shown.**
Heavy's "Trade Publication" line (A$10,000) appears as plan-only on the Other Channels tab. But the
client has sent **actual** results: `Article Reporting.xlsx` (Mining Magazine and TechPapersWorld
weekly page views, sessions, engaged sessions, outbound clicks and CTR) and the `TechPapersWorld`
advertorial report (765 page views, 667 sessions, 524 engaged, 43 outbound clicks, 5.62% CTR for 28
April to 28 May). These are not in the dashboard because there is no automated feed for them.
**Note for the meeting:** the plan's 15% outbound CTR target looks optimistic against the roughly 5%
CTR actually reported. If the client wants trade-pub actuals on the dashboard, we would load these
spreadsheets as a manual seed.

**Gap 4: Lead-pacing detail is simplified.**
The four `Lead Pacing` PDFs are Heavy Industries' weekly pacing plans for its four lead lines (HQL 48,
Roverpath MQL 85, Finalfunnel MQL 435, Demand AI MQL 51), broken down by **application segment**
(Mining/Metals, Energy & Chemicals, Consumer/Food, Life Sciences) and by **TAL versus Whitespace**,
with an **uneven** weekly target curve and actual-versus-deficit tracking. The dashboard's weekly
pacing chart works at the program / pillar / market level with an **even** target pace, and does not
carry the segment or TAL/Whitespace split (Salesforce does not send us that dimension). So the
client's richest pacing view is a planning artifact we do not fully reproduce.

**Gap 5: Standalone media-plan PDFs and the master sheet disagree on budgets.**
The dashboard uses the sums from the master `SE ANZ Dashboard` sheet, which are the most complete. The
individual plan PDFs often quote a smaller "Overall Budget" because they cover only part of the scope:

| Program | Standalone PDF "Overall Budget" | Master sheet total (used by dashboard) | Why they differ |
|---|---|---|---|
| Water & Environment | A$59,111 | A$81,034 | PDF is awareness only and an older (Mar to Jun) version; master adds lead-gen |
| Heavy Industries | A$77,500 | A$67,195 | PDF is a partial/earlier figure; an old seed had A$87,500 |
| AirSeT | A$50,000 | A$90,000 | PDF is the awareness portion only; master adds LinkedIn streams + lead gen |
| EBA | A$20,000 | A$32,500 | PDF is programmatic only; master adds the A$12,500 lead-gen line |
| Advancing Energy Technology | A$38,000 or A$257,000 | A$0 (see gap 2) | PDF has both a small and a full figure; not yet seeded |

These are reconcilable, but it is worth confirming which budget is canonical per program so the
numbers in the dashboard match what the client expects to see.

**Gap 6: New Energy Landscape (NEL) is provided but not shown.**
The client's master `SE ANZ Dashboard` lists six programs; the dashboard shows five. NEL (job 2053,
A$35,000, programmatic + LinkedIn video, awareness only, no Salesforce leads) is in our data but is
**not** a selectable campaign. It has no lead lines, so it does not fit the content-syndication model,
but its paid delivery is not surfaced anywhere. Confirm whether NEL should be added as a sixth
(awareness-only) program or intentionally left out.

---

## 11. Inventory of the client source files

Everything the client sent lives in `clients/client_schneider/raw_files/`. Here is what each file is
and how it maps to the dashboard.

| File | What it is | Role in the dashboard |
|---|---|---|
| `SE ANZ Dashboard.pdf` and `SE ANZ Dashboard (1).xlsx` | The **master specification**: six programs with dates, channels, expected KPIs, spend and campaign IDs | The source of truth for programs, targets, budgets and the campaign-to-ID mapping. The xlsx is the clean tabular version. |
| `Schneider Campaigns.pdf` | The **canonical Salesforce campaign-ID list** (five programs, ten IDs) | The IDs to pull from the database (see §9). |
| `1130 SE Water & Environment - Media Plan.pdf` | Detailed W&E media plan (3 pillars, LinkedIn + programmatic) | Seeds W&E channels and budget. |
| `SE Ecostruxure Building - Media Plan.pdf` | EBA programmatic plan (A$20,000, AU/NZ 80/20) | Seeds EBA paid line. |
| `SE Heavy Industries - Media Plan.pdf` | Heavy 3-pillar plan (Industrial Modernisation, Energy Transformation, Operational Automation) | Seeds Heavy channels; note the A$77,500 headline versus A$67,195 used. |
| `2223 SE Airset - Media Plan.pdf` | AirSeT product-launch plan (Trade Desk + LinkedIn, RM/SM, A$50,000 awareness) | Seeds AirSeT paid lines. |
| `2053_SE_ANZ_New Energy Landscape Awareness - Media Plan.pdf` | NEL awareness plan (A$35,000) | Program not shown (gap 6). |
| `2061_SE_ANZ_Advancing Energy Technology Activation - Media Plan - r1.pdf` | The full A$257,000 Advancing Energy Technology plan (LinkedIn, Search, Energy Magazine, ECD Online, Sustainability Matters, Innovation Aus, Capital Brief) + persona targeting detail | Under-seeded today (gap 2). |
| `Lead Pacing.pdf`, `Lead Pacing (1).pdf`, `(2).pdf`, `(3).pdf` | Heavy's four lead lines' weekly pacing, by segment and TAL/Whitespace | Simplified in the dashboard (gap 4). Specifically: `Lead Pacing.pdf` = Demand AI HQL (48), `(1)` = Roverpath MQL (85), `(2)` = Finalfunnel MQL (Industrial Modernisation 235 + Operational Automation 200 = 435), `(3)` = Demand AI MQL (51). |
| `Article Reporting.xlsx` | Weekly trade-publication actuals (Mining Magazine, TechPapersWorld) | Not shown (gap 3). |
| `TechPapersWorld_Advertorial_Report_28Apr_28May 1.pdf` | Advertorial performance report (765 views, 5.62% CTR) | Not shown (gap 3). |
| `Schneider_Pacific_All_campaigns_2026-07-01 (2).pptx` | A sample of the dashboard's own AI "Download slides" output | Explained in §7; numbers match the dashboard. |

---

## 12. Live numbers snapshot (as of 2 July 2026)

These figures move as data refreshes; the structure does not. Captured from live BigQuery.

**Content syndication leads (296 total after the 3 Jul AirSeT fix, all status New):**

| Program | Australia | New Zealand | Total | Target | Delivered vs target |
|---|---|---|---|---|---|
| Heavy Industries | 145 | 7 | 152 | 619 | 25% |
| EBA | 65 | 18 | 83 | 157 | 53% |
| Water & Environment | 43 | 11 | 54 | 184 | 29% |
| AirSeT | 5 | 2 | 7 | 157 | 4% |
| Advancing Energy Technology | 0 | 0 | 0 | 0 | n/a |
| **Total** | **258** | **38** | **296** | **1,117** | **27%** |

**Leads by programme (Salesforce pillar):** EBA 83; Heavy: Operational Automation & Intelligence 57,
Industrial Modernisation 41, TAL 36, whitespace 18; Water & Environment Pillar 2: 54.

**Weekly lead arrivals:** w/c 25 May: 11, 1 Jun: 10, 8 Jun: 65, 15 Jun: 72, 22 Jun: 78, 29 Jun: 53.

**Paid delivery in scope (measured, whole flight):**

| Program | Platform | Spend (AUD) | Impressions |
|---|---|---|---|
| EBA | Trade Desk | 7,071 | 5,767,855 |
| Water & Environment | LinkedIn | 2,371 | 13,424 |
| Water & Environment | Trade Desk | 2,008 | 328,350 |
| AirSeT | Trade Desk | 1,757 | 70,720 |
| AirSeT | LinkedIn | 1,393 | 44,121 |
| Heavy | (none yet) | 0 | 0 |
| Advancing Energy Technology | (none yet) | 0 | 0 |

Roughly 6.2M impressions at a blended CPM near A$2.34; the Trade Desk delivers about 99% of
impressions at a low CPM, LinkedIn a small share at a higher CPM. Australia is about 88% of leads and
roughly 79% of paid spend, reflecting the larger Australian market.

**Data window:** 29 April to 2 July 2026 (65 days). **FX:** USD x 1.50, SGD x 1.15. **Refresh:** every
10 minutes, self-gating.

---

## 13. Frequently asked questions

**Q: How fresh is the data?**
Within about 10 minutes of new data landing in the source systems. The footer shows a "data through"
timestamp. There is no fixed daily refresh time.

**Q: Why did AirSeT show zero leads (now fixed to 7)?**
It was a Salesforce ID mismatch, not a lack of leads. The client's two files list different AirSeT
IDs, and the seven real leads landed under `VbxRrYAJ` (Roverpath), which had not been mapped. We added
it on 3 Jul, so AirSeT now shows 7 (5 AU + 2 NZ). We still want the client to confirm which AirSeT IDs
are canonical. See §9 and §10 gap 1.

**Q: Are these leads MQLs?**
Not yet graded. Salesforce sends them as status "New." We report total leads against the combined
MQL + HQL target. When the CRM starts grading, the dashboard is already built to show the breakdown.

**Q: Why is Heavy Industries at 25% of target but described as on track?**
Because pacing is measured against the **time-to-date** target (how far into the flight we are), not
the full target. Heavy's flight runs to 31 October, so 152 of 619 this early is on or ahead of pace.
The portfolio is about 12% ahead of the time-to-date pace.

**Q: Why does DV360 show nothing on the Paid Media table?**
Schneider does run DV360, but only for other APAC programs, not for these five Pacific programs. In
scope, paid delivery is Trade Desk and LinkedIn. This is correct, not a bug.

**Q: Why can I not filter Content Syndication by date?**
By design. Leads are about pacing to a target over the full flight, so the CS tabs always show the
whole flight. The date filter applies to the Paid Media tab only.

**Q: What currency is everything in? Are the FX rates real?**
AUD throughout. USD is x 1.50 and SGD is x 1.15. These are agreed placeholders and can be updated.
Trade Desk is already AUD.

**Q: Where do the budget numbers come from, and why do the plan PDFs show different totals?**
The dashboard uses the sums from the master SE ANZ Dashboard sheet. Individual plan PDFs often quote a
smaller "Overall Budget" because they cover only part of the scope (awareness only, or an older
version). See §10 gap 5 for the reconciliation.

**Q: Is the "Advancing Energy Technology" budget really zero?**
No; its full plan is about A$257,000. It is not seeded yet because the program launches 1 July and the
detailed plan came in after the initial build. See §10 gap 2.

**Q: Can we see the trade-publication (Mining Magazine, TechPapersWorld) results here?**
Not currently; those come as spreadsheets with no automatic feed, so Heavy's Trade Publication line is
plan-only. We can load them as a manual seed if wanted. See §10 gap 3.

**Q: Is the AI slide deck trustworthy on the numbers?**
Yes. The figures are passed to the AI verbatim from the dashboard; the AI writes the commentary and
recommendations, not the numbers, and cannot invent a source. The deck and dashboard always agree.

**Q: Is the data secure?**
Yes. The page is password protected and the underlying data file is in a private bucket, served only
to a logged-in session, never public.

---

## 14. Things to say carefully in the meeting

- **AirSeT is now showing its 7 real leads (fixed 3 Jul).** If it comes up, note that the client's two
  files listed different AirSeT Salesforce IDs; the live leads landed under the Roverpath ID
  (`VbxRrYAJ`), which we have now mapped. Ask the client to confirm the canonical AirSeT IDs so it
  stays correct. Do not present it as a performance issue: it was a mapping/source discrepancy.
- **Leads are ungraded ("New").** Avoid language like "we hit X MQLs." Say "X leads delivered against
  a target of Y; the CRM has not yet graded them into MQL/HQL."
- **Pacing versus total.** When a program looks low against its full target, frame it against the
  time-to-date pace and the flight end date.
- **Advancing Energy Technology shows little today** because it launches 1 July and its budget is not
  fully seeded yet. Flag it as "coming online," not "underperforming."
- **Trade-publication and detailed lead-pacing views** exist in the client's files but not on the
  dashboard. If they ask, be honest that these are not automated feeds and offer to add them.
- **FX rates are placeholders.** If spend precision matters, confirm the USD and SGD rates.

---

## 15. Technical appendix (for engineers)

### Three-stage pipeline
```
(1) SOURCE to RAW (shared)                    (2) RAW to VIEWS to JSON                 (3) JSON to FRONTEND
snowflake_data_pull fills                     clients/client_schneider/sql/*.sql       schneider-dash (Cloud Run service)
raw_snowflake.{dv360_apac,                    filter SE's slice + roll up + seeds;     serves a login page, then
tradedesk_apac_all, linkedin_ads_apac,        schneider-export (Cloud Run job)         dashboard.html, which fetches
salesforce_cs_apac_all}                       reads views to schneider.json            /data.json and draws the charts
```

### Data contract (matched by name)
`sql/*.sql view column` to `job/main.py env{} key` to `dashboard.html data.* key`. Renaming one stage
breaks the next.

### The views that actually matter to the dashboard
- **`pm_delivery` (sql/20)**: paid delivery tagged to program, scoped to the five, at
  program x platform x day x market. Powers Paid Media.
- **`cs_by_programme` (sql/18)** and **`cs_weekly` (sql/19)**: Salesforce leads rolled up per
  campaign x programme x market (and by week). Powers Content Syndication and Comparison.
- **`stg_salesforce` (sql/17)**: the inner join of the shared Salesforce mirror to
  `seed_salesforce_map` (the nine IDs) with flight-window clamping.
- **Seed tables** (`seed_media_plan`, `seed_plan_budget`, `seed_campaign_map`, `seed_salesforce_map`):
  targets, budgets, display names, and the lead-ID map.
- The staging views `stg_dv360 / stg_linkedin / stg_tradedesk / stg_ad_delivery` (sql/01 to 04) apply
  the per-platform SE filters and FX and feed `pm_delivery`.
- Views 05 to 16 (legacy paid rollups) and 40 to 46 (GA4) are created but **not read** by the current
  job. GA4 is built but disabled (no Schneider property id). The `GA4_ENABLED` flag referenced in some
  older notes no longer exists in `job/main.py`.

### Where the client-editable inputs live
- `data/campaign_map.csv`: program display names, match patterns (how a platform campaign name is
  tagged to a program), portfolio membership.
- `data/media_plan.csv`: per-program channel lines with spend, impression/click/lead targets, flight
  dates, and the Salesforce lead-ID per lead line.
- `data/plan_budget.csv`: per-program overall budget and flight window.
- `data/targets.csv`: extra KPI targets (EcoConsult only today).
- `data/salesforce_map.csv`: the nine-ID Salesforce mapping. **Note:** this file is currently
  BigQuery-only (not committed to the repo). **This is the file to edit to fix the AirSeT gap** (add
  `VbxRrYAJ`), then reload seeds and force a rebuild.

### To apply a fix (PowerShell, from the repo root)
```powershell
# after editing a data/*.csv seed (for example adding the AirSeT Roverpath ID to salesforce_map.csv)
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```
`FORCE_REBUILD=1` is required after any seed or view-only change, because such a change does not
advance the upstream tables the freshness gate watches.

### Coordinates
| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_schneider` |
| Data bucket / object | `bidbrain-analytics-schneider-dash` / `schneider.json` |
| Export job | `schneider-export` |
| Web service | `schneider-dash` |
| Access | `https://dashboards.bidbrain.ai/d/schneider/` |

For deeper engineering detail see the sibling docs in this folder: `README.md` (developer overview),
`INTAKE.md` (the resolved data slice and open items), `sql/README.md`, `job/README.md`,
`dash/README.md`, and `_eda/pacific_eda.md` (the Pacific carve-out history).
