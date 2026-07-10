-- Schneider Electric — staged GA4 website analytics. SHIPPED DISABLED (returns 0 rows until the SE
-- GA4 property id is set below).
--
-- SOURCE: the native GA4 Data Transfer bridge `raw_ga4.perf_ga4` (session-grain: day × session
-- source/medium × campaign × channel). This is the DIRECT read-only path Calvin is arranging — once
-- Schneider grant our account Viewer access and we add their property to ingest/dts_data_pull, the
-- property's rows appear here automatically. Mirrors client_vmch/sql/01_stg_ga4.sql (WHOLE-SITE, single
-- market — perf_ga4 carries NO geo/country dimension, so GA4 here is the whole property, not split by
-- market; Schneider is AU/NZ, so this reads as AU/NZ website traffic).
--
-- GRAIN CAVEAT (perf_ga4): the DTS TrafficAcquisition report populates sessions / engaged_sessions /
-- event_count / conversions (= key events) / total_revenue. total_users / new_users / screen_page_views /
-- user_engagement_duration come back NULL from DTS (they live in other GA4 reports at incompatible
-- grains) — so those KPIs read '-' until a Windsor GA4 pull is added for this property.
--
-- TO ENABLE: replace REPLACE_WITH_SE_GA4_PROPERTY_ID with the real numeric SE GA4 property id (GA4
--   Admin → Property Settings), add that id to ingest/dts_data_pull/create_views.py PROPERTY_NAMES and
--   create its DTS transfer, reapply views, then run the job with FORCE_REBUILD=1.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_ga4` AS
SELECT
  metric_date,
  COALESCE(NULLIF(session_default_channel_group, ''), '(not set)') AS channel_group,
  CASE
    WHEN session_default_channel_group IN ('Paid Search','Paid Social','Paid Other','Paid Video','Cross-network','Display') THEN 'Paid'
    WHEN session_default_channel_group LIKE 'Organic%'         THEN 'Organic'
    WHEN session_default_channel_group = 'Direct'              THEN 'Direct'
    WHEN session_default_channel_group IN ('Referral','Email') THEN 'Referral'
    ELSE 'Other'
  END AS channel_bucket,
  COALESCE(NULLIF(session_source_medium, ''), '(not set)')  AS source_medium,
  COALESCE(NULLIF(session_campaign_name, ''), '(not set)')  AS campaign,
  CAST(sessions AS INT64)                    AS sessions,
  CAST(engaged_sessions AS INT64)            AS engaged_sessions,
  CAST(total_users AS INT64)                 AS total_users,
  CAST(new_users AS INT64)                   AS new_users,
  CAST(screen_page_views AS INT64)           AS screen_page_views,
  CAST(user_engagement_duration AS NUMERIC)  AS user_engagement_duration,
  CAST(conversions AS NUMERIC)               AS conversions
FROM `bidbrain-analytics.raw_ga4.perf_ga4`
WHERE property_id IN ('REPLACE_WITH_SE_GA4_PROPERTY_ID');   -- <<< placeholder: matches no rows until set
