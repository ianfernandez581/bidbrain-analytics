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
-- pull in unrelated 2306_* campaigns. NETWORK is deliberately NOT filtered: should Google ever
-- report SEARCH_PARTNERS rows on these campaigns, they stay in the totals (over-filtering is the
-- silent failure).
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
-- CURRENCY: USD (verified across every row). NOTE this differs from the rest of the dashboard,
-- whose warehouse layer is AUD (`spend_aud`) with a browser-only AUD->EUR conversion — so Search
-- spend must NOT be summed with LinkedIn/Trade Desk spend anywhere downstream until that is
-- resolved. `cost_usd` is named to make a mixed-currency sum look wrong at the point of writing it.
-- CURRENCY stays in the GROUP BY so a source-side currency change splits rows loudly instead of
-- mislabelling the column.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.stg_google_search` AS
WITH s AS (
  SELECT
    DATE(DAY)                                  AS day,
    SPLIT(CAMPAIGN_NAME, '_')[SAFE_OFFSET(3)]  AS market,
    CAMPAIGN_NAME                              AS campaign_name,
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
  GROUP BY day, market, campaign_name, currency
)
SELECT
  s.*,
  -- Freshness footer: the latest day Search has loaded. Search runs ~a day behind Trade Desk, so
  -- any rolling window on the dashboard must be computed per channel from this, never shared.
  MAX(day) OVER ()                             AS data_through
FROM s;
