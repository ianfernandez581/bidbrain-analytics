-- Schneider Electric — weekly media delivery (ISO week, Monday-anchored), folded across
-- DV360 + TradeDesk + LinkedIn. One row per week with each platform's imps/clicks/spend plus
-- the blended ad_* totals. Built on stg_ad_delivery. Spend is AUD. Powers the weekly spend /
-- pacing view (and a flight-overlap timeline). Mirrors client_STT/sql/12_weekly.sql in shape
-- (minus the GA4 session series, which Schneider ships disabled).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.weekly` AS
SELECT
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
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
GROUP BY week_start
ORDER BY week_start;
