-- City Perfume — Meta creative performance x DAY (range-aware source for the creative-mix donut
-- and the top-creative gallery). One row per creative_id x day, carrying the (day-invariant)
-- creative metadata via ANY_VALUE plus the daily delivery sums. The dashboard clips to the range,
-- re-aggregates per creative_id, then rebuilds the mix donut and the top gallery over the window.
-- campaign_name is carried so the Campaign multi-select still applies. purchases /
-- purchase_value_claimed are Meta-CLAIMED (never in the blended headline); roas_claimed / ctr
-- derived in the dashboard. Day rows are sparse (only days a creative delivered).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.meta_creative_daily` AS
SELECT
  metric_date                         AS day,
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
  SUM(purchases)                      AS purchases,
  SUM(revenue_claimed)                AS purchase_value_claimed,
  SUM(thruplays)                      AS thruplays
FROM `bidbrain-analytics.client_cityperfume.stg_meta`
GROUP BY day, creative_id
HAVING spend_aud > 0 OR imps > 0   -- references the aggregated SELECT aliases (not SUM(SUM(...)))
ORDER BY day, spend_aud DESC;
