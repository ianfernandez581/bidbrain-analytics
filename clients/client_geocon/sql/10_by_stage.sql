-- 10_by_stage: spend, spend-share, leads, lead-share, CPL by funnel_stage.
-- The budget-reallocation decision view: surfaces when a stage eats spend out of proportion
-- to the leads it returns. One row per funnel_stage (Conversion / Retargeting / Traffic).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.by_stage` AS
WITH stage AS (
  SELECT
    funnel_stage,
    SUM(spend)       AS spend,
    SUM(leads)       AS leads,
    SUM(impressions) AS impressions,
    SUM(link_clicks) AS link_clicks,
    SUM(landing_page_views) AS landing_page_views,
    SUM(reach)       AS reach
  FROM `bidbrain-analytics.client_geocon.geocon_daily`
  GROUP BY funnel_stage
),
totals AS (
  SELECT SUM(spend) AS total_spend, SUM(leads) AS total_leads FROM stage
)
SELECT
  s.funnel_stage,
  s.spend,
  s.leads,
  s.impressions,
  s.link_clicks,
  s.landing_page_views,
  s.reach,
  s.spend / NULLIF(t.total_spend, 0) AS spend_share,
  s.leads  / NULLIF(t.total_leads, 0) AS lead_share,
  s.spend / NULLIF(s.leads, 0)        AS cpl,
  s.link_clicks / NULLIF(s.impressions, 0) AS ctr,
  s.spend / NULLIF(s.impressions, 0) * 1000 AS cpm,
  s.impressions / NULLIF(s.reach, 0)       AS frequency
FROM stage s
CROSS JOIN totals t
ORDER BY s.spend DESC