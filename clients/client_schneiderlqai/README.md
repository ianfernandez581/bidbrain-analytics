# client_schneiderlqai — Schneider Electric "Liquid AI Data Center" (LQAIDC)

A **single-campaign, paid-media-only** dashboard for Schneider Electric's **Liquid AI Data Center**
(LQAIDC) push — a TOFU / **Awareness** campaign for *Liquid Cooling for AI Data Centers*, run by
**Transmission**. It is a lean sibling of `client_schneider` (same aesthetic + engines), NOT part of
the multi-program Schneider Pacific dashboard.

- **Channels:** LinkedIn (single-image Sponsored Content) + The Trade Desk (programmatic display)
  + **Google Search (SEM, added 2026-08-31)** — 5 markets (AU/UAE/SA/BR/CL), live since 2026-08-17,
  scoped by an EXACT five-name `IN` list in `sql/05_stg_google_search.sql` (the `&` in
  `2306_SE_AI&LiquidCooling_*` breaks unescaped LIKE/regex — treat the name as an opaque string; a
  rename freezes the channel loudly, and the job WARNs when the scope returns 0 rows). Search is its
  own `search` payload block, NEVER unioned into `delivery` (different currency basis, below). Its
  `engagement_actions` = raw Google CONVERSIONS renamed — the account counts Se.com page views / CTA
  clicks / file downloads as conversion actions (~1,517 vs 660 clicks), so "conversions" would read
  as leads and be wrong by two orders of magnitude; no lead-only split exists in this source.
  **On screen (2026-08-31): its OWN "Google Search (SEM)" section on the Overview tab** - 5 KPI
  tiles (spend EUR with the USD source figure, imps, clicks, CTR, CPC), a full-label engagement
  line, a market table (5 markets), a daily spend+clicks trend, and an FX + per-channel freshness
  footnote ("Converted from USD at {fx_usd_eur}, {fx_rate_date}"). **Has its OWN Channel chip**
  (Google yellow `#F5C542` with DARK ink - white is unreadable on that yellow; `section:true` in
  `PLATFORMS`, so the blended delivery consumers iterate `DELIVERY_PLATFORMS` and can never see
  it): the chip SHOWS/HIDES this section and nothing else - Search never enters the blended
  figures, so unticking it cannot move a number, and it can NEVER hide the unavailable state
  (fail-loud beats filter state; the chip leaves the roster when the scope empties). Honours the
  Country chips + date picker, and
  **ROLLING date presets re-anchor to Search's own `data_through`** (`gsRange()` - Search loads ~a
  day behind, so a shared "Last 7 days" would truncate its newest day and zero-pad the missing
  one); calendar presets / custom ranges pass through. **Visibility contract:** `search.data_through`
  null -> section hidden (never delivered); set but `daily` empty -> a loud UNAVAILABLE state
  (the job carries the last published `data_through` forward when the sql/05 scope empties, so a
  campaign rename shows on screen instead of silently removing the section). The media-plan tab's
  Search line stays `live=0` / unwired to pacing until the plan line is confirmed to be this buy.
  The overview CSV export and the AI-deck payload stay delivery-only (raise before adding Search
  to either - mixed currency columns).
- **Countries (6):** India (dominant), Brazil, Australia, Chile, Saudi Arabia (KSA), UAE.
  Media-plan regions: South America (BR+CL), MEA (SA+AE), Pacific (AU), India.
- **Awareness only** — objective is Website visits / display reach. **No leads, no conversions, no
  Salesforce/CS, no GA4.** The story is reach (impressions), clicks, CTR, cost efficiency (CPM/CPC),
  and pacing vs the media-plan targets.
