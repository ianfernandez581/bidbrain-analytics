/*
 * src/central/accordion.test.js — client-accordion behaviour on the grouped table.
 * Pure: exercises the exported _bodyHtml on pre-built rows (no DOM, no calc).
 *   - collapsed by default: one summary row per client, all child rows hidden
 *   - summary row aggregates additive columns (spend/budget) + shows the campaign count
 *   - expand one client: only that client's children un-hide (others stay collapsed)
 *   - collapse: children hidden again
 */
'use strict';
const view = require('./render-central');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };
const countChild = s => (s.match(/ct-childrow/g) || []).length;
const countHidden = s => (s.match(/ct-childrow ct-hidden/g) || []).length;
const countSum = s => (s.match(/ct-sumrow/g) || []).length;

function mkRow(section, client, name, channel, extra) {
  return Object.assign({
    section: section, client: client, name: name, channel: channel, status: 'Active', objective: '',
    _id: section + '|' + client + '|' + name + '|' + channel, _d: {}, _src: {}, _missing: [], _archived: false, _unbilled: false,
    mediaSpend: 100, clientSpend: 120, totalBudget: 1000, impressions: 5000,
    jobNumber: 'J1', platformMargin: 0.5, forecastCpm: 10, keyKpi: '', kpiPerformance: '', notes: '', startDate: '2026-01-01', endDate: '2026-12-31', spendMult: null
  }, extra || {});
}
const rows = [
  mkRow('TRANSMISSION', 'Schneider', 'EBA', 'TradeDesk'),
  mkRow('TRANSMISSION', 'Schneider', 'NEL', 'TradeDesk', { mediaSpend: 100, totalBudget: 1000 }),
  mkRow('TRANSMISSION', 'Cloudflare', 'Q3 Core DG', 'LinkedIn')
];
const schKey = view._clientKey('TRANSMISSION', 'Schneider');
const cfKey = view._clientKey('TRANSMISSION', 'Cloudflare');

// --- collapsed by default ---
view.CS.openClients = {};
const collapsed = view._bodyHtml(rows, true);
check('one summary row per client (2 clients → 2 ct-sumrow)', countSum(collapsed) === 2, countSum(collapsed));
check('all 3 campaign rows are present as children', countChild(collapsed) === 3, countChild(collapsed));
check('collapsed by default: all 3 children hidden', countHidden(collapsed) === 3, countHidden(collapsed));
check('Schneider summary shows "2 campaigns"', /2 campaigns/.test(collapsed));
check('Cloudflare summary shows "1 campaign"', /1 campaign\b/.test(collapsed));
check('summary aggregates additive spend (Schneider mediaSpend 100+100 = $200)', collapsed.indexOf('$200') >= 0);
check('summary aggregates budget (Schneider 1000+1000 = $2.0K)', collapsed.indexOf('$2.0K') >= 0);
check('no chevron is open when collapsed', collapsed.indexOf('ct-chev open') < 0);

// --- expand Schneider only ---
view.CS.openClients = {}; view.CS.openClients[schKey] = true;
const expanded = view._bodyHtml(rows, true);
check('expand Schneider: only Cloudflare child stays hidden (1)', countHidden(expanded) === 1, countHidden(expanded));
check('expanded Schneider chevron is open', expanded.indexOf('ct-chev open') >= 0);
check('Cloudflare stays collapsed (independent groups)', expanded.indexOf('data-cchild="' + cfKey + '"') >= 0 && new RegExp('ct-childrow ct-hidden"[^>]*data-cchild="' + cfKey.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).test(expanded));

// --- expand both ---
view.CS.openClients[cfKey] = true;
check('expand both: zero hidden children', countHidden(view._bodyHtml(rows, true)) === 0);

// --- collapse back ---
view.CS.openClients = {};
check('collapse: children hidden again (3)', countHidden(view._bodyHtml(rows, true)) === 3);

// --- non-summable columns show — in the summary (spot-check: platformMargin not summed) ---
view.CS.openClients = {};
const sumrowHtml = view._bodyHtml(rows, true).split('ct-sumrow')[1] || '';
check('summary leaves non-additive columns as — (dash present in summary row)', /—/.test(sumrowHtml));

console.log('\n' + (fail ? '✗' : '✓') + ' accordion: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
