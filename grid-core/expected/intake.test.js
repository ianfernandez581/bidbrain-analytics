/*
 * expected/intake.test.js - locks the file-intake contract (preprocess.js).
 *
 * The defect this pins: only spreadsheets and CSVs were ever read, and every
 * omission (unreadable type, parse error, truncated sheet, head-sampled CSV)
 * was recorded internally and shown to nobody. A run over PART of a dump must
 * never look identical to a run over all of it.
 *
 * Free, deterministic, no key, no server, no network.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const XLSX = require('xlsx');
const { preprocess, classify, CSV_FULL_ROW_MAX } = require('./preprocess');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };

// ---- classify: the types that used to fall through and never be opened ----
check('.xlsx is a sheet', classify('plan.xlsx') === 'sheet');
check('.xlsm is a sheet', classify('plan.xlsm') === 'sheet');
check('.xls (legacy media plan) is a sheet, not "other"', classify('plan.xls') === 'sheet', classify('plan.xls'));
check('.xlsb is a sheet', classify('plan.xlsb') === 'sheet', classify('plan.xlsb'));
check('.csv is a table', classify('audience.csv') === 'table');
check('.txt is text', classify('utm notes.txt') === 'text', classify('utm notes.txt'));
check('.md is text', classify('README.md') === 'text');
check('.pdf stays pdf', classify('brief.pdf') === 'pdf');
check('.pptx stays deck', classify('deck.pptx') === 'deck');
check('.docx stays doc', classify('links.docx') === 'doc');
check('unknown extension is other', classify('mail.msg') === 'other');
check('case-insensitive', classify('PLAN.XLS') === 'sheet');

// ---- build a fixture dump on disk ----
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gl-intake-'));

const wb = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
  ['Campaign', 'Budget'], ['LinkedIn Awareness', 6000], ['Programmatic', 8000],
]), 'Media Plan');
XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([]), 'Blank');
XLSX.writeFile(wb, path.join(dir, 'media_plan.xlsx'));

// a small CSV: a plan exported to CSV, must be bundled WHOLE
const smallRows = ['name,budget'].concat(
  Array.from({ length: 40 }, (_, i) => `line ${i + 1},${(i + 1) * 100}`));
fs.writeFileSync(path.join(dir, 'plan_export.csv'), smallRows.join('\n'));

// a big CSV: an audience list, head sample is correct
const bigRows = ['email,segment'].concat(
  Array.from({ length: CSV_FULL_ROW_MAX + 50 }, (_, i) => `u${i}@x.com,seg`));
fs.writeFileSync(path.join(dir, 'audience.csv'), bigRows.join('\n'));

fs.writeFileSync(path.join(dir, 'utm_notes.txt'), 'utm_campaign=2026_jun_anz\nutm_source=linkedin\n');
fs.writeFileSync(path.join(dir, 'brief.pdf'), '%PDF-1.4\nnot a real pdf\n');
fs.writeFileSync(path.join(dir, 'mailbox.msg'), 'binary-ish');

// A REAL legacy .xls workbook: the case that used to be classified 'other' and
// never opened at all, so a media plan saved in the old format was invisible.
const legacy = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(legacy, XLSX.utils.aoa_to_sheet([
  ['Campaign', 'Budget'], ['LegacyLine', 1234],
]), 'Legacy');
fs.writeFileSync(path.join(dir, 'legacy_plan.xls'), XLSX.write(legacy, { type: 'buffer', bookType: 'biff8' }));

// A workbook that genuinely cannot be opened (encrypted/corrupt zip).
fs.writeFileSync(path.join(dir, 'locked_plan.xlsx'),
  Buffer.concat([Buffer.from('PK', 'latin1'), Buffer.from('garbage'.repeat(20))]));
// Byte-identical copy of the media plan, in a subfolder that sorts AFTER it so
// the original is the one walked (and parsed) first.
fs.mkdirSync(path.join(dir, 'zz_copies'), { recursive: true });
fs.copyFileSync(path.join(dir, 'media_plan.xlsx'), path.join(dir, 'zz_copies', 'media_plan_copy.xlsx'));

const { manifest, bundleText } = preprocess(dir);
const byName = (n) => manifest.files.find((f) => f.file.endsWith(n));
const intake = manifest.intake;

// ---- the intake summary exists and reconciles ----
check('manifest carries an intake summary', !!intake);
check('files_total counts every file', intake.files_total === 9, intake.files_total);
check('the byte-identical copy is a duplicate', intake.duplicates === 1, intake.duplicates);

// ---- content that MUST be read ----
check('xlsx sheet reached the bundle', bundleText.includes("SHEET: Media Plan"));
check('small CSV is bundled COMPLETE, not head-sampled', byName('plan_export.csv').sampled === false, byName('plan_export.csv'));
check('small CSV: every row reached the bundle', bundleText.includes('R41: line 40,4000'));
check('big CSV IS head-sampled', byName('audience.csv').sampled === true);
check('big CSV records its true row count', byName('audience.csv').rows === CSV_FULL_ROW_MAX + 50, byName('audience.csv').rows);
check('txt content reached the bundle', bundleText.includes('utm_campaign=2026_jun_anz'));

// ---- omissions that MUST be recorded ----
check('pdf is marked unread', byName('brief.pdf').unread === true);
check('unknown type is marked unread', byName('mailbox.msg').unread === true);
check('unread files are listed in intake', intake.unread.length === 2, intake.unread);
check('empty sheet recorded', byName('media_plan.xlsx').empty_sheets.includes('Blank'));
check('a real legacy .xls is PARSED, not skipped', !byName('legacy_plan.xls').parse_error, byName('legacy_plan.xls').parse_error);
check('legacy .xls content reached the bundle', bundleText.includes('LegacyLine'));
check('an unopenable workbook records a parse error', !!byName('locked_plan.xlsx').parse_error);
check('parse errors are listed in intake', intake.parse_errors.length === 1, intake.parse_errors);

// ---- the model must be TOLD content was withheld, not just left it out ----
check('inventory labels unread files explicitly', bundleText.includes('CONTENT NOT EXTRACTED'));
check('inventory labels the head-sampled CSV', bundleText.includes('HEAD SAMPLE ONLY'));
check('inventory labels the parse failure', bundleText.includes('COULD NOT BE PARSED'));
check('duplicate still labelled', bundleText.includes('BYTE-IDENTICAL DUPLICATE'));

// ---- a clean dump raises nothing ----
const clean = fs.mkdtempSync(path.join(os.tmpdir(), 'gl-clean-'));
XLSX.writeFile(wb, path.join(clean, 'only_plan.xlsx'));
const ci = preprocess(clean).manifest.intake;
check('clean dump: nothing unread', ci.unread.length === 0);
check('clean dump: no parse errors', ci.parse_errors.length === 0);
check('clean dump: no truncation', ci.truncated_sheets.length === 0);
check('clean dump: content_read counts the workbook', ci.content_read === 1, ci.content_read);

fs.rmSync(dir, { recursive: true, force: true });
fs.rmSync(clean, { recursive: true, force: true });

console.log('\n' + (fail ? '✗' : '✓') + ' intake: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
