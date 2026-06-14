-- VMCH — TTD delivery by creative / ad format (whole flight).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ttd_creative` AS
SELECT
  creative_name AS creative,
  ad_format,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud
FROM `bidbrain-analytics.client_vmch.stg_ttd`
GROUP BY creative_name, ad_format
ORDER BY spend_aud DESC;