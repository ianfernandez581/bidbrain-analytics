-- VMCH — staged GA4 website analytics.
--
-- Source raw_ga4.perf_ga4 is at session-source-grain (one row per day ×
-- session_source_medium × channel × campaign), with session columns on the row.
-- This is a straightforward filter + channel_bucket CASE.
-- VMCH is AU-only; there is no geo/country column in the source, so no market
-- dimension — the dashboard omits the Country filter for GA4.
-- Conversions are the GA4 key events metric.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ga4` AS
SELECT
  metric_date,
  COALESCE(NULLIF(session_default_channel_group, ''), '(not set)') AS channel_group,
  CASE
    WHEN session_default_channel_group IN ('Paid Search','Paid Social','Paid Other','Paid Video','Cross-network','Display') THEN 'Paid'
    WHEN session_default_channel_group LIKE 'Organic%'        THEN 'Organic'
    WHEN session_default_channel_group = 'Direct'             THEN 'Direct'
    WHEN session_default_channel_group IN ('Referral','Email') THEN 'Referral'
    ELSE 'Other'
  END AS channel_bucket,
  COALESCE(NULLIF(session_source_medium, ''), '(not set)')   AS source_medium,
  COALESCE(NULLIF(session_campaign_name, ''), '(not set)')   AS campaign,
  sessions,
  engaged_sessions,
  total_users,
  new_users,
  screen_page_views,
  CAST(user_engagement_duration AS NUMERIC) AS user_engagement_duration,
  CAST(conversions AS NUMERIC)              AS conversions
FROM `bidbrain-analytics.raw_ga4.perf_ga4`
WHERE account_name = 'VMCH Website - GA4';