- **Currency:** **displayed in EUR; stored in AUD.** Both channels are native AUD and the warehouse
  keeps AUD (targets treated as AUD — see INTAKE.md). The dashboard converts AUD→EUR **in the browser
  only** (`bbApplyFx()` in `dash/dashboard.html`, rate constant `AUD_TO_EUR`). The rate is **not displayed
  anywhere in the UI** (client request 2026-08-11), so that constant and this line are the only
  record of it - keep them in step, because a wrong rate would be silently unfalsifiable on screen.
  This is the only EUR dashboard in the estate. The conversion must stay front-end: `spend_aud` is
  built from shared `raw_snowflake` views that `client_schneider` and `client_schneidersecpwr` also
  read, so converting in SQL or the export job would re-denominate their numbers too.
  **EXCEPTION — Google Search (2026-08-31): a SINGLE USD->EUR hop IN THE VIEW** (`sql/05`), because
  that buy bills USD and routing USD->AUD->EUR would invent an AUD figure that never existed and
  compound two rates on a number that must reconcile against a US invoice. Safe in SQL here because
  `stg_google_search` is THIS client's own view, not a shared one. The rate is pinned as columns
  (`fx_usd_eur` 0.86259 / `fx_rate_date` 2026-08-17 — the ECB flight-start reference rate; no booked
  rate was supplied), `cost_usd` stays beside `cost_eur` so the source figure is recoverable, and
  the dashboard must EXEMPT the `search` block from `bbApplyFx()` and footnote the section
  "Converted from USD at {fx_usd_eur}, {fx_rate_date}". Search cost is NEVER summed with
  LinkedIn/Trade Desk spend on any surface.
- **Flight:** 15 May → 31 Dec 2026. Data started 16 May (LinkedIn) / 18 May (Trade Desk).

## Live
- **Service:** `schneiderlqai-dash` · https://schneiderlqai-dash-516554645957.australia-southeast1.run.app
- **Front-door:** https://dashboards.bidbrain.ai/d/schneiderlqai/ (Transmission agency) — see `dash/LIVE_URL.md`.
- Password-gated (Secret Manager `schneiderlqai-dash-password`); the platform logs in server-side so
  there is no second password via the front-door.

## Tabs
> **Channel chips (2026-08-15):** a coloured LinkedIn / Trade Desk chip pair in the control bar,
> honoured by `pmRows()` + `crRows()` via `platOk()`. **Only engines with delivery in the current
> country/date selection are rendered** (client rule - never advertise a channel this campaign does
> not have), the last engine cannot be unticked, and the group hides itself on the Media Plan tab
> (plan targets, not measured delivery) and whenever one engine is left. **+ a Google Search chip
> (2026-08-31)** on the same roster rules, with different reach: it shows/hides the Google Search
> (SEM) section ONLY (Search never enters the blended delivery model - see the Channels bullet).

1. **Overview** — delivery KPIs (spend / impressions / clicks / CTR + CPM/CPC), a **pace-to-plan** card
   (delivered vs media-plan targets over the flight), a delivery-over-time hero chart (grain + Relative/
   Absolute toggles), a LinkedIn-vs-Trade-Desk channel table, spend-by-channel + spend-by-country charts,
   a country summary table, and the **Google Search (SEM) section** (own lane + currency basis - see
   the Channels bullet above).
2. **Creative** — LinkedIn message concepts (3), Trade Desk display concepts (Accelerate AI / Cooling
   Performance / Cool & Smart / Every Degree / Generic) + banner-format mix, best creatives by CTR, and
   a sortable/searchable creative detail table.
3. **Media Plan** — budget tiles, delivered-vs-target pacing per live channel, and the full 7-line brief
   media plan (LinkedIn / Trade Desk / Search / Reddit × Awareness + Retargeting) with Live/Planned tags.
   Search, Reddit and the Retargeting lines are **planned (tbc), not yet live** — targets shown for context.

