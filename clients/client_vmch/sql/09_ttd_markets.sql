-- VMCH — TTD delivery (placeholder). No geo dimension exists in the source
-- (VMCH is AU-only), so this view returns a single row with the totals.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ttd_markets` AS
SELECT
  'Australia' AS market,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud
FROM `bidbrain-analytics.client_vmch.stg_ttd`;