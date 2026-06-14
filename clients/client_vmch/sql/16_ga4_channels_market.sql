-- VMCH — GA4 sessions by channel group.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_channels_market` AS
SELECT
  'Australia' AS market,
  channel_group,
  ANY_VALUE(channel_bucket) AS channel_bucket,
  SUM(sessions) AS sessions,
  SUM(engaged_sessions) AS engaged_sessions,
  SUM(total_users) AS users,
  SUM(conversions) AS conversions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01'
GROUP BY channel_group;