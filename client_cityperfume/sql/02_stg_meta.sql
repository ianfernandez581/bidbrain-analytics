-- City Perfume — Meta staging (filter the shared raw layer once, here).
--
-- Source: bidbrain-analytics.raw_windsor.perf_meta, account_name='Cityperfume.com.au'
-- (note the .com.au string — different from the Google/TTD 'City Perfume' string).
-- AD x day grain (true key = ad_id, 133 distinct; ad_name is reused/relabelled).
-- ALL AUD (currency='AUD' on 100% of rows) — `cost` IS spend in account currency, no FX.
--
-- effective_status is current-config delivery state, NOT a per-date spend flag:
-- paused/archived rows hold ~50% of lifetime spend & purchases, so we DO NOT filter on
-- it — all delivered rows count toward historical totals.
--
-- purchases / purchase_value are Meta-CLAIMED (omni) conversions — shown separately,
-- never summed into the blended headline. There is no native creative_type column, so
-- we derive video vs image from the presence of any video play. creative_link_url is
-- always NULL and destination_url is sparse (~32%) — neither is used; the thumbnail +
-- title + body + creative_id power the creative gallery instead.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.stg_meta` AS
SELECT
  campaign_name,
  adset_name,
  ad_name,
  ad_id,
  objective,
  effective_status,
  metric_date,
  impressions                       AS imps,
  clicks,
  link_clicks,
  landing_page_views,
  cost                              AS spend_aud,
  add_to_cart,
  initiate_checkout,
  purchases,
  purchase_value                    AS revenue_claimed,
  thruplays,
  video_3s_views,
  CASE
    WHEN COALESCE(video_3s_views, 0) > 0
      OR COALESCE(thruplays, 0)      > 0
      OR COALESCE(video_starts, 0)   > 0 THEN 'video'
    ELSE 'image'
  END                               AS creative_type,
  creative_id,
  creative_thumbnail_url,
  creative_title,
  creative_body
FROM `bidbrain-analytics.raw_windsor.perf_meta`
WHERE account_name = 'Cityperfume.com.au'
  AND metric_date >= DATE '2025-06-01';
