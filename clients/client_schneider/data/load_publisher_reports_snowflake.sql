-- AET direct-publisher actuals (manual monthly ingest) -- r2: Westwick split by publication
-- Grain: one row per publisher x placement/line x month. NOTE: some rows carry clicks with NULL
-- impressions (shared sends/positions per the publisher report) -- never drop them.
CREATE TABLE IF NOT EXISTS APAC_ALL_PLATFORM.PUBLIC.PUBLISHER_REPORTS_APAC (
  REPORT_MONTH DATE, JOB_NUMBER VARCHAR(20), CLIENT VARCHAR(100), CAMPAIGN VARCHAR(100),
  PUBLISHER VARCHAR(120), PRODUCT_TYPE VARCHAR(40), PLACEMENT_NAME VARCHAR(300),
  START_DATE DATE, END_DATE DATE, IMPRESSIONS NUMBER, CLICKS NUMBER, SENDS NUMBER,
  OPEN_RATE FLOAT, VIEWABILITY FLOAT, BOOKED_VIEWS NUMBER, DELIVERED_VIEWS NUMBER,
  SOURCE VARCHAR(60), LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
DELETE FROM APAC_ALL_PLATFORM.PUBLIC.PUBLISHER_REPORTS_APAC
 WHERE CAMPAIGN='Advancing Energy Technology' AND JOB_NUMBER IN ('2608','2609','ENGY');
INSERT INTO APAC_ALL_PLATFORM.PUBLIC.PUBLISHER_REPORTS_APAC
(REPORT_MONTH,JOB_NUMBER,CLIENT,CAMPAIGN,PUBLISHER,PRODUCT_TYPE,PLACEMENT_NAME,START_DATE,END_DATE,
 IMPRESSIONS,CLICKS,SENDS,OPEN_RATE,VIEWABILITY,BOOKED_VIEWS,DELIVERED_VIEWS,SOURCE) VALUES
('2026-07-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','content_newsletter','Newsletter integration - ''A message from Schneider Electric''',NULL,NULL,158968,172,NULL,54,NULL,NULL,NULL,'CB report job 2609'),
('2026-07-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','content_web','Partner article views - short & long form',NULL,NULL,29274,63,NULL,NULL,NULL,NULL,NULL,'CB report job 2609'),
('2026-07-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','adv_newsletter','Newsletter advertising',NULL,NULL,317936,133,NULL,54,NULL,NULL,NULL,'CB report job 2609'),
('2026-07-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','adv_display','Web display advertising',NULL,NULL,45196,66,NULL,NULL,77,NULL,NULL,'CB report job 2609'),
('2026-08-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','content_newsletter','Newsletter integration - ''A message from Schneider Electric''',NULL,NULL,202844,1831,NULL,56,NULL,NULL,NULL,'CB report job 2609'),
('2026-08-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','content_web','Partner article views - short & long form',NULL,NULL,72649,52,NULL,NULL,NULL,NULL,NULL,'CB report job 2609'),
('2026-08-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','adv_newsletter','Newsletter advertising (clicks to se.com)',NULL,NULL,580371,1390,NULL,56,NULL,NULL,NULL,'CB report job 2609'),
('2026-08-01','2609','Schneider Electric','Advancing Energy Technology','Capital Brief','adv_display','Web display advertising',NULL,NULL,101929,149,NULL,NULL,74,NULL,NULL,'CB report job 2609'),
('2026-07-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_newsletter','ENGY nl banner Jul 2026','2026-07-07','2026-07-24',14131,76,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-07-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_newsletter','ENGY nl banner Jul 2026','2026-07-28','2026-07-28',5472,34,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_newsletter','ENGY nl banner Aug 2026','2026-08-04','2026-08-26',26907,109,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-07-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_display','ON-259779 ENGY Web MREC Jul - Sep 2026 [July 2026]',NULL,NULL,1973,3,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_display','ON-259779 ENGY Web MREC Jul - Sep 2026 [August 2026]',NULL,NULL,12127,9,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_display','ON-259779 ENGY Webskin Aug 2026 [August 2026]',NULL,NULL,2601,17,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_display','ON-259779 ENGY Webskin Aug 2026 [August 2026]',NULL,NULL,973,1,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_display','ON-259779 ENGY Webskin Aug 2026 [August 2026]',NULL,NULL,2008,18,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','adv_display','ON-259779 ENGY Webskin Aug 2026 [August 2026]',NULL,NULL,520,0,NULL,NULL,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-07-01','ENGY','Schneider Electric','Advancing Energy Technology','Energy Magazine','solus_edm','ENGY Solus eDM','2026-07-23','2026-07-23',NULL,64,7443,26.75,NULL,NULL,NULL,'Project ENGY Q3 workbook'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_newsletter','eNews 1 text panel 1',NULL,NULL,55704,45,NULL,29.0,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_newsletter','eNews 1 text panel 2',NULL,NULL,NULL,36,NULL,29.0,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_display','Side Bars Left',NULL,NULL,6657,5,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_display','Side Bars Right',NULL,NULL,NULL,3,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','adv_display','Side Bars Left',NULL,NULL,7998,7,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','adv_display','Side Bars Right',NULL,NULL,NULL,6,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_display','Welcome Roadblock',NULL,NULL,6613,80,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','adv_display','Premier Tab',NULL,NULL,7951,3,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_display','Premier Tab',NULL,NULL,6591,2,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_display','Leaderboard Banner x5',NULL,NULL,3837,4,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','adv_display','M Leaderboard Banner x5',NULL,NULL,2706,3,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','adv_display','MREC Position 1 x5',NULL,NULL,8054,8,NULL,NULL,NULL,NULL,NULL,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','ECD Online (Westwick-Farrow)','sponsored_article','power-under-pressure-can-your-infrastructure-keep-up--617694274',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1241,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','sponsored_article','the-water-sector-s-biggest-problem-may-not-be-underground-301998802',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1211,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','sponsored_article','how-energy-technology-can-advance-net-zero-journeys-933426641',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1160,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','sponsored_article','from-ac-to-dc-the-next-phase-of-electrification-will-reshape-power-distribution-782681471',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1169,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','sponsored_article','climate-reporting-is-exposing-a-problem-bigger-than-emissions-449420198',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1165,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','sponsored_article','when-sustainability-targets-outpace-building-systems-450681073',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1171,'WF report job 2608'),
('2026-08-01','2608','Schneider Electric','Advancing Energy Technology','Sustainability Matters (Westwick-Farrow)','sponsored_article','the-energy-advantage-the-next-growth-opportunity-for-australia-and-new-zealand-1278118982',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1000,1207,'WF report job 2608');
