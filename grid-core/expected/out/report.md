# Job 2053 SE ANZ NEL Awareness: gaps and inconsistencies in the supplied files

Reviewed: everything in `grid-core/files` (media plan, activation form, LinkedIn setup sheet, creative sheets 3 and 4, LGF copy review, insight tag workbook, content review tracker, TTD bulk upload, TAL lists, creative assets). Baseline used by `daily_kpi.xlsx`: AUD 35,000, flight 2026-06-01 to 2026-08-22, TradeDesk 8,000 + LinkedIn 27,000 (Video 6,000, Doc Ads 14,000, SIA 7,000).

## Inconsistencies

1. **Two different flight windows.** The media plan header says 28-Apr-26 to 18-Jul-26, with a note in the same row: "revise to june start through august". Every later document uses 2026-06-01 to 2026-08-22 (all 12 rows of the setup sheet, both creative sheets, and every TTD bulk upload row). The baseline uses the June window; the plan document itself was never re-issued, so anyone reading only the plan gets the wrong flight.
   Sources: `2053_SE_ANZ_New Energy Landscape Awareness - Media Plan.xlsx` (sheet "Media Plan", rows 4-5); `2053_SE_NEL_LinkedIn_Setup_Sheet.xlsx` (sheet "2. Campaign Setup Grid"); `2053_SE_NEL_TTD_Creative_Bulk_Upload.xlsx` (sheet "Hosted Display", flight date columns).

2. **Stated duration is 82 days; the actual window is 83.** Both the plan and the creative sheets say "82 days", but 2026-06-01 to 2026-08-22 inclusive is 83 days. Harmless until someone divides a budget by the wrong number.
   Sources: media plan sheet "Media Plan" row 6; `2053_SE_NEL_LinkedIn_Creative_Sheet_4.xlsx` (sheet "0. Campaigns", header row).

3. **Budget expectation gap: brief says $30K, plan totals $35,000.** The activation form states "Budget (excluding fees): $30K AUD". The approved plan totals $35,000. If the client still believes $30K, the wash-up starts $5,000 apart.
   Sources: `Transmission_Activation_Form_SE New Energy Awareness_2053.xlsx` (sheet "Launchpad Template", Budget row); media plan sheet "Media Plan" row 8.

4. **A total row that does not sum.** Creative Sheet 4's campaign overview says "TOTAL MEDIA BUDGET (12 campaigns) $35,000", but the 12 LinkedIn campaigns listed sum to $27,000. The missing $8,000 is the TradeDesk line, which is not one of the 12. The label is wrong on its own sheet.
   Source: `2053_SE_NEL_LinkedIn_Creative_Sheet_4.xlsx` (sheet "0. Campaigns", TOTAL row; campaign budgets rows 4-15).

5. **Inconsistent UTM tagging across the campaign.** The awareness video and all TTD destination URLs carry `utm_campaign=2026_apr_...` and `campaign_objective=consideration` (April naming, consideration objective, on awareness lines), while the SIA conversion URLs use `2026_jun_...`. Analytics will split one campaign across two utm_campaign vintages. Also, every NZ URL carries a `utm_id` beginning `au_`, so NZ traffic is tagged with an AU campaign id.
   Sources: `2053_SE_NEL_LinkedIn_Creative_Sheet_4.xlsx` (sheet "5. UTM Audit", rows 4-9); `SE_2053_NEL Content Review Tracker.xlsx` (sheet "Creative and CTAs"); TTD bulk upload clickthrough URLs.

6. **KPI expectation vs what the plan buys.** The brief's primary KPI is "qualified leads and enquiries" plus database growth. The plan contracts CPM impressions (812,778) and estimated clicks (2,745); no lead volume was ever agreed anywhere in the files. If the client measures this campaign in leads, that expectation is currently unanchored.
   Sources: activation form (sheet "Launchpad Template", Primary KPI row); media plan sheet "Media Plan" totals row.

7. **LGF scope moved from 5 forms to 3 between documents.** The LGF copy review sets up 5 lead gen forms (including two DC Charging Infographic forms). The final creative sheet builds 3, one per doc ad. It looks like a deliberate simplification, but no document records the decision.
   Sources: `2053_SE_NEL_LGF_Copy_Review.xlsx` (sheet "LGF Copy Updates", intro); `2053_SE_NEL_LinkedIn_Creative_Sheet_4.xlsx` (sheet "4. LGF", header).

8. **The media plan workbook contains sheets from a different campaign.** "Sheet1", "Results", "Premium Display Investment" and "Recommendations" describe Paid Search, Facebook, Bloomberg, IDG, CBSi and DV360 buys that match no NEL plan line. Anyone skimming the workbook can quote a number from the wrong campaign.
   Source: media plan workbook, those four sheets.

## Missing

9. **Fee treatment.** The brief's $30K is "excluding fees"; the plan's $35,000 says nothing about fees. Whether $35,000 is media-only or fee-loaded is stated nowhere.
   Sources: activation form Budget row; media plan sheet "Media Plan" row 8.

10. **Client sign-off on the media plan.** No document in the dump records approval of the $35,000 plan or of the revised June flight.
    Source: absent from all supplied files.

11. **Creative approval for statics and video.** Creative Sheet 4 records SE approval for the 3 doc ads and all LGF copy. The content review tracker's "Media Go Live status" column is empty on every row, so there is no recorded approval for the 12 TTD statics, the 2 LinkedIn videos, or the 3 SIA images.
    Sources: `SE_2053_NEL Content Review Tracker.xlsx` (sheet "Creative and CTAs", Media Go Live status column); `2053_SE_NEL_LinkedIn_Creative_Sheet_4.xlsx` (sheets "3. Doc Ads", "4. LGF").

12. **Insight Tag install confirmation.** The implementation workbook gives install steps and a test protocol (partner ID 8223628, four Folloze pages, test lead `test+nel@example.com`), but nothing records that any test passed. The conversion lane may be running without measurement.
    Source: `2053_SE_NEL_LinkedIn_Insight_Tag_Implementation.xlsx` (sheet "Check It Works").

13. **One unreferenced asset.** `EVlink_Pro_DC_Brochure_Pacific - amended for NECA.pdf` sits in the doc ads folder but is referenced by no doc ad, LGF, or tracker row. Purpose unknown.
    Source: `CREATIVE/Consideration - LinkedIn Document ads/[Provided by SE] Document ads/`.

## Watch

14. **Three NZ campaigns are below LinkedIn's $10/day floor.** NZ PillarA Video ($720), NZ PillarB Video ($480) and NZ PillarB SIA ($560) average $8.67, $5.78 and $6.75 per day over 83 days. The setup sheet's own risk note flags them: they will pace at the floor or be capped. Check at the first pacing review.
    Source: `2053_SE_NEL_LinkedIn_Setup_Sheet.xlsx` (sheet "2. Campaign Setup Grid", risk note row; budgets rows 2, 4, 12).

15. **Housekeeping.** The two media plan files are byte-identical (keep one). The six un-renamed `Static-*.jpg` files under `CREATIVE/Programmatic ads/` are byte-identical to the renamed TTD files and are superseded copies.
    Source: file hashes computed over `grid-core/files`.
