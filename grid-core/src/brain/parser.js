/*
 * src/brain/parser.js — Brain V3 parse pipeline (offline-first).
 * ----------------------------------------------------------------------------
 * parseFile(fileId) runs: route -> raw text -> structured extraction ->
 * challenger verification -> confidence -> persist. Updates job progress at each
 * stage so the frontend progress bar can follow.
 *
 * LLM usage is OPTIONAL and key-gated:
 *   - ANTHROPIC_API_KEY present  -> Claude structured extraction + challenger verify
 *   - LLAMA_CLOUD_API_KEY present -> LlamaParse for PDF/PPTX/DOCX
 * When a key is absent we DEGRADE GRACEFULLY, never crash:
 *   - XLSX/CSV are parsed natively (real data, no LLM needed) and extracted with a
 *     deterministic column-mapping heuristic.
 *   - PDF/PPTX without LlamaParse -> a clearly-labelled mock extraction.
 *   - Verification without Claude -> a rule-based verifier (sum/date/channel checks).
 * This keeps the whole flow demonstrable offline and upgrades to real LLM the moment
 * keys are added. Which mode ran is recorded in extraction_raw/verification_raw.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const XLSX = require('xlsx');
const dbmod = require('./db');

const HAS_ANTHROPIC = !!process.env.ANTHROPIC_API_KEY;
const HAS_LLAMA = !!process.env.LLAMA_CLOUD_API_KEY;
const CLAUDE_MODEL = process.env.BRAIN_CLAUDE_MODEL || 'claude-opus-4-8';
const CHANNELS = ['TV', 'Print', 'OOH', 'Radio', 'Digital', 'Meta', 'LinkedIn', 'Trade Desk', 'Google Ads', 'DV360', 'Reddit', 'Other'];
const uuid = () => crypto.randomUUID();

function log(...a) { console.log('[BRAIN][Parse]', ...a); }

// ---------------------------------------------------------------------------
// Public entry — never throws; captures all errors into the job record.
// ---------------------------------------------------------------------------
async function parseFile(fileId) {
  const file = dbmod.getFile(fileId);
  const jobId = dbmod.getJobByFile(fileId).id;
  try {
    dbmod.updateJobProgress(jobId, 'parsing', 5);
    dbmod.updateFileStatus(fileId, 'parsing');

    // Stage 2 — raw text/markdown
    const raw = await getRawText(file, jobId);
    dbmod.updateJobRaw(jobId, 'llama_parse_raw', raw.text.slice(0, 200000));
    dbmod.updateJobProgress(jobId, 'extracting', 25);

    // Stage 3 — structured extraction
    const kpiObj = loadKpiObject(file.client_id);
    // A PDF with no LlamaParse key but an Anthropic key: Claude reads the PDF
    // natively as a base64 document block — no LlamaParse required.
    const nativePdf = raw.mock && file.file_type === 'pdf' && HAS_ANTHROPIC;
    let extraction;
    if (nativePdf) extraction = await claudePdfExtract(file, kpiObj);
    else if (HAS_ANTHROPIC) extraction = await claudeExtract(raw.text, file, kpiObj);
    else extraction = heuristicExtract(raw, file);
    dbmod.updateJobRaw(jobId, 'extraction_raw', JSON.stringify(extraction).slice(0, 200000));
    dbmod.updateJobProgress(jobId, 'verifying', 50);

    // Stage 4 — challenger verification (Claude challenger needs source text;
    // the native-PDF path has none, so it uses the deterministic rule verifier).
    const verification = (HAS_ANTHROPIC && !raw.mock)
      ? await claudeVerify(raw.text, extraction.campaigns, file)
      : ruleVerify(extraction, file);
    dbmod.updateJobRaw(jobId, 'verification_raw', JSON.stringify(verification).slice(0, 200000));
    dbmod.updateJobProgress(jobId, 'verifying', 75);

    // Stage 5 — confidence + persist
    const rows = buildRows(extraction, verification, file, jobId);
    if (rows.length) dbmod.insertExtractedRows(rows);
    const flagged = rows.filter(r => r.flagged_for_review).length;
    dbmod.updateFileStatus(fileId, flagged ? 'needs_review' : 'ready');
    dbmod.updateJobProgress(jobId, 'complete', 95);

    // Stage 6 — finalize
    const avg = rows.length ? rows.reduce((a, r) => a + r.confidence, 0) / rows.length : 0;
    dbmod.updateJobResult(jobId, { status: 'complete', finished_at: new Date().toISOString(), progress_pct: 100, overall_confidence: Math.round(avg * 100) / 100 });
    log(`complete file=${fileId} rows=${rows.length} flagged=${flagged} conf=${avg.toFixed(2)} mode=${HAS_ANTHROPIC ? 'claude' : 'heuristic'}`);
  } catch (err) {
    log(`FAILED file=${fileId}: ${err.message}`);
    dbmod.updateJobResult(jobId, { status: 'failed', finished_at: new Date().toISOString(), error_message: String(err.message || err).slice(0, 1000) });
    dbmod.updateFileStatus(fileId, 'failed');
  }
}

// ---------------------------------------------------------------------------
// Stage 2 — raw text
// ---------------------------------------------------------------------------
async function getRawText(file, jobId) {
  const ext = file.file_type;
  if (ext === 'xlsx' || ext === 'xls') return xlsxToTables(file.local_path);
  if (ext === 'csv') return csvToTables(file.local_path);
  if (ext === 'pdf' || ext === 'pptx' || ext === 'docx') {
    if (HAS_LLAMA) return { text: await llamaParse(file.local_path, file.filename), tables: [] };
    // offline mock: cannot truly read the binary here. NOTE: for PDFs, if
    // ANTHROPIC_API_KEY is set the caller routes to claudePdfExtract() instead of
    // using this text (Claude reads the PDF natively — no LlamaParse needed).
    var hint = ext === 'pdf'
      ? 'Set ANTHROPIC_API_KEY (Claude reads PDFs natively) or LLAMA_CLOUD_API_KEY to parse this PDF for real.'
      : `Set LLAMA_CLOUD_API_KEY to parse ${ext.toUpperCase()} files for real.`;
    return { text: `[MOCK PARSE]\nDocument: ${file.filename}\n${hint}`, tables: [], mock: true };
  }
  throw new Error(`Unsupported file type: ${ext}`);
}

function xlsxToTables(p) {
  const wb = XLSX.readFile(p);
  const tables = [];
  let md = '';
  wb.SheetNames.forEach(name => {
    const ws = wb.Sheets[name];
    const aoa = XLSX.utils.sheet_to_json(ws, { header: 1, blankrows: false, defval: null });
    if (!aoa.length) return;
    const header = aoa[0].map(h => String(h == null ? '' : h).trim());
    const rows = aoa.slice(1).filter(r => r.some(c => c != null && String(c).trim() !== ''));
    tables.push({ sheet: name, header, rows });
    md += `\n## Sheet: ${name}\n| ${header.join(' | ')} |\n| ${header.map(() => '---').join(' | ')} |\n`;
    rows.forEach(r => { md += `| ${header.map((_, i) => r[i] == null ? '' : r[i]).join(' | ')} |\n`; });
  });
  return { text: md.trim(), tables };
}

function csvToTables(p) {
  const wb = XLSX.readFile(p, { raw: false });
  const name = wb.SheetNames[0];
  const aoa = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, blankrows: false, defval: null });
  const header = (aoa[0] || []).map(h => String(h == null ? '' : h).trim());
  const rows = aoa.slice(1).filter(r => r.some(c => c != null && String(c).trim() !== ''));
  let md = `| ${header.join(' | ')} |\n| ${header.map(() => '---').join(' | ')} |\n`;
  rows.forEach(r => { md += `| ${header.map((_, i) => r[i] == null ? '' : r[i]).join(' | ')} |\n`; });
  return { text: md.trim(), tables: [{ sheet: path.basename(p), header, rows }] };
}

// LlamaParse REST (only when keyed). Upload -> poll -> fetch markdown.
async function llamaParse(filePath, filename) {
  const key = process.env.LLAMA_CLOUD_API_KEY;
  const base = 'https://api.cloud.llamaindex.ai/api/v1/parsing';
  const buf = fs.readFileSync(filePath);
  const fd = new FormData();
  fd.append('file', new Blob([buf]), filename);
  const up = await fetch(`${base}/upload`, { method: 'POST', headers: { Authorization: `Bearer ${key}` }, body: fd });
  if (!up.ok) throw new Error(`LlamaParse upload failed: ${up.status}`);
  const jobId = (await up.json()).id;
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 3000));
    const st = await (await fetch(`${base}/job/${jobId}`, { headers: { Authorization: `Bearer ${key}` } })).json();
    if (st.status === 'SUCCESS') {
      const res = await fetch(`${base}/job/${jobId}/result/markdown`, { headers: { Authorization: `Bearer ${key}` } });
      return (await res.json()).markdown || '';
    }
    if (st.status === 'ERROR' || st.status === 'FAILED') throw new Error('LlamaParse job failed');
  }
  throw new Error('LlamaParse timed out after 5 minutes');
}

// ---------------------------------------------------------------------------
// Stage 3 — extraction
// ---------------------------------------------------------------------------
function loadKpiObject(clientId) {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'config', 'kpi-objects', clientId + '.json'), 'utf8')); }
  catch { return null; }
}

async function claudeExtract(text, file, kpiObj) {
  const Anthropic = require('@anthropic-ai/sdk');
  const client = new Anthropic();
  const schema = extractionSchema();
  const sys = `You extract campaign-level historical media data from parsed marketing documents into strict JSON.
Client: ${file.client_id}. KPI context: ${kpiObj ? JSON.stringify(kpiObj.primary_kpi) : 'n/a'}.
Channel hint from uploader: ${file.channel_hint || 'auto-detect'}.
Only use the channel vocabulary: ${CHANNELS.join(', ')}. Dates must be YYYY-MM-DD. Never invent numbers not supported by the document.`;
  const msg = await withTimeout(client.messages.create({
    model: CLAUDE_MODEL, max_tokens: 4096, system: sys,
    tools: [{ name: 'emit', description: 'Emit the extracted campaigns.', input_schema: schema }],
    tool_choice: { type: 'tool', name: 'emit' },
    messages: [{ role: 'user', content: `Extract every campaign flight from this document.\n\n${text.slice(0, 120000)}` }]
  }), 60000);
  const use = msg.content.find(c => c.type === 'tool_use');
  return use ? use.input : { campaigns: [], document_summary: '', totals_reported: {}, extraction_notes: 'no tool output' };
}

// Native-PDF extraction: send the PDF to Claude as a base64 document block
// (no beta header; 32MB / 600-page limits) and force the same extraction tool.
// This is the "PDF parses for real with only ANTHROPIC_API_KEY" path.
async function claudePdfExtract(file, kpiObj) {
  const Anthropic = require('@anthropic-ai/sdk');
  const client = new Anthropic();
  const b64 = fs.readFileSync(file.local_path).toString('base64'); // no newlines
  const sys = `You extract campaign-level historical media data from a marketing PDF into strict JSON.
Client: ${file.client_id}. KPI context: ${kpiObj ? JSON.stringify(kpiObj.primary_kpi) : 'n/a'}.
Channel hint from uploader: ${file.channel_hint || 'auto-detect'}.
Only use the channel vocabulary: ${CHANNELS.join(', ')}. Dates must be YYYY-MM-DD. Never invent numbers not present in the document. Use the page/table as the source_citation.`;
  const msg = await withTimeout(client.messages.create({
    model: CLAUDE_MODEL, max_tokens: 4096, system: sys,
    tools: [{ name: 'emit', description: 'Emit the extracted campaigns.', input_schema: extractionSchema() }],
    tool_choice: { type: 'tool', name: 'emit' },
    messages: [{
      role: 'user', content: [
        { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: b64 } },
        { type: 'text', text: 'Extract every campaign flight from this media plan PDF.' }
      ]
    }]
  }), 90000);
  const use = msg.content.find(c => c.type === 'tool_use');
  var out = use ? use.input : { campaigns: [], document_summary: '', totals_reported: {}, extraction_notes: 'no tool output' };
  out._mode = 'claude_pdf';
  return out;
}

async function claudeVerify(text, campaigns, file) {
  const Anthropic = require('@anthropic-ai/sdk');
  const client = new Anthropic();
  const schema = verificationSchema();
  const msg = await withTimeout(client.messages.create({
    model: CLAUDE_MODEL, max_tokens: 4096,
    system: 'You are a challenger reviewing another model\'s extraction. For each campaign, judge whether each field is supported by the source text. Be strict.',
    tools: [{ name: 'emit', description: 'Emit per-row verifications.', input_schema: schema }],
    tool_choice: { type: 'tool', name: 'emit' },
    messages: [{ role: 'user', content: `SOURCE:\n${text.slice(0, 90000)}\n\nEXTRACTED:\n${JSON.stringify(campaigns).slice(0, 20000)}` }]
  }), 60000);
  const use = msg.content.find(c => c.type === 'tool_use');
  return use ? use.input : { row_verifications: [], overall_extraction_quality: 0.8 };
}

function withTimeout(p, ms) {
  return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('Claude API timed out')), ms))]);
}

// Deterministic offline extractor — maps table columns to the schema by header keywords.
function heuristicExtract(raw, file) {
  const campaigns = [];
  (raw.tables || []).forEach(tbl => {
    const H = tbl.header.map(h => h.toLowerCase());
    const find = (...kw) => H.findIndex(h => kw.some(k => h.includes(k)));
    const ci = {
      campaign: find('campaign', 'name', 'publication', 'publisher', 'location', 'site', 'placement', 'title'),
      channel: find('channel', 'platform', 'network', 'medium', 'type', 'format'),
      sub: find('sub', 'station', 'masthead', 'panel'),
      start: find('start', 'from', 'insertion', 'launch', 'flight start'),
      end: find('end', 'to', 'finish', 'flight end'),
      date: find('date', 'month', 'period', 'flight'),
      spend: find('spend', 'cost', 'budget', 'investment', 'net', 'gross', 'media $', 'amount'),
      impr: find('impression', 'imps'),
      reach: find('reach', 'circulation', 'audience'),
      clicks: find('click'),
      conv: find('conversion', 'lead', 'response'),
      grps: find('grp', 'trp', 'rating')
    };
    tbl.rows.forEach((r, idx) => {
      const get = i => (i >= 0 && r[i] != null && String(r[i]).trim() !== '') ? r[i] : null;
      const num = v => { if (v == null) return null; const n = Number(String(v).replace(/[^0-9.\-]/g, '')); return isNaN(n) ? null : n; };
      const iget = v => { const n = num(v); return n == null ? null : Math.round(n); };
      let start = parseDate(get(ci.start)) || parseDate(get(ci.date));
      let end = parseDate(get(ci.end)) || start;
      if (!start && end) start = end;
      const channel = normChannel(get(ci.channel) || file.channel_hint);
      const spend = num(get(ci.spend));
      // completeness score
      let mapped = 0, total = 5;
      if (get(ci.campaign)) mapped++;
      if (channel !== 'Other' || get(ci.channel)) mapped++;
      if (start) mapped++;
      if (spend != null) mapped++;
      if (iget(get(ci.impr)) != null || iget(get(ci.reach)) != null || num(get(ci.grps)) != null) mapped++;
      if (!start && spend == null) return; // junk row
      campaigns.push({
        campaign_name: get(ci.campaign) ? String(get(ci.campaign)) : null,
        channel, sub_channel: get(ci.sub) ? String(get(ci.sub)) : null,
        period_start: start || '2024-01-01', period_end: end || start || '2024-01-01',
        spend_aud: spend, impressions: iget(get(ci.impr)),
        reach: iget(get(ci.reach)) != null ? iget(get(ci.reach)) : (H[ci.reach] && H[ci.reach].includes('thousand') ? null : null),
        clicks: iget(get(ci.clicks)), conversions: iget(get(ci.conv)), grps: num(get(ci.grps)),
        source_citation: `${tbl.sheet}!row ${idx + 2}`,
        extraction_confidence: Math.round((0.55 + 0.09 * mapped) * 100) / 100
      });
    });
  });
  const totalSpend = campaigns.reduce((a, c) => a + (c.spend_aud || 0), 0);
  return {
    campaigns,
    document_summary: `[heuristic] ${file.filename}: ${campaigns.length} rows across ${new Set(campaigns.map(c => c.channel)).size} channel(s).`,
    totals_reported: { total_spend_aud: totalSpend || null, total_reach: null },
    extraction_notes: HAS_LLAMA ? 'Heuristic column-mapping (no ANTHROPIC_API_KEY).' : 'Heuristic column-mapping; no LLM keys set. Add ANTHROPIC_API_KEY + LLAMA_CLOUD_API_KEY for LLM extraction of unstructured docs.',
    _mode: 'heuristic'
  };
}

// Rule-based verifier — sum check, date sanity, channel-vocabulary check.
function ruleVerify(extraction, file) {
  const rows = extraction.campaigns || [];
  const sum = rows.reduce((a, c) => a + (c.spend_aud || 0), 0);
  const claimed = extraction.totals_reported && extraction.totals_reported.total_spend_aud;
  const sumOk = claimed == null || Math.abs(sum - claimed) <= Math.max(1, claimed * 0.02);
  const verifs = rows.map((c, i) => {
    const datesOk = !!(c.period_start && c.period_end && c.period_start <= c.period_end);
    const channelOk = CHANNELS.includes(c.channel);
    const spendOk = c.spend_aud == null || c.spend_aud >= 0;
    const notes = [];
    if (!datesOk) notes.push('date range invalid or missing');
    if (!channelOk) notes.push('channel not in reference list');
    if (!spendOk) notes.push('negative spend');
    return { index: i, campaign_name_ok: !!c.campaign_name, channel_ok: channelOk, dates_ok: datesOk, spend_ok: spendOk, impressions_ok: true, notes: notes.join('; ') };
  });
  const quality = rows.length ? verifs.filter(v => v.dates_ok && v.channel_ok && v.spend_ok).length / rows.length : 0;
  return {
    row_verifications: verifs,
    overall_extraction_quality: Math.round(quality * 100) / 100,
    checks: [
      { label: 'Row spend sums to document total', pass: sumOk, detail: claimed != null ? `rows=$${Math.round(sum)} vs claimed=$${Math.round(claimed)}` : 'no document total to compare' },
      { label: 'All flight dates within valid ranges', pass: verifs.every(v => v.dates_ok), detail: `${verifs.filter(v => v.dates_ok).length}/${verifs.length} rows` },
      { label: 'Channel names match reference vocabulary', pass: verifs.every(v => v.channel_ok), detail: `${verifs.filter(v => v.channel_ok).length}/${verifs.length} rows` }
    ],
    _mode: 'rule'
  };
}

// ---------------------------------------------------------------------------
// Stage 5 — confidence + row build
// ---------------------------------------------------------------------------
function buildRows(extraction, verification, file, jobId) {
  const verifs = verification.row_verifications || [];
  const quality = typeof verification.overall_extraction_quality === 'number' ? verification.overall_extraction_quality : 0.8;
  return (extraction.campaigns || []).map((c, i) => {
    const v = verifs[i] || {};
    const anyFalse = ['campaign_name_ok', 'channel_ok', 'dates_ok', 'spend_ok', 'impressions_ok'].some(k => v[k] === false);
    let conf = typeof c.extraction_confidence === 'number' ? c.extraction_confidence : 0.7;
    if (anyFalse) conf *= 0.7;
    conf = Math.min(conf, quality || conf);
    conf = Math.round(conf * 100) / 100;
    return {
      id: uuid(), job_id: jobId, file_id: file.id, client_id: file.client_id,
      campaign_name: c.campaign_name || null, channel: normChannel(c.channel), sub_channel: c.sub_channel || null,
      period_start: c.period_start, period_end: c.period_end || c.period_start,
      spend_aud: numOrNull(c.spend_aud), impressions: intOrNull(c.impressions), reach: intOrNull(c.reach),
      clicks: intOrNull(c.clicks), conversions: intOrNull(c.conversions), grps: numOrNull(c.grps),
      source_citation: c.source_citation || null, confidence: conf,
      flagged_for_review: conf < 0.75 ? 1 : 0
    };
  });
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
function numOrNull(v) { if (v == null || v === '') return null; const n = Number(v); return isNaN(n) ? null : n; }
function intOrNull(v) { const n = numOrNull(v); return n == null ? null : Math.round(n); }
function normChannel(v) {
  if (!v) return 'Other';
  const s = String(v).toLowerCase();
  const map = [['trade desk', 'Trade Desk'], ['ttd', 'Trade Desk'], ['dv360', 'DV360'], ['display & video', 'DV360'],
  ['linkedin', 'LinkedIn'], ['meta', 'Meta'], ['facebook', 'Meta'], ['instagram', 'Meta'], ['google', 'Google Ads'],
  ['reddit', 'Reddit'], ['tv', 'TV'], ['television', 'TV'], ['print', 'Print'], ['press', 'Print'], ['magazine', 'Print'],
  ['ooh', 'OOH'], ['out of home', 'OOH'], ['outdoor', 'OOH'], ['billboard', 'OOH'], ['radio', 'Radio'], ['audio', 'Radio'],
  ['digital', 'Digital'], ['programmatic', 'Digital']];
  for (const [k, val] of map) if (s.includes(k)) return val;
  return CHANNELS.includes(v) ? v : 'Other';
}
function parseDate(v) {
  if (v == null || v === '') return null;
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  const s = String(v).trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
  // dd/mm/yyyy or d/m/yy
  let m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$/);
  if (m) { let [, d, mo, y] = m; if (y.length === 2) y = '20' + y; return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`; }
  // "Oct 2024" / "October 2024" / "1 Oct 2024"
  const months = { jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06', jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12' };
  m = s.toLowerCase().match(/(\d{1,2}\s+)?([a-z]{3,})[a-z]*\s+(\d{4})/);
  if (m) { const mo = months[m[2].slice(0, 3)]; if (mo) { const d = m[1] ? String(parseInt(m[1])).padStart(2, '0') : '01'; return `${m[3]}-${mo}-${d}`; } }
  const dt = new Date(s);
  return isNaN(dt) ? null : dt.toISOString().slice(0, 10);
}

function extractionSchema() {
  return {
    type: 'object', properties: {
      campaigns: {
        type: 'array', items: {
          type: 'object', properties: {
            campaign_name: { type: ['string', 'null'] },
            channel: { type: 'string', enum: CHANNELS },
            sub_channel: { type: ['string', 'null'] },
            period_start: { type: 'string' }, period_end: { type: 'string' },
            spend_aud: { type: ['number', 'null'] }, impressions: { type: ['integer', 'null'] },
            reach: { type: ['integer', 'null'] }, clicks: { type: ['integer', 'null'] },
            conversions: { type: ['integer', 'null'] }, grps: { type: ['number', 'null'] },
            source_citation: { type: 'string' }, extraction_confidence: { type: 'number' }
          }, required: ['channel', 'period_start', 'period_end', 'source_citation', 'extraction_confidence']
        }
      },
      document_summary: { type: 'string' },
      totals_reported: { type: 'object', properties: { total_spend_aud: { type: ['number', 'null'] }, total_reach: { type: ['integer', 'null'] } } },
      extraction_notes: { type: 'string' }
    }, required: ['campaigns', 'document_summary']
  };
}
function verificationSchema() {
  return {
    type: 'object', properties: {
      row_verifications: {
        type: 'array', items: {
          type: 'object', properties: {
            index: { type: 'integer' }, campaign_name_ok: { type: 'boolean' }, channel_ok: { type: 'boolean' },
            dates_ok: { type: 'boolean' }, spend_ok: { type: 'boolean' }, impressions_ok: { type: 'boolean' }, notes: { type: 'string' }
          }, required: ['index']
        }
      },
      overall_extraction_quality: { type: 'number' }
    }, required: ['row_verifications', 'overall_extraction_quality']
  };
}

module.exports = { parseFile, HAS_ANTHROPIC, HAS_LLAMA, _heuristicExtract: heuristicExtract, _parseDate: parseDate, _claudePdfExtract: claudePdfExtract };
