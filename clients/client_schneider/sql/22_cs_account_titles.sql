-- Schneider Electric — TOP JOB TITLES PER ACCOUNT (the "Top accounts reached" card on the Content
-- Syndication tab). Client request 2026-09-01: "Under Top accounts reached, is it possible to
-- identify the top 1 or 2 job titles from each account?" — the answer is yes, from a field already
-- in the Salesforce feed. Nothing is inferred or modelled here.
--
-- Companion to view 21 (cs_audience), NOT part of it. cs_audience is a LONG one-value-per-row shape
-- (dim / value); a title belongs to a COMPANY, so it needs a two-level key and would have had to be
-- smuggled into `value` as a delimited string. A separate array is honest and lets the dashboard
-- rank titles itself.
--
-- GRAIN: campaign × market × company × title. One row per distinct title at an account, with the
-- number of leads that carried it. The dashboard sums across the selected markets and ranks, so
-- the ranking follows the Campaign dropdown and the Region chips exactly as the account totals do.
--
-- CASE FOLDING: grouped on UPPER(job_title) so "operations manager" and "Operations Manager" are one
-- title (2 of 342 spellings collide that way today). The DISPLAY form is MIN(), not ANY_VALUE() —
-- ANY_VALUE is non-deterministic and would make a client-facing label flicker run to run for no
-- reason (the cloudflare pacing-tier lesson).
--
-- COVERAGE: JOB_TITLE is 90.6% populated (997 of 1,101 flight-clamped leads). Leads with no title
-- are simply absent here, so per-account title counts can be LOWER than the account's lead total —
-- the dashboard states the shortfall rather than implying the titles cover every lead. Do NOT
-- COALESCE a missing title to 'Unknown': an invented bucket would rank against real ones.
--
-- PII: aggregated to a count per company. Never join a name/email back onto this — see the PII SCOPE
-- note in 17_stg_salesforce.sql.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.cs_account_titles` AS
SELECT
  campaign,
  market,
  company,
  MIN(job_title) AS job_title,
  COUNT(*)       AS leads
FROM `bidbrain-analytics.client_schneider.stg_salesforce`
WHERE company IS NOT NULL AND job_title IS NOT NULL
GROUP BY campaign, market, company, UPPER(job_title);
