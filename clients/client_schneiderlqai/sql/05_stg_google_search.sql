-- Schneider Electric "Liquid AI Data Center" (LQAIDC) — staged Google Search (SEM), added 2026-08-31.
--
-- Third channel on this dashboard (after LinkedIn + The Trade Desk). Source is the shared
-- raw_snowflake.google_ads_apac mirror (Snowflake `APAC_ALL_PLATFORM.PUBLIC."Google Ads - APAC"`),
-- CAMPAIGN-level grain since Transmission's 2026-08-20 export change (see the cloudflare
-- 04b_stg_google_ads header for that history).
--
-- SCOPE: an explicit IN (...) list of the five SEM campaign names, per the build brief — NOT a LIKE
-- pattern (the `&` in the names breaks unescaped LIKE/regex; treat the name as an opaque string
-- everywhere, and never interpolate it into a URL unencoded). All five sit under
-- ACCOUNT_NAME = 'AAG region Account' and report NETWORK = 'SEARCH' only (verified 2026-08-31; the
-- account holds no other LIQUID/LQAIDC/2306 campaign). Trade-off, per the repo's "campaign names
-- are NOT stable keys" rule: if Transmission renames these, rows drop OUT of this list and the
-- channel freezes visibly — loud under-inclusion, chosen over a fuzzy match that could silently
-- pull in unrelated 2306_* campaigns.
--
-- NETWORK and CURRENCY both sit in the GROUP BY — the same split-loudly pattern, NOT filters: a
-- SEARCH_PARTNERS (or worse, a Display) row would surface as its own labelled row instead of being
-- silently folded into — or silently dropped from — Search spend; a source-side currency change
-- splits rows instead of mislabelling cost_usd. Today both are single-valued (SEARCH / USD), so
-- the GROUP BY is a pass-through.
--
-- MARKET is the 4th underscore-delimited segment of CAMPAIGN_NAME (AU / UAE / SA / BR / CL —
-- note SA = Saudi Arabia here, not South America). The fixed-offset parse is safe ONLY because the
-- IN list is a closed set of five known names — the gate sees the parse's whole input domain. A
-- sixth campaign is one new name in the IN list; the market then derives itself.
--
-- ENGAGEMENT_ACTIONS is the raw CONVERSIONS column, renamed on purpose: this account counts
-- Se.com_Page View / Se.com_CTA Click / Se.com_File Download as conversion actions, so the figure
-- runs ~1,517 against 660 clicks. Labelled "conversions" it would read as lead volume and be wrong
-- by two orders of magnitude. No campaign-level split exists to derive a lead-only metric (the
-- conversion table carries no CAMPAIGN_NAME) — do not attempt one from this source.
--
-- CURRENCY / FX: this buy bills in USD (verified across every row) while the rest of the dashboard
-- stores AUD and converts to EUR in the browser (`bbApplyFx()`). Search does a SINGLE USD->EUR hop
-- HERE — never USD->AUD->EUR, which would invent an AUD amount that never existed for this buy and
-- compound two rates on a figure that must reconcile against a US invoice. The rate is PINNED as a
-- column with its effective date (fx CTE below): 0.86259 EUR/USD, the ECB reference rate for
-- 2026-08-17 — the flight-start rate, used because no booked rate was supplied. cost_usd stays
-- next to cost_eur so the source figure is always recoverable. The dashboard must EXEMPT these
-- columns from bbApplyFx() (Stage 3) and footnote the section
-- "Converted from USD at {fx_usd_eur}, {fx_rate_date}."
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.stg_google_search` AS
WITH fx AS (
  -- Pinned flight-start rate (ECB reference, 2026-08-17). One row, cross-joined; the ONLY place
  -- the Search USD->EUR rate is defined — the totals view and the export job inherit it from here.
  SELECT DATE '2026-08-17' AS fx_rate_date, 0.86259 AS fx_usd_eur
),
s AS (
  SELECT
    DATE(DAY)                                  AS day,
    SPLIT(CAMPAIGN_NAME, '_')[SAFE_OFFSET(3)]  AS market,
    CAMPAIGN_NAME                              AS campaign_name,
    NULLIF(TRIM(IFNULL(NETWORK, '')), '')      AS network,
    CURRENCY                                   AS currency,
    SUM(IMPRESSIONS)                           AS impressions,
    SUM(CLICKS)                                AS clicks,
    SUM(COSTS)                                 AS cost_usd,
    SUM(CONVERSIONS)                           AS engagement_actions
  FROM `bidbrain-analytics.raw_snowflake.google_ads_apac`
  WHERE ACCOUNT_NAME = 'AAG region Account'
    AND CAMPAIGN_NAME IN (
      '2306_SE_AI&LiquidCooling_AU_SEM_AWR',
      '2306_SE_AI&LiquidCooling_UAE_SEM_AWR',
      '2306_SE_AI&LiquidCooling_SA_SEM_AWR',
      '2306_SE_AI&LiquidCooling_BR_SEM_AWR',
      '2306_SE_AI&LiquidCooling_CL_SEM_AWR'
    )
  GROUP BY day, market, campaign_name, network, currency
)
SELECT
  s.day,
  s.market,
  s.campaign_name,
  s.network,
  s.currency,
  s.impressions,
  s.clicks,
  s.cost_usd,
  s.cost_usd * fx.fx_usd_eur                   AS cost_eur,
  s.engagement_actions,
  fx.fx_usd_eur,
  fx.fx_rate_date,
  -- Freshness footer: the latest day Search has loaded. Search runs ~a day behind Trade Desk, so
  -- any rolling window on the dashboard must be computed per channel from this, never shared.
  MAX(s.day) OVER ()                           AS data_through
FROM s CROSS JOIN fx;
