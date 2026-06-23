-- Schneider Electric — PAID-MEDIA delivery TAGGED to internal program, SCOPED to the 5 CS programs.
-- Replicates the dashboard's first-match-wins idOf() join in SQL so the Paid Media tab can filter by
-- program AND market AND day together (the existing ad_campaign_* arrays split market vs day):
--   * map      = seed_campaign_map (ALL 28 rows, with seq = match precedence).
--   * camp_rank = each delivering platform campaign × every map row whose any '|'-token is a substring
--                 of the (lowercased) campaign name, ranked by seq (CROSS JOIN + correlated EXISTS).
--   * camp_map = first match per campaign (rn=1) — exactly idOf()'s "first row in array order wins".
-- Then keep only delivery whose program is one of the 5 CS programs. Reads stg_ad_delivery (view 04,
-- the unified platform·campaign·day·market·imps·clicks·spend_aud base) + the seed_campaign_map table.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.pm_delivery` AS
WITH map AS (
  SELECT internal_campaign_id, seq, LOWER(match_pattern) AS pat
  FROM `bidbrain-analytics.client_schneider.seed_campaign_map`
),
camps AS (
  SELECT DISTINCT campaign FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
),
camp_rank AS (
  SELECT c.campaign, m.internal_campaign_id AS program,
         ROW_NUMBER() OVER (PARTITION BY c.campaign ORDER BY m.seq) AS rn
  FROM camps c, map m
  WHERE EXISTS (
    SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
    WHERE TRIM(tok) != '' AND STRPOS(LOWER(c.campaign), TRIM(tok)) > 0)
),
camp_map AS (SELECT campaign, program FROM camp_rank WHERE rn = 1)
SELECT cm.program, d.platform, d.metric_date,
       -- normalize to the shared market vocab used by the CS views (Australia / New Zealand / ANZ /
       -- Other) so the global Region chips are coherent across the Paid Media + CS tabs.
       CASE WHEN d.market IN ('Australia','New Zealand','ANZ') THEN d.market ELSE 'Other' END AS market,
       d.imps, d.clicks, d.spend_aud
FROM `bidbrain-analytics.client_schneider.stg_ad_delivery` d
JOIN camp_map cm USING (campaign)
WHERE cm.program IN ('water_env','eba','heavy','global_rebrand','airset');
