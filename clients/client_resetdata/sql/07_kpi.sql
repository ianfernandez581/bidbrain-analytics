-- ResetData — headline KPI row (the single row the dashboard reads for the big numbers).
--
-- B2B "ads → traffic / leads": GA4 website outcomes next to Google + Meta + TTD + Reddit
-- delivery. Window = 2025-12-01 → latest GA4 day (the live data starts mid-Dec 2025).
-- FX_USD_AUD (1.50) converts TTD's USD spend into the AUD reporting currency (Google + Meta +
-- Reddit already AUD), so a single combined media-spend figure is valid. ad_* = Google + Meta
-- + TTD + Reddit combined.
-- NO revenue/ROAS/transactions (B2B — those are ~0 upstream). conversions = GA4 key events;
-- platform conversions kept per-platform (Google solid, Meta sparse, TTD none).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.kpi` AS
WITH
g AS (
  SELECT
    MIN(metric_date) AS ga4_start, MAX(metric_date) AS ga4_end,
    SUM(sessions)                 AS sessions,
    SUM(engaged_sessions)         AS engaged_sessions,
    SUM(total_users)              AS users,
    SUM(new_users)                AS new_users,
    SUM(screen_page_views)        AS page_views,
    SUM(user_engagement_duration) AS eng_duration,
    SUM(conversions)              AS conversions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0))        AS paid_sessions,
    SUM(IF(channel_group = 'Display', sessions, 0))      AS display_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0))  AS social_sessions,
    SUM(IF(channel_group = 'Paid Search', sessions, 0))  AS search_sessions
  FROM `bidbrain-analytics.client_resetdata.stg_ga4`
  WHERE metric_date >= DATE '2025-12-01'
),
ga AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         SUM(conversions) AS conversions,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_google`
),
me AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         SUM(conversions) AS conversions,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_meta`
),
td AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_ttd`
),
rd AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         SUM(conversions) AS conversions, SUM(page_visits) AS page_visits,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_reddit`
)
SELECT
  1.50 AS fx_usd_aud,
  DATE '2025-12-01' AS campaign_start,
  g.ga4_end         AS campaign_end,
  DATE_DIFF(g.ga4_end, DATE '2025-12-01', DAY) + 1 AS campaign_days,
  g.sessions, g.engaged_sessions, g.users, g.new_users, g.page_views,
  g.eng_duration, g.conversions,
  g.paid_sessions, g.display_sessions, g.social_sessions, g.search_sessions,
  ga.imps AS ga_imps, ga.clicks AS ga_clicks, ga.spend_aud AS ga_spend_aud,
  ga.conversions AS ga_conv, ga.start_date AS ga_start, ga.end_date AS ga_end,
  me.imps AS me_imps, me.clicks AS me_clicks, me.spend_aud AS me_spend_aud,
  me.conversions AS me_conv, me.start_date AS me_start, me.end_date AS me_end,
  td.imps AS td_imps, td.clicks AS td_clicks, td.spend_aud AS td_spend_aud,
  td.start_date AS td_start, td.end_date AS td_end,
  rd.imps AS rd_imps, rd.clicks AS rd_clicks, rd.spend_aud AS rd_spend_aud,
  rd.conversions AS rd_conv, rd.page_visits AS rd_page_visits,
  rd.start_date AS rd_start, rd.end_date AS rd_end,
  (IFNULL(ga.imps,0)   + IFNULL(me.imps,0)   + IFNULL(td.imps,0)   + IFNULL(rd.imps,0))   AS ad_imps,
  (IFNULL(ga.clicks,0) + IFNULL(me.clicks,0) + IFNULL(td.clicks,0) + IFNULL(rd.clicks,0)) AS ad_clicks,
  (IFNULL(ga.spend_aud,0) + IFNULL(me.spend_aud,0) + IFNULL(td.spend_aud,0) + IFNULL(rd.spend_aud,0)) AS ad_spend_aud,
  -- combined platform-reported conversions (Google + Meta + Reddit; TTD reports none)
  (IFNULL(ga.conversions,0) + IFNULL(me.conversions,0) + IFNULL(rd.conversions,0))        AS ad_conv
FROM g, ga, me, td, rd;
