-- Schneider Electric — LinkedIn delivery by campaign × creative type, for the Campaign-filtered
-- creative-mix donut. Reads stg_linkedin directly (creative_type / video / engagements live
-- there, not in the unified stg_ad_delivery). cost_aud already holds AUD. The dashboard sums the
-- selected LinkedIn campaigns per creative type. Mirrors client_STT/sql/23.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.li_campaign_creative` AS
WITH agg AS (
  SELECT
    campaign_name          AS campaign,
    creative_type,
    SUM(imps)              AS imps,
    SUM(clicks)            AS clicks,
    SUM(cost_aud)          AS cost_aud,
    SUM(video_views)       AS video_views,
    SUM(video_starts)      AS video_starts,
    SUM(video_completions) AS video_completions,
    SUM(engagements)       AS engagements
  FROM `bidbrain-analytics.client_schneider.stg_linkedin`
  GROUP BY campaign, creative_type
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR cost_aud > 0
ORDER BY imps DESC;
