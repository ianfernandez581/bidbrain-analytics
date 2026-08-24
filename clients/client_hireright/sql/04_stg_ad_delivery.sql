-- HireRight - unified ad-delivery base (the single source for the Campaign filter
-- and every campaign-grained roll-up). One long-format row per platform x campaign x
-- day, folding DV360, TradeDesk and LinkedIn into the SAME shape so ad_campaigns /
-- ad_campaign_monthly / ad_campaign_weekly / ad_campaign_daily / ad_campaign_market
-- are built once on top. Mirrors client_STT/sql/03c_stg_ad_delivery.sql.
--
-- spend_usd is USD for all three (each stg_* view already converted at the shared rate).
-- market: DV360 carries real geo (country + region); TradeDesk + LinkedIn are 'Global'
-- air-cover. creative_type is LinkedIn-only (NULL elsewhere).
--
-- ============================================================================
-- WHY THERE IS NO SINGLE `conversions` COLUMN HERE ANY MORE (fixed 2026-08-24)
-- ============================================================================
-- This view used to emit ONE `conversions` column built as:
--     DV360 CONVERSIONS_TOTAL  UNION  TTD TOTAL_CLICK_PLUS_VIEW_CONVERSIONS
--                              UNION  LinkedIn LEADS
-- and `kpi.ad_conv` added all three together into a headline "Conversions" tile
-- captioned "DV360 + TradeDesk + LinkedIn leads". Those are three DIFFERENT things:
--
--   * DV360  CONVERSIONS_TOTAL              - Floodlight, post-click + post-view
--   * TTD    TOTAL_CLICK_PLUS_VIEW_CONVS    - TTD pixel, post-click + post-view
--   * LI     LEADS                          - a human completing a lead-gen FORM
--
-- Adding a view-through display conversion to a submitted lead form produces a number
-- that means nothing and reads as an outcome count - the client would reasonably take
-- it for "leads generated" and it is mostly ad-served impressions that were never
-- clicked. It also double-counts: the DV360 and TTD tags can both fire on the same
-- site action for the same user, and nothing deduplicates them.
--
-- So the two kinds are carried SEPARATELY and never summed:
--   `leads`     - LinkedIn lead-gen form submissions ONLY. A real, direct outcome.
--   `attr_conv` - DV360 + TradeDesk programmatic ATTRIBUTED conversions. Same broad
--                 definition (post-click + post-view against an advertiser tag), so
--                 they may be added to each other, but they are NOT deduplicated
--                 across the two platforms and must always be labelled as attributed
--                 rather than presented as actions the campaign caused.
-- Repo precedent for this rule: client_cloudflare carries Google Ads PMax conversions
-- as `conversions` and LABELS them, never folding them into LEADS; client_vmch labels
-- its TTD post-view/post-click figures explicitly rather than calling them enquiries.
-- If a future edit wants one blended outcome number, it needs a conversion definition
-- agreed with the client first - not a SUM.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_ad_delivery` AS
SELECT
  'dv360'                   AS platform,
  campaign_name             AS campaign,
  brief,
  metric_date,
  market,
  region,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_usd,
  engagements,
  CAST(NULL AS INT64)       AS leads,       -- DV360 has no lead-form concept
  attr_conv
FROM `bidbrain-analytics.client_hireright.stg_dv360`
UNION ALL
SELECT
  'tradedesk'               AS platform,
  campaign_name             AS campaign,
  brief,
  metric_date,
  market,
  region,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_usd,
  CAST(NULL AS INT64)       AS engagements, -- not in the TTD mirror
  CAST(NULL AS INT64)       AS leads,       -- TTD has no lead-form concept
  attr_conv
FROM `bidbrain-analytics.client_hireright.stg_tradedesk`
UNION ALL
SELECT
  'linkedin'                AS platform,
  campaign_name             AS campaign,
  brief,
  metric_date,
  market,
  region,
  creative_type,
  imps,
  clicks,
  cost_usd                  AS spend_usd,   -- cost_usd already holds USD (see stg_linkedin)
  engagements,
  leads,
  CAST(NULL AS INT64)       AS attr_conv    -- LinkedIn reports no post-view conversions here
FROM `bidbrain-analytics.client_hireright.stg_linkedin`;
