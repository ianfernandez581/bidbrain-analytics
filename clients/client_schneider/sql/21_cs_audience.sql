-- Schneider Electric — AUDIENCE INTELLIGENCE for the Executive Scorecard tab.
-- Reframes the CS leads from "how many" to "WHO we reached" — the lead-QUALITY story senior B2B
-- marketers value (Forrester: lead volume alone is a weak KPI). Built ENTIRELY from fields already
-- in the Salesforce feed (see stg_salesforce 17): the account (company), the job FUNCTION, and the
-- job LEVEL (seniority). Everything here is true source data — no fabrication.
--
-- LONG format, one row per campaign × market × dim × value, so the dashboard can filter by region
-- and aggregate the whole portfolio. dim ∈ {account, function, seniority}:
--   * account   — one row per company (the ABM "named accounts reached" hook). 100% populated.
--   * function  — job_function bucketed into ~7 clean groups. 100% populated.
--   * seniority — job_level bucketed to Executive / Director / Manager / Not disclosed (~40% disclosed;
--                 the undisclosed share is shown honestly rather than hidden).
-- Leads are already flight-clamped + scoped to SE's 9 campaigns by stg_salesforce (1 row per lead,
-- so COUNT(*) == leads).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.cs_audience` AS
WITH base AS (
  SELECT campaign, market, company, job_function, job_level
  FROM `bidbrain-analytics.client_schneider.stg_salesforce`
),
acct AS (
  SELECT campaign, market, 'account' AS dim, company AS value, COUNT(*) AS leads
  FROM base WHERE company IS NOT NULL
  GROUP BY campaign, market, company
),
func AS (
  SELECT campaign, market, 'function' AS dim,
    CASE
      WHEN CONTAINS_SUBSTR(UPPER(job_function), 'CYBER')                                  THEN 'Cybersecurity'
      WHEN CONTAINS_SUBSTR(UPPER(job_function), 'INFORMATION TECHNOLOGY')
        OR UPPER(job_function) = 'IT'
        OR CONTAINS_SUBSTR(UPPER(job_function), 'DATA &')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'ANALYTICS')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'OPERATIONAL TECHNOLOGY')                 THEN 'IT, Data & Analytics'
      WHEN CONTAINS_SUBSTR(UPPER(job_function), 'ENGINEER')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'MAINTENANCE')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'RELIABILITY')                            THEN 'Engineering & Maintenance'
      WHEN CONTAINS_SUBSTR(UPPER(job_function), 'MANUFACTUR')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'PRODUCTION')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'OPERATION')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'OIL')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'GAS')                                    THEN 'Operations & Manufacturing'
      WHEN CONTAINS_SUBSTR(UPPER(job_function), 'PROCUREMENT')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'PURCHAS')                                THEN 'Procurement & Supply'
      WHEN CONTAINS_SUBSTR(UPPER(job_function), 'PROJECT')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'STRATEGY')
        OR CONTAINS_SUBSTR(UPPER(job_function), 'PLANNING')                              THEN 'Project & Strategy'
      ELSE 'Other'
    END AS value,
    COUNT(*) AS leads
  FROM base WHERE job_function IS NOT NULL
  GROUP BY campaign, market, value
),
sen AS (
  SELECT campaign, market, 'seniority' AS dim,
    CASE
      WHEN job_level IS NULL                                                             THEN 'Not disclosed'
      WHEN CONTAINS_SUBSTR(UPPER(job_level), 'EXECUTIVE')
        OR CONTAINS_SUBSTR(UPPER(job_level), 'CHIEF')
        OR CONTAINS_SUBSTR(UPPER(job_level), 'CHAIRMAN')
        OR CONTAINS_SUBSTR(UPPER(job_level), 'PRESIDENT')
        OR CONTAINS_SUBSTR(UPPER(job_level), 'VP')
        OR CONTAINS_SUBSTR(UPPER(job_level), 'HEAD')                                      THEN 'Executive'
      WHEN CONTAINS_SUBSTR(UPPER(job_level), 'DIRECTOR')                                  THEN 'Director'
      WHEN CONTAINS_SUBSTR(UPPER(job_level), 'MANAGER')                                   THEN 'Manager'
      ELSE 'Other'
    END AS value,
    COUNT(*) AS leads
  FROM base
  GROUP BY campaign, market, value
)
SELECT * FROM acct
UNION ALL SELECT * FROM func
UNION ALL SELECT * FROM sen;
