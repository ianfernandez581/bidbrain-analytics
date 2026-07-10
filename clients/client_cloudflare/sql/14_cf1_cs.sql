-- cf1_cs: CF1 Content-Syndication leads ("Double Touch" MQLs).
-- Client request (2026-06-22): surface CF1's content-syndication delivery in the
-- "CF1 India" single-campaign view. Vendors upload leads to CaptureIQ; Nabeel uploads
-- them to Integrate; they land in Salesforce -> raw_snowflake.salesforce_cs_apac_all.
-- The 2 CF1 CS campaign IDs below are ALSO in the core 13-campaign filter
-- (sql/10_salesforce_leads_live.sql, the "Connectivity Cloud (ANZ)" pair) where they feed
-- the geographic CS pacing model; THIS view is a separate, CF1-scoped lane that mirrors the
-- exact query the client sent (Total = New + Accepted, Accepted, Rejected) against the
-- 110 Double Touch MQL target. Every lead in these campaigns is a "Double Touch" lead
-- (CAMPAIGN name ends in "Double Touch"; ASSET_1 AND ASSET_2 both populated on every row),
-- so the accepted count IS the delivered double-touch MQL count -- no asset filter needed.
--
-- Grain: one row per (DAY, PUBLISHER, REGION, TOPIC, STATUS_BUCKET). DT_CREATED is a single
-- bulk-load instant (manual Integrate upload), so it carries NO daily signal -- DAY holds the
-- true per-lead delivery date and is what the cumulative-delivery line uses.
CREATE OR REPLACE VIEW `client_cloudflare.cf1_cs` AS
WITH base AS (
  SELECT
    DAY,
    -- Publisher / region / topic parsed from the CS CAMPAIGN string, e.g.
    --   2026_Q2_SAARC_Final Funnel_CF1_Modernize Security_ACQ_EN_Double Touch
    CASE
      WHEN CAMPAIGN LIKE '%Final Funnel%' THEN 'Final Funnel'
      WHEN CAMPAIGN LIKE '%Roverpath%'    THEN 'Roverpath'
      ELSE 'Other'
    END AS PUBLISHER,
    COALESCE(REGEXP_EXTRACT(CAMPAIGN, r'^[0-9]{4}_Q[0-9]_([A-Z]+)_'), 'Unknown') AS REGION,
    COALESCE(REGEXP_EXTRACT(CAMPAIGN,
      r'_(Connectivity Cloud|Modernize Security|Modernize Network|Modernize Applications)_'),
      'Other') AS TOPIC,
    -- Status buckets per the client's query. Today the 2 campaigns carry only Accepted/Rejected;
    -- New/Other are kept so the lane stays correct if the lifecycle ever populates them.
    CASE
      WHEN LEAD_STATUS = 'Accepted' THEN 'Accepted'
      WHEN LEAD_STATUS = 'Rejected' THEN 'Rejected'
      WHEN LEAD_STATUS = 'New'      THEN 'New'
      ELSE 'Other'
    END AS STATUS_BUCKET
  FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
  -- The 2 CF1 CS campaign IDs are seed-driven (definitions.json -> seed_cf1_cs_campaign_ids).
  WHERE CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_cf1_cs_campaign_ids`)
)
SELECT DAY, PUBLISHER, REGION, TOPIC, STATUS_BUCKET, COUNT(*) AS LEADS
FROM base
GROUP BY DAY, PUBLISHER, REGION, TOPIC, STATUS_BUCKET;
