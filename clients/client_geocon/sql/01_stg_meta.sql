-- 01_stg_meta: filter raw_windsor.perf_meta to Geocon campaigns, daily x campaign x adset x ad grain.
-- This is the client's slice + the per-row funnel_stage classification. The raw layer IS
-- raw_windsor.perf_meta (Windsor-sourced, self-refreshing) -- this is NOT Snowflake.
-- The prefix filter STARTS_WITH('Geocon_') lets future Geocon campaigns (e.g. The Irving) flow
-- in automatically and is immune to the trailing-space quirk in 'Geocon_Traffic_MayJune 2026'.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_meta` AS
SELECT
  metric_date                                                          AS date,
  campaign_id,
  TRIM(campaign_name)                                                  AS campaign_name,
  adset_id,
  TRIM(adset_name)                                                     AS adset_name,
  ad_id,
  TRIM(ad_name)                                                        AS ad_name,
  objective,
  effective_status,
  currency,
  CAST(cost AS FLOAT64)                                                AS spend,
  impressions,
  reach,
  frequency,
  clicks,
  link_clicks,
  unique_link_clicks,
  outbound_clicks,
  landing_page_views,
  leads,
  leads_website,
  leads_onfacebook,
  unique_leads,
  cost_per_lead,
  video_3s_views,
  video_completes,
  thruplays,
  creative_id,
  creative_title,
  creative_body,
  creative_thumbnail_url,
  destination_url,
  CASE
    WHEN campaign_name LIKE '%Leads%'        THEN 'Conversion'
    WHEN campaign_name LIKE '%Retargeting%'  THEN 'Retargeting'
    WHEN campaign_name LIKE '%Traffic%'      THEN 'Traffic'
    ELSE 'Other'
  END AS funnel_stage
FROM `bidbrain-analytics.raw_windsor.perf_meta`
WHERE STARTS_WITH(campaign_name, 'Geocon_')