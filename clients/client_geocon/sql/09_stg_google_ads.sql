-- 09_stg_google_ads: the Geocon slice of the native BigQuery Data Transfer (DTS) Google Ads
-- export. Added 2026-08-24 for Northbourne Gateway, which buys TWO Google lines -- YouTube
-- awareness video (A$12,000 / 266,667 imps / plan CPV A$0.50) and Canberra-investor search
-- (A$16,500 / 350 clicks / plan CTR 2.5%), plus a A$7,500 management fee that is not media.
--
-- SOURCE IS DTS, NOT WINDSOR, and that is deliberate. Geocon Group (customer_id 5457742070) is
-- ALREADY linked under the MCC 3451896252 that DTS mirrors and it refreshes daily and free;
-- raw_windsor.perf_google_ads is a laptop-run fallback loader that last ran 2026-06-06 and does
-- not carry the account at all.
--
-- THE THREE NORTHBOURNE CAMPAIGNS ALREADY EXIST AND ARE PAUSED (verified 2026-08-24):
--   0201_Geocon_NGW558_ANZ_YouTube_AWR                (VIDEO)
--   0201_Geocon_NGW558_National_SearchBrand_CNV       (SEARCH)
--   0201_Geocon_NGW558_National_SearchNonBrand_CNV    (SEARCH)
-- They carry zero stats rows until they are switched on, so this view returns nothing yet. The
-- naming is what the `NGW558` / `0201_` tokens in targets/property_map.csv were written against.
--
-- ***p_ads_CampaignBasicStats, NOT p_ads_CampaignStats.*** CampaignStats is additionally segmented
-- by click_type, which DUPLICATES impressions across rows: summed over one week of a live account
-- it reported 22,892 impressions where BasicStats reported the true 21,008. Clicks happen to
-- agree, so the error is silent on the metric most people spot-check. BasicStats is segmented only
-- by date / device / network / slot and is additive.
--
-- ***VIDEO VIEWS ARE AVAILABLE - correcting an earlier note that said they were not (2026-08-31).***
-- They are absent from CampaignBasicStats and CampaignStats, and the MCC-wide VideoStats table was
-- EMPTY, which is where the old "no video metric exists in any source" conclusion came from. The
-- PER-ACCOUNT table set carries them: `p_ads_VideoNonClickStats_<customer_id>` has
-- `metrics_video_trueview_views`, the view rate, the average CPV and all four completion quartiles.
-- Verified on the live YouTube line: 16,547 TrueView views at A$0.072 CPV over 2026-08-26..08-29.
--
-- ONLY THE COUNT IS CARRIED. `video_views` is additive and every rate is re-derived downstream from
-- summed components (view rate = views / impressions, CPV = spend / views) - the repo-wide rule that
-- a RATE must never enter a fact table, because every consumer SUMs these rows by day and channel.
-- The quartile columns are rates whose denominator (video-capable impressions) is NOT in that table,
-- so they cannot be multiplied back to counts here and are deliberately left out rather than carried
-- as un-summable rates.
--
-- `video_3s_views` / `video_completes` stay NULL: those are META's 3-second-view and completion
-- events, and a TrueView view (30s, or the full ad, or an interaction) is a DIFFERENT event. Folding
-- one into the other would put two incomparable metrics in one column.
--
-- Cost is micros -> AUD (the account's own currency; no FX step). Conversions are carried and
-- LABELLED as Google-reported conversions, never folded into `leads` -- Northbourne's lead lane is
-- Meta + LinkedIn lead forms, and silently summing search conversions into it would double-count
-- an enquiry that also filled in the Meta form.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_google_ads` AS
WITH map AS (
  SELECT seq, property_key, LOWER(match_pattern) AS pat
  FROM `bidbrain-analytics.client_geocon.seed_property_map`
  WHERE COALESCE(match_pattern, '') != ''
),
camp AS (
  SELECT DISTINCT campaign_id, campaign_name, campaign_advertising_channel_type AS ch_type, campaign_status
  FROM `bidbrain-analytics.raw_google_ads.p_ads_Campaign_3451896252`
  WHERE customer_id = 5457742070
),
names AS (SELECT DISTINCT campaign_name AS nm FROM camp),
nm_rank AS (
  SELECT n.nm, m.property_key, ROW_NUMBER() OVER (PARTITION BY n.nm ORDER BY m.seq) AS rn
  FROM names n, map m
  WHERE EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(LOWER(n.nm), TRIM(tok)) > 0)
),
nm_map AS (SELECT nm, property_key FROM nm_rank WHERE rn = 1),
stats AS (
  SELECT campaign_id, segments_date AS date,
         SUM(metrics_impressions)                AS impressions,
         SUM(metrics_clicks)                     AS clicks,
         SUM(metrics_cost_micros) / 1e6          AS spend,
         SUM(metrics_conversions)                AS conversions,
         SUM(metrics_view_through_conversions)   AS view_through_conversions
  FROM `bidbrain-analytics.raw_google_ads.p_ads_CampaignBasicStats_3451896252`
  WHERE customer_id = 5457742070
  GROUP BY 1, 2
),
-- TrueView views per campaign x day, both accounts. LEFT JOINed below so a non-video campaign keeps
-- a NULL (not measured) rather than a 0 (measured, none) - the nullness rule the dashboard reads.
vid AS (
  SELECT campaign_id, segments_date AS date, SUM(metrics_video_trueview_views) AS video_views
  FROM (
    SELECT campaign_id, segments_date, metrics_video_trueview_views
    FROM `bidbrain-analytics.raw_google_ads.p_ads_VideoNonClickStats_5457742070` WHERE customer_id = 5457742070
    UNION ALL
    SELECT campaign_id, segments_date, metrics_video_trueview_views
    FROM `bidbrain-analytics.raw_google_ads.p_ads_VideoNonClickStats_2020134915` WHERE customer_id = 2020134915
  )
  GROUP BY 1, 2
)
SELECT
  s.date,
  'Google Ads'                                 AS channel,
  COALESCE(nm.property_key, 'Unmapped')        AS property,
  CAST(s.campaign_id AS STRING)                AS campaign_id,
  TRIM(c.campaign_name)                        AS campaign_name,
  -- Google Ads has no ad-set tier at this grain; the CHANNEL TYPE (SEARCH / VIDEO / DISPLAY) is
  -- the useful sub-campaign dimension and is what distinguishes the YouTube line from the search
  -- lines, so it stands in for adset. (The cloudflare precedent: when the export flattens to
  -- campaign grain, name the substitute dimension rather than shipping a null tier.)
  c.ch_type                                    AS adset_id,
  c.ch_type                                    AS adset_name,
  CAST(s.campaign_id AS STRING)                AS ad_id,
  TRIM(c.campaign_name)                        AS ad_name,
  c.ch_type                                    AS objective,
  c.campaign_status                            AS effective_status,
  'AUD'                                        AS currency,
  s.spend,
  s.impressions,
  CAST(NULL AS INT64)                          AS reach,
  s.clicks,
  s.clicks                                     AS link_clicks,
  CAST(NULL AS INT64)                          AS landing_page_views,
  CAST(NULL AS INT64)                          AS leads,   -- see header: conversions are NOT leads
  CAST(NULL AS STRING)                         AS creative_id,
  CAST(NULL AS STRING)                         AS creative_title,
  CAST(NULL AS STRING)                         AS creative_body,
  CAST(NULL AS STRING)                         AS creative_thumbnail_url,
  CAST(NULL AS STRING)                         AS destination_url,
  CAST(NULL AS INT64)                          AS video_3s_views,     -- not in the feed; see header
  CAST(NULL AS INT64)                          AS video_completes,    -- not in the feed; see header
  CAST(NULL AS INT64)                          AS thruplays,
  v.video_views,
  s.conversions,
  s.view_through_conversions
FROM stats s
JOIN camp c USING (campaign_id)
LEFT JOIN vid v USING (campaign_id, date)
LEFT JOIN nm_map nm ON c.campaign_name = nm.nm
