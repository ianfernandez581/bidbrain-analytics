-- 27_crm_signups_weekly.sql — Q1+Q2: app signups per ISO week × source, with the
-- loaded-balance and paying conversions. Grain: (week_start, source_bucket). Frontend
-- sums across source for the funnel-over-time line and stacks by source for "where from",
-- and finds the latest week for the "signed up this week" headline.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_signups_weekly` AS
SELECT
  DATE_TRUNC(DATE(rd_signup_at), WEEK(MONDAY)) AS week_start,
  source_bucket,
  COUNT(*)                              AS signups,
  COUNTIF(loaded_balance)               AS loaded_balance,
  COUNTIF(is_paying)                    AS paying,
  COUNTIF(has_ad_click_id)              AS ad_attributed,   -- carries a gclid/fbclid
  ROUND(SUM(IF(is_paying, rd_total_spend, 0)), 2) AS rd_spend
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts`
WHERE is_app_signup
GROUP BY week_start, source_bucket
ORDER BY week_start, source_bucket;
