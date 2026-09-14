-- LQAIDC content syndication — STAGING: the Salesforce CS leads (added 2026-09-14, client request
-- "add content syndication to the board ... all are submitted via CaptureIQ").
--
-- The lead path is vendor -> CaptureIQ -> Integrate -> Salesforce, and Salesforce mirrors into the
-- SHARED `raw_snowflake.salesforce_cs_apac_all`, which holds EVERY client's leads (Cloudflare,
-- MongoDB and all three Schneider books). Scope is therefore an INNER JOIN against this client's own
-- seeded campaign-ID list — never a name filter.
--
-- WHY A SEED AND NOT A NAME: Schneider's uploads carry a BLANK `CAMPAIGN` ('-') on every row. 73,260
-- of the mirror's 83,079 rows have no campaign name at all, and every Schneider row is among them
-- (Cloudflare's carry full descriptive names, which is why a name filter works there and cannot work
-- here). Measured 2026-09-11. So the campaign ID is the only key, and it has to be stated.
--
-- THE ID IS PROVISIONAL. `seed_cs_campaign_map.confirmed` is 0 until the client confirms it. The
-- export job carries that flag through and the dashboard shows a visible pending banner — it is NOT
-- a silent assumption. Pangea also delivers Schneider's C&SP programme (brief 1957), so a wrong ID
-- would publish another programme's leads under this campaign. See the seed CSV's note column.
--
-- PII SCOPE — same rule as client_schneider/sql/17: FIRST_NAME, LAST_NAME, EMAIL, PHONE and
-- ENRICHED_PHONE_NUMBER are deliberately DROPPED here and must stay dropped. JOB_TITLE is carried
-- because the client asked for performance by job title, and it IS one step closer to a named
-- individual than COMPANY_NAME alone — at a small account, a title plus the company is one person.
-- It is the client's own CRM field about their own leads, the dashboard is password-gated and the
-- JSON lives in a private bucket, so this does not change WHO can see it. Keep it that way: titles
-- are only ever aggregated to a COUNT per company (sql/11), never emitted per lead.
--
-- LEADS = 1 per row (the mirror's LEADS column is 1 or NULL), so COUNT(*) == SUM(leads).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.stg_salesforce` AS
SELECT
  s.DAY                                        AS metric_date,
  s.CAMPAIGN_ID                                AS salesforce_campaign_id_raw,
  REGEXP_EXTRACT(s.CAMPAIGN_ID, r'^([A-Za-z0-9]+)') AS salesforce_campaign_id,
  -- The suffix itself, kept rather than discarded: ' replace' and '(Rejected)' plausibly mean
  -- different things for whether a lead counts as delivered, and that is a question for
  -- Transmission, not an assumption to bury in a regex. NULL for the normal case.
  NULLIF(TRIM(REGEXP_REPLACE(s.CAMPAIGN_ID, r'^[A-Za-z0-9]+', '')), '') AS campaign_id_suffix,
  m.vendor                                     AS vendor,
  -- COUNTRY: the mirror mixes ISO-2 codes and full names in the same column (it carries 'AU' and
  -- 'Australia' on different rows of the same campaign), so both forms are folded to ONE display
  -- name. An unmapped value becomes 'Other' and stays VISIBLE — never dropped, or the market rows
  -- stop summing to the headline count.
  CASE UPPER(TRIM(COALESCE(s.COUNTRY_NAME, '')))
    WHEN 'AU' THEN 'Australia'   WHEN 'AUSTRALIA'    THEN 'Australia'
    WHEN 'NZ' THEN 'New Zealand' WHEN 'NEW ZEALAND'  THEN 'New Zealand'
    WHEN 'IN' THEN 'India'       WHEN 'INDIA'        THEN 'India'
    WHEN 'BR' THEN 'Brazil'      WHEN 'BRAZIL'       THEN 'Brazil'
    WHEN 'CL' THEN 'Chile'       WHEN 'CHILE'        THEN 'Chile'
    WHEN 'AE' THEN 'UAE'         WHEN 'UNITED ARAB EMIRATES' THEN 'UAE'
    WHEN 'SA' THEN 'Saudi Arabia' WHEN 'SAUDI ARABIA' THEN 'Saudi Arabia'
    -- '' and '-' are the mirror's two empty sentinels and mean NOT SUPPLIED, which is a different
    -- claim from "a country outside the plan" - folding them into 'Other' would assert the latter.
    -- Verified live 2026-09-14: 2 of 43 leads carry '-'. Both buckets are rendered, never dropped,
    -- or the market rows stop summing to the headline lead count.
    WHEN '' THEN 'Not disclosed' WHEN '-' THEN 'Not disclosed'
    ELSE 'Other'
  END                                          AS country,
  -- REGION: the CS buy is allocated by PANGEA'S four regions (ANZ 68 / India 235 / MEA 18 / SAM 79
  -- = 400 leads), which are NOT the same as the paid board's four (Pacific / India / MEA / South
  -- America). The difference is real and deliberate: Pangea's ANZ includes New Zealand, which the
  -- paid campaign does not run in. Do NOT reuse sql/03_delivery's region CASE here — pacing CS
  -- against a region the plan does not allocate would be wrong in both directions.
  CASE UPPER(TRIM(COALESCE(s.COUNTRY_NAME, '')))
    WHEN 'AU' THEN 'ANZ'   WHEN 'AUSTRALIA'    THEN 'ANZ'
    WHEN 'NZ' THEN 'ANZ'   WHEN 'NEW ZEALAND'  THEN 'ANZ'
    WHEN 'IN' THEN 'India' WHEN 'INDIA'        THEN 'India'
    WHEN 'BR' THEN 'SAM'   WHEN 'BRAZIL'       THEN 'SAM'
    WHEN 'CL' THEN 'SAM'   WHEN 'CHILE'        THEN 'SAM'
    WHEN 'AE' THEN 'MEA'   WHEN 'UNITED ARAB EMIRATES' THEN 'MEA'
    WHEN 'SA' THEN 'MEA'   WHEN 'SAUDI ARABIA' THEN 'MEA'
    WHEN '' THEN 'Not disclosed' WHEN '-' THEN 'Not disclosed'
    ELSE 'Other'
  END                                          AS region,
  COALESCE(s.LEADS, 1)                         AS leads,
  -- STATUS: forward-compatible bucket. Every Schneider lead is CRM-raw 'New' today (STATUS and
  -- LEAD_STATUS_SF are INT64 and all-NULL, so they are excluded). Revisit when the CRM grades these.
  CASE UPPER(TRIM(COALESCE(s.LEAD_STATUS, '')))
    WHEN ''               THEN 'New'
    WHEN 'NEW'            THEN 'New'
    WHEN 'WORKING'        THEN 'Working'
    WHEN 'CONTACTED'      THEN 'Working'
    WHEN 'REPLIED'        THEN 'Working'
    WHEN 'NURTURE'        THEN 'Working'
    WHEN 'QUALIFIED'      THEN 'Qualified'
    WHEN 'MQL'            THEN 'Qualified'
    WHEN 'SQL'            THEN 'Qualified'
    WHEN 'ACCEPTED'       THEN 'Qualified'
    WHEN 'CONVERTED'      THEN 'Qualified'
    WHEN 'DISQUALIFIED'   THEN 'Disqualified'
    WHEN 'UNQUALIFIED'    THEN 'Disqualified'
    WHEN 'UNRESPONSIVE'   THEN 'Disqualified'
    WHEN 'DO NOT CONTACT' THEN 'Disqualified'
    ELSE 'Other'
  END                                          AS status_bucket,
  -- AUDIENCE fields. '' and '-' are the mirror's two empty sentinels and BOTH normalise to NULL —
  -- a lead with no title is ABSENT from the title rollups, never coalesced to an invented 'Unknown'
  -- that would rank against real values.
  -- NB JOB_LEVEL is EMPTY on every candidate LQAI campaign (measured 2026-09-11), unlike the
  -- Schneider Pacific book where it is ~40% populated. Seniority is therefore DERIVED from the
  -- title text in sql/10 and labelled as derived on screen.
  CASE WHEN TRIM(COALESCE(s.COMPANY_NAME, '')) IN ('', '-') THEN NULL ELSE TRIM(s.COMPANY_NAME) END AS company,
  CASE WHEN TRIM(COALESCE(s.JOB_FUNCTION, '')) IN ('', '-') THEN NULL ELSE TRIM(s.JOB_FUNCTION) END AS job_function,
  CASE WHEN TRIM(COALESCE(s.JOB_LEVEL,    '')) IN ('', '-') THEN NULL ELSE TRIM(s.JOB_LEVEL)    END AS job_level,
  -- Free-text lead-form field: runs of internal whitespace squashed (the only mechanical noise seen
  -- in this feed). Case is NOT folded here — a display spelling has to be chosen deterministically,
  -- which sql/11 does when it groups.
  CASE WHEN TRIM(COALESCE(s.JOB_TITLE, '')) IN ('', '-') THEN NULL
       ELSE REGEXP_REPLACE(TRIM(s.JOB_TITLE), r'\s+', ' ') END                                     AS job_title
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all` s
-- MATCH ON THE ID'S BASE, NOT THE RAW STRING. CAMPAIGN_ID in this feed sometimes carries a
-- handling suffix appended by whoever prepares the upload - measured 2026-09-14, eight distinct
-- suffixed values exist, in two spellings: a bare ' replace' (7 of them) and a parenthesised
-- '(Rejected)'. An exact-match join drops those rows SILENTLY - it cannot error, because the value
-- is a perfectly good string that simply matches nothing. It is doing exactly that on
-- client_mongodb today: its four-id IN list understates that dashboard's lead count by 29 (2.7%).
-- No Schneider id has a suffixed variant yet, so this is forward protection - but this lane is
-- brand new and its vendor's leads have not started arriving, so it is protection we will need
-- before we would notice needing it.
-- Same class as the repo-wide "campaign names are NOT stable keys" rule (md/AGENTS.md), applied to
-- ids: normalise ONCE at the staging boundary and let everything downstream read the clean value.
JOIN `bidbrain-analytics.client_schneiderlqai.seed_cs_campaign_map` m
  ON m.salesforce_campaign_id = REGEXP_EXTRACT(s.CAMPAIGN_ID, r'^([A-Za-z0-9]+)')
-- FLIGHT CLAMP: only count leads inside the seeded vendor flight. A vendor's Salesforce campaign can
-- carry spillover from before it started delivering for this brief (the client_schneider EBA
-- precedent: 4 leads landed before its flight start). A blank seeded date means no clamp on that end.
WHERE (m.flight_start IS NULL OR s.DAY >= m.flight_start)
  AND (m.flight_end   IS NULL OR s.DAY <= m.flight_end);
