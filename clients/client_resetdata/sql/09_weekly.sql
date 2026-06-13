-- ResetData — weekly ads-vs-traffic correlation series (campaign window).
--
-- One row per ISO week (Mon-anchored). Pairs the week's ad delivery (Google + Meta + TTD
-- impressions/clicks/spend) with the website sessions on the three channels those ads map to
-- — Paid Search (Google), Paid Social (Meta), Display (TTD) — plus all paid and all sessions.
-- This is what the "Ads → Traffic" tab plots and correlates. Per-platform impressions kept so
-- the Platform filter can recompute the ad series client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.weekly` AS
WITH
g AS (
  SELECT
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(sessions)                                       AS ga4_sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
    SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
    SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions,
    SUM(conversions)                                    AS conversions
  FROM `bidbrain-analytics.client_resetdata.stg_ga4`
  WHERE metric_date >= DATE '2025-12-01'
  GROUP BY week_start
),
ga AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS ga_imps, SUM(clicks) AS ga_clicks, SUM(spend_aud) AS ga_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_google`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY week_start
),
me AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS me_imps, SUM(clicks) AS me_clicks, SUM(spend_aud) AS me_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_meta`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY week_start
),
td AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks, SUM(spend_aud) AS td_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_ttd`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY week_start
)
SELECT
  g.week_start,
  g.ga4_sessions, g.paid_sessions, g.search_sessions, g.social_sessions, g.display_sessions,
  g.conversions,
  IFNULL(ga.ga_imps, 0)   AS ga_imps,
  IFNULL(me.me_imps, 0)   AS me_imps,
  IFNULL(td.td_imps, 0)   AS td_imps,
  IFNULL(ga.ga_imps,0) + IFNULL(me.me_imps,0) + IFNULL(td.td_imps,0)         AS ad_imps,
  IFNULL(ga.ga_clicks,0) + IFNULL(me.me_clicks,0) + IFNULL(td.td_clicks,0)   AS ad_clicks,
  IFNULL(ga.ga_spend_aud,0) + IFNULL(me.me_spend_aud,0) + IFNULL(td.td_spend_aud,0) AS ad_spend_aud
FROM g
LEFT JOIN ga USING (week_start)
LEFT JOIN me USING (week_start)
LEFT JOIN td USING (week_start)
ORDER BY week_start;
