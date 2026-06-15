-- ResetData — staged Reddit (top-of-funnel community awareness + traffic).
--
-- Source raw_windsor.perf_reddit, ResetData slice client_slug = 'resetdata' (the ONLY client
-- on Reddit to date; account 'ResetData Ad Account (100Digital)', agency 100-digital). EDA:
-- 3 community TOF campaigns / 33 ads, Feb–Jun 2026, objectives CONVERSIONS + CLICKS. Reddit's
-- native engagement (upvotes / downvotes / comments) and all video metrics are NULL upstream,
-- so they are not surfaced. Numbered 04b so it sits in the stg_* block (after stg_ttd, before
-- stg_ad_delivery / the roll-ups that read it) — create_views.py applies files in name order.
--
-- Currency: account_currency = AUD — native, no FX (matches the AUD reporting currency).
-- spend_aud is the AUD billed rate. conversions = sign-up + lead clicks (the demand-gen
-- conversions Reddit reports — sparse, like Meta leads). page_visits = page-visit clicks + views
-- (Reddit's traffic-driving signal, analogous to Meta landing-page views). reach is unique
-- people and NON-ADDITIVE across days, so it is deliberately not summed here.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_reddit` AS
SELECT
  metric_date,
  campaign_name                                              AS campaign,
  campaign_objective                                         AS objective,
  account_currency                                           AS currency,
  impressions                                                AS imps,
  clicks,
  ROUND(spend * 2, 2)                                        AS spend_aud,    -- AUD billed rate
  IFNULL(page_visit_clicks, 0) + IFNULL(page_visit_views, 0) AS page_visits,
  IFNULL(signup_clicks, 0)     + IFNULL(lead_clicks, 0)      AS conversions
FROM `bidbrain-analytics.raw_windsor.perf_reddit`
WHERE client_slug = 'resetdata';
