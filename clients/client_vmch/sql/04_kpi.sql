-- VMCH — headline KPI row (single row the dashboard reads for the big numbers).
--
-- Campaign window = 2026-04-01 → latest data (TTD started Apr 2026).
-- NO fx constant — spend is already AUD.
-- ad_* = TTD only (one platform).
-- YoY baseline (gp) must be LIKE-FOR-LIKE: the SAME calendar span one year earlier
-- (2025-04-01 .. latest-GA4-date minus one year), NOT a full 12 months — the flight is only ~2
-- months, so comparing it to a year would show a false ~77% drop instead of real YoY growth.
-- TTD data covers Apr-Jun 2026; the campaign window aligns to TTD's start.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.kpi` AS
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
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2026-04-01'
),
gp AS (
  -- prior-year, same span: 2025-04-01 .. (max GA4 date − 1 year)
  SELECT
    SUM(sessions) AS sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0)) AS paid_sessions
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2025-04-01'
    AND metric_date <= DATE_SUB(
          (SELECT MAX(metric_date) FROM `bidbrain-analytics.client_vmch.stg_ga4`), INTERVAL 1 YEAR)
),
ttd AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         SUM(post_view_conv)  AS post_view,    -- TTD post-view (view-through) attributed conversions
         SUM(post_click_conv) AS post_click,   -- TTD post-click attributed conversions
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery`   -- incl. MODELLED April (03b/03c)
)
SELECT
  DATE '2026-04-01' AS campaign_start,
  g.ga4_end         AS campaign_end,
  DATE_DIFF(g.ga4_end, DATE '2026-04-01', DAY) + 1 AS campaign_days,
  g.sessions, g.engaged_sessions, g.users, g.new_users, g.page_views,
  g.eng_duration, g.conversions,
  g.paid_sessions, g.display_sessions, g.social_sessions,
  gp.sessions      AS prior_sessions,
  gp.paid_sessions AS prior_paid_sessions,
  ttd.imps AS ttd_imps, ttd.clicks AS ttd_clicks, ttd.spend_aud AS ttd_spend_aud,
  ttd.start_date AS ttd_start, ttd.end_date AS ttd_end,
  ttd.imps                     AS ad_imps,
  ttd.clicks                   AS ad_clicks,
  ttd.spend_aud                AS ad_spend_aud,
  ttd.post_view                AS ad_post_view,
  ttd.post_click               AS ad_post_click
FROM g, gp, ttd;