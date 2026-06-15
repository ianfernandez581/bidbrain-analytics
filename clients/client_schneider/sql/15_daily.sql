-- Schneider Electric — DAILY media delivery, folded across DV360 + TradeDesk + LinkedIn.
-- One row per day with each platform's imps/clicks/spend plus the blended ad_* totals.
-- Same shape as `monthly`/`weekly` (06/07), just the day grain — built on stg_ad_delivery so
-- it always agrees with the campaign-grained roll-ups. Spend is AUD. Powers the Day option of
-- the VIEW BY grain toggle on the Portfolio cumulative-spend + funnel monthly-delivery charts.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.daily` AS
SELECT
  FORMAT_DATE('%Y-%m-%d', metric_date) AS day,
  SUM(IF(platform = 'dv360',     imps, 0))       AS dv_imps,
  SUM(IF(platform = 'dv360',     clicks, 0))     AS dv_clicks,
  SUM(IF(platform = 'dv360',     spend_aud, 0))  AS dv_spend_aud,
  SUM(IF(platform = 'tradedesk', imps, 0))       AS td_imps,
  SUM(IF(platform = 'tradedesk', clicks, 0))     AS td_clicks,
  SUM(IF(platform = 'tradedesk', spend_aud, 0))  AS td_spend_aud,
  SUM(IF(platform = 'linkedin',  imps, 0))       AS li_imps,
  SUM(IF(platform = 'linkedin',  clicks, 0))     AS li_clicks,
  SUM(IF(platform = 'linkedin',  spend_aud, 0))  AS li_spend_aud,
  SUM(imps)      AS ad_imps,
  SUM(clicks)    AS ad_clicks,
  SUM(spend_aud) AS ad_spend_aud
FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
GROUP BY day
ORDER BY day;
