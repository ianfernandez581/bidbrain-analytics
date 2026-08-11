-- Schneider Electric — PAID-MEDIA delivery TAGGED to internal program, SCOPED to the 8 dashboard
-- programs (the 5 CS programs + NEL + Microgrid + EcoConsult, paid-only programs with delivery but
-- no Salesforce CS leads).
-- Replicates the dashboard's first-match-wins idOf() join in SQL so the Paid Media tab can filter by
-- program AND market AND day together (the existing ad_campaign_* arrays split market vs day):
--   * map      = seed_campaign_map (ALL 28 rows, with seq = match precedence).
--   * camp_rank = each delivering platform campaign × every map row whose any '|'-token is a substring
--                 of the (lowercased) campaign name, ranked by seq (CROSS JOIN + correlated EXISTS).
--   * camp_map = first match per campaign (rn=1) — exactly idOf()'s "first row in array order wins".
-- Then keep only delivery whose program is one of the 8 dashboard programs. Reads stg_ad_delivery (view 04,
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
       -- MARKET: normalized to the two markets the CS leads use (Australia / New Zealand) so the
       -- Region chips stay strictly AU vs NZ across the Paid Media + CS tabs. After stg_tradedesk
       -- resolves the AU/NZ split from ad-group names, in-scope delivery is almost entirely
       -- country-specific; the small residual that is genuinely cross-market and can't be split by
       -- country (e.g. airset's 'RM AirSeT – Retargeting – ANZ' LinkedIn line, ~$500) is folded into
       -- Australia (the dominant Pacific market) so it stays in the paid totals rather than being
       -- dropped. There is no ANZ / Other bucket.
       --
       -- WARNING - THIS FOLD IS AN `ELSE`, so it is silent. Every program in scope today is AU/NZ, but
       -- a program that runs outside Australasia would have 100% of its foreign delivery reported AS
       -- AUSTRALIA. Enterprise IT (brief 1958) was briefly in scope on 2026-08-10 and needed a
       -- multi-region arm ahead of the fold:
       --     WHEN cm.program IN ('ent_it') THEN d.market   -- keep the region stg_ad_delivery resolved
       -- (its ad groups are region-coded SE_EntIT_2026_{PAC,India,MEA,SAM}_* with no country token, so
       -- the fold would have booked A$44k of MEA/India/South America spend as Australia). It was
       -- removed with the program the same day. RESTORE THAT ARM before adding any non-AU/NZ program -
       -- the dashboard already builds its Region chips per campaign (campaigns[].markets), so it will
       -- render the real regions as soon as this view emits them.
       CASE
         WHEN d.market = 'New Zealand' THEN 'New Zealand'
         ELSE 'Australia'
       END AS market,
       SUM(d.imps) AS imps, SUM(d.clicks) AS clicks, SUM(d.spend_aud) AS spend_aud,
       -- LinkedIn on-platform LEAD-FORM leads (NULL on DV360/TradeDesk - see stg_ad_delivery).
       -- Separate lane from the Salesforce CS leads: EcoConsult's Lead Generation ad sets report
       -- lead-form leads while it has no Salesforce campaign at all, so this is the ONLY place
       -- that delivery surfaces. Never sum it into a CS figure. SUM over an all-NULL DV360/TTD
       -- group returns NULL, so the "NULL not 0 off LinkedIn" contract survives the rollup.
       SUM(d.leads) AS leads, SUM(d.lead_form_opens) AS lead_form_opens
FROM `bidbrain-analytics.client_schneider.stg_ad_delivery` d
JOIN camp_map cm USING (campaign)
-- SCOPE = the client's own intake sheet, NOT everything delivering under the Schneider advertiser.
-- Three programs with live delivery are deliberately OUT (client, 2026-08-10 - separate campaigns,
-- separate stakeholders): ent_it (1958), ind_edge (2463), software_first (2305). See the CS_PROGRAMS
-- note in job/main.py - both lists must stay in sync.
WHERE cm.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid','ecoconsult')
-- AGGREGATED to the grain this view actually exposes (program × platform × day × market). It carries
-- NO campaign column, so the ungrouped version emitted one duplicate row per delivering campaign/ad
-- group and every consumer summed them anyway - which had pushed schneider.json to 13.6 MB. Grouping
-- restores ~0.4 MB with byte-identical totals. Keep this GROUP BY - if a campaign-grain view is ever
-- needed, add a SEPARATE view rather than un-grouping this one.
GROUP BY 1, 2, 3, 4;
