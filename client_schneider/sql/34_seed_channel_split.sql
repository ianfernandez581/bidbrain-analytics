-- Schneider Electric — SEED: approved channel split (AUD) per internal campaign × stage × channel.
-- Editable. Powers the channel-split sub-view on the Spend & Pacing tab.
--
-- SEED ONLY 2306 (ai_lc — AI & Liquid Cooling): the only approved split in the brief. Stages are
-- Prospecting vs Retargeting (RT). Total = 480,600 AUD (ex_fees), which is ai_lc's plan budget.
-- TODO: add other campaigns' approved splits when the plans are confirmed (none other today).
--
-- NB: Search + Reddit are PLANNED channels with NO delivery in the warehouse (Schneider has no
-- Google Ads / Reddit rows) — the dashboard shows them as "planned, no platform delivery"
-- rather than zero performance.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_channel_split` AS
SELECT * FROM UNNEST([
  STRUCT(
    'ai_lc' AS internal_campaign_id, 'Prospecting' AS stage, 'Premium' AS channel, 85440.0 AS budget_aud),
  STRUCT('ai_lc', 'Prospecting', 'Programmatic', 53400.0),
  STRUCT('ai_lc', 'Prospecting', 'Search',       74760.0),
  STRUCT('ai_lc', 'Prospecting', 'LinkedIn',     69420.0),
  STRUCT('ai_lc', 'Prospecting', 'Reddit',       26700.0),
  STRUCT('ai_lc', 'Retargeting', 'Programmatic', 96120.0),
  STRUCT('ai_lc', 'Retargeting', 'LinkedIn',     74760.0)
]);
