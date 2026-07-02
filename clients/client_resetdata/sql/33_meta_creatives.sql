-- ResetData — Meta creatives WITH preview thumbnails: the creative gallery on the Paid Media tab.
--
-- The existing meta_creative view groups by creative_name for the mix chart; this one is the visual
-- gallery — one row per creative_id carrying the actual ad: thumbnail image + title + body copy +
-- destination link, alongside delivery + the "Signup Button" lead conversions. 39 creatives, all with
-- a thumbnail. reads raw_windsor.perf_meta directly (stg_meta drops the thumbnail/url columns).
--
-- CAVEAT: creative_thumbnail_url is a Meta CDN URL that can EXPIRE. We take the MOST RECENT non-null
-- thumbnail per creative (ARRAY_AGG ... ORDER BY metric_date DESC) so each export refreshes the URL;
-- as long as Meta ingestion keeps running the images stay live. If Meta ingestion stalls, some may 404.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.meta_creatives` AS
WITH agg AS (
  SELECT
    creative_id,
    ANY_VALUE(NULLIF(creative_title, ''))                                                              AS title,
    ANY_VALUE(NULLIF(creative_body, ''))                                                               AS body,
    ARRAY_AGG(NULLIF(creative_thumbnail_url, '') IGNORE NULLS ORDER BY metric_date DESC LIMIT 1)[SAFE_OFFSET(0)] AS thumbnail_url,
    ARRAY_AGG(NULLIF(creative_link_url, '')      IGNORE NULLS ORDER BY metric_date DESC LIMIT 1)[SAFE_OFFSET(0)] AS link_url,
    SUM(impressions)                AS imps,
    SUM(clicks)                     AS clicks,
    SUM(link_clicks)                AS link_clicks,
    ROUND(SUM(cost), 2)             AS spend_aud,
    SUM(signup_button_conversions)  AS conversions
  FROM `bidbrain-analytics.raw_windsor.perf_meta`
  WHERE account_name = 'Reset backup – Ad account'
  GROUP BY creative_id
)
SELECT * FROM agg
WHERE imps > 0
ORDER BY imps DESC;
