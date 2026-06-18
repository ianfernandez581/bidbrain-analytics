-- VMCH — daily trend (campaign window): GA4 sessions vs TTD delivery.
-- One row per day. Mirrors 05_monthly.sql / 12_weekly.sql at metric_date grain, so the
-- Overview/Website trend charts can offer a Day view. Flight is Apr 2026+ so daily volume is small.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.daily` AS
WITH
g AS (
  SELECT
    metric_date AS day,
    SUM(sessions)                                                      AS sessions,
    SUM(IF(channel_bucket = 'Paid',    sessions, 0))                   AS paid_sessions,
    SUM(IF(channel_bucket = 'Organic', sessions, 0))                   AS organic_sessions,
    SUM(IF(channel_bucket = 'Direct',  sessions, 0))                   AS direct_sessions,
    SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions,
    SUM(IF(channel_group = 'Display',     sessions, 0))                AS display_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0))                AS social_sessions,
    SUM(engaged_sessions) AS engaged_sessions,
    SUM(total_users)      AS users,
    SUM(conversions)      AS conversions
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY day
),
ttd AS (
  SELECT metric_date AS day,
         SUM(imps) AS ttd_imps, SUM(clicks) AS ttd_clicks, SUM(spend_aud) AS ttd_spend_aud
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery`   -- incl. MODELLED April (03b/03c)
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY day
)
SELECT
  IFNULL(g.day, ttd.day) AS day,
  IFNULL(g.sessions, 0)          AS sessions,
  IFNULL(g.paid_sessions, 0)     AS paid_sessions,
  IFNULL(g.organic_sessions, 0)  AS organic_sessions,
  IFNULL(g.direct_sessions, 0)   AS direct_sessions,
  IFNULL(g.other_sessions, 0)    AS other_sessions,
  IFNULL(g.display_sessions, 0)  AS display_sessions,
  IFNULL(g.social_sessions, 0)   AS social_sessions,
  IFNULL(g.engaged_sessions, 0)  AS engaged_sessions,
  IFNULL(g.users, 0)             AS users,
  IFNULL(g.conversions, 0)       AS conversions,
  IFNULL(ttd.ttd_imps, 0)      AS ttd_imps,
  IFNULL(ttd.ttd_clicks, 0)    AS ttd_clicks,
  IFNULL(ttd.ttd_spend_aud, 0) AS ttd_spend_aud,
  IFNULL(ttd.ttd_imps, 0)      AS ad_imps,
  IFNULL(ttd.ttd_clicks, 0)    AS ad_clicks,
  IFNULL(ttd.ttd_spend_aud, 0) AS ad_spend_aud
FROM g
FULL OUTER JOIN ttd USING (day)
ORDER BY day;
