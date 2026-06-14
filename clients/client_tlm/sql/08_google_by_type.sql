-- TLM — Google Ads delivery by campaign_type: the e-commerce breakdown.
--
-- EDA shows three campaign_types: PERFORMANCE_MAX (7 campaigns, $13.8K spend, 4.66 ROAS),
-- SEARCH (13 campaigns, $9.3K spend, 6.08 ROAS), and SHOPPING (1 campaign, $236 spend,
-- 0 conversions). This view surfaces that split so the Google Ads tab can show the type
-- donut + table. ROAS/AOV/CPA are derived client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.google_by_type` AS
SELECT
  campaign_type,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_aud)   AS spend_aud,
  SUM(conversions) AS conversions,
  SUM(revenue)     AS revenue
FROM `bidbrain-analytics.client_tlm.stg_google`
GROUP BY campaign_type
ORDER BY spend_aud DESC;