-- 02_fact: the single per-(date x campaign x adset x ad) fact table the export job ships whole.
-- This is the NEW architecture (rebuilt 2026-06): instead of many server-side rollup views
-- (overview / by_campaign / by_ad / daily / by_stage / fatigue), the job emits THIS fact as a
-- compact `rows[]` array and the dashboard rolls everything up CLIENT-SIDE, filtered by the chosen
-- date range. That is what makes the date-range filter + CSV "export all data" exact and free.
--
-- Grain is guaranteed one row per (date, campaign_id, adset_id, ad_id) by GROUP BY on the IDs;
-- names + creative metadata come via ANY_VALUE (constant within a date x ad). Grouping on the IDs
-- (not the creative text) avoids the old by_ad fragmentation, where day-to-day variation in
-- creative_title/body split a single ad into many rows.
--
-- Additive metrics are SUMMED. Reach is summed too (Meta reach is a deduped audience and is NOT
-- truly additive across days, but the previous model summed it as well, so we keep that convention
-- for continuity; frequency is therefore impressions / summed-reach). All ratio metrics are
-- recomputed CLIENT-SIDE from these summed components, never stored here.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_nextsmile.fact` AS
SELECT
  date,
  campaign_id,
  ANY_VALUE(campaign_name)          AS campaign_name,
  adset_id,
  ANY_VALUE(adset_name)             AS adset_name,
  ad_id,
  ANY_VALUE(ad_name)                AS ad_name,
  ANY_VALUE(funnel_stage)           AS funnel_stage,
  ANY_VALUE(currency)               AS currency,
  ANY_VALUE(creative_id)            AS creative_id,
  ANY_VALUE(creative_title)         AS creative_title,
  ANY_VALUE(creative_body)          AS creative_body,
  ANY_VALUE(creative_thumbnail_url) AS creative_thumbnail_url,
  ANY_VALUE(destination_url)        AS destination_url,
  SUM(spend)                        AS spend,
  SUM(impressions)                  AS impressions,
  SUM(reach)                        AS reach,
  SUM(clicks)                       AS clicks,
  SUM(link_clicks)                  AS link_clicks,
  SUM(landing_page_views)           AS landing_page_views,
  SUM(leads)                        AS leads,
  SUM(video_3s_views)               AS video_3s_views,
  SUM(video_completes)              AS video_completes,
  SUM(thruplays)                    AS thruplays,
  SUM(leads_website)                AS leads_website,
  SUM(leads_onfacebook)             AS leads_onfacebook,
  ANY_VALUE(objective)              AS objective,
  ANY_VALUE(effective_status)       AS effective_status
FROM `bidbrain-analytics.client_nextsmile.stg_meta`
GROUP BY date, campaign_id, adset_id, ad_id
