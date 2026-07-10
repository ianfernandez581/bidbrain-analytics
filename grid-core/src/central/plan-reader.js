/*
 * src/central/plan-reader.js — Central media-plan reader (server-side).
 * ----------------------------------------------------------------------------
 * Extracts Central [CONFIG] fields from a dropped media-plan file, with per-field
 * provenance, then matches the result against existing Central rows. It NEVER
 * writes a campaign row — it produces a draft that a human reviews and commits.
 *
 * Reuse (per the audit): SheetJS (`xlsx`) for spreadsheets and parser.js's own
 * text extraction (`_getRawText`) for PDF/DOCX/PPTX; parser.js's `_parseDate` for
 * dates; the @anthropic-ai/sdk tool-call shape from parser.js. The extraction
 * SCHEMA is NEW (Central CONFIG, not historical delivery).
 *
 * Degrades gracefully: no ANTHROPIC_API_KEY (or any LLM failure) → deterministic
 * header-keyword heuristic, everything tagged confidence:"low". The buyer always
 * gets a review panel — never a dead end.
 */
'use strict';
const fs = require('fs');
const XLSX = require('xlsx');
const parser = require('../brain/parser');

const HAS_ANTHROPIC = !!process.env.ANTHROPIC_API_KEY;
const CLAUDE_MODEL = process.env.BRAIN_CLAUDE_MODEL || 'claude-opus-4-8';

// The [CONFIG] fields we extract — calc.js names verbatim (single naming authority).
const TARGET_FIELDS = ['jobNumber', 'client', 'name', 'objective', 'channel', 'managedBy',
  'startDate', 'endDate', 'platformMargin', 'adServingCost', 'forecastCpm', 'keyKpi', 'kpiTarget',
  'budgetGross', 'totalBudget', 'spendMult', 'notes'];

// Field → coercion kind (drives normalization + heuristic value-shape validation).
const FIELD_KIND = {
  jobNumber: 'text', client: 'text', name: 'text', objective: 'text', channel: 'text',
  managedBy: 'text', keyKpi: 'text', notes: 'text',
  startDate: 'date', endDate: 'date',
  platformMargin: 'pct', spendMult: 'num', adServingCost: 'money', forecastCpm: 'money',
  kpiTarget: 'num', budgetGross: 'money', totalBudget: 'money'
};

const SHEET_PRIORITY = /plan|media|brief|launch|budget/i;
const CELL_CAP = 3500;   // max non-empty cells serialized to the LLM

/* keep in sync with render-central.js centralRowId() — the join key is (client,name). */
function centralRowId(client, name) {
  const n = s => String(s == null ? '' : s).trim().toLowerCase().replace(/\s+/g, ' ');
  return n(client) + '::' + n(name);
}

// ---------------------------------------------------------------------------
// Normalization (post-extraction; per-field, never fails the whole extraction)
// ---------------------------------------------------------------------------
function normNum(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  let s = String(v).trim().toLowerCase().replace(/[$,\s]/g, '').replace(/aud|usd|sgd|x/g, '');
  let mult = 1;
  if (/[0-9.]k$/.test(s)) { mult = 1e3; s = s.replace(/k$/, ''); }
  else if (/[0-9.]m$/.test(s)) { mult = 1e6; s = s.replace(/m$/, ''); }
  const n = parseFloat(s);
  return Number.isFinite(n) ? n * mult : null;
}
function normPct(v) {
  if (v == null || v === '') return null;
  const hasPctSign = typeof v === 'string' && v.includes('%');
  const n = normNum(typeof v === 'string' ? v.replace('%', '') : v);
  if (n == null) return null;
  if (hasPctSign) return n / 100;
  return n > 1 ? n / 100 : n;          // 0.4 stays 0.4; 40 becomes 0.4
}
function normDate(v) { return parser._parseDate(v); }
function normText(v) { if (v == null) return null; const s = String(v).trim(); return s === '' ? null : s; }
function firstNumber(v) { if (v == null) return null; const m = String(v).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/); return m ? parseFloat(m[0]) : null; }

// Coerce one raw string per its field kind. Returns {value, parseError?}.
function coerce(field, raw) {
  if (raw == null || String(raw).trim() === '') return { value: null };
  const kind = FIELD_KIND[field];
  let out;
  if (kind === 'money' || kind === 'num') out = normNum(raw);
  else if (kind === 'pct') out = normPct(raw);
  else if (kind === 'date') out = normDate(raw);
  else out = normText(raw);
  if (out == null && kind !== 'text') return { value: null, parseError: `could not parse "${String(raw).slice(0, 40)}" as ${kind}` };
  return { value: out };
}

