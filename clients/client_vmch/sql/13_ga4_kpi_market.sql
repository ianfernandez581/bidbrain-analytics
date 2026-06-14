-- VMCH — GA4 headline metrics (whole-campaign). No geo dimension — single "Australia" row.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_kpi_market` AS
SELECT
  'Australia' AS market,
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
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01';