# The Little Marionette — Performance Dashboard

Australian specialty-coffee roaster / e-commerce retailer, run by the agency
**100% Digital** (agency slug `100-digital`). This is an e-commerce / ROAS build:
Google Ads `conversions_value` is revenue (AUD), the source of ROAS / AOV / CPA.

## EDA Summary (14 Jun 2026)

| Source | Table | Account/Advertiser | Rows | Window | Spend | Conv | Revenue |
|--------|-------|--------------------|------|--------|-------|------|---------|
| Google Ads (DTS) | `raw_google_ads.perf_google_ads` | The Little Marionette | 1,169 | 2025-08-05 → 2026-06-13 | $23,353 AUD | 1,161 purchases | $120,993 AUD |
| Trade Desk (Windsor) | `raw_windsor.perf_the_trade_desk` | The Little Marionette | 1,147 | 2026-04-30 → 2026-06-12 | $1,687 AUD | — | — |

**Decision gates (all resolved):**

| Gate | Finding | Decision |
|------|---------|----------|
| `conversions_value > 0`? | $120,993 AUD | **E-commerce/ROAS shape** (ROAS ~5.18) |
| `campaign_type` column exists? | YES — PERFORMANCE_MAX, SEARCH, SHOPPING | **google_by_type breakdown built** |
| TTD currency = USD? | **AUD** (Windsor already AUD) | CASE passes through; fx_usd_aud=1.50 documented |
| TTD video populated? | video_starts=0, video_completes=0 | **No video funnel** |
| TTD conversions JSON? | All 1,147 rows non-NULL | "Pixel fires (anonymous slots — no revenue attribution)" callout |
| Window start? | 2025-08-01 (first-of-month of Google min) | |
| Spend units? | CPM=$23.97 | **Already whole AUD** — NOT micros |
| TTD stale? | Max 2026-06-12 vs Google 2026-06-13 (1 day) | **Not stale** |

## Deltas from ResetData

| Dimension | ResetData | TLM |
|-----------|-----------|-----|
| Business shape | B2B / leads-as-conversions | E-commerce / ROAS |
| Sources | 5 (GA, Meta, TTD, GA4, GA4 events) | 2 (Google Ads DTS + Trade Desk Windsor) |
| Revenue | Omitted (0 upstream) | Google conversions_value = revenue |
| Tabs | Overview / Paid Media / Website Traffic / Ads→Traffic | Overview / Google Ads / Trade Desk / Performance |
| Website/sessions layer | Yes (GA4) | No (no GA4 source) |
| Country filter | Yes | No (single market) |
| Google Ads source | Windsor (USD, divide 1e6) | Native DTS (already AUD, no division) |
| TTD currency | Windsor USD → AUD ×1.50 | Windsor AUD (pass-through) |
| Google by type | Heuristic only | Native campaign_type column |
| Video funnel | TTD populated | TTD video empty (skip) |
| Spend unit | Windsor micros → /1e6 | DTS already whole AUD |

## Coordinates

| Thing | Value |
|-------|-------|
| Folder / dataset | `clients/client_tlm/` / `client_tlm` |
| Data bucket | `bidbrain-analytics-tlm-dash` |
| Export job | `tlm-export` (SA: `tlm-dash-job@bidbrain-analytics.iam.gserviceaccount.com`) |
| Web service | `tlm-dash` (SA: `tlm-dash-web@bidbrain-analytics.iam.gserviceaccount.com`) |
| Secrets | `tlm-dash-password`, `tlm-dash-session-key` |
| Scheduler | `tlm-export-daily` (`*/10 * * * *` UTC, self-gating) |
| JSON object | `tlm.json` |

## Deploy / refresh

**First stand-up** (provisions everything — run once):

```powershell
.\clients\client_tlm\deploy_tlm.ps1
```

**Day-to-day:**

