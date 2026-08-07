// Stage 0 - deterministic preprocess. No model, no network.
// Walks a dump directory and produces:
//   - a manifest: every file with type, size, sha256, sheet names, and media
//     metadata measured IN CODE (jpeg/png dims, mp4 duration/dims via a
//     minimal ISO-BMFF parse since ffprobe is not on the box, pdf page count
//     best effort, csv row counts)
//   - a text bundle of every spreadsheet sheet as row-numbered CSV, for the
//     one model call (TAL-style large data CSVs are summarized, not inlined)
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const XLSX = require('xlsx');

const SHEET_CHAR_CAP = 30000;
const DATA_CSV_ROW_CAP = 15; // head sample for BIG data CSVs (audience lists etc)
// A CSV at or under this many data rows is bundled WHOLE: a media plan exported
// to CSV is 30-60 rows and losing everything past row 15 silently drops budget
// lines. Only genuine data exports (audience lists) exceed it.
const CSV_FULL_ROW_MAX = 200;
const TEXT_CHAR_CAP = 30000;
// Types that could carry campaign content but that this stage cannot read. They
// are labelled in the inventory (so the model knows the content was WITHHELD,
// not absent) and raised as findings by validate.js - never silently dropped.
const UNREAD_TYPES = ['pdf', 'deck', 'doc', 'other'];

function walk(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else if (e.name.toLowerCase() !== 'desktop.ini') acc.push(p);
  }
  return acc;
}

function classify(rel) {
  const ext = path.extname(rel).toLowerCase();
  // .xls/.xlsb are BIFF/binary workbooks that SheetJS reads through the same
  // XLSX.read call - a legacy media plan used to fall through to 'other' and
  // was never opened at all.
  if (['.xlsx', '.xlsm', '.xls', '.xlsb'].includes(ext)) return 'sheet';
  if (ext === '.csv' || ext === '.tsv') return 'table';
  if (['.txt', '.md'].includes(ext)) return 'text';
  if (['.jpg', '.jpeg', '.png', '.gif', '.webp'].includes(ext)) return 'image';
  if (ext === '.mp4' || ext === '.mov') return 'video';
  if (ext === '.pdf') return 'pdf';
  if (ext === '.pptx') return 'deck';
  if (ext === '.docx') return 'doc';
  return 'other';
}

// ---- media measurement (in code, never the model) ----
function jpegDims(buf) {
  let i = 2;
  while (i + 9 < buf.length) {
    if (buf[i] !== 0xff) { i++; continue; }
    const m = buf[i + 1];
    if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) {
      return { height: buf.readUInt16BE(i + 5), width: buf.readUInt16BE(i + 7) };
    }
    i += 2 + buf.readUInt16BE(i + 2);
  }
  return null;
}

