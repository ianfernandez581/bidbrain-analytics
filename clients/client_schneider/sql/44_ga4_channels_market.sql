-- Schneider Electric — GA4 sessions by channel group (whole property). SHIPPED DISABLED (0 rows until
-- stg_ga4's property placeholder is set). Whole-site single 'All' market. Mirrors client_vmch/sql/16.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_channels_market` AS
SELECT
  'All' AS market,
  channel_group,
  ANY_VALUE(channel_bucket)  AS channel_bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged_sessions,
  SUM(total_users)           AS users,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
GROUP BY channel_group;