```powershell
# Re-apply views (any SQL change)
.\clients\client_tlm\sql\deploy_views_tlm.ps1

# Rebuild + redeploy export job
.\clients\client_tlm\job\deploy_job_tlm.ps1

# Rebuild + redeploy web app
.\clients\client_tlm\dash\deploy_dash_tlm.ps1

# Run export manually
gcloud run jobs execute tlm-export --region australia-southeast1 --wait
```

## Caveats

1. **TTD Windsor is already AUD** — EDA shows `currency = 'AUD'` for all TLM rows. The FX case at 1.50 in `stg_ttd` is present but not exercised. If a USD row ever lands from Windsor, it'll convert correctly.
2. **Google spend is whole AUD** — The native DTS loader has already converted micros to currency units. Do NOT divide by 1,000,000 (CPM sanity check: ~$23.97). This differs from Windsor-based Google Ads clients.
3. **TTD video fields are 0** — No video creative in this flight, so the dashboard skips the video funnel chart.
4. **No GA4, no Meta, no Reddit** — TLM is a two-source build. The "Website Traffic" and "Ads → Traffic" tabs do not exist.
5. **Branding (done)** — Real The Little Marionette logo is inlined: the **dashboard is light cream
   + slate-blue** (`#4F7290`, sampled from thelittlemarionette.com) with a navy-recoloured wordmark;
   the **login keeps a dark slate ground** so the supplied white logo reads. Logos are injected from
   `creatives/TLM__logo_white.avif` by `creatives/inject_logos.py` (idempotent — re-run to refresh).
6. **ROAS / CPA are Google-only (attributed)** — ROAS = revenue ÷ **Google** spend (≈5.18×), CPA =
   Google spend ÷ purchases. TTD pixel fires carry no attributable revenue, so they're excluded from
   the efficiency ratios (blended-on-total would read ≈4.83×). The **Media spend** KPI still shows
   total spend (Google + TTD), with TTD called out in its sub-label.
7. **Weekly revenue now flows** — `ad_campaign_weekly` carries `conversions` + `revenue` (Google-only;
   TTD NULL). Without it the Performance scatter, the week-grain hero revenue/ROAS line, and the
   week-grain trend silently read zero. Three-stage contract: view 13 → `job/main.py` → `dashboard.html`.
8. **`ttd_creative` is whole-flight** — the creative × ad-format table has no date grain, so it is NOT
   date-scoped (labelled as such); it does honour the Platform/Campaign selection. Everything else on
   every tab honours Date + Platform + Campaign.
9. **"Top creatives — what worked" carries NO real artwork (by design).** The Trade Desk tab shows a
   **CTR leaderboard** — top 10 banners by click-through, name + size + Impr./Clicks/CTR/Spend, #1 pilled
   (`renderTTD`, `.clist`/`.crow` in `dash/dashboard.html`) — NOT a thumbnail gallery. Reason (researched
   2026-07-03, all three ingest paths): TTD lands only `creative_name` + `ad_format` into
   `raw_windsor.perf_the_trade_desk` (26 cols, no image column); Windsor's 3 `the_trade_desk` image
   fields are all "(Deprecated)" and **live-return NULL**; the TTD Platform API that could serve previews
   is closed/credentialed (we're read-only). Google Ads via DTS exports no images either (empty columns,
   no Asset tables). Snowflake is irrelevant (TLM never reads it). A ResetData-style thumbnail gallery
   works ONLY because Meta uniquely serves `creative_thumbnail_url`.
   - **Real TTD artwork → manual seed of the top ~10 banners:** agency exports ~10 images from the TTD
     UI (advertiser `mor6pp1`), seed keyed by `creative_name`, thread through `sql/10` → `job/main.py`
     (`ttd_creative[]`) → `dashboard.html` (mirror ResetData's `33_meta_creatives.sql` render). No API access.
   - **Google PMax/Shopping product images are obtainable** (Search is text-only): via a Windsor pull of
     `google_ads` "Asset image asset full size url" + `google_merchant` "Product Image Link", or the Google
     Ads API `asset` resource — needs Windsor connector scope / Merchant Center auth / a dev token. TLM's
     Google customer id = `1869745895` (shared MCC `3451896252`).