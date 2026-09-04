-- 07_stg_linkedin: the Geocon slice of the SHARED raw_windsor.perf_linkedin table.
-- Added 2026-08-24 for Northbourne Gateway, whose media plan buys LinkedIn (A$6,000 / 75,000 imps
-- / plan CPM A$80). Gateway Braddon is Meta-only and is unaffected by this view existing.
--
-- THERE IS NO GEOCON LINKEDIN ACCOUNT IN WINDSOR YET (verified 2026-08-24: the connector carries
-- APJC / STT / Cloudflare / Schneider / PropTrack / HireRight / ResetData and nothing else). This
-- view therefore returns ZERO ROWS today, on purpose -- it is the socket the channel plugs into,
-- and the dashboard's LinkedIn lane switches itself on the first day a row lands. Nothing here
-- needs editing at go-live UNLESS the campaign names miss the scope regex below.
--
-- SCOPE IS A POSITIVE MATCH, NEVER A FALLBACK. perf_linkedin is shared across seven clients, so
-- the filter must be narrow enough that no other client's delivery can be swept in, and the
-- property resolution below must never default -- an unmatched Geocon row lands in 'Unmapped'
-- (which the export ALARMS on) rather than silently inflating a live development's KPIs. That is
-- the opposite of 01_stg_meta, where the catch-all ELSE is safe because the Meta account+prefix
-- scope is already exact and Gateway Braddon is the legitimate default.
--
-- REGEXP_CONTAINS, not LIKE: `_` is a single-character wildcard in LIKE and every token here is
-- short (see the repo-wide rule in md/AGENTS.md).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_linkedin` AS
WITH map AS (
  -- The catch-all row (empty pattern) is EXCLUDED: a non-Meta channel must match a development
  -- by name or be reported as Unmapped. See the header.
  SELECT seq, property_key, LOWER(match_pattern) AS pat
  FROM `bidbrain-analytics.client_geocon.seed_property_map`
  WHERE COALESCE(match_pattern, '') != ''
),
base AS (
  SELECT * FROM `bidbrain-analytics.raw_windsor.perf_linkedin`
  WHERE REGEXP_CONTAINS(
          UPPER(CONCAT(IFNULL(account_name,''), '|', IFNULL(campaign_group_name,''), '|', IFNULL(campaign_name,''))),
          r'GEOCON|NGW558|NORTHBOURNE')
),
-- Resolve the development off the CAMPAIGN GROUP + CAMPAIGN name together: LinkedIn's brief token
-- can sit on either (the client_schneider lesson - a group named for one brief can hold campaigns
-- named for another - so we match on the pair rather than trusting one).
names AS (SELECT DISTINCT CONCAT(IFNULL(campaign_group_name,''), ' ', IFNULL(campaign_name,'')) AS nm FROM base),
nm_rank AS (
  SELECT n.nm, m.property_key, ROW_NUMBER() OVER (PARTITION BY n.nm ORDER BY m.seq) AS rn
  FROM names n, map m
  WHERE EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(LOWER(n.nm), TRIM(tok)) > 0)
),
nm_map AS (SELECT nm, property_key FROM nm_rank WHERE rn = 1)
SELECT
  b.metric_date                                       AS date,
  'LinkedIn'                                          AS channel,
  -- ACCOUNT-SCOPED FALLBACK (client-confirmed 2026-09-04, applied at go-live). The name join is
  -- still tried FIRST and still wins wherever it resolves. It is the fallback that is new: LinkedIn
  -- ad account 556629043 was built for Northbourne Gateway and its delivery is Northbourne's, but
  -- its campaign is named "Gateway Braddon Aug2026" and carries no Northbourne token - so without
  -- this every row would land in 'Unmapped', be excluded from every KPI, and alarm the export.
  --
  -- This is an INSTRUCTION, not an inference, and it is SETTLED (client, 2026-09-04): this is the
  -- FIRST LinkedIn campaign Geocon has run, set up before a naming convention existed, so the
  -- Braddon naming is an artefact of that and not a signal about the development. Do not "correct"
  -- it back. Three naming signals point at Braddon and all three are knowingly overridden - the
  -- account name (`Geocon Group - AUD`), the campaign group (`Gateway Braddon Aug2026`) and the
  -- ad-set prefix (`GWB_ACT_PROSP_*`, GWB = Gateway Braddon).
  --
  -- Scoped to the ACCOUNT ID so a genuine Gateway Braddon LinkedIn campaign on a different account
  -- still resolves on its own, and 'Unmapped' still fires for anything neither rule claims. Delete
  -- this arm the day the ad sets are renamed to carry a Northbourne token - the name join above
  -- runs first and will take over by itself.
  COALESCE(nm.property_key,
           IF(CAST(b.account_id AS STRING) = '556629043', 'Northbourne Gateway', 'Unmapped')
          )                                           AS property,
  b.campaign_id,
  TRIM(IFNULL(b.campaign_group_name, b.campaign_name)) AS campaign_name,
  b.campaign_id                                       AS adset_id,   -- LinkedIn's "campaign" IS the ad set
  TRIM(b.campaign_name)                               AS adset_name,
  b.creative_id                                       AS ad_id,
  TRIM(IFNULL(b.share_title, b.creative_id))          AS ad_name,
  b.objective_type                                    AS objective,
  b.campaign_status                                   AS effective_status,
  b.currency,
  CAST(b.spend AS FLOAT64)                            AS spend,
  b.impressions,
  b.reach,
  b.clicks,
  b.landing_page_clicks                               AS link_clicks,
  CAST(NULL AS INT64)                                 AS landing_page_views,  -- no LPV in this feed
  b.one_click_leads                                   AS leads,
  b.creative_id,
  b.share_title                                       AS creative_title,
  CAST(NULL AS STRING)                                AS creative_body,
  CAST(NULL AS STRING)                                AS creative_thumbnail_url,
  b.landing_page                                      AS destination_url,
  b.video_views                                       AS video_3s_views,
  b.video_completions                                 AS video_completes,
  CAST(NULL AS INT64)                                 AS thruplays
FROM base b
LEFT JOIN nm_map nm ON CONCAT(IFNULL(b.campaign_group_name,''), ' ', IFNULL(b.campaign_name,'')) = nm.nm
