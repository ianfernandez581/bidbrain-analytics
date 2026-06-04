-- Schneider Electric — GA4 sessions by channel group BY market (campaign window). SHIPPED
-- DISABLED (0 rows until stg_ga4's property placeholder is set). Mirrors client_STT/sql/16.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_channels_market` AS
SELECT
  market,
  channel_group,
  ANY_VALUE(channel_bucket)  AS channel_bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged_sessions,
  SUM(total_users)           AS users,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY market, channel_group;
