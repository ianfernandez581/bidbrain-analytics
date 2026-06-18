# VMCH — Villa Maria Catholic Homes · Performance Dashboard

Australian aged-care / disability / retirement-living **not-for-profit**, run by the agency
**100% Digital** (agency slug `100-digital`). This is a **brand-awareness** build, not an
e-commerce one: there is **no revenue / ROAS**. The website outcome is *enquiries* — phone
calls, email clicks and contact-form submits (GA4 key events). One paid channel (The Trade
Desk programmatic display) set against the VMCH website (GA4).

> Lineage note: copied from the STT archetype (GA4 + media). An earlier automated port left a
> broken STT clone in the dashboard (phantom Google/DV360/LinkedIn cards, "9 APAC markets",
> empty country filter, undefined CSS vars). The **data layer (SQL views + `job/main.py`) was
> sound**; the **`dash/` layer was rewritten from scratch** to match VMCH's real two-source,
> single-market, no-revenue shape and rebranded. See _Caveats_.

## EDA summary (14 Jun 2026)

| Source | Table | Account / Advertiser | Window | Spend | Notes |
|--------|-------|----------------------|--------|-------|-------|
| The Trade Desk (Windsor) | `raw_windsor.perf_the_trade_desk` | `VMCH ` (trailing space) | 2026-04-30 → 2026-06-12 | **A$20,445** | 4.4M imps, 3,248 clicks, AUD (no FX) |
| GA4 (DTS) | `raw_ga4.perf_ga4` + `…_events` | `VMCH Website - GA4` | flight ≥ 2026-04-01 | — | 124,634 sessions, 76,764 users; enquiries via key events |

**Decision gates (all resolved):**

| Gate | Finding | Decision |
|------|---------|----------|
| Revenue / `conversions_value`? | none (NFP) | **Awareness shape** — enquiries, not ROAS |
| Other ad platforms? | **none** in `raw_google_ads` / `perf_meta` / Windsor Google Ads | **Single platform = The Trade Desk** |
| Geo / market column? | none in either source | **Single market "Australia"** — no Country filter |
| TTD currency? | `AUD` upstream | pass-through, no FX (1.50 case present but unused) |
| Session conversions? | 0 (GA4 key-event tagging lapsed after Jan-2026) | **Count enquiries from `event_count`, not `conversions`** |
| Where are enquiries? | in `event_count` per `event_name` (Clicked to Call 957, Contact Us Form - Send 575, Book Call Back 551, Clicked to Email 253, Property Alert 97…) | `06_ga4_key_events.sql` regex-buckets them into 5 enquiry types; flight total ≈ **2,736** |
| Campaigns? | 4 = service lines RAC / RL / SAH / Disability | Campaign filter relabels them |
| Display → last-click sessions? | only ~25 GA4 "Display" sessions in-window vs 4.4M imps | **Frame display as upper-funnel** — reach + clicks, not 1:1 session lift |

## Dashboard (4 tabs)

`dash/dashboard.html` — one self-contained file. Filters: **Date range** (defaults to **all available
history**; flight marked on charts) + **Campaign** (4 service lines). No Country/Platform chips (single
market, single platform).

