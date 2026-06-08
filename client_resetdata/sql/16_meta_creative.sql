-- ResetData — Meta delivery by creative (the creative-mix chart on the Paid Media tab).
-- Meta carries a creative dimension (creative_title / creative_body / creative_id, ~18 creatives,
-- surfaced as creative_name in stg_meta); group by it so stakeholders can see which creatives ran
-- and how they delivered. Top by impressions. Outer WHERE for the delivering filter (see 13).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.meta_creative` AS
WITH agg AS (
  SELECT
    creative_name,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(link_clicks) AS link_clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions
  FROM `bidbrain-analytics.client_resetdata.stg_meta`
  GROUP BY creative_name
)
SELECT * FROM agg
WHERE imps > 0
ORDER BY imps DESC;
