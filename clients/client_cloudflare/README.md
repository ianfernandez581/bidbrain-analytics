# client_cloudflare — Cloudflare APAC dashboard on the MongoDB GCP pattern

**Status: LIVE.** The gated web app is deployed and serving (HTTP 200 verified
2026-06-04). See [`dash/LIVE_URL.md`](dash/LIVE_URL.md) for the URL.

This folder runs the **Cloudflare** dashboard on the same Google Cloud
architecture as `client_mongodb` — **BigQuery owns the model** (since 2026-06-17;
see [BigQuery owns the model](#bigquery-owns-the-model-was-the-snowflake-modelled-exception)):

```
raw_snowflake.* mirrors (shared ingest/snowflake_data_pull)  +  client_cloudflare.seed_* (static, from data/)
  -> BigQuery views (clients/client_cloudflare/sql)      staging -> models
  -> Cloud Run JOB  (clients/client_cloudflare/job)      read views -> cloudflare.json   (NO Snowflake)
  -> GCS (private)  gs://bidbrain-analytics-cloudflare-dash/cloudflare.json
  -> Cloud Run SERVICE (clients/client_cloudflare/dash)  password gate + serves dashboard.html + proxies /data.json
  -> Platform front-door  https://dashboards.bidbrain.ai/d/cloudflare/  (reverse-proxies + one login)
```

The `cloudbuild.yaml` files are a **future** push-to-main CD trigger (one per
unit, like MongoDB §11) — **not active**. This client was stood up, and is
redeployed, by the manual order below.

This replaces Cloudflare's current setup (Snowflake **tasks** writing
`pacing.json` + `paid_media.json` to a **public** R2 bucket, read by a static
page). The two payloads are merged into one `cloudflare.json`, served behind the
same Flask password gate MongoDB uses.

## What's in this folder

| Path | What it is |
|---|---|
| [`job/`](job/README.md) | **Export Job** (`cloudflare-export`): reads the BigQuery views → writes `cloudflare.json`. **No Snowflake** (BQ-only, like MongoDB). [Guide →](job/README.md) |
| [`dash/`](dash/README.md) | **Web App** (`cloudflare-dash`): password gate + serves `dashboard.html` + proxies `/data.json`. Also carries its **own Feedback pill for DIRECT logins** (the front-door injects one only for sessions that come through it, and Cloudflare's people mostly hit the `…run.app` URL) — needs the one-time `dash/enable_feedback_cloudflare.ps1`. [Guide →](dash/README.md) |
| [`sql/`](sql/README.md) | The BigQuery **model** views — staging (`stg_*`) → `paid_media_model`/`pacing_model`/etc. — over `raw_snowflake.*` + the `seed_*` static tables. [Guide →](sql/README.md) |
| [`create_views.py`](create_views.py) | Applies every `sql/*.sql` view (runner; `NN_` prefix = dependency order). |
| `data/` | Local CSV snapshots of the three STATIC Snowflake tables (pacing targets, account tiers, LINE JP). **Gitignored** (`clients/*/data/`) — `TIERS` is sensitive client ABM data — so it's NOT in the repo; regenerate with `pull_static.py`. The live seeds persist in BigQuery (`seed_*`). |
| [`pull_static.py`](pull_static.py) | **One-time** Snowflake → `data/*.csv` pull (manual; needs the Snowflake key; re-run on a fresh checkout or when a static upload changes). **⚠️ The Q2 pacing targets in `seed_real_targets` were rebalanced on 2026-06-19 directly in BQ + `data/real_targets.csv` (grand total unchanged at 3216; regional split updated to the client's new Phase×Region table — see git log). The Snowflake `CLOUDFLARE_SANDBOX.CS_REPORTING.REAL_TARGETS` source was NOT updated, so re-running `pull_static.py` will REVERT this. Update Snowflake first, or skip the real_targets pull.** |
| [`seed_static.py`](seed_static.py) | Loads `data/*.csv` → BigQuery `client_cloudflare.seed_*` (no Snowflake). Re-run after `pull_static.py`. |
| [`snowflake_v_*.sql`](snowflake_v_salesforce_leads_live.sql) | **Reference only** now — the live Snowflake DDL for Cloudflare's OWN legacy R2 export tasks. NOT part of this pipeline (the BQ `sql/` views are the source of truth). |
| [`scheduler.ps1`](scheduler.ps1) | Creates/refreshes the Cloud Scheduler trigger for `cloudflare-export` (default `*/10` UTC; pass `-Cron` to override). The job self-gates, so most ticks no-op. Idempotent. |

> There is **no** one-shot `deploy_cloudflare.ps1` for this client — it was stood
> up via the manual order in [One-time replicate / deploy order](#one-time-replicate--deploy-order)
> below. (Only STT has a one-shot stand-up script, `clients/client_STT/deploy_stt.ps1`.)

## Google Ads — the 5th paid channel (added 2026-08-11)

Transmission connected the **`Cloudflare APAC`** Google Ads account (`ACCOUNT_ID 3034487647`) into
`raw_snowflake.google_ads_apac` around **2026-07-22**. It feeds **Q3 Core DG (brief 2479)**.

**Live today — two campaigns** (figures at 2026-08-20):

| Campaign | Type | Market / lane | Delivery |
|---|---|---|---|
| `CF_JP_Q3_TOFU_YouTube_VideoViews_Prospecting` (`24037386856`) | YouTube VideoViews, awareness | **JP** · `CORE_DG` | 275,598 imps · 145 clicks · **US$1,220.40** · 176,429 video views (07-22 →) |
| `CF_JP_Q3_Leadgen_PMax_Mythos_RMKT_LP` | **Performance Max**, lead-gen remarketing | **JP** · `CORE_DG` | 118,136 imps · 3,818 clicks · **US$635.14** · **24 conversions** (08-06 →) |

Currency is **USD** — already the reporting currency, so there is **no FX step**.
The account-scoped filter is what let the second campaign appear with no code change to the
`WHERE` clause, exactly as designed. Its name carries a `_JP_` token, so it resolved to JP
rather than falling into the `UNMAPPED` bucket that no market chip shows.

**Files:** `sql/04b_stg_google_ads.sql` (new staging view) → a `google_ads` arm in
[`sql/05_paid_media_model.sql`](sql/05_paid_media_model.sql) and
[`sql/06_paid_creatives_model.sql`](sql/06_paid_creatives_model.sql) → dashboard `PM_CHANS` entry +
`PM_GA`/`.pill.ga` colour + a `ga_market_day` array in `adaptPayload`.
**`job/main.py` needed NO change** — it emits generic `rows[]` keyed by `channel`, so a new channel
flows through on its own. That property is worth preserving.

### Scoped by ACCOUNT, not campaign name — deliberately
The media sheet lists **two** Google Ads lines against 2479 (Awareness from 15-Jul, Lead Generation
from 17-Jul) but **only Awareness is connected**. Filtering on `ACCOUNT_NAME = 'Cloudflare APAC'`
means the Lead Generation campaign starts reporting the moment Transmission connects it, with **no
code change here**. It also avoids the repo-wide "campaign names are NOT stable keys" trap — these
names do **not** follow the `CLOUD_ACQ_` convention every other channel uses, so a name filter would
be both fragile and wrong.

### Both original gaps closed 2026-08-20 — and what it cost (read before touching this channel)
Transmission (Ankit) shipped both asks in one change to the shared `Google Ads - APAC` export.
Neither arrived in the shape we expected.

**1. The Lead Generation campaign is connected — by flattening the whole table's grain.**
It is a **Performance Max** campaign, which reports nothing at ad-group level, so the export moved
from AD GROUP to **CAMPAIGN** level and **`AD_GROUP_NAME` was dropped**. Because the mirror is a
`SELECT *` WRITE_TRUNCATE copy, the new schema landed unannounced on the next `*/10` tick and
`stg_google_ads` — and through it `paid_media_model`, `paid_creatives_model` and **every
`cloudflare-export` run** — failed for ~19 hours (08-19 13:10 UTC → 08-20 08:46 UTC). The dashboard
did not error; it silently served its last good JSON, which is the failure mode to watch for.
STT reads the same mirror but not the ad group, so it was unaffected.
- The grain is now `DAY × CAMPAIGN × NETWORK` and **`NETWORK` is carried as a real dimension** —
  it is the only sub-campaign cut left, and for PMax it is the useful one (all 24 conversions are
  **DISCOVER**; CONTENT has produced none on US$110).
- **The `TOFU | Persona` vs `TOFU | Custom Intent` split is gone for good**, including from
  history — the truncate rewrote the past too. `paid_creatives_model` now labels Google Ads rows
  `<Network> (network)` so a placement is never read as a creative name.
- Delivery reconciled across the change with **no loss**: the Awareness campaign's 07-22 → 08-08
  window reads 172,332 imps / 90 clicks / $764.83 against the 172,396 / 90 / $765.16 recorded at
  build time — a 0.04% Google restatement.

**2. The video columns arrived as RATES, and two of the five are dead.**
`VIDEO_PLAYED_TO_50` / `_75` and `VIEW_RATE_IN_STREAM` / `TRUEVIEW_VIEW_RATE` are FLOAT rates in
0..1, all denominated in impressions. **A rate must never reach a fact table that gets `SUM()`ed**,
so `stg_google_ads` multiplies each back out to a COUNT at source-row grain. Downstream rollups are
then exact and the rate is re-derived from the totals.
- `VIDEO_PLAYED_TO_25_` is **100% NULL** — and note the **stray trailing underscore** in the column
  name, itself a source-side bug.
- `VIDEO_PLAYED_TO_100` is **literally 0.0 on every row**. It cannot be real when 67% of
  impressions reach the 75% quartile. **Neither is referenced**, and the UI says so — carrying
  them would draw a 0% completion rate that reads as a failed campaign.
- **Still no native view COUNT and no working completion metric.** Worth asking for both.

**What the dashboard now shows** (`renderGaVideoNote()` → `#gaVideoBlock`, Paid Media tab, under
the benchmark table, auto-hidden when the lane has no video in range): a **4-tile KPI strip**
(video views · view rate · cost per view · watched-to-75%) over a **horizontal completion funnel**
(video impressions → watched 50% → watched 75%). It was shipped as a paragraph first and rejected
on sight - the client reads this tab in tiles and charts, and a wall of prose under a table of
numbers does not get read. Current figures: **193,625 video views at a 62.6% view rate and $0.0096
CPV**. The funnel deliberately renders **only the stages the feed reports** (`.filter(v => v > 0)`)
- a zero bar for the two dead quartiles would read as a failed campaign rather than missing data.
The view rate is measured against `VIDEO_IMPS` — impressions on video-capable placements only. This
matters: dividing by total Google Ads impressions charges the ~69k Discover and search impressions
against the rate and understates it by ~13 points (49.2% vs 62.6%). The network dimension is
collapsed by `paid_media_model`'s `GROUP BY`, so that denominator has to travel as its own measure.
**This is the number that retires the "0.05% CTR" problem** — CTR was never the lens for a video
buy, and `PM_CHANS[].note` now says to judge it on view rate and CPV.

**There is NO creative-level Google Ads data - anywhere (checked 2026-08-20).** All three
possible sources were queried, so do not re-investigate this without new access:
| Source | Verdict |
|---|---|
| `raw_snowflake.google_ads_apac` | Campaign grain since 08-20. No ad / asset / creative column. |
| `raw_google_ads.*` (native DTS, MCC `3451896252`) | Carries only customers `2617916504`, `1054407474`, `1869745895`. Account `3034487647` is **not linked**. |
| `raw_windsor.perf_google_ads` | Schema has **no creative field at all**, and holds only City Perfume + Reset Data. |

So `paid_creatives_model` shows **campaign × network** - the finest grain that exists - labelled
`<campaign> - <Network>`. Network *alone* was wrong: it merged the TOFU VideoViews buy and PMax's
YouTube placements into a single "Youtube" row, which are not the same thing. The 1,000-impression
floor (`CREATIVE_MIN_IMPS`) already drops the 1-11 impression Search / Search Partners / Mixed rows,
so the finer grain cannot pollute the top-by-CTR ranking. **To get real creatives, Transmission must
add ad / asset-level columns** (ad name + asset for PMax, video asset for the YouTube buy). Until
then this is the floor, not a design choice - do not substitute anything that merely looks like a
creative name.

**Conversions are NOT leads.** The PMax campaign's 24 platform conversions are carried as their own
`conversions` field and rendered in the benchmark table's Leads cell as `24 platform conv.`, the
same labelled treatment TTD's "no pixel" gets. They are deliberately **not** folded into `LEADS`:
that column holds LinkedIn lead-gen and Salesforce CS leads, and mixing a platform conversion in
would move a client-facing lead total and the Total row with it.

### The market bug this shipped with, and the rule that came out of it
The first deploy put this campaign in **SAARC**, not JP. Cause: **`_` is a single-character WILDCARD
in SQL `LIKE`**, so the India arm's `LIKE '%_in_%'` matched the `t-in-g` inside `..._Prospecting`,
and it sat above the JP arm. Both Google Ads arms now use the boundary-anchored
`REGEXP_CONTAINS(LOWER(x), r'(^|[ _-])jp([ _-]|$)')` form; `apac-xx` variants stay plain
`CONTAINS_SUBSTR` (a hyphen is not a wildcard). **Never match a 2-3 letter market token with `LIKE`.**
See the repo-wide note in `md/AGENTS.md`.
**Hardened 2026-08-15:** the pre-existing `'%_jp_%'` / `'%_kr_%'` arms in the LinkedIn arms of
`paid_media_model` / `paid_creatives_model` now use the same boundary-anchored form. They only
survived because the `apac-xx` arms above them fire first on every current LinkedIn name.
**Verified a strict no-op** — channel × market × imps × spend identical before and after across all
five channels (LinkedIn has no JP/KR delivery today, so this is forward protection only). **No
`LIKE '%_xx_%'` market token remains in live code in this client.**

## Channel filter chips (Paid Media tab, 2026-08-15)
A resetdata-style coloured chip row above the Markets chips: `renderPaidChannelChips()` /
`togglePaidChannel()`, with `deliveredChans()` (delivery in the date range + lane) as the roster and
`activeChans()` = roster ∩ selection. Everything channel-shaped already read `activeChans()`, so one
click removes a channel from the KPIs, charts, tables, creatives and footer at once.
- **Only channels WITH DELIVERY are rendered** (client, 2026-08-15) — nothing greyed out. Reddit and
  LINE are Q2-only buys, so under a Q3 view they are simply absent. Never advertise a channel this
  lane/range does not have.
- The **last channel cannot be unticked** (no blank tab), and the whole row **hides itself when only
  one channel is left** — a lone chip you can't untick is clutter, not a control.
- "Everything ticked" is stored as the **empty set**, so a channel added later can never be silently
  excluded, and the reset compares against the DELIVERED roster (not all of `PM_CHANS`) or you could
  never return to the all-selected state under a range where some channels never ran.

## The motion layer (2026-08-20) - aesthetics only, and how to tune it

> **This dashboard is NOT on the shared BB MOTION KIT, on purpose.** The kit
> (`scripts/motion_kit/`, applied to every other dashboard on 2026-08-20) is the portable, subtler
> subset of what is described below - one interaction vocabulary, a CSS-only wash, the same reveal
> engine, no canvas. This layer is richer and signed off as-is, so `apply_motion_kit.py` skips
> `cloudflare` and there is no marker block here. **Do not "unify" the two**: a kit run would
> replace the retuned aurora, the sweep bands, the KPI sheen and the travelling masthead rail with
> three drifting orbs. Fixes that belong to BOTH have to be made twice, deliberately.

Everything in this section is presentation. It changes how the dashboard ARRIVES, never what it
says: the whole layer can be deleted and every number, chart, filter and CSV is identical. Two
mechanisms touch rendered output and both restore it exactly - the bar reveal stashes the inline
`width` and puts the same string back, and the KPI count-up writes the ORIGINAL text on its final
frame. Verified by rendering the dashboard with and without the layer and diffing every tab's
text plus every bar width: identical across all four tabs.

**Where it lives** - three insertions in `dash/dashboard.html`, all marked:
- CSS: the `PREMIUM MOTION LAYER` block, deliberately the LAST thing in `<style>` so it wins the
  cascade over the rules it re-times.
- DOM: the `ANIMATED AURORA` layers right after `<body>`, plus `.topbar .rail`.
- JS: the `PREMIUM MOTION ENGINE` IIFE (`window.bbMotion`) just before `boot()`, plus a short
  `MOTION` block in the `Chart.defaults` section.

**The aurora** is one `<canvas>` (`#bbAurora`) carrying the swaying curtains AND the slanted sweep
bands, over four CSS orbs, under one static scrim (vignette + film grain). Dials, in the order you
should reach for them: `time +=` in `frame()` (how alive), the strip `opacity` in `build()` (how
present), `SCALE` (backing-store resolution), the orb alphas in the CSS.

**Performance is the whole design constraint here, and it is counter-intuitive.** Measured in a
software-rendered browser (no GPU - which is what a locked-down corporate laptop gives you):
- `filter: blur(18px)` on the full-viewport canvas: **61fps -> 3fps on its own.** A full-screen
  blur is re-applied every frame the canvas paints. It is gone; the softening now comes free from
  drawing the canvas at 28% scale and letting the compositor upscale it.
- three 170%-wide diagonal bands as DOM layers, animating opacity + transform: **half the frame
  rate** (25 -> 51fps when frozen). They are now drawn INSIDE the canvas - same shapes, one
  moving layer instead of four.
- `mix-blend-mode` on the full-screen grain forces the whole stack underneath, canvas included,
  to re-composite every frame. Dropped; 3% plain opacity looks the same.
- `blur(130px)` on the orbs was redundant - a radial gradient that fades to transparent is
  already soft.
The rule that falls out: **the cost is the NUMBER and SIZE of animated full-screen layers, not the
drawing inside them.** One low-res canvas is nearly free; four window-sized CSS layers are not.

**The reveal system** tags surfaces with `[data-bb-reveal]` and adds `.bb-in` on first
intersection. Two things there are load-bearing:
- `threshold: 0`, never a fraction. Threshold is the share of the ELEMENT that is visible, so a
  card taller than the viewport (the 1,000-row lead table) can never reach 6% and would sit at
  opacity 0 forever.
- the **watchdog** (`sweepStuck`): a second after any scan, anything still unrevealed but inside
  the viewport is shown unconditionally. Hiding content until an observer says so means a missed
  callback hides DATA - the animation is worth losing, the number is not. If it ever fires it is
  papering over a bug, and the dashboard still reads.
Re-scanning is driven by a `MutationObserver` on `<body>` (childList, rAF-coalesced) rather than by
editing 40 render functions, so anything a filter change re-renders animates in the same way.

**Type**: Inter is now actually LOADED (Google Fonts). The stack always named it but nothing
shipped it, so Windows rendered Segoe UI and macOS SF - the same dashboard in two typefaces.

**The login page** (`dash/main.py` `LOGIN_HTML`) was re-skinned to match: same dark base, same
warm aurora, same button/press/focus vocabulary. Its aurora is CSS-only - no canvas, no
requestAnimationFrame - because a login screen should not run an animation loop.


## EMEA top-of-tab summary sections (2026-08-27)

The **KPI strip**, **Leads vs target / Progress** and the **By-region summary** now render on
Core DG EMEA. They were APJ-only because they read the legacy `pacing.rows` model
(`salesforce_leads_live`), which holds **zero EMEA rows**. They are now fed from `cs_pacing`
instead - the same payload branch the Pacing detail section below them already used. **The legacy
model was NOT backfilled**: widening it would move live APAC numbers and desync the status-dash
checks. Code lives in the `BB:EMEATOP` block in `dash/dashboard.html`.

**They call the SAME four render functions as APJ** (`renderKPIs` / `renderLeadsTarget` /
`renderProgress` / `renderRegionGrid`), fed an agg-shaped object by `cspdTopAgg()`. That is the
whole design: a basis cannot drift between theatres if there is one implementation. All four pace
on **accepted / target**, which is what the client's sheet does (deficit = Planned - Accepted).

**Every target comparison on this tab is now ACCEPTED / target, on all three lanes** (Core DG APJ,
Core DG EMEA, Regional) - see "One basis for every pacing figure" below. An earlier version of this
paragraph said the Pacing detail band was "a different component" that answers a different question
and should not be harmonised; that was already contradicted 260 lines further down by the 08-27 fix
to `cspd_w_pace`, and the contradiction is most of why the by-market chart kept a delivered basis
for another week. **DELIVERED survives only as a delivery COUNT and as the acceptance/rejection
rate denominator.** If you add a panel that puts an actual next to a target, it uses accepted.

Verified 2026-08-27: accepted 265, delivered 306, rejected 41, unprocessed 253, flight target 830,
target due to date 192 -> **31.9% of plan against 23.1% time elapsed, 138.0% leads pacing**. The
pacing-versus-time comparison is the point of the section: a bare 31.9% reads as underperformance.

### Three things to keep right

- **The in-progress week is DAY-PRORATED, and it has to be.** Targets are seeded weekly, elapsed
  time is continuous, so counting a whole week's target the moment that week opens makes pacing
  lurch with no change on the ground - EMEA would fall from 138% to 103.5% between Thu 27 and Fri
  28 Aug. Each week contributes `target x (its days elapsed / 7)`, giving 131.8% on the 28th.
  **The legacy APAC model never had this bug** because its targets are seeded PER DAY
  (`ALLOCATED_TARGET`, ~4,400 rows a quarter); `cspdTopAgg()` reproduces that from weekly rows.
  **Testing trap:** on the last day of a week, days-elapsed and completed-weeks agree by
  coincidence (21 of 91 days = exactly 3 weeks on 27 Aug 2026), so a proration bug is invisible
  that day. Test a mid-week date - `scripts`-free harness in the git history, or simulate `Date`.
- **The flight is DERIVED FROM THE TARGET WEEKS, never from a stated end date.** Three sources
  disagree: 13 Friday-anchored weeks from 07 Aug -> **5 Nov**; the EMEA sheet's overall tab ->
  31 Oct; its Roverpath tab -> 30 Sep. Week 13 *starts* 30 Oct, so a 31 Oct end would make it a
  two-day week. `cspdFlight()` takes first week start -> last week start + 6 days = 91 days.
  **Confirm the real end date with Jade**; a correction arrives as CSV rows and needs no code.
- **EMEA is labelled "Flight", never "Q3".** 310 of its 830 (37%) falls in October, which is Q4,
  and drawing a time-elapsed bar against a calendar quarter it is not being bought in would be a
  straight misstatement. `periodLabel()`/`toDateWord()` are lane-aware and return
  `qtrLabel()`/`'QTD'` unchanged on APAC, so **every APJ caption is byte-identical**.

- **`cspdResolveScope()` must run before ANY read of `cspdRows()` (fixed 2026-08-28).** `CSPD`
  starts `{ book: null }` - the payload decides which books exist, so the selection is resolved on
  first read, not at boot. That resolution used to be a SIDE EFFECT of `cspdCfg()`, which only
  runs inside `renderCsPacingDetail()`. `cspdTopAgg()` runs *before* that in `renderAll()`
  (deliberately - `renderCsPacingDetail()`'s tail is `applyRegionPanelScope()` and must go last),
  so on the first paint `cspdBookOf(r) === null` matched nothing and **the entire EMEA top band
  rendered zeros off 0 of 169 rows** while the Pacing detail below it rendered correctly, because
  that section resolves the book itself. The theatre filter was never the problem: step 1 returned
  169 rows, the book step dropped all 169. It is now resolved in one function both callers hit -
  reordering the calls would only have traded this bug for the panel-scope one. **A third reader
  of `cspdRows()` must call `cspdResolveScope()` first too.**
  **The test that missed it** stubbed `CSPD = { book: 'Core DG' }` - it pre-set the exact state
  that breaks. When a bug depends on initialisation order, the harness has to start from the
  declaration in the file, not from a convenient value.
- **`cfg.period_label` is lane-aware, so the whole Pacing detail section follows.** It resolves to
  `Flight` off-theatre and to the payload's own label on APAC, which is what stops EMEA captions
  reading "whole Q3" / "265 of 830 Q3 target" for a flight that is 37% Q4.

**The five composition donuts render on EMEA since 2026-09-05** (client: "these updates we are
doing for APJ do it on EMEA too, just make sure no data will spill onto each other") - see
"Composition donuts on EMEA" below. **Still hidden on EMEA:** Best performing assets, the
leads-trend and the lead-detail table. They need lead-GRAIN rows that the v2 model deliberately
does not ship. `CSPD_ANY_THEATRE_BLOCKS` is the list that decides what renders off-theatre -
**adding an id there without repointing its data source at a v2 view renders an EMPTY panel under
an EMEA heading**, which is what it prevents.

### Composition donuts on EMEA (2026-09-05)

The APJ donuts aggregate the LEGACY lead rows in the browser (`aggregate()` over
`salesforce_leads_live`, APAC-only by its 13-ID allowlist). EMEA had no lead-grain rows in the
payload at all, so the five cards were hidden. Now:

| | |
|---|---|
| Lead grain | `sql/16_stg_cs_leads_v2.sql` - **+`JOB_FUNCTION`, `JOB_LEVEL`, `JOB_TITLE`** (passthrough) |
| Composition grain | `sql/19_cs_composition_v2.sql` -> `cs_composition_v2` (theatre x book x vendor x market x **dim x value**, LONG format, campaign to date) |
| Payload branch | `job/main.py` -> `cs_composition` (`{theatre, book, vendor, market, dim, value, accepted, unprocessed}`) |
| Frontend | `cscxDims()` -> `renderCompositionDonuts()` -> the SAME `donut()` APJ uses |

**Why long format and no day:** five dimensions in one block, one reader; a wide row per lead would
ship a job TITLE against a market at lead grain for no gain. The EMEA CS tab has no date control
(the top band is campaign-to-date), so the donuts are campaign-to-date too, like the band they sit
under. `DIM` values are the dashboard's own keys (`solutions / countries / jobFunc / jobLevel /
jobTitle`), so the reader is a lookup, not a translation table. Blank -> `Unknown`, the same label
`aggregate()`'s `lbl()` gives a blank on APJ, which is what lets every dimension sum to the same
total.

**No-spill guarantee, in three layers.** (1) The view carries `THEATRE`, and both theatres are in
it on purpose (the `18_*` reasoning) - a view silently holding one theatre is a trap the day APJ
migrates. (2) The dashboard filters it through **`cspdScopeOk()`** - the ONE predicate behind
`cspdRows()` (theatre + book + publisher + L3 market), factored out for exactly this - so the same
test that admits a pacing row to the band admits a composition row to the ring. APJ never reads
`cs_composition` (it keeps `aggregate()`), EMEA never reads the legacy rows. (3) The job asserts,
per (theatre, book), that **each of the five dimensions sums to `cs_pacing`'s accepted total** and
WARNs by name if not; the dashboard draws an `Unaccounted` slice on any shortfall. Verified in
BigQuery on apply: APAC Core DG 1,661 x 5, APAC Regional 63 x 5, EMEA Core DG 1,834 x 5, all `ties
= true`; and in the headless render the APAC and EMEA Country rings share no label.

**Ring total on EMEA = `cspdTopAgg().accepted`** (+ New in Admin View), i.e. the KPI strip's own
figure for the same scope - the two tie or the ring says so. An older JSON with no
`cs_composition` block hides both donut rows (`renderCompositionV2`) rather than drawing five
empty rings. The five call sites (ids, fold limits, lane counts) live in ONE function,
`renderCompositionDonuts()`, so the theatres cannot drift onto different charts.

**The scrolling legend (2026-09-05)** replaced the Chart.js legend on all five donuts, both
theatres: `plugins.legend.display=false` and `dlLegend()` draws a horizontal chip lane under the
ring (swatch / label / count, sorted descending, edge fades only on the side with more content,
hover a chip to isolate its slice, hover a SLICE to isolate AND scroll its chip into view, wheel
scrolls the lane but only preventDefaults while there is room, thin themed scrollbar,
`prefers-reduced-motion` turns the smooth scroll off). Card height is fixed by CSS (`.dl-ring`
172px + one or two lanes) whatever the category count - Country used to wrap its legend and
Professional demographic's legend overflowed the card. **Folds:** Country and Job function no
longer fold (every value gets a slice - which also removes the collision between Salesforce's
REAL `Other` job function, 128 leads, and the `Other (n more)` fold chip); only Professional
demographic folds (top 24 titles, two lanes). **Click-to-toggle survived:** a chip click calls
`chart.toggleDataVisibility(i)`, the same state the native legend drove, so `bbDonutCenter`
(vendored, untouched) keeps subtracting a hidden slice from the centre total. The AI deck
(`buildDeckPayload` -> `_bbTop(agg.*)`) and the CSV export read the AGGREGATE, never the legend
DOM, so they always carry the full set. Class prefix is `dl-` because `.chip` is the market chip.
Reference prototype the build was matched to: `donut-legend-scroller.html` (Build A, single lane;
Build C, two lanes) - not committed.

**Scope = theatre + book + publisher (`cspdRows()`), the same as the band below**, so the two can
never disagree - that disagreement is what this work existed to fix. Because the book/publisher
pickers sit further down the page, the strip carries a caption (`#csTopScope`) naming the scope,
the flight window and the days elapsed. A figure that moves with an off-screen control is worse
than no figure.

## CS Comparison on Core DG EMEA (2026-09-02, client request)

The **CS Comparison** tab now renders on the EMEA lane. It compares **market vs market inside one
period** - it is not a period comparison and it reads nothing from paid media. That matters,
because it had been gated on `emeaHasPaid() && emeaHasPriorQuarter()`: **two conditions the tab
never uses**. EMEA has neither, so a tab that could have been filled since 06 Aug stayed dark. The
gate is now `emeaHasCompare()` - does the payload carry Comparison rows for this theatre.

Code lives in the **`BB:EMEACOMPARE`** block in `dash/dashboard.html`, and it follows `BB:EMEATOP`
exactly: `cscAgg()` builds an **agg-shaped object** off the new `cs_compare` branch and hands it to
`renderComparePanel()`, which stays the **single** implementation for both theatres. A basis cannot
drift between theatres if there is one renderer. The legacy `salesforce_leads_live` model is
**untouched** - it is APJ-only by construction (campaign-ID allowlist, zero EMEA rows), and widening
it would move live APJ numbers and desync the status-dash accuracy checks.

### What was already there, and what actually had to be built

The market split needed **no work at all**, contrary to how this looks from Snowflake: every EMEA
campaign is named `EMEA-<region>` and `sql/16_stg_cs_leads_v2` has mapped six of them
(UKI / DACH / SEUR / NEUR / CEERI / MEA) since 2026-08-24. **Do not write a `COUNTRY_NAME` -> market
CASE for EMEA** - the campaign name already carries it, and a country-derived mapping would be a
second, disagreeing definition of the same dimension.

What was missing was **grain**. `17_cs_pacing_v2` aggregates to week x market x vendor, and the
panels need three things it throws away: **COUNTRY** (the drill-down; EMEA spans 33 countries, UKI
alone 13), **ASSET** (the "Best performing assets" list) and **DAY** (the tab is date-range driven,
and a range that cuts mid-week cannot be honoured from week buckets). So:

| | |
|---|---|
| Lead grain | `sql/16_stg_cs_leads_v2.sql` - **+`ASSET_1`, `ASSET_2`, `SERVICE`** |
| Comparison grain | `sql/18_cs_compare_v2.sql` -> `cs_compare_v2` (day x market x country x asset) |
| Payload branch | `job/main.py` -> `cs_compare` (~314 KB, 1,017 rows both theatres) |
| Frontend | `BB:EMEACOMPARE` + a theatre branch in `renderComparePanel` / `populateRegionSelects` |

`cs_compare_v2` carries **no targets**: those already ship on `cs_pacing` at their own grain, and a
second copy of a number that must agree is how two panels end up disagreeing. It covers **both
theatres** on purpose - only EMEA reads it today, but a view that silently held one theatre would be
its own trap the day APJ is migrated onto it.

### Four things to keep right

1. **Targets are MARKET grain, so they are not paced against under a country drill-down** (or a
   single publisher - the same rule `cspdResolveScope()` already applies). The plan has no country
   dimension, so a country's share of a market target is an allocation we invented. `hasTargets`
   goes false, the KPI prints `-` and **the target series is dropped from both charts** rather than
   drawn as a zero bar - a zero-high "target" beside real delivery reads as a plan that was missed.
2. **The weekly target is prorated** (`weekDueFraction`, shared with the Pacing detail band), or the
   figure lurches a full week's worth the moment a week opens. **Test mid-week**: on the last day of
   a week, prorated and whole-completed-weeks give the same answer by coincidence. EMEA's plan is
   heavily back-loaded (65/week for three weeks, then ~1,260/week from 28 Aug), so at 34 days
   elapsed only 1,805 of 12,058 is due - that is correct, not a proration bug.
3. **`resolveAssetSolutions` moved to module scope** when this became its second caller. It is one
   definition on purpose: the solution COLOUR MAP keys on those exact strings, so two copies would
   eventually give one asset two colours on two tabs.
4. **`SERVICE`'s CASE is a second copy of the one in `sql/13_pacing_model.sql`** and the two must
   move together. Not shared yet because `sql/13` sits on the live APJ path and factoring it out
   would put every headline APJ number through a new join for a cosmetic label. **Follow-up**: hoist
   both onto a shared campaign -> solution view, the way `04b_campaign_program` was done on
   schneider.

### Verified 2026-09-02

`cs_compare` reconciles **exactly** to `cs_pacing` - the same lead universe, independently
aggregated - on both theatres and on every market:

| | UKI | DACH | SEUR | NEUR | CEERI | MEA |
|---|---|---|---|---|---|---|
| Accepted | 240 | 169 | 181 | 170 | 126 | 192 |
| Rejected | 51 | 32 | 24 | 24 | 12 | 26 |
| Acceptance | 82.5% | 84.1% | 88.3% | 87.6% | 91.3% | 88.1% |
| Countries | 13 | 5 | 6 | 7 | 11 | 7 |

Theatre totals: EMEA 1,078 accepted / 169 rejected, APAC 1,724 / 313 - **zero delta against
`cs_pacing` on both**.

**EMEA assets are almost entirely the file-slug naming convention** (`26Q3_EBOOK_accelerating-ai-
adoption-with-sase`), with one short code (`A-MSM-11`) leading. They render through
`prettyAssetName()`'s fallback, which is the point of that fallback - an unmapped variant looks
unfamiliar rather than looking broken. Fold a new one into `ASSET_ALIASES` when it earns a name.

### The date control is now PER TAB on this lane

`PROGRAMS.core_emea.dateControl` was `false` because nothing EMEA rendered responded to the range.
The Comparison tab does, so it is now `['compare']` and `applyDateControl()` resolves it per tab -
the picker appears on Comparison and nowhere else on the lane. Add a tab key there the day another
EMEA tab gains range-driven content; `true` shows it everywhere.

## Pacing detail + Core DG EMEA (2026-08-24)

A **Pacing detail** section on the Content Syndication tab, directly under "Pacing - target vs
actual", and **`core_emea` promoted from a disabled placeholder to a live lane** - which brings
**EMEA** onto this dashboard for the first time. Client-approved layout; built from
`cloudflare_cs_build.sql` (Transmission's Snowflake DDL) as the logic reference.

**EMEA is reached through the topbar lane dropdown ("Core DG EMEA"), not its own control.** An
APAC/EMEA toggle was built beside the date picker first and **removed the same day** (client
request): the lane dropdown already existed, already gated tabs per lane (`PROGRAMS[...].tabs`
-> `applyLaneTabs`) and already had a `core_emea` entry, so a second control meant two ways to
say the same thing - and two things that could disagree. `currentLane` is now the single source
of truth; `laneTheatre()` derives the theatre from it and `cspdTheatre()` is the only reader.
Adding a third theatre is a `PROGRAMS` entry + an `<option>` + CSV rows.

**Where each piece lives**

| piece | file |
|---|---|
| Targets (committed CSV -> BQ) | `targets/cs_targets_q3.csv` -> `seed_cs_targets_q3` (`seed_static.py`) |
| Lead grain, name-scoped | `sql/16_stg_cs_leads_v2.sql` -> `stg_cs_leads_v2` |
| Book x week x market x vendor | `sql/17_cs_pacing_v2.sql` -> `cs_pacing_v2` |
| Payload branch | `job/main.py` -> `cs_pacing` (+ a per-theatre-x-book audit line every run) |
| UI | `dash/dashboard.html` -> `#cspdSection`, `renderCsPacingDetail()`, `PROGRAMS.core_emea`, `laneTheatre()` |
| Campaign (book) picker + publisher table | `dash/dashboard.html` -> `cspdRenderBookSel()`, `cspdRenderVendorTable()`, `#cspdVendorCard` |

**It runs in BigQuery, not Snowflake, on purpose.** The build script creates views in
`CLOUDFLARE_SANDBOX.CS_REPORTING`, but our pipeline role there is **read-only** (same reason
the KR campaign-scope fix still isn't applied), and the base table is *already* in the shared
mirror and *already* in this client's freshness gate. So the logic is ported 1:1 into
`client_cloudflare` views and the targets became a committed CSV, per the repo's
committed-CSV->BQ standard. No ingest change, no gate change, and the targets are
version-controlled instead of living in DDL nobody here can re-run.

**It cannot move an existing number.** `sql/10_salesforce_leads_live` is untouched. `16`/`17`
are a parallel read of the same mirror, `cs_pacing` is a separate payload branch, and the whole
section hides itself when that branch is absent - so an older `cloudflare.json` renders exactly
as it did before. Verified: 600 inserted lines, 0 removed.

**Reconciliation** (2026-08-24, matches the client's pacing sheet exactly):

| | Target | Delivered | Accepted | Rejected | Needs review |
|---|---|---|---|---|---|
| EMEA | 830 | 234 | 208 | 26 | 0 |
| APAC | 2,290 | 1,591 | 1,365 | 226 | 0 |

APAC delivery runs **ahead** of the sheet because this is live off Salesforce and the sheet is
a snapshot. That is expected.

### Regional campaigns + publishers (2026-08-27, Lydia's request)

> *"For Content Syndication, please add regional campaigns/publishers to the pacing dashboard
> i.e. DemandAI, Interlink and SitPub."*

**DemandAI and Interlink were being DROPPED, not just hidden.** `16_stg_cs_leads_v2` excluded
`SEG_PROGRAM = 'ANZ DnB'` outright, and their Salesforce campaign IDs
(`701RG00001aeA3kYAE` / `701RG00001aetXiYAI`) are not in the 13-ID allowlist behind
`10_salesforce_leads_live` either - so they appeared **nowhere on the dashboard at all**.
They are now in scope as their own **BOOK**, and the section gained a **Campaign picker** and a
**Delivery by publisher** table.

**`BOOK` is a plan, not a region - keep the two apart.** ANZ DnB runs in ANZ, i.e. inside APAC,
on the same Monday week anchor, so modelling it as a third *theatre* (which the old code comment
suggested) would have been a lie about the region and would have forced it into the topbar lane
dropdown. It is a second dimension: `BOOK` in `sql/16` -> `sql/17`'s join key -> the seed CSV ->
`cs_pacing.rows[].book` -> the picker.

**Books are never summed, and there is deliberately NO "all campaigns" option.** Only Core DG has
a seeded target sheet (APAC 2,290 / EMEA 830); an all-books selection would divide combined
delivery by one book's target and report a pacing figure that is wrong in the *flattering*
direction. `Target` prints "no target" rather than 0 where a book has no sheet (a 0 reads as a
target of zero and would make Pacing look infinitely ahead).

**The Delivery by publisher table FOLLOWS the Campaign picker (2026-09-04, John: "I thought we
agreed we would move DemandAI and Interlink as these are DNB campaigns only in Australia").**
From 2026-08-27 to 09-04 it was the one cross-book panel - it spanned every book in the theatre
so the regional publishers had somewhere to appear at all - which put DemandAI and Interlink in
the Core DG view under a REGIONAL badge, and its caption read "every campaign in APAC, not just
the one selected above". The badge made the tagging right and the scope wrong. It now reads the
same book-scoped rows as the band above it (`cfg.rows`, not the removed `cfg.allRows`), so Core DG
lists Roverpath / VRSM Lead Magnet / Final Funnel and Regional lists DemandAI / Interlink - **the
regional publishers are scoped, not hidden** (Lydia's ask still stands; they render in full with
the picker on Regional, and the footnote drops its "internal allocation" sentence there because
no publisher in that book carries a target). Per-publisher figures are unchanged by construction:
the same `book x vendor` aggregate, filtered. Verified in a headless render of the built page
against the live payload: Core DG APAC 852 + 400 + 409 = 1,661 accepted, Regional DemandAI 71
delivered / 62 accepted, Interlink 1 delivered / 45 pending review; EMEA rows and figures
identical (only its caption changed - it no longer claims to span every campaign, and it does not
mention the Campaign picker there because a single-book theatre hides it).
**Sweep result, same day:** every other panel in the Pacing detail section and the CS Comparison
tab already read `cspdRows()` / `cspdResolveScope()` (book-scoped). The only theatre-wide readers
left are the picker's own book list, the dev-only targets-staleness check (`weeksAll`, a fact about
the seed), and the market CHIP roster (`cspdAllMarkets()`, a roster not a figure). The legacy APJ
CS panels above the section (KPI strip, region cards, weekly chart - `sql/10`) are not book-aware
at all: the 13-ID allowlist makes them Core DG by construction, so they do not move when the
picker is set to Regional. That is the documented two-model split, not a scope leak.

**The Core DG numbers did not move, and that was the acceptance test.** APAC Core DG
2,290 / 1,708 / 1,460 / 248 and EMEA 830 / 306 / 265 / 41 are identical before and after,
verified in BigQuery and in a headless render of the built page. Regional adds 72 delivered /
63 accepted / 9 rejected alongside them.

**`SitPub` does not exist in the Salesforce feed under any spelling** (checked every campaign
name in `salesforce_cs_apac_all`, all quarters, for `PUB|SIT|SITU|REGISTER`; the only hits are
the `ACQUISITION` token, which contains "sit"). Nothing was invented for it. Vendors are
discovered from the data, so it appears on its own the day its first lead lands - exactly as
Pipeline360 and Inbox Insight did.

**Publisher display names are now aliased in `sql/16`** (`DEMANDAI` -> `DemandAI`,
`INTERLINK` -> `Interlink`, `PIPELINE360` -> `Pipeline360`, `INBOXINSIGHT` -> `Inbox Insight`).
Salesforce carries recent publishers in SHOUTY caps and older ones in title case. **`Roverpath`,
`Final Funnel` and the `VSRM` -> `VRSM Lead Magnet` alias are load-bearing**, not cosmetic: they
are the join keys for the seeded targets. Unmapped spellings fall through unchanged.

**The `Unclassified` book is the safe residual, not dead code.** The programme list in `sql/16`'s
`BOOK` CASE is explicit, because this feed churns fast - `GENERAL`, `VER-RETAIL` and `EXP` all
appeared inside one week in Aug 2026. A ninth programme lands in `Unclassified`, is counted, is
selectable, and is WARNed about by name in the job log; it is never folded into Core DG, where it
would inflate delivery against a fixed target. Mapping it is one line in that CASE.

**~~Still deliberately out of scope: `SEG_PROGRAM = 'EXP'` and `VENDOR = 'ACQUISITION'`.~~ DEAD -
both exclusions were REMOVED 2026-08-31 and both of this note's premises were wrong.** Jade
confirmed Acquisition IS a CS partner (streams 2&3 of the "Q3 EMEA Content Syndication" plan, CPL
$32, with seeded weekly targets), and CF1 EXP is a bought line on the same plan; the extra
`EXP` segment sits AFTER the three segments the view parses, so region and vendor were never
shifted. Its 482 rows were all `New` when the exclusion was written and were mostly DELIVERED by
08-31 (EXP UKI alone 60 accepted / 17 rejected), so by then the exclusion was hiding real delivery
from the pacing figures. `sql/16_stg_cs_leads_v2.sql` carries the live reasoning - kept here only
so the old instruction cannot be followed by mistake.

**A count-up race in the motion layer was fixed here too** (`countUp` in `dash/dashboard.html`).
The last frame of the 780ms animation wrote back the string captured when it STARTED, so a figure
re-rendered inside that window - scroll the section into view, then immediately change the
campaign, publisher or week - was overwritten with the *previous scope's* number and stayed there
until the next render. Each frame now bails if anything else has written to the element, so the
render function always wins. **The same bug is in `scripts/motion_kit/kit_js.tpl` line ~48** and
therefore in every kit-injected dashboard; fixing it there is a separate estate-wide re-inject.

### Weekly pacing + what the publisher targets actually are (2026-08-27)

**`cspd_w_pace` paces on ACCEPTED, not delivered.** It used to divide DELIVERED by target while
the Lead deficit tile *in the same card* measured ACCEPTED against the same target, so the two
openly contradicted each other - EMEA w/c 08-21 read "112.5% - 72 vs 64 target" (ahead) beside
"Lead deficit 7 - accepted leads behind target" (behind). Accepted is what the plan is bought in
and what every other pacing figure on the tab already used (the campaign-to-date band, the
publisher table, the deficit tile). The caption now names the metric - "57 accepted vs 64 target" -
so nobody re-derives it. (The `Delivered` tile it used to sit beside became an **Accepted** tile on
2026-09-04 - see "The weekly card's headline is accepted" below - so the whole card now reads in
one unit.)

Two weeks change verdict, and **both flips move INTO agreement with their own deficit tile**:
EMEA 08-21 112.5% -> 89.1% (deficit 7) and APJ 07-27 105.6% -> 90.0% (deficit 18). Every other
week keeps its verdict and just drops by that week's rejection rate. **Nothing that reconciles to
the client's sheet moves**: the campaign-to-date band (APJ 1,450 of 2,290 / 63.3%), the top KPI
strip and every delivered/accepted/rejected count are untouched. Only this one tile.

> **This change fixed the TILE and left the CHART below it on delivered** - closed 2026-09-03, see
> "One basis for every pacing figure". The lesson is worth more than the fix: the note above says
> "Only this one tile" as reassurance about blast radius, and it was accurate, but *"which other
> panel on this card compares an actual to the same target?"* was never asked. Sweep the whole card,
> not the one element in the ticket.

### One basis for every pacing figure (2026-09-03, Jade)

**Client decision, via the Internal Notes widget: "for the weekly lead pacing, instead of
'delivered' we should show accepted".** Reported after Jade queried the KR/JP region cards in
Teams; the cards were already accepted-based, and the panel actually disagreeing with them was the
**by-market chart** - the last target comparison on the tab still measuring DELIVERED
(accepted + rejected).

**One change: `cspdRenderMarketChart()` aggregates `accepted` instead of `delivered`** (frontend
only - the payload, the views and the counts all already carried both). The card is retitled
*Accepted vs target by market* (*Accepted by market* on a book with no target sheet, e.g. Regional)
and its caption now names the basis.

How badly the two disagreed, on one card, for the same week: at w/c 31 Aug the weekly tile read
**169 accepted vs 98 due** while the chart underneath it totalled **211 against a 171 target**.
Jade's w/c 24 Aug example was the same shape - 174 vs a 173 target looked exactly on plan, when the
week had delivered 136 accepted against 173.

**It was NOT counting unreviewed leads** (the standing suspicion, ruled out): w/c 24 Aug is
136 accepted + 38 rejected = 174 delivered, and its 64 pending sit in the UNMAPPED bucket the chart
already excludes. `IS_DELIVERED` in `sql/16` has always been `Accepted|Rejected` only.

Values that move, all three lanes (Core DG APJ, Core DG EMEA, Regional - one component serves them
all, so a single edit covers all three). Every week drops by exactly its own rejected count:

| lane / selection | target | before (delivered) | after (accepted) |
|---|---|---|---|
| APJ Core DG, w/c 31 Aug | 171 | 211 | **169** |
| APJ Core DG, w/c 24 Aug (Jade's) | 173 | 174 | **136** |
| APJ Core DG, Q3 to date | 1,599 | 1,965 | **1,661** |
| EMEA Core DG, w/c 28 Aug | 1,268 | 208 | **185** |
| EMEA Core DG, Flight to date | 1,986 | 1,247 | **1,078** |
| Regional (ANZ DnB), w/c 3 Aug | no target | 71 | **62** |

**Left alone deliberately:** the campaign-to-date band's `Delivered` tile and the publisher
table's Delivered column (delivery counts, not pacing; the WEEKLY card's Delivered tile went on
2026-09-04, see the next section); the acceptance and rejection RATES (accepted + rejected is the
correct reviewed-lead denominator - it is what makes the two sum to 100%); the by-region cards and
the KPI strip (already accepted); `cspdDefaultWeek()` / the `qtd` cut-off / the `noDeliveryYet`
guard, which test `delivered > 0` to mean *"has this week been reviewed at all"* - a reviewed-ness
test, not a pacing basis, and the caption already says "no processed delivery yet".

`sql/17_cs_pacing_v2.sql`'s **`WEEKLY_PACING`** column moved to `ACCEPTED / TARGET` in the same
change. It divided DELIVERED by TARGET while `LEAD_DEFICIT`, three lines below it in the same
`SELECT`, measured ACCEPTED - so one column called w/c 24 Aug 100.6% of plan and its neighbour
called it 37 short. Neither column reaches the dashboard (`job/main.py` carries only the counts),
so this is purely for anyone querying the view directly - which is exactly who a disagreeing basis
misleads. **Needs `sql/deploy_views_cloudflare.ps1`; the dashboard change needs
`dash/deploy_dash_cloudflare.ps1`. No job or payload change, so no forced run is required and the
status-dash accuracy checks (which compare the JSON to BigQuery counts) cannot move.**

**Verified by internal consistency, not against fixed numbers** (this data moved twice on the day):
a headless render of the real `cloudflare.json` across all 3 lanes x every delivering week x the
cumulative chip (19 scenarios) confirms only the market chart's title, caption and series changed -
band, weekly tile, weekly chart, rejection chart and row sums byte-identical - and 16 assertions
pass: the chart's accepted total equals the accepted the pacing tile prints for the same selection;
accepted + rejected = delivered and accepted + rejected + pending = total leads (checked against
the independent `cs_compare` block) every week; weekly accepted sums to the band's Accepted tile
(APJ 1,661 / EMEA 1,078 / Regional 63) and to the EMEA region cards; target sums by market equal
target sums by publisher (APJ 2,290, EMEA 12,058); and monthly totals equal weekly totals.

### The weekly card's headline is accepted (2026-09-04, Jade)

**Same client instruction, one panel further.** The 09-03 change put every target COMPARISON on
accepted; what it left behind was the weekly card's own headline TILE, still labelled `Delivered`.
So the card read `Delivered 174` in its largest figure, immediately left of a pacing tile whose
caption said `136 accepted vs 173 target` - the exact pair of numbers Jade's example was about, on
one card, in two units. A reader taking the headline at face value re-derives the delivered-vs-
target comparison the 09-03 fix removed from the chart.

**`cspd_w_del` -> `cspd_w_acc`, printing `w.accepted`.** The delivery count is NOT dropped: it
moves to the tile's `.cnt` sub-line as *"N delivered (reviewed)"*, which also keeps the
acceptance/rejection-rate denominator on screen next to the rates themselves. The id was renamed
rather than left pointing at a different measure - an id that says `del` while holding accepted is
how the next person re-introduces the bug.

**Frontend only, one file.** No `sql/`, no `job/main.py`, no payload key - `accepted` and
`delivered` have both been in `cs_pacing` since the section was built, and `cspdSum()` already
returned both. Needs `dash/deploy_dash_cloudflare.ps1` only; no forced job run, and the status-dash
accuracy checks cannot move.

**Still `Delivered`, still correctly so:** the campaign-to-date band at the top of the section
(which pairs Delivered WITH Accepted, so neither can be mistaken for the other) and the publisher
table's Delivered column. Both are delivery counts that nothing paces against.

**The transferable half** is the repo-wide rule this section already carries one level up: a basis
is a property of the CARD. 08-27 fixed the tile and left the chart; 09-03 fixed the chart and left
the headline. Each pass swept what the ticket named. When you next change a basis, enumerate every
figure in that card - including the ones that state no target at all, because a headline in the
wrong unit is what the reader paces by eye.

**The two-model gap on APJ is CLOSED (2026-09-04, client report: "publisher table RP+VRSM+FF =
1,661, top says 1,650, Pacing detail says 1,661").** The region cards and KPI strip read the LEGACY
`pacing` model (`sql/10`, campaign-ID allowlist, COUNTRY_NAME markets) while the Pacing detail band
reads `cs_pacing` (`sql/16`, campaign-NAME scope). The 11 leads were two defects, both on the legacy
side, plus one latent one on the v2 side - see "Headline vs Pacing detail: the 1,650 / 1,661 fix"
under Gotchas for what moved and how to re-verify. Both models are now expected to agree on the
APAC Core DG accepted total at the Q3 default; a future gap is a bug, not a documented split.

**The per-publisher targets are an INTERNAL ALLOCATION - now APJ-ONLY** (the EMEA Roverpath/
Final Funnel 1:1 rows described below were REMOVED 2026-08-31 - superseded Stream 1 scope, see
the streams 2&3 block; **the EMEA vendors seeded 2026-08-31 are CLIENT-SET**). Cloudflare's Core DG
plan sets targets per MARKET per WEEK and has no publisher dimension at all - the supplied sheet
(`raw files/CF_FY26 Q3_Core DG Lead Pacing...csv`) is Week / Date / Region / Country and never
names a vendor. The split in `targets/cs_targets_q3.csv` was applied when the seed was built:

| theatre | split | evidence |
|---|---|---|
| EMEA | flat **1:1** | all 78 market x week cells IDENTICAL for Roverpath and Final Funnel; 830 -> 415 / 415 |
| APAC | flat **2:1:1** | every market (ANZ 470/238/235, ASEAN 209/106/104, Japan 122/62/60 ...), rolling up to the client's market totals EXACTLY - 943/419/220/309/244/155 = 2,290 |

So the MARKET, WEEK and THEATRE totals are client-set and reconcile to their sheet; the
per-publisher slice is ours. **APJ's 2:1:1 has exactly the same status as EMEA's 1:1** - APJ's
64.9% / 63.1% / 60.5% are no more client-set than EMEA's 39.8% / 24.1%.

**The decision (client, 2026-08-27) was to KEEP the percentages and label them**, not blank them:
the allocation is how the book is actually run, so the figure is useful as long as nobody reads it
as a commitment. The footnote under *Delivery by publisher* leads with "Publisher targets are an
internal allocation of the market plan, not a client-set target. Publisher pacing is indicative."
on **both** theatres, then keeps the existing "no lead target is loaded for X, Y" sentence.

**`CSPD_PUBLISHER_TARGETS_ARE_REAL` is deliberately `true`.** It means "the UI may pace against the
seeded publisher target". Setting it `false` makes every target-shaped figure fall back to its
existing no-target copy wherever a single publisher is selected - the band, the weekly tile, the
market chart and the table together, so they cannot disagree. That path is wired and tested; it is
one line if the labelling ever proves not to be enough. **The suppression must stay all-or-nothing:
fixing only the table would leave it reading "no target" under a band still showing 63.1%.**

### Streams 2&3 targets + Acquisition (2026-08-31, per Jade)

`targets/cs_targets_q3.csv` carries the EMEA Core DG flight target of **12,058**, all from the
APPROVED "Media Plan 29-07-26" tab (the tab's own header total): **Pipeline360 3,039 + Inbox
Insight 2,714 + Acquisition 3,740** (174 rows, per-publisher, client-set) **+ the IDE Lite
line 2,565 split Roverpath 1,666 / Final Funnel 899** (156 rows). The plan's own notes say
"IDE Lite is Rover Path and Final Funnel", but the client has NOT confirmed the split - the
loaded ratio is delivery-to-date (271:148 at 2026-08-31, per Calvin, INTERIM), generated by
the committed **`targets/build_ide_lite_split.py`** (change `IDE_LITE_SPLIT`, rerun, reseed,
force the job when Jade answers - one line) and labelled interim in the publisher-table
footnote. History: the total briefly read 10,323 (a stale 830 Roverpath/FF allocation from the
SUPERSEDED "Media Plan 28-07-26 - Stream 1" scope sat under the 174 rows - removed
2026-08-31), then briefly 9,493 with no IDE Lite at all, which KILLED weekly pacing: all
delivery to date sits in weeks 1-3 and only IDE Lite carries week 1-3 targets. Only IDE Lite's
line spans all 13 weeks - streams 2&3 targets start at plan week 4/5 by design. Source:
the client's own **"Cloudflare EMEA - Q3 Content Syndication Pacing.xlsx"**, sheet
`Media Plan 29-07-26`, columns **X-AJ** (per publisher x region x week, six campaign blocks:
CF1 ACQ / CF1 EXP / Modernize Security / Retail / BFSI / Closed Lost, DT+ST lines summed).
**These are CLIENT-SET per-publisher targets**, unlike the Stream 1 / APJ allocation above -
the *Delivery by publisher* footnote now says so per vendor (`CSPD_CLIENT_SET_VENDORS` in
`renderCsPacingDetail`'s note block).

- **Week mapping: each plan week maps to the Friday bucket that CONTAINS its Monday** (W1 =
  Mon 08-03 -> Fri 07-31 ... W13 -> Fri 10-23), and sql/16's EMEA anchor is **2026-07-31** to
  match. Mapping the Monday to the FOLLOWING Friday instead (the original by-number mapping)
  ran a full bucket late: plan W4's targets sat in the 08/28 bucket while ALL of that week's
  delivery (dated 08-24..08-30) lands in 08/21 - flight-to-date target read 192 instead of
  ~720 (fixed 2026-08-31, Calvin). Both anchors are Fridays, so the remap moved NO lead dated
  on/after 08-07; only leads dated 07-31..08-06 shift into their true 07-31 bucket. Weekly
  buckets still smear the plan's Monday weeks by 3 days; quarter totals reconcile exactly.
- **The seed's TARGET is INT64 and the plan's weeklies are fractional** (32.22/wk etc.) - each
  plan LINE was rounded week-by-week with cumulative rounding so every line total, and so every
  vendor total, matches the sheet EXACTLY. Rebuild script: the conversion lives in the git
  history of this change; re-runs must re-assert vendor totals 3,039 / 2,714 / 3,740.
- **`sql/16` scope changes with it**: the 2026-08-27 exclusions of `SEG_PROGRAM='EXP'` and
  `VENDOR='ACQUISITION'` are REMOVED (Jade confirmed Acquisition is a real streams-2&3 partner;
  its 482 rows had become 475 DELIVERED, and CF1 EXP is a bought line on the same plan).
  `ACQUISITION` -> 'Acquisition' joined the vendor alias map; `EXP` joined the Core DG book
  list. **Verified 2026-08-31: all five APAC vendor rows byte-identical before/after; admitted
  exactly Acquisition's 482 leads + Pipeline360's 56 EXP leads (both named in advance -
  the md/AGENTS.md scope-fix rule).**
- **Expect the vendors' early delivery to sit in week 08/21 with no target** - the plan's first
  counted weeks are W4/W5 (08-24 / 08-31 Mondays) and the partners front-loaded ~650 leads just
  before that. The FULL OUTER JOIN shows both sides; it is the plan's own schedule, not a bug.

### Current state (recorded 2026-08-31, verification pass)

**Deployed:** `cloudflare-dash-00146-cwt` (dash), `cloudflare-export` image from `bd27b7d`
(carries `ga_campaigns`). Batch commits: `bd27b7d` + `a1b66ca` on the dev branch; the
2026-08-31 verification pass (EMEA 9,493 correction, config lock) is the commit after those.
Deployed artifacts == committed files, verified by hash at each push.

**Live from the 2026-08-31 batches:** EMEA flight target 12,058 (streams 2&3 client-set 9,493
+ IDE Lite 2,565 interim-split across Roverpath/Final Funnel; the superseded 830 removed),
the **cspd weekly pacing chart** (`#cspdWeeklyChart`, target vs accepted per week, both
theatres), Acquisition + EXP in scope, Google Ads plan benchmarks + CPC actual-only + PMax
strip, canonical solution labels, creative names decoded to asset names, Google Ads creatives
restored to the creative tables/switcher, section-header wrap fix, exact-domain test-lead
filter (sql/10/14/16).

**TEMPORARY (2026-09-01, Ian, for the client WIP meeting):** the By-region summary cards HIDE
the Flight Target row on the EMEA lane (`showFlight` in `renderRegionGrid`) - the whole-flight
number dwarfed the other bars. The value stays in "Leads vs target" above; Ian is raising the
presentation with John. Restore = flip `showFlight` (hint text follows automatically). APJ
cards unchanged.

**Blocked - do not build until the owner moves:**
- One-solution-per-asset: mechanism WIRED, `ASSET_SOLUTION_MODE='stacked'` deliberately -
  waiting on the CLIENT's rule via Jade (highest volume / original solution / master mapping).
- IDE Lite split ratio: INTERIM (delivery-to-date 271:148) - waiting on JADE's confirmed
  Roverpath/Final Funnel split; one-line change in `targets/build_ide_lite_split.py`.
- Asset table layout rework: waiting on JADE's spec.
- Channel/TTD chart fix: waiting on the SCREENSHOT of what's wrong.
- PMax benchmarks: NONE exist in the Q3 workbook - the strip says so; nothing to grade until
  the client supplies one.
- Asset codes `A-MSM-10` / `A-MSM-11` / `G-MSM-2`: unresolved in `ASSET_NAMES` - waiting on
  titles from the client; they render as `concept ...` meanwhile.
- Snowflake `V_SALESFORCE_CS_APAC_CLOUDFLARE`: PARKED - corrected DDL is committed at
  `snowflake_v_salesforce_cs_apac_cloudflare.sql`, needs a manual ACCOUNTADMIN paste (Calvin),
  and NOTHING in our pipeline reads it.

### 2026-08-31 batch (Calvin's EDA list)

- **Solution labels are the client's canonical forms** - `sql/13`'s SERVICE CASE emits
  `Modernize Security` / `Modernize Network` / `Modernize Applications` (was `Modernized X`).
  The match was always SUBSTRING, so both campaign-name vintages were already folded into one
  row - only the labels moved; per-solution totals are byte-identical. The assets chart's
  `solColors` map keys on these exact strings (legacy spellings kept as fallbacks) - rename
  together. A POSITIONAL solution parse (which mis-files 333 EMEA EXP leads under 'CF1' and
  splits the Modernize(d) pair 970/684) exists only in Snowflake-side EDA, never in this model.
- **Google Ads creatives were silently ABSENT from the Top/Bottom creative tables** from the
  channel's launch (2026-08-11) until 2026-08-31: the creatives feed says `'Google Ads'` while
  `activeChans()` keys say `'GoogleAds'`, and the unnormalised compare dropped every row - and
  kept the channel out of the CHANNEL switcher. `creativeChanKey()` normalises both spots;
  `CH_LABEL`/`creativePill` know the channel now. Same class as the ASSET_ALIASES lesson: two
  spellings of one key, and the miss is silent.
- **PMax strip** (`#gaPmaxBlock`, `renderGaPmaxNote`) under the video block: platform
  conversions, cost per conversion, and Google's 50-conversion validity bar, whole-flight from
  the new `paid_media.ga_campaigns` payload branch (job queries `stg_google_ads` at campaign
  grain; spend grossed by `bbApplySpendMult` like every money field). The Q3 benchmark workbook
  covers NO PMax metric - its $411 cybersecurity CPL is for qualified leads - so cost per
  conversion renders as an ACTUAL with that stated, never a vs-zero grade.
- **Creative names decode to CS ASSET names** (2026-08-31, client approved): a `[GA]-XXX-n` or
  bare short-code token in a creative name resolves through `ASSET_NAMES` and LEADS the row's
  label (prettyCreative), so the creative tables and the CS assets chart speak one language.
  Raw name stays in the row tooltip; an unmapped code keeps the old 'concept XXX-n' render
  (never blank/Unknown). Unresolved at 2026-08-31: A-MSM-10, A-MSM-11, G-MSM-2 - add them to
  ASSET_NAMES when the client supplies titles. Google Ads rows skip prettyCreative entirely
  (their label is already 'campaign - Network').
- **One-solution-per-asset resolver is WIRED but OFF** (`ASSET_SOLUTION_MODE = 'stacked'` +
  `ASSET_SOLUTION_OVERRIDES` next to the assetAgg build): 'dominant' collapses each asset's
  bar to its highest-lead solution, 'override' consults the client's master mapping first.
  Waiting on Jade's rule - flipping it is a one-word edit + dash redeploy; totals never move.
- **Section header rows (`.section`) wrap** (`flex-wrap:wrap`, and the creative CHANNEL seg is
  `flex:0 0 auto`): on a narrow window the right-pinned seg used to run past the page edge and
  its last button clipped mid-word ("Trade..." - client screenshot). Verified 700-1500px: no
  clipped control, no body horizontal scroll, on every tab and lane.
- **`snowflake_v_salesforce_cs_apac_cloudflare.sql`** is the corrected DDL for Calvin's broken
  Snowflake EDA view (base table gained LEAD_STATUS_SF; `t.*` returned 29 cols vs 28 declared).
  Nothing in our pipeline reads it. Needs ACCOUNTADMIN to apply - see the file header.

### Gotchas - read before editing

- **The Transmission test-lead filter must stay identical in `sql/10` and `sql/16` (fixed
  2026-08-27).** `sql/16` shipped without it, so the Pacing detail band counted 12 test leads as
  APAC delivery (10 accepted / 2 rejected) and 1 more sat unprocessed on EMEA - which is why the
  APJ KPI strip (reads `10_*`) and the Pacing detail band (reads `16_*`) printed different totals
  on the same screen. Both now use `LOWER(SPLIT(EMAIL,'@')[SAFE_OFFSET(1)]) NOT LIKE
  '%transmission%'`. **Filter on the email DOMAIN, never on the string `test`**: a genuine
  rejected lead from **Advantest Corporation** (`advantest.com`) carries `test` in its company
  name and its domain. Nothing in `status_dashboard` verifies `16_*`, so a future divergence here
  is invisible to the accuracy monitor - keep the two predicates in sync by hand.
- **Headline vs Pacing detail: the 1,650 / 1,661 fix (2026-09-04).** The client summed Roverpath +
  VRSM + Final Funnel in *Delivery by publisher* (1,661), matched the Pacing detail band (1,661),
  and found the KPI strip 11 short (1,650). Three causes, three fixes, all in one change:
  1. **10 leads - VRSM's Korean leads fell to `OTHER`.** `sql/10`'s KR arm is campaign-scoped
     (client decision 2026-07-02: Korea counts only on the Core DG campaigns, not the N*/P*
     Modernize ones). The Q3 **VRSM Lead Magnet** campaign (`701RG00001W1FQRYA3`) joined the
     13-ID allowlist on 2026-07-10 - AFTER that decision - and was never added to
     `segments.KR`, so its Korean leads (10 accepted at 09-04) landed in `OTHER`, which is not a
     chip, and vanished from every headline figure while `sql/16` (market from the campaign
     name) booked them under Korea. Fixed in `definitions.json` (`segments.KR.campaign_ids`, now
     7) -> `definitions_seed.py` -> `seed_kr_campaign_ids`; the status verifier builds its KR /
     OTHER checks from the same file (LIVE copy `gs://bidbrain-analytics-status-dash/definitions/
     cloudflare.json`, uploaded in the same change), so they moved together. The same campaign
     also now reads `PUBLISHER = 'VRSM Lead Magnet'` in `sql/10` instead of `'Unknown'`.
  2. **1 lead - a Q3-campaign lead dated 2026-06-01.** The KPI strip is a DATE window (Q3 =
     from 07-01) over Salesforce's created date; the band is campaign-scoped and clamps a
     pre-anchor lead into week 1. A Roverpath Korea lead on a `2026_Q3_*` campaign carried a
     June created date, so one side counted it and the other did not. `sql/10` now clamps `DAY`
     to the first day of the quarter the campaign is NAMED for (raw date kept as
     `DAY_CREATED`) - the same rule as `sql/16`'s `GREATEST(..., anchor)`, at quarter grain.
     **Side effect, deliberate:** 13 `2026_Q2_*` leads dated March 2026 (7 accepted / 6
     rejected) moved INTO Q2, so the Q2 headline and the QoQ tab's Q2 column rose by that much.
  3. **Latent - the accepted bucket differed.** `sql/16` counted bare `Accepted`; the strip,
     `sql/15` and the verifier use the client's bucket `Accepted|Replied|Unresponsive`. Zero
     leads in scope carry the other two statuses today, so nothing moved, but the day one does
     the two panels would have split again. `sql/16` now uses the client bucket (and widens
     `IS_DELIVERED` with it so the rates still sum to 100%).
  Found in the same pass and fixed alongside - then hardened the same day on John's report
  (see the next gotcha): **64 EMEA Acquisition leads were sitting on the APJ lane.**
  **Re-verify** (both should print the same number):
  ```sql
  SELECT COUNT(*) FROM `bidbrain-analytics.client_cloudflare.salesforce_leads_live`
  WHERE DAY >= DATE '2026-07-01' AND LEAD_STATUS IN ('Accepted','Replied','Unresponsive') AND REGION_GRP <> 'OTHER';
  SELECT SUM(IS_ACCEPTED) FROM `bidbrain-analytics.client_cloudflare.stg_cs_leads_v2`
  WHERE THEATRE = 'APAC' AND BOOK = 'Core DG';
  ```
  If they differ, diff by `CAMPAIGN_ID`: the remaining legitimate differences are RIG (asset-based,
  hidden under Q3) and anything `sql/10` routes to `OTHER` (a new country, or Korea on an N*/P*
  campaign).
- **EMEA Acquisition leads were counted as APJ - theatre is now resolved by CAMPAIGN_ID, never
  defaulted (2026-09-04, John).** Two Acquisition `VER-FINANCE` campaigns created 2026-09-02 were
  named `2026_Q3_CEERI_ACQUISITION_...` (52 leads / 48 accepted) and `2026_Q3_DACH_ACQUISITION_...`
  (12 / 11) - no `EMEA-` prefix - and `sql/16`'s theatre rule was `IF(token LIKE 'EMEA%', 'EMEA',
  'APAC')`, so they defaulted into APJ: an Acquisition row in the APJ publisher table, a "64 leads
  matched no market rule" warning, and a 59-accepted hole in EMEA Acquisition's CEERI/DACH pacing.
  **What was implemented (the stronger option):** `sql/16` now resolves THEATRE in three tiers -
  (a) a per-`CAMPAIGN_ID` VOTE built from the data every run (`id_theatre` / `id_resolved` CTEs:
  count the id's leads whose name is unambiguous - an `EMEA-` prefix or a canonical APAC token -
  and resolve when one side has >= 80%; Acquisition's single id `701RG00001e1aegYAA` votes 917:0
  EMEA across its 27 name variants), (b) the NAME only when the id has no vote (a resolved market
  implies its theatre; an `EMEA-` prefix implies EMEA), (c) otherwise **`UNRESOLVED`** - on
  NEITHER lane, counted, WARNed by the job and shown in **Admin View** (`cspdUnresolved` card,
  from `cs_pacing.unresolved`) as a count of unmatched campaigns. MARKET still comes from the
  name (an id spans every market of its theatre), the market CASE accepts EMEA tokens with or
  without the prefix, and a name market from the WRONG theatre for the id becomes `UNMAPPED` on
  the id's lane with `REGION_CONFLICT=1` (zero today). Verified 2026-09-04: every id in the
  mirror votes 100% one way; Acquisition gone from APJ; EMEA Acquisition 981 leads / 879 accepted
  (CEERI 52/48, DACH 12/11 included); APJ Core DG accepted 1,720 -> 1,661 (-59 exactly); Roverpath
  852 / VRSM 400 / Final Funnel 409 unchanged; `region_source` census {id: all, name: 0, none: 0};
  grand total EMEA + APJ + Regional conserved. The 64 leads carry TAL `VER-FINANCE`, which has NO
  target of its own: the seed has no programme dimension, so they pace inside Acquisition's
  per-market weekly targets (which the plan's BFSI block is summed into - see "Streams 2&3").
- **Composition donuts undercounted - the top-N slice dropped the tail (2026-09-05, Nabeel).** The
  five CS donuts (Solutions / Country / Job function / Job level / Professional demographic) read
  the same 1,661 accepted leads, but Country printed 1,539 and Job function 1,657. `donut()` did
  `data.slice(0, limit)` and appended an "Other" slice ONLY when a total was passed - which only
  the job-title chart did - so Country drew 10 of 14 countries (New Zealand 40 / Thailand 37 /
  Philippines 35 / Viet Nam 10 dropped = 122) and Job function 8 of 12 (Finance/Procurement,
  DevOps, Press/Media, Developer, 1 each = 4). Solutions and Job level only reconciled because
  they have fewer values than the limit. The centre label (`bbDonutCenter`, vendored) sums the
  VISIBLE slices, so a truncated ring printed a truncated total and concealed itself. Now: (1)
  `donut()` folds everything past the limit into ONE visible **"Other (n more)"** slice built
  from the data - labelled with the count of folded VALUES because JOB_FUNCTION carries a REAL
  Salesforce value called "Other" (128 leads), and a bare "Other" fold would have drawn two
  legend entries with one name; (2) every donut is passed the scoped total
  (`agg.breakdownTotal`) and draws any shortfall as an **"Unaccounted"** slice + a console
  warning, so a future drop is visible rather than absorbed; (3) `aggregate()` labels a blank
  dimension **"Unknown"** instead of letting `groupCount()` skip the row (zero blanks in scope
  today). The AI-deck payload had the same blind spot, worse - `_bbTop` was a bare `slice(0,8)`
  (8 of 14 countries, 1,423 of 1,661) - so it now folds its tail the same way and ships
  `dims_total`. **Not changed, on purpose:** the lowercase **"C-level"** slice (13 accepted, all on
  the VRSM Lead Magnet ANZ campaign) and the country casing variants are REAL upstream values -
  the raw mirror carries them and nothing in the pipeline rewrites the column. Folding them in
  the frontend would hide a publisher-feed defect that also reaches the CSV and the deck; if the
  client wants them merged, it belongs in `sql/10` beside the country map's `UPPER(TRIM())`,
  with the status-check updated in the same change. **Manager is absent for a legitimate
  reason:** the only Q3 Manager leads in the allowlist sit on a Q2-only campaign (capped) and
  are Rejected/New, so they are outside an accepted-only ring either way. Verified headless
  against the live payload: all five rings sum to 1,661 at the Q3 default; Country shows 10 +
  "Other (4 more)" 122, Job function 8 + "Other (4 more)" 4, job titles 10 + "Other (139 more)"
  842. Frontend only - `dash/deploy_dash_cloudflare.ps1`.
- **APJ TTD target is recognised at WEEK CLOSE (2026-09-05, client instruction via Nabeel).** The
  "Leads vs target" card's TTD Target, the KPI strip's "Current pacing", the per-market TTD bars
  in the region grid, the Comparison tab's "QTD Target" bar and the AI deck's `ttd_target` /
  `vs_ttd_pct` all read `aggregate().ttdTarget`. It used to be `DAY <= now` over `pacing.rows`,
  which was START-of-week in effect: `sql/13_pacing_model` puts a cell's weekly target either
  on its accepted leads' own dates or, with no lead yet, on a placeholder dated the week's
  MONDAY, so the whole week counted the moment it opened (Fri 4 Sep read 1,599 = plan weeks 1-9
  INCLUDING the week in progress, 103.9% pacing). Now a week's target joins the denominator only
  once the FOLLOWING Monday has arrived (`weekClosed()` in `aggregate()`), applied to every week
  of the quarter so a closed quarter (Q2) is unchanged and there is no discontinuity. Same day
  after the change: TTD 1,428 (8 weeks to Sun 30 Aug), current pacing 116.3%; Q3 target 2,290,
  QTD accepted 1,661 and overall 72.5% untouched. The card carries a methodology line naming the
  basis ("recognised at week close: the N plan weeks completed to <date>; the week in progress
  is not yet included") and the deck payload carries `ttd_basis`. **This is a deliberate,
  client-directed EXCEPTION to the repo-wide "prorate a weekly target" rule** (md/AGENTS.md).
  **EMEA follows the SAME rule since the same day (client: "this should apply to EMEA too"):**
  `weekDueFraction()` now returns 1 for a closed plan week and 0 otherwise (it prorated before),
  so `cspdTopAgg` / `cscAgg` / the per-market "Due to date" bars all moved with no per-site edit;
  the prorated "Incl. week in progress" KPI, Leads-vs-target row and Progress row were REMOVED
  and EMEA's top cards now carry APJ's labels (Current pacing = vs weeks closed, Overall pacing =
  vs the full flight target) plus the same methodology line; the Pacing detail weekly tile shows
  '-' with "week in progress, day d of 7 - the week target is recognised at week close" for the
  in-progress week and sums CLOSED weeks only under "to date". Do not restore proration on
  either lane without the client. Two facts
  worth knowing when someone compares TTD% to Time%: time elapsed is measured over the CALENDAR
  quarter (1 Jul - 30 Sep) while the plan's 13 weeks run Mon 6 Jul - Sun 4 Oct, and the weekly
  targets are a mild front-loaded curve (182 -> 169 -> 176, total 2,290), so the two
  percentages are not directly comparable under ANY recognition rule. The weekly pacing chart
  plots each week's own target and is unaffected; the lead CSV export carries no target.
- **Weekly buckets will NOT match the client's sheet, and that is understood and accepted.**
  The sheet is dated when Nabeel delivers leads to Integrate; Salesforce dates them on lead
  creation. Quarter totals reconcile exactly, weekly splits do not (EMEA returns 114 / 120 for
  weeks 1-2 where the sheet shows 79 / 155 - our 120 is confirmed correct for our definition).
  **Do not try to reconcile this in code.** It resolves only when delivery dates arrive via the
  Integrate export.
- **The week math deviates from the Snowflake original deliberately** (negative `MOD` + a
  pre-anchor clamp). Full reasoning in `sql/README.md` -> "16 + 17". Removing the clamp makes
  the weekly figures silently stop summing to the campaign-to-date total.
- **`applyRegionPanelScope()` must stay the LAST thing `renderCsPacingDetail()` does.** It is
  the tail of `renderAll()`, and several blocks on that tab set their own `display` during that
  pass - `renderLeadDetail()` re-shows the dev-only **per-lead PII table** every time. Scoping
  before the repaint left that table visible under EMEA showing APAC leads. Running it last
  also covers the date-picker path (`applyDateRange` -> `renderAll`).
- **Under EMEA the rest of the CS tab is HIDDEN, not empty-stated**, because
  `salesforce_leads_live` is APAC-only (5,873 rows, zero EMEA) and every KPI/donut/chart above
  the section reads it. `CSPD_LEGACY_THEATRE` is the one constant to revisit if that view is
  ever widened. The date-range banner is suppressed there too - nothing visible responds to it -
  and `PROGRAMS.core_emea.note` is what tells the reader why the tab is short.
- **A theatre change must call `renderAll()`, and `switchDashboard` does.** `switchTab()` does
  NOT re-render `main` (it only toggles panels - the CS tab is otherwise built once at boot and
  on a date change), so without that call the section would keep the previous theatre's numbers.
  It fires unconditionally on a theatre change, not just when `main` is the active tab, or
  `panel-main` would be left stashed in the wrong hide/show state for later.
- **Vendors are DISCOVERED from the data, never listed in code.** Pipeline360 and Inbox Insight
  showed up on their own and now have rows in the publisher table with no delivery yet. They have
  no targets either, so they appear with delivery and no pacing. **That is correct - do not
  suppress them**, and do not make `17_*`'s FULL OUTER JOIN an inner join. The same is true of
  BOOKS: the campaign picker is built from the payload, and it HIDES ITSELF when a theatre has
  only one book (which is why EMEA gains no control it cannot use).
- **Market display order is data** (`MARKET_SEQ` in the targets CSV), not code. Same for the
  week grid and the quarter total. Nothing in the component is hardcoded to 8 markets or a
  Jul-Sep window - that is what lets EMEA (6 markets, 13 Friday-anchored weeks from 2026-08-07)
  and APAC (8 markets, Monday-anchored from 2026-07-06) share one component. **A third theatre
  is a third set of CSV rows and no new component code.**
- **The targets seed is the only non-live input.** Admin View shows a warning when the latest
  `WEEK_START` with a target falls behind the current week - last quarter this failed silently
  and the pacing model returned zero targets for seven weeks before anyone noticed. Re-seed
  each quarter: edit the CSV -> `seed_static.py` -> forced job run.
- **Absolute values only.** The relative view was removed at the client's request (2026-08-20,
  dashboard-wide) and must not come back here.
- **Rejection reasons have no live source.** The panel renders only when `cs_pacing.reasons` is
  non-empty and hides cleanly otherwise. Do not populate it with anything that isn't real.
- **`switchDashboard` re-syncs the `<select>`.** It is normally the thing that called it, but
  this dropdown is the region control now: a programmatic call that left it reading "Core DG
  APJ" while the page rendered EMEA would misstate which theatre the numbers belong to.
- **The shared date picker is HIDDEN on this lane** (`PROGRAMS.core_emea.dateControl:false`).
  Everything range-driven on the CS tab is APAC-scoped and therefore hidden under EMEA, and the
  one section that does render has its own week selector - so the picker changed nothing on
  screen. A visible control that does nothing is worse than no control. Flip the flag the day
  EMEA gains range-driven content.
- **`seed_static.py` now SKIPS a gitignored CSV that is absent** (`data/tiers.csv`,
  `data/line_cf.csv` on a fresh checkout) with a warning, instead of aborting the whole run -
  and it leaves that seed's existing BigQuery table alone rather than truncating it to empty.
  A missing file under the version-controlled `targets/` dir is still a hard error, because
  that one IS a real problem. Before this, seeding the committed CS targets on a clean checkout
  was impossible without first running `pull_static.py` (which needs the Snowflake key).

### Redeploy

Seeds load BEFORE views (`sql/17` reads the seed), and a seed/view change is invisible to the
freshness gate:

```powershell
.\.venv\Scripts\python.exe clients\client_cloudflare\seed_static.py
.\.venv\Scripts\python.exe clients\client_cloudflare\create_views.py
gcloud run jobs execute cloudflare-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
.\clients\client_cloudflare\dash\deploy_dash_cloudflare.ps1
```

## BigQuery owns the model (was the Snowflake-modelled exception)

Until 2026-06-17 Cloudflare was the **only** client that didn't follow the repo
pattern: the job pulled Snowflake's pre-modelled `CLOUDFLARE_SANDBOX.*` views and
landed them as thin `src_*` pass-throughs. It's now on the standard MongoDB pattern —
**BigQuery owns the model**:

- The four **dynamic** platform tables are already mirrored into `raw_snowflake`
  by the shared `ingest/snowflake_data_pull` unit (no Cloudflare-specific pull).
- The **static** Cloudflare-only tables (`REAL_TARGETS`, `TIERS`, the LINE JP upload)
  were pulled once to [`data/`](data/) (`pull_static.py`) and seeded into BigQuery
  `seed_*` (`seed_static.py`). **LINE no longer comes from Snowflake** — see
  [Updating LINE (manual)](#updating-line-manual) below.
- The Snowflake modelling SQL was **ported into [`sql/`](sql/README.md)** — the
  `V_STG_*` staging, `V_PAID_ADS_FINAL_MODEL`, `V_SALESFORCE_LEADS_LIVE`,
  `V_TIER_MAPPING_CLEANED`, `V_TARGETS_V2_NORM`, `V_PACING_FINAL_MODEL`, and the
  hardcoded benchmark/`li_weekly` constants — over `raw_snowflake.*` + the seeds.
- The job no longer touches Snowflake; it just reads the views (gates on BQ
  `__TABLES__.last_modified` like every other client).

**Verified parity** on the cutover: every headline figure matches the old pipeline
exactly (paid media per-channel imps/clicks/spend, creatives, 12 CS campaigns,
3911 leads / 3328 accepted / 416 rejected / 167 new, the 3 LinkedIn campaign dashes).
The pacing **tier** sub-split (Tier 2/3/Other) is **non-deterministic in the source
model** — `TIERS` has 742 cleaned account names mapping to conflicting tiers and 349
accepted leads match multiple tiers, so the post-join `QUALIFY` dedup picks a tier
arbitrarily. The old Snowflake view re-resolves these on every rebuild too; the BQ
port reproduces the model faithfully, so that split flickers as it always did (the
region totals and all headline counts are stable/exact).

### Updating LINE (manual)

LINE is the **one channel with no API/Windsor connector** — it's a hand-download from
LINE Ad Manager. The old Snowflake relay (`V_STG_LINE_CF` → `pull_static.py`) is being
**retired**: the LINE Ads account is migrating to **LY Ads** (LINE×Yahoo merger; LINE
Ads delivery ends ~late Oct 2026), and pre-migration the old account view gates behind
the migration tool. So LINE now flows **download → `data/line_cf.csv` directly**, no
Snowflake. Steps:

1. **Download** at https://admanager.line.biz/ → open the Cloudflare JP ad account →
   **☰ menu → Reports & Measurement → Performance report → + Create report**. Set
   **Aggregation interval = Daily (日別)**, level = **Ad**, format **CSV**, period =
   the full flight (or All time). The report generates async → download from the
   report list. (The dashboard's **Download report** button only emits a *Total*
   summary — it does NOT give daily rows; you need the Performance report builder.)
2. **Convert**: `.\.venv\Scripts\python.exe clients\client_cloudflare\convert_line_export.py`
   — auto-picks the newest `LINE*.csv` in `~/Downloads`, maps `Day/Ad name/Impressions/
   Clicks/Cost` → the `seed_line_cf` 7 cols (video cols → 0; these are IMAGE ads),
   sums to one row per (day, ad), and writes `data/line_cf.csv`. It prints range +
   totals — clicks should match the LINE UI exactly.
3. **Load + rebuild**: `seed_static.py` then the export job with `FORCE_REBUILD=1`
   (a seed change is invisible to the freshness gate). The model (`05_paid_media_model`
   `line_jp`) sums by day and converts **JPY→USD@155**.

### Updating targets (committed CSV → BQ)

CS pacing targets live in the **version-controlled** `targets/real_targets.csv` (week × tier ×
region × country × target) — NOT the gitignored `data/`. This is the per-client "targets in BQ from
a committed CSV" standard: the CSV is the source of truth, `seed_static.py` loads it into
`client_cloudflare.seed_real_targets`, and `sql/12_targets_v2_norm.sql` maps `(REGION, COUNTRY)` to
the 11 market codes. To change targets:

1. Edit `targets/real_targets.csv` (commit it).
2. `.\.venv\Scripts\python.exe clients\client_cloudflare\seed_static.py` (reloads `seed_real_targets`).
3. Run the export job with `FORCE_REBUILD=1` (a seed change is invisible to the freshness gate).

The per-market Q2 totals reconcile to the Q2 media-plan sheet (total **3216**). `tiers.csv`
and `line_cf.csv` stay in gitignored `data/` — they are pulled/manual snapshots, not targets.

**Q3 FY26 targets — ADDED (2026-07-09), client-confirmed.** The client's Core DG Lead Pacing plan
(`Raw Files/CF_FY26 Q3_Core DG Lead Pacing(Target Format Needed).csv`) was transformed into the seed
format and appended to `targets/real_targets.csv`, so it now carries **Q2 + Q3** rows (Q2 weeks
`2026-03-30 → 2026-06-15`, Q3 weeks `2026-07-06 → 2026-09-28`, 13 weeks). Q3 grand total **2290**
(ANZ 943 / ASEAN 419 / SAARC 220 / GCR 309 / JP 244 / KR 155), reconciled to the plan's own total row.
The dashboard **opens on Q3** (2026-08-05; it defaulted to Q2 from 2026-07-09), so these Q3 targets drive
the target KPIs + pacing cards on load. **The target is quarter-anchored** (the full selected-quarter plan, NOT the in-range
sum) — otherwise, because the date range clamps to the last day with data, an in-progress quarter like
Q3 would show only the elapsed weeks' target (the "Q3 Target = 182 instead of 2290" bug, fixed
2026-07-09 via `pacingWindow`/`quarterTargets` in `aggregate()`). **Note: the Q3 "Core DG" plan has NO
RIG line**, so the RIG chip shows Q3 actuals with no target — that's the client's scope, not a bug. The
raw plan put each ANZ/ASEAN region total on its lead country (Australia / SIM) and left NZ / RoA blank
(seeded as `0`); the `targets_v2_norm` view sums per region so the roll-up is unaffected. To change Q3,
edit `targets/real_targets.csv`, re-seed (`seed_static.py` / the `bq load` below) and run the job with
`FORCE_REBUILD=1`. The CF1 India lane keeps its own Q2 `li_weekly`/`CF1_CS_TARGET` plan (unaffected).

**Since `.venv` may be broken / ADC unauthed, reload the seed with `bq` (gcloud creds, no venv) —
`bq load` of ONLY `real_targets` is safer than `seed_static.py`, which also loads the gitignored
`tiers.csv`/`line_cf.csv` and fails if `data/` is absent:**

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"      # gcloud auth login first if the token expired
bq --project_id=bidbrain-analytics --location=australia-southeast1 load `
  --replace --source_format=CSV --skip_leading_rows=1 --allow_quoted_newlines `
  client_cloudflare.seed_real_targets "clients/client_cloudflare/targets/real_targets.csv" `
  WEEK:INTEGER,DATE:DATE,TIER:STRING,REGION:STRING,COUNTRY:STRING,TARGET:INTEGER
gcloud run jobs execute cloudflare-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```
Then rebuild + deploy the dash service (see CLAUDE.md → *Redeploy after an edit*).

### Brief-number campaign prefixes broke paid-media market parsing (FIXED 2026-08-04)

Transmission is progressively renaming campaigns with a leading brief number (`1160_`, `2103_`,
`2479_` ...). Trade Desk market derivation was a **fixed offset** into the underscore-split name, so
every token shifted one position: `MARKET_L3` came back as `APAC-ANZ` instead of `ANZ`, `JAPAN-JPN`
instead of `JP`. Those are non-empty, so the rows passed `paid_media_model`'s `MARKET_L3 <> ''`
guard, landed in `paid_media.rows[]`, and then matched **no** dashboard market chip - and
`passesAll()` in `dash/dashboard.html` filters every aggregate by chip. Silent loss, no error.

Two leaks, both closed:

| leak | imps | why | fix |
|---|---:|---|---|
| off-chip after remap | 4,989,809 | prefix shifted the offset (`APAC-*`, `JAPAN-JPN`); plus `TW`/`HK` were never in `PM_MARKET_REMAP` | parse off `CAMPAIGN_NAME_NORM`; add `TW`/`HK` → `GCR` |
| dropped at the model | 7,360,518 | short-form names (DOOH / High Impact, Q2 May-Jun) have no offset-8 token at all | `" - AU"/" - NZ"/" - ANZ"` suffix fallback in `03_stg_tradedesk.sql` |

**Trade Desk impressions rendered on the dash: 23,702,942 → 36,053,269 (+52%).** Spend and clicks
move with it. The second row is Q2 history that was never displayed before, so Q2 totals change; to
revert just that part, delete the suffix-fallback `CASE` arm in `03_stg_tradedesk.sql`.

### DOOH excluded from the dashboard (2026-08-05, client request)

The suffix-fallback fix above surfaced the two Q2 DOOH campaigns (`CLOUD_ACQ_2026-Q2-DOOH - AU`/
`- NZ`, ran 2026-05-12 → 05-31: 12 creatives, **1,362,226 imps / $19,799.59 / 0 clicks**). DOOH is
out-of-home - it structurally cannot click - so all 12 creatives sat at 0% CTR and filled the
whole bottom-10 creatives table (which is whole-flight, not date-scoped, so they showed even under
Q3). Client asked for **full removal**: `03_stg_tradedesk.sql` drops any campaign whose RAW name
contains `dooh` (substring, so brief-number prefixes can't dodge it), which removes DOOH from
spend, imps and every KPI/chart/creative table (both `paid_media_model` and `paid_creatives_model`
read that view). Q3 KPIs don't move (DOOH ended in May); Q2 totals drop by the figures above.
**Mirrored** as an explicit `NOT ILIKE '%DOOH%'` in the two whole-advertiser TTD checks in
`status_dashboard/job/main.py` - keep both sides in sync or the accuracy monitor goes red. The
sibling short-form campaign `High Impact--HyperlocalGeo - ANZ` (5,998,292 imps / $9,900.01 /
1,923 clicks) is real clickable display and **stays**. To revert: delete the `NOT LIKE '%dooh%'`
predicate in the view + the two `NOT ILIKE` lines in the status checks.

The same campaign exists under **both** name forms in the feed (15 raw names = 8 real campaigns for
the Q3 MDS line), so any name-keyed aggregate was also splitting in half. Normalising unions them.
Reference figure to check against, from the media-buyer sheet pull: the 8 `*_MDS_TTD_*COREDG-Q3`
campaigns = **5,516,027 imps / 4,788 clicks / $14,499.98**.

**LinkedIn was hardened the same way but no number changed** (3,746,467 / 16,908 / 487 before and
after). Its `CAMPAIGN_NAME` is the *ad set* name, which has not been renamed yet; the parent campaign
names in the sheet already carry prefixes, and a rename would have zeroed the channel via
`STARTS_WITH(CAMPAIGN_NAME,'CLOUD_ACQ_')`. That now reads `CAMPAIGN_NAME_NORM`.

**Google Ads is NOT wireable yet.** The sheet's Cloudflare Google Ads campaign
(`CF_JP_Q3_TOFU_YouTube_VideoViews_Prospecting`, id `24037386856`) appears in **none** of our
sources - 0/28 name overlap against `raw_snowflake.google_ads_apac`, `raw_google_ads.perf_google_ads`
(native DTS) and `raw_windsor.perf_google_ads`. That account is not ingested at all. It needs linking
to MCC 345-189-6252 + a DTS transfer before a Google Ads lane can exist here.

### 7 coarse market groups (2026-07-07 rollback of the 2026-06-25 11-chip split, per the Jade call)

The CS markets are the **coarse 7 groups**, plus a residual `OTHER` that is **not a chip** (so it's
excluded from the dashboard). Defined in `sql/10_salesforce_leads_live.sql`'s `REGION_GRP` and carried
straight through `sql/13_pacing_model.sql` (`MARKET_REGION = REGION_GRP`); targets are rolled up to the
same 7 in `sql/12_targets_v2_norm.sql`:

**`ANZ` (AU+NZ), `ASEAN` (SG/MY/ID/TH/VN/PH), `SAARC` (IN), `GCR` (CN/TW/HK), `KR`, `JP`, `RIG`.**
This **rolls back** the 2026-06-25 split (which had broken these into 11 chips) at the client's request,
so CS markets now match the paid-media L3 grain 1:1 (dashboard `ALL_MARKETS` + `PAID_ALL_MARKETS` are
identical). Rolling REGION_GRP back to coarse also re-activates the `ANZ`/`ASEAN`/`GCR` accepted-lead
columns in `sql/13` (they had silently gone to zero under the 11-chip codes).

### 2026-07-07 changes from the Jade call (test leads, unprocessed, quarter labels)

- **Test leads excluded.** `sql/10` now drops any lead whose email DOMAIN contains `transmission`
  (`... AND LOWER(IFNULL(SPLIT(EMAIL,'@')[SAFE_OFFSET(1)],'')) NOT LIKE '%transmission%'`). The vendors
  were each sent ≥2 test leads on Transmission emails (Nabeel / Shalvi / Jade), which were inflating the
  Q3 rejection rate (~36%). The SAME filter is mirrored into the status dashboard's Cloudflare CS check
  (`status_dashboard/job/main.py`, `_CF_TEST_LEAD_FILTER`) so the accuracy monitor doesn't false-alarm.
  **`sql/14_cf1_cs` was MISSED by this change and fixed 2026-08-09** — the CF1 Double-Touch lane predates
  the filter, so 3 Transmission test leads were reported as CF1 rejections (**20 instead of 17**, rejection
  rate 14.1% -> the true 12.2%; `reviewed` 142 -> 139). Accepted was unaffected (no test lead is Accepted),
  which is why only the one check went red. **Any new CS lane must carry this filter** — the status dash's
  CF1 checks had it on the source side from day one and are what caught the gap. Keep the two identical.
- **Unprocessed / New leads removed from the dashboard.** They're our internal backlog, not shown to
  Cloudflare. Acceptance & rejection rate now use **reviewed = accepted + rejected** as the denominator
  (so acc% + rej% = 100%); the unprocessed pacing bar, the "pending triage" note, the Comparison-tab
  Unprocessed % KPI, and the QoQ status-mix New row are all gone. The `cs_qoq` view still emits `New`
  (harmless; the front-end ignores it). Overview "Total leads" was relabelled **"Accepted leads"** (the
  KPI always showed the accepted count).
- **Quarter captions are dynamic.** Captions must not hardcode a quarter (the default was Q3 at the
  time, showing a Q2-labelled plan). Captions follow the selected quarter via `qtrLabel()` (returns
  `Q3` / `Q2` / `Q2-Q3`, or `Quarter` for a custom range) applied to every `.qlbl` span + the JS-built
  labels (`renderProgress` / `renderLeadsTarget` / by-region summary / date-scope banner). The QoQ tab
  gained a caveat line ("Q3 campaigns launched late, so QTD reads light — timing, not a data issue").

### Q2-only campaigns - the 4 P* Surround-ABM/Modernize ids capped at Q2 (2026-08-05)

Client request (via Transmission): the 4 P* campaigns (`701RG00001PXLpxYAH` / `701RG00001PXHnzYAH`
Roverpath Modernize Applications, `701RG00001PXNyDYAX` / `701RG00001PWX5gYAH` Final Funnel ABM
Modernize Security) are **Q2 campaigns that still receive REPLACEMENT leads** for rejected Q2 leads.
Replacements land with **Q3 created dates** (`DAY`), and since the dashboard buckets quarters by
created date they were surfacing on the Q3 side. Fix: a **date cap, not removal** - the ids stay in
`cs_campaigns` (Q2 history untouched), but a new `definitions.json` block **`cs_q2_only_campaigns`**
(cutoff `2026-07-01`) seeds `seed_cs_q2_only_campaign_ids`, and `sql/10`'s WHERE excludes their leads
with `DAY >= DATE '2026-07-01'` **everywhere** (CS Overview, QoQ Q3 side, pacing, lead table, CSV).
The status verifier builds the SAME cap from the same file (`_cf_cs_cte` in
`status_dashboard/job/main.py`), so the accuracy checks stay green. Caveats: replacement leads created
on/after Jul 1 appear **nowhere** (they don't backfill Q2 - the quarter is still a created-date range),
and the cutoff date is a mirrored literal in `sql/10` (change it in both files together). To lift the
cap, empty the `campaigns` list in `cs_q2_only_campaigns` and re-run `definitions_seed.py`.

### Admin View (internal) - unprocessed leads + Source-ID filter (2026-07-10)

The unprocessed/New leads removed above (client rule) are still viewable INTERNALLY via a role-gated
**Client View / Admin View** toggle in the **topbar** (a pill toggle, right of the date picker - it
reuses the `.qtr-*` CSS of the retired Q2/Q3 quarter control, which is why that CSS stays). **Client View** = exactly what the client sees; **Admin View** turns
on everything below. It is **hidden from clients**: the toggle appears only when the platform proxy
injected `window.BB_DEV=true` - which it does for an **admin / super-admin** session or the
**Transmission agency** portal (see `bidbrain-platform/dash/main.py` `_dev_flag_script`, injected
alongside `window.BB_SPEND_MULT`). A `?dev=1` URL param is a fallback for direct (non-proxied) access.
(Internally the flag is still `devMode`; Admin View = `devMode` true.)

Admin View **defaults ON** for a dev-allowed viewer (so you don't have to find the toggle); clients never
get `window.BB_DEV` so they only ever see Client View. When in Admin View it:

- **(a) Unprocessed across all CS Overview charts** - an "Unprocessed" KPI in the Overall group, a
  stacked bar on the pacing chart, an unprocessed line on the Accepted-leads trend, an Unprocessed bar
  per market card, and New leads folded into the Solutions / Country / demographic / asset composition
  donuts (centre totals become accepted + unprocessed).
- **(b) Source-ID (campaign) dropdown** that filters the CS view to a single `CAMPAIGN_ID`. LEADS only -
  the plan/target stays at the market grain; the acceptance/rejection rate denominator stays reviewed-only.
  Each option reads `<label> (<CAMPAIGN_ID>) - <n> leads`; the label comes from the `CAMPAIGN_LABELS`
  const in `dash/dashboard.html` (a MIRROR of `definitions.json` `cs_campaigns[].label` - keep in sync
  when that file changes), falling back to the raw Salesforce `CAMPAIGN` name for any unmapped ID.
- **(c) Lead-detail table** at the bottom of the CS Overview - every lead in the current filter with
  EVERY field we hold (Source ID, campaign, status, date, market, publisher/offer, company, title,
  country, name, email, phone, opt-in, lead id, raw timestamps, source file). Sortable + scrollable,
  capped at 1000 DOM rows, with a full-set **CSV export**. Contains PII, so it's `devMode`-gated (never
  client-facing). Frontend-only - the fields are already in `pacing.rows[]`.
- **(d) "Internal Notes" tab** (an Admin-View-only tab, hidden in Client View; **renamed from "Data
  from Transmission" 2026-08-05**) - an **Internal notes** card first (team notes with add/edit/delete;
  the UI is platform-injected into `#bbNotesMount` for staff sessions through dashboards.bidbrain.ai -
  empty on a raw run.app URL), then **what Transmission committed** in two tables: **Source IDs** (the canonical CS
  campaign/Source-ID list that should be present, from `definitions.json` / `seed_cs_campaign_ids`, with
  a **Label** column - the curated `CAMPAIGN_LABELS` name - plus a **Sample campaign** column (raw SF
  name), and what has actually landed per ID: leads / accepted / rejected / unprocessed + a Present?
  flag; a red row = committed but not yet delivering), and the **pacing plan** (the target numbers
  Transmission sent - `targets_v2_norm` over the committed `real_targets.csv` - per market x tier, Q2/Q3
  split + totals). **This one needs the job** (`build_transmission()` -> `transmission` in
  `cloudflare.json`), not just the frontend.

Frontend gating: `DEV_ALLOWED` (window.BB_DEV or ?dev=1) reveals the topbar toggle; `devMode` (Admin
View, default = `DEV_ALLOWED`) drives the Source-ID controls, the admin-only tab and the in-CS
unprocessed/lead-table rendering (`applyViewMode()` reflects the mode; `aggregate()` is the single
choke point). `setAdminView()` flips it.

### "Best performing assets" - one bar per asset, labelled by NAME (2026-08-26, client request)

Jade flagged the chart's labels as "gone wonky". Two separate defects, both visible on the same
screenshot, and the second was distorting the ranking rather than just the axis:

**1. Salesforce carries TWO asset-naming conventions at once.** Every asset has a short code
(`A-MAT-2`). Since **2026-07-07** the feed ALSO carries the file-slug form of the SAME asset
(`26Q2_REPORT_2026-app-innovation-report_v1`) - **308 leads across 14 slugs, 13 of which duplicate a
code already in the feed**. So one asset drew two bars, split its own lead count between them, and
put a 45-character filename on the x-axis at 45 degrees.

**2. The chart keyed on `asset || service`, so an asset that ran on two solution campaigns drew a
second bar under the IDENTICAL label** (that is the repeated `A-MAT-2` on Jade's screenshot).
`SERVICE` is parsed from `CAMPAIGN` in `sql/13_pacing_model.sql`, not from the asset, so it is a
property of the campaign the asset ran on - and the chart was ALREADY built to stack by solution
(`stack:'one'`), so that split belonged inside one bar.

**What the client was actually looking at (Q3 to 2026-08-25, accepted, all visible markets):** the
true top asset - *2026 Cloudflare APAC App Innovation Report* - has **299 leads** but was scattered
across four bars (146 + 89 + 8 under `A-MAT-2`, 55 + 1 under the slug) and so never appeared as
number one. *Coffee shop networking* is **128**, shown as 51. The chart's headline bar read 165.

**The fix (all in `dash/dashboard.html`, frontend only - no view, job or payload change):**
- `ASSET_ALIASES` folds each slug onto its short code. **Add a row here when a new slug appears.** An
  unmapped slug is NOT lost - it keeps its own bar, and `prettyAssetName()` renders it as prose
  (`[Ebook] Accelerating AI adoption with SASE`) instead of as a filename, so this can never look
  broken again while we wait to map it.
- `aggregate()` keys the asset map on `assetId(ASSET_1)` alone and carries a `services[]` breakdown
  per asset, so there is **one row per asset** and the solution split stacks inside its bar.
- The chart is **horizontal** (`indexAxis:'y'`). That is what buys the real fix: a 12-item x-axis has
  no room for a title, which is why the label was the cryptic CODE in the first place. Reading down a
  left-hand axis, the label can be the asset NAME, at a fixed width, with the code kept in the
  tooltip. Tick length FOLLOWS THE CARD WIDTH (`w/16`, capped 16-38 chars) so at the 900px breakpoint,
  where the 2-up grid collapses, the label clips itself instead of squeezing the plot.
- Tooltip is `interaction:{mode:'index', axis:'y'}` - **`axis:'y'` is required on a horizontal bar**
  or hovering picks one segment instead of the whole asset - and titles off `rows[dataIndex].id`,
  never `items[0].label`, because two long names can truncate to the same string.
- The comparison panels (`renderCompareAssets`) now print the NAME too, plus the leading solution.
- Both charts on that grid row share `.chart-wrap.xtall` (364px); giving only the assets card the
  taller wrap left ~90px of dead space under its sibling, since grid items stretch.

**Verified** against BigQuery for the default (Q3) window: all 12 bars reconcile exactly -
299 / 174 / 134 / 128 / 108 / 103 / 75 / 73 / 46 / 42 / 36 / 30.

**Open:** `A-MSM-11` (73 leads) and `A-CCT-5` (30) are not in the Q2 asset list, so they still render
as their bare code. Two slugs have no short-code twin and are shown prettified:
`26Q2_EBOOK_accelerating-ai-adoption-with-sase_v1` and `25Q2_SOL-BR_GartnerMQSV-SASE_M_v1_en-US`.
Ask Transmission for the titles and add them to `ASSET_NAMES`.

### Spreadsheet-style tables (sort + search, 2026-07-10)

Every data table is **sortable** (the vendored `bb-sortable` engine - click a header) **and searchable**:
a small **Search table...** box is injected above each table with more than a handful of rows and
filters the data rows as you type (header + Total row always stay visible). Both survive the
`innerHTML` re-renders the dashboard does: a document-level `MutationObserver` re-wires new tables for
sorting and re-injects the search box (`window.bbEnsureSearch`), and each box's query is remembered per
host container so it persists across a rebuild. Grouped tables (colspan section-headers) and tiny
summary tables (< 6 data rows) are intentionally left without a search box. **Cloudflare-only for now** -
the search half is a local extension of the otherwise-vendored `bb-sortable`; it is NOT yet propagated
to the canonical copy (`clients/client_resetdata`) or the other dashboards.

### Korea reconciliation (144 vs 164) — Ian to confirm with data

The client (Nabeel) reports **164 Korea leads DELIVERED** (101 Final Funnel + 63 Roverpath); the dash
KR chip shows **~144**, which is Korea **ACCEPTED** leads. The ~20 gap is almost certainly
delivered-vs-accepted (rejected + new Korea leads), **not** a country-name or campaign-scoping bug — so
`sql/10` keeps the exact `= 'KOREA, REPUBLIC OF'` match (a broadened `LIKE '%KOREA%'` would over-count
AND desync the status-dash check). Confirm the split before changing anything:

```sql
SELECT
  CASE WHEN LEAD_STATUS IN ('Accepted','Replied','Unresponsive') THEN 'Accepted'
       WHEN LEAD_STATUS = 'Rejected' THEN 'Rejected' ELSE 'New/other' END AS bucket,
  CASE WHEN CAMPAIGN_ID IN ('701RG00001ElJZzYAN','701RG00001ElTu3YAF','701RG00001ElVXdYAN') THEN 'Roverpath'
       WHEN CAMPAIGN_ID IN ('701RG00001ElUoXYAV','701RG00001ElUa0YAF','701RG00001ElNYkYAN') THEN 'Final Funnel' END AS publisher,
  COUNT(*) AS leads
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
WHERE UPPER(TRIM(COUNTRY_NAME)) = 'KOREA, REPUBLIC OF'
  AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_kr_campaign_ids`)
  AND LOWER(IFNULL(SPLIT(EMAIL,'@')[SAFE_OFFSET(1)],'')) NOT LIKE '%transmission%'
GROUP BY 1, 2 ORDER BY 2, 1;
```

If the total across all buckets ≈ 164 and Accepted ≈ 144, the dash is correct and the client is
quoting *delivered*; frame it that way rather than changing the KR logic. Also try the same query with
country variants (`LIKE '%KOREA%'`) — if that adds ~20 *accepted*, the fix is a broadened match (apply
it in BOTH `sql/10` and the status check's KR arm to stay in sync).

- **Korea Leads (KR)** — Country `'Korea, Republic of'` leads in the **Core DG CS campaigns**: the
  **6 ORIGINAL El\* campaigns** (3 Roverpath + 3 Final Funnel Lead-Gen) **+ the Q3 VRSM Lead Magnet
  campaign** `701RG00001W1FQRYA3` (added 2026-09-04 - see the 1,650 / 1,661 gotcha; seed-driven via
  `seed_kr_campaign_ids`, 7 IDs). **2026-07-02:** reverted the 2026-06-25 "ALL Korea in the 12
  campaigns" rule at the client's request. Korea leads from the N\*/P\* campaigns (Connectivity Cloud /
  Modernize Security / Modernize Applications, ~55 live 2026-07-02) fall through to `OTHER`.
- **RIG Leads (RIG)** — **NON-Korea AND** `ASSET_2` `IN ('A-MAM-2','A-MAM-3')` (the gaming-vertical
  *Modernize Applications* asset — only `A-MAM-3` has data) **AND** the **3 Final Funnel** campaigns.
  Asset-based, evaluated **before** geography, so it spans every country. Live count **180** (167 accepted).

The geographic markets are pure `COUNTRY_NAME` maps, **case-normalised** (`UPPER(TRIM(COUNTRY_NAME))`)
so mis-cased countries (`japan`, `Hong kong`, `india`) route to JP / GCR-HK / SAARC instead of falling
to a residual. The `ELSE 'OTHER'` arm holds Korea leads outside the KR campaigns (~55) plus any
brand-new/unmapped country. `OTHER` is **not one of the 11 chips**, so those leads are excluded from the
dash — the headline CS totals sum over the chips, so there is no total-vs-sum drift on screen (this
matches the pre-2026-06-25 behaviour; the ~55 leftover Korea leads just aren't counted anywhere on the
dash). Add `OTHER` to `ALL_MARKETS` in `dash/dashboard.html` if those leads should become visible.
The old `pacing_model` "Computer Games + Tier 2 → RIG" override was removed so RIG equals the exact def.
The reference DDL `snowflake_v_salesforce_leads_live.sql` (Transmission's / Cloudflare's legacy R2 export,
NOT our pipeline) keeps the geographic logic, but its KR arm was **also campaign-scoped to the 6**
(2026-07-02) — that file is a **manual Snowflake DDL our read-only roles can't apply**, so it needs an
owner/ACCOUNTADMIN to run the `CREATE OR REPLACE` (keep the `copy grants`) before Transmission's own view
matches. The **status dashboard** reproduces KR / RIG + **reconciles the `OTHER` residual** straight from
Snowflake; its core CS counts (Total / Accepted / Rejected / New) query the whole 13-campaign universe
with **no region filter** (so they include the ~55 OTHER leads the dash omits).

**Targets follow the media-plan sheet** per market (Q2 total **3216**: AU 1150 / NZ 127 / SIM 381 /
RoA 165 / SAARC 282 / GCR-CN 106 / GCR-TW 106 / GCR-HK 204 / KR 202 / RIG 172 / JP 321), and now live
as a **version-controlled committed CSV** (`targets/real_targets.csv` → `seed_real_targets`, the
per-client "targets in BQ from a committed CSV" standard — see *Updating targets* below).

### Re-skinned onto the MongoDB design language - dark glow, orange accent (2026-08-05)

Client request (JM): *"I like the overall style and format structure of the Mongo and Schneider
dashboards - the headers at the top, position of logos, navigation, the cleaner layout. Is it a
different design or layout used? What is different? I would ideally like the Mongo/SE design with
Orange as the background."*

**What was different.** MongoDB and Schneider run the newer **Bidbrain design system**, in two
variants of the same tokens:

| | canvas | cards | header | navigation |
|---|---|---|---|---|
| **MongoDB** | dark base (`--bg:#05131A`) + brand-accent glow | dark surfaces | agency wordmark · divider · **client logo** (supplied artwork, inlined) · Live | one **sticky glass control bar**: tab rail + exports + filters |
| **Schneider** | **brand colour AS the background** (deep green + 2 radial glows + arc pattern) | **WHITE, floating** with a green glow shadow | agency · divider · white logo chip · region tag · campaign select | tab rail in the bar |
| **Cloudflare (before)** | flat bright-orange gradient | white | **flat black bar**, wordmark knocked out in white, no chip | a white pill tab bar floating loose on the canvas + the date picker up in the topbar |

Both reference dashboards re-skin from a handful of CSS custom properties - that is the whole point
of the system, and it is why MongoDB's `:root` carries a literal *"change ONLY these to reskin
another client"* block.

**What Cloudflare adopted: the MongoDB dark-glow variant, on orange** (client picked it after seeing
both - *"I like the MongoDB more, the colouring, shading"*). A warm near-black base lit by orange
glow, near-white text on dark surfaces. Changes, all in `dash/dashboard.html`:

- **Tokens** - `:root` is now MongoDB's set (`--bg/--bg-2/--surface/--surface-2`, `--line/--line-2`,
  `--ink/--muted/--muted-2`) with `--brand-accent` = Cloudflare orange and orange `--glow*`.
  **Re-skinning another client is the accent block alone**, exactly as MongoDB's `:root` documents.
- **The legacy `--cf-*` names are REMAPPED onto those tokens** (`--cf-card:var(--surface)`,
  `--cf-bg:var(--surface-2)`, `--cf-line:var(--line)`, `--cf-ink:var(--ink)`, `--cf-mute:var(--muted)`)
  - MongoDB's own trick for its `--mdb-*` names. That one block flipped ~90% of the stylesheet with
  no edit; only hardcoded hex literals had to be chased (see below).
- **`--cf-navy` is now LIGHT** (`#E7D6C6`). It survives only as the dashed target-marker / "ahead of
  pace" colour on the progress + pacing bars; at its old near-black it was invisible on dark.
- **Body** - MongoDby's gradient recipe with orange: a glow blooming from the top, a second top-right,
  a warm lift bottom-left, over a near-black warm base. (The Schneider arc-pattern SVG was dropped.)
- **Header** - the Cloudflare mark is the **supplied artwork** (`creatives/Cloudlfare logo.jpg`, a white
  logo on its own orange field) **inlined as a base64 data URI** in `.logo-chip` -> `img.cf-logo`,
  height 36px. It replaced the hand-drawn SVG cloud + inked `CLOUDFLARE` wordmark on a white chip
  (2026-08-05); the chip no longer paints white, because a white surround would frame the artwork as
  an orange tile - so there is now **no white surface left** in the theme. **Inline, never a path:**
  the `dash/` Docker build context excludes `creatives/`, so a `src="..."` file reference or a `/logo`
  route would 404 in the deployed service. To swap it again, drop the new file in `creatives/` and
  re-inline it. MongoDB's surface-to-base topbar gradient with the accent glow spilling downward;
  the Transmission logo stays top-right, so there is no text agency wordmark.
- **Navigation** - a **sticky dark-glass `.control-bar`** holds the tab rail **and** the shared
  date-range picker + the internal View toggle, which used to live in the black topbar. Tabs use
  MongoDB's underline-on-a-hairline treatment (`.control-tabs`) with an accent drop-shadow.
- **Glow furniture** - MongoDB's `.kpi.accent` (accent bled into the surface + halo), glowing KPI
  stripes, `--shadow-card`, accent-tinted `tr.total`, and dark-tinted channel pills / callouts.
- **CHARTS ARE RE-THEMED** - the one part that is not just tokens, and the reason this variant is more
  work than the Schneider one:
  - **`Chart.defaults`** are set once, before any chart is built (`color`, `borderColor`,
    `scale.grid.color`, `scale.ticks.color`, legend label colour, tooltip bg/border/text). Chart.js
    defaults ticks and legends to `#666` and grid to near-black - invisible here. Doing it globally
    means **no chart can be left reading dark-on-dark**, including ones that never passed a colour.
  - Palette constants re-tuned: `PM_INK` (was `#1B2834` navy - would have vanished) → warm light;
    `PM_LINE`/`LINE` → `rgba(255,255,255,.09)`; `PM_LI` `#0A66C2`→`#3B93E8`, `PM_PURPLE`→`#B98AE8`,
    `PM_RD`/`PM_LN` brightened; `TARGET`/`PM_TARGET` → `#8A7263`; the 12-colour categorical `colors`
    array lost its three near-blacks; donut `borderColor:'#fff'` → the surface colour.

**No data, metric, chart, table or filter was added, removed or rewired** - shell, tokens and chart
colours only. Verified against the pre-re-skin file: **24 chart canvases before and after, all 163
element ids intact.** Gotchas worth knowing:

- `.dash-select` must keep a **SOLID** background: Chrome/Windows paints the native `<option>` list
  from the select's own background, so a translucent one renders white text on a near-white popup -
  invisible options, on the primary nav control. `option` colours are set explicitly for both the
  topbar select and the white-row dev select.
- The date picker's popover **anchors right** now (`.control-right .dp-pop{left:auto;right:0}`) - it
  sits on the right of the control bar, and left-anchored it opened off-screen.
- `#cmpTabs` (the CF1 campaign view's tab bar) reuses `.tabs`/`.tab` but sits **directly on the
  canvas** - single-campaign views have no control bar - so it takes the on-canvas colours. Without
  that override its ink text was unreadable on the orange.
- `switchDashboard()` hides `#controlBar` (not `.tabs`) for single-campaign views, since the shared
  date control lives in the bar too - hiding only the tabs would leave an empty glass strip.

### Surround ABM split out of Core DG - the lane model (2026-08-14, client request)

Brief **2193 "Surround ABM"** was summing into Core DG. It is a separate book with separate
numbers, so the client asked for it in the dropdown on its own. The dropdown now holds two KINDS
of entry, and this is the distinction to hold on to:

| kind | entries | renders |
|---|---|---|
| **PROGRAM lane** | `core` (Core DG APJ) · `core_emea` (Core DG EMEA) · `surround_abm` (Surround ABM) | the FULL core shell - tab rail, shared date range, market chips - scoped to one brief |
| **CAMPAIGN lane** | `peyc` · `cf1_india` · `coles_hyper` | the single-campaign LinkedIn view (`renderCampaign`, whole-window totals, no date control) |

`core_emea` went LIVE 2026-08-24 (it had been a disabled placeholder). It is a program lane that
differs from `core` in **theatre** rather than in brief - see "Pacing detail + Core DG EMEA".
A lane now carries a `theatre`, and `laneTheatre()` is what the CS Pacing detail section reads.

**The split is a data-layer dimension, not a front-end filter over campaign names.** A `PROGRAM`
column flows the whole contract: `sql/03_stg_tradedesk` (+ `01_stg_linkedin`) → `05_paid_media_model`
/ `06_paid_creatives_model` → `job/main.py` `program` → `dashboard.html` `row.prog`. Values:

- **`CORE_DG`** - briefs 1160 (High Impact/HyperlocalGeo) / 2103 (Q2 Core DG) / 2479 (Q3 Core DG),
  plus all LinkedIn, Reddit and LINE. The `ELSE` arm, so a brand-new brief lands here rather than
  vanishing - it just needs splitting out once someone notices it.
- **`SURROUND_ABM`** - brief 2193: **Trade Desk only**, 5 campaigns
  (`..._{ANZ,ASEAN,GCR,KR,IN}-SURROUND-ABM`, TTD ids `6cm53fr` / `y2kxvxf` / `9lg1jx3` / `on8odve` /
  `hebzbzj`). Matched by **substring on the RAW name** (`'%surround%abm%'`, plus a `2193_` prefix
  arm) - never a fixed offset, and it spans both name vintages in the feed (the same campaign exists
  prefixed and un-prefixed - see the brief-number section above). Verified 2026-08-14: **10 distinct
  raw names = 5 campaigns x 2 vintages**, which is exactly why the substring rule is not optional.

**It is NOT a Q2 brief, despite the names.** Every campaign name reads `2026-Q2`, but delivery
started **2026-06-12** and is still running: **Q2 38,095 imps / $2,722.20, Q3 81,013 imps /
$4,714.45** (whole flight to 2026-08-12: **119,108 imps / 290 clicks / $7,436.65**; markets
IN 61,921 · AUNZ 30,609 · HKTW 11,496 · SGMYIDPHTH 10,560 · KR 4,522 - all five remap cleanly
through `PM_MARKET_REMAP`). Two thirds of it is Q3, so **never date-gate this lane to Q2** and don't
call it a Q2 campaign - the name is not the flight. The dashboard opens on Q3, so the lane's default
view is the Q3 portion; widen the range for the whole flight.

**Core DG's Q2 numbers MOVE.** Q2 spend / impressions / clicks / market rows / creatives all drop by
Surround ABM's delivery, because that is what "separate them" means. Q3 is unaffected (Surround ABM
never ran in Q3). The AI deck (`buildDeckPayload`) is pinned to `CORE_DG` explicitly - it is the Core
DG deliverable and is whole-flight, so it must not follow the lane selector.

**The status-dashboard accuracy checks are unaffected, by design.** `paid_media.rows[]` still carries
EVERY row - a `program` column was ADDED, nothing was removed - and the two TTD checks compare the
whole Snowflake advertiser total against the sum of `rows[]`. So the split is a rendering dimension,
not a data exclusion, and the monitor stays green with no mirrored edit. **Keep it that way:** if a
lane is ever implemented by dropping rows from the payload instead of tagging them, those checks go
red and the whole "advertiser-total vs dashboard-total catches a parsing regression" guarantee dies.

**What the Surround ABM lane deliberately does NOT show** (`PROGRAMS[].tabs` / `.plans` in
`dash/dashboard.html`, and the banner in `#laneNote` says so on screen):

- **Only the Paid Media tab.** Content Syndication / CS Comparison / QoQ / Internal Notes are
  CS-driven and are NOT program-scoped, so they would silently show Core DG's leads under a Surround
  ABM heading.
- **No budget pacing and no LinkedIn lead-commit block.** `PACING_PLANS` and `LI_LEADGEN_PLANS` are
  Core DG's committed plans; grading another brief's spend against them would be worse than showing
  nothing. `renderPacing` / `renderWeeklyTarget` / `liQ3PlanCtx` all gate on `laneCfg().plans`.
- The lane's footer row-count and window are **lane-scoped**, so it never advertises Core DG's flight
  over Surround ABM's numbers.

**Surround ABM has Content-Syndication campaigns too, and they are still in CORE.** The 4 P*
Salesforce ids labelled `CF Surround ABM *` in `definitions.json` (Q2-capped, see above) remain in
the core 13-ID CS filter exactly as before - this change touched the PAID model only. Moving them
would change the client's headline CS totals AND desync the status-dashboard CS checks, so it is a
separate, deliberate piece of work if they ever ask for it.

**To add another lane** (e.g. a future brief): one `WHEN` arm in the `PROGRAM` CASE in
`sql/03_stg_tradedesk.sql` (mirror it in `01_stg_linkedin.sql` - keep the two byte-identical), one
entry in `PROGRAMS` in `dash/dashboard.html`, one `<option>` in `#dashSelect`. Then reapply the views
and run the job with `FORCE_REBUILD=1` (a view change is invisible to the freshness gate). The job
prints a per-program `rows / imps / spend` line every run - that is the cheap check that the name
parse still works, and the thing to read first if a lane ever goes empty.

### Custom date range in the picker (2026-08-14)

The calendar always allowed an arbitrary range by clicking a start then an end day, but there was no
way to *type* a date and nothing in the preset list said "custom" - so a specific window (a flight, a
client's reporting fortnight) meant paging the calendar. Added, in `dash/dashboard.html` only:

- A **`Custom range`** preset, listed **last**. It is the "none of the above" state: it highlights
  automatically whenever the selection matches no preset, and clicking it does NOT change the range -
  it focuses the From field (overwriting a range you had just clicked out would be the wrong move).
  `detectPreset()` skips it explicitly, or `presetRange()`'s `else` arm would make it masquerade as
  "All time".
- **From / To date inputs** under the calendar (`#dpFrom` / `#dpTo`). They edit the SAME draft the
  calendar does, so the two always agree; `min`/`max` are bound to the data window, an out-of-window
  entry clamps, and a reversed pair is swapped rather than rejected. Bound to `change`, not `input` -
  a date input fires `input` on every partial keystroke and would clamp a half-typed year.
- Apply commits as normal, so the quarter derivation (`syncQuarterFromRange`), the `.qlbl` captions
  ("Quarter" for a custom span) and every tab re-render are unchanged.

### Lane dropdown: "Core DG APJ" + an EMEA placeholder (2026-08-05)

The topbar dropdown's first entry was renamed **"Core Demand Generation" → "Core DG APJ"** (client
request, JM) ahead of **Core DG EMEA** launching the week of 2026-08-05. The `<option>` **value is
still `core`** — only the label changed — so `switchDashboard()`, `activeTab`, every core-tab render
path and the whole payload are untouched by the rename. Two display strings follow it: the AI deck's
`context.campaign` in `buildDeckPayload()` and the Stage-A `business_model` brief in `dash/report.py`.
`campaign_key` stays `core_demand_gen` (the stable identifier `/report` summaries carry, so cached
decks don't orphan).

#### Core DG EMEA — LIVE since 2026-08-24 (was a disabled placeholder)

`<option value="core_emea">Core DG EMEA</option>` is now a **real PROGRAM lane** in `PROGRAMS`,
which is what stopped it falling through to `renderCampaign()`'s empty *"No data"* state (the old
reason it was greyed out). It ships **Content Syndication only**:

- `PROGRAMS.core_emea` = `{ prog:'CORE_DG', theatre:'EMEA', tabs:['main','txdata'], plans:false }`.
  `tabs` is what hides Paid Media / CS Comparison / QoQ - no EMEA ad accounts are connected, and
  EMEA launched 2026-08-07 so there is no prior quarter. `plans:false` because the budget and
  LinkedIn lead-commit pacing blocks are Core DG APJ's plans.
- The **CS data** comes from `sql/16_stg_cs_leads_v2` + `17_cs_pacing_v2` (campaign-NAME scope, so
  EMEA is included) -> the `cs_pacing` payload branch -> the **Pacing detail** section.
- **Everything else on the CS tab stays APAC** and is hidden under this lane, because
  `salesforce_leads_live` is scoped by the campaign-ID allowlist and holds zero EMEA rows.

**What EMEA still does NOT have, and what each would take:**

1. **Paid media.** Needs EMEA rows in `raw_snowflake.*`, then either a `REGION` column through
   `paid_media_model` / `paid_creatives_model` (preferred - one set of views, one gate) or a cloned
   `sql/` chain. Then add `paid` to `PROGRAMS.core_emea.tabs` and give the paid panels an EMEA
   `ALL_MARKETS` / targets / `PACING_PLANS` (all three differ from APJ's).
2. **The APAC-shaped CS blocks** (KPI strip, donuts, trends, by-region summary, QoQ). These need
   `10_salesforce_leads_live` widened past its 13-ID allowlist - which would move live APAC numbers
   and desync the status-dash accuracy checks, so it is a deliberate piece of work, not a tweak.
   `CSPD_LEGACY_THEATRE` is the constant that encodes the current APAC-only assumption.
3. **A prior quarter** for QoQ - simply time.

`QUARTERS` / `activeChans()` need no change either way; both are region-agnostic.

### Quarter selection — opens on the CURRENT quarter, picked in the calendar (2026-08-05)

**The dashboard opens on the quarter today falls in — Q3 (Jul 1 – Sep 30) as of 2026-08-05** — and
the quarter is chosen **in the date-range calendar**, whose first two presets are `Q3 (Jul-Sep)` /
`Q2 (Apr-Jun)`. **The topbar Q2/Q3 chip pair is GONE** (client request 2026-08-05: a row of quarter
buttons doesn't scale as quarters accumulate) — one control, not two.

- `QUARTERS` (now declared **above** the `DateRange` IIFE) is the single source of truth for every
  quarter span, and the calendar's quarter presets are **generated from it** (`QUARTER_ORDER`,
  newest first) — the old duplicate hardcoded `q2`/`q3` preset dates are gone. **Add a quarter to
  `QUARTERS` and it appears in the calendar automatically**; nothing else to touch.
- The quarter presets are listed **first** deliberately: `detectPreset()` returns the first matching
  preset, so the picker button reads "Q3 (Jul-Sep)" instead of the identical-but-vaguer
  "This quarter" (both produce the same range while Q3 is current).
- The default comes from **`currentQuarterKey()`** (the quarter containing today, pinned to the
  nearest one outside the defined set), so it **rolls forward on its own** — no annual edit. It
  falls back to the full data window if that quarter has no data yet.
- The **date range stays the single source of truth**; the selected quarter is *derived* from it by
  **`syncQuarterFromRange()`** (was `syncQuarterChips`; `toggleQuarter`/`renderQuarterChips` were
  deleted with the chips). A custom calendar range resolves to **no** quarter and `qtrLabel()`
  captions read a neutral "Quarter". The **Q2+Q3 union** (`[Apr 1, dataMax]`, labelled "Q2-Q3") is
  still reachable by selecting a spanning range.
- The `.qtr-filter`/`.qtr-group`/`.qtr-chip` **CSS stays** — the Client/Admin view toggle reuses it.

**RIG drops out of the MARKETS filter under Q3** (client request 2026-07-09 — "remove the RIG filter
option when Q3 is toggled"): the Core DG Q3 plan carries **no RIG line**, so `visibleMarkets()` hides
the RIG chip AND excludes RIG from the data (`matchMarket` + the by-region grid) when Q3 is the active
quarter (Q3 selected, not Q2). RIG stays under Q2 and the Q2+Q3 union (both have RIG Q2 data). In
practice Q3 has zero RIG rows anyway, so this only removes an irrelevant chip — no headline number
changes. (The CS Comparison tab's A/B region dropdowns are NOT yet quarter-scoped, so they still list
RIG; low priority.)

**RIG is now Q3-hidden EVERYWHERE, not just the CS Overview (2026-08-05** — client: "RIG shouldn't be
detailed in the market focus for Q3"**)**: (1) the **Paid Media tab** got the same quarter gate —
`paidRigHidden()`/`paidVisibleMarkets()` mirror `visibleMarkets()`, so under a Q3-only selection the
RIG chip, its market-table/chart rows, its KPI contribution (`passesAll`) and its whole-flight
creative rows all drop out; `syncQuarterFromRange()` re-chips the paid tab too. This also killed the
phantom **$0.00 RIG row** the client saw under Q3: TTD's `ALL` token remaps to RIG and ~6 imps /
$0.002 of trailing post-Q2 `ALL` rows kept the row alive (`spendByMarket()` only drops EXACT-zero
markets). (2) the **QoQ tab's "Accepted leads by market" grid** drops the RIG row unconditionally
(that tab is Q3-vs-Q2 by construction; a RIG row read as a false collapse — Q2 74 leads vs a Q3 that
was never booked). RIG leads still count inside the QoQ status totals; only the market detail row is
gone. RIG still shows under Q2 / Q2-Q3 / custom ranges on the paid tab, and the deck payload stays
whole-flight all-markets (RIG's Q2 data belongs there). If a REAL `ALL`-market campaign ever runs in
Q3, un-gate `paidRigHidden()` and give it its own token — the data is only hidden, never discarded.

The selection is **global** — it drives Paid Media, Content Syndication and CS Comparison alike (the
QoQ tab is Q3-vs-Q2 by construction and ignores the range). Implemented entirely in
`dash/dashboard.html` (`QUARTERS`/`QUARTER_ORDER`/`quarterSpan`/`currentQuarterKey`/
`syncQuarterFromRange`/`visibleMarkets` + the generated quarter presets); no data-layer change.
**Because the default is now Q3, the RIG market chip is hidden on load** (see above) — expected, not
a bug.

**Q3 targets/pacing are loaded (2026-07-09).** The Q3 target rows are in `seed_real_targets`, so the
Q3 view now shows real target KPIs + the two pacing cards (`renderLeadsTarget`, `renderProgress`). The
target-less placeholder (target KPIs `—`, *"Targets & pacing not set for the selected period yet —
showing actuals only"*) still fires automatically for any span with no `ALLOCATED_TARGET` rows (e.g.
a custom range past Q3, or RIG under Q3 — the Core DG plan has no RIG line). To reload targets: edit
`targets/real_targets.csv` → `seed_static.py` (or the targeted `bq load`) → job `FORCE_REBUILD=1`; the
pacing UI reflects it on the next build (the service serves the bucket live, so **no dashboard redeploy
is needed** unless `dashboard.html` itself changed).

**Target KPIs + the "Pacing - target vs actual" chart are QUARTER-ANCHORED, not range-clamped
(2026-07-09).** The shared date range clamps to the last day that has data, so for an in-progress
quarter (Q3, data only to ~week 1) a range-clamped target/pacing would show only the elapsed weeks
(the "Q3 Target = 182 instead of 2290" / "Q3 pacing chart shows only week 1" bugs). Fix: `aggregate()`
computes the target over the full selected-quarter span via `pacingWindow()`/`quarterTargets` (headline
`q2Target`, `ttdTarget`, `regionRows`), and a dedicated **`pacingDaily`** series (also full-quarter)
backs `renderWeekly` so Q3 shows every one of its 13 plan weeks like Q2 shows 12. Actuals still appear
only where leads exist (future weeks carry target + 0 actual; a small pre-plan-week bucket holds any
leads that arrived before the plan's first Monday). The daily accepted-leads line (`renderDaily`) and
the CS Comparison panels still read the in-range `dailyFull`/`weekly`. **The pacing chart has
**Month/Week only** (no Day grain) - client request 2026-07-09.

**ABSOLUTE ONLY, DASHBOARD-WIDE (2026-08-20, client request).** The Relative/Absolute **AXIS** toggle
is gone from every chart group here - the client reads these as real values and the indexed view was
generating more questions than it answered. This is a documented **exception to the repo-wide toggle
rule** in `md/AGENTS.md`. What was removed: the six `<span class="seg" id="*_scale">` controls
(`csWeekly`, `csDaily`, `ttdImpCtr`, `dailyStack`, `effTrio`, `cmp`), their `wireToggles` bindings
(each call now passes `null` for the scale seg) and the copy that offered the option. The five scale
vars are now **`const pmScale/effScale/cmpScale/csDailyScale/csWeeklyScale = 'abs'`**, so every
builder's `isRel`/`cmpRel` is permanently false. **The relative branches are deliberately KEPT** -
they are what a restore would use, so absolute is enforced in ONE place rather than by deleting ~200
lines of chart logic. The **Month/Week/Day grain toggles are untouched.** Verified in a browser after
deploy: across all four tabs and all five dropdown lanes, zero `*_scale` elements, zero
Relative/Absolute buttons, and **no chart renders an "Index (peak=100)" axis** - every axis reads a
real unit (Leads, Impressions, Clicks, CTR (%), CPC ($), Spend (USD), Cumulative).

### Budget pacing by channel (2026-07-20)

A **pacing section sits directly under the "Channel performance vs media plan benchmarks" table** on the
Paid Media tab - one horizontal bar per channel that ran in the **selected quarter** (it **follows
`selQuarters`**, itself derived from the calendar range). Each bar's **orange fill = billed spend within that quarter**, a
**dashed vertical marker = where spend should be today to finish the quarter on budget** (budget x fraction
of the quarter elapsed; a *complete* quarter pins the marker at 100%, so the bar reads as final delivery vs
budget), and the figure on the right is the **$ gap to pace** (behind / on / ahead). Frontend-only
(`renderPacing()` + the `.pace-*` CSS in `dash/dashboard.html`) - no data-contract or job change; it reads
the existing `paid_media.rows[]`. Re-renders on every quarter change (`applyDateRange → renderPaidMediaAll`).

- **Quarter-driven** (`PACING_PLANS` keyed by `Q2`/`Q3`; a custom calendar range that resolves to no
  quarter shows every quarter). **Q3** shows **TTD + LinkedIn** only (Reddit was dropped in Q3, LINE isn't a Q3 platform);
  **Q2** shows **all four** (TTD, LinkedIn, Reddit, LINE). "today" = the browser clock clamped to the
  flight. The section is deliberately **independent of the date-range picker and market chips**
  (whole-quarter, all-market) - filtering the dashboard does not move it.
- **Budgets are a hardcoded editable knob** `PACING_PLANS` in `dash/dashboard.html` (same pattern as
  mongodb's `MARGIN_TARGET` / the `CF1_CS_TARGET`); NOT in the pipeline - edit the const and redeploy the
  dash service (no job/view rebuild).
  - **Q3: TTD $47,624.56 / LinkedIn $61,022.44** - media-plan platform budgets from
    `targets/real_targets Q3.csv` ("Program total (APAC + JP)").
  - **Q2: every channel uses `useActual:true`** - Q2 has NO committed spend budget in the repo, so the
    budget IS the actual Q2 spend (each bar reads 100% delivered, $0 gap - a placeholder). Swap a channel's
    `useActual` for a `budget` number once the real Q2 figure is known, and its bar shows real over/under.
- **Multiplier-aware:** the budget is grossed by the same per-channel client-billed spend multiplier as
  spend (`bbMultFor`), so the pacing % is invariant to raw (direct) vs billed (front-door) access - it
  reconciles with the (also-grossed) spend column in the table above it.

### Paid Media shows only the channels that RAN in the selection (2026-08-05)

Client request alongside the Q3 default: **a channel with no activity in the selected period must not
appear at all** - Reddit and LINE are Q2-only, and under Q3 they were drawing empty zero rows,
zero-width donut slices and flat zero trend lines that read like under-delivery.

**`PM_CHANS` in `dash/dashboard.html` is now the ONE channel roster** (`key` / `label` / `long` /
`abbr` / `pill` / `color` / `pre` field-prefix / `mkey` market field / `rows()` accessor) and
**`activeChans()`** filters it to the channels with real delivery (spend **or** impressions **or**
clicks) inside the applied **date range** - so it follows the calendar, and a channel reappears the
moment a range covering its flight is selected. Everything channel-shaped renders from it:

| Piece | Behaviour |
|---|---|
| Spend KPI caption, blended spend/imps/clicks/CPM/CTR/CPC, "vs plan" CPC caption | live channels only (`renderPaidKPIs`) |
| "Spend by channel" donut + its hint line | one slice per live channel; hint reads e.g. "Trade Desk + LinkedIn mix." |
| "Daily spend - all channels stacked" | one stacked series per live channel |
| Daily efficiency trio (CTR / Clicks / CPC) | one line per live channel - was a hardcoded TTD/LinkedIn/Reddit trio, so **LINE now plots too under Q2** (`channelByGrain` gained the missing `ln_imp`/`ln_clk` sums) |
| "Channel performance vs media plan benchmarks" table | one row per live channel + an explicit empty-state row |
| "Market breakdown - …" heading, market stack / bar / table | heading names the live channels; stacked series + market totals sum only over them (`chanTotal`) |
| Creative channel filter + both creative tables | only live channels are offered and included; a pick that goes inactive falls back to "All channels" |
| TTD section (heading + "TTD daily" card) | hidden unless TTD delivered |
| LinkedIn funnel card | hidden unless LinkedIn delivered |
| Paid footer "Source: …" | lists the live channels |

**"LinkedIn leads vs weekly target" now hides outside its plan window.** `li_weekly`
(`sql/09_li_weekly_targets.sql`) is the **fixed 13-week Q2 plan** (Mar 30 - Jun 30), so the block
renders only while the selected range overlaps that window. This also fixes a real defect the Q3
default would have exposed: `weekIndex()` matched "any date >= the last week start", so **every
post-Q2 lead was piling into the W13 bar** - it now returns -1 outside `[planStart, planEnd]` (both
parsed from the plan's own `period` strings).

Market rows follow the same rule (`spendByMarket()` already dropped zero-spend markets). Frontend-only
- no `sql/`, `job/main.py` or data-contract change.

**Liveness keys on the DATE RANGE ONLY, deliberately not on the market chips.** If it also honoured
the chips, a channel whose markets all failed to parse would **vanish** from the tab instead of
showing a visible zero row - precisely the silent row-loss failure mode the [brief-number prefix
fix](#brief-number-campaign-prefixes-broke-paid-media-market-parsing-fixed-2026-08-04) chased down
(unmapped `MARKET_L3` passes the model's non-empty guard, then matches no chip, then `passesAll()`
drops it from every aggregate). A parsing regression must stay loud. It also keeps the channel list
stable while chips are toggled, instead of channels appearing/disappearing under the cursor.

### Q3 LinkedIn lead-gen commit plan - weekly pacing + benchmark "vs plan" lead columns (2026-08-06)

Client sheet (via JM): Q3 lead-gen is **LinkedIn only** and runs **only in 4 markets** -
ANZ $18,051 / CPL $301 / 60 leads, ASEAN $10,066 / $126 / 80, SAARC(India) $6,798 / $115 / 59,
GCR(HK) $2,858 / $260 / 11 = **$37,773 / 210 committed leads**. Frontend-only, all in
`dash/dashboard.html`:

- **`LI_LEADGEN_PLANS`** is the hardcoded editable knob (same pattern as `PACING_PLANS`); keys match
  the market chips (SAARC = India, GCR = HK). Edit it + redeploy the dash service to change the plan.
- **"LinkedIn leads vs weekly target" is now quarter-aware** (`renderWeeklyTarget` dispatches): a
  range touching Q3 renders the Q3 plan **paced FLAT by day** over Jul 1 - Sep 30 (`liPlanWeeks` -
  Monday-aligned weeks clamped to the quarter, so the partial first/last weeks get proportionally
  smaller targets and the cumulative target lands exactly on the commit); otherwise the fixed Q2
  `li_weekly` path renders unchanged. **Targets follow the market chips** (`liPlanScope`: all chips =
  210 total; one market selected = that market's commit), actuals follow chips + date range as
  before. The Q3 block **shows even with zero LinkedIn delivery** (a commit plan with no delivery
  must read behind, not vanish) - unlike the Q2 path, which still hides via `chanIsActive`.
- **The "Channel performance vs media plan benchmarks" table gained right-hand `Leads / vs plan /
  CPL / vs plan` columns** (LinkedIn row only; TTD has no pixel). Leads are graded against the
  **whole-quarter commit** (`liQ3PlanCtx`, scoped to the selected market chips); CPL vs the blended
  planning CPL of those markets. **Both cells read the table's plain `actual vs plan` shape**
  (`352 vs 210`, `$94 vs $180`) since 2026-08-17 - they were the only two with extra wording
  (`of 210 commit - pace 85`, `vs $180 plan`). Leads used to be graded against the **flat
  pace-to-date** (commit x fraction of Q3 elapsed) while the cell printed the commit, which only
  self-explained because `pace 85` was printed beside it; shortened, that reads as
  `352 vs 210 -> +314%` and invites the client to check the arithmetic. **The delta must grade the
  two numbers on screen**, so Leads now grade the commit like every other column (full-period plan
  benchmark, date-ranged actual). The pace-to-date is not lost - it is in the cell's `title`
  tooltip, and the "LinkedIn leads vs weekly target" chart below is the block that tells the
  flat-pacing story properly (cumulative target line). `liPlanScope().pace` is still computed and
  is the knob if a pro-rated grade is ever wanted back. Renders only
  under a **pure-Q3 selection** (a quarter commit can't grade Q2 or a custom sub-range - cells fall
  back to `-`). CAVEAT: actual CPL uses ALL LinkedIn spend (the feed has no campaign-objective
  split), so it reads conservative vs the lead-gen-line plan CPL - noted in the cell tooltip;
  splitting lead-gen campaigns out would need a `sql/` change.

### LinkedIn creative lead efficiency - top 10 by CPL / by CVR (2026-08-26, client request)

Two ranked tables on the Paid Media tab, sitting **directly under the LinkedIn funnel card**:
**Top 10 creatives by cost per lead** and **Top 10 creatives by conversion rate**. Placement is the
point - the funnel prints LinkedIn's blended CPL and click-to-lead rate, and these tables are that
same pair of numbers broken down to the creative that earned them.

**Definitions, deliberately identical to the funnel above** so no two figures on the tab disagree:
`CPL = spend / submitted leads`, `CVR = submitted leads / clicks`. Spend is the GROSSED figure
(`bbApplySpendMult` has already run over `PAYLOAD.creatives`), the same billed basis as every other
dollar on the tab.

**The data change was one column.** `sql/06_paid_creatives_model.sql` now carries `FORM_OPENS` on the
LinkedIn arm (`NULL` on the other four - they have no lead form at all, which is not the same as zero
starts) -> `job/main.py` `form_opens` -> `adaptPayload` `formOpens`. `LEADS` was already there, so CPL
and CVR were derivable before; the form-start stage is what makes a low CVR *diagnosable* - nobody
opening the form is a targeting problem, opening and abandoning is a form problem. Verified against
`paid_media_model`: LinkedIn ties EXACTLY on leads / form opens / clicks / spend
(590 / 6,779 / 21,149 / $153,281.15), so each table's totals row equals the funnel above it.

**Gotchas, all of them learned from the live data:**

- **The floor is on LEADS (3), not impressions.** The CTR tables floor at 1,000 impressions because
  CTR is a rate over impressions; CPL and CVR are rates over LEADS. A one-lead creative has a CPL that
  is simply its whole spend and a CVR that swings by whole points on one form submit - 8 clicks and
  1 lead is a 12.5% CVR and means nothing. At 3 leads, 22 of the 40 lead-bearing LinkedIn creatives
  qualify. It **relaxes to 1 automatically** when the selection is too narrow to fill a table (GCR
  alone has 5), and the note says which floor is in force - a caveated table beats a blank one.
- **NO green/red verdict colour, and do not add one.** It was built, then removed the same day:
  a top 10 ranked ascending by CPL, measured against a blend that includes the zero-lead awareness
  creatives, is green in EVERY row of EVERY market selection (verified at all-markets, ANZ-only and
  GCR-only). A colour that cannot go red looks like a judgement while making none. The ranked column
  carries the LinkedIn blue instead, and the reference lives where it can be read - the blend
  sentence and the table's own pinned totals row.
- **The blend deliberately includes awareness creatives.** It is the whole-channel CPL, which is why
  it ties to the funnel - but it therefore sits well above any individual lead-gen creative. The
  caption says so ("lead-gen and awareness together") rather than dressing every row up as beating
  a benchmark. Scoping it to lead-bearing creatives only would put two different LinkedIn CPLs on
  one tab; do not.
- **Volume is a percentage, not a bar.** A bar was built first and removed: the distribution is far
  too skewed (top creative 134 leads, most 3-22), so nine rows in ten drew an empty track, which
  reads as failure rather than as small.
- **`prettyLiCreative()` is a SECOND decoder, not a replacement.** `prettyCreative()` was written for
  the TTD/LINE display names and recognises none of the LinkedIn tokens, so it renders these
  14-token ad-set names as a wall of raw string. The LinkedIn one keeps only what changes a media
  decision (message, asset format, funnel stage, audience, concept). It matches **by token, never by
  offset** (the repo-wide rule) - and position is already unreliable here: one live ANZ ad set is
  named `Create CLOUD_ACQ_...`, which shifts its whole name by one.
- **The country token is dropped ONLY when it equals the market pill.** Blanket-skipping it collapsed
  `APAC-TCN_HK` against `APAC-TCN_HKTW` and merged the three ASEAN sub-markets (SGMYID / SGMYTH /
  VNPHID) into one label - three of the seven markets are multi-country. `prettyLiCreative(raw, market)`
  compares against the row's own market, so it needs no list and stays right if a market is added.
- **`lceTable()` de-duplicates labels.** The `Create CLOUD_ACQ_...` ad set decodes identically to its
  twin, and two identical-looking rows carrying different numbers is the one failure a ranked table
  must not have. Both currently have 0 leads so neither can surface, but the guard is not conditional
  on that. The raw name is on the `title` of every row regardless.
- Scope is the market chips + the lane + the RIG quarter gate, and **NOT the Channel seg** - that
  control belongs to the CTR section's header. Whole flight, because these rows carry no date.
- The block hides entirely when LinkedIn did not deliver in the selection, so the **Surround ABM lane
  (Trade Desk only) never shows it**. Verified.

**Redeploy order:** `sql/deploy_views_cloudflare.ps1` -> `job/deploy_job_cloudflare.ps1` ->
`dash/deploy_dash_cloudflare.ps1` (the view feeds the job, the job feeds the JSON the dash reads).

## The data contract (`cloudflare.json` -> `/data.json`)

```json
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",
  "data_through": "YYYY-MM-DDTHH:MM:SSZ",
  "paid_media": {
    "row_count": 0,
    "window": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { "channel","program","date","week_start","market","imps","clicks","spend_usd",
                "leads","form_opens","link_clicks","action_clicks","video_starts",
                "video_completions","video_imps","video_views","video_q50","video_q75",
                "conversions","spend_jpy","fx_usd_jpy" } ],
    // `channel` is one of TTD / LinkedIn / Reddit / LINE / Google Ads. The job does NOT enumerate
    // channels - it copies whatever paid_media_model emits - so adding a channel is a SQL + frontend
    // change only (that is how Google Ads landed 2026-08-11 with no job edit).
    "creatives": [ { "channel","program","market","creative","imps","clicks","spend_usd","leads",
                     "form_opens" } ],
    // `form_opens` (2026-08-26) is LinkedIn-only - NULL on the other four channels, which have no
    // lead form at all (not zero starts). It feeds the "LinkedIn creative lead efficiency" tables.
    // ga_campaigns (2026-08-31): Google Ads at CAMPAIGN grain (whole-flight, no date column),
    // queried by the job straight from stg_google_ads. Feeds ONLY the PMax strip
    // (renderGaPmaxNote). spend_usd is raw; bbApplySpendMult grosses it by the google factor.
    "ga_campaigns": [ { "campaign","first_day","last_day","spend_usd","imps","clicks","conversions" } ],
    "benchmarks":        { "<channel>": { "ctr","cpm","cpc" } },
    // GoogleAds joined benchmarks_channel 2026-08-31 (client flag: its row graded against zeros).
    // Source is NOT the media plan (which predates the channel) but the client-shared Q3 workbook
    // CF_Q3_July_Channel_Benchmarks_v3.xlsx: CTR 0.12% (YouTube in-stream), CPM $4.00 (Japan
    // YouTube). It commits NO CPC benchmark, so CPC is NULL and the dashboard prints the bare
    // actual + a "-" delta (benchVs() in renderBenchmarkTable - a falsy benchmark never renders
    // "vs $0.00"). The video strip's view-rate/CPV benchmarks (31.9% / $0.067, same workbook) are
    // frontend consts GA_VTR_BM/GA_CPV_BM in renderGaVideoNote() - update all of these together.
    "benchmarks_market": { "<market>":  { "ctr","cpm","cpc" } },
    "li_weekly": [ { "week","period","week_start","target","cum_target" } ]
  },
  "pacing": {
    "row_count": 0,
    "rows": [ /* every column of V_PACING_FINAL_MODEL, dates as ISO strings */ ]
  },
  // cs_composition (2026-09-05): the five composition donuts for a non-legacy theatre. Long
  // format - one row per scope x dimension x value with the accepted (+ New) count; dim is one
  // of solutions / countries / jobFunc / jobLevel / jobTitle. Scoped in the browser by
  // cspdScopeOk(), the same predicate as cs_pacing. Absent on an older JSON -> the donut rows
  // hide themselves off-theatre. See sql/19_cs_composition_v2.sql + cscxDims().
  "cs_composition": {
    "row_count": 0,
    "rows": [ { "theatre","book","vendor","market","dim","value","accepted","unprocessed" } ]
  },
  // cs_compare (2026-09-02): the CS Comparison panels for a non-legacy theatre. Same lead
  // universe as cs_pacing, one grain finer (it keeps country / asset / day, which the panels
  // need and the week-grain pacing view aggregates away). Carries NO targets - those live on
  // cs_pacing and must not exist twice. Absent on an older JSON -> the tab simply does not
  // appear on that lane. See sql/18_cs_compare_v2.sql + the BB:EMEACOMPARE block.
  "cs_compare": {
    "row_count": 0,
    "rows": [ { "theatre","book","vendor","market","country","day","week_start",
                "service","asset","leads","delivered","accepted","rejected","unprocessed" } ]
  },
  "cs_pacing": {
    "row_count": 0,
    // Region-resolution guard (2026-09-04): campaigns sql/16 could not place in a theatre from
    // CAMPAIGN_ID or name, or whose name market belongs to a different theatre than the id.
    // Those leads are on NEITHER lane; this is what makes them visible (Admin View card
    // `cspdUnresolved`). leads=0 -> card hidden. region_source = census of how every lead was
    // placed ({id, name, none}) - the job prints it every run.
    "unresolved": { "leads": 0, "accepted": 0, "campaigns": 0,
                    "items": [ { "campaign","campaign_id","theatre","market","reason","leads","accepted" } ] },
    "region_source": { "id": 0, "name": 0, "none": 0 },
    "period_label": "Q3",     // the quarter the TARGETS SEED covers; drives the section's own
                              // captions + its "<period> to date" chip, NOT the date picker
    "reasons": [],            // rejection reasons: NO live source yet (manual at the Integrate
                              // push). Panel renders only when non-empty; never fabricate.
    "rows": [ { "theatre","book","vendor","market","market_seq","week_start","week_number",
                "target","delivered","accepted","rejected","unprocessed","needs_review" } ]
    // AGGREGATED + PII-free (counts by book x week x market x vendor), ~100 KB - NOT the lead
    // grain. `book` (2026-08-27) is which PLAN the campaign is bought under - "Core DG",
    // "Regional" (the ANZ DnB book: DemandAI / Interlink / SitPub) or "Unclassified" - and is a
    // SEPARATE dimension from `theatre`. The dashboard's campaign picker never sums two books
    // together, because only Core DG has a seeded target. A payload written before `book`
    // existed renders as it did: the dashboard reads a missing key as "Core DG".
    // The view's convenience REJECTION_RATE / ACCEPTANCE_RATE / WEEKLY_PACING / LEAD_DEFICIT
    // columns are deliberately NOT carried: they are correct only at that exact grain, and
    // the dashboard re-derives every rate from the counts after aggregating.
  },
  "campaigns": {
    "peyc":        { "label","campaign_group","window","totals","daily":[…],"by_campaign":[…] },
    "cf1_india":   { …same…, "cs": { "target":110,"metric","accepted","rejected","new","total",
                                      "reviewed","data_through","by_publisher":[…],"by_region":[…],"daily":[…] } },
    "coles_hyper": { … }
  },
  "transmission": {
    "source_ids": [ { "id","campaign","leads","accepted","rejected","unprocessed","present" } ],
    "pacing": { "rows":[ {"market","tier","q2","q3","total"} ], "q2_total","q3_total","grand_total" }
  }
}
```

`transmission` (2026-07-10) powers the committed-data tables on the dev-only **"Internal Notes" tab**
(named "Data from Transmission" until 2026-08-05) - what Transmission
committed for this dashboard: `source_ids` = the canonical CS Source-ID list that should be present
(from `seed_cs_campaign_ids` / `definitions.json`) LEFT-JOINed to `salesforce_leads_live` so each ID
shows what has landed (+ a `present` flag); `pacing` = the target plan they sent (`targets_v2_norm` over
the committed `real_targets.csv`), per market x tier with a Q2/Q3 split. Built by
`build_transmission()` in `job/main.py`. See _Dev mode_ above.

`dashboard.html` reads `paid_media` exactly like the old `paid_media.json`
(`adaptPayload` is unchanged) and `pacing.rows` exactly like the old
`pacing.json` (`rawRows`). The `paid_media.creatives[]` array (creative-grain
delivery) powers the "Top & bottom performing creatives" tables **and the "LinkedIn
creative lead efficiency" tables** (see that section below) — **these rows
carry NO `date`, so the dashboard filters them by the market chips ONLY, never the
date range** (`renderCreativeTables` uses `paidMediaActiveMarkets.has(r.market)`, NOT
`passesAll()`, whose `dateOk(undefined)` would silently blank the tables). Their
`market` is raw TTD `MARKET_L3` (e.g. `HKTW`, `CN`, `AUNZ`, `SGMYIDPHTH`), so every
token must be in `PM_MARKET_REMAP` or the row falls outside the 7 L1 buckets and
drops. `campaigns`
powers the three single-campaign LinkedIn dashboards selectable in the top-bar
dropdown (read from the shared `raw_snowflake.linkedin_ads_apac` mirror, not from
Snowflake directly). **CF1 also carries a content-syndication lane** (`campaigns.cf1_india.cs`,
from `sql/14_cf1_cs`): "Double Touch MQLs" vs a **110 target** — accepted/rejected, by
publisher/region, and a cumulative-delivery line keyed on the lead `DAY`. It's the 2 CF1
CS campaign IDs (vendors→CaptureIQ→Integrate→Salesforce; also in the core 13-ID filter, but
this is a separate CF1-scoped view). In the UI the CF1 single-campaign view is split into two
**tabs** (`#cmpTabs`, mirroring the Core dashboard's tab pattern): **LinkedIn Paid Media**
(`#cmpLI`, default) and **Content Syndication** (`#cmpCS`). `setupCmpTabs()` shows the tab bar
only when a campaign has a `cs` block — peyc/coles_hyper have none, so they stay a single
LinkedIn view with no tabs. `switchCmpTab()` toggles the panels and `.resize()`s the charts
(Chart.js can't size a canvas created while `display:none`). Target is the one knob
(`CF1_CS_TARGET` in `job/main.py`). `data_through` is the newest source `LAST_ALTERED` (true
data instant); `last_updated` is the build time. See `dash/DASHBOARD.md`.

**Channel / market labels must match the dashboard:** `benchmarks` keys must be
`TTD`, `LinkedIn`, `Reddit`, `LINE`, `GoogleAds`; row `channel` must be one of
`LinkedIn`/`LI`, `TTD`/`TradeDesk`, `Reddit`, `LINE`; markets must be the seven
in `all_markets`. These come straight from the Snowflake views — if your view
emits different strings, fix it in `sql/` (the only place that maps them).

---

## One-time replicate / deploy order

Prereqs: `gcloud` authenticated; APIs enabled (`run`, `cloudbuild`,
`artifactregistry`, `bigquery`, `storage`, `secretmanager`); the Artifact
Registry docker repo `bidbrain` exists; the shared Snowflake key secret
`snowflake-bq-key` exists (same one MongoDB uses).

```bash
PROJECT=bidbrain-analytics
REGION=australia-southeast1

# 1. Private data bucket
gcloud storage buckets create gs://bidbrain-analytics-cloudflare-dash \
  --project $PROJECT --location $REGION --uniform-bucket-level-access

# 2. BigQuery dataset
bq --location=$REGION mk --dataset $PROJECT:client_cloudflare

# 3. Runtime service accounts
gcloud iam service-accounts create cloudflare-dash-job --project $PROJECT
gcloud iam service-accounts create cloudflare-dash-web --project $PROJECT
#   job: read/write its dataset + bucket, read the Snowflake key
bq update --dataset --source <(echo '{}') $PROJECT:client_cloudflare  # (or grant via IAM policy)
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-cloudflare-dash \
  --member="serviceAccount:cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
#   (also grant cloudflare-dash-job roles/bigquery.dataEditor on the client_cloudflare dataset)
#   web: read the bucket + its two secrets
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-cloudflare-dash \
  --member="serviceAccount:cloudflare-dash-web@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# 4. Secrets
printf 'choose-a-dashboard-password' | gcloud secrets create cloudflare-dash-password --data-file=- --project $PROJECT
python -c "import secrets;print(secrets.token_urlsafe(48),end='')" | gcloud secrets create cloudflare-dash-session-key --data-file=- --project $PROJECT
#   grant both secrets to cloudflare-dash-web (roles/secretmanager.secretAccessor)
#   (the job is BQ-only now — it does NOT need snowflake-bq-key. pull_static.py does,
#    but that's a manual one-time local run, not the scheduled job.)

# 5. Seed the static tables into BigQuery. data/ is gitignored, so on a fresh checkout pull
#    the snapshots first (needs the Snowflake key); then load them to BQ (no Snowflake).
python clients/client_cloudflare/pull_static.py    # Snowflake -> data/*.csv (skip if data/ already present)
python clients/client_cloudflare/seed_static.py    # data/*.csv -> client_cloudflare.seed_*

# 6. Apply the BigQuery model views (needs the seeds + raw_snowflake.* mirrors to exist)
python clients/client_cloudflare/create_views.py

# 7. Run the job — reads the views, produces cloudflare.json in GCS (no Snowflake)
python clients/client_cloudflare/job/main.py

# 8. Build dashboard.html from your existing index.html (see dash/DASHBOARD.md)

# 9. Deploy the SERVICE — build the image, then deploy as yourself.
#    (Do NOT `gcloud builds submit --config .../cloudbuild.yaml` from a laptop: it fails
#     with iam.serviceaccounts.actAs because Cloud Build's SA can't act as the runtime SA.
#     The cloudbuild.yaml files are for a future push-to-main trigger only.)
IMG=australia-southeast1-docker.pkg.dev/$PROJECT/bidbrain/cloudflare-dash:$(git rev-parse --short HEAD)
gcloud builds submit clients/client_cloudflare/dash --tag $IMG --region $REGION
gcloud run services update cloudflare-dash --image $IMG --region $REGION \
  --service-account cloudflare-dash-web@$PROJECT.iam.gserviceaccount.com \
  --set-env-vars=GCS_BUCKET=bidbrain-analytics-cloudflare-dash,DATA_OBJECT=cloudflare.json \
  --set-secrets=DASH_PASSWORD=cloudflare-dash-password:latest,SESSION_SECRET=cloudflare-dash-session-key:latest \
  --memory=512Mi
gcloud run services update cloudflare-dash --region $REGION --no-invoker-iam-check  # org policy: app does its own auth

#10. Deploy the JOB the same way (or just keep running it locally while testing)
IMG=australia-southeast1-docker.pkg.dev/$PROJECT/bidbrain/cloudflare-export:$(git rev-parse --short HEAD)
gcloud builds submit clients/client_cloudflare/job --tag $IMG --region $REGION
gcloud run jobs deploy cloudflare-export --image $IMG --region $REGION \
  --service-account cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com --memory 1Gi
```

Then, mirroring MongoDB:
- **Freshness-gated run** — Cloud Scheduler trigger executing the `cloudflare-export`
  job every `*/10` (UTC). Run [`scheduler.ps1`](scheduler.ps1). The job is **self-gating**:
  each tick it cheaply probes `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` for its four upstream
  Snowflake tables (metadata-only — no warehouse credits) and only does the full rebuild +
  upload when one advanced, recording a `_freshness.json` watermark in the bucket. So the
  dashboard refreshes **within ~10 min of new data** instead of at a fixed 22:00 UTC, while
  most ticks are a ~3s no-op. The payload carries both `last_updated` (build time) and
  `data_through` (newest source `LAST_ALTERED`). Re-running [`seed_static.py`](seed_static.py)
  changes a *static* input that the gate doesn't watch, so kick the job once by hand after it
  (`gcloud run jobs execute cloudflare-export --region australia-southeast1 --wait`). See
  [`job/README.md`](job/README.md#freshness-gate--why-most-runs-do-nothing-and-thats-the-point).
- **Access path** — via the platform front-door at `https://dashboards.bidbrain.ai/d/cloudflare/`
  (one login over all dashboards; the front-door reverse-proxies this service). There is no
  `cloudflare.bidbrain.ai` subdomain. See `dash/LIVE_URL.md`.
- **CD (future, not active)** — the per-unit `cloudbuild.yaml` files are wiring
  for two push-to-`^main$` Cloud Build triggers (included files
  `clients/client_cloudflare/job/**` and `clients/client_cloudflare/dash/**`). Not enabled yet;
  redeploys today use the manual build-then-deploy steps above.

## See also

- [Root README](../../README.md) — the whole-platform map, security model, and naming conventions.
- [`../client_mongodb/`](../client_mongodb/README.md) — the template this client is based on (and diverges from).
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — the shared raw layer this client now reads (`salesforce_cs_apac_all`, `tradedesk_apac_all`, `linkedin_ads_apac`, `reddit_ads_apac_all`), like every other client.
