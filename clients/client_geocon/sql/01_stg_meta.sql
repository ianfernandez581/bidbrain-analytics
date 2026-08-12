-- 01_stg_meta: filter raw_windsor.perf_meta to Geocon campaigns, daily x campaign x adset x ad grain.
-- This is the client's slice + the per-row funnel_stage classification. The raw layer IS
-- raw_windsor.perf_meta (Windsor-sourced, self-refreshing) -- this is NOT Snowflake.
-- Scope = ad account AND campaign prefix, BOTH required (2026-08-06): perf_meta is a SHARED
-- table carrying six Meta ad accounts incl. other agencies', so the account_id pins the slice
-- to the 100% Digital - Clients account (act 3754165911553001); and that account hosts SEVERAL
-- 100-digital clients (geocon, bellshakespeare, nextsmile), so the prefix is still needed to
-- split them. STARTS_WITH('Geocon_') lets future Geocon campaigns (e.g. The Irving) flow in
-- automatically and is immune to the trailing-space quirk in 'Geocon_Traffic_MayJune 2026'.
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
  END AS funnel_stage,
  -- PROPERTY (the development the campaign sells). Added 2026-08-12 ahead of the Northbourne
  -- Gateway launch, and it is a SAFETY RAIL, not decoration: the account+prefix scope above
  -- deliberately lets ANY new `Geocon_` campaign flow in automatically, so without this column
  -- Northbourne's delivery would have silently merged into Gateway Braddon's KPIs the moment it
  -- started spending - inflating leads, spend and CPL on a live client dashboard with no error
  -- anywhere. The dashboard filters on this, so the two developments stay separate by default.
  --
  -- Northbourne's real campaign names are NOT known yet, so the match is deliberately broad
  -- (any of 'Northbourne' / 'NBG' / 'North Bourne', case-insensitive, anywhere in the name).
  -- CONFIRM IT the day the campaigns go live:
  --     SELECT DISTINCT campaign_name, property FROM `...client_geocon.stg_meta`;
  -- and tighten this arm if the naming turns out different. Everything that is not Northbourne
  -- stays 'Gateway Braddon' - the ELSE keeps today's three campaigns exactly where they were,
  -- so no existing number moves.
  CASE
    WHEN REGEXP_CONTAINS(campaign_name, r'(?i)north\s*bourne|nbg') THEN 'Northbourne Gateway'
    ELSE 'Gateway Braddon'
  END AS property
FROM `bidbrain-analytics.raw_windsor.perf_meta`
WHERE account_id = '3754165911553001'   -- 100% Digital - Clients
  AND STARTS_WITH(campaign_name, 'Geocon_')