## Architecture (standard 3-stage pattern)
```
raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all}          (shared mirrors, filled by ingest/)
  -> sql/01_stg_linkedin, 02_stg_tradedesk                     (scope: Schneider account + '%LQAIDC%')
  -> sql/03_delivery (platform x date x country x region fact) + sql/04_creative
raw_snowflake.google_ads_apac                                  (shared mirror, campaign grain)
  -> sql/05_stg_google_search (day x market; exact 5-name IN scope; USD + pinned USD->EUR)
  -> sql/06_search_channel_totals (one row: sums + CTR/CPC + fx + data_through)
  + data/media_plan.csv -> seed_media_plan  (load_seeds.py)    (the brief targets)
  -> job/main.py  -> gs://bidbrain-analytics-schneiderlqai-dash/schneiderlqai.json
     (delivery/creative/plan + the `search` block: daily rows, totals, own data_through)
  -> dash/main.py (Flask gate) serves dashboard.html + /data.json
```
- **Scope filter** keys on `CAMPAIGN_NAME LIKE '%LQAIDC%'` (LinkedIn ad-set name / Trade Desk campaign
  name) so it rolls up **both** raw name forms — the campaign name gained a `2306_` prefix mid-flight
  (~6-7 Jul 2026); same ad-set/ad-group IDs. (The Enterprise IT `1958_SE_EntIT_*` campaigns in the same
  Trade Desk export are a DIFFERENT brief and are deliberately out of scope.)
- **Country** is parsed from the LinkedIn ad-set `CAMPAIGN_NAME` / Trade Desk `AD_GROUP_NAME`.
- **Targets** (`plan.channels`) are summed over the media-plan lines flagged `live=1` (LinkedIn Awareness
  + both Trade Desk Awareness lines): LinkedIn 925,600 imp / 5,091 clk / A$69,420; Trade Desk 9,196,000
  imp / 34,176 clk / A$138,840. Live budget A$208,260; full plan A$473,124.
- **Spend multiplier:** the dashboard's `bbApplySpendMult` grosses delivered `spend_aud` by
  `window.BB_SPEND_MULT` per channel (linkedin / ttd). Plan **targets are NOT grossed** — they are the
  media-plan (billed) budget, so grossed-delivery-vs-billed-budget paces correctly on the front-door.

## Freshness
Self-gating `*/10` UTC (`schneiderlqai-export-daily`). Gate watches
`raw_snowflake.{linkedin_ads_apac, tradedesk_apac_all, google_ads_apac}` `__TABLES__.last_modified`;
watermark = `gs://...-schneiderlqai-dash/_freshness.json`. **Static re-seeds (media plan) need
`FORCE_REBUILD=1`.** Google Search loads ~a day behind Trade Desk, so the `search` block carries its
OWN `data_through` — any rolling window must be computed per channel from it, never shared.

## Deploy / edit (root CLAUDE.md is the canonical command source)
- Edited `dash/dashboard.html` or `dash/main.py` -> `dash/deploy_dash_schneiderlqai.ps1`
- Edited `job/main.py` -> `job/deploy_job_schneiderlqai.ps1`
- Edited a `sql/*.sql` view -> `sql/deploy_views_schneiderlqai.ps1`
- Edited `data/media_plan.csv` (targets) -> `deploy_seeds_schneiderlqai.ps1` (forces the rebuild)
- First-time standup (idempotent): `deploy_schneiderlqai.ps1`
- Optional "Download slides" (AI deck): `dash/enable_report_schneiderlqai.ps1` once, then redeploy the dash.

## GCP facts
- Project `bidbrain-analytics`, region `australia-southeast1`.
- Dataset `client_schneiderlqai` · bucket `bidbrain-analytics-schneiderlqai-dash` ·
  job `schneiderlqai-export` · service `schneiderlqai-dash`.
- SAs `schneiderlqai-dash-job@` (BQ read + bucket write) · `schneiderlqai-dash-web@` (bucket read +
  secretAccessor). Secrets `schneiderlqai-dash-password`, `schneiderlqai-dash-session-key`.
