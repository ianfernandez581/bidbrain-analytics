-- Schneider Electric — GA4 headline metrics BY market + prior-year baseline. SHIPPED DISABLED
-- (returns 0 rows until stg_ga4's property placeholder is set). Mirrors client_STT/sql/13.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_kpi_market` AS
WITH cur AS (
  SELECT
    market,
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
    SUM(IF(channel_group = 'Paid Search', sessions, 0))  AS search_sessions
  FROM `bidbrain-analytics.client_schneider.stg_ga4`
  WHERE metric_date >= DATE '2025-06-01'
  GROUP BY market
),
prior AS (
  SELECT
    market,
    SUM(sessions) AS prior_sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0)) AS prior_paid_sessions
  FROM `bidbrain-analytics.client_schneider.stg_ga4`
  WHERE metric_date >= DATE '2024-06-01' AND metric_date < DATE '2025-06-01'
  GROUP BY market
)
SELECT
  c.*,
  IFNULL(p.prior_sessions, 0)      AS prior_sessions,
  IFNULL(p.prior_paid_sessions, 0) AS prior_paid_sessions
FROM cur c
LEFT JOIN prior p USING (market)
ORDER BY sessions DESC;
