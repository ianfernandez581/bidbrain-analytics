-- 11_stg_ga4: the Geocon slice of the SHARED raw_windsor.perf_ga4 table (Google Analytics 4,
-- session-acquisition grain: property x date x source/medium/campaign/channel-group).
--
-- Added 2026-08-31, the day the "connect Google Analytics" blocker cleared: two Geocon GA4
-- properties are now connected to the Windsor connector -
--     550962241  "GEOCON"          - the geocon.com.au brand site (created ~2026-08-21)
--     551838402  "Gatewaybraddon"  - the campaign landing site    (created ~2026-08-27)
-- Both properties are DAYS old, so history genuinely starts late August 2026; that is the full
-- history, not a gap.
--
-- THE PROPERTY NAMES DO NOT TELL YOU WHICH DEVELOPMENT THE TRAFFIC BELONGS TO. The property
-- NAMED "Gatewaybraddon" carries almost exclusively NORTHBOURNE GATEWAY campaign traffic
-- (verified 2026-08-31: 3,225 Paid Social sessions from the 0201_GG_* Meta campaigns, 508
-- Display sessions from the 0201_geocon_ngw558_* Trade Desk lines, 99 Paid Search sessions from
-- 0201_Geocon_NGW558_National_Search*) - Braddon sits on Northbourne Avenue and the landing site
-- serves the new development. So the DEVELOPMENT is resolved from the SESSION CAMPAIGN NAME via
-- the same seed_property_map tokens every other geocon staging view uses (first match by seq,
-- catch-all excluded), and the site label stays purely descriptive. Non-campaign traffic
-- ((organic) / (direct) / (referral) / (not set)) resolves to NULL - it belongs to the SITE, not
-- to a development, and nothing here may guess otherwise.
--
-- SOURCE IS WINDSOR, NOT DTS, and not by preference: GA4 DTS transfers for both properties were
-- created 2026-08-31 and FAIL on "User does not have permission to access the Google Analytics
-- property" - ian@100.digital (the DTS credential) has no GA4 access; the Windsor connection was
-- authorised by a different Google login. The failed DTS configs are left in place ON PURPOSE:
-- they self-heal the day the client grants ian@100.digital Viewer on the two properties, and this
-- view can then move to the DTS-first / Windsor-fallback pattern (the VMCH precedent). Until
-- then raw_windsor.perf_ga4 is kept fresh by the scheduled windsor-ga4-ingest job (pinned to
-- these two properties via GA4_ACCOUNTS - see scripts/deploy_ingest_jobs.ps1).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_ga4` AS
WITH map AS (
  -- Catch-all (empty-pattern) row excluded: campaign traffic must match a development by name or
  -- stay NULL. Same rule as 07_stg_linkedin / 08_stg_ttd / 09_stg_google_ads.
  SELECT seq, property_key, LOWER(match_pattern) AS pat
  FROM `bidbrain-analytics.client_geocon.seed_property_map`
  WHERE COALESCE(match_pattern, '') != ''
),
base AS (
  SELECT * FROM `bidbrain-analytics.raw_windsor.perf_ga4`
  WHERE property_id IN ('550962241', '551838402')
),
names AS (
  SELECT DISTINCT session_campaign_name AS nm FROM base
  WHERE COALESCE(session_campaign_name, '') NOT IN ('', '(not set)', '(organic)', '(direct)', '(referral)')
),
nm_rank AS (
  SELECT n.nm, m.property_key, ROW_NUMBER() OVER (PARTITION BY n.nm ORDER BY m.seq) AS rn
  FROM names n, map m
  WHERE EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(LOWER(n.nm), TRIM(tok)) > 0)
),
nm_map AS (SELECT nm, property_key FROM nm_rank WHERE rn = 1)
SELECT
  b.metric_date                              AS date,
  b.property_id,
  -- Descriptive SITE label (the GA4 property's own identity, prettified). NOT a development.
  CASE b.property_id
    WHEN '550962241' THEN 'Geocon brand site'
    WHEN '551838402' THEN 'Gateway Braddon site'
    ELSE COALESCE(b.account_name, b.property_id)
  END                                        AS site,
  COALESCE(b.session_default_channel_group, 'Unassigned') AS channel_group,
  b.session_source                           AS source,
  b.session_medium                           AS medium,
  b.session_campaign_name                    AS campaign,
  -- The development whose CAMPAIGN drove the session; NULL for organic/direct/unmatched traffic.
  nm.property_key                            AS property,
  b.sessions,
  b.engaged_sessions,
  b.total_users,
  b.new_users,
  b.screen_page_views,
  b.user_engagement_duration,
  b.conversions
FROM base b
LEFT JOIN nm_map nm ON b.session_campaign_name = nm.nm
