-- Schneider Electric — PAID-MEDIA delivery TAGGED to internal program, SCOPED to the 8 dashboard
-- programs (the 5 CS programs + NEL + Microgrid + EcoConsult, paid-only programs with delivery but
-- no Salesforce CS leads).
-- The campaign -> program tagging (the dashboard's original first-match-wins idOf(), replicated in
-- SQL) now lives in ONE place, 04b_campaign_program — this view, 22_search_campaigns and
-- 23_search_scope_audit all read it, so the Search detail can never disagree with the platform
-- totals here. Extracting it was a strict no-op: verified program x platform x imps x clicks x spend
-- identical before and after (2026-09-02). Reads stg_ad_delivery (view 04, the unified
-- platform·campaign·day·market·imps·clicks·spend_aud base) + campaign_program, then keeps only
-- delivery whose program is one of the dashboard programs.
--
-- PLATFORMS: dv360 / tradedesk / linkedin / google_search (Search added 2026-09-02). Nothing in this
-- view is platform-aware — a new platform arrives simply by being unioned into stg_ad_delivery.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.pm_delivery` AS
WITH camp_map AS (
  SELECT campaign, program FROM `bidbrain-analytics.client_schneider.campaign_program`
)
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
       --
       -- GOOGLE SEARCH (2026-09-02) is the platform this fold is now most exposed to: its account
       -- ('AAG region Account') carries the brief-2306 campaigns running in Brazil, Chile, Saudi
       -- Arabia and the UAE. They stay out because brief 2306 maps to `ai_lc`, which is NOT in the
       -- program list below - the region never enters into it. That exclusion is DESIGNED, not
       -- luck: `2306_` was added to ai_lc's match_pattern precisely so those campaigns resolve to a
       -- named out-of-scope program instead of falling through unmatched, and 23_search_scope_audit
       -- asserts every Search campaign still resolves and that nothing in scope is non-Pacific.
       -- In-scope Search today is 2061_* (AU/NZ, -> global_rebrand) and 2389_* (_ANZ_, -> mcset);
       -- the 2389 lines fold to Australia here, the same treatment mcset's ANZ-wide TTD line gets.
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
-- mcset (MCSeT + EvoPacT, brief 2389) added 2026-08-11 at the client's request. Paid-only, awareness,
-- ANZ: LinkedIn `SE_MCSet_ANZ_AWAR_TAL - AU`/`- NZ` (live 2026-08-06) + TTD `SE_MCSet_ANZ_Aug2026 -
-- AWAR` (live 2026-08-05). Its seeded match_pattern was `Cooling Solutions`, which matched NONE of
-- those and instead claimed two brief-1130 campaigns from Aug-Sep 2025 - a different, finished event
-- brief. The pattern is now `MCSet|EvoPact|2389_`; simulating the swap against stg_ad_delivery moved
-- exactly 5 campaigns (3 gained, the 2 stale 1130 ones released) and stole nothing from any other
-- program. NOTE its TTD line is ANZ-wide (market='ANZ'), so the AU/NZ fold below books that spend as
-- Australia while LinkedIn splits AU/NZ properly - the same treatment airset's ANZ line already gets.
WHERE cm.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid','ecoconsult','mcset')
-- AGGREGATED to the grain this view actually exposes (program × platform × day × market). It carries
-- NO campaign column, so the ungrouped version emitted one duplicate row per delivering campaign/ad
-- group and every consumer summed them anyway - which had pushed schneider.json to 13.6 MB. Grouping
-- restores ~0.4 MB with byte-identical totals. Keep this GROUP BY - if a campaign-grain view is ever
-- needed, add a SEPARATE view rather than un-grouping this one.
GROUP BY 1, 2, 3, 4;
