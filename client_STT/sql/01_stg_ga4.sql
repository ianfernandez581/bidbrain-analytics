-- STT GDC — staged GA4 website analytics (the "what happened on the site" layer).
--
-- This is the ONE place the STT GA4 filter lives: the 11 "STT GDC Web *" GA4
-- properties (one property_id each — "All" is the main corporate site, the rest
-- are the regional sites + a Global property). Everything downstream reads this
-- view, so the account list never has to be repeated.
--
-- Grain: one row per (property/market × date × session source-medium × default
-- channel group) — straight off raw_windsor.perf_ga4. Derives a clean market
-- label and a coarse channel BUCKET (Paid / Organic / Direct / Referral / Other)
-- so the "effect of ads on traffic" story can split paid from the rest.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_ga4` AS
SELECT
  metric_date,
  account_name,
  CASE account_name
    WHEN 'STT GDC Web All'         THEN 'All Sites'
    WHEN 'STT GDC Web Global'      THEN 'Global'
    WHEN 'STT GDC Web Singapore'   THEN 'Singapore'
    WHEN 'STT GDC Web Malaysia'    THEN 'Malaysia'
    WHEN 'STT GDC Web India'       THEN 'India'
    WHEN 'STT GDC Web Philippines' THEN 'Philippines'
    WHEN 'STT GDC Web Indonesia'   THEN 'Indonesia'
    WHEN 'STT GDC Web Thailand'    THEN 'Thailand'
    WHEN 'STT GDC Web Vietnam'     THEN 'Vietnam'
    WHEN 'STT GDC Web Japan'       THEN 'Japan'
    WHEN 'STT GDC Web Korea'       THEN 'Korea'
    ELSE 'Other'
  END AS market,
  session_default_channel_group AS channel_group,
  CASE
    WHEN session_default_channel_group IN
         ('Paid Search','Paid Social','Paid Other','Cross-network','Display') THEN 'Paid'
    WHEN session_default_channel_group LIKE 'Organic%'                         THEN 'Organic'
    WHEN session_default_channel_group = 'Direct'                             THEN 'Direct'
    WHEN session_default_channel_group IN ('Referral','Email')                THEN 'Referral'
    ELSE 'Other'
  END AS channel_bucket,
  session_source_medium,
  sessions,
  engaged_sessions,
  total_users,
  new_users,
  screen_page_views,
  user_engagement_duration,
  conversions
FROM `bidbrain-analytics.raw_windsor.perf_ga4`
WHERE account_name IN (
  'STT GDC Web Japan', 'STT GDC Web Korea', 'STT GDC Web Singapore',
  'STT GDC Web Indonesia', 'STT GDC Web Thailand', 'STT GDC Web Vietnam',
  'STT GDC Web Global', 'STT GDC Web Malaysia', 'STT GDC Web Philippines',
  'STT GDC Web All', 'STT GDC Web India'
);
