-- 01_stg_meta: filter raw_windsor.perf_meta to Geocon campaigns, daily x campaign x adset x ad grain.
-- This is the client's slice + the per-row funnel_stage classification. The raw layer IS
-- raw_windsor.perf_meta (Windsor-sourced, self-refreshing) -- this is NOT Snowflake.
-- Scope = ad account AND campaign prefix, BOTH required (2026-08-06): perf_meta is a SHARED
-- table carrying six Meta ad accounts incl. other agencies', so the account_id pins the slice
-- to the 100% Digital - Clients account (act 3754165911553001); and that account hosts SEVERAL
-- 100-digital clients (geocon, bellshakespeare, nextsmile), so the prefix is still needed to
-- split them.
--
-- ***THE PREFIX IS A SET, NOT A LITERAL (2026-08-31).*** Northbourne Gateway's Meta campaigns are
-- named `0201_GG_ACT Northboune Gateway_statics_CNV` - a brief number, then **GG** for Geocon
-- Group, NOT the `Geocon_` that Gateway Braddon uses. A bare STARTS_WITH('Geocon_') returned FALSE
-- for every one of them, so 100% of Northbourne's Meta delivery was dropped here: ~221k impressions
-- across 6 live campaigns on the plan's LARGEST line (seq 9, A$90,000). Silent, because a row
-- excluded at this gate never reaches the property map, so the export's `Unmapped` warning cannot
-- fire for it either - the dashboard just reads zero and looks healthy.
--
-- An earlier fix stripped a leading `^[0-9]+_` before the same `Geocon_` test and was signed off as
-- "a strict no-op, 0 newly admitted campaigns". **That no-op WAS the bug**: it was written against
-- the Trade Desk / Google Ads naming (`0201_Geocon_NGW558_*`), which Meta does not follow, so it
-- verified green while still admitting nothing. When a scope fix is meant to ADMIT rows, "no change"
-- is a FAILURE, not a pass - assert the new names are in, not merely that the old ones still are.
--
-- Both spellings are now accepted after the brief number is stripped. `Cairns Awareness` (another
-- client on this same account) matches neither, so the split still holds and the property map's
-- catch-all ELSE stays safe.
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
    AND REGEXP_CONTAINS(REGEXP_REPLACE(TRIM(campaign_name), r'^[0-9]+_', ''),
                        r'^(Geocon_|GG_)')   -- see header: GG = Geocon Group
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