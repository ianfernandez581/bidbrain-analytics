-- City Perfume — Meta creative performance (Paid Media tab). One row per creative_id
-- (~124), carrying the derived creative_type (video/image), objective, thumbnail/title for
-- the gallery, and spend/imps/clicks/purchases/purchase_value. The dashboard aggregates
-- creative_type for the mix donut and shows the top creatives by spend with thumbnails.
-- purchases/purchase_value are Meta-CLAIMED (shown as such, never in the blended headline).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.meta_creative` AS
SELECT
  creative_id,
  ANY_VALUE(creative_type)            AS creative_type,
  ANY_VALUE(objective)                AS objective,
  ANY_VALUE(creative_title)           AS creative_title,
  ANY_VALUE(creative_thumbnail_url)   AS creative_thumbnail_url,
  ANY_VALUE(ad_name)                  AS ad_name,
  ANY_VALUE(campaign_name)            AS campaign_name,
  SUM(spend_aud)                      AS spend_aud,
  SUM(imps)                           AS imps,
  SUM(clicks)                         AS clicks,
  SAFE_DIVIDE(SUM(clicks), SUM(imps)) AS ctr,
  SUM(purchases)                      AS purchases,
  SUM(revenue_claimed)                AS purchase_value_claimed,
  SAFE_DIVIDE(SUM(revenue_claimed), SUM(spend_aud)) AS roas_claimed,
  SUM(thruplays)                      AS thruplays
FROM `bidbrain-analytics.client_cityperfume.stg_meta`
GROUP BY creative_id
HAVING spend_aud > 0 OR imps > 0   -- references the aggregated SELECT aliases (not SUM(SUM(...)))
ORDER BY spend_aud DESC;
