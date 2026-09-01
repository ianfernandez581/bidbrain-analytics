-- Schneider Electric — STAGING: Salesforce content-syndication leads (the CS lane, WIRED).
-- Filters the SHARED Salesforce CS mirror (raw_snowflake.salesforce_cs_apac_all holds EVERY client's
-- leads) to Schneider's 9 campaign IDs by INNER JOINing seed_salesforce_map on CAMPAIGN_ID. The join
-- attaches: campaign (internal_campaign_id — the 5 top-level programs) and programme (pillar_label —
-- the SF "programme" within a campaign), mirroring client_mongodb's campaign→programme model.
--
-- Join key = CAMPAIGN_ID (STRING). CAMPAIGN text is blank ('-'); display names come from the seed map.
-- DAY is already a DATE (weekly-batched feed). LEADS = 1 per row, so COUNT(*)==SUM(LEADS).
--
-- MARKET = normalized COUNTRY_NAME (verified live: AU/NZ/Australia only for SE; REGION is useless '-').
--   AU/AUSTRALIA -> 'Australia', NZ/NEW ZEALAND -> 'New Zealand', else -> 'Other'.
-- STATUS bucket from LEAD_STATUS (STRING; every SE lead is 'New' today — STATUS & LEAD_STATUS_SF are
--   INT64 numeric codes, all NULL, so they're excluded). Forward-compatible WHEN list; revisit when
--   the CRM grades leads to MQL/SQL/HQL.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_salesforce` AS
SELECT
  s.DAY                                        AS metric_date,
  s.CAMPAIGN_ID                                AS salesforce_campaign_id,
  m.internal_campaign_id                       AS campaign,
  m.pillar_label                               AS programme,
  CASE UPPER(TRIM(COALESCE(s.COUNTRY_NAME,'')))
    WHEN 'AU'          THEN 'Australia'
    WHEN 'AUSTRALIA'   THEN 'Australia'
    WHEN 'NZ'          THEN 'New Zealand'
    WHEN 'NEW ZEALAND' THEN 'New Zealand'
    WHEN ''            THEN 'Other'
    ELSE 'Other'
  END                                          AS market,
  COALESCE(s.LEADS, 1)                         AS leads,
  CASE UPPER(TRIM(COALESCE(s.LEAD_STATUS, '')))
    WHEN ''                THEN 'New'
    WHEN 'NEW'             THEN 'New'
    WHEN 'WORKING'         THEN 'Working'
    WHEN 'CONTACTED'       THEN 'Working'
    WHEN 'REPLIED'         THEN 'Working'
    WHEN 'NURTURE'         THEN 'Working'
    WHEN 'QUALIFIED'       THEN 'Qualified'
    WHEN 'MQL'             THEN 'Qualified'
    WHEN 'SQL'             THEN 'Qualified'
    WHEN 'ACCEPTED'        THEN 'Qualified'
    WHEN 'CONVERTED'       THEN 'Qualified'
    WHEN 'DISQUALIFIED'    THEN 'Disqualified'
    WHEN 'UNQUALIFIED'     THEN 'Disqualified'
    WHEN 'UNRESPONSIVE'    THEN 'Disqualified'
    WHEN 'DO NOT CONTACT'  THEN 'Disqualified'
    ELSE 'Other'
  END                                          AS status_bucket,
  -- AUDIENCE INTELLIGENCE fields (the Content Syndication tab; the Executive Scorecard tab they were
  -- built for was removed 2026-08-18). Verified populated for SE (re-measured 2026-09-01 over the
  -- 1,101 flight-clamped leads): COMPANY_NAME 100%, JOB_FUNCTION 100%, JOB_LEVEL ~40%,
  -- JOB_TITLE 90.6% (997/1,101); INDUSTRY/ASSET/STATE/REVENUE are empty for SE so are NOT
  -- surfaced. '' and '-' are normalised to NULL.
  --
  -- PII SCOPE. name / email / phone are deliberately dropped here and must stay dropped. JOB_TITLE
  -- was added 2026-09-01 at the client's request ("identify the top 1-2 job titles from each
  -- account" on the Top-accounts card) and it IS a step closer to a named individual than
  -- COMPANY_NAME alone - at a small account, "Chief Operating Officer" + the company name is one
  -- person. It is the client's own CRM field about their own leads, the dashboard is password-gated
  -- and the JSON lives in a private bucket, so the exposure does not change WHO can see it. Keep it
  -- that way: title is aggregated to a COUNT per company (view 22), never emitted per lead.
  CASE WHEN TRIM(COALESCE(s.COMPANY_NAME, '')) IN ('', '-') THEN NULL ELSE TRIM(s.COMPANY_NAME) END AS company,
  CASE WHEN TRIM(COALESCE(s.JOB_FUNCTION, '')) IN ('', '-') THEN NULL ELSE TRIM(s.JOB_FUNCTION) END AS job_function,
  CASE WHEN TRIM(COALESCE(s.JOB_LEVEL,    '')) IN ('', '-') THEN NULL ELSE TRIM(s.JOB_LEVEL)    END AS job_level,
  -- Free-text lead-form field: 342 distinct spellings over 997 leads, so titles are mostly unique
  -- per lead. Internal runs of whitespace are squashed (the only mechanical noise present - 0 rows
  -- carry a double space today, so this is forward protection); case is NOT folded here because a
  -- display form has to be chosen deterministically, which view 22 does when it groups.
  CASE WHEN TRIM(COALESCE(s.JOB_TITLE, '')) IN ('', '-') THEN NULL
       ELSE REGEXP_REPLACE(TRIM(s.JOB_TITLE), r'\s+', ' ') END AS job_title
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all` s
JOIN `bidbrain-analytics.client_schneider.seed_salesforce_map` m
  ON m.salesforce_campaign_id = s.CAMPAIGN_ID
-- CLAMP leads to the program's FLIGHT WINDOW (the same `seed_plan_budget` flight the dashboard's
-- "Flight windows across the portfolio" Gantt draws): only count leads from flight_start onward
-- (and up to flight_end where set). Pre-flight leads (e.g. EBA had 4 leads 2026-05-21..24 before its
-- 2026-05-25 start) are spillover and must NOT be counted. No seeded flight_start → no clamp (show all).
LEFT JOIN `bidbrain-analytics.client_schneider.seed_plan_budget` b
  ON b.internal_campaign_id = m.internal_campaign_id
WHERE (b.flight_start IS NULL OR s.DAY >= b.flight_start)
  AND (b.flight_end   IS NULL OR s.DAY <= b.flight_end);
