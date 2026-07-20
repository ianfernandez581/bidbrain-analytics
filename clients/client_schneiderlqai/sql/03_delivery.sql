-- LQAIDC unified paid-media delivery fact — the dashboard's main data source (the pm_delivery analog).
--
-- One row per platform × country × day. The dashboard aggregates this client-side (hero time-series,
-- channel comparison, country breakdown), filtered by the country chips + the date-range picker. The
-- `region` rolls the 6 countries up to the media-plan's reporting regions (the brief groups them as
-- South America (Brazil & Chile), MEA (Saudi Arabia & UAE), Pacific (Australia), and India).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.delivery` AS
WITH u AS (
  SELECT platform, metric_date, country, imps, clicks, spend_aud FROM `bidbrain-analytics.client_schneiderlqai.stg_linkedin`
  UNION ALL
  SELECT platform, metric_date, country, imps, clicks, spend_aud FROM `bidbrain-analytics.client_schneiderlqai.stg_tradedesk`
)
SELECT
  platform,
  metric_date,
  country,
  CASE country
    WHEN 'Brazil'       THEN 'South America'
    WHEN 'Chile'        THEN 'South America'
    WHEN 'Saudi Arabia' THEN 'MEA'
    WHEN 'UAE'          THEN 'MEA'
    WHEN 'Australia'    THEN 'Pacific'
    WHEN 'India'        THEN 'India'
    ELSE 'Other'
  END                                      AS region,
  SUM(imps)                                AS imps,
  SUM(clicks)                              AS clicks,
  SUM(spend_aud)                           AS spend_aud
FROM u
GROUP BY platform, metric_date, country, region;
