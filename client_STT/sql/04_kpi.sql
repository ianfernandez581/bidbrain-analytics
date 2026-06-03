-- STT GDC — headline KPI row (single row the dashboard reads for the big numbers).
--
-- Campaign window = 2025-06-01 → latest GA4 day (FY25-26 Always On, SOW 2).
-- FX_USD_SGD (1.34) converts the LinkedIn USD spend into the SGD reporting
-- currency so a single combined media-spend figure can sit next to DV360's SGD
-- and Google Ads' (already SGD-converted in stg_google). The prior-year window
-- gives a rough pre-campaign baseline for the sessions Δ. ad_* = LinkedIn + DV360
-- + Google Ads combined.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.kpi` AS
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
    SUM(IF(channel_group = 'Paid Social', sessions, 0))  AS social_sessions
  FROM `bidbrain-analytics.client_stt.stg_ga4`
  WHERE metric_date >= DATE '2025-06-01'
),
gp AS (
  SELECT
    SUM(sessions) AS sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0)) AS paid_sessions
  FROM `bidbrain-analytics.client_stt.stg_ga4`
  WHERE metric_date >= DATE '2024-06-01' AND metric_date < DATE '2025-06-01'
),
li AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(cost_usd) AS cost_usd,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_stt.stg_linkedin`
),
dv AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_sgd) AS spend_sgd,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_stt.stg_dv360`
),
ga AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_sgd) AS spend_sgd,
         SUM(conversions) AS conversions,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_stt.stg_google`
)
SELECT
  1.34 AS fx_usd_sgd,
  DATE '2025-06-01' AS campaign_start,
  g.ga4_end         AS campaign_end,
  DATE_DIFF(g.ga4_end, DATE '2025-06-01', DAY) + 1 AS campaign_days,
  g.sessions, g.engaged_sessions, g.users, g.new_users, g.page_views,
  g.eng_duration, g.conversions,
  g.paid_sessions, g.display_sessions, g.social_sessions,
  gp.sessions      AS prior_sessions,
  gp.paid_sessions AS prior_paid_sessions,
  li.imps AS li_imps, li.clicks AS li_clicks, li.cost_usd AS li_cost_usd,
  li.start_date AS li_start, li.end_date AS li_end,
  dv.imps AS dv_imps, dv.clicks AS dv_clicks, dv.spend_sgd AS dv_spend_sgd,
  dv.start_date AS dv_start, dv.end_date AS dv_end,
  ga.imps AS ga_imps, ga.clicks AS ga_clicks, ga.spend_sgd AS ga_spend_sgd,
  ga.conversions AS ga_conv, ga.start_date AS ga_start, ga.end_date AS ga_end,
  (li.imps + dv.imps + ga.imps)                              AS ad_imps,
  (li.clicks + dv.clicks + ga.clicks)                         AS ad_clicks,
  (dv.spend_sgd + li.cost_usd * 1.34 + ga.spend_sgd)          AS ad_spend_sgd
FROM g, gp, li, dv, ga;
