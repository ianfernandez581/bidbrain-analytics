-- LQAIDC Google Search channel totals — one row, whole-flight, for the headline tiles.
--
-- Derived entirely from stg_google_search so the totals can never disagree with the daily view —
-- including the pinned USD->EUR rate, which is defined ONCE in the stg view's fx CTE and only
-- inherited here (fx_usd_eur / fx_rate_date carried through for the Stage 3 footnote:
-- "Converted from USD at {fx_usd_eur}, {fx_rate_date}."). cost_usd stays beside cost_eur so the
-- invoice-reconcilable source figure is always recoverable; neither is ever summed with the
-- AUD-warehoused LinkedIn / Trade Desk spend.
-- CTR/CPC are SAFE_DIVIDE (no delivery -> NULL, never a divide-by-zero or a false 0).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.search_channel_totals` AS
SELECT
  SUM(impressions)                              AS impressions,
  SUM(clicks)                                   AS clicks,
  SUM(cost_usd)                                 AS cost_usd,
  SUM(cost_eur)                                 AS cost_eur,
  SUM(engagement_actions)                       AS engagement_actions,
  SAFE_DIVIDE(SUM(clicks), SUM(impressions))    AS ctr,
  SAFE_DIVIDE(SUM(cost_usd), SUM(clicks))       AS cpc_usd,
  SAFE_DIVIDE(SUM(cost_eur), SUM(clicks))       AS cpc_eur,
  MAX(fx_usd_eur)                               AS fx_usd_eur,
  MAX(fx_rate_date)                             AS fx_rate_date,
  MAX(day)                                      AS data_through
FROM `bidbrain-analytics.client_schneiderlqai.stg_google_search`;
