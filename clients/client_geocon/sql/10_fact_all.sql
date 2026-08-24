-- 10_fact_all: the CHANNEL-AGNOSTIC fact the export ships as rows[]. One row per
-- (date x channel x campaign x adset x ad), unioning Meta + LinkedIn + Trade Desk + Google Ads,
-- with the media-plan LINE each row belongs to resolved on the way through.
--
-- WHY IT EXISTS (2026-08-24). Gateway Braddon is a single-channel Meta launch and `fact` served it
-- perfectly. Northbourne Gateway is a A$205,600 five-channel plan, so the dashboard needs one
-- shape that can carry all of them. Rather than fork the dashboard per development, the Meta arm
-- below is `fact` VERBATIM with a channel label bolted on -- Gateway Braddon's rows are therefore
-- byte-identical to what they were, and every existing KPI, chart, table, CSV and AI deck reads
-- exactly the same numbers. `fact` is deliberately KEPT (not folded into this view) so that
-- identity is auditable with a single-view diff.
--
-- CROSS-CONTAMINATION IS IMPOSSIBLE BY CONSTRUCTION. Only the Meta arm may resolve to Gateway
-- Braddon, because only the Meta scope (ad account + `Geocon_` prefix) is exact enough to make a
-- catch-all safe. The other three channels come from tables shared with six-to-eleven other
-- clients, so they must match a development BY NAME or land in 'Unmapped' -- which the export job
-- ALARMS on rather than absorbs. A Geocon Trade Desk campaign nobody told us about therefore
-- shows up as a loud warning, not as an invisible A$40k added to a live client's spend.
--
-- PLAN-LINE ATTRIBUTION is first-match-wins over seed_media_plan.match_pattern, scoped to the row's
-- own (property, channel) and to MEASURABLE lines only, matched against campaign name AND ad-group
-- name together. Lines with an EMPTY pattern sort LAST, so a channel catch-all (Meta, which buys a
-- single line) can only claim what no patterned line already claimed. A row that matches nothing
-- keeps plan_line NULL: that is delivery outside the signed plan and the job reports the total.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.fact_all` AS
WITH meta_rows AS (
  SELECT
    date, 'Meta' AS channel, property,
    campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
    funnel_stage, currency, objective, effective_status,
    creative_id, creative_title, creative_body, creative_thumbnail_url, destination_url,
    spend, impressions, reach, clicks, link_clicks, landing_page_views, leads,
    video_3s_views, video_completes, thruplays, leads_website, leads_onfacebook,
    CAST(NULL AS FLOAT64) AS conversions, CAST(NULL AS FLOAT64) AS view_through_conversions
  FROM `bidbrain-analytics.client_geocon.fact`
),
-- The three new channels arrive at raw grain, so they are re-grouped to the fact grain here (the
-- Meta arm is already grouped by 02_fact). SUM/ANY_VALUE mirrors 02_fact exactly.
other_src AS (
  SELECT date, channel, property, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
         objective, effective_status, currency, spend, impressions, reach, clicks, link_clicks,
         landing_page_views, leads, creative_id, creative_title, creative_body,
         creative_thumbnail_url, destination_url, video_3s_views, video_completes, thruplays,
         CAST(NULL AS FLOAT64) AS conversions, CAST(NULL AS FLOAT64) AS view_through_conversions
  FROM `bidbrain-analytics.client_geocon.stg_linkedin`
  UNION ALL
  SELECT date, channel, property, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
         objective, effective_status, currency, spend, impressions, reach, clicks, link_clicks,
         landing_page_views, leads, creative_id, creative_title, creative_body,
         creative_thumbnail_url, destination_url, video_3s_views, video_completes, thruplays,
         CAST(NULL AS FLOAT64), CAST(NULL AS FLOAT64)
  FROM `bidbrain-analytics.client_geocon.stg_ttd`
  UNION ALL
  SELECT date, channel, property, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
         objective, effective_status, currency, spend, impressions, reach, clicks, link_clicks,
         landing_page_views, leads, creative_id, creative_title, creative_body,
         creative_thumbnail_url, destination_url, video_3s_views, video_completes, thruplays,
         conversions, view_through_conversions
  FROM `bidbrain-analytics.client_geocon.stg_google_ads`
),
other_rows AS (
  SELECT
    date, channel, property, campaign_id, adset_id, ad_id,
    ANY_VALUE(campaign_name) AS campaign_name,
    ANY_VALUE(adset_name)    AS adset_name,
    ANY_VALUE(ad_name)       AS ad_name,
    CAST(NULL AS STRING)     AS funnel_stage,   -- resolved from the plan line below
    ANY_VALUE(currency)      AS currency,
    ANY_VALUE(objective)     AS objective,
    ANY_VALUE(effective_status) AS effective_status,
    ANY_VALUE(creative_id)   AS creative_id,
    ANY_VALUE(creative_title) AS creative_title,
    ANY_VALUE(creative_body) AS creative_body,
    ANY_VALUE(creative_thumbnail_url) AS creative_thumbnail_url,
    ANY_VALUE(destination_url) AS destination_url,
    SUM(spend) AS spend, SUM(impressions) AS impressions, SUM(reach) AS reach,
    SUM(clicks) AS clicks, SUM(link_clicks) AS link_clicks,
    SUM(landing_page_views) AS landing_page_views, SUM(leads) AS leads,
    SUM(video_3s_views) AS video_3s_views, SUM(video_completes) AS video_completes,
    SUM(thruplays) AS thruplays,
    CAST(NULL AS INT64) AS leads_website, CAST(NULL AS INT64) AS leads_onfacebook,
    SUM(conversions) AS conversions, SUM(view_through_conversions) AS view_through_conversions
  FROM other_src
  GROUP BY date, channel, property, campaign_id, adset_id, ad_id
),
all_rows AS (
  SELECT date, channel, property, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
         funnel_stage, currency, objective, effective_status, creative_id, creative_title,
         creative_body, creative_thumbnail_url, destination_url, spend, impressions, reach, clicks,
         link_clicks, landing_page_views, leads, video_3s_views, video_completes, thruplays,
         leads_website, leads_onfacebook, conversions, view_through_conversions
  FROM meta_rows
  UNION ALL
  SELECT date, channel, property, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
         funnel_stage, currency, objective, effective_status, creative_id, creative_title,
         creative_body, creative_thumbnail_url, destination_url, spend, impressions, reach, clicks,
         link_clicks, landing_page_views, leads, video_3s_views, video_completes, thruplays,
         leads_website, leads_onfacebook, conversions, view_through_conversions
  FROM other_rows
),
plan AS (
  SELECT property_key, channel, seq, line_name, phase, LOWER(COALESCE(match_pattern, '')) AS pat
  FROM `bidbrain-analytics.client_geocon.media_plan`
  WHERE measurable
),
-- One (property, channel, name) triple per distinct delivering name, ranked so a patterned line
-- always beats the channel catch-all and the lowest plan `seq` wins between patterned lines.
keys AS (
  SELECT DISTINCT property, channel,
         LOWER(CONCAT(IFNULL(campaign_name,''), ' ', IFNULL(adset_name,''))) AS nm
  FROM all_rows
),
key_rank AS (
  SELECT k.property, k.channel, k.nm, p.seq, p.line_name, p.phase,
         ROW_NUMBER() OVER (PARTITION BY k.property, k.channel, k.nm
                            ORDER BY (p.pat = ''), p.seq) AS rn
  FROM keys k
  JOIN plan p ON p.property_key = k.property AND p.channel = k.channel
  WHERE p.pat = ''
     OR EXISTS (SELECT 1 FROM UNNEST(SPLIT(p.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(k.nm, TRIM(tok)) > 0)
),
key_map AS (SELECT property, channel, nm, seq, line_name, phase FROM key_rank WHERE rn = 1)
SELECT
  a.* EXCEPT (funnel_stage),
  km.seq       AS plan_seq,
  km.line_name AS plan_line,
  -- Stage precedence: Meta keeps its own campaign-name classification (unchanged, so Gateway
  -- Braddon's stage chips and donut cannot move); every other channel takes the PHASE THE PLAN
  -- BOUGHT, which is the client's own language, falling back to the campaign-name suffix
  -- convention (_AWR / _CNV / _RTG) and finally to 'Other'.
  COALESCE(
    a.funnel_stage,
    km.phase,
    CASE
      WHEN REGEXP_CONTAINS(UPPER(a.campaign_name), r'(^|[ _-])(RTG|RT|RETARGET)') THEN 'Retargeting'
      WHEN REGEXP_CONTAINS(UPPER(a.campaign_name), r'(^|[ _-])(CNV|CONV)')        THEN 'Conversion'
      WHEN REGEXP_CONTAINS(UPPER(a.campaign_name), r'(^|[ _-])(AWR|AWARE)')       THEN 'Awareness'
    END,
    'Other') AS funnel_stage
FROM all_rows a
LEFT JOIN key_map km
  ON  km.property = a.property AND km.channel = a.channel
  AND km.nm = LOWER(CONCAT(IFNULL(a.campaign_name,''), ' ', IFNULL(a.adset_name,'')))
