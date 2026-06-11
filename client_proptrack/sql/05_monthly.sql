-- PropTrack (Transmission) — monthly trend (from 2025-08): the Overview hero series.
--
-- One row per month with The Trade Desk and LinkedIn delivery side by side, plus combined ad_*.
-- TradeDesk only delivered in May–Jun 2026, so it appears at the tail; LinkedIn is always-on with
-- real gaps (no delivery Sep/Oct'25, Mar/Apr'26). FULL OUTER JOIN on month so every delivering
-- month from either platform appears; IFNULL(...,0) fills the other side. Spend is AUD (no FX).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.monthly` AS
WITH
td AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks,
         SUM(spend_aud) AS td_spend_aud, SUM(conversions) AS td_conv
  FROM `bidbrain-analytics.client_proptrack.stg_tradedesk` GROUP BY month
),
li AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(spend_aud) AS li_spend_aud,
         SUM(engagements) AS li_eng, SUM(video_views) AS li_video_views
  FROM `bidbrain-analytics.client_proptrack.stg_linkedin` GROUP BY month
)
SELECT
  month,
  IFNULL(td.td_imps, 0)        AS td_imps,
  IFNULL(td.td_clicks, 0)      AS td_clicks,
  IFNULL(td.td_spend_aud, 0)   AS td_spend_aud,
  IFNULL(td.td_conv, 0)        AS td_conv,
  IFNULL(li.li_imps, 0)        AS li_imps,
  IFNULL(li.li_clicks, 0)      AS li_clicks,
  IFNULL(li.li_spend_aud, 0)   AS li_spend_aud,
  IFNULL(li.li_eng, 0)         AS li_eng,
  IFNULL(li.li_video_views, 0) AS li_video_views,
  IFNULL(td.td_imps, 0)      + IFNULL(li.li_imps, 0)      AS ad_imps,
  IFNULL(td.td_clicks, 0)    + IFNULL(li.li_clicks, 0)    AS ad_clicks,
  IFNULL(td.td_spend_aud, 0) + IFNULL(li.li_spend_aud, 0) AS ad_spend_aud,
  IFNULL(td.td_conv, 0)                                   AS ad_conv
FROM td FULL OUTER JOIN li USING (month)
WHERE month >= '2025-08'
ORDER BY month;
