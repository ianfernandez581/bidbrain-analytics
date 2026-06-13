-- Schneider Electric (APAC, via Transmission) — staged DV360 programmatic display.
--
-- The Schneider DV360 filter lives here once: ADVERTISER_NAME ILIKE 'APAC | Schneider
-- Electric%'. Spend is converted to the AUD reporting currency from the row CURRENCY.
--
-- FX CONSTANTS (EDITABLE — placeholders, confirm with client; set once here and reuse
-- the same numbers in every view that sums spend — stg_linkedin / stg_tradedesk / kpi):
--     FX_USD_AUD = 1.50      FX_SGD_AUD = 1.15
--
-- Spend = REVENUE_ADV_CURRENCY (the advertiser-billed cost incl. media + fees — what SE
-- actually paid, the figure stakeholders expect, not the bare MEDIA_COST).
--
-- GEOGRAPHY: market is FINE-grained — the priority APAC/ANZ countries keep their own name
-- (Australia, New Zealand, India, Singapore …) so the dashboard can surface the AU/NZ 80/20
-- split the brief calls out; the global programmatic spill is grouped to coarse regions
-- (East Asia / South Asia / Pacific / MEA / South America / North America / Europe / RoW).
-- The dashboard rolls `market` up to the brief's reporting region (Australia+New Zealand →
-- ANZ; the SEA countries → SEA; etc.) for the region split. CAMPAIGN_NAME is carried so the
-- Campaign filter (and the seed_campaign_map bridge) can slice DV360 delivery.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_dv360` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  CASE COUNTRY_NAME
    WHEN 'AU' THEN 'Australia'    WHEN 'NZ' THEN 'New Zealand'
    WHEN 'IN' THEN 'India'        WHEN 'SG' THEN 'Singapore'
    WHEN 'MY' THEN 'Malaysia'     WHEN 'ID' THEN 'Indonesia'
    WHEN 'TH' THEN 'Thailand'     WHEN 'PH' THEN 'Philippines'
    WHEN 'VN' THEN 'Vietnam'      WHEN 'JP' THEN 'Japan'
    ELSE CASE
      WHEN COUNTRY_NAME IN ('KH','LA','MM','BN') THEN 'SEA'
      WHEN COUNTRY_NAME IN ('CN','HK','TW','MO','KR') THEN 'East Asia'
      WHEN COUNTRY_NAME IN ('PK','BD','LK','NP','BT','MV','AF','IR') THEN 'South Asia'
      WHEN COUNTRY_NAME IN ('FJ','PG','NC','VU','SB','WS','TO','PF','GU','NR','CK','AS','KI','FM','MH','TV','NU','WF','PW') THEN 'Pacific'
      WHEN COUNTRY_NAME IN ('SA','AE','QA','KW','EG','ZA','BH','OM','JO','IQ','IL','LB','YE','SY','PS',
                            'MA','DZ','TN','LY','SD','NG','KE','GH','TZ','UG','ET','ZW','ZM','NA','BW','RW','AO',
                            'CM','CI','SN','MZ','MW','MU','MG','SC','LS','SZ','GA','CG','CD','BI','BJ','BF','TG',
                            'ML','NE','GN','GM','LR','SL','CV','SS','SO','EH','MR','CF','TD','KM','GW','ST','DJ','RE','YT') THEN 'MEA'
      WHEN COUNTRY_NAME IN ('BR','CL','AR','MX','CO','PE','VE','EC','UY','PY','BO','CR','PA','GT','HN','NI','SV',
                            'DO','JM','TT','BB','BS','BZ','SR','GY','GF','HT','CU','PR','AG','VC','VG','VI','KY',
                            'BM','GD','DM','LC','KN','AI','TC','SX','AW','CW','BQ','MS','GP','MQ','BL','PM') THEN 'South America'
      WHEN COUNTRY_NAME IN ('US','CA') THEN 'North America'
      WHEN COUNTRY_NAME IN ('GB','DE','FR','ES','IT','NL','BE','SE','PL','RO','RS','IE','AT','CH','PT','GR','NO',
                            'BG','HU','CZ','FI','SK','DK','HR','LT','SI','LV','EE','LU','MT','CY','IS','MK','BA',
                            'AL','ME','MD','UA','BY','XK','AD','MC','LI','SM','GI','FO','GL','GG','JE','IM','RU',
                            'GE','AM','AZ','KZ','UZ','TM','KG','TJ','MN') THEN 'Europe & C.Asia'
      ELSE 'Other (RoW)'
    END
  END                                      AS market,
  IMPRESSIONS                              AS imps,
  CLICKS                                   AS clicks,
  -- USD → AUD @1.50, SGD → AUD @1.15, otherwise already AUD (advertiser currency).
  CASE CURRENCY
    WHEN 'USD' THEN REVENUE_ADV_CURRENCY * 1.50
    WHEN 'SGD' THEN REVENUE_ADV_CURRENCY * 1.15
    ELSE REVENUE_ADV_CURRENCY
  END                                      AS spend_aud,
  CONVERSIONS_TOTAL                        AS conversions,
  ENGAGEMENTS                              AS engagements,
  ACTIVE_VIEW_VIEWABLE_IMPRESSION          AS viewable_imps,
  CURRENCY                                 AS currency
FROM `bidbrain-analytics.raw_snowflake.dv360_apac`
WHERE ADVERTISER_NAME LIKE 'APAC | Schneider Electric%';
