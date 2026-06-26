-- 02_geocon_daily: derived metrics at daily x campaign x adset x ad grain.
-- All denominators wrapped in NULLIF(_,0) so a zero never divides. These metric names are
-- the contract job/main.py reads.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.geocon_daily` AS
SELECT
  date,
  campaign_id,
  campaign_name,
  adset_id,
  adset_name,
  ad_id,
  ad_name,
  creative_id,
  creative_title,
  creative_body,
  creative_thumbnail_url,
  destination_url,
  funnel_stage,
  currency,
  spend,
  impressions,
  reach,
  COALESCE(frequency, impressions / NULLIF(reach, 0)) AS frequency,
  clicks,
  link_clicks,
  outbound_clicks,
  landing_page_views,
  leads,
  leads_website,
  unique_leads,
  video_3s_views,
  video_completes,
  thruplays,
  -- link-based efficiency (the client report quotes link CTR)
  link_clicks  / NULLIF(impressions, 0)                AS ctr,
  clicks       / NULLIF(impressions, 0)                AS ctr_all,
  spend        / NULLIF(impressions, 0) * 1000         AS cpm,
  spend        / NULLIF(link_clicks, 0)                AS cpc,
  spend        / NULLIF(leads, 0)                      AS cpl,
  spend        / NULLIF(landing_page_views, 0)         AS cost_per_lpv
FROM `bidbrain-analytics.client_geocon.stg_meta`