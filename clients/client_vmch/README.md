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

`dash/dashboard.html` — one self-contained file. Filters: **Date range** + **Campaign** (4 service
lines). No Country/Platform chips (single market, single platform).

- **Overview** — media spend + website sessions + enquiry events (3-axis hero), channel donut,
  paid-vs-rest stack, TTD delivery, AI commentary on enquiries.
- **Trade Desk** — delivery KPIs (spend/imps/clicks/CTR/CPM/CPC), monthly spend+clicks, spend-by-
  campaign donut, campaign breakdown table, top ad groups, creative-format mix.
- **Website** — GA4 KPIs, sessions-by-channel, monthly trend (total/paid/display), enquiry events
  by type, top sources/mediums.
- **Media → Traffic** — honest upper-funnel read: weekly impressions vs sessions, correlation
  scatter, weekly clicks, stat strip (clicks, click-rate, last-click Display sessions).

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
4. **Display is upper-funnel** — TTD drove 4.4M impressions but GA4 attributes only ~25 last-click
   "Display" sessions. The **Media → Traffic** tab says so explicitly — judge the flight on reach,
   clicks (3,248) and assisted enquiries, not a 1:1 session lift. Do not overclaim.
5. **TTD already AUD** — Windsor returns `advertiser_currency_code = 'AUD'`; the FX@1.50 case in
   `stg_ttd` is present but never exercised.
6. **TTD creative/ad-group tables are whole-flight** (no date grain); ad groups honour the Campaign
   filter via the campaign prefix in the ad-group name (RAC/RL/SAH/Disability).
7. **YoY** uses `kpi.prior_sessions` / `prior_paid_sessions`. The prior CTE in `04_kpi.sql` is
   **like-for-like**: the same calendar span one year earlier (`2025-04-01 .. max-GA4-date − 1yr`),
   NOT a full 12 months — otherwise a ~2-month flight vs a year reads as a false −77% drop (real is
   sessions **+47%**; paid sessions −45% YoY is genuine — VMCH's all-channel paid traffic is down YoY,
   our TTD flight is additive awareness). `ga4_kpi_market.prior_*` is hardcoded 0 — never read YoY there.
8. **Total users is approximate** — `raw_ga4.perf_ga4` is session-source-medium grain, so summed
   `total_users` / `new_users` double-count (new can exceed total). The Website "Total users" card
   shows the summed figure with a `sessions/user` sub-label and does NOT show "new" (which would
   exceed total). No de-duplicated property-level user count is available from this source.
9. **Latest period is partial** — GA4 currently lands ~a few days behind The Trade Desk (GA4 ends
   ~2026-06-01, TTD ~2026-06-12), so the trailing month/week reads low; the Overview note says so.
   The dashboard defaults its date range to the **flight** (Apr 2026 →) — pre-flight 2025 months use
   a different GA4 event taxonomy and are intentionally outside the default range.
