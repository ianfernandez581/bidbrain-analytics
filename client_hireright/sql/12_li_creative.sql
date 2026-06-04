-- HireRight - LinkedIn delivery by creative type (whole flight). Carries the full
-- engagement-funnel metric set (video starts/completions, lead-form opens, leads) so
-- the dashboard can build both the creative-mix donut and the funnel. cost_usd is USD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.li_creative` AS
SELECT
  creative_type,
  SUM(imps)              AS imps,
  SUM(clicks)            AS clicks,
  SUM(cost_usd)          AS cost_usd,
  SUM(video_views)       AS video_views,
  SUM(video_starts)      AS video_starts,
  SUM(video_completions) AS video_completions,
  SUM(lead_form_opens)   AS lead_form_opens,
  SUM(leads)             AS leads,
  SUM(engagements)       AS engagements
FROM `bidbrain-analytics.client_hireright.stg_linkedin`
GROUP BY creative_type
ORDER BY imps DESC;
