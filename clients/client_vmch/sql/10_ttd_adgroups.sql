-- VMCH — TTD delivery by ad group (whole flight).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ttd_adgroups` AS
SELECT
  ad_group_name                                               AS ad_group,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud
FROM `bidbrain-analytics.client_vmch.stg_ttd`
GROUP BY ad_group_name
ORDER BY spend_aud DESC;