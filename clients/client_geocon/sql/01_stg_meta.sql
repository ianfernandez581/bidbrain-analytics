-- 01_stg_meta: filter raw_windsor.perf_meta to Geocon campaigns, daily x campaign x adset x ad grain.
-- This is the client's slice + the per-row funnel_stage classification. The raw layer IS
-- raw_windsor.perf_meta (Windsor-sourced, self-refreshing) -- this is NOT Snowflake.
-- Scope = ad account AND campaign prefix, BOTH required (2026-08-06): perf_meta is a SHARED
-- table carrying six Meta ad accounts incl. other agencies', so the account_id pins the slice
-- to the 100% Digital - Clients account (act 3754165911553001); and that account hosts SEVERAL
-- 100-digital clients (geocon, bellshakespeare, nextsmile), so the prefix is still needed to
-- split them. The prefix test runs on the name with any leading BRIEF NUMBER stripped
-- ('0201_Geocon_NGW558_...' -> 'Geocon_NGW558_...'), which still pins the slice to Geocon while
-- surviving the numbering Geocon's agency now puts on every Northbourne campaign (confirmed on
-- its live Trade Desk and Google Ads lines, 2026-08-27). A bare STARTS_WITH(campaign_name,
-- 'Geocon_') would drop 100% of Northbourne's Meta delivery SILENTLY: the rows never reach the
-- property map below, so the export job's Unmapped WARNING cannot fire for them either. This is
-- the repo-wide rule in md/AGENTS.md -- campaign names are NOT stable keys, and STARTS_WITH is
-- the shape that breaks outright on a prefix. Normalising also lets future Geocon developments
-- (e.g. The Irving) flow in automatically and is immune to the trailing-space quirk in
-- 'Geocon_Traffic_MayJune 2026'.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_meta` AS
-- PROPERTY MAP JOIN (client_schneider seed_campaign_map pattern, de-correlated). BigQuery cannot
-- run the map as a correlated scalar subquery, so it is resolved exactly as schneider's idOf()
-- replica does: rank every (campaign x matching map row) by `seq` and keep rn=1. The catch-all row
-- has an EMPTY pattern at the highest seq, so every campaign matches at least one row and the join
-- can never drop delivery.
WITH map AS (
  SELECT seq, property_key, LOWER(COALESCE(match_pattern, '')) AS pat
  FROM `bidbrain-analytics.client_geocon.seed_property_map`
),
base AS (
  SELECT * FROM `bidbrain-analytics.raw_windsor.perf_meta`
  WHERE account_id = '3754165911553001'   -- 100% Digital - Clients
    AND STARTS_WITH(REGEXP_REPLACE(TRIM(campaign_name), r'^[0-9]+_', ''), 'Geocon_')
),
camps AS (SELECT DISTINCT TRIM(campaign_name) AS cname FROM base),
camp_rank AS (
  SELECT c.cname, m.property_key,
         ROW_NUMBER() OVER (PARTITION BY c.cname ORDER BY m.seq) AS rn
  FROM camps c, map m
  WHERE m.pat = ''
     OR EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(LOWER(c.cname), TRIM(tok)) > 0)
),
camp_map AS (SELECT cname, property_key FROM camp_rank WHERE rn = 1)
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
  cm.property_key                                                      AS property
FROM base b
JOIN camp_map cm ON TRIM(b.campaign_name) = cm.cname