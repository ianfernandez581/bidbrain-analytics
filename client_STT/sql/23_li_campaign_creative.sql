-- STT GDC — LinkedIn delivery by campaign × creative type, for the Campaign-filtered
-- creative-mix donut on the Paid Media tab. Reads stg_linkedin directly (creative_type,
-- video_views and engagements live there, not in the unified stg_ad_delivery). cost_usd
-- already holds SGD. The dashboard sums the selected LinkedIn campaigns per creative type.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.li_campaign_creative` AS
WITH agg AS (
  SELECT
    campaign_name AS campaign,
    creative_type,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(cost_usd)    AS cost_usd,
    SUM(video_views) AS video_views,
    SUM(engagements) AS engagements
  FROM `bidbrain-analytics.client_stt.stg_linkedin`
  GROUP BY campaign, creative_type
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR cost_usd > 0
ORDER BY imps DESC;
