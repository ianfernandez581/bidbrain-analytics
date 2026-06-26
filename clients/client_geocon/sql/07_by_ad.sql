-- 07_by_ad: per-ad (and adset) metric rows, for winner/loser + creative drill.
-- One row per (campaign x adset x ad). creative metadata included so the UI can show the
-- creative title/body and thumbnail.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.by_ad` AS
SELECT
  campaign_name,
  funnel_stage,
  adset_name,
  ad_name,
  creative_id,
  creative_title,
  creative_body,
  creative_thumbnail_url,
  currency,
  SUM(spend)              AS spend,
  SUM(impressions)        AS impressions,
  SUM(reach)              AS reach,
  SUM(clicks)             AS clicks,
  SUM(link_clicks)        AS link_clicks,
  SUM(landing_page_views) AS landing_page_views,
  SUM(leads)              AS leads,
  SUM(video_3s_views)     AS video_3s_views,
  SUM(video_completes)    AS video_completes,
  -- derived (divide-by-zero safe)
  SUM(link_clicks) / NULLIF(SUM(impressions), 0)        AS ctr,
  SUM(clicks)      / NULLIF(SUM(impressions), 0)        AS ctr_all,
  SUM(spend)       / NULLIF(SUM(impressions), 0) * 1000 AS cpm,
  SUM(spend)       / NULLIF(SUM(link_clicks), 0)        AS cpc,
  SUM(spend)       / NULLIF(SUM(leads), 0)              AS cpl,
  SUM(spend)       / NULLIF(SUM(landing_page_views), 0) AS cost_per_lpv,
  SUM(impressions) / NULLIF(SUM(reach), 0)              AS frequency
FROM `bidbrain-analytics.client_geocon.geocon_daily`
GROUP BY campaign_name, funnel_stage, adset_name, ad_name, creative_id,
         creative_title, creative_body, creative_thumbnail_url, currency