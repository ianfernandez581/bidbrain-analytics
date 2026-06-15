-- ResetData — DAILY trend (the day-grain analogue of `monthly`/`weekly`).
--
-- One row per calendar day: GA4 sessions split by bucket (and the ad-mapped channels Paid
-- Search = Google, Paid Social = Meta + Reddit, Display = TTD) + GA4 key events, alongside
-- Google + Meta + TTD + Reddit delivery for the same day. Powers the "View by → Day" grain on
-- the Overview hero, Website "Total vs ad-driven" and Ads → Traffic trend charts. From
-- 2025-12-01 (the start of the live data), matching `monthly`/`weekly`. raw_ga4.perf_ga4 is
-- already day-grained, so this is real per-day data (NOT interpolated). NO revenue (B2B).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.daily` AS
WITH
g AS (
  SELECT
    metric_date AS day,
    SUM(sessions)                                                           AS sessions,
    SUM(IF(channel_bucket = 'Paid',    sessions, 0))                        AS paid_sessions,
    SUM(IF(channel_bucket = 'Organic', sessions, 0))                        AS organic_sessions,
    SUM(IF(channel_bucket = 'Direct',  sessions, 0))                        AS direct_sessions,
    SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions,
    SUM(IF(channel_group = 'Paid Search', sessions, 0))                     AS search_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0))                     AS social_sessions,
    SUM(IF(channel_group = 'Display',     sessions, 0))                     AS display_sessions,
    SUM(engaged_sessions) AS engaged_sessions,
    SUM(total_users)      AS users,
    SUM(conversions)      AS conversions
  FROM `bidbrain-analytics.client_resetdata.stg_ga4`
  WHERE metric_date >= DATE '2025-12-01'
  GROUP BY day
),
ga AS (
  SELECT metric_date AS day,
         SUM(imps) AS ga_imps, SUM(clicks) AS ga_clicks, SUM(spend_aud) AS ga_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_google`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY day
),
me AS (
  SELECT metric_date AS day,
         SUM(imps) AS me_imps, SUM(clicks) AS me_clicks, SUM(spend_aud) AS me_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_meta`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY day
),
td AS (
  SELECT metric_date AS day,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks, SUM(spend_aud) AS td_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_ttd`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY day
),
rd AS (
  SELECT metric_date AS day,
         SUM(imps) AS rd_imps, SUM(clicks) AS rd_clicks, SUM(spend_aud) AS rd_spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_reddit`
  WHERE metric_date >= DATE '2025-12-01' GROUP BY day
)
SELECT
  g.day,
  g.sessions, g.paid_sessions, g.organic_sessions, g.direct_sessions, g.other_sessions,
  g.search_sessions, g.social_sessions, g.display_sessions,
  g.engaged_sessions, g.users, g.conversions,
  IFNULL(ga.ga_imps, 0)      AS ga_imps,
  IFNULL(ga.ga_clicks, 0)    AS ga_clicks,
  IFNULL(ga.ga_spend_aud, 0) AS ga_spend_aud,
  IFNULL(me.me_imps, 0)      AS me_imps,
  IFNULL(me.me_clicks, 0)    AS me_clicks,
  IFNULL(me.me_spend_aud, 0) AS me_spend_aud,
  IFNULL(td.td_imps, 0)      AS td_imps,
  IFNULL(td.td_clicks, 0)    AS td_clicks,
  IFNULL(td.td_spend_aud, 0) AS td_spend_aud,
  IFNULL(rd.rd_imps, 0)      AS rd_imps,
  IFNULL(rd.rd_clicks, 0)    AS rd_clicks,
  IFNULL(rd.rd_spend_aud, 0) AS rd_spend_aud,
  IFNULL(ga.ga_imps,0)   + IFNULL(me.me_imps,0)   + IFNULL(td.td_imps,0)   + IFNULL(rd.rd_imps,0)   AS ad_imps,
  IFNULL(ga.ga_clicks,0) + IFNULL(me.me_clicks,0) + IFNULL(td.td_clicks,0) + IFNULL(rd.rd_clicks,0) AS ad_clicks,
  IFNULL(ga.ga_spend_aud,0) + IFNULL(me.me_spend_aud,0) + IFNULL(td.td_spend_aud,0) + IFNULL(rd.rd_spend_aud,0) AS ad_spend_aud
FROM g
LEFT JOIN ga USING (day)
LEFT JOIN me USING (day)
LEFT JOIN td USING (day)
LEFT JOIN rd USING (day)
ORDER BY day;
