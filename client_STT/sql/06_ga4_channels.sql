-- STT GDC — website sessions by GA4 default channel group (campaign window).
-- Feeds the "where traffic comes from" breakdown; the dashboard highlights the
-- Paid bucket (and Display = DV360, Paid Social = LinkedIn) in red.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_channels` AS
SELECT
  channel_group,
  ANY_VALUE(channel_bucket)  AS channel_bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged_sessions,
  SUM(total_users)           AS users,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_stt.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY channel_group
ORDER BY sessions DESC;
