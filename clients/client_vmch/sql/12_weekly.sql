-- VMCH — weekly ads-vs-traffic correlation series (campaign window).
-- One row per ISO week. Pairs TTD impressions/clicks/spend with GA4 Display sessions.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.weekly` AS
WITH
g AS (
  SELECT
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(sessions)                                       AS ga4_sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
    SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY week_start
),
ttd AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS ttd_imps, SUM(clicks) AS ttd_clicks, SUM(spend_aud) AS ttd_spend_aud
  FROM `bidbrain-analytics.client_vmch.stg_ttd`
  WHERE metric_date >= DATE '2026-04-01' GROUP BY week_start
)
SELECT
  g.week_start,
  g.ga4_sessions, g.paid_sessions, g.display_sessions,
  IFNULL(ttd.ttd_imps, 0)      AS ttd_imps,
  IFNULL(ttd.ttd_clicks, 0)    AS ttd_clicks,
  IFNULL(ttd.ttd_imps, 0)      AS ad_imps,
  IFNULL(ttd.ttd_clicks, 0)    AS ad_clicks,
  IFNULL(ttd.ttd_spend_aud, 0) AS ad_spend_aud
FROM g
LEFT JOIN ttd USING (week_start)
ORDER BY week_start;