-- 06_media_plan: the signed media plan, one row per BOUGHT LINE, per development.
-- Source of truth is the VERSION-CONTROLLED committed CSV targets/media_plan.csv, loaded to
-- client_geocon.seed_media_plan by seed_static.py. To change a plan: edit the CSV ->
-- seed_static.py -> export FORCE_REBUILD=1 (a seed change is invisible to the freshness gate).
--
-- WHY LINES AND NOT JUST A BUDGET: Northbourne Gateway is bought as nine separate lines across
-- five channels, each with its OWN impression / click / CPM / CTR target. A single blended
-- benchmark would mark a search line (plan CPM ~A$1,178, bought on clicks) as catastrophically
-- expensive and a Trade Desk line (plan CPM A$15) as a runaway win. Every plan-vs-actual number
-- on the dashboard is therefore compared line-for-line, or channel-for-channel, never blended.
--
-- `measurable` = FALSE marks a line this pipeline can NEVER report delivery for: SEO (an organic
-- search retainer, no ad server) and the Google Search management fee (an agency fee, not media).
-- They are 8.3% of the Northbourne budget (A$17,100 of A$205,600). Pacing spend-to-date against
-- the FULL budget would therefore read permanently under-pace by construction, so the dashboard
-- paces against the MEASURABLE budget and shows the full committed figure beside it.
--
-- `match_pattern` is '|'-separated case-insensitive SUBSTRING tokens matched against the
-- delivering campaign / ad-group name, first-match-wins by `seq` -- the same shape as
-- seed_property_map and client_schneider's seed_campaign_map. It is what lets a channel's delivery
-- be attributed to the LINE that bought it (three Trade Desk lines share one advertiser; two
-- Google lines share one account). The Meta line deliberately carries NO pattern: Meta has a
-- single Northbourne line, so everything on that channel belongs to it and a token could only
-- ever lose delivery.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.media_plan` AS
SELECT
  property_key, seq, phase, line_name, media, channel, description, targeting, geo,
  imp_target, video_view_target, reach_target, freq_cap,
  cpm_target, cpv_target, ctr_target, click_target,
  budget_aud, cost_type, measurable, match_pattern
FROM `bidbrain-analytics.client_geocon.seed_media_plan`
