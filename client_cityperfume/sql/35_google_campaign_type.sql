-- City Perfume — Google Ads by campaign_type (Paid Media tab). PERFORMANCE_MAX dominates
-- spend (~61%), then SHOPPING / SEARCH. roas_claimed is Google-claimed conversions_value
-- over spend (context, never the blended headline). All AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.google_campaign_type` AS
SELECT
  campaign_type,
  SUM(spend_aud)                                    AS spend_aud,
  SUM(imps)                                         AS imps,
  SUM(clicks)                                       AS clicks,
  SAFE_DIVIDE(SUM(clicks), SUM(imps))               AS ctr,
  SUM(conversions)                                  AS conversions,
  SUM(revenue_claimed)                              AS revenue_claimed,
  SAFE_DIVIDE(SUM(revenue_claimed), SUM(spend_aud)) AS roas_claimed
FROM `bidbrain-analytics.client_cityperfume.stg_google`
GROUP BY campaign_type
ORDER BY spend_aud DESC;
