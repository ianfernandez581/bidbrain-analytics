-- ResetData — GA4 sessions / engaged / key events by channel group (whole window).
-- Powers the Overview channel-mix donut and the Website tab's channel breakdown.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga4_channels` AS
SELECT
  channel_group,
  ANY_VALUE(channel_bucket)  AS channel_bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged_sessions,
  SUM(total_users)           AS users,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_resetdata.stg_ga4`
GROUP BY channel_group
ORDER BY sessions DESC;
