-- TLM — ad delivery by campaign × ISO week (campaign window), for the Campaign-filtered
-- Performance tab weekly chart + Pearson correlation scatter. Week is Monday-anchored to
-- match `weekly`. From 2025-08-01 (window start per EDA). Delivering rows only.
-- conversions + revenue are carried (Google-only; TTD is NULL) so the weekly scatter, the
-- week-grain hero revenue/ROAS line, and the week-grain perf trend stay campaign-filterable
-- instead of silently reading zero.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.ad_campaign_weekly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions,   -- Google-only (TTD NULL); the e-commerce signal
    SUM(revenue)     AS revenue        -- Google-only (TTD NULL); ROAS numerator
  FROM `bidbrain-analytics.client_tlm.stg_ad_delivery`
  WHERE metric_date >= DATE '2025-08-01'
  GROUP BY platform, campaign, week_start
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY week_start, platform, campaign;