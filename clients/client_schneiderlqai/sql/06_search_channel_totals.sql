-- LQAIDC Google Search channel totals — one row, whole-flight, for the headline tiles.
--
-- Derived entirely from stg_google_search so the totals can never disagree with the daily view.
-- CTR/CPC are SAFE_DIVIDE (no delivery -> NULL, never a divide-by-zero or a false 0).
-- cost/cpc are USD — see the stg view header: do NOT sum or blend with the AUD/EUR channels.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.search_channel_totals` AS
SELECT
  SUM(impressions)                              AS impressions,
  SUM(clicks)                                   AS clicks,
  SUM(cost_usd)                                 AS cost_usd,
  SUM(engagement_actions)                       AS engagement_actions,
  SAFE_DIVIDE(SUM(clicks), SUM(impressions))    AS ctr,
  SAFE_DIVIDE(SUM(cost_usd), SUM(clicks))       AS cpc_usd,
  MAX(day)                                      AS data_through
FROM `bidbrain-analytics.client_schneiderlqai.stg_google_search`;
