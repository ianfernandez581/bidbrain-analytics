-- ResetData — monthly trend: the hero "ad spend vs website sessions" series.
--
-- One row per month: GA4 sessions split by bucket (and the ad-mapped channels Paid Search =
-- Google, Paid Social = Meta, Display = TTD) + GA4 key events, alongside Google + Meta + TTD
-- delivery for the same month. From 2025-12 (the start of the live data). ad_* folds the three
-- platforms in (TTD already USD→AUD in its stg view). NO revenue (B2B).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.monthly` AS
WITH
g AS (
  SELECT
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(sessions)                                                           AS sessions,
    SUM(IF(channel_bucket = 'Paid',    sessions, 0))                        AS paid_sessions,
    SUM(IF(channel_bucket = 'Organic', sessions, 0))                        AS organic_sessions,
    SUM(IF(channel_bucket = 'Direct',  sessions, 0))                        AS direct_sessions,
    SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions,
    SUM(IF(channel_group = 'Paid Search', sessions, 0))                     AS search_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0))                     AS social_sessions,
    SUM(IF(channel_group = 'Display',     sessions, 0))                     AS display_sessions,
    SUM(engaged_sessions) AS engaged_sessions,
    SUM(total_users)      AS users,
    SUM(conversions)      AS conversions
  FROM `bidbrain-analytics.client_resetdata.stg_ga4`
  WHERE metric_date >= DATE '2025-12-01'
  GROUP BY month
),
ga AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS ga_imps, SUM(clicks) AS ga_clicks, SUM(spend_aud) AS ga_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_google` GROUP BY month
),
me AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS me_imps, SUM(clicks) AS me_clicks, SUM(spend_aud) AS me_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_meta` GROUP BY month
),
td AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks, SUM(spend_aud) AS td_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_ttd` GROUP BY month
)
SELECT
  g.*,
  IFNULL(ga.ga_imps, 0)      AS ga_imps,
  IFNULL(ga.ga_clicks, 0)    AS ga_clicks,
  IFNULL(ga.ga_spend_aud, 0) AS ga_spend_aud,
  IFNULL(me.me_imps, 0)      AS me_imps,
  IFNULL(me.me_clicks, 0)    AS me_clicks,
  IFNULL(me.me_spend_aud, 0) AS me_spend_aud,
  IFNULL(td.td_imps, 0)      AS td_imps,
  IFNULL(td.td_clicks, 0)    AS td_clicks,
  IFNULL(td.td_spend_aud, 0) AS td_spend_aud,
  IFNULL(ga.ga_imps,0)   + IFNULL(me.me_imps,0)   + IFNULL(td.td_imps,0)   AS ad_imps,
  IFNULL(ga.ga_clicks,0) + IFNULL(me.me_clicks,0) + IFNULL(td.td_clicks,0) AS ad_clicks,
  IFNULL(ga.ga_spend_aud,0) + IFNULL(me.me_spend_aud,0) + IFNULL(td.td_spend_aud,0) AS ad_spend_aud
FROM g
LEFT JOIN ga USING (month)
LEFT JOIN me USING (month)
LEFT JOIN td USING (month)
ORDER BY month;
