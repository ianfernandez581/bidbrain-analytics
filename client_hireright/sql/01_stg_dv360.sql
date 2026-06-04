-- HireRight - staged DV360 programmatic display. The ONLY source with real geo.
--
-- The HireRight DV360 filter lives here once: ADVERTISER_NAME contains "HireRight"
-- (case-insensitive). BigQuery has no ILIKE, so the brief's `ILIKE '%HireRight%'`
-- is expressed as LOWER(...) LIKE '%hireright%' (same intent, valid Standard SQL).
--
-- Reporting currency = USD. DV360 rows are already USD, but the CASE keeps the
-- AUD->USD conversion robust at the shared FX constant if an AUD row ever appears:
--     FX_AUD_USD = 0.65   (placeholder - editable; reused in stg_tradedesk / stg_linkedin)
--
-- Spend = REVENUE_ADV_CURRENCY (advertiser-billed cost incl. media + fees - what
-- HireRight actually paid, the figure stakeholders expect, not the bare MEDIA_COST).
-- COUNTRY_NAME is a 2-letter code -> mapped to a friendly name where known, else the
-- raw code is kept (raw codes are acceptable for a baseline). CAMPAIGN_NAME is carried
-- so the dashboard's Campaign filter can slice DV360 delivery client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_dv360` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  CASE COUNTRY_NAME
    WHEN 'US' THEN 'United States'
    WHEN 'PH' THEN 'Philippines'
    WHEN 'AU' THEN 'Australia'
    WHEN 'CA' THEN 'Canada'
    WHEN 'SG' THEN 'Singapore'
    WHEN 'AE' THEN 'UAE'
    WHEN 'HK' THEN 'Hong Kong'
    WHEN 'ID' THEN 'Indonesia'
    WHEN 'NZ' THEN 'New Zealand'
    WHEN 'SA' THEN 'Saudi Arabia'
    WHEN 'NL' THEN 'Europe'
    WHEN 'DE' THEN 'Europe'
    WHEN 'SE' THEN 'Europe'
    WHEN 'DK' THEN 'Europe'
    WHEN 'NO' THEN 'Europe'
    ELSE COALESCE(COUNTRY_NAME, 'Unknown')
  END                                      AS market,
  IMPRESSIONS                              AS imps,
  CLICKS                                   AS clicks,
  -- AUD -> USD @0.65, otherwise already USD (advertiser currency).
  CASE CURRENCY WHEN 'AUD' THEN REVENUE_ADV_CURRENCY * 0.65 ELSE REVENUE_ADV_CURRENCY END AS spend_usd,
  CONVERSIONS_TOTAL                        AS conversions,
  ENGAGEMENTS                              AS engagements,
  CURRENCY                                 AS currency
FROM `bidbrain-analytics.raw_snowflake.dv360_apac`
WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%';
