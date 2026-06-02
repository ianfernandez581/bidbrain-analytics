-- STT GDC — staged LinkedIn Ads (the paid-social / awareness driver).
--
-- The STT LinkedIn filter lives here once: the Transmission-run USD account
-- (STTGDC_TransmissionSG_USD), which carried the FY25-26 Always On social
-- activity Jun–Dec 2025. Spend is USD (account is "_USD"); the dashboard
-- converts to SGD with the FX constant in `kpi` / `monthly` / `weekly`.
--
-- CREATIVE_TYPE is 'STANDARD' for the single-image Sponsored Content and NULL
-- for the rest (video / other formats); label it so the creative-mix chart reads
-- cleanly.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_linkedin` AS
SELECT
  DAY AS metric_date,
  CAMPAIGN_NAME AS campaign_name,
  CASE
    WHEN CREATIVE_TYPE = 'STANDARD' THEN 'Sponsored Content'
    WHEN CREATIVE_TYPE IS NULL OR CREATIVE_TYPE = '' THEN 'Video / Other'
    ELSE CREATIVE_TYPE
  END AS creative_type,
  IMPRESSIONS AS imps,
  CLICKS AS clicks,
  COSTS AS cost_usd,
  VIDEO_VIEWS AS video_views,
  ENGAGEMENTS AS engagements,
  LEADS AS leads,
  LEAD_FORM_OPENS AS lead_form_opens
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE ACCOUNT_NAME = 'STTGDC_TransmissionSG_USD';
