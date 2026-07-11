/*
 * src/central/central-rebuild.test.js — locks the definitive-rebuild fixes:
 *   calc.js formula corrections (CPM media-basis, derived adServingCost, campaignMargin,
 *   budgetGross-based budget tracking) + the re-import (spendMult, adServing rate,
 *   platformMargin sanity, discarded derived columns) + the nav-collapse markup.
 * Pure: calc.js is dependency-free; the import + HTML checks read the committed files.
 */
'use strict';
const fs = require('fs'), path = require('path');
const calc = require('./calc');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };
const near = (a, b, t) => a != null && Math.abs(a - b) < (t || 0.01);

// real rows from Zhen's sheet
const geo = { mediaSpend: 10283.8, clientSpend: 20567.6, impressions: 879505, adServing: 0, budgetGross: 22500, totalBudget: 11250, platformMargin: 0.5 };
const rdtd = { mediaSpend: 1426.18, clientSpend: 4949.84, impressions: 430328, adServing: 5, budgetGross: 7911.69, totalBudget: 7911.69, platformMargin: 0.6 };

// ---- A. CPM Performance is MEDIA-based ----
check('CPM media-based: Geocon = 11.69', near(calc.cpmPerformance(geo), 11.69));
check('CPM media-based: ResetData/TD = 3.31', near(calc.cpmPerformance(rdtd), 3.31));
check('CPM is NOT client-based (Geocon client-basis would be 23.38)', !near(calc.cpmPerformance(geo), 23.38, 1));

// ---- B. adServingCost derived from rate × impressions ----
check('adServingCost: ResetData/TD = 2151.64 (5 × 430328/1000)', near(calc.adServingCost(rdtd), 2151.64));
check('adServingCost: Geocon = 0 (rate 0)', calc.adServingCost(geo) === 0);
check('adServingCost: 0 when impressions 0', calc.adServingCost({ adServing: 5, impressions: 0 }) === 0);

// ---- C. campaignMargin uses the derived adServingCost ----
check('campaignMargin: ResetData/TD = 0.277', near(calc.campaignMargin(rdtd), 0.277, 0.001));
check('campaignMargin: Geocon = 0.50', near(calc.campaignMargin(geo), 0.5, 0.001));
check('campaignMargin: — when clientSpend 0', calc.campaignMargin({ clientSpend: 0, mediaSpend: 5 }) === null);

// ---- D. budget tracking on effectiveBudget = budgetGross || totalBudget ----
check('effectiveBudget uses budgetGross (Geocon 22500, not totalBudget 11250)', calc.effectiveBudget(geo) === 22500);
check('effectiveBudget falls back to totalBudget when no gross', calc.effectiveBudget({ totalBudget: 5000 }) === 5000);
check('pctBudgetSpent: Geocon = 91.4% (client/gross, not the old 183%)', near(calc.pctBudgetSpent(geo), 0.9141, 0.001));
check('pctBudgetSpent: ResetData/TD = 62.6%', near(calc.pctBudgetSpent(rdtd), 0.6256, 0.001));
check('budgetRemaining: Geocon = 22500 - 20567.6', near(calc.budgetRemaining(geo), 22500 - 20567.6));

// ---- E. re-import data (config/central-import.json) ----
const imp = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'config', 'central-import.json'), 'utf8'));
const gw = imp.find(r => r.advertiser === 'Gateway');
const rd = imp.find(r => r.advertiser === 'ResetData' && /tradedesk/i.test(r.channel || ''));
check('import: spendMult computed (Gateway = 2)', gw && gw.spendMult === 2, gw && gw.spendMult);
check('import: ResetData/TD spendMult = 3.4707 (client/media, 4dp)', rd && rd.spendMult === 3.4707, rd && rd.spendMult);
check('import: ResetData/TD adServing RATE = 5', rd && rd.adServing === 5);
check('import: no platformMargin outside [0,1]', imp.every(r => r.platformMargin == null || (r.platformMargin >= 0 && r.platformMargin <= 1)));
check('import: "NA" platformMargin → null (ResetData/Meta)', (imp.find(r => r.advertiser === 'ResetData' && /meta/i.test(r.channel || '')) || {}).platformMargin === null);
check('import: derived columns discarded (no campaignMargin/cpmPerf/adservingCost)', imp.every(r => !('campaignMargin' in r) && !('cpmPerf' in r) && !('adservingCost' in r)));

// ---- F. nav-collapse markup in the-grid.html ----
const html = fs.readFileSync(path.join(__dirname, '..', '..', 'the-grid.html'), 'utf8');
check('nav: sideToggle + sideExpand buttons present', /id="sideToggle"/.test(html) && /id="sideExpand"/.test(html));
check('nav: side-collapsed CSS hides the sidebar', /\.app\.side-collapsed \.sidebar\s*\{\s*display:none\}/.test(html));
check('nav: collapse persists to localStorage (grid-side)', /localStorage\.setItem\('grid-side'/.test(html));

// ---- G. lenient health criteria (Step 1 gate → watch → winner → steady) ----
const T = new Date('2026-11-01');              // fixed "today" between the test flights
const H = (c, today) => calc.computeRow(c, today || new Date()).health;
// Step 1: insufficient-data gate → null (never grade the unmeasurable)
check('health: 0 impressions → insufficient (null)', H({ impressions: 0, mediaSpend: 100, clientSpend: 100, budgetGross: 1000 }) === null);
check('health: no budget → insufficient (null)', H({ impressions: 1000, mediaSpend: 100, clientSpend: 100 }) === null);
check('health: null media/client → insufficient (null)', H({ impressions: 1000, mediaSpend: null, clientSpend: null, budgetGross: 1000 }) === null);
// Step 2: watch — negative margin
check('health: negative margin → watch', H({ impressions: 1000, mediaSpend: 200, clientSpend: 100, budgetGross: 1000, forecastCpm: 500 }) === 'watch');
// Step 3: winner — positive margin + cpm<forecast + pacing 0.7-1.3 (Geocon-shaped)
check('health: Geocon-shaped → winner', H({ impressions: 879505, mediaSpend: 10283.8, clientSpend: 20567.6, budgetGross: 22500, forecastCpm: 40, startDate: '2026-01-01', endDate: '2026-12-31' }, T) === 'winner');
// Step 4: steady — has data, margin 0 (not negative), not a standout (ResetData/Meta-shaped)
check('health: margin 0 + data → steady', H({ impressions: 84197, mediaSpend: 1959.24, clientSpend: 1959.24, budgetGross: 3000, forecastCpm: 40 }) === 'steady');
// EBA anomaly — CPM >90% below forecast → watch (the "$1.42 vs $28" detector)
check('health: EBA anomaly (CPM 1.54 vs forecast 20) → watch', H({ impressions: 6075501, mediaSpend: 9346, clientSpend: 27146, budgetGross: 20000, forecastCpm: 20, startDate: '2026-01-01', endDate: '2026-12-31' }, T) === 'watch');
// normal cheap display (not extreme) is NOT flagged anomalous (ResetData/TD 12% of forecast)
check('health: normal cheap CPM (12% of forecast) is NOT anomaly-watch', H({ impressions: 430328, mediaSpend: 1426.18, clientSpend: 4949.84, adServing: 5, budgetGross: 7911.69, forecastCpm: 28, startDate: '2026-01-01', endDate: '2026-12-31' }, T) !== 'watch');

console.log('\n' + (fail ? '✗' : '✓') + ' central-rebuild: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
