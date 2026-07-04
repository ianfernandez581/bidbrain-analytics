-- VMCH — TTD delivery by creative / ad format, PER DAY.
-- Daily twin of 11_ttd_creative so the Trade Desk creative-format donut responds to the
-- date-range picker. Reads stg_ttd (pure-measured, like 11_).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ttd_creative_daily` AS
SELECT
  metric_date    AS day,
  creative_name  AS creative,
  ad_format,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud
FROM `bidbrain-analytics.client_vmch.stg_ttd`
GROUP BY metric_date, creative_name, ad_format;