// Build the final per-field object (value coerced + provenance) from raw extraction map.
function normalizeFields(rawMap) {
  const fields = {};
  for (const f of TARGET_FIELDS) {
    const hit = rawMap[f];
    if (!hit || hit.value == null || String(hit.value).trim() === '') { fields[f] = { value: null, confidence: hit ? (hit.confidence || 'low') : null }; continue; }
    const c = coerce(f, hit.value);
    fields[f] = {
      value: c.value,
      confidence: hit.confidence === 'high' ? 'high' : 'low',
      sheet: hit.sheet || null, cellRef: hit.cellRef || null, page: hit.page != null ? hit.page : null,
      raw: String(hit.value).slice(0, 80)
    };
    if (c.parseError) { fields[f].parseError = c.parseError; }
  }
  // derive kpiTarget from keyKpi text when not separately found
  if ((fields.kpiTarget.value == null) && fields.keyKpi.value != null) {
    const n = firstNumber(fields.keyKpi.value);
    if (n != null) fields.kpiTarget = { value: n, confidence: 'low', sheet: fields.keyKpi.sheet, cellRef: fields.keyKpi.cellRef, page: fields.keyKpi.page, derivedFrom: 'keyKpi' };
  }
  return fields;
}

// ---------------------------------------------------------------------------
// Spreadsheet reading → a cell grid that preserves A1 provenance
// ---------------------------------------------------------------------------
function readGrid(localPath) {
  const wb = XLSX.readFile(localPath, { cellDates: true });
  const sheets = [];
  wb.SheetNames.forEach(name => {
    const ws = wb.Sheets[name];
    if (!ws || !ws['!ref']) return;
    const range = XLSX.utils.decode_range(ws['!ref']);
    const cells = [];                 // {ref,r,c,val}
    const map = new Map();            // "r:c" -> val (string)
    for (let r = range.s.r; r <= range.e.r; r++) {
      for (let c = range.s.c; c <= range.e.c; c++) {
        const ref = XLSX.utils.encode_cell({ r, c });
        const cell = ws[ref];
        if (!cell) continue;
        let val = cell.w != null ? cell.w : cell.v;
        if (val instanceof Date) val = val.toISOString().slice(0, 10);
        if (val == null || String(val).trim() === '') continue;
        val = String(val).trim();
        cells.push({ ref, r, c, val });
        map.set(r + ':' + c, val);
      }
    }
    if (cells.length) sheets.push({ name, cells, map, range });
  });
  // prioritize plan-ish sheets first (stable order otherwise)
  sheets.sort((a, b) => (SHEET_PRIORITY.test(b.name) ? 1 : 0) - (SHEET_PRIORITY.test(a.name) ? 1 : 0));
  return sheets;
}

