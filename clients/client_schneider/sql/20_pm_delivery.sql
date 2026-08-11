-- Schneider Electric — PAID-MEDIA delivery TAGGED to internal program, SCOPED to the 10 dashboard
-- programs (the 5 CS programs + NEL + Microgrid + EcoConsult + Enterprise IT + Industrial Edge, the
-- paid-only programs having delivery but no Salesforce CS leads).
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
       -- MARKET, in two modes.
       --
       -- (a) MULTI-REGION programs (the IN-list below) keep the region stg_ad_delivery resolved
       --     (India / MEA / South America / Pacific / …). Enterprise IT (brief 1958, added
       --     2026-08-10) is an APAC-wide ABM program: only ~12% of its delivery is Pacific,
       --     and its ad groups are region-coded (SE_EntIT_2026_{PAC,India,MEA,SAM}_*) with NO
       --     country token, so the AU/NZ fold below would have reported A$44k of MEA/India/
       --     South America spend AS AUSTRALIA. Passing the real region through is the whole
       --     point of including it - the dashboard's Region chips are built per campaign
       --     (campaigns[].markets) so a multi-region program shows its own regions.
       --     A new EntIT ad group with no region token lands in 'Unmapped' and shows as a
       --     loud chip rather than being silently absorbed into Australia.
       --
       -- (b) Everything else normalizes to the two markets the CS leads use (Australia /
       --     New Zealand) so the Region chips stay strictly AU vs NZ across Paid Media + CS.
       --     After stg_tradedesk resolves the AU/NZ split from ad-group names, in-scope
       --     delivery is almost entirely country-specific; the small residual that is
       --     genuinely cross-market and can't be split by country (e.g. airset's
       --     'RM AirSeT – Retargeting – ANZ' LinkedIn line, ~$500) is folded into Australia
       --     (the dominant Pacific market) so it stays in the paid totals rather than being
       --     dropped. There is no ANZ / Other bucket.
       CASE
         WHEN cm.program IN ('ent_it') THEN d.market
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
WHERE cm.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid','ecoconsult',
                     'ent_it','ind_edge')
-- AGGREGATED to the grain this view actually exposes (program × platform × day × market). It carries
-- NO campaign column, so the ungrouped version emitted one duplicate row per delivering campaign/ad
-- group and every consumer summed them anyway. Adding ent_it's 42 lines pushed schneider.json to
-- 13.6 MB; grouping restores it to ~1 MB with byte-identical totals. Keep this GROUP BY - if a
-- campaign-grain view is ever needed, add a SEPARATE view rather than un-grouping this one.
GROUP BY 1, 2, 3, 4;
