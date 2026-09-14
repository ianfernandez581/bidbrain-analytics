-- LQAIDC content syndication — AUDIENCE INTELLIGENCE (client request 2026-09-14: "audience insight
-- where possible - performance by job title / job function and seniority").
--
-- LONG format, one row per vendor x region x dim x value, so the dashboard can scope by region chips
-- and aggregate without a second query. dim IN ('function', 'seniority', 'account'):
--   * function  — JOB_FUNCTION, bucketed to a small clean set.
--   * seniority — DERIVED FROM THE TITLE TEXT, not read from a field. See the block below.
--   * account   — one row per company; the "which accounts did we reach" view.
--
-- ================= SENIORITY IS DERIVED HERE, AND THAT MUST BE SAID ON SCREEN =================
-- client_schneider reads seniority straight from JOB_LEVEL. That field is EMPTY on every candidate
-- LQAI campaign (measured 2026-09-11 — every row '-'), so the same approach returns one bucket of
-- "Not disclosed" and answers nothing. JOB_TITLE, by contrast, is well populated here.
-- So seniority is parsed from the title, and three rules keep that honest:
--   1. The dashboard LABELS it as derived from job title. A derived field presented as a CRM field
--      is a claim the data does not support.
--   2. Order is most-senior-first and the arms are DELIMITER- or WORD-anchored, because 'Director'
--      appears inside 'Directorate' and 'Manager' inside 'Management Accountant'.
--   3. A title that matches nothing is 'Other', which is RENDERED, never dropped — the buckets must
--      sum to the lead count or the chart silently disagrees with the KPI above it.
-- If the client later supplies a real seniority field, replace this CASE and drop the screen label
-- in the same change.
-- ==============================================================================================
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.cs_audience` AS
WITH base AS (
  SELECT vendor, region, company, job_function, job_title
  FROM `bidbrain-analytics.client_schneiderlqai.stg_salesforce`
),
acct AS (
  SELECT vendor, region, 'account' AS dim, company AS value, COUNT(*) AS leads
  FROM base WHERE company IS NOT NULL
  GROUP BY vendor, region, company
),
func AS (
  SELECT vendor, region, 'function' AS dim,
    CASE
      WHEN job_function IS NULL THEN 'Not disclosed'
      WHEN REGEXP_CONTAINS(UPPER(job_function), r'INFORMATION TECHNOLOGY|^IT$|\bIT\b|TECHNOLOGY|TECHNICAL|DATA|DIGITAL') THEN 'IT & Technology'
      WHEN REGEXP_CONTAINS(UPPER(job_function), r'FACILIT|ESTATE|PROPERT|MAINTEN')                   THEN 'Facilities'
      WHEN REGEXP_CONTAINS(UPPER(job_function), r'ENGINEER')                                          THEN 'Engineering'
      WHEN REGEXP_CONTAINS(UPPER(job_function), r'OPERATION|MANUFACTUR|PRODUCTION')                   THEN 'Operations'
      WHEN REGEXP_CONTAINS(UPPER(job_function), r'ENERGY|SUSTAIN|ENVIRON')                            THEN 'Energy & Sustainability'
      WHEN REGEXP_CONTAINS(UPPER(job_function), r'FINANC|ACCOUNT|PROCURE|PURCHAS')                    THEN 'Finance & Procurement'
      ELSE 'Other'
    END AS value,
    COUNT(*) AS leads
  FROM base
  GROUP BY vendor, region, value
),
seniority AS (
  SELECT vendor, region, 'seniority' AS dim,
    CASE
      WHEN job_title IS NULL THEN 'Not disclosed'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'(^|[^A-Z])(CEO|CIO|CTO|COO|CFO|CDO|CISO)([^A-Z]|$)')   THEN 'C-suite'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'\bCHIEF\b|\bOWNER\b|\bFOUNDER\b')                    THEN 'C-suite'
      -- ===== VP MUST BE TESTED BEFORE THE 'PRESIDENT' ARM BELOW IT. =====
      -- `\bPRESIDENT\b` also matches the PRESIDENT inside "Vice President", so with the plain-word
      -- C-suite arm above it, EVERY VP was classified as C-suite. Caught 2026-09-14 before release
      -- by running the arms over the REAL title strings - "Vice President/SVP/EVP", "Vice President
      -- of Technology" and "Assistant Vice President Information Technology" all misfired.
      -- It fails in the FLATTERING direction (it inflates apparent C-suite reach on a client-facing
      -- chart) and nothing on screen would contradict it. BigQuery's RE2 has NO lookbehind, so the
      -- fix is ORDER, not a negative assertion: do not reorder these arms.
      -- A title carrying both ("EVP and Chief Financial Officer") resolves C-suite via the arms
      -- above, which is the convention.
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'(^|[^A-Z])(VP|SVP|EVP|AVP)([^A-Z]|$)|\bVICE PRESIDENT\b') THEN 'VP'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'\bPRESIDENT\b|\bPARTNER\b')                            THEN 'C-suite'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'\bDIRECTOR\b|\bDIRECTORS\b')                           THEN 'Director'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'\bHEAD OF\b|\bGENERAL MANAGER\b|(^|[^A-Z])GM([^A-Z]|$)') THEN 'Head / GM'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'\bMANAGER\b|\bLEAD\b|\bSUPERVISOR\b')                  THEN 'Manager'
      WHEN REGEXP_CONTAINS(UPPER(job_title), r'\bENGINEER\b|\bARCHITECT\b|\bSPECIALIST\b|\bANALYST\b|\bCONSULTANT\b|\bADMINISTRATOR\b|\bTECHNICIAN\b') THEN 'Practitioner'
      ELSE 'Other'
    END AS value,
    COUNT(*) AS leads
  FROM base
  GROUP BY vendor, region, value
)
SELECT * FROM acct
UNION ALL SELECT * FROM func
UNION ALL SELECT * FROM seniority;
