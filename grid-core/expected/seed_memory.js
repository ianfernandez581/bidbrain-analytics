// Greenlight memory seeder - turns a folder of media-buyer spreadsheets into
// cited markdown "flag ledgers", so the memory wiki has reference material
// before any campaign has ever run through Greenlight.
//
// DETERMINISTIC. No model call, no ANTHROPIC_API_KEY, no network. Every item it
// emits carries a FILE | SHEET | CELL citation in the same convention the
// extractor uses, so a human (or a later model pass) can verify each one
// against the source before promoting it to a lesson.
//
// It finds four things buyers actually do in spreadsheets:
//   1. ANNOTATION COLUMNS  - a column headed Remarks / Status / Comments /
//      Action / Approval / Go Live / CTA for ... ; non-empty cells are flags,
//      and the empty ones are counted (an approval field with nothing in it is
//      itself a finding).
//   2. MARGIN NOTES        - free text sitting outside the data block, e.g. a
//      bare note in the column right of a key:value header row.
//   3. FLAG PHRASES        - cells containing FLAG / TBC / awaiting / not
//      provided / revise / over N char limit / pending / to confirm ...
//   4. REVIEW BLOCKS       - label:value pairs from copy-review documents:
//      The problem / What we propose / What changed / Original / Our update.
//
// Usage:
//   node expected/seed_memory.js --files <dir> [--out <dir>] [--max-cell 400]
// Defaults: --files ../files   --out ./memory-seed
//
// Output: <out>/flags/<source-slug>.md   one ledger per spreadsheet
//         <out>/INDEX.md                 counts + what to do next
'use strict';

const fs = require('fs');
const path = require('path');
const XLSX = require('xlsx'); // already a grid-core dependency (preprocess.js)

const ANNOTATION_HEADER = /^(remarks?|comments?|notes?|status|flags?|feedback|review(er)?( status)?|actions?( required| needed)?|issues?|approv(al|ed)( by| status)?|sign.?off|go.?live( status| date)?|cta for|next steps?|owner|due|resolution|amend(ment)?s?|changes?( required)?|revisions?)\b/i;

const FLAG_PHRASE = new RegExp([
  '\\bflag(ged|s)?\\b', '\\btbc\\b', '\\btbd\\b', '\\bt\\.b\\.c\\b',
  'awaiting', 'not provided', 'no(t)? (yet )?(supplied|received|confirmed|specified|available)',
  'pending', '\\brevise\\b', 'revised to', 'to (be )?(confirm|check|revise|update)',
  'please (confirm|approve|provide|check)', 'needs? (to be |a )?(confirm|approv|updat|chang|shorter)',
  'over \\d+ ?char', 'exceeds', 'too long', 'above the (cap|limit)', 'character limit',
  '\\bissue\\b', '\\bproblem\\b', '\\bmissing\\b', '\\bincorrect\\b', '\\bwrong\\b',
  '\\bdiscrepancy\\b', 'does not match', 'mismatch', 'not applicable', '\\bn/?a\\b',
  'constructed', 'bypass', 'assumed', 'placeholder', 'draft only', 'superseded',
].join('|'), 'i');

