-- City Perfume — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per platform x campaign x day, folding the three paid channels
-- (Google paid search/PMax/shopping, Meta paid social, Trade Desk display) into the SAME
-- shape so every campaign-grained roll-up (ad_campaigns / ad_campaign_monthly /
-- ad_campaign_weekly) is built once on top of it. Mirrors STT's stg_ad_delivery.
--
-- spend_aud is AUD for all three (no FX anywhere in this client). platform_conversions /
-- platform_revenue are each platform's OWN-CLAIMED numbers (Google conversions/value,
-- Meta purchases/purchase_value, TTD multi-touch conversions/NULL value) — surfaced for
-- the per-platform "platform-claimed" panels and NEVER summed into the blended headline,
-- which divides v_sales revenue by total spend instead. creative_type is Meta-only
-- (video/image), NULL for Google/TTD. Conversions/revenue cast to FLOAT64 so the three
-- branches union cleanly (Google NUMERIC, Meta INT/NUMERIC, TTD FLOAT64).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.stg_ad_delivery` AS
SELECT
  'google'                          AS platform,
  campaign_name                     AS campaign,
  metric_date,
  CAST(NULL AS STRING)              AS creative_type,
  imps,
  clicks,
  spend_aud,
  CAST(conversions AS FLOAT64)      AS platform_conversions,
  CAST(revenue_claimed AS FLOAT64)  AS platform_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_google`
UNION ALL
SELECT
  'meta'                            AS platform,
  campaign_name                     AS campaign,
  metric_date,
  creative_type,
  imps,
  clicks,
  spend_aud,
  CAST(purchases AS FLOAT64)        AS platform_conversions,
  CAST(revenue_claimed AS FLOAT64)  AS platform_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_meta`
UNION ALL
SELECT
  'ttd'                             AS platform,
  campaign_name                     AS campaign,
  metric_date,
  CAST(NULL AS STRING)              AS creative_type,
  imps,
  clicks,
  spend_aud,
  CAST(conversions AS FLOAT64)      AS platform_conversions,
  CAST(NULL AS FLOAT64)             AS platform_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_ttd`;
