-- Schneider Electric — headline KPI row (single row the dashboard reads for the big numbers).
--
-- Whole-flight media delivery folded across the three platforms (DV360 + TradeDesk +
-- LinkedIn). Reporting currency AUD: each stg_* view already converted to AUD, so these
-- roll-ups just sum. The FX constants are surfaced here for the dashboard footer/notes.
-- No GA4 / prior-year baseline (GA4 ships disabled — see 40_stg_ga4.sql); the website
-- outcome layer switches on once the SE GA4 property ids are known.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.kpi` AS
WITH
dv AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         SUM(conversions) AS conversions, SUM(engagements) AS engagements,
         SUM(viewable_imps) AS viewable_imps,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_schneider.stg_dv360`
),
td AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
         SUM(conversions) AS conversions,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_schneider.stg_tradedesk`
),
li AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(cost_aud) AS spend_aud,
         SUM(leads) AS leads, SUM(lead_form_opens) AS lead_form_opens,
         SUM(video_views) AS video_views, SUM(video_starts) AS video_starts,
         SUM(video_completions) AS video_completions, SUM(engagements) AS engagements,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_schneider.stg_linkedin`
)
SELECT
  1.50 AS fx_usd_aud,
  1.15 AS fx_sgd_aud,
  LEAST(dv.start_date, td.start_date, li.start_date)  AS campaign_start,
  GREATEST(dv.end_date, td.end_date, li.end_date)     AS campaign_end,
  DATE_DIFF(GREATEST(dv.end_date, td.end_date, li.end_date),
            LEAST(dv.start_date, td.start_date, li.start_date), DAY) + 1 AS campaign_days,
  dv.imps AS dv_imps, dv.clicks AS dv_clicks, dv.spend_aud AS dv_spend_aud,
  dv.conversions AS dv_conv, dv.engagements AS dv_engagements, dv.viewable_imps AS dv_viewable_imps,
  dv.start_date AS dv_start, dv.end_date AS dv_end,
  td.imps AS td_imps, td.clicks AS td_clicks, td.spend_aud AS td_spend_aud,
  td.conversions AS td_conv, td.start_date AS td_start, td.end_date AS td_end,
  li.imps AS li_imps, li.clicks AS li_clicks, li.spend_aud AS li_spend_aud,
  li.leads AS li_leads, li.lead_form_opens AS li_lead_form_opens,
  li.video_views AS li_video_views, li.video_starts AS li_video_starts,
  li.video_completions AS li_video_completions, li.engagements AS li_engagements,
  li.start_date AS li_start, li.end_date AS li_end,
  (dv.imps + td.imps + li.imps)             AS ad_imps,
  (dv.clicks + td.clicks + li.clicks)        AS ad_clicks,
  (dv.spend_aud + td.spend_aud + li.spend_aud) AS ad_spend_aud,
  (dv.conversions + td.conversions)          AS ad_conversions,
  (li.leads + li.lead_form_opens)            AS ad_leads
FROM dv, td, li;
