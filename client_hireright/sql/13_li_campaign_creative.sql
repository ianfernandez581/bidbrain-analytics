-- HireRight - LinkedIn delivery by campaign x creative type, for the Campaign-filtered
-- creative-mix donut AND the campaign-filtered engagement funnel on the Paid Media tab.
-- Reads stg_linkedin directly (creative_type, video + lead-gen fields live there, not
-- in the unified stg_ad_delivery). cost_usd already holds USD. The dashboard sums the
-- selected LinkedIn campaigns per creative type (and folds across types for the funnel).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.li_campaign_creative` AS
WITH agg AS (
  SELECT
    campaign_name AS campaign,
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
  GROUP BY campaign, creative_type
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR cost_usd > 0
ORDER BY imps DESC;
