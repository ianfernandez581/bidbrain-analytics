/**
 * config/central-seed.js — TEST FIXTURE, NOT A RUNTIME DATA SOURCE.
 * ----------------------------------------------------------------------------
 * The live Central tab reads the real `const DATA` array (the full Central2.xlsx
 * "Live Campaigns" parse from build_grid_data.py) — see render-central.js
 * getSourceRows(). These 7 hand-seeded rows exist ONLY so the render smoke tests
 * have a small, stable, edge-case-covering dataset (both agencies, multi-campaign
 * clients, one all-null row for the divide-by-zero guards). Do not point the live
 * tab at this file.
 *
 * Rows carry ONLY [CONFIG]/[API] fields — every [DERIVED] column is computed by
 * src/central/calc.js at render time, never stored here.
 *
 * Coverage this seed intentionally exercises:
 *   - both agency sections, in order: "100% Digital" then "Transmission"
 *   - multi-campaign clients (ResetData x2, Cloudflare x2) -> client rowspan grouping
 *   - one row with MISSING spend/impressions (ResetData "Prospecting - Meta") ->
 *     the "—" divide-by-zero guards (margin / CPM / % spent / pacing all blank)
 *
 * TODO: wire [API] fields (impressions, mediaSpend, clientSpend) to the data source.
 *       Replace this whole file with the live Central feed once connectors land.
 *
 * @type {import('../src/central/calc.js').Campaign[]}
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.CentralSeed = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /** Agency display order — sections render in exactly this sequence. */
  const AGENCY_ORDER = ['100% Digital', 'Transmission'];

  /** @type {Array<Object>} */
  const CAMPAIGNS = [
    // ── 100% Digital ────────────────────────────────────────────────────────
    { agency: '100% Digital', client: 'ResetData', currency: 'AUD',
      jobNumber: 'RD-1042', name: 'Always On - Google Ads', objective: 'Leads', channel: 'Google Ads',
      managedBy: 'Zhen', status: 'Active', startDate: '2026-06-01', endDate: '2026-08-31',
      platformMargin: 0.15, adServing: 'CM360', adServingCost: 420, forecastCpm: 18.0,
      keyKpi: 'CPL < $120', kpiPerformance: '$96 CPL', budgetGross: 60000, totalBudget: 51000,
      impressions: 3120000, mediaSpend: 28800, clientSpend: 34500,
      campaignLink: 'https://dashboards.bidbrain.ai/d/resetdata/', nextReportingDue: '2026-07-15',
      notes: 'Search + PMax; scaling top keywords' },

    { agency: '100% Digital', client: 'ResetData', currency: 'AUD',
      jobNumber: 'RD-1043', name: 'Prospecting - Meta', objective: 'Awareness', channel: 'Meta',
      managedBy: 'Zhen', status: 'Draft', startDate: '2026-07-20', endDate: '2026-09-30',
      platformMargin: 0.15, adServing: 'CM360', adServingCost: null, forecastCpm: 12.0,
      keyKpi: 'CPM < $14', kpiPerformance: null, budgetGross: 30000, totalBudget: 25500,
      impressions: null, mediaSpend: null, clientSpend: null,
      campaignLink: null, nextReportingDue: null,
      notes: 'Not launched — spend + impressions still empty (tests the — guards)' },

    { agency: '100% Digital', client: 'The Little Marionette', currency: 'AUD',
      jobNumber: 'TLM-0210', name: 'Coffee Q3 - PMax', objective: 'ROAS', channel: 'Google Ads',
      managedBy: 'Aisha', status: 'Active', startDate: '2026-07-01', endDate: '2026-09-30',
      platformMargin: 0.12, adServing: 'None', adServingCost: 0, forecastCpm: 9.5,
      keyKpi: 'ROAS > 4.0', kpiPerformance: '4.6 ROAS', budgetGross: 24000, totalBudget: 21120,
      impressions: 1450000, mediaSpend: 9200, clientSpend: 11000,
      campaignLink: 'https://dashboards.bidbrain.ai/d/tlm/', nextReportingDue: '2026-07-18',
      notes: 'Shopping + PMax; TTD display secondary' },

    // ── Transmission ────────────────────────────────────────────────────────
    { agency: 'Transmission', client: 'Cloudflare', currency: 'USD',
      jobNumber: 'CF-3301', name: 'APAC ABM - LinkedIn', objective: 'MQLs', channel: 'LinkedIn',
      managedBy: 'Marcus', status: 'Active', startDate: '2026-07-01', endDate: '2026-09-30',
      platformMargin: 0.20, adServing: 'None', adServingCost: 0, forecastCpm: 55.0,
      keyKpi: 'CPL < $180', kpiPerformance: '$164 CPL', budgetGross: 120000, totalBudget: 96000,
      impressions: 1980000, mediaSpend: 41000, clientSpend: 52000,
      campaignLink: 'https://dashboards.bidbrain.ai/d/cloudflare/', nextReportingDue: '2026-07-14',
      notes: 'Content syndication lane runs in parallel' },

    { agency: 'Transmission', client: 'Cloudflare', currency: 'USD',
      jobNumber: 'CF-3302', name: 'APAC ABM - Trade Desk', objective: 'Reach', channel: 'Trade Desk',
      managedBy: 'Marcus', status: 'Active', startDate: '2026-07-01', endDate: '2026-09-30',
      platformMargin: 0.25, adServing: 'Flashtalking', adServingCost: 1300, forecastCpm: 8.5,
      keyKpi: 'Viewability > 70%', kpiPerformance: '73%', budgetGross: 80000, totalBudget: 64000,
      impressions: 7250000, mediaSpend: 30500, clientSpend: 39000,
      campaignLink: 'https://dashboards.bidbrain.ai/d/cloudflare/', nextReportingDue: '2026-07-14',
      notes: 'Partner (media) spend shown; billed client spend separate' },

    { agency: 'Transmission', client: 'MongoDB', currency: 'USD',
      jobNumber: 'MDB-0088', name: 'Content Syndication - Trade Desk', objective: 'Leads', channel: 'Trade Desk',
      managedBy: 'Priya', status: 'Paused', startDate: '2026-05-15', endDate: '2026-07-31',
      platformMargin: 0.22, adServing: 'CM360', adServingCost: 900, forecastCpm: 7.0,
      keyKpi: 'CPL < $200', kpiPerformance: '$210 CPL', budgetGross: 90000, totalBudget: 72000,
      impressions: 9800000, mediaSpend: 61000, clientSpend: 70200,
      campaignLink: 'https://dashboards.bidbrain.ai/d/mongodb/', nextReportingDue: '2026-07-12',
      notes: 'Paused pending creative refresh — pacing reads Over' },

    { agency: 'Transmission', client: 'Schneider', currency: 'AUD',
      jobNumber: 'SE-2050', name: 'Water & Environment - LinkedIn', objective: 'MQLs', channel: 'LinkedIn',
      managedBy: 'Priya', status: 'Ended', startDate: '2026-04-01', endDate: '2026-06-30',
      platformMargin: 0.18, adServing: 'None', adServingCost: 0, forecastCpm: 48.0,
      keyKpi: 'MQL 157', kpiPerformance: '149 MQL', budgetGross: 70000, totalBudget: 58800,
      impressions: 1210000, mediaSpend: 47000, clientSpend: 58000,
      campaignLink: 'https://dashboards.bidbrain.ai/d/schneider/', nextReportingDue: '2026-07-05',
      notes: 'Flight closed; final reconciliation done' },
  ];

  return { AGENCY_ORDER, CAMPAIGNS };
});
