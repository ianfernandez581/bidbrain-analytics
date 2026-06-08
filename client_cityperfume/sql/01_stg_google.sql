-- City Perfume — Google Ads staging (filter the shared raw layer once, here).
--
-- Source: bidbrain-analytics.raw_google_ads.perf_google_ads, account_name='City Perfume'.
-- Campaign x day grain. ALL AUD (currency_code='AUD' on 100% of rows) so NO FX is
-- applied anywhere in this client. `spend` is NUMERIC dollars already (NOT micros —
-- verified: SUM=1.54M AUD vs 177M imps => ~AUD 8.7 CPM; do not divide by 1e6).
-- conversions_value is Google-CLAIMED revenue (shown separately, never summed into the
-- blended headline). Reporting window 2025-06-01 -> latest is applied once, here.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.stg_google` AS
SELECT
  campaign_name,
  campaign_type,
  metric_date,
  impressions                       AS imps,
  clicks,
  spend                             AS spend_aud,
  conversions,
  conversions_value                 AS revenue_claimed
FROM `bidbrain-analytics.raw_google_ads.perf_google_ads`
WHERE account_name = 'City Perfume'
  AND metric_date >= DATE '2025-06-01';
