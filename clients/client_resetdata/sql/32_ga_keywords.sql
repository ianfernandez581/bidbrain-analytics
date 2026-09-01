-- ResetData — Google Ads keywords: the "who we targeted" panel on the Paid Media tab.
--
-- For a search-heavy B2B account the real "targeting" is the search intent we bid on, so this
-- surfaces the top keywords (text + match type) with their delivery + conversions. Far more
-- meaningful here than audience segments (which for search are sparse and need extra dimension
-- tables to resolve). Reveals what converts: e.g. "sovereign ai solutions" / "ai consulting
-- australia" drive leads; brand ("resetdata") drives the most clicks.
--
-- Source = native DTS: ads_Keyword (the keyword text + match type) joined to ads_KeywordBasicStats
-- (metrics) on the ad-group-criterion id, scoped to ResetData's customer_id 1054407474. cost_micros
-- -> AUD via /1e6. Aggregated across ad groups by (keyword, match_type) so a keyword used in several
-- ad groups shows once. Top 50 by impressions (the dashboard shows the leaders).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga_keywords` AS
-- TWO table sets, split on one cutover (2026-08-31): the MCC-wide set froze at 2026-08-24 when
-- Google stopped serving metrics at manager level, and Reset Data's own per-account set takes
-- over from 08-25. Reading only one of them would either drop the history or double-count the
-- overlap a DTS refresh window creates. Same cutover as raw_google_ads.perf_google_ads.
-- NOTE the asymmetry with st_src below, and do not "tidy" it: ads_Keyword_* is a DIMENSION
-- table (criterion id -> text + match type) and carries NO segments_date, so the cutover
-- predicate that belongs on the stats tables fails the view outright here (400 Unrecognized
-- name: segments_date). No date split is needed either - the kw CTE below collapses both
-- sets with GROUP BY cid + ANY_VALUE, so a criterion in both resolves to one row.
WITH kw_src AS (
  SELECT ad_group_criterion_criterion_id, ad_group_criterion_keyword_text, ad_group_criterion_keyword_match_type
  FROM `bidbrain-analytics.raw_google_ads.ads_Keyword_3451896252`
  WHERE customer_id = 1054407474
  UNION ALL
  SELECT ad_group_criterion_criterion_id, ad_group_criterion_keyword_text, ad_group_criterion_keyword_match_type
  FROM `bidbrain-analytics.raw_google_ads.ads_Keyword_1054407474`
),
st_src AS (
  SELECT ad_group_criterion_criterion_id, metrics_impressions, metrics_clicks, metrics_cost_micros, metrics_conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_KeywordBasicStats_3451896252`
  WHERE customer_id = 1054407474 AND segments_date <= DATE '2026-08-24'
  UNION ALL
  SELECT ad_group_criterion_criterion_id, metrics_impressions, metrics_clicks, metrics_cost_micros, metrics_conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_KeywordBasicStats_1054407474`
  WHERE segments_date >= DATE '2026-08-25'
),
kw AS (
  SELECT ad_group_criterion_criterion_id AS cid,
    ANY_VALUE(ad_group_criterion_keyword_text)       AS keyword,
    ANY_VALUE(ad_group_criterion_keyword_match_type) AS match_type
  FROM kw_src
  GROUP BY cid
),
st AS (
  SELECT ad_group_criterion_criterion_id AS cid,
    SUM(metrics_impressions)                 AS imps,
    SUM(metrics_clicks)                      AS clicks,
    ROUND(SUM(metrics_cost_micros) / 1e6, 2) AS spend_aud,
    ROUND(SUM(metrics_conversions), 1)       AS conversions
  FROM st_src
  GROUP BY cid
)
SELECT
  kw.keyword,
  kw.match_type,
  SUM(st.imps)        AS imps,
  SUM(st.clicks)      AS clicks,
  ROUND(SUM(st.spend_aud), 2)   AS spend_aud,
  ROUND(SUM(st.conversions), 1) AS conversions
FROM st JOIN kw USING (cid)
WHERE kw.keyword IS NOT NULL
GROUP BY kw.keyword, kw.match_type
HAVING imps > 0
ORDER BY imps DESC
LIMIT 50;
