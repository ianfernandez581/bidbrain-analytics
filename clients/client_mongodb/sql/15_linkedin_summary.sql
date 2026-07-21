-- MongoDB - LinkedIn whole-flight summary (one row). Additive base only; the job/dashboard
-- derive CTR/CPC/CPM/CPL from these sums. spend_usd is the headline (USD); spend_native +
-- currency are kept so the native figure can be shown too. Empty until the Windsor account is
-- readable (see 14_stg_linkedin.sql).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.linkedin_summary` AS
SELECT
  COUNT(DISTINCT campaign_id)  AS campaigns,
  COUNT(DISTINCT creative_id)  AS creatives,
  MIN(metric_date)             AS start_date,
  MAX(metric_date)             AS end_date,
  ANY_VALUE(currency)          AS currency,
  SUM(imps)                    AS imps,
  SUM(clicks)                  AS clicks,
  SUM(spend_usd)               AS spend_usd,
  SUM(spend_native)            AS spend_native,
  SUM(reach)                   AS reach,
  SUM(landing_page_clicks)     AS landing_page_clicks,
  SUM(leads)                   AS leads,
  SUM(lead_form_opens)         AS lead_form_opens,
  SUM(engagements)             AS engagements,
  SUM(video_views)             AS video_views,
  SUM(video_completions)       AS video_completions,
  SUM(ext_website_conversions) AS ext_website_conversions
FROM `bidbrain-analytics.client_mongodb.stg_linkedin`;
