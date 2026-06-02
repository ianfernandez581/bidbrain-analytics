-- STT GDC — website sessions by market / property (campaign window).
-- Each market is a distinct GA4 property ("All Sites" = the main corporate site,
-- the rest are the regional sites + Global). paid_sessions / display_sessions /
-- social_sessions let the dashboard show how much of each site's traffic the ads
-- drove.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_markets` AS
SELECT
  market,
  SUM(sessions)                                       AS sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
  SUM(engaged_sessions)                               AS engaged_sessions,
  SUM(total_users)                                    AS users,
  SUM(conversions)                                    AS conversions
FROM `bidbrain-analytics.client_stt.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY market
ORDER BY sessions DESC;
