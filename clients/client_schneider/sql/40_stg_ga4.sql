-- Schneider Electric — staged GA4 website analytics. SHIPPED DISABLED.
--
-- Copied from client_STT/sql/01_stg_ga4.sql, with the property filter PARAMETERISED to a
-- clearly-marked placeholder that matches NO property, so this view (and every ga4_* view
-- built on it) applies cleanly but returns ZERO rows until the SE GA4 property id(s) are known.
-- The export job gates the ga4_* JSON branches behind GA4_ENABLED (job/main.py), and the
-- dashboard's Website tab renders the "awaiting GA4 property id" stub while disabled.
--
-- TO ENABLE: (1) replace the placeholder below with the real SE GA4 PROPERTY_ID(s), e.g.
--   WHERE PROPERTY_ID IN ('123456789','987654321')
-- (2) set GA4_ENABLED = True in client_schneider/job/main.py, (3) reapply views + run the job.
--
-- Event-grained source handling is kept intact (mirrors STT): SESSIONS repeats on every event
-- row, so session/user metrics come ONLY from the per-session events (session_start /
-- first_visit); engaged_sessions from the user_engagement event; the capitalised 'Sessions'
-- pseudo-row is dropped via EVENT_NAME = LOWER(EVENT_NAME). The conversions allowlist is a
-- placeholder — confirm SE's key-event names when enabling.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_ga4` AS
SELECT
  DATE(DAY) AS metric_date,
  COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')     AS account_name,
  COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')     AS market,
  COALESCE(NULLIF(CHANNEL_GROUPING, ''), '(not set)') AS channel_group,
  CASE
    WHEN CHANNEL_GROUPING IN ('Paid Search','Paid Social','Paid Other','Cross-network','Display') THEN 'Paid'
    WHEN CHANNEL_GROUPING LIKE 'Organic%'      THEN 'Organic'
    WHEN CHANNEL_GROUPING = 'Direct'           THEN 'Direct'
    WHEN CHANNEL_GROUPING IN ('Referral','Email') THEN 'Referral'
    ELSE 'Other'
  END AS channel_bucket,
  COALESCE(NULLIF(SESSION_SOURCES, ''), '(not set)') AS session_source_medium,
  SUM(IF(EVENT_NAME = 'session_start', SESSIONS, 0))    AS sessions,
  SUM(IF(EVENT_NAME = 'user_engagement', SESSIONS, 0)) AS engaged_sessions,
  SUM(IF(EVENT_NAME = 'session_start', TOTAL_USERS, 0)) AS total_users,
  SUM(IF(EVENT_NAME = 'first_visit',   NEW_USERS, 0))   AS new_users,
  SUM(IF(EVENT_NAME = 'page_view',     EVENT_COUNT, 0)) AS screen_page_views,
  CAST(NULL AS NUMERIC)                                 AS user_engagement_duration,
  -- TODO confirm SE's GA4 key-event names — placeholder allowlist carried over from STT.
  SUM(IF(EVENT_NAME IN ('contact_submit_success','generate_lead','newsletter_subscribe_success'), KEY_EVENTS, 0)) AS conversions
FROM `bidbrain-analytics.raw_snowflake.google_analytics_apac_all`
WHERE PROPERTY_ID IN ('REPLACE_WITH_SE_GA4_PROPERTY_IDS')   -- <<< placeholder: matches no rows until set
GROUP BY ALL;
