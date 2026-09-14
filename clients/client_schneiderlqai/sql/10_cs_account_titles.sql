-- LQAIDC content syndication — TOP JOB TITLES PER ACCOUNT. Backs the "Top accounts" card's
-- per-account title list (client request 2026-09-14: an account view, plus performance by job title).
--
-- Companion to sql/09 (cs_audience), deliberately NOT part of it: cs_audience is a LONG
-- one-value-per-row shape (dim / value), and a title belongs to a COMPANY, so it needs a two-level
-- key and would otherwise have to be smuggled into `value` as a delimited string. A separate view is
-- honest and lets the dashboard rank titles itself.
--
-- GRAIN: vendor x region x company x title. One row per distinct title at an account, with the
-- number of leads carrying it. The dashboard sums across the selected regions and ranks, so the
-- ranking follows the region chips exactly as the account totals do.
--
-- CASE FOLDING: grouped on UPPER(job_title) so "operations manager" and "Operations Manager" are one
-- title. The DISPLAY form is MIN(), not ANY_VALUE() — ANY_VALUE is non-deterministic and would make
-- a client-facing label flicker run to run for no reason.
--
-- COVERAGE: a lead with no title is simply ABSENT here (sql/07 normalises '' and '-' to NULL), so an
-- account's per-title counts can sum to LESS than its lead total. The dashboard states that shortfall
-- rather than implying the titles cover every lead. Do NOT coalesce a missing title to 'Unknown' —
-- an invented bucket would rank against real ones.
--
-- PII: aggregated to a count per company. Never join a name or email back onto this — see the PII
-- SCOPE note in sql/07_stg_salesforce.sql.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.cs_account_titles` AS
SELECT
  vendor,
  region,
  company,
  MIN(job_title)                               AS job_title,
  COUNT(*)                                     AS leads
FROM `bidbrain-analytics.client_schneiderlqai.stg_salesforce`
WHERE company IS NOT NULL AND job_title IS NOT NULL
GROUP BY vendor, region, company, UPPER(job_title);
