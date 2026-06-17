-- li_weekly_targets: LinkedIn 13-week Q2 lead plan (weekly + cumulative) -- constants.
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_LI_WEEKLY_TARGETS (hardcoded literal view).
-- The W7 cumulative jump (78, not 77) is intentional per the original payload.
CREATE OR REPLACE VIEW `client_cloudflare.li_weekly_targets` AS
SELECT 'W1'  AS WEEK, 'Mar 30 - Apr 5'  AS PERIOD, DATE '2026-03-30' AS WEEK_START, 11 AS TARGET,  11 AS CUM_TARGET
UNION ALL SELECT 'W2',  'Apr 6 - Apr 12',  DATE '2026-04-06', 11,  22
UNION ALL SELECT 'W3',  'Apr 13 - Apr 19', DATE '2026-04-13', 11,  33
UNION ALL SELECT 'W4',  'Apr 20 - Apr 26', DATE '2026-04-20', 11,  44
UNION ALL SELECT 'W5',  'Apr 27 - May 3',  DATE '2026-04-27', 11,  55
UNION ALL SELECT 'W6',  'May 4 - May 10',  DATE '2026-05-04', 11,  66
UNION ALL SELECT 'W7',  'May 11 - May 17', DATE '2026-05-11', 11,  78
UNION ALL SELECT 'W8',  'May 18 - May 24', DATE '2026-05-18', 11,  89
UNION ALL SELECT 'W9',  'May 25 - May 31', DATE '2026-05-25', 11, 100
UNION ALL SELECT 'W10', 'Jun 1 - Jun 7',   DATE '2026-06-01', 11, 111
UNION ALL SELECT 'W11', 'Jun 8 - Jun 14',  DATE '2026-06-08', 11, 122
UNION ALL SELECT 'W12', 'Jun 15 - Jun 21', DATE '2026-06-15', 11, 133
UNION ALL SELECT 'W13', 'Jun 22 - Jun 30', DATE '2026-06-22', 11, 144;
