-- Schneider Electric — GA4 headline metrics (whole property, all available dates). SHIPPED DISABLED
-- (0 rows until stg_ga4's property placeholder is set). Whole-site — perf_ga4 has no geo, so a single
-- 'All' market row (mirrors client_vmch/sql/13). users / new_users / page_views / eng_duration are
-- NULL from the DTS source (see stg_ga4 grain caveat). prior_* kept 0 (no YoY baseline yet).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_kpi_market` AS
SELECT
  'All' AS market,
  SUM(sessions)                 AS sessions,
  SUM(engaged_sessions)         AS engaged_sessions,
  SUM(total_users)              AS users,
  SUM(new_users)                AS new_users,
  SUM(screen_page_views)        AS page_views,
  SUM(user_engagement_duration) AS eng_duration,
  SUM(conversions)              AS conversions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0))        AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0))      AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0))  AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0))  AS search_sessions,
  0 AS prior_sessions,
  0 AS prior_paid_sessions
FROM `bidbrain-analytics.client_schneider.stg_ga4`;
