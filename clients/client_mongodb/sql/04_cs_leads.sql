CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.cs_leads` AS
-- By-market CS rollup (DNB + KGA/IDC combined). TOTAL_LEADS counts only the "delivered"
-- statuses — the UNION of both definitions: New + Unresponsive + Accepted (DNB) and
-- Unresponsive + Do Not Contact + New (KGA/IDC) = New + Unresponsive + Accepted + Do Not
-- Contact. This EXCLUDES 'Unqualified' / 'Rejected' (so it is NOT COUNT(*)) and keeps the
-- by-market totals consistent with the per-programme totals in cs_leads_by_programme.
-- "Do Not Contact" (IDC-only) is counted as still-pending NEW_LEADS.
SELECT MARKET,
  COUNTIF(LEAD_STATUS IN ("New","Unresponsive","Accepted","Do Not Contact")) AS TOTAL_LEADS,
  COUNTIF(LEAD_STATUS="Accepted") AS ACCEPTED,
  COUNTIF(LEAD_STATUS="Rejected") AS REJECTED,
  COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New")) AS NEW_LEADS,
  MAX(DAY) AS LAST_LEAD_DAY
FROM `bidbrain-analytics.client_mongodb.stg_salesforce` GROUP BY MARKET
