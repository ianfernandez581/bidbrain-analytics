-- Schneider Electric — LinkedIn delivery by creative type (whole flight). cost_aud is AUD.
-- Powers the creative-mix donut on Channel Comparison / Delivery. Mirrors client_STT/sql/09.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.li_creative` AS
SELECT
  creative_type,
  SUM(imps)              AS imps,
  SUM(clicks)            AS clicks,
  SUM(cost_aud)          AS cost_aud,
  SUM(video_views)       AS video_views,
  SUM(video_starts)      AS video_starts,
  SUM(video_completions) AS video_completions,
  SUM(engagements)       AS engagements
FROM `bidbrain-analytics.client_schneider.stg_linkedin`
GROUP BY creative_type
ORDER BY imps DESC;
