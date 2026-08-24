-- HireRight - staged LinkedIn Ads (paid social). The account's audience is global
-- (NAM/EMEA/APAC combined) with no country column in the feed, so `market` is a flat
-- 'Global'. That is a REAL limitation of the source, not a parsing shortcut: do not
-- invent a market by reading the campaign name without first checking the actual
-- names (`SELECT DISTINCT campaign_name FROM stg_linkedin`) - a guessed geo token is
-- worse than an honest 'Global'.
--
-- The HireRight LinkedIn filter lives here once: ACCOUNT_NAME starts with "HireRight"
-- (case-insensitive). BigQuery has no ILIKE, so the brief's `ILIKE 'HireRight%'` is
-- expressed as LOWER(...) LIKE 'hireright%'. `scope_audit` (17) lists every distinct
-- account this matches, so a second HireRight account cannot join in unnoticed.
--
-- CURRENCY: LinkedIn has NO currency column in the mirror - the ACCOUNT NAME is the
-- only signal, so an `*_AUD` account is converted at the shared rate and everything
-- else is taken as USD. That is an assumption riding on a naming convention; if a
-- third currency ever appears it will be silently reported as USD. `scope_audit`
-- surfaces the account names so that assumption stays checkable.
--
-- CAMPAIGN NAMES ARE NOT STABLE KEYS (repo-wide rule): the brief-number prefix is
-- stripped into its own `brief` column - see 01_stg_dv360's header for why.
--
-- CREATIVE_TYPE is labelled for the creative-mix chart: 'STANDARD' = single image,
-- NULL/'' = video / other, anything else passes through. VIDEO_* and the lead-gen
-- fields are carried so the dashboard can build the engagement funnel.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_linkedin` AS
SELECT
  DATE(l.DAY)                              AS metric_date,
  REGEXP_REPLACE(TRIM(l.CAMPAIGN_NAME), r'^[0-9]+_', '')  AS campaign_name,
  NULLIF(REGEXP_EXTRACT(TRIM(l.CAMPAIGN_NAME), r'^([0-9]+)_'), '') AS brief,
  l.CAMPAIGN_NAME                          AS campaign_name_raw,
  'Global'                                 AS market,
  'Global'                                 AS region,
  CASE
    WHEN l.CREATIVE_TYPE = 'STANDARD' THEN 'Single Image'
    WHEN l.CREATIVE_TYPE IS NULL OR l.CREATIVE_TYPE = '' THEN 'Video / Other'
    ELSE l.CREATIVE_TYPE
  END                                      AS creative_type,
  l.IMPRESSIONS                            AS imps,
  l.CLICKS                                 AS clicks,
  -- `*_AUD` account -> USD at the shared rate, else already USD. cost_usd holds USD.
  CASE WHEN ENDS_WITH(l.ACCOUNT_NAME, '_AUD') THEN l.COSTS * fx.aud_usd
       ELSE l.COSTS END                    AS cost_usd,
  l.VIDEO_VIEWS                            AS video_views,
  l.VIDEO_STARTS                           AS video_starts,
  l.VIDEO_COMPLETIONS                      AS video_completions,
  l.ENGAGEMENTS                            AS engagements,
  -- Lead-gen FORM submissions. This is a direct, unambiguous outcome and is kept
  -- strictly separate from the two programmatic post-view conversion counts - see
  -- 04_stg_ad_delivery.
  l.LEADS                                  AS leads,
  l.LEAD_FORM_OPENS                        AS lead_form_opens,
  l.LINK_CLICKS                            AS link_clicks,
  l.ACTION_CLICKS                          AS action_clicks
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac` l
CROSS JOIN `bidbrain-analytics.client_hireright.fx` fx
WHERE LOWER(l.ACCOUNT_NAME) LIKE 'hireright%';
