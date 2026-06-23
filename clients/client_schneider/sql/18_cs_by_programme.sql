-- Schneider Electric — CS leads rolled up per campaign × programme (SF pillar_label) × market × status,
-- plus the last lead date. The single source for the Content Syndication tab's snapshot, doughnuts
-- (by market / by programme), by-region summary and programme×market table. Mirrors client_mongodb's
-- cs_leads_by_programme, but the campaign is EXPLICIT (from the seed map), not derived from the label.
-- Reads stg_salesforce (view 17). Status counts are New-only today (forward-compatible).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.cs_by_programme` AS
SELECT
  campaign,
  programme,
  market,
  SUM(leads)                                      AS total,
  SUM(IF(status_bucket='New',          leads, 0)) AS new_leads,
  SUM(IF(status_bucket='Working',      leads, 0)) AS working,
  SUM(IF(status_bucket='Qualified',    leads, 0)) AS qualified,
  SUM(IF(status_bucket='Disqualified', leads, 0)) AS disqualified,
  MAX(metric_date)                                AS last_lead_day
FROM `bidbrain-analytics.client_schneider.stg_salesforce`
GROUP BY campaign, programme, market;
