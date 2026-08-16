-- Secure Power — one row per LinkedIn AD SET, for the dashboard's "Targeting Breakdown" report.
--
-- The Reports tab reproduces a report the media buyer otherwise compiles by hand: click into every
-- ad set in Campaign Manager, screenshot the Audience panel, and retype it into a spreadsheet. This
-- view supplies the SKELETON of that report from real delivery (which ad sets exist, their current
-- name, phase, geo and flight) and LEFT JOINs the hand-recorded audience columns from
-- `seed_adset_targeting` (see ../load_targeting.py for why those are seeded and not fetched).
--
-- GRAIN: exactly one row per adset_id. `delivery` is deliberately aggregated and carries no ad-set
-- column (see its header), so this is the SEPARATE finer-grain view that comment calls for - not an
-- un-grouping of it. 36 rows today, so it is cheap to carry in the payload.
--
-- THE NAME IS NOT THE KEY. Transmission renames ad sets mid-flight (adset 859128356 delivered as
-- `SE_Industrial Edge_Awareness_AU` and later as `2463_SE_Industrial Edge Wave3_AWR_AU_image`), so
-- every name-derived field is resolved from the LATEST name the ad set delivered under and the
-- earlier names are kept in `aliases` rather than being silently dropped. Grouping on the name
-- instead would split one ad set into two report rows. Repo rule: "campaign names are NOT stable
-- keys" (md/AGENTS.md).
--
-- PHASE tokens are matched most-specific-first. Retargeting before Conversion before Consideration
-- before Awareness, because 'CONVERSION' CONTAINS 'CON' - a Consideration-first test mislabels every
-- conversion ad set. Short tokens are delimiter-anchored so 'CON' cannot match inside a word. The
-- same ladder is mirrored in load_targeting.py's phase_of() (it only pre-fills the CSV's reference
-- column; THIS view is what reaches the screen). Enterprise IT's ad sets carry a vertical
-- (Hero / Generic / Manufacturing / ...) rather than a funnel phase, so they land on 'Unspecified'
-- by design - that is true, not a parse failure.
--
-- GEO comes from the same market parser the delivery views use (stg_linkedin), taken from the latest
-- name. An ad set renamed from `..._AU` to `..._ANZ_image` therefore reads ANZ, which is what the
-- platform says today; the AU-era name stays visible in `aliases`.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneidersecpwr.linkedin_adsets` AS
WITH per_adset AS (
  SELECT
    adset_id,
    ANY_VALUE(campaign)                                         AS campaign,
    -- Current identity = the name/market carried by the most recent delivering row.
    ARRAY_AGG(STRUCT(adset_name, market, group_name)
              ORDER BY metric_date DESC, imps DESC LIMIT 1)[OFFSET(0)] AS cur,
    ARRAY_AGG(DISTINCT adset_name IGNORE NULLS)                 AS all_names,
    MIN(metric_date)                                            AS first_delivery,
    MAX(metric_date)                                            AS last_delivery,
    SUM(imps)                                                   AS imps,
    SUM(clicks)                                                 AS clicks,
    SUM(spend_aud)                                              AS spend_aud,
    SUM(leads)                                                  AS leads
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_linkedin`
  WHERE adset_id IS NOT NULL
  GROUP BY adset_id
)
SELECT
  a.adset_id,
  a.campaign,
  a.cur.adset_name                                              AS adset_name,
  a.cur.group_name                                              AS group_name,
  a.cur.market                                                  AS geo,
  CASE
    WHEN REGEXP_CONTAINS(UPPER(a.cur.adset_name), r'(^|[ _-])(RTG|RT1|RT2)([ _-]|$)')
      OR CONTAINS_SUBSTR(UPPER(a.cur.adset_name), 'RETARGET')            THEN 'Retargeting'
    WHEN REGEXP_CONTAINS(UPPER(a.cur.adset_name), r'(^|[ _-])CNV([ _-]|$)')
      OR CONTAINS_SUBSTR(UPPER(a.cur.adset_name), 'CONVERSION')          THEN 'Conversion'
    WHEN REGEXP_CONTAINS(UPPER(a.cur.adset_name), r'(^|[ _-])(CNS|CON)([ _-]|$)')
      OR CONTAINS_SUBSTR(UPPER(a.cur.adset_name), 'CONSIDERATION')       THEN 'Consideration'
    WHEN REGEXP_CONTAINS(UPPER(a.cur.adset_name), r'(^|[ _-])AWR([ _-]|$)')
      OR CONTAINS_SUBSTR(UPPER(a.cur.adset_name), 'AWARENESS')           THEN 'Awareness'
    ELSE 'Unspecified'
  END                                                           AS phase,
  -- Prior names this ad set delivered under, current name excluded. Empty for an ad set never renamed.
  ARRAY(SELECT n FROM UNNEST(a.all_names) n WHERE n <> a.cur.adset_name ORDER BY n) AS aliases,
  a.first_delivery,
  a.last_delivery,
  a.imps,
  a.clicks,
  a.spend_aud,
  a.leads,
  -- Hand-recorded audience configuration. NULL (not '') when the buyer has not filled a cell in, so
  -- the dashboard can say "not yet recorded" instead of printing a convincing-looking blank.
  NULLIF(TRIM(t.targeting_method),  '')                         AS targeting_method,
  NULLIF(TRIM(t.job_titles),        '')                         AS job_titles,
  NULLIF(TRIM(t.job_seniorities),   '')                         AS job_seniorities,
  NULLIF(TRIM(t.job_functions),     '')                         AS job_functions,
  NULLIF(TRIM(t.industries),        '')                         AS industries,
  NULLIF(TRIM(t.company_list),      '')                         AS company_list,
  NULLIF(TRIM(t.exclusions),        '')                         AS exclusions,
  NULLIF(TRIM(t.audience_size),     '')                         AS audience_size,
  NULLIF(TRIM(t.notes),             '')                         AS notes,
  -- One flag the UI keys off, rather than re-deriving "is anything filled in?" in three places.
  (COALESCE(NULLIF(TRIM(t.job_titles), ''), NULLIF(TRIM(t.job_seniorities), ''),
            NULLIF(TRIM(t.job_functions), ''), NULLIF(TRIM(t.industries), ''),
            NULLIF(TRIM(t.company_list), ''), NULLIF(TRIM(t.targeting_method), '')) IS NOT NULL)
                                                                AS has_targeting
FROM per_adset a
LEFT JOIN `bidbrain-analytics.client_schneidersecpwr.seed_adset_targeting` t
  ON t.adset_id = a.adset_id;
