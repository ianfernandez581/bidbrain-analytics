-- PropTrack (Transmission) — staged LinkedIn Ads (the always-on paid-social presence).
--
-- The LinkedIn filter lives here once: ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD'
-- (ACCOUNT_ID 510177932). Spend is native AUD (COSTS) — NO FX conversion (unlike STT's
-- stg_linkedin, which multiplied a USD account by 1.34; that logic does not exist here).
--
-- Delivery is intermittent across 2025-08 → 2026-06 (real spend in Aug/Nov/Dec'25,
-- Jan/Feb/May/Jun'26; nothing in Sep/Oct'25, Mar/Apr'26) — the monthly chart shows gaps,
-- and that is correct. IMPRESSIONS (plural) IS populated here (unlike TradeDesk).
--
-- CREATIVE_TYPE is STANDARD (single-image Sponsored Content) or VIDEO. CAMPAIGN_GROUP_NAME
-- is the objective/initiative grouping — the primary breakdown for the LinkedIn tab.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.stg_linkedin` AS
SELECT
  DAY                 AS metric_date,
  CAMPAIGN_NAME       AS campaign_name,
  CAMPAIGN_GROUP_NAME AS campaign_group,
  CASE
    WHEN CREATIVE_TYPE = 'STANDARD' THEN 'Sponsored Content (Standard)'
    WHEN CREATIVE_TYPE = 'VIDEO'    THEN 'Video'
    WHEN CREATIVE_TYPE IS NULL OR CREATIVE_TYPE = '' THEN 'Other'
    ELSE CREATIVE_TYPE
  END AS creative_type,
  IMPRESSIONS        AS imps,
  CLICKS             AS clicks,
  COSTS              AS spend_aud,             -- native AUD, no FX
  ENGAGEMENTS        AS engagements,
  VIDEO_VIEWS        AS video_views,
  VIDEO_COMPLETIONS  AS video_completions,
  CONVERSIONS        AS conversions,           -- 0 for this client (LinkedIn carries no pixel conv)
  LEADS              AS leads,
  LEAD_FORM_OPENS    AS lead_form_opens
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD';