function pngDims(buf) {
  if (buf.length < 24 || buf.readUInt32BE(12) !== 0x49484452) return null;
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

function mp4Meta(buf) {
  const out = {};
  function boxes(start, end, cb) {
    let i = start;
    while (i + 8 <= end) {
      let size = buf.readUInt32BE(i);
      const type = buf.toString('latin1', i + 4, i + 8);
      let header = 8;
      if (size === 1) { size = Number(buf.readBigUInt64BE(i + 8)); header = 16; }
      if (size < header || i + size > end) break;
      cb(type, i + header, i + size);
      i += size;
    }
  }
  boxes(0, buf.length, (t, s, e) => {
    if (t !== 'moov') return;
    boxes(s, e, (t2, s2, e2) => {
      if (t2 === 'mvhd') {
        const v = buf[s2];
        out.duration_seconds = v === 1
          ? Number(buf.readBigUInt64BE(s2 + 16)) / buf.readUInt32BE(s2 + 12)
          : buf.readUInt32BE(s2 + 12) / buf.readUInt32BE(s2 + 8);
      }
      if (t2 === 'trak') {
        boxes(s2, e2, (t3, s3) => {
          if (t3 !== 'tkhd') return;
          const off = buf[s3] === 1 ? 88 : 76;
          const w = buf.readUInt32BE(s3 + off) / 65536;
          const h = buf.readUInt32BE(s3 + off + 4) / 65536;
          if (w > 0 && h > 0) { out.width = w; out.height = h; }
        });
      }
    });
  });
  return Object.keys(out).length ? out : null;
}

function pdfPages(buf) {
  const tail = buf.toString('latin1', Math.max(0, buf.length - 2 * 1024 * 1024));
  const head = buf.toString('latin1', 0, Math.min(buf.length, 2 * 1024 * 1024));
  for (const chunk of [tail, head]) {
    const m = [...chunk.matchAll(/\/Type\s*\/Pages[^>]*?\/Count\s+(\d+)/g)];
    if (m.length) return { pages: Math.max(...m.map((x) => parseInt(x[1], 10))), method: 'pages-count' };
  }
  return null;
}

function measure(file, buf) {
  const ext = path.extname(file).toLowerCase();
  try {
    if (ext === '.jpg' || ext === '.jpeg') return jpegDims(buf);
    if (ext === '.png') return pngDims(buf);
    if (ext === '.mp4' || ext === '.mov') return mp4Meta(buf);
    if (ext === '.pdf') return pdfPages(buf);
  } catch (e) {
    return { error: String(e.message || e) };
  }
  return null;
}

// Two shapes in vendor workbooks cost real prompt tokens and carry no campaign
// information. Both are summarized rather than inlined - the sheet still
// appears (so the model knows it exists and can cite it) but its bulk does not.
// Measured on the Schneider NEL dump: 2,925 tokens, 7% of the bundle.
//   - header-only: a template tab with column headers and zero data rows, e.g.
//     the 8 unused format tabs in a Trade Desk bulk-upload workbook.
//   - enumeration: a long, narrow static reference list, e.g. that workbook's
//     496-row IANA time-zone tab and 105-row publisher list.
const ENUM_MIN_ROWS = 40;
const ENUM_MAX_COLS = 2;
const ENUM_SAMPLE = 5;

function classifySheet(rows) {
  if (rows.length <= 1) return 'header-only';
  const cols = Math.max(...rows.map((r) => r.split(',').length));
  if (cols <= ENUM_MAX_COLS && rows.length >= ENUM_MIN_ROWS) return 'enumeration';
  return 'data';
}

// Character scan rather than /,+$/: a regex anchored on a repeated class
// backtracks super-linearly, and a wide sheet can end a row with hundreds of
// empty cells.
function trimTrailingCommas(s) {
  let end = s.length;
  while (end > 0 && s.codePointAt(end - 1) === 44 /* , */) end--;
  return end === s.length ? s : s.slice(0, end);
}

function numberedCsv(ws) {
  const csv = XLSX.utils.sheet_to_csv(ws, { blankrows: false });
  // Trailing empty cells are pure padding on every row of a ragged sheet.
  const lines = csv.split('\n').map(trimTrailingCommas).filter((l) => l.length);
  if (!lines.length) return '';

  const kind = classifySheet(lines);
  if (kind === 'header-only') {
    return `R1: ${lines[0]}\n[TEMPLATE TAB: column headers only, no data rows]`;
  }
  if (kind === 'enumeration') {
    const sample = lines.slice(0, ENUM_SAMPLE).map((l, i) => `R${i + 1}: ${l}`).join('\n');
    return `${sample}\n[STATIC REFERENCE LIST: ${lines.length} rows total, first ${ENUM_SAMPLE} shown - not campaign data]`;
  }
  return lines.map((l, i) => `R${i + 1}: ${l}`).join('\n');
}

// ---- content extraction, one branch per readable type. Stamps the entry with
// whatever was LOST (truncated/empty sheets, head-sampled rows, parse errors)
// so validate.js can raise it - preprocess never drops content silently.
function extractSheet(entry, buf, rel, bundle) {
  try {
    const wb = XLSX.read(buf, { type: 'buffer' });
    entry.sheets = wb.SheetNames;
    entry.truncated_sheets = [];
    entry.empty_sheets = [];
    for (const name of wb.SheetNames) {
      let text = numberedCsv(wb.Sheets[name]);
      if (!text) { entry.empty_sheets.push(name); continue; }
      if (text.length > SHEET_CHAR_CAP) {
        entry.truncated_sheets.push(name);
        text = text.slice(0, SHEET_CHAR_CAP) + '\n[TRUNCATED at ' + SHEET_CHAR_CAP + ' chars]';
      }
      bundle.push(`=== FILE: ${rel} | SHEET: ${name} ===\n${text}`);
    }
  } catch (e) {
    entry.parse_error = String(e.message || e);
  }
}

function extractTable(entry, buf, rel, bundle) {
  const lines = buf.toString('utf8').split(/\r?\n/).filter((l) => l.length);
  entry.rows = Math.max(0, lines.length - 1); // data rows excluding header
  // Small CSV = probably a plan or a tracker: bundle it whole. Big CSV = an
  // audience/data export: a head sample is the right call.
  entry.sampled = entry.rows > CSV_FULL_ROW_MAX;
  const keep = entry.sampled ? DATA_CSV_ROW_CAP : lines.length;
  const body = lines.slice(0, keep).map((l, i) => `R${i + 1}: ${l}`).join('\n');
  const label = entry.sampled
    ? `DATA CSV (${entry.rows} data rows; head sample only)`
    : `CSV (${entry.rows} data rows; complete)`;
  bundle.push(`=== FILE: ${rel} | ${label} ===\n${body}`);
}

function extractText(entry, buf, rel, bundle) {
  let text = buf.toString('utf8');
  if (text.length > TEXT_CHAR_CAP) {
    entry.truncated = true;
    text = text.slice(0, TEXT_CHAR_CAP) + '\n[TRUNCATED at ' + TEXT_CHAR_CAP + ' chars]';
  }
  if (text.trim()) bundle.push(`=== FILE: ${rel} | TEXT ===\n${text}`);
}

const EXTRACTORS = { sheet: extractSheet, table: extractTable, text: extractText };

/** What the pipeline actually saw, so a run over PART of a dump can never look
 *  identical to a run over all of it. */
function intakeSummary(files) {
  const live = files.filter((f) => !f.duplicate_of);
  return {
    files_total: files.length,
    duplicates: files.length - live.length,
    content_read: live.filter((f) => EXTRACTORS[f.type] && !f.parse_error).length,
    unread: live.filter((f) => f.unread).map((f) => f.file),
    parse_errors: live.filter((f) => f.parse_error).map((f) => ({ file: f.file, error: f.parse_error })),
    truncated_sheets: live.flatMap((f) => (f.truncated_sheets || []).map((s) => `${f.file} | sheet '${s}'`)),
    sampled_csvs: live.filter((f) => f.sampled).map((f) => `${f.file} (${f.rows} rows)`),
  };
}

/**
 * preprocess(dir) -> { manifest, bundleText }
 * manifest.files: [{file, bytes, sha256, type, sheets?, measured?, rows?, duplicate_of?, unread?, parse_error?}]
 * manifest.intake: the reconciliation summary (see intakeSummary)
 * bundleText: the converted-sheets text for the model call.
 */
function preprocess(rootDir) {
  const files = [];
  const bundle = [];
  const byHash = new Map();

  for (const abs of walk(rootDir)) {
    const rel = path.relative(rootDir, abs).split(path.sep).join('/');
    const buf = fs.readFileSync(abs);
    const sha = crypto.createHash('sha256').update(buf).digest('hex');
    const entry = { file: rel, bytes: buf.length, sha256: sha, type: classify(rel) };
    if (byHash.has(sha)) {
      entry.duplicate_of = byHash.get(sha);
      files.push(entry);
      continue; // byte-identical: measured and bundled once
    }
    byHash.set(sha, rel);

    const m = measure(abs, buf);
    if (m) entry.measured = m;

    const extractor = EXTRACTORS[entry.type];
    if (extractor) extractor(entry, buf, rel, bundle);
    else if (UNREAD_TYPES.includes(entry.type)) {
      // No converter for this type: the file reaches the model as a filename
      // and nothing else. Flag it on the manifest (not just in the inventory
      // prose) so validate.js can raise it as a real finding - a file that was
      // PRESENT but UNREAD is a silent hole in the audit otherwise. `unread`
      // feeds the intake summary (i_unread); `converted:false` is the per-file
      // marker validate.js's f_unread check reads.
      entry.unread = true;
      entry.converted = false;
    }
    files.push(entry);
  }

  files.sort((a, b) => a.file.localeCompare(b.file));

  // Manifest header block for the model: file inventory + code measurements.
  // Anything whose content was withheld says so EXPLICITLY, so the model treats
  // it as unavailable rather than as an empty or irrelevant file.
  const inv = files.map((f) => {
    const bits = [`${f.file} (${f.type}, ${f.bytes} bytes)`];
    if (f.duplicate_of) bits.push(`BYTE-IDENTICAL DUPLICATE of ${f.duplicate_of}`);
    if (f.measured) bits.push('measured: ' + JSON.stringify(f.measured));
    if (f.rows != null) bits.push(`${f.rows} data rows`);
    if (f.sampled) bits.push('HEAD SAMPLE ONLY (rows beyond the sample were not supplied)');
    if (f.parse_error) bits.push(`COULD NOT BE PARSED (${f.parse_error}) - content unavailable to this run`);
    if (f.truncated_sheets && f.truncated_sheets.length) bits.push(`TRUNCATED SHEETS: ${f.truncated_sheets.join(', ')}`);
    if (f.unread) bits.push('CONTENT NOT EXTRACTED (this file type is not read by this run; its content is unavailable, not absent)');
    return '- ' + bits.join(' | ');
  }).join('\n');

  const intake = intakeSummary(files);

  const bundleText = `=== FILE INVENTORY (measured in code) ===\n${inv}\n\n${bundle.join('\n\n')}`;
  return { manifest: { root: rootDir, generated_at: new Date().toISOString(), intake, files }, bundleText };
}

module.exports = { preprocess, classify, CSV_FULL_ROW_MAX, SHEET_CHAR_CAP, UNREAD_TYPES };