const REVIEW_LABEL = /^\s*(the problem|what we propose|what changed|our update|original|proposed|current|previously|before|after|reason|rationale|why)\s*[:(]?/i;

const clean = (v) => {
  if (v == null) return '';
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  return String(v).replace(/[\u2013\u2014]/g, '-').replace(/\s*\n\s*/g, ' / ').replace(/\s+/g, ' ').trim();
};
const slug = (s) => s.toLowerCase().replace(/\.[a-z]+$/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 70);
const esc = (s) => s.replace(/\|/g, '\\|');

function readGrid(ws) {
  const ref = ws['!ref'];
  if (!ref) return null;
  const r = XLSX.utils.decode_range(ref);
  const grid = [];
  for (let row = r.s.r; row <= r.e.r; row++) {
    const line = [];
    for (let col = r.s.c; col <= r.e.c; col++) {
      const cell = ws[XLSX.utils.encode_cell({ r: row, c: col })];
      line.push(cell ? clean(cell.v) : '');
    }
    grid.push(line);
  }
  return { grid, r };
}

function addr(rowIdx, colIdx, base) {
  return XLSX.utils.encode_cell({ r: base.s.r + rowIdx, c: base.s.c + colIdx });
}

function scanSheet(sheetName, ws, maxCell) {
  const read = readGrid(ws);
  if (!read) return null;
  const { grid, r: base } = read;
  const cut = (s) => (s.length > maxCell ? s.slice(0, maxCell) + ' [...]' : s);
  const out = { sheet: sheetName, annotations: [], notes: [], flags: [], review: [], emptyCols: [] };
  const seen = new Set();
  const claim = (a) => (seen.has(a) ? false : (seen.add(a), true));

  // ---- 1. annotation columns: a header cell anywhere that names a flag field
  const annCols = new Map(); // colIdx -> {header, headerRow}
  grid.forEach((line, ri) => {
    line.forEach((v, ci) => {
      if (!v || v.length > 40 || annCols.has(ci)) return;
      if (ANNOTATION_HEADER.test(v)) annCols.set(ci, { header: v, headerRow: ri });
    });
  });
  for (const [ci, meta] of annCols) {
    let filled = 0;
    let empty = 0;
    for (let ri = meta.headerRow + 1; ri < grid.length; ri++) {
      const v = (grid[ri] || [])[ci] || '';
      const rowHasData = (grid[ri] || []).some((x, i) => i !== ci && x);
      if (!v) { if (rowHasData) empty++; continue; }
      filled++;
      const a = addr(ri, ci, base);
      if (claim(a)) out.annotations.push({ cell: a, header: meta.header, text: cut(v), row: base.s.r + ri + 1 });
    }
    if (empty && !filled) out.emptyCols.push({ header: meta.header, rows: empty, col: addr(meta.headerRow, ci, base) });
    else if (empty) out.emptyCols.push({ header: meta.header, rows: empty, col: addr(meta.headerRow, ci, base), partial: true });
  }

  // ---- 2. margin notes: buyer commentary sitting outside the table's own
  // columns. Two shapes matter, and both need the sheet's table header located
  // first so ordinary data cells are not mistaken for notes:
  //   - above the header: the key:value preamble (Campaign Start Date | date |
  //     "revise to june start through august")
  //   - below/beside it: a column the header row never names
  const isNum = (s) => /^-?[\d.,%$ ]+$/.test(s);
  const headerRows = new Set();
  const headerCols = new Set();
  grid.forEach((line, ri) => {
    const filled = line.map((v, i) => [v, i]).filter(([v]) => v);
    if (filled.length < 4) return;
    if (!filled.every(([v]) => v.length <= 40 && !isNum(v))) return;
    headerRows.add(ri);
    filled.forEach(([, i]) => headerCols.add(i));
  });
  const firstHeaderRow = headerRows.size ? Math.min(...headerRows) : Infinity;

  grid.forEach((line, ri) => {
    if (headerRows.has(ri)) return;
    const lastData = line.reduce((acc, v, i) => (v ? i : acc), -1);
    if (lastData < 2) return;
    const label = clean(line[0] || line[1] || '');
    for (let ci = 2; ci <= lastData; ci++) {
      const v = line[ci];
      if (!v || v.length < 4 || isNum(v) || annCols.has(ci)) continue;
      // below the table header, only unnamed columns count as margin notes
      if (ri > firstHeaderRow && headerCols.has(ci)) continue;
      const a = addr(ri, ci, base);
      if (claim(a)) out.notes.push({ cell: a, label: label || '(no label)', text: cut(v) });
    }
  });

  // ---- 3. flag phrases anywhere
  grid.forEach((line, ri) => {
    line.forEach((v, ci) => {
      if (!v || v.length < 3) return;
      if (!FLAG_PHRASE.test(v)) return;
      const a = addr(ri, ci, base);
      if (claim(a)) out.flags.push({ cell: a, text: cut(v), context: clean(line[0] || line[1] || '').slice(0, 80) });
    });
  });

  // ---- 4. review blocks: label in col A, content in col B
  grid.forEach((line, ri) => {
    const label = line[0] || '';
    if (!REVIEW_LABEL.test(label)) return;
    const body = line.slice(1).find((x) => x) || '';
    if (!body) return;
    const a = addr(ri, 1, base);
    let heading = '';
    for (let k = ri - 1; k >= 0 && k > ri - 14; k--) {
      const h = (grid[k] || [])[0] || '';
      if (h && !REVIEW_LABEL.test(h) && h.length < 120) { heading = h; break; }
    }
    out.review.push({ cell: a, label: label.replace(/\s*[:(]\s*$/, ''), text: cut(body), heading });
  });

  const total = out.annotations.length + out.notes.length + out.flags.length + out.review.length;
  return total || out.emptyCols.length ? out : null;
}

function renderFile(fileRel, sheets) {
  const L = [];
  L.push('# Flag ledger - ' + fileRel);
  L.push('');
  L.push('> Extracted deterministically by `expected/seed_memory.js`. Every row cites the cell it');
  L.push('> came from. Nothing here is a lesson yet - a human reviews these and promotes the');
  L.push('> transferable ones into `memory/lessons/` (see docs/memory-design.md §8).');
  L.push('');
  for (const s of sheets) {
    L.push('## Sheet: ' + s.sheet);
    L.push('');
    if (s.annotations.length) {
      L.push('### Buyer annotations (flag columns)');
      L.push('');
      L.push('| Cell | Column | Note |');
      L.push('|---|---|---|');
      for (const a of s.annotations) L.push(`| ${a.cell} | ${esc(a.header)} | ${esc(a.text)} |`);
      L.push('');
    }
    if (s.notes.length) {
      L.push('### Margin notes (text outside the data block)');
      L.push('');
      L.push('| Cell | Against | Note |');
      L.push('|---|---|---|');
      for (const n of s.notes) L.push(`| ${n.cell} | ${esc(n.label)} | ${esc(n.text)} |`);
      L.push('');
    }
    if (s.review.length) {
      L.push('### Review blocks (problem / proposal / change)');
      L.push('');
      let lastHeading = null;
      for (const rv of s.review) {
        if (rv.heading && rv.heading !== lastHeading) { L.push('**' + rv.heading + '**'); L.push(''); lastHeading = rv.heading; }
        L.push(`- \`${rv.cell}\` **${rv.label}:** ${rv.text}`);
      }
      L.push('');
    }
    if (s.flags.length) {
      L.push('### Flag phrases');
      L.push('');
      L.push('| Cell | Row context | Text |');
      L.push('|---|---|---|');
      for (const f of s.flags) L.push(`| ${f.cell} | ${esc(f.context)} | ${esc(f.text)} |`);
      L.push('');
    }
    if (s.emptyCols.length) {
      L.push('### Unfilled tracking columns (the absence is a finding)');
      L.push('');
      for (const e of s.emptyCols) {
        L.push(`- \`${e.col}\` **${e.header}** - ${e.rows} data row(s) with nothing recorded${e.partial ? ' (partially filled)' : ''}`);
      }
      L.push('');
    }
  }
  return L.join('\n') + '\n';
}

function main() {
  const argv = process.argv;
  const argOf = (k, d) => { const i = argv.indexOf(k); return i > -1 && argv[i + 1] ? argv[i + 1] : d; };
  const filesDir = path.resolve(argOf('--files', path.join(__dirname, '..', 'files')));
  const outDir = path.resolve(argOf('--out', path.join(__dirname, 'memory-seed')));
  const maxCell = Number(argOf('--max-cell', 400));

  if (!fs.existsSync(filesDir)) {
    console.error('[seed] no such directory: ' + filesDir);
    process.exit(2);
  }

  const found = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(xlsx|xlsm|xltx)$/i.test(e.name) && !e.name.startsWith('~$')) found.push(p);
    }
  })(filesDir);

  if (!found.length) {
    console.error('[seed] no spreadsheets under ' + filesDir);
    process.exit(2);
  }

  fs.mkdirSync(path.join(outDir, 'flags'), { recursive: true });
  const summary = [];

  for (const file of found.sort()) {
    const rel = path.relative(filesDir, file).split(path.sep).join('/');
    let wb;
    try { wb = XLSX.readFile(file, { cellDates: true }); }
    catch (e) { console.error(`[seed] SKIP ${rel}: ${e.message}`); continue; }

    const sheets = [];
    for (const name of wb.SheetNames) {
      const s = scanSheet(name, wb.Sheets[name], maxCell);
      if (s) sheets.push(s);
    }
    const counts = sheets.reduce((a, s) => ({
      annotations: a.annotations + s.annotations.length,
      notes: a.notes + s.notes.length,
      flags: a.flags + s.flags.length,
      review: a.review + s.review.length,
      emptyCols: a.emptyCols + s.emptyCols.length,
    }), { annotations: 0, notes: 0, flags: 0, review: 0, emptyCols: 0 });
    const total = counts.annotations + counts.notes + counts.flags + counts.review;

    if (!sheets.length) { console.log(`[seed] ${rel}: nothing flagged`); summary.push({ rel, counts, total, out: null }); continue; }

    const outName = 'flags/' + slug(rel) + '.md'; // full rel path: same basename in two folders must not collide
    fs.writeFileSync(path.join(outDir, outName), renderFile(rel, sheets));
    console.log(`[seed] ${rel}: ${total} item(s) -> ${outName}`);
    summary.push({ rel, counts, total, out: outName });
  }

  const I = [];
  I.push('# Memory seed - extracted buyer flags');
  I.push('');
  I.push(`Source: \`${filesDir}\` · ${found.length} spreadsheet(s) · generated ${new Date().toISOString().slice(0, 10)}`);
  I.push('');
  I.push('Deterministic extraction, no model call. Each ledger cites the cell every item came from.');
  I.push('');
  I.push('| Source file | Annotations | Margin notes | Review blocks | Flag phrases | Unfilled cols | Ledger |');
  I.push('|---|--:|--:|--:|--:|--:|---|');
  for (const s of summary) {
    I.push(`| ${esc(s.rel)} | ${s.counts.annotations} | ${s.counts.notes} | ${s.counts.review} | ${s.counts.flags} | ${s.counts.emptyCols} | ${s.out ? `[ledger](${s.out})` : '-'} |`);
  }
  I.push('');
  I.push('## Next step');
  I.push('');
  I.push('These ledgers are raw experience, not lessons. Promote the transferable ones into');
  I.push('`expected/memory/lessons/` using the front-matter format in `docs/memory-design.md` §5:');
  I.push('a platform constraint that will recur (a character cap, a daily minimum) is a **global**');
  I.push('lesson; a habit of one agency or client is **agency/** or **client/** scoped; a one-off is');
  I.push('campaign-scoped or discarded.');
  I.push('');
  fs.writeFileSync(path.join(outDir, 'INDEX.md'), I.join('\n') + '\n');
  console.log(`[seed] wrote ${outDir}/INDEX.md`);
}

main();
