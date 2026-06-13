-- City Perfume — Google Ads by campaign_type x DAY (range-aware source for the Paid-Media
-- campaign-type chart). Day grain; the dashboard clips + re-aggregates per type and derives
-- ctr / roas_claimed (Google-claimed conversions_value / spend — context, never the blended
-- headline) from the summed columns. All AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.google_campaign_type_daily` AS
SELECT
  metric_date           AS day,
  campaign_type,
  SUM(spend_aud)        AS spend_aud,
  SUM(imps)             AS imps,
  SUM(clicks)           AS clicks,
  SUM(conversions)      AS conversions,
  SUM(revenue_claimed)  AS revenue_claimed
FROM `bidbrain-analytics.client_cityperfume.stg_google`
GROUP BY day, campaign_type
ORDER BY day, spend_aud DESC;
