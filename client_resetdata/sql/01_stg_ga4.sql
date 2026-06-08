-- ResetData — staged GA4 website analytics (the OUTCOME of the paid media).
--
-- Source raw_ga4.perf_ga4 is ALREADY at Traffic-Acquisition grain (one row per
-- day x session_source_medium x channel x campaign), with session columns sitting
-- right on the row — so this is a PLAIN filter + channel_bucket CASE, NOT the
-- Snowflake event-grained reconstruction client_STT's stg_ga4 needed. The ResetData
-- slice is client_slug = 'reset-data' (account_name = 'Reset Data').
--
-- ResetData is B2B: total_revenue / transactions are ~0 upstream (verified), so no
-- revenue columns are carried — `conversions` (GA4 key events) is the outcome metric.
-- AU-only, so no market/country dimension (drop STT's COUNTRY split entirely).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_ga4` AS
SELECT
  metric_date,
  COALESCE(NULLIF(session_default_channel_group, ''), '(not set)') AS channel_group,
  CASE
    WHEN session_default_channel_group IN ('Paid Search','Paid Social','Paid Other','Cross-network','Display') THEN 'Paid'
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
  user_engagement_duration,
  conversions
FROM `bidbrain-analytics.raw_ga4.perf_ga4`
WHERE client_slug = 'reset-data';
