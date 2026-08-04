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
const DATA_CSV_ROW_CAP = 15; // data CSVs (audience lists etc) get a head sample only

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
  if (ext === '.xlsx' || ext === '.xlsm') return 'sheet';
  if (ext === '.csv' || ext === '.tsv') return 'table';
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

function numberedCsv(ws) {
  const csv = XLSX.utils.sheet_to_csv(ws, { blankrows: false });
  const lines = csv.split('\n').filter((l) => l.length);
  return lines.map((l, i) => `R${i + 1}: ${l}`).join('\n');
}

/**
 * preprocess(dir) -> { manifest, bundleText }
 * manifest.files: [{file, bytes, sha256, type, sheets?, measured?, rows?, duplicate_of?}]
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

    if (entry.type === 'sheet') {
      try {
        const wb = XLSX.read(buf, { type: 'buffer' });
        entry.sheets = wb.SheetNames;
        for (const name of wb.SheetNames) {
          let text = numberedCsv(wb.Sheets[name]);
          if (!text) continue;
          if (text.length > SHEET_CHAR_CAP) text = text.slice(0, SHEET_CHAR_CAP) + '\n[TRUNCATED at ' + SHEET_CHAR_CAP + ' chars]';
          bundle.push(`=== FILE: ${rel} | SHEET: ${name} ===\n${text}`);
        }
      } catch (e) {
        entry.parse_error = String(e.message || e);
      }
    } else if (entry.type === 'table') {
      const text = buf.toString('utf8');
      const lines = text.split(/\r?\n/).filter((l) => l.length);
      entry.rows = Math.max(0, lines.length - 1); // data rows excluding header
      const sample = lines.slice(0, DATA_CSV_ROW_CAP).map((l, i) => `R${i + 1}: ${l}`).join('\n');
      bundle.push(`=== FILE: ${rel} | DATA CSV (${entry.rows} data rows; head sample only) ===\n${sample}`);
    }
    files.push(entry);
  }

  files.sort((a, b) => a.file.localeCompare(b.file));

  // Manifest header block for the model: file inventory + code measurements.
  const inv = files.map((f) => {
    const bits = [`${f.file} (${f.type}, ${f.bytes} bytes)`];
    if (f.duplicate_of) bits.push(`BYTE-IDENTICAL DUPLICATE of ${f.duplicate_of}`);
    if (f.measured) bits.push('measured: ' + JSON.stringify(f.measured));
    if (f.rows != null) bits.push(`${f.rows} data rows`);
    if (f.type === 'deck' || f.type === 'doc') bits.push('NOT CONVERTED (content unavailable to this run)');
    return '- ' + bits.join(' | ');
  }).join('\n');

  const bundleText = `=== FILE INVENTORY (measured in code) ===\n${inv}\n\n${bundle.join('\n\n')}`;
  return { manifest: { root: rootDir, generated_at: new Date().toISOString(), files }, bundleText };
}

module.exports = { preprocess };
