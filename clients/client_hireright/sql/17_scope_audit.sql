-- HireRight - SCOPE AUDIT. One row per (source, matched entity) that this client's
-- three filters currently sweep in, with its volume and window.
--
-- WHY: two of the three filters are SUBSTRING / prefix matches on a human-typed name -
--     DV360     LOWER(ADVERTISER_NAME) LIKE '%hireright%'
--     LinkedIn  LOWER(ACCOUNT_NAME)    LIKE 'hireright%'
--     TradeDesk ADVERTISER_NAME = 'HireRight'          (exact - the safe one)
-- so a second HireRight advertiser, a renamed account, or a test/staging entity would
-- start contributing to every KPI on the dashboard with nothing on screen changing.
-- The failure is silent and in the WRONG direction: numbers go UP, which looks like
-- performance rather than a bug.
--
-- This view does not filter anything - it makes the current scope legible. The export
-- job prints it as a WARNING line every run, so widening shows up in the job log, and
-- it gives the status pipeline something to check that is NOT a mirror of the view's
-- own parse (the repo rule against circular accuracy checks - see AGENTS.md).
--
-- currency_forms is the tell for the LinkedIn currency assumption: LinkedIn has no
-- currency column, so `*_AUD` in the ACCOUNT NAME is the only signal and anything else
-- is taken as USD. More than one distinct form here means that assumption needs review.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.scope_audit` AS
SELECT
  'dv360'                                  AS source,
  'ADVERTISER_NAME'                        AS matched_on,
  ADVERTISER_NAME                          AS entity,
  COUNT(*)                                 AS rows_matched,
  MIN(DATE(DAY))                           AS first_day,
  MAX(DATE(DAY))                           AS last_day,
  COUNT(DISTINCT CAMPAIGN_NAME)            AS campaigns,
  STRING_AGG(DISTINCT CURRENCY ORDER BY CURRENCY) AS currency_forms
FROM `bidbrain-analytics.raw_snowflake.dv360_apac`
WHERE LOWER(ADVERTISER_NAME) LIKE '%hireright%'
GROUP BY ADVERTISER_NAME
UNION ALL
SELECT
  'tradedesk',
  'ADVERTISER_NAME',
  ADVERTISER_NAME,
  COUNT(*),
  MIN(DATE(DAY)),
  MAX(DATE(DAY)),
  COUNT(DISTINCT CAMPAIGN_NAME),
  STRING_AGG(DISTINCT CURRENCY ORDER BY CURRENCY)
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
WHERE ADVERTISER_NAME = 'HireRight'
GROUP BY ADVERTISER_NAME
UNION ALL
SELECT
  'linkedin',
  'ACCOUNT_NAME',
  ACCOUNT_NAME,
  COUNT(*),
  MIN(DATE(DAY)),
  MAX(DATE(DAY)),
  COUNT(DISTINCT CAMPAIGN_NAME),
  -- LinkedIn has no CURRENCY column; the account-name suffix is the only signal.
  ANY_VALUE(CASE WHEN ENDS_WITH(ACCOUNT_NAME, '_AUD') THEN 'AUD (from account name)'
                 ELSE 'USD (assumed)' END)
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE LOWER(ACCOUNT_NAME) LIKE 'hireright%'
GROUP BY ACCOUNT_NAME
ORDER BY source, rows_matched DESC;
