-- 23_cs_enriched_by_publisher.sql
--
-- WEEKLY ENRICHED LEADS BY PUBLISHER (client request 2026-09-17, via Fahad).
-- "a weekly breakdown by publisher showing how many of the leads are enriched."
--
-- ---------------------------------------------------------------------------------------
-- THE COUNTS COME FROM SALESFORCE. INTEGRATE SUPPLIES ONLY THE OFFER SPLIT.
--
-- This is the whole design decision, and it is what keeps this panel from contradicting the
-- Weekly Enriched Leads tab a screen above it. The two sources disagree about enrichment in
-- BOTH directions - Integrate holds 56 enrichments for VRSM that Salesforce does not (dated
-- 3-23 Aug), and Salesforce holds 36 that Integrate does not (the 2026-07-21 Precision MQL
-- batch) - so sourcing counts from Integrate would put two different enrichment figures on one
-- screen. That is the defect the client raised on the pacing card on 2026-09-16, and it is not
-- worth repeating for a split we can get another way.
--
-- So: ENRICHED_PHONE, IS_ACCEPTED and the sentinel handling all stay exactly as
-- sql/20_cs_enriched_leads defines them. This view re-cuts the SAME population by publisher.
-- It must tie to that tab; if it ever does not, this view is wrong, not the tab.
--
-- ---------------------------------------------------------------------------------------
-- THE OFFER SPLIT NOW ARRIVES RESOLVED. IT IS NOT DEFINED HERE.
--
-- VRSM (701RG00001W1FQRYA3) is the one campaign mixing enrichable survey leads with Lead Magnet
-- leads, and nothing in the Salesforce feed separates them. Integrate's landing-page URL does
-- (see sql/19b_integrate_bridge), and sql/20 applies that override - confined to VRSM, because
-- every other campaign sells ONE offer and its id already names it.
--
-- Until 2026-09-18 the override lived HERE, because VRSM was excluded from the headline tab and
-- appeared only on this panel. Jade asked for it on the headline tab too, so the rule moved up
-- to sql/20 and this view reads `OFFER_TYPE` already resolved. Both panels now divide by the
-- same population BY CONSTRUCTION rather than by two copies of one rule agreeing - and the
-- headline moved 413/345 (83.5%) -> 543/451 (83.1%), which is this panel's own total.
--
-- ---------------------------------------------------------------------------------------
-- THE TRAILING WEEK IS NOT A COLLAPSE, IT IS A QUEUE - and this view exists partly to say so.
-- Enrichment lands days after the lead. Measured 2026-09-18, Roverpath survey leads:
--   w/c 17 Aug  62 available / 50 enriched (12 NA)
--   w/c 31 Aug  17 available / 16 enriched  (1 NA)
--   w/c 07 Sep  10 available /  1 enriched  (9 NA)   <- 90% still queued
-- Drawn raw, that last week reads as Roverpath falling from 94% to 10%. It has not. NA_COUNT
-- and PENDING_SHARE are carried so the dashboard can mark or withhold a week that is still
-- processing, the same rule the Weekly Enriched Leads tab already applies by dropping a week
-- with nothing available.

CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.cs_enriched_by_publisher` AS
-- THE OFFER OVERRIDE MOVED TO sql/20 ON 2026-09-18 AND THIS VIEW NO LONGER REPEATS IT.
-- It lived here while the headline tab still excluded VRSM, which meant the two panels on one
-- screen resolved the offer by two separate copies of the same rule - the shape that eventually
-- lets them disagree. Jade asked for VRSM on the headline tab, so `OFFER_TYPE` arrives already
-- resolved and `OFFER_FROM_INTEGRATE` already flagged. Read them; do not re-derive them here.
SELECT
  DATE_TRUNC(DAY, WEEK(MONDAY))                               AS WEEK_START,
  THEATRE,
  PUBLISHER,
  -- AVAILABLE TO ENRICH = accepted leads on the two offers enrichment is actually bought on
  -- (Jade, 2026-09-10). This is the denominator the client wrote the wording for, and it is the
  -- same one the Weekly Enriched Leads tab divides by - never "all accepted leads".
  COUNTIF(IS_ACCEPTED AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions'))
                                                              AS AVAILABLE,
  COUNTIF(IS_ACCEPTED AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions')
          AND IS_ENRICHED)                                    AS ENRICHED,
  -- Still queued at Integrate: submitted, no number back yet. The lag signal.
  COUNTIF(IS_ACCEPTED AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions')
          AND ENRICHED_STATE = 'NA')                          AS NA_COUNT,
  -- Never submitted. Distinct from NA and NOT interchangeable with it - the two sentinels are
  -- the trap this whole lane was built around.
  COUNTIF(IS_ACCEPTED AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions')
          AND ENRICHED_STATE = 'DASH')                        AS DASH_COUNT,
  -- Share of the available population still waiting. The dashboard marks a week above a
  -- threshold rather than drawing its rate as a fall.
  SAFE_DIVIDE(
    COUNTIF(IS_ACCEPTED AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions')
            AND ENRICHED_STATE = 'NA'),
    COUNTIF(IS_ACCEPTED AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions')))
                                                              AS PENDING_SHARE,
  -- Context only, never a denominator (the client's own framing, 2026-09-16).
  COUNTIF(IS_ACCEPTED)                                        AS ACCEPTED_ALL_OFFERS,
  -- How many of this cell's available leads were placed by Integrate's URL rather than by the
  -- campaign id. Non-zero only on VRSM. The job prints it so a silent drop in the split's
  -- reach - a URL convention change upstream - shows up as a number, not as a quiet shortfall.
  COUNTIF(IS_ACCEPTED AND OFFER_FROM_INTEGRATE
          AND OFFER_TYPE IN ('Pulse Survey', 'Qualification Questions'))
                                                              AS SPLIT_BY_INTEGRATE
FROM `bidbrain-analytics.client_cloudflare.cs_enriched_leads`
GROUP BY 1, 2, 3
-- A publisher-week with nothing enrichable is not a zero, it is an absent row: it means that
-- publisher does not sell these offers, and drawing it as 0% would read as failure.
HAVING AVAILABLE > 0
