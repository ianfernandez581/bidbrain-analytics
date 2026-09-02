-- Schneider Electric — CAMPAIGN -> internal PROGRAM, the first-match-wins tagging ladder, extracted
-- to ONE view (2026-09-02) so every consumer resolves a campaign the same way.
--
-- This is the SQL replica of the dashboard's original client-side idOf(): each delivering platform
-- campaign is tested against every seed_campaign_map row whose any '|'-token is a substring of the
-- (lowercased) campaign name, and the LOWEST `seq` wins — exactly "first row in array order wins".
--   * map       = seed_campaign_map (ALL 28 rows; seq = match precedence).
--   * camps     = every distinct campaign in stg_ad_delivery (all four platforms).
--   * camp_rank = campaign x every matching map row, ranked by seq.
--   * rn = 1    = the winner.
--
-- WHY IT IS ITS OWN VIEW: 20_pm_delivery inlined this ladder, and adding the campaign-grain Search
-- views (22 / 23) would have made three copies of the same precedence logic that must always agree —
-- the repo's "N copies must move together" failure mode. A Search detail table that disagreed with
-- the platform table above it is exactly the defect this prevents. 20 / 22 / 23 all read this view;
-- the tagging is defined once. It is DELIBERATELY unscoped (it maps EVERY delivering campaign,
-- including out-of-scope programs) — scoping is each consumer's `WHERE program IN (...)`, and the
-- unscoped rows are what 23_search_scope_audit needs to prove nothing fell through.
--
-- REMEMBER a campaign name is not a stable key (repo-wide rule): Transmission is progressively
-- prefixing names with the brief number, so tokens here should be substrings that survive that
-- (`2281_`, `2389_`, `2061_` are prefix tokens on purpose). Before editing any match_pattern,
-- simulate it against `SELECT DISTINCT campaign FROM stg_ad_delivery` and check BOTH what it catches
-- and what else claims those campaigns — see the client README's ind_edge / mcset worked examples.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.campaign_program` AS
WITH map AS (
  SELECT internal_campaign_id, seq, LOWER(match_pattern) AS pat
  FROM `bidbrain-analytics.client_schneider.seed_campaign_map`
),
camps AS (
  SELECT DISTINCT campaign FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
),
camp_rank AS (
  SELECT c.campaign, m.internal_campaign_id AS program, m.seq,
         ROW_NUMBER() OVER (PARTITION BY c.campaign ORDER BY m.seq) AS rn
  FROM camps c, map m
  WHERE EXISTS (
    SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
    WHERE TRIM(tok) != '' AND STRPOS(LOWER(c.campaign), TRIM(tok)) > 0)
)
SELECT campaign, program, seq FROM camp_rank WHERE rn = 1;
