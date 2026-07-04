-- VMCH — TTD delivery by ad group, PER DAY.
-- Daily twin of 10_ttd_adgroups so the Trade Desk ad-groups table responds to the
-- date-range picker. Reads stg_ttd (pure-measured, like 10_) — the modelled April
-- RAC/SAH slivers stay OUT, matching the whole-flight table.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ttd_adgroups_daily` AS
SELECT
  metric_date    AS day,
  ad_group_name  AS ad_group,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud
FROM `bidbrain-analytics.client_vmch.stg_ttd`
GROUP BY metric_date, ad_group_name;
