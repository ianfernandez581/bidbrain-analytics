-- Schneider Electric "Liquid AI Data Center" (LQAIDC) -- staged Reddit Ads.
--
-- Live 2026-09-15. Source is WINDSOR (`raw_windsor.perf_reddit`), NOT Transmission's Snowflake
-- export, and that is not a preference -- the buy runs AU + IN + **BRAZIL**, and their export is
-- APAC-scoped, so it could never have carried the Brazil line. The account was granted and
-- readable in Windsor from day one; the three-day gap before this lane existed was our loader's
-- account list, not an access problem (see SELECT_ACCOUNTS in the reddit loader).
--
-- SPEND IS AUD, VERIFIED, AND NEEDS NO CONVERSION HERE. Windsor's field description for `spend`
-- says "USD", which is a generic doc string and wrong for this account. Three checks settled it
-- from our own warehouse rather than by asking the agency:
--   1. `account_currency` is a REAL per-account field, not a constant -- it returns USD for
--      Transmission_Cloudflare and AUD for both ResetData and this account.
--   2. It agrees with what we already independently report on both accounts where we know the
--      answer (ResetData's Reddit is AUD-native; Cloudflare reports USD).
--   3. Transmission_Cloudflare exists in BOTH feeds for 2026-04-01..06-30 and they reconcile to
--      0.21% on spend -- a trailing-attribution gap, not a currency gap (a wrong currency shows
--      as ~50%).
-- So this lane rides the dashboard's existing AUD->EUR shim exactly like LinkedIn and Trade Desk.
-- Google Search is the ONLY genuinely-USD source here and keeps its own in-view conversion; do
-- NOT copy that pattern into this file.
--
-- SCOPE IS ACCOUNT **AND** CAMPAIGN TOKEN, and both halves are load-bearing:
--   * the account id is the primary key, but an opaque Windsor id can be RE-MINTED on a re-grant
--     (it happened to the Cloudflare TTD seat), so the exact account name is an OR'd fallback;
--   * `LQAIDC` is required because "Schneider APAC AUD" is an ACCOUNT, not a brief -- a second
--     Schneider Reddit buy landing there would otherwise inflate every figure on this dashboard
--     silently. Same trap as `1958_SE_EntIT_*` sharing the Trade Desk export.
--
-- Country comes from the campaign name's 2-letter token (AU/IN/BR) and the tactic from the ad
-- group's targeting token (Whitelist / Interest). BOUNDARY-ANCHORED REGEX, never `LIKE '%_AU_%'`
-- -- `_` is a LIKE wildcard and a 2-letter code matches inside ordinary words (the repo-wide rule;
-- it cost Cloudflare a JP-vs-SAARC mis-resolution). Neither parser carries a real-value ELSE: an
-- unrecognised token reads `Unclassified` and stays VISIBLE, because a silent default turns a
-- naming change into misattribution instead of a question.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.stg_reddit` AS
SELECT
  'reddit'                                 AS platform,
  metric_date,
  CASE
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[ _-])AU([ _-]|$)') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[ _-])IN([ _-]|$)') THEN 'India'
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[ _-])BR([ _-]|$)') THEN 'Brazil'
    ELSE 'Unclassified'
  END                                      AS country,
  -- Every campaign is the plan's Reddit AWARENESS line (`_AWR_`). Parsed, not assumed, so a
  -- retargeting or consideration line added later does not quietly report as awareness.
  CASE
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[ _-])(AWR|AWARENESS)([ _-]|$)') THEN 'Awareness'
    WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'(^|[ _-])(RTG|RETARGETING)[0-9]*([ _-]|$)') THEN 'Retargeting'
    ELSE 'Unclassified'
  END                                      AS phase,
  -- The buy WITHIN the phase, from the ad group: Reddit is bought two ways per country here, and
  -- collapsing them would hide the whole reason there are two ad groups.
  CASE
    WHEN CONTAINS_SUBSTR(UPPER(ad_group_name), 'WHITELIST') THEN 'Subreddit whitelist'
    WHEN CONTAINS_SUBSTR(UPPER(ad_group_name), 'INTEREST')  THEN 'Interest targeting'
    ELSE 'Unclassified'
  END                                      AS tactic,
  campaign_name,
  ad_group_name,
  SUM(impressions)                         AS imps,
  SUM(clicks)                              AS clicks,
  -- AUD, per the header. `account_currency` is carried so a consumer can assert it rather than
  -- trust this comment.
  SUM(spend)                               AS spend_aud,
  ANY_VALUE(account_currency)              AS account_currency
FROM `bidbrain-analytics.raw_windsor.perf_reddit`
WHERE (account_id = 'a2_jl767nztzctc' OR account_name = 'Schneider APAC AUD')
  AND UPPER(campaign_name) LIKE '%LQAIDC%'
GROUP BY platform, metric_date, country, phase, tactic, campaign_name, ad_group_name;
