-- STT GDC — weekly ads-vs-traffic correlation series (campaign window).
--
-- One row per ISO week (Mon-anchored). Pairs the week's ad delivery (LinkedIn +
-- DV360 + Google Ads impressions/clicks/spend) with the website sessions on the
-- three channels those ads map to — Display (DV360), Paid Social (LinkedIn) and
-- Paid Search (Google Ads) — plus all paid and all sessions. This is what the
-- "Ads → Traffic" tab plots and correlates. Per-platform impressions are kept so
-- the dashboard's Platform filter can recompute the ad series client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.weekly` AS
WITH
g AS (
  SELECT
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(sessions)                                       AS ga4_sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
    SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
    SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions
  FROM `bidbrain-analytics.client_stt.stg_ga4`
  WHERE metric_date >= DATE '2025-06-01'
  GROUP BY week_start
),
li AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(cost_usd) AS li_cost_usd
  FROM `bidbrain-analytics.client_stt.stg_linkedin`
  WHERE metric_date >= DATE '2025-06-01' GROUP BY week_start
),
dv AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS dv_imps, SUM(clicks) AS dv_clicks, SUM(spend_sgd) AS dv_spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_dv360`
  WHERE metric_date >= DATE '2025-06-01' GROUP BY week_start
),
ga AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS ga_imps, SUM(clicks) AS ga_clicks, SUM(spend_sgd) AS ga_spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_google`
  WHERE metric_date >= DATE '2025-06-01' GROUP BY week_start
)
SELECT
  g.week_start,
  g.ga4_sessions, g.paid_sessions, g.display_sessions, g.social_sessions, g.search_sessions,
  IFNULL(li.li_imps, 0)   AS li_imps,
  IFNULL(dv.dv_imps, 0)   AS dv_imps,
  IFNULL(ga.ga_imps, 0)   AS ga_imps,
  IFNULL(li.li_imps, 0) + IFNULL(dv.dv_imps, 0) + IFNULL(ga.ga_imps, 0)                  AS ad_imps,
  IFNULL(li.li_clicks, 0) + IFNULL(dv.dv_clicks, 0) + IFNULL(ga.ga_clicks, 0)            AS ad_clicks,
  IFNULL(dv.dv_spend_sgd, 0) + IFNULL(li.li_cost_usd, 0) * 1.34 + IFNULL(ga.ga_spend_sgd, 0) AS ad_spend_sgd
FROM g
LEFT JOIN li USING (week_start)
LEFT JOIN dv USING (week_start)
LEFT JOIN ga USING (week_start)
ORDER BY week_start;