- **Overview** — the **combined campaign story**: the standalone `VMCH_Campaign_Analysis.html` retrospective
  (Oct 2025 – Mar 2026) **stitched to the live flight** (Apr 2026 →) into one continuous timeline. Built by
  the `OV` IIFE in `dash/dashboard.html`: the historical daily series is **hard-coded** in the module
  (`__HIST_DATA__`) and merged at render time with the live `DATA.daily` / `DATA.ad_campaign_daily` (the two
  are contiguous — analysis ends 2026-03-29, live begins 2026-04-01, no overlap). Channel map by campaign
  prefix: SAH→sah, RL→rl (live-only), RAC→rac, Disability→dis; `rt`=Retargeting is historical-only. Every
  time-series chart has a **Month/Week** grain toggle (`OV.setGrain`; aggregates the combined daily via `byGrain`)
  that re-renders the whole tab. Hero = **"effect of spend on results"**: spend stacked by platform (bars, drawn
  **behind**, `order:20`) + website-sessions line (front) + total-impressions line, with per-channel
  impressions/clicks + total clicks as **hidden, legend-toggleable** lines. Then exec summary,
  combined KPIs (full-timeline spend/imps/clicks/sessions + the original-flight 100 conversions + live TTD
  attributed), the 6 analysis charts (traffic overlay, first visits, engagement, campaign-by-unit — all
  continuous where data exists; first-visit/bounce/page-views/pages-per-session are historical-only as the
  live feed doesn't carry them), the disability conversion ramp, conversion breakdown + ROAS/LTV tables +
  8 recommendations (the Oct–Mar campaign retrospective). The date/campaign filters are inert on this tab
  (the combined narrative is fixed); they still drive the other three tabs. To revise, edit `OV` in
  `dash/dashboard.html` and redeploy the service — front-end only, no job/view change.
- **Trade Desk** — delivery KPIs (spend/imps/clicks/CTR/CPM/CPC), monthly spend+clicks, spend-by-
  campaign donut, campaign breakdown table (**now with Post-view / Post-click columns**), top ad groups,
  creative-format mix.
- **Website** — GA4 KPIs (total sessions led); a **Campaign effect** panel (`STATISTICAL MODEL`, see
  caveat 13); and three displays that all **scale with the Campaign filter by spend share** (additive;
  full data when all OR none selected): **Enquiries by type**, the **Sessions** trend (single line,
  was "total vs paid"), and **Enquiry events by type** by date (**flight-scoped**). The Campaign filter
  now shows on this tab (it was hidden). Removed: sessions-by-channel, Display-reach-vs-engagement, and
  Top sources/mediums.
- **Media → Traffic** — the full chain: **spend → impressions → clicks → post-click → post-view**
  conversions (funnel + stat strip), impressions-vs-sessions trend, correlation scatter, weekly clicks.
  Last-click Display sessions kept as an honest aside (small by design — display is upper-funnel).

## Coordinates

| Thing | Value |
|-------|-------|
| Folder / dataset | `clients/client_vmch/` / `client_vmch` |
| Data bucket | `bidbrain-analytics-vmch-dash` |
| Export job | `vmch-export` (SA `vmch-dash-job@bidbrain-analytics.iam.gserviceaccount.com`) |
| Web service | `vmch-dash` (SA `vmch-dash-web@bidbrain-analytics.iam.gserviceaccount.com`) |
| Secrets | `vmch-dash-password`, `vmch-dash-session-key` |
| Scheduler | `vmch-export-daily` (`*/10 * * * *` UTC, self-gating) |
| JSON object | `vmch.json` |

## Deploy / refresh

**First stand-up** (provisions everything — run once):

```powershell
.\clients\client_vmch\deploy_vmch.ps1
```

**Day-to-day** (see the per-stage scripts; raw commands in root `CLAUDE.md`):

```powershell
.\clients\client_vmch\sql\deploy_views_vmch.ps1     # edited a sql/*.sql view
.\clients\client_vmch\job\deploy_job_vmch.ps1       # edited job/main.py (JSON shape)
.\clients\client_vmch\dash\deploy_dash_vmch.ps1     # edited dash/dashboard.html or dash/main.py
gcloud run jobs execute vmch-export --region australia-southeast1 --wait   # manual refresh
```

## Branding

- Real assets in `creatives/`: `Logo.webp` (orange-red `#EB3300` "VMCH" wordmark, transparent),
  `Screenshot 2026-06-14 181950.png` (vmch.org.au — palette reference: orange `#EB3300` + maroon
  hero `#4C2736`).
- `creatives/inject_logos.py` inlines the VMCH logo (as a data URI) into the dashboard topbar
  (`<img class="brandlogo">`) and the login (`<img class="client">`). Idempotent — re-run after
  dropping a new logo.
- The **100% Digital** agency mark is an inline SVG wordmark in the topbar + login (no official
  raster asset exists in the repo; swap one in via the same inject pattern if provided).
- Palette lives in `dash/dashboard.html` `:root` + the JS `C{}`/`KE_PALETTE`, and `dash/main.py`
  `LOGIN_HTML` — edit there, not in `creatives/`.

## Caveats

1. **Single ad platform** — The Trade Desk only. `ad_*` KPIs == `ttd_*`. No Google/DV360/LinkedIn
   exist for VMCH; do not re-add those cards.
2. **Single market** — the `*_market` views (`ttd_markets`, `ga4_kpi_market`, `ga4_*_market`,
   `ad_campaign_market*`) are **vestigial single-row "Australia"** constructs inherited from the
   STT lineage. The job still emits them, but the dashboard reads the flat `kpi` / `monthly` /
   `ga4_channels_market` (aggregated) directly. Harmless; left in place to avoid a job/view churn.
3. **No revenue / ROAS** — NFP. Outcomes are GA4 **enquiries**: phone-call & email clicks, contact
   & call-back form submits, property/sales alerts. **GA4 `conversions` (key-event marking) is 0 for
   the whole 2026 flight — tagging lapsed after Jan-2026** — so `06_ga4_key_events.sql` counts the
   real enquiry ACTIONS from **`event_count`** (regex-bucketed into 5 categories by `event_name`,
   excluding donations / downloads / subscribes / form-starts / pure engagement). Flight total ≈ 2,736
   (Phone 957 · Contact 851 · Call-back 551 · Email 264 · Property/sales alert 113). `kpi.conversions`
   stays 0 and is no longer used for the headline. If GA4 key-event tagging is re-enabled upstream,
   revisit whether to switch back to `conversions`.
4. **Display is upper-funnel** — TTD drove 4.5M impressions but GA4 attributes only ~25 last-click
   "Display" sessions. Judge the flight on **reach, clicks (~3,435) and ad-attributed conversions**
   (≈113 post-view + 13 post-click — see caveat 5), not a 1:1 last-click session lift. Do not overclaim.
   The **Media → Traffic** tab makes the full chain explicit: spend → impressions → clicks → post-click → post-view.
5. **TTD-attributed conversions** (added Jun 2026) — the real "attributable leads". `03_stg_ttd.sql`
    parses Windsor's **double-encoded** `conversions` JSON (`PARSE_JSON(JSON_VALUE(conversions))`) into
    `post_view_conv` (view-through) + `post_click_conv` (click-through). **Pixels come in DUPLICATE PAIRS**
    (`*_01`==`*_02`, `*_03`==`*_04` row-identical ~99.9%), so sum ONLY the **distinct pixels {01,03,05}** —
    summing 01–05 double-counts. `conversion_touch_*` (~3,300) is **total pixel fires, NOT ad-attributed** —
    never surface it as conversions/leads. Flows `stg_ttd`→`stg_ad_delivery`→`ad_campaigns`/`_monthly`/`_weekly`/`_daily`
    (`post_view`/`post_click`) and `kpi` (`ad_post_view`/`ad_post_click`). De-duped flight totals: **113 post-view, 13 post-click**.
6. **Junk traffic excluded** — `01_stg_ga4.sql` filters out the `programmatic-display / *` source/medium.
    GA4 buckets it into "Unassigned" and it *looks* like ~19–38k display sessions, but it is **not credible**:
    it predates loaded ad spend (peaks Mar-2026), 12k of its April sessions came from just 144 TTD clicks
    (impossible 1:1), and it runs **2.5s / 5.7% engagement** (vs the site's 47s / 40%), dragging whole-site
    engagement from ~46% to ~30% when present. **Do NOT resurfacing it as a "display win"** — it's the kind of
    too-good-doesn't-add-up number that destroys trust with a sceptical client. Filtering it lifts the flight
    engagement rate back to ~40% and the channel mix to genuine channels. (Headline flight sessions: ~103k, not 124.6k.)
7. **TTD already AUD** — Windsor returns `advertiser_currency_code = 'AUD'`; the FX@1.50 case in
   `stg_ttd` is present but never exercised.
8. **TTD creative/ad-group tables are whole-flight** (no date grain); ad groups honour the Campaign
   filter via the campaign prefix in the ad-group name (RAC/RL/SAH/Disability).
9. **YoY** uses `kpi.prior_sessions` / `prior_paid_sessions`. The prior CTE in `04_kpi.sql` is
   **like-for-like**: the same calendar span one year earlier (`2025-04-01 .. max-GA4-date − 1yr`),
   NOT a full 12 months — otherwise a ~2-month flight vs a year reads as a false −77% drop. With the junk
   source excluded (caveat 6) the real flight figure is sessions **103,002 vs 84,844 prior ≈ +21%**; paid
   sessions −45% YoY is genuine — VMCH's all-channel paid traffic is down YoY, our TTD flight is additive
   awareness. `ga4_kpi_market.prior_*` is hardcoded 0 — never read YoY there.
10. **Total users is approximate** — `raw_ga4.perf_ga4` is session-source-medium grain, so summed
    `total_users` / `new_users` double-count (new can exceed total). The Website "Total users" card
    shows the summed figure with a `sessions/user` sub-label and does NOT show "new" (which would
    exceed total). No de-duplicated property-level user count is available from this source.
11. **Date range defaults to ALL available history** (Jan 2025 →) so the client sees the full trend; the
    **flight (Apr 2026 →)** is demarcated on every time-series chart by the `flightMarker` plugin (faint
    pre-flight shade + dashed "Flight →" line). Pre-flight, two things are NOT comparable and are scoped/
    annotated: (a) **no ad spend** was loaded; (b) **GA4 enquiry tagging changed in 2026** (2025 ≈110k vs
    flight 2,736 — a taxonomy artefact, not a real decline), so the **enquiry charts clamp to the flight**
    via `inFlight()` (ovHero enquiry lines null pre-flight with `spanGaps:false`+`indexedNN`; `webKeyEvents`
    filters its keys). KPI cards + channel/source breakdowns stay flight-window. An always-on date-scope
    banner explains this. **Latest period is partial** — GA4 lands ~a few days behind TTD, so the trailing
    month/week reads low (the Overview note says so).
12. **April RAC + SAH delivery is MODELLED** (added 2026-06-18). The Trade Desk's full April delivery for
    RAC and SAH never reached the Windsor feed — only stray Apr-30 slivers did (RAC 16k imps / A$38, SAH 7
    imps / A$0.10). The client supplied April's real campaign totals (RAC 1,251,220 imps · 3,809 clicks ·
    A$4,678.58; SAH 3,050,621 imps · 2,772 clicks · A$7,041.63), so we simulate the month by spreading each
    total **evenly across all 30 days (÷30)** in `sql/03b_stg_april_modelled.sql`. That view is UNION'd into
    `03c_stg_ad_delivery.sql` — which also **drops the stray Apr RAC/SAH slivers** (no double count) — so the
    modelled month flows into every campaign roll-up. `04_kpi` / `05_monthly` / `12_weekly` / `30_daily` were
    **repointed from `stg_ttd` to `stg_ad_delivery`** so the KPIs + trends pick it up too. Disability ran for
    real in April and is untouched. `stg_ttd` itself stays pure-measured, so `ttd_adgroups` / `ttd_creative`
    (whole-flight, no date grain) show **only** measured TTD — the modelled month has no ad-group/creative
    detail. A view-only/seed change like this needs `FORCE_REBUILD=1` on the export (the gate watches raw
    tables, which didn't move). Tiny ≤0.4% rounding drift on imps/clicks from the flat ÷30 split is expected.
13. **GA4 "Campaign effect" panel = additive spend-share attribution** (added 2026-06-18). GA4 has no campaign
    dimension, so we can't split sessions/enquiries by campaign directly. Instead, over the **full combined
    Oct'25→present timeline** (the same `OV.combined()` series the Overview plots — `OV` now exposes
    `combined`), we fit an **OLS regression** of total website sessions on total ad spend (zero-spend baseline
    weeks included, so the slope is lift-above-baseline). That gives the sessions the whole programme drove
    (full-timeline weekly r ≈ 0.85, highly significant). Each campaign is then credited **in proportion to its
    share of spend**, so individual campaigns **sum to the all-campaigns total** (intuitive, fewer client
    questions) — NOT independent per-campaign regressions, which over-attribute (each claims the shared trend
    and they'd sum to ~2× the total). **Modelled enquiries** = modelled sessions × the site enquiry rate
    (enquiries ÷ sessions over the flight ≈ 2.6%). The scatter + Pearson *r* + two-tailed Student-*t* p-value
    (computed in-page via `olsFit`/`betai`, no libraries) show the selected campaign's own spend-vs-sessions
    relationship. Driven by the Campaign filter (`computeAttribution`/`renderWebAttribution` in
    `dash/dashboard.html`). The same spend-share credit also **scales the Enquiries-by-type chart, the
    Sessions trend, and the by-date enquiry chart** (all additive; show full data when all OR none are
    selected). The method is spelled out in-panel — association evidence, framed transparently, not causal proof.
14. **GA4 source = native DTS with a Windsor fallback** (added 2026-06-18). VMCH's native GA4 Data Transfer
    (property `287370621`) is FAILING on a permission error — it froze at **2026-06-01** while properties on a
    still-valid credential (STT, City Perfume, Reset Data) keep updating; a shared Google account lost access to a
    cluster (VMCH, Atlantis ×2, Sophiie, ChocolateGrove, RSVP, 100.digital). So `01_stg_ga4.sql` /
    `02_stg_ga4_events.sql` now read **DTS first, and Windsor (`raw_windsor.perf_ga4` / `perf_ga4_events`,
    property 287370621) for any date the DTS lacks** — **per-date precedence, so no double counting** (verified:
    May 31 = 917 sessions from DTS only; Jun 2→ from Windsor). If the DTS is re-authorised, its dates
    automatically resume precedence. Windsor is a separate, healthy connector (its own API-key auth, unaffected by
    the DTS failure) — the two share an identical event-name vocabulary, so the enquiry bucketing is unchanged.
    **Refresh Windsor** with `ingest/windsor_data_pull/ga4/ga4_loader.py <from> <to>` **and**
    `events_loader.py <from> <to>` (fixed-range, all properties; e.g. `2026-06-01 2026-06-17`). The export
    freshness gate now also watches `raw_windsor.perf_ga4(+events)`.
    **Ongoing freshness — open:** the Windsor GA4 loaders are NOT yet a scheduled job, so GA4 will refreeze at the
    last manual pull until either (a) the DTS is re-authorised (cleanest — BigQuery → Data Transfers → refresh
    credentials, then backfill), or (b) the Windsor GA4 loaders are deployed/scheduled. NOTE: `job/main.py`'s
    gate edit is committed but **not yet deployed** — `job/deploy_job_vmch.ps1` fails on `iam.serviceaccounts.actAs`
    for the runtime SA and references `vmch-export-job@` (the live SA is `vmch-dash-job@`, per Coordinates); the
    live job still rebuilds daily off the TTD gate, which picks up the refreshed Windsor data regardless.
