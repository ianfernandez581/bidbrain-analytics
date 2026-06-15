-- TLM — ad delivery by campaign × day (campaign window), for the Campaign-filtered
-- day-grain charts (Overview hero, Google Ads monthly→daily chart, Performance trend).
-- Mirrors 13_ad_campaign_weekly.sql but groups on the raw metric_date ('YYYY-MM-DD')
-- instead of DATE_TRUNC(...,WEEK). From 2025-08-01 (window start per EDA). Delivering
-- rows only. conversions + revenue are carried (Google-only; TTD is NULL) so the day-grain
-- hero revenue/ROAS line and perf trend stay campaign-filterable instead of reading zero.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    metric_date      AS day,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions,   -- Google-only (TTD NULL); the e-commerce signal
    SUM(revenue)     AS revenue        -- Google-only (TTD NULL); ROAS numerator
  FROM `bidbrain-analytics.client_tlm.stg_ad_delivery`
  WHERE metric_date >= DATE '2025-08-01'
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY day, platform, campaign;
