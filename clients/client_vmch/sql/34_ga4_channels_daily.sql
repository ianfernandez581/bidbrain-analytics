-- VMCH — GA4 sessions by channel group, PER DAY.
-- Daily twin of 16_ga4_channels_market so the Website channel donut responds to the
-- date-range picker (re-aggregated within range on the frontend). Same flight clamp,
-- so the default all-time view sums to the whole-flight totals.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_channels_daily` AS
SELECT
  metric_date               AS day,
  channel_group,
  ANY_VALUE(channel_bucket) AS channel_bucket,
  SUM(sessions)             AS sessions,
  SUM(engaged_sessions)     AS engaged_sessions,
  SUM(total_users)          AS users,
  SUM(conversions)          AS conversions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01'
GROUP BY metric_date, channel_group;
