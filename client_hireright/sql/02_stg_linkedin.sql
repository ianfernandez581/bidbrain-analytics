-- HireRight - staged LinkedIn Ads (paid social / air-cover). Audience is global
-- (NAM/EMEA/APAC combined) with no usable geo, so market is a flat 'Global'.
--
-- The HireRight LinkedIn filter lives here once: ACCOUNT_NAME starts with "HireRight"
-- (case-insensitive). BigQuery has no ILIKE, so the brief's `ILIKE 'HireRight%'` is
-- expressed as LOWER(...) LIKE 'hireright%'. LinkedIn has NO currency column; the
-- account is _USD, so spend is USD as-is. The brief's AUD guard
-- (`LIKE '%\_AUD' ESCAPE '\'`) - invalid in BigQuery - is expressed as
-- ENDS_WITH(ACCOUNT_NAME, '_AUD') at the shared FX constant (FX_AUD_USD = 0.65,
-- see stg_dv360 header). cost_usd holds USD.
--
-- CREATIVE_TYPE is labelled for the creative-mix chart: 'STANDARD' = single image,
-- NULL/'' = video / other, anything else passes through. VIDEO_* and the lead-gen
-- fields are carried so the dashboard can build the engagement funnel.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_linkedin` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  'Global'                                 AS market,
  CASE
    WHEN CREATIVE_TYPE = 'STANDARD' THEN 'Single Image'
    WHEN CREATIVE_TYPE IS NULL OR CREATIVE_TYPE = '' THEN 'Video / Other'
    ELSE CREATIVE_TYPE
  END                                      AS creative_type,
  IMPRESSIONS                              AS imps,
  CLICKS                                   AS clicks,
  -- _AUD account -> USD @0.65, else already USD. cost_usd holds USD.
  CASE WHEN ENDS_WITH(ACCOUNT_NAME, '_AUD') THEN COSTS * 0.65 ELSE COSTS END AS cost_usd,
  VIDEO_VIEWS                              AS video_views,
  VIDEO_STARTS                             AS video_starts,
  VIDEO_COMPLETIONS                        AS video_completions,
  ENGAGEMENTS                              AS engagements,
  LEADS                                    AS leads,
  LEAD_FORM_OPENS                          AS lead_form_opens,
  LINK_CLICKS                              AS link_clicks,
  ACTION_CLICKS                            AS action_clicks
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%';
