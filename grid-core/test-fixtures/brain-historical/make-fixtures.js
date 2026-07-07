/*
 * Generates the three synthetic historical fixtures with KNOWN totals so the
 * seed script can report extraction accuracy. Idempotent — safe to re-run.
 *   resetdata-print-2024.xlsx  (3 sheets)      print total spend = $59,500
 *   resetdata-ooh-jcdecaux-2025.csv            OOH total spend   = $105,000
 *   resetdata-tv-q4-2024-media-plan.pdf        TV total spend    = $340,000
 */
'use strict';
const fs = require('fs');
const path = require('path');
const XLSX = require('xlsx');
const DIR = __dirname;

// ---- Print XLSX (3 sheets) ----
function makePrint() {
  const wb = XLSX.utils.book_new();
  const sheets = {
    Q1: [['Publisher', 'Insertion Date', 'Cost', 'Circulation'],
    ['Australian Financial Review', '2024-01-15', 12000, 90000],
    ['The Australian', '2024-02-10', 9500, 75000]],
    Q2: [['Publisher', 'Insertion Date', 'Cost', 'Circulation'],
    ['BRW', '2024-04-05', 8000, 40000],
    ['Capital Brief', '2024-05-20', 6000, 25000]],
    H2: [['Publisher', 'Insertion Date', 'Cost', 'Circulation'],
    ['Australian Financial Review', '2024-08-01', 14000, 90000],
    ['The Australian', '2024-10-12', 10000, 75000]]
  };
  Object.entries(sheets).forEach(([name, aoa]) => XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(aoa), name));
  XLSX.writeFile(wb, path.join(DIR, 'resetdata-print-2024.xlsx'));
}

// ---- OOH CSV ----
function makeOOH() {
  const rows = [
    ['location', 'format', 'start_date', 'end_date', 'panels', 'spend_aud', 'reach_thousands'],
    ['Sydney CBD', 'Large Format', '2025-02-01', '2025-02-28', 12, 45000, 1200],
    ['Melbourne CBD', 'Digital', '2025-03-01', '2025-03-31', 8, 38000, 950],
    ['Brisbane Airport', 'Large Format', '2025-04-01', '2025-04-30', 4, 22000, 400]
  ];
  fs.writeFileSync(path.join(DIR, 'resetdata-ooh-jcdecaux-2025.csv'), rows.map(r => r.join(',')).join('\n') + '\n');
}

// ---- TV PDF (minimal hand-built, single page, text lines) ----
function makeTVPdf() {
  const lines = [
    'ResetData — TV Media Plan — Q4 2024 (Oct-Dec)',
    '',
    'Channel   Flight Start   Flight End   Spend AUD   Reach     GRPs',
    'CH7       2024-10-01     2024-12-31   120000      850000    320',
    'CH9       2024-10-01     2024-12-31   110000      800000    300',
    'CH10      2024-10-01     2024-12-31   70000       500000    180',
    'Foxtel    2024-10-01     2024-12-31   40000       200000    90',
    '',
    'Total campaign spend: AUD 340,000   Total reach: 2,350,000'
  ];
  fs.writeFileSync(path.join(DIR, 'resetdata-tv-q4-2024-media-plan.pdf'), Buffer.from(buildPdf(lines), 'latin1'));
}

// Minimal valid single-page PDF with Helvetica text, correct xref offsets.
function buildPdf(lines) {
  const esc = s => s.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
  let content = 'BT /F1 11 Tf 40 760 Td 14 TL\n';
  lines.forEach((l, i) => { content += (i ? 'T* ' : '') + '(' + esc(l) + ') Tj\n'; });
  content += 'ET';
  const objs = [
    '<</Type/Catalog/Pages 2 0 R>>',
    '<</Type/Pages/Kids[3 0 R]/Count 1>>',
    '<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>',
    `<</Length ${Buffer.byteLength(content, 'latin1')}>>\nstream\n${content}\nendstream`,
    '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>'
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [];
  objs.forEach((o, i) => { offsets.push(Buffer.byteLength(pdf, 'latin1')); pdf += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xrefPos = Buffer.byteLength(pdf, 'latin1');
  pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  offsets.forEach(off => { pdf += String(off).padStart(10, '0') + ' 00000 n \n'; });
  pdf += `trailer\n<</Size ${objs.length + 1}/Root 1 0 R>>\nstartxref\n${xrefPos}\n%%EOF`;
  return pdf;
}

function makeAll() { makePrint(); makeOOH(); makeTVPdf(); }
if (require.main === module) { makeAll(); console.log('fixtures written to', DIR); }
module.exports = { makeAll, EXPECTED: { print: 59500, ooh: 105000, tv: 340000 } };
