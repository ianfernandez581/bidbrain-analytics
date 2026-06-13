# City Perfume Dashboard — BUILD CHECKLIST

Live status board for the City Perfume build. Status tags:
`☐ TODO` · `◐ IN PROGRESS` · `⚠ BLOCKED (needs Ian)` · `☑ DONE`

Client key `cityperfume` · dataset `client_cityperfume` · bucket `bidbrain-analytics-cityperfume-dash`
· object `cityperfume.json` · job `cityperfume-export` · service `cityperfume-dash` · region `australia-southeast1`.

> **Post-launch note (as of 2026-06-13):** this board records the original 2026-06-06 build (then **25 views**).
> The dashboard has since been extended: a **6th tab (Year on Year)**, the **`40_yoy_monthly`** view, a family
> of **day-grained views `50–59`** powering a global **Date range** picker, and a global **Sales-channel** chip
> filter. The live dataset now holds **36 views**. The ROAS framing also moved from blended-MER (total) to the
> **online-only incremental Margin ROAS** of the analysis handoff (see B3 + `analysis/city_perfume_roas_handoff.md`).
> The scheduler is now **self-gating on `*/10 * * * *` UTC** (rebuilds only when an upstream raw table advances),
> not the fixed **22:00 UTC** daily cron recorded in the build log below. The export job vendors `freshness.py`.

---

## Blockers / needs Ian

