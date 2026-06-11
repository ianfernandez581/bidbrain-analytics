-- STT GDC — staged GA4 website analytics, now sourced DIRECTLY from Snowflake
-- (raw_snowflake.google_analytics_apac_all, property 318963196 = "STT GDC Web All"),
-- replacing the Windsor perf_ga4 source. Compatibility shim: emits the SAME column
-- names the downstream rollups (04-17) expect, so nothing else in sql/ changes.
-- Source is EVENT-grained (one row per day x country x channel x source x city x event),
-- and SESSIONS repeats on every event row, so session/user metrics are taken ONLY from
-- the per-session events (session_start / first_visit) to avoid multiplying by event count.
-- engaged_sessions is derived from the user_engagement event (see below); engagement
-- DURATION is still absent upstream (NULL -> dashboard "—" for avg-engagement only).
-- "market" is the visitor COUNTRY_NAME, normalized to the canonical APAC labels the
-- paid platforms emit (stg_google / stg_dv360 map 'KR' -> 'Korea'). GA4 spells Korea
-- "South Korea", which would otherwise fail the dashboard's APAC_MARKETS whitelist and
-- silently drop all Korea website sessions; the other 8 APAC markets already match.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_ga4` AS
SELECT
  DATE(DAY) AS metric_date,
  IF(COUNTRY_NAME = 'South Korea', 'Korea',
     COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')) AS account_name,
  IF(COUNTRY_NAME = 'South Korea', 'Korea',
     COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')) AS market,
  COALESCE(NULLIF(CHANNEL_GROUPING, ''), '(not set)') AS channel_group,
  CASE
    WHEN CHANNEL_GROUPING IN ('Paid Search','Paid Social','Paid Other','Cross-network','Display') THEN 'Paid'
    WHEN CHANNEL_GROUPING LIKE 'Organic%'      THEN 'Organic'
    WHEN CHANNEL_GROUPING = 'Direct'           THEN 'Direct'
    WHEN CHANNEL_GROUPING IN ('Referral','Email') THEN 'Referral'
    ELSE 'Other'
  END AS channel_bucket,
  -- SESSION_SOURCES (plural) is the STRING source; SESSION_SOURCE (singular) is an
  -- unrelated INT64 upstream, so it is NOT a usable fallback here.
  COALESCE(NULLIF(SESSION_SOURCES, ''), '(not set)') AS session_source_medium,
  SUM(IF(EVENT_NAME = 'session_start', SESSIONS, 0))    AS sessions,
  -- engaged_sessions: GA4 fires a user_engagement event on engaged sessions, so the
  -- SESSIONS value on those rows = count of sessions with engagement — the standard
  -- proxy for GA4 "engaged sessions" (~339,921 over 2025-06-01..2026-05-30).
  SUM(IF(EVENT_NAME = 'user_engagement', SESSIONS, 0)) AS engaged_sessions,
  SUM(IF(EVENT_NAME = 'session_start', TOTAL_USERS, 0)) AS total_users,
  SUM(IF(EVENT_NAME = 'first_visit',   NEW_USERS, 0))   AS new_users,
  SUM(IF(EVENT_NAME = 'page_view',     EVENT_COUNT, 0)) AS screen_page_views,
  CAST(NULL AS NUMERIC)                                 AS user_engagement_duration,
  SUM(IF(EVENT_NAME IN ('contact_submit_success','generate_lead','newsletter_subscribe_success'), KEY_EVENTS, 0)) AS conversions
FROM `bidbrain-analytics.raw_snowflake.google_analytics_apac_all`
WHERE PROPERTY_ID = '318963196'
GROUP BY ALL;
