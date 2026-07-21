-- MongoDB - staged LinkedIn Ads (paid social), from the shared Windsor raw layer.
--
-- New lane (2026-07): the AWS Immersion Day lead-gen campaign runs on LinkedIn, not Trade
-- Desk, so it comes from raw_windsor.perf_linkedin (built by ingest/windsor_data_pull/linkedin)
-- rather than raw_snowflake. Grain there is (account x creative x date).
--
-- SCOPE = every MongoDB campaign, by campaign-name prefix. The Windsor loader tags rows
-- client_slug='mongodb' via a keyword fallback, but we filter on the campaign NAME here so
-- the lane is explicit and independent of that tagging: campaign names look like
--   MONGODB_2026-Q3_AWS-IMMERSION-DAY_AU_LEAD-GENERATION_LINKEDIN
-- so `UPPER(campaign_name) LIKE 'MONGODB%'` picks up this campaign and any future MongoDB
-- LinkedIn campaign automatically.
--
-- CURRENCY: LinkedIn spend is in the account's NATIVE currency (`currency`; the AU account is
-- AUD). The MongoDB dashboard reports USD (Trade Desk), so spend is converted to USD here via
-- the same FX approach the other clients use; spend_native + currency are kept for reference.
--   AUD->USD 0.65 (the hireright rate), SGD->USD 0.746 (=1/1.34, the STT rate), USD 1.0.
--
-- NOTE: until the Windsor connector for the MongoDB ad account (502299829) is re-authed, that
-- account returns a hard 500 and this view is EMPTY - by design the whole lane just renders
-- "no data yet" and lights up the moment the account becomes readable. See
-- ingest/windsor_data_pull/linkedin/README.md.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_linkedin` AS
SELECT
  metric_date,
  campaign_name,
  campaign_group_name,
  campaign_id,
  creative_id,
  objective_type,
  campaign_type,
  -- Market parsed from the campaign-name token (…_AU_… / _ANZ_ / _APAC_ …); best-effort, the
  -- lane is single-market (AU) today so this is informational.
  CASE
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[_-])AU([_-]|$)')  THEN 'AU'
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[_-])ANZ([_-]|$)') THEN 'ANZ'
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[_-])NZ([_-]|$)')  THEN 'NZ'
    WHEN CONTAINS_SUBSTR(UPPER(campaign_name), 'APAC')                 THEN 'APAC'
    ELSE 'Other'
  END                                       AS market,
  currency,
  impressions                               AS imps,
  clicks,
  spend                                     AS spend_native,
  spend * CASE currency
            WHEN 'AUD' THEN 0.65
            WHEN 'SGD' THEN 0.746
            WHEN 'USD' THEN 1.0
            WHEN 'GBP' THEN 1.27
            WHEN 'EUR' THEN 1.08
            ELSE 1.0
          END                               AS spend_usd,
  reach,
  landing_page_clicks,
  one_click_leads                           AS leads,
  lead_form_opens,
  engagements,
  likes,
  comments,
  shares,
  follows,
  video_views,
  video_starts,
  video_completions,
  ext_website_conversions,
  ext_website_post_click_conversions,
  ext_website_post_view_conversions,
  landing_page,
  share_title,
  creative_status
FROM `bidbrain-analytics.raw_windsor.perf_linkedin`
WHERE UPPER(campaign_name) LIKE 'MONGODB%';
