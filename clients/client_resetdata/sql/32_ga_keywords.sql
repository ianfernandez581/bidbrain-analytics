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
WITH kw AS (
  SELECT ad_group_criterion_criterion_id AS cid,
    ANY_VALUE(ad_group_criterion_keyword_text)       AS keyword,
    ANY_VALUE(ad_group_criterion_keyword_match_type) AS match_type
  FROM `bidbrain-analytics.raw_google_ads.ads_Keyword_3451896252`
  WHERE customer_id = 1054407474
  GROUP BY cid
),
st AS (
  SELECT ad_group_criterion_criterion_id AS cid,
    SUM(metrics_impressions)                 AS imps,
    SUM(metrics_clicks)                      AS clicks,
    ROUND(SUM(metrics_cost_micros) / 1e6, 2) AS spend_aud,
    ROUND(SUM(metrics_conversions), 1)       AS conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_KeywordBasicStats_3451896252`
  WHERE customer_id = 1054407474
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