// Compact per-sheet text with A1 refs so the LLM can cite cellRef. Capped.
function gridToText(sheets) {
  let out = '', used = 0;
  for (const sh of sheets) {
    out += `\n## Sheet: ${sh.name}\n`;
    for (const cell of sh.cells) {
      if (used >= CELL_CAP) { out += '…(truncated)\n'; return out; }
      out += `${cell.ref}: ${cell.val}\n`;
      used++;
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// LLM extraction (Central CONFIG schema) — key-gated, tool-forced. Optional.
// ---------------------------------------------------------------------------
function extractionSchema() {
  return {
    type: 'object', properties: {
      extractions: {
        type: 'array', items: {
          type: 'object', properties: {
            field: { type: 'string', enum: TARGET_FIELDS },
            value: { type: 'string' },
            sheet: { type: ['string', 'null'] },
            cell_ref: { type: ['string', 'null'] },
            page: { type: ['integer', 'null'] },
            confidence: { type: 'string', enum: ['high', 'low'] }
          }, required: ['field', 'value', 'confidence']
        }
      }
    }, required: ['extractions']
  };
}
const SYS_PROMPT = `You extract campaign CONFIG fields from a marketing media plan into strict JSON via the emit tool.
Extract ONLY these fields (omit any you cannot find — never guess): ${TARGET_FIELDS.join(', ')}.
keyKpi is the verbatim KPI text (e.g. "300 opt-ins"); kpiTarget is just its number (e.g. 300).
platformMargin/spendMult are the agency's commercial numbers if stated. Money may be written like "$20k".
For every field, cite provenance: for spreadsheets set sheet + cell_ref (e.g. "D14"); for documents set page.
Return confidence "high" only when the source is explicit and unambiguous, else "low". Never invent a value.`;

async function llmExtract(userContent) {
  const Anthropic = require('@anthropic-ai/sdk');
  const client = new Anthropic();
  const msg = await Promise.race([
    client.messages.create({
      model: CLAUDE_MODEL, max_tokens: 4096, system: SYS_PROMPT,
      tools: [{ name: 'emit', description: 'Emit the extracted CONFIG fields.', input_schema: extractionSchema() }],
      tool_choice: { type: 'tool', name: 'emit' },
      messages: [{ role: 'user', content: userContent }]
    }),
    new Promise((_, rej) => setTimeout(() => rej(new Error('Claude timed out')), 90000))
  ]);
  const use = msg.content.find(c => c.type === 'tool_use');
  const arr = (use && use.input && use.input.extractions) || [];
  const map = {};
  for (const e of arr) {
    if (!TARGET_FIELDS.includes(e.field)) continue;
    map[e.field] = { value: e.value, sheet: e.sheet || null, cellRef: e.cell_ref || null, page: e.page != null ? e.page : null, confidence: e.confidence === 'high' ? 'high' : 'low' };
  }
  return map;
}

// ---------------------------------------------------------------------------
// Heuristic extraction (no key / LLM failure) — header-keyword proximity.
// ---------------------------------------------------------------------------
const KEYWORDS = {
  jobNumber: ['job number', 'job no', 'job #', 'jobno', 'job code', 'project number', 'po number', 'job'],
  client: ['client', 'advertiser', 'account name', 'brand', 'customer'],
  name: ['campaign name', 'campaign', 'initiative', 'activity name'],
  objective: ['objective', 'campaign objective', 'goal', 'purpose'],
  channel: ['channel', 'platform', 'media type', 'network'],
  managedBy: ['managed by', 'account manager', 'campaign manager', 'owner', 'trader', 'buyer', 'manager'],
  startDate: ['start date', 'flight start', 'live date', 'launch date', 'start'],
  endDate: ['end date', 'flight end', 'close date', 'finish', 'end'],
  platformMargin: ['platform margin', 'agency margin', 'commission', 'margin'],
  adServingCost: ['ad serving cost', 'adserving cost', 'ad-serving', 'ad serving', 'serving cost'],
  forecastCpm: ['forecast cpm', 'target cpm', 'planned cpm', 'cpm'],
  keyKpi: ['key kpi', 'kpi', 'key metric', 'success metric'],
  budgetGross: ['gross budget', 'budget gross', 'gross media', 'gross'],
  totalBudget: ['total budget', 'net budget', 'media budget', 'budget', 'investment'],
  spendMult: ['spend multiplier', 'billing multiplier', 'markup', 'mark-up', 'multiplier', 'uplift'],
  notes: ['notes', 'comments', 'remarks']
};
// evaluate specific keys before generic ones so "gross"/"platform margin" win over "budget"/"margin"
// kpiTarget is NOT here — it is derived from keyKpi's number in normalizeFields().
const HEURISTIC_ORDER = ['jobNumber', 'client', 'name', 'objective', 'channel', 'managedBy', 'startDate', 'endDate',
  'budgetGross', 'totalBudget', 'platformMargin', 'spendMult', 'adServingCost', 'forecastCpm', 'keyKpi', 'notes'];

function valueShapeOk(field, s) {
  const kind = FIELD_KIND[field];
  if (kind === 'date') return normDate(s) != null;
  if (kind === 'money' || kind === 'num') return normNum(s) != null;
  if (kind === 'pct') return normNum(String(s).replace('%', '')) != null;
  // text: non-empty and not obviously another header keyword
  const low = String(s).toLowerCase();
  return String(s).trim() !== '' && !Object.values(KEYWORDS).some(list => list.includes(low));
}

function heuristicExtract(sheets) {
  const map = {};
  const usedRefs = new Set();
  for (const field of HEURISTIC_ORDER) {
    const kws = KEYWORDS[field];
    if (!kws) continue;
    let best = null;
    for (const sh of sheets) {
      for (const cell of sh.cells) {
        const low = cell.val.toLowerCase();
        if (!kws.some(k => low.includes(k))) continue;
        // candidate value cells: right neighbour then below neighbour
        const cands = [];
        for (let c = cell.c + 1; c <= Math.min(cell.c + 3, sh.range.e.c); c++) { const v = sh.map.get(cell.r + ':' + c); if (v != null) { cands.push({ ref: XLSX.utils.encode_cell({ r: cell.r, c }), val: v }); break; } }
        for (let r = cell.r + 1; r <= Math.min(cell.r + 3, sh.range.e.r); r++) { const v = sh.map.get(r + ':' + cell.c); if (v != null) { cands.push({ ref: XLSX.utils.encode_cell({ r, c: cell.c }), val: v }); break; } }
        for (const cand of cands) {
          if (usedRefs.has(sh.name + '!' + cand.ref)) continue;
          if (!valueShapeOk(field, cand.val)) continue;
          best = { sheet: sh.name, cellRef: cand.ref, value: cand.val };
          break;
        }
        if (best) break;
      }
      if (best) break;
    }
    if (best) { usedRefs.add(best.sheet + '!' + best.cellRef); map[field] = { ...best, confidence: 'low' }; }
  }
  return map;
}

// ---------------------------------------------------------------------------
// Candidate matching (client,name) against existing Central rows. No auto-attach.
// ---------------------------------------------------------------------------
function bigrams(s) { s = String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); const out = []; for (let i = 0; i < s.length - 1; i++) out.push(s.slice(i, i + 2)); return out; }
function dice(a, b) { const A = bigrams(a), B = bigrams(b); if (!A.length || !B.length) return 0; const setB = {}; B.forEach(x => setB[x] = (setB[x] || 0) + 1); let hit = 0; A.forEach(x => { if (setB[x] > 0) { hit++; setB[x]--; } }); return (2 * hit) / (A.length + B.length); }

function loadCentralRows() {
  // CentralSeed is a UMD module — require works server-side. central_rows overrides
  // are layered on so matches reflect what's actually live.
  let seed; try { seed = require('../../config/central-seed.js'); } catch { seed = { CAMPAIGNS: [] }; }
  const db = require('../brain/db');
  const overrides = db.getCentralOverrides();
  return (seed.CAMPAIGNS || []).map(row => {
    const id = centralRowId(row.client, row.name);
    const ov = overrides[id] || {};
    const merged = { ...row };
    for (const f in ov) merged[f] = ov[f].value;
    merged._id = id;
    return merged;
  });
}

function matchCandidates(fields) {
  const rows = loadCentralRows();
  const job = fields.jobNumber && fields.jobNumber.value;
  const client = fields.client && fields.client.value;
  const name = fields.name && fields.name.value;
  const scored = rows.map(r => {
    let score, reason;
    if (job && r.jobNumber && String(r.jobNumber).trim().toLowerCase() === String(job).trim().toLowerCase()) {
      score = 1; reason = 'exact job number';
    } else {
      score = dice((client || '') + ' ' + (name || ''), (r.client || '') + ' ' + (r.name || '')); reason = 'name similarity';
    }
    return { rowId: r._id, client: r.client, name: r.name, jobNumber: r.jobNumber || null, channel: r.channel || null, score: Math.round(score * 100) / 100, reason };
  });
  scored.sort((a, b) => b.score - a.score);
  return scored.filter(c => c.score > 0).slice(0, 3);
}

// ---------------------------------------------------------------------------
// Public entry — extract(fileRec) → {fields, mode, candidates}. Never throws for
// content reasons; a hard read failure returns an empty-but-usable result.
// ---------------------------------------------------------------------------
async function extract(fileRec) {
  const ext = (fileRec.file_type || '').toLowerCase();
  let sheets = null, docText = null, isPdf = ext === 'pdf';
  try {
    if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') sheets = readGrid(fileRec.local_path);
    else { const raw = await parser._getRawText({ file_type: ext, local_path: fileRec.local_path, filename: fileRec.filename }); docText = raw && raw.text; }
  } catch (e) {
    // fail soft — buyer still gets an empty review panel for manual entry
    return { fields: normalizeFields({}), mode: 'empty', candidates: matchCandidates(normalizeFields({})), readError: String(e.message || e).slice(0, 200) };
  }

  let rawMap = null, mode = 'heuristic';
  if (HAS_ANTHROPIC) {
    try {
      if (sheets) rawMap = await llmExtract(gridToText(sheets));
      else if (isPdf) {
        const b64 = fs.readFileSync(fileRec.local_path).toString('base64');
        rawMap = await llmExtract([
          { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: b64 } },
          { type: 'text', text: 'Extract the campaign CONFIG fields from this media plan.' }
        ]);
      } else if (docText) rawMap = await llmExtract(docText.slice(0, 120000));
      mode = 'claude';
    } catch (e) { rawMap = null; mode = 'heuristic'; }
  }
  if (!rawMap) {
    rawMap = sheets ? heuristicExtract(sheets) : {};   // docs without LLM/Llama have no readable grid → empty (manual entry)
    mode = sheets ? 'heuristic' : (docText && !/\[MOCK PARSE\]/.test(docText) ? 'heuristic-doc' : 'manual');
  }

  const fields = normalizeFields(rawMap);
  return { fields, mode, candidates: matchCandidates(fields) };
}

// Current field values for one row (central_rows override layered over the seed),
// used server-side for commit conflict detection. {} when the row does not exist.
function currentRowValues(rowId) {
  const row = loadCentralRows().find(r => r._id === rowId);
  return row || {};
}

module.exports = {
  extract, centralRowId, matchCandidates, loadCentralRows, currentRowValues,
  _normNum: normNum, _normPct: normPct, _normalizeFields: normalizeFields,
  _readGrid: readGrid, _heuristicExtract: heuristicExtract, TARGET_FIELDS
};
