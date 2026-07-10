/*
 * Generates Central media-plan test fixtures. Run: node test-fixtures/central/make-central-fixtures.js
 * Fixture 1 is deliberately messy: a title merged across row 1, a Client key/value
 * pair on row 2, the real header on row 3 and one data row on row 4, budget as
 * "$20k", margin as "40%", KPI as "300 opt-ins", plus a non-plan "Notes" sheet and
 * a prose "Brief" sheet to exercise sheet prioritization.
 */
'use strict';
const XLSX = require('xlsx');
const path = require('path');

const wb = XLSX.utils.book_new();

// --- "Notes" (non-plan sheet, should be de-prioritized) ---
const notes = XLSX.utils.aoa_to_sheet([
  ['Internal notes'], ['Budget approvals pending'], ['do not send to client']
]);
XLSX.utils.book_append_sheet(wb, notes, 'Notes');

// --- "Media Plan" (the real one) ---
const mp = XLSX.utils.aoa_to_sheet([
  ['MongoDB APAC Q3 Media Plan', null, null, null, null, null, null, null, null, null, null], // row1 title (merged)
  ['Client', 'MongoDB', null, null, null, null, null, null, null, null, null],                 // row2 key/value
  ['Job Number', 'Campaign', 'Channel', 'Objective', 'Total Budget', 'Platform Margin', 'Forecast CPM', 'Key KPI', 'Managed By', 'Start Date', 'End Date'], // row3 headers
  ['MDB-0099', 'Content Syndication Q3', 'Trade Desk', 'Leads', '$20k', '40%', '$7.50', '300 opt-ins', 'Priya', '2026-07-01', '2026-09-30'] // row4 data
]);
mp['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 10 } }];
XLSX.utils.book_append_sheet(wb, mp, 'Media Plan');

// --- "Brief" (prose) ---
const brief = XLSX.utils.aoa_to_sheet([
  ['Campaign Brief'], ['Objective: drive qualified leads for MongoDB Atlas in APAC.'],
  ['Audience: senior data engineers.']
]);
XLSX.utils.book_append_sheet(wb, brief, 'Brief');

const out = path.join(__dirname, 'mongodb-q3-media-plan.xlsx');
XLSX.writeFile(wb, out);
console.log('wrote', out);
