-- LQAIDC creative performance — one row per platform × country × concept × format × creative, whole
-- flight. Backs the Creative tab. LinkedIn concepts are the 3 ad-title messages (single-image
-- Sponsored Content); Trade Desk concepts are the 4 display messages × 3 banner sizes.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.creative` AS
WITH u AS (
  SELECT platform, country, concept, creative_format, creative_name, imps, clicks, spend_aud
  FROM `bidbrain-analytics.client_schneiderlqai.stg_linkedin`
  UNION ALL
  SELECT platform, country, concept, creative_format, creative_name, imps, clicks, spend_aud
  FROM `bidbrain-analytics.client_schneiderlqai.stg_tradedesk`
)
SELECT
  platform,
  country,
  concept,
  creative_format,
  creative_name,
  SUM(imps)                                AS imps,
  SUM(clicks)                              AS clicks,
  SUM(spend_aud)                           AS spend_aud
FROM u
GROUP BY platform, country, concept, creative_format, creative_name;
