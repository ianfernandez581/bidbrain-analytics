-- 08_stg_ttd: the Geocon slice of the SHARED raw_windsor.perf_the_trade_desk table.
-- Added 2026-08-24 for Northbourne Gateway, whose media plan buys THREE Trade Desk lines --
-- High Impact rich media (A$40,000), Retargeting (A$12,000) and Lookalike (A$12,000), A$64,000
-- and 4.27M impressions in total at a plan CPM of A$15. Gateway Braddon is Meta-only and is
-- unaffected by this view existing.
--
-- THERE IS NO GEOCON TRADE DESK ADVERTISER IN WINDSOR YET (verified 2026-08-24: the seat carries
-- VMCH / ResetData / WEHI / TLM / Altech / ACRS / City Perfume / Qtopia / Caltex / Peaches & Cream
-- / BigAds and nothing else). This view returns ZERO ROWS today, on purpose -- it is the socket
-- the channel plugs into and the dashboard's Trade Desk lane switches itself on the first day a
-- row lands. Getting the advertiser GRANTED to the shared Windsor seat is a go-live blocker; see
-- the client README.
--
-- THE THREE LINES SHARE ONE ADVERTISER, so the media-plan line each row belongs to is resolved in
-- 10_fact_all from the ad-group / campaign name against seed_media_plan.match_pattern. Ad-group
-- name is checked FIRST (the caltex + client_schneider precedent: the tactic lives on the ad group,
-- not the campaign).
--
-- Scope is a POSITIVE match and property resolution NEVER defaults -- an unmatched Geocon row
-- lands in 'Unmapped' and the export alarms on it. See 07_stg_linkedin's header for why.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_ttd` AS
WITH map AS (
  SELECT seq, property_key, LOWER(match_pattern) AS pat
  FROM `bidbrain-analytics.client_geocon.seed_property_map`
  WHERE COALESCE(match_pattern, '') != ''
),
base AS (
  SELECT * FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
  WHERE REGEXP_CONTAINS(
          UPPER(CONCAT(IFNULL(advertiser_name,''), '|', IFNULL(campaign_name,''))),
          r'GEOCON|NGW558|NORTHBOURNE')
),
names AS (SELECT DISTINCT CONCAT(IFNULL(campaign_name,''), ' ', IFNULL(ad_group_name,'')) AS nm FROM base),
nm_rank AS (
  SELECT n.nm, m.property_key, ROW_NUMBER() OVER (PARTITION BY n.nm ORDER BY m.seq) AS rn
  FROM names n, map m
  WHERE EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(LOWER(n.nm), TRIM(tok)) > 0)
),
nm_map AS (SELECT nm, property_key FROM nm_rank WHERE rn = 1)
SELECT
  b.metric_date                                AS date,
  'Trade Desk'                                 AS channel,
  COALESCE(nm.property_key, 'Unmapped')        AS property,
  b.campaign_id,
  TRIM(b.campaign_name)                        AS campaign_name,
  b.ad_group_id                                AS adset_id,
  TRIM(b.ad_group_name)                        AS adset_name,
  b.creative_id                                AS ad_id,
  TRIM(IFNULL(b.creative_name, b.creative_id)) AS ad_name,
  b.ad_format                                  AS objective,
  CAST(NULL AS STRING)                         AS effective_status,
  b.currency,
  CAST(b.cost AS FLOAT64)                      AS spend,
  b.impressions,
  CAST(NULL AS INT64)                          AS reach,       -- TTD reach is not in this feed
  b.clicks,
  b.clicks                                     AS link_clicks, -- TTD reports one click measure
  CAST(NULL AS INT64)                          AS landing_page_views,
  CAST(NULL AS INT64)                          AS leads,       -- awareness/retargeting lines: no lead form
  b.creative_id,
  b.creative_name                              AS creative_title,
  CAST(NULL AS STRING)                         AS creative_body,
  CAST(NULL AS STRING)                         AS creative_thumbnail_url,
  CAST(NULL AS STRING)                         AS destination_url,
  b.video_starts                               AS video_3s_views,
  b.video_completes,
  CAST(NULL AS INT64)                          AS thruplays
FROM base b
LEFT JOIN nm_map nm ON CONCAT(IFNULL(b.campaign_name,''), ' ', IFNULL(b.ad_group_name,'')) = nm.nm
