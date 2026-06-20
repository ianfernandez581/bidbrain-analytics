-- 28_crm_source_quality.sql — Q3+Q5: by Original Source, the full quality funnel so you
-- can see which sources drive real PAYING customers vs free signups only, and which
-- produce the best-quality leads (signup-rate, pay-rate, deal-rate). Grain: source_bucket.
-- NB: HubSpot's own attribution is thin (most signups are Offline/Direct) — `ad_attributed`
-- (carries a gclid/fbclid) is the more reliable paid signal; real ad/campaign attribution
-- lives in the Paid Media / Ads→Traffic tabs.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_source_quality` AS
SELECT
  source_bucket,
  COUNT(*)                                  AS leads,
  COUNTIF(is_app_signup)                    AS signups,
  COUNTIF(is_app_signup AND loaded_balance) AS loaded_balance,
  COUNTIF(is_app_signup AND is_paying)      AS paying,
  COUNTIF(is_app_signup AND NOT is_paying)  AS free_only,      -- signed up, never paid
  COUNTIF(has_deal)                         AS with_deal,
  COUNTIF(is_customer)                      AS customers,
  COUNTIF(has_ad_click_id)                  AS ad_attributed,
  ROUND(SUM(IF(is_paying, rd_total_spend, 0)), 2) AS rd_spend,
  ROUND(SAFE_DIVIDE(COUNTIF(is_app_signup), COUNT(*)) * 100, 1)               AS signup_rate_pct,
  ROUND(SAFE_DIVIDE(COUNTIF(is_app_signup AND is_paying), NULLIF(COUNTIF(is_app_signup), 0)) * 100, 1) AS pay_rate_pct
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts`
GROUP BY source_bucket
ORDER BY paying DESC, signups DESC, leads DESC;