| # | Status | Question |
|---|--------|----------|
| B1 | ☑ RESOLVED | **Logos** embedded 2026-06-06 — 100% Digital (webp) + City Perfume (png) base64-inlined in the topbar (`dashboard.html`) and login page (`main.py`). Source files in `Creatives/`. |
| B2 | ⚠ NEEDS CONFIRM | **Attribution stance** — data strongly backs it: v_sales is the single truth; platform-claimed revenue (Google/Meta/GA4) shown separately, never summed. Confirm OK. |
| B3 | ☑ RESOLVED | **ROAS basis** — brief said "ad spend ÷ total v_sales revenue" (= **31.0x**), but EDA showed in-store **Neto POS = 63%** of sales (ads can't drive walk-ins). Resolved (2026-06-12, per `analysis/city_perfume_roas_handoff.md`): dashboard is now **online-only** (Website + Marketplaces, in-store POS excluded) and reports **one canonical incremental Margin ROAS ≈ 2.6× (net ≈ 1.6×)** = 7× incremental online revenue × 37.7% online margin — NOT a total-revenue ÷ spend ratio. Old ratio headlines (31× blended / 11.6× online) retired; platform-claimed shown separately, never summed. 7× is a planning estimate pending the T7 spend-down/geo holdout (`analysis/validation_plan.md`). |

**Findings flagged to client (not blockers — building defensively):**
- **GA4 tracking is BROKEN from Oct 2025** — row counts collapse from ~2,500/mo to <120/mo; purchase_revenue/transactions go null. GA4 is only reliable Jun–Sep 2025. Website/GA4 tab will carry a visible "tracking degraded from Oct 2025" note and lean on the healthy window. Worth a separate heads-up to City Perfume's analytics owner.
- **Margin data quality** — 21,889 lines have `cost_price=0` (→ margin=line_total, inflates margin ~$3.24M lifetime) and 19,535 lines have negative margin (−$8.02M, promos/clearance). Margin shown net-as-reported with a caveat; flag for validation.

---

## EDA findings & decisions

Window chosen for all roll-ups: **2025-06-01 → latest** (first full month Meta exists; current month June-2026 is partial → labelled/excluded in trends). Everything is **AUD across every source → no FX needed** (unlike STT).

| # | Question | What the data showed | Decision |
|---|----------|----------------------|----------|
| 1 | Currency / FX | Google `currency_code`, Meta `currency`, TTD `currency` all = **AUD** (100%); GA4 & v_sales have no currency col but client is AU. | **AUD only, no FX.** No `fx_*` constant at stg layer. Document the AUD assumption for GA4/sales. |
| 2 | Reporting window | v_sales 2021-07→2026-06-06 (full); Google 2018→now; **Meta 2025-05→2026-05**; TTD only **2026-05-17→05-31** (2-wk pilot); GA4 2022→now but broken Oct-2025. | **Rolling window from 2025-06-01.** Trends end at last complete month (May-2026); June-2026 partial labelled. |
| 3 | Attribution model | 12-mo truth $15.79M / 63,983 orders. Platform-claimed: Google $3.49M (22% of truth), Meta $0.60M (3.8%), GA4 $0.30M (1.9%). They disagree ~6x and sum to only 27.8% of truth. | **Blended.** v_sales = truth for revenue/orders/margin/AOV. Platform-claimed shown side-by-side, **never summed**. (B2 confirm.) |
| 4 | TTD conversions JSON | Double-encoded JSON *string* — needs `PARSE_JSON(JSON_VALUE(conversions))`. 397 `conversion_touch_03` over 60/105 rows; **no revenue/value** in JSON. Pure display awareness pilot. | **Keep TTD upper-funnel** (imps/clicks/spend). Parse `conversion_touch_03` as a labelled secondary "DSP view-through" conversion; no ROAS from TTD. |
| 5 | Meta effective_status | 5 values; **paused/archived hold ~50% of lifetime spend & 685/2013 purchases**. Status = current config, not a per-date spend flag. | **Include ALL statuses** in historical totals. Never filter by effective_status. |
| 6 | Sales Channel filter | 20 lifetime values; in **window only 10 deliver**: Neto POS $9.90M (63%), Website $4.76M (30%), then BigW/Lasoo/OzSale/eBay/Amazon AU/MyDeal/EverydayMarket (~7%), Control Panel $747 (junk). | **Include filter**, grouped **In-store POS / Website / Marketplaces / Other**. Whitelist delivering channels; tail → Other. Scopes v_sales metrics only (ad spend unaffected). |
| 7 | Product category | `product_name` follows "Brand … CONCENTRATION SIZEml"; 75% have a size token, ~0 nulls. EDP $37.1M / EDT $6.3M / Parfum-Elixir $9.1M / Gift Set & Hamper $9.9M. Brand extraction noisy. | **Derive CONCENTRATION category** via regex (EDP/EDT/Parfum/Gift Set & Hamper/Other). Top products by `product_name`. Brand grouping skipped for v1. |
| 8 | Logos / palette | brief paths are placeholders | Placeholder palette + TODO (see B1). |

**Key source facts (memorize for SQL):**
- **Google** `raw_google_ads.perf_google_ads` (`account_name='City Perfume'`): cols `impressions, clicks, spend, conversions, conversions_value, campaign_type`. `spend` is **NUMERIC AUD, NOT micros** (no /1e6). Campaign-day grain, 292 campaigns. campaign_type: PERFORMANCE_MAX (61% spend), SHOPPING, SEARCH, DISPLAY, VIDEO, SMART, DEMAND_GEN.
- **Meta** `raw_windsor.perf_meta` (`account_name='Cityperfume.com.au'`): **ad-grain, key `ad_id`**. cost=spend (AUD). Funnel: `add_to_cart, initiate_checkout, purchases, purchase_value`. Video: `thruplays, video_3s_views, video_starts`. Creative: `creative_id, creative_thumbnail_url(100%), creative_title(99%), creative_body(100%)`; `creative_link_url` always NULL, `destination_url` 32%. No creative_type col → derive `video` vs `image` from video metrics. objective ≈ all OUTCOME_SALES.
- **TTD** `raw_windsor.perf_the_trade_desk` (`advertiser_name='City Perfume'`): 105 rows, 1 campaign, display-only. `impressions, clicks, cost` (AUD); video all zero. conversions JSON (see #4).
- **GA4 A** `raw_ga4.perf_ga4` (`account_name='City Perfume'`): session/source-medium/channel grain. `session_default_channel_group` (16 vals) drives bucketing — **Cross-network = Performance Max = PAID** (largest group, don't bucket as Other). cols `sessions, engaged_sessions, transactions, purchase_revenue, ecommerce_purchases`.
- **GA4 B** `raw_ga4.perf_ga4_events` (`client_slug='city-perfume'`): event×date, **no source dim**. Funnel events: view_item 168k, add_to_cart 20k, begin_checkout 5.5k, purchase 7.4k. `is_conversion_event` unreliable → use event_name='purchase'. Funnel = sessions (A) + mid-funnel events (B), **site-wide only**.
- **v_sales** `client_cityperfume.v_sales`: order-line grain, 358,695 lines. `order_id, date_placed(TS), sales_channel, email(PII), customer_id(PII 100% pop), sku, product_name, quantity, unit_price, line_total, cost_price, margin`. customer_id = identity key (email 65% pop). **email/customer_id NEVER exported.**

Smoke-test counts: v_sales **358,695** · google **22,117** · ga4 **59,463** · ga4_events **13,620** · meta **2,801** · ttd **105**.

---

## Proposed view set (`sql/`) — ~26 views, NN_ ordered (awaiting B2/B3 sign-off)

**Staging (filter once each, AUD, no FX):**
`01_stg_google` · `02_stg_meta` (ad-grain, all statuses, derived creative_type) · `03_stg_ttd` (parsed touch_03) · `04_stg_ad_delivery` (unified long: platform·campaign·date·spend_aud·imps·clicks·platform_conversions·platform_revenue·creative_type) · `05_stg_ga4` (channel_group + channel_bucket, Cross-network→Paid) · `06_stg_sales` (line-grain cleaned: channel_group, concentration category, is_new_customer; customer_id stays BQ-internal only)

**Headline/trend:** `10_kpi` (window consts, spend, revenue total+online, orders, margin, AOV, blended ROAS all+online, platform-claimed separate) · `11_monthly` · `12_weekly`
**GA4 (Website tab):** `13_ga4_channels` · `14_ga4_monthly_channel` · `15_ga4_sources` · `16_ga4_funnel`
**Sales (unique tab):** `20_sales_kpi` · `21_sales_monthly` · `22_sales_products` (by revenue & margin + category mix) · `23_sales_by_channel` · `24_sales_new_returning`
**Campaign-grained:** `30_ad_campaigns` (option list) · `31_ad_campaign_monthly` · `32_ad_campaign_weekly` · `33_meta_creative` · `34_platform_summary` (platform-claimed ROAS shown separately) · `35_google_campaign_type`

Invariant (mirror STT): all-campaigns selection reproduces whole-window kpi/monthly/weekly **ad** totals. Sales side has no campaign dim → stays whole under Campaign filter.

---

## Phases

### Phase 0 — Standup
- [☑] Verify env (bq/venv/repo layout) · [☑] Smoke-test all source filters · [☑] Create `clients/client_cityperfume/` + seed checklist · [☑] Mirror to in-IDE todos

### Phase 1 — EDA
- [☑] Profile all 6 sources + reconcile (workflow `wv4qc4uvw`, 6 agents)
- [☑] Record all 8 decisions
- [☑] **CHECKPOINT passed** — Ian: blended MER (total) headline + online secondary (re: omnichannel halo onto in-store), logos later, build all views. New/returning to be prominent in dash.

### Phase 2 — BigQuery views (`sql/`)  ☑ DONE — 25 views applied + verified
- [☑] `create_views.py` (applies sql/*.sql in order) · [☑] Staging 01–06 · [☑] Headline 10–12 · [☑] GA4 13–16 · [☑] Sales 20–25 (added 25_sales_category) · [☑] Campaign 30–35
- [☑] **All-campaigns invariant verified**: kpi=monthly=weekly=ad_campaigns=campaign_monthly=campaign_weekly=platform_summary ad spend all **$517,729**.
- [☑] **Sales truth reconciles**: kpi=sales_kpi=sales_monthly=by_channel=by_category=new_returning all **$16,053,034**; orders new+returning=total=64,834; GA4 sessions 453,782 consistent across ga4_channels/funnel.
- [☑] Headline numbers: **blended ROAS 31.0× · online ROAS 11.6× · revenue $16.05M · margin %, AOV, new/returning all wired.** (One bug fixed: 33_meta_creative HAVING re-aggregated an alias.)

### Phase 3 — Export job (`job/`)  ☑ DONE
- [☑] `CLIENT="cityperfume"` · [☑] Generic `clean()` mapper (Decimal→float, DATE→YYYY-MM-DD) → JSON keys mirror view columns · [☑] **PII guard: reads roll-ups only + `assert_no_pii` refuses to write if customer_id/email leak** · [☑] Local dry-run: 576KB, rev $16.05M, ROAS 31.0×, 24 sections, 0 PII keys (grep-verified) · [☑] Dockerfile/requirements/cloudbuild/deploy_job all written

### Phase 4 — Dashboard (`dash/`)  ☑ DONE
- [☑] `main.py` auth gate + /data.json proxy **byte-for-byte from STT** (SameSite=None+Secure) · [☑] Login rebranded (placeholder serif wordmark + champagne/gold, TODO real logo) · [☑] Dockerfile/requirements/cloudbuild/deploy_dash written
- [☑] `dashboard.html` — 5 tabs (Overview · Paid Media · Website & GA4 · Sales & Products · Ads → Revenue), Platform + searchable Campaign filters (client-side ad rescale), **Revenue-basis toggle (All ⇄ Online)** for the ROAS framing, **new-vs-returning section prominent**, AI commentary, Fraunces+Inter / charcoal+champagne+blush branding
- [☑] **Verified: headless-rendered all 5 tabs in Chrome against the real JSON — content shown, no JS errors, every tab populated.** Data contract cross-checked (all 24 sections' keys match the JS).
- Note: Sales-channel surfaced as Sales-tab content + the All/Online toggle (not a global filter — channel decomposition isn't carried on every trend, so a global filter would only partially rescale). Done-when only requires Platform/Campaign filters. ✓

### Phase 5 — Deploy scripts  ☑ WRITTEN (execution gated on Ian go + logos)
- [☑] `deploy_cityperfume.ps1` (one-shot idempotent; dataset pre-exists → Exists check leaves v_sales alone) · [☑] `scheduler.ps1` (22:00 UTC) · [☑] per-stage `sql/deploy_views_` + `job/deploy_job_` + `dash/deploy_dash_` · [☑] both `cloudbuild.yaml` · [☑] least-privilege SAs/IAM mirrored from STT
- [☐] **Run `deploy_cityperfume.ps1`** (prompts for dashboard password; provisions SAs/IAM/secrets/bucket/job/scheduler/service) — awaiting Ian go-ahead

### Done-when
- [☑] views apply clean (25) · [☑] job writes `cityperfume.json` (no PII) + dry-run verified · [☑] dash renders 5 tabs real data (headless-verified) behind gate · [☑] `deploy_cityperfume.ps1` re-runnable (written) · [☑] `clients/client_cityperfume/README.md` + `dash/LIVE_URL.md` + `.gitignore`
- [☑] **LIVE DEPLOYED 2026-06-06** → https://cityperfume-dash-p32gk2wuia-ts.a.run.app — provisioned SAs/IAM/secrets/bucket, applied 25 views, ran the export job (PII-free JSON in bucket), wired the 22:00 UTC scheduler, deployed the gated service. Verified live: login 200 · /data.json 401→200 · auth 302 · 0 PII keys. URL recorded in `dash/LIVE_URL.md`.
- [☑] **Logos embedded** — 100% Digital + City Perfume base64-inlined (topbar + login).
- Two deploy-script fixes made during standup (both committed to `deploy_cityperfume.ps1`, now fully non-interactive + re-runnable): (1) view-apply switched to `create_views.py` — WinPS→`bq` stdin mangled the UTF-8 em-dashes in SQL comments; (2) added `--no-allow-unauthenticated --quiet` to the dash deploy to avoid the interactive prompt. Harmless note: `/healthz` is shadowed by Google's edge; Cloud Run health-checks the port.
