-- HireRight - staged DV360 programmatic display. The ONLY source with real geo.
--
-- The HireRight DV360 filter lives here once: ADVERTISER_NAME contains "HireRight"
-- (case-insensitive). BigQuery has no ILIKE, so the brief's `ILIKE '%HireRight%'`
-- is expressed as LOWER(...) LIKE '%hireright%' (same intent, valid Standard SQL).
-- That is a SUBSTRING match on a name, so it would also sweep in a second HireRight
-- advertiser if Transmission ever creates one - `scope_audit` (17) lists every
-- distinct advertiser this matches so a silent widening is visible, not guessed at.
--
-- Reporting currency = USD. DV360 rows are already USD, but the CASE keeps the
-- AUD->USD conversion robust at the shared rate if an AUD row ever appears. The rate
-- comes from the single-row `fx` view (00_fx.sql) - never re-type the literal here.
--
-- Spend = REVENUE_ADV_CURRENCY (advertiser-billed cost incl. media + fees - what
-- HireRight actually paid, the figure stakeholders expect, not the bare MEDIA_COST).
--
-- CAMPAIGN NAMES ARE NOT STABLE KEYS (repo-wide rule, AGENTS.md): Transmission is
-- progressively prefixing campaign names with the brief number (`2265_...`). Every
-- roll-up here groups by campaign, so the day a prefix lands the SAME campaign would
-- appear under two names and each aggregate would split in half. `campaign_name` is
-- therefore the NORMALISED name (prefix stripped once) and the prefix is kept as its
-- own `brief` column, so nothing is lost and nothing splits.
--
-- GEO: COUNTRY_NAME is a 2-letter ISO code. It is mapped to a friendly country name
-- AND rolled up to a region. The previous version folded NL/DE/SE/DK/NO into a single
-- 'Europe' market while leaving every other country individual - which meant the
-- market list mixed countries with a continent and European delivery could not be
-- read per country. Country and region are now separate columns: no information is
-- discarded, and the dashboard can group either way. An unmapped code keeps its raw
-- 2-letter form (visible as odd, rather than silently absorbed into a default).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_dv360` AS
SELECT
  DATE(d.DAY)                              AS metric_date,
  -- Normalised campaign name = the grouping key everywhere downstream.
  REGEXP_REPLACE(TRIM(d.CAMPAIGN_NAME), r'^[0-9]+_', '')  AS campaign_name,
  -- The stripped brief number, kept as a dimension (NULL until Transmission prefixes).
  NULLIF(REGEXP_EXTRACT(TRIM(d.CAMPAIGN_NAME), r'^([0-9]+)_'), '') AS brief,
  d.CAMPAIGN_NAME                          AS campaign_name_raw,
  CASE UPPER(d.COUNTRY_NAME)
    WHEN 'US' THEN 'United States'      WHEN 'CA' THEN 'Canada'
    WHEN 'MX' THEN 'Mexico'             WHEN 'BR' THEN 'Brazil'
    WHEN 'AR' THEN 'Argentina'          WHEN 'CL' THEN 'Chile'
    WHEN 'GB' THEN 'United Kingdom'     WHEN 'IE' THEN 'Ireland'
    WHEN 'NL' THEN 'Netherlands'        WHEN 'DE' THEN 'Germany'
    WHEN 'FR' THEN 'France'             WHEN 'ES' THEN 'Spain'
    WHEN 'IT' THEN 'Italy'              WHEN 'PT' THEN 'Portugal'
    WHEN 'BE' THEN 'Belgium'            WHEN 'CH' THEN 'Switzerland'
    WHEN 'AT' THEN 'Austria'            WHEN 'PL' THEN 'Poland'
    WHEN 'SE' THEN 'Sweden'             WHEN 'DK' THEN 'Denmark'
    WHEN 'NO' THEN 'Norway'             WHEN 'FI' THEN 'Finland'
    WHEN 'AU' THEN 'Australia'          WHEN 'NZ' THEN 'New Zealand'
    WHEN 'SG' THEN 'Singapore'          WHEN 'MY' THEN 'Malaysia'
    WHEN 'ID' THEN 'Indonesia'          WHEN 'TH' THEN 'Thailand'
    WHEN 'VN' THEN 'Vietnam'            WHEN 'PH' THEN 'Philippines'
    WHEN 'IN' THEN 'India'              WHEN 'JP' THEN 'Japan'
    WHEN 'KR' THEN 'South Korea'        WHEN 'CN' THEN 'China'
    WHEN 'HK' THEN 'Hong Kong'          WHEN 'TW' THEN 'Taiwan'
    WHEN 'AE' THEN 'UAE'                WHEN 'SA' THEN 'Saudi Arabia'
    WHEN 'QA' THEN 'Qatar'              WHEN 'IL' THEN 'Israel'
    WHEN 'ZA' THEN 'South Africa'
    ELSE COALESCE(NULLIF(TRIM(d.COUNTRY_NAME), ''), 'Unknown')
  END                                      AS market,
  CASE
    WHEN UPPER(d.COUNTRY_NAME) IN ('US','CA')                         THEN 'North America'
    WHEN UPPER(d.COUNTRY_NAME) IN ('MX','BR','AR','CL')               THEN 'Latin America'
    WHEN UPPER(d.COUNTRY_NAME) IN ('GB','IE','NL','DE','FR','ES','IT','PT',
                                   'BE','CH','AT','PL','SE','DK','NO','FI') THEN 'Europe'
    WHEN UPPER(d.COUNTRY_NAME) IN ('AU','NZ')                         THEN 'Pacific'
    WHEN UPPER(d.COUNTRY_NAME) IN ('SG','MY','ID','TH','VN','PH','IN','JP',
                                   'KR','CN','HK','TW')               THEN 'Asia'
    WHEN UPPER(d.COUNTRY_NAME) IN ('AE','SA','QA','IL','ZA')          THEN 'MEA'
    ELSE 'Other'
  END                                      AS region,
  d.IMPRESSIONS                            AS imps,
  d.CLICKS                                 AS clicks,
  -- AUD -> USD at the shared rate, otherwise already USD (advertiser currency).
  CASE d.CURRENCY WHEN 'AUD' THEN d.REVENUE_ADV_CURRENCY * fx.aud_usd
                  ELSE d.REVENUE_ADV_CURRENCY END AS spend_usd,
  -- DV360 Floodlight conversions (post-click + post-view). NOT the same definition as
  -- TradeDesk's pixel conversions and NOT the same thing as a LinkedIn lead - see
  -- 04_stg_ad_delivery for why these are never summed into one "conversions" figure.
  d.CONVERSIONS_TOTAL                      AS attr_conv,
  d.ENGAGEMENTS                            AS engagements,
  d.CURRENCY                               AS currency
FROM `bidbrain-analytics.raw_snowflake.dv360_apac` d
CROSS JOIN `bidbrain-analytics.client_hireright.fx` fx
WHERE LOWER(d.ADVERTISER_NAME) LIKE '%hireright%';
