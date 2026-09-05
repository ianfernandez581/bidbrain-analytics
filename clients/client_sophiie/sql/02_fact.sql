-- 02_fact: the single per-(date x campaign x ad group x creative) fact table the export job ships
-- whole. Same architecture as every other lean client here: the job emits THIS fact as a compact
-- `rows[]` array and the dashboard rolls everything up CLIENT-SIDE (KPIs, by-stage / by-tier /
-- by-creative, the daily trend, the vs-target delta table), filtered by the chosen date range. That
-- is what makes the date-range filter + the CSV "export all data" exact and free.
--
-- Grain is guaranteed one row per (date, campaign_id, ad_group_id, creative_id) by GROUP BY on the
-- IDs; the raw layer's extra ad_format dimension is summed away (ANY_VALUE keeps a representative
-- format label - a TTD creative virtually always serves one format). Names + tier/market/stage come
-- via ANY_VALUE (constant within a date x creative). All ratio metrics (CTR/CPM/CPC/CPA/video
-- completion) are recomputed CLIENT-SIDE from these summed components, NEVER stored - a stored rate
-- cannot be re-aggregated over a date sub-range (md/AGENTS.md "RATES MUST NEVER ENTER A FACT TABLE").
CREATE OR REPLACE VIEW `bidbrain-analytics.client_sophiie.fact` AS
SELECT
  date,
  campaign_id,
  ANY_VALUE(campaign_name)   AS campaign_name,
  ad_group_id,
  ANY_VALUE(ad_group_name)   AS ad_group_name,
  ANY_VALUE(tier)            AS tier,
  ANY_VALUE(market)          AS market,
  creative_id,
  ANY_VALUE(creative_name)   AS creative_name,
  ANY_VALUE(ad_format)       AS ad_format,
  ANY_VALUE(funnel_stage)    AS funnel_stage,
  ANY_VALUE(currency)        AS currency,
  SUM(spend)                 AS spend,
  SUM(impressions)           AS impressions,
  SUM(clicks)                AS clicks,
  SUM(video_starts)          AS video_starts,
  SUM(video_25)              AS video_25,
  SUM(video_50)              AS video_50,
  SUM(video_75)              AS video_75,
  SUM(video_completes)       AS video_completes,
  -- SUM (not AVG) both sides, then divide ONCE at the top level - averaging per-row rates
  -- would weight a 10-impression row the same as a 10,000-impression one.
  SUM(sampled_viewed_impressions)  AS sampled_viewed,
  SUM(sampled_tracked_impressions) AS sampled_tracked,
  SUM(post_view_conv)        AS post_view_conv,
  SUM(post_click_conv)       AS post_click_conv,
  -- Distinct conversion slots seen anywhere in this group, so the job can report which anonymous
  -- TTD slots are actually reporting (see the SIGN-UPS note in sql/01_stg_ttd.sql).
  STRING_AGG(DISTINCT conv_slots, ',') AS conv_slots
FROM `bidbrain-analytics.client_sophiie.stg_ttd`
GROUP BY date, campaign_id, ad_group_id, creative_id
