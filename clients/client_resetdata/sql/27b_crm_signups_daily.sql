-- 27b_crm_signups_daily.sql -- DAY-grain companion to crm_signups_weekly: app signups per
-- created DAY x source (the same created-date basis the whole Signups & CRM tab scopes on).
-- Backs the "App signups" chart's Day/Week toggle — the frontend renders this at day grain, or
-- rolls it up to ISO weeks (Mon-anchored, matching crm_signups_weekly) when Week is selected.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_signups_daily` AS
SELECT
  DATE(hs_created_at)                   AS day,
  source_bucket,
  COUNT(*)                              AS signups,
  COUNTIF(loaded_balance)               AS loaded_balance,
  COUNTIF(is_paying)                    AS paying,
  COUNTIF(has_ad_click_id)              AS ad_attributed,   -- carries a gclid/fbclid
  ROUND(SUM(IF(is_paying, rd_total_spend, 0)), 2) AS rd_spend
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts`
WHERE is_app_signup
GROUP BY day, source_bucket
ORDER BY day, source_bucket;
