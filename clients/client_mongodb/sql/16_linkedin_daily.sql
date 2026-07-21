-- MongoDB - LinkedIn daily delivery (for the trend chart's Month/Week/Day + Relative/Absolute
-- toggle and the date-range picker). WEEK_START mirrors the paid_media_model so the same
-- bucketing helpers work. Additive base only. Empty until the Windsor account is readable.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.linkedin_daily` AS
SELECT
  metric_date                              AS DAY,
  DATE_TRUNC(metric_date, WEEK(MONDAY))    AS WEEK_START,
  SUM(imps)                                AS imps,
  SUM(clicks)                              AS clicks,
  SUM(spend_usd)                           AS spend_usd,
  SUM(leads)                               AS leads,
  SUM(lead_form_opens)                     AS lead_form_opens,
  SUM(landing_page_clicks)                 AS landing_page_clicks
FROM `bidbrain-analytics.client_mongodb.stg_linkedin`
GROUP BY DAY, WEEK_START
ORDER BY DAY;
