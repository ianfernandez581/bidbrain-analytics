-- PropTrack (Transmission) — headline KPI row (single row the dashboard reads for the big numbers).
--
-- Combined window = earliest delivery day → latest, across both platforms (2025-08-07 → 2026-06-09).
-- Spend is AUD throughout (no FX). ad_* = The Trade Desk + LinkedIn combined. All conversions are
-- TradeDesk pixel conversions (LinkedIn conversions = 0); the click / view-through split is kept.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.kpi` AS
WITH
td AS (
  SELECT
    SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
    SUM(conversions) AS conv, SUM(click_conv) AS click_conv, SUM(vt_conv) AS vt_conv,
    MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_proptrack.stg_tradedesk`
),
li AS (
  SELECT
    SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
    SUM(conversions) AS conv, SUM(engagements) AS eng, SUM(video_views) AS video_views,
    SUM(leads) AS leads, SUM(lead_form_opens) AS lead_opens,
    MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_proptrack.stg_linkedin`
)
SELECT
  LEAST(td.start_date, li.start_date)  AS campaign_start,
  GREATEST(td.end_date, li.end_date)   AS campaign_end,
  DATE_DIFF(GREATEST(td.end_date, li.end_date), LEAST(td.start_date, li.start_date), DAY) + 1 AS campaign_days,
  td.start_date AS td_start, td.end_date AS td_end,
  li.start_date AS li_start, li.end_date AS li_end,
  -- combined
  (td.imps + li.imps)             AS ad_imps,
  (td.clicks + li.clicks)         AS ad_clicks,
  (td.spend_aud + li.spend_aud)   AS ad_spend_aud,
  (td.conv + li.conv)             AS ad_conv,
  -- The Trade Desk
  td.imps AS td_imps, td.clicks AS td_clicks, td.spend_aud AS td_spend_aud,
  td.conv AS td_conv, td.click_conv AS td_click_conv, td.vt_conv AS td_vt_conv,
  -- LinkedIn
  li.imps AS li_imps, li.clicks AS li_clicks, li.spend_aud AS li_spend_aud,
  li.eng AS li_eng, li.video_views AS li_video_views, li.leads AS li_leads, li.lead_opens AS li_lead_opens
FROM td, li;
