/*
 * server.js — The Grid backend (Brain V3).
 * ----------------------------------------------------------------------------
 * Plain Node http (no Express — grid-core has no Express and multer would require
 * it). Serves the static app AND the Brain APIs. Uploads arrive as base64 JSON
 * (not multipart) so we need neither Express nor multer — documented deviation.
 *
 * Run:  node server.js         (PORT env, default 8787)
 * Env:  ANTHROPIC_API_KEY, LLAMA_CLOUD_API_KEY (optional — pipeline degrades
 *       gracefully to offline heuristic + rule verifier when absent).
 */
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// load .env if present (no dependency — tiny parser)
(function loadEnv() {
  try {
    const p = path.join(__dirname, '.env');
    if (fs.existsSync(p)) fs.readFileSync(p, 'utf8').split('\n').forEach(l => {
      const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/); if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    });
  } catch { /* ignore */ }
})();

const db = require('./src/brain/db');
const parser = require('./src/brain/parser');
const bqWriter = require('./src/brain/bq-writer');
const planReader = require('./src/central/plan-reader');
const centralView = require('./src/central/render-central'); // for the single mapGridRowToCentral()

const ROOT = __dirname;
const PORT = process.env.PORT || 8787;
const TMP = process.env.BRAIN_TMP_DIR || path.join(ROOT, 'tmp', 'brain-uploads');
fs.mkdirSync(TMP, { recursive: true });
const CENTRAL_TMP = process.env.CENTRAL_TMP_DIR || path.join(ROOT, 'tmp', 'central-uploads');
fs.mkdirSync(CENTRAL_TMP, { recursive: true });
const CENTRAL_OK_EXT = ['xlsx', 'xls', 'csv', 'pdf', 'docx', 'pptx'];
const CENTRAL_MAX_FILE = 15 * 1024 * 1024;
const CENTRAL_MIME = {
  xlsx: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/octet-stream'],
  xls: ['application/vnd.ms-excel', 'application/octet-stream'],
  csv: ['text/csv', 'application/vnd.ms-excel', 'text/plain', 'application/octet-stream'],
  pdf: ['application/pdf'],
  docx: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/octet-stream'],
  pptx: ['application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/octet-stream']
};

// ONE-TIME import of the sheet parse into the campaigns DB (the DB is Central's source
// of truth; this snapshot import is NOT a pipeline). Idempotent guard inside the method.
(function importCentralSheetOnce() {
  try {
    const snapPath = path.join(ROOT, 'config', 'central-import.json');
    if (!fs.existsSync(snapPath)) return;
    const snap = JSON.parse(fs.readFileSync(snapPath, 'utf8'));
    const mapped = snap.map(r => centralView._mapGridRowToCentral(r));
    const res = db.importCentralSnapshot(mapped);
    if (res.inserted) console.log(`[CENTRAL] imported ${res.inserted} campaigns from sheet snapshot; by status ${JSON.stringify(res.byStatus)}`);
    else console.log(`[CENTRAL] campaigns already imported (${res.total} rows) — skipping`);
  } catch (e) { console.error('[CENTRAL] sheet import failed:', e.message); }
})();

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.map': 'application/json' };
const MAX_FILE = 50 * 1024 * 1024;
const OK_EXT = ['pdf', 'pptx', 'docx', 'xlsx', 'xls', 'csv'];

function send(res, code, obj) { const b = JSON.stringify(obj); res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(b); }
function readBody(req, cap) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', c => { size += c.length; if (size > (cap || 80 * 1024 * 1024)) { reject(new Error('body too large')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => { try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}); } catch (e) { reject(new Error('invalid JSON body')); } });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    const p = url.pathname;

    // ---- Brain historical API ----
    if (p === '/api/brain/historical/upload' && req.method === 'POST') return upload(req, res);
    let m;
    if ((m = p.match(/^\/api\/brain\/historical\/jobs\/(.+)$/)) && req.method === 'GET') return jobStatus(res, m[1]);
    if (p === '/api/brain/historical/files' && req.method === 'GET') return listFiles(res, url.searchParams.get('client_id'));
    if ((m = p.match(/^\/api\/brain\/historical\/files\/(.+)\/rows$/)) && req.method === 'GET') return fileRows(res, m[1]);
    if ((m = p.match(/^\/api\/brain\/historical\/files\/(.+)\/commit$/)) && req.method === 'POST') return commit(req, res, m[1]);
    if ((m = p.match(/^\/api\/brain\/historical\/rows\/(.+)$/)) && req.method === 'PATCH') return patchRow(req, res, m[1]);

    // ---- Central: campaigns (source of truth) + CONFIG provenance + media-plan reader ----
    if (p === '/api/central/campaigns' && req.method === 'GET') return send(res, 200, { campaigns: db.getCampaigns() });
    if (p === '/api/central/campaigns' && req.method === 'POST') return centralCreateCampaign(req, res);
    if ((m = p.match(/^\/api\/central\/campaigns\/([^/]+)\/archive$/)) && req.method === 'POST') return centralArchive(req, res, decodeURIComponent(m[1]));
    if (p === '/api/central/rows' && req.method === 'GET') return send(res, 200, { overrides: db.getCentralOverrides() });
    if ((m = p.match(/^\/api\/central\/row\/([^/]+)\/field$/)) && req.method === 'POST') return centralEditField(req, res, decodeURIComponent(m[1]));
    // Sync is STILL STUBBED (501). Contract for the NEXT task:
    //   POST /api/central/sync will: read campaigns from the DB → overlay BQ metrics per
    //   the validated client map (live_metrics.py pattern) → UPDATE only the API-metric
    //   columns (impressions/mediaSpend/clientSpend) + metricsSource + lastSyncedAt on
    //   matching rows → NEVER touch CONFIG columns → skip archived rows and status='Ended'
    //   rows unless ?includeEnded=1 → return the refreshed rows. Campaigns with no BQ match
    //   keep their last values and metricsSource stays 'sheet-import'.
    if (p === '/api/central/sync' && req.method === 'POST') return send(res, 501, { message: 'sync backend pending — next task' });
    if (p === '/api/central/plan/upload' && req.method === 'POST') return centralPlanUpload(req, res);
    if ((m = p.match(/^\/api\/central\/plan\/([^/]+)\/commit$/)) && req.method === 'POST') return centralPlanCommit(req, res, m[1]);
    if ((m = p.match(/^\/api\/central\/plan\/([^/]+)\/discard$/)) && req.method === 'POST') return centralPlanDiscard(req, res, m[1]);

    // ---- Brain ClickUp mock endpoint (now real server-side; the browser interceptor is the file:// fallback) ----
    if (p === '/api/brain/clickup-task' && req.method === 'POST') {
      const body = await readBody(req);
      console.log('[BRAIN][ClickUp] task payload:', JSON.stringify(body).slice(0, 300));
      const taskId = 'CU-MOCK-' + crypto.randomBytes(3).toString('hex');
      return send(res, 200, { success: true, mock_task_id: taskId, updated_at: new Date().toISOString() });
    }

    // ---- static ----
    if (req.method === 'GET') return serveStatic(res, p);
    send(res, 404, { error: 'not found' });
  } catch (err) {
    console.error('[server] error', err.message);
    if (!res.headersSent) send(res, 500, { error: err.message });
  }
});

// -------- handlers --------
async function upload(req, res) {
  let body;
  try { body = await readBody(req); } catch (e) { return send(res, 400, { error: e.message }); }
  const clientId = body.client_id;
  const channelHint = body.channel_hint || null;
  const files = Array.isArray(body.files) ? body.files : [];
  if (!clientId) return send(res, 400, { error: 'client_id is required' });
  if (!files.length) return send(res, 400, { error: 'no files provided' });
  if (files.length > 10) return send(res, 400, { error: 'max 10 files per upload' });

  const out = [];
  for (const f of files) {
    const filename = (f.filename || 'upload').replace(/[^\w.\- ]/g, '_');
    const ext = filename.split('.').pop().toLowerCase();
    if (!OK_EXT.includes(ext)) return send(res, 400, { error: `unsupported format .${ext} (allowed: ${OK_EXT.join(', ')})`, filename });
    let buf;
    try { buf = Buffer.from(String(f.data_base64 || '').replace(/^data:[^,]+,/, ''), 'base64'); } catch { return send(res, 400, { error: 'invalid base64', filename }); }
    if (buf.length > MAX_FILE) return send(res, 400, { error: `file too large (${(buf.length / 1048576).toFixed(1)}MB > 50MB limit)`, filename });

    const id = crypto.randomUUID();
    const dir = path.join(TMP, id); fs.mkdirSync(dir, { recursive: true });
    const local = path.join(dir, filename);
    fs.writeFileSync(local, buf);
    db.createFile({ id, filename, file_type: ext, size_bytes: buf.length, client_id: clientId, channel_hint: channelHint, local_path: local });
    const jobId = db.createJob(id);
    console.log(`[BRAIN][Upload] ${id} ${filename} ${buf.length} bytes for client=${clientId}`);
    // fire-and-forget parse
    setImmediate(() => parser.parseFile(id).catch(e => console.error('[BRAIN][Parse] uncaught', e.message)));
    out.push({ id, job_id: jobId, filename, file_type: ext, size_bytes: buf.length, status: 'uploaded' });
  }
  send(res, 200, { files: out, llm: { anthropic: parser.HAS_ANTHROPIC, llama: parser.HAS_LLAMA } });
}

function jobStatus(res, jobId) {
  const job = db.getJob(jobId); if (!job) return send(res, 404, { error: 'job not found' });
  const file = db.getFile(job.file_id);
  const rows = db.getExtractedRowsByFile(job.file_id);
  send(res, 200, {
    id: job.id, file_id: job.file_id, filename: file ? file.filename : null,
    status: job.status, progress_pct: job.progress_pct, started_at: job.started_at, finished_at: job.finished_at,
    overall_confidence: job.overall_confidence, error_message: job.error_message,
    row_count: rows.length, flagged_row_count: rows.filter(r => r.flagged_for_review).length
  });
}

function listFiles(res, clientId) { send(res, 200, { files: db.getRecentUploads(clientId) }); }

function fileRows(res, fileId) {
  const file = db.getFile(fileId); if (!file) return send(res, 404, { error: 'file not found' });
  const job = db.getJobByFile(fileId);
  let verification = null; try { verification = job && job.verification_raw ? JSON.parse(job.verification_raw) : null; } catch { }
  send(res, 200, { file, rows: db.getExtractedRowsByFile(fileId), verification });
}

async function patchRow(req, res, rowId) {
  let body; try { body = await readBody(req); } catch (e) { return send(res, 400, { error: e.message }); }
  const updated = db.updateExtractedRow(rowId, body);
  if (!updated) return send(res, 404, { error: 'row not found' });
  send(res, 200, { row: updated });
}

async function commit(req, res, fileId) {
  let body = {}; try { body = await readBody(req); } catch { }
  const snap = db.commitSnapshot(fileId, body.committed_by || 'grid-user');
  if (!snap) return send(res, 400, { error: 'nothing to commit (file has no extracted rows)' });
  // V3.5: also load the rows into BigQuery. Never blocks the SQLite commit — a BQ
  // problem (dataset not provisioned, no write perms) is reported, not thrown.
  let bq = { written: false, reason: 'not_attempted' };
  try { bq = await bqWriter.writeSnapshot(fileId); } catch (e) { bq = { written: false, error: String(e.message || e).slice(0, 300) }; }
  console.log(`[BRAIN][Commit] file=${fileId} rows=${snap.row_count} spend=$${snap.total_spend_aud} -> ${snap.target_bq_dataset}.${snap.target_bq_table} | BQ ${bq.written ? 'WRITTEN (' + bq.rows + ' rows)' : 'not written: ' + (bq.reason || bq.error)}`);
  send(res, 200, { snapshot: snap, bq });
}

// ==================== Central handlers ====================

// Inline field edit (dropdowns / contenteditable). :id is a campaign id. Writes the
// campaigns row (source of truth) + appends provenance. Whitelisted; derived rejected.
async function centralEditField(req, res, id) {
  let body; try { body = await readBody(req); } catch (e) { return send(res, 400, { error: e.message }); }
  const field = body.field, value = body.value;
  if (!field) return send(res, 400, { error: 'field is required' });
  const r = db.updateCampaignField(id, field, value, 'edit', {});
  if (!r.ok) return send(res, r.error === 'campaign not found' ? 404 : 400, { error: r.error });
  return send(res, 200, { ok: true, id, campaign: r.campaign });
}

// Add a campaign (thin Draft row). section+client+name required; derived rejected.
async function centralCreateCampaign(req, res) {
  let body; try { body = await readBody(req); } catch (e) { return send(res, 400, { error: e.message }); }
  const r = db.createCampaign(body && typeof body === 'object' ? body : {}, 'manual');
  if (!r.ok) return send(res, 400, { error: r.error });
  console.log(`[CENTRAL] created campaign ${r.campaign.id} (${r.campaign.client} / ${r.campaign.name})`);
  return send(res, 200, { ok: true, campaign: r.campaign });
}

// Soft delete (archive). No hard-delete route exists.
function centralArchive(req, res, id) {
  const r = db.archiveCampaign(id);
  if (!r.ok) return send(res, r.error === 'campaign not found' ? 404 : 400, { error: r.error });
  return send(res, 200, { ok: true, campaign: r.campaign });
}

// Media-plan upload: base64 JSON (see note in header — server has no multer/Express).
// { filename, data_base64, mime? }. Validates ext + size (+ mime when supplied),
// runs extraction, persists a PENDING draft, returns fields + candidates. Never
// echoes raw file contents.
async function centralPlanUpload(req, res) {
  let body; try { body = await readBody(req, 40 * 1024 * 1024); } catch (e) { return send(res, 400, { error: e.message }); }
  const filename = String(body.filename || 'upload').replace(/[^\w.\- ]/g, '_');
  const ext = filename.split('.').pop().toLowerCase();
  if (!CENTRAL_OK_EXT.includes(ext)) return send(res, 400, { error: `unsupported format .${ext} — allowed: ${CENTRAL_OK_EXT.join(', ')}` });
  if (body.mime && CENTRAL_MIME[ext] && !CENTRAL_MIME[ext].includes(String(body.mime))) {
    return send(res, 400, { error: `file content type (${body.mime}) does not match .${ext}` });
  }
  let buf;
  try { buf = Buffer.from(String(body.data_base64 || '').replace(/^data:[^,]+,/, ''), 'base64'); }
  catch { return send(res, 400, { error: 'invalid base64 file data' }); }
  if (!buf.length) return send(res, 400, { error: 'empty file' });
  if (buf.length > CENTRAL_MAX_FILE) return send(res, 400, { error: `file too large (${(buf.length / 1048576).toFixed(1)}MB > 15MB limit)` });

  const id = crypto.randomUUID();
  const dir = path.join(CENTRAL_TMP, id); fs.mkdirSync(dir, { recursive: true });
  const local = path.join(dir, filename);
  fs.writeFileSync(local, buf);
  db.createPlanExtraction({ id, filename });
  console.log(`[CENTRAL][Plan] upload ${id} ${filename} ${buf.length}B`);
  try {
    const result = await planReader.extract({ id, filename, file_type: ext, local_path: local });
    db.db.prepare('UPDATE plan_extractions SET extracted_json=? WHERE id=?').run(JSON.stringify(result), id);
    return send(res, 200, { id, filename, mode: result.mode, fields: result.fields, candidates: result.candidates, readError: result.readError || null });
  } catch (e) {
    console.error('[CENTRAL][Plan] extract failed', e.message);
    // fail soft: still return an empty, usable set for manual entry
    const empty = planReader._normalizeFields({});
    db.db.prepare('UPDATE plan_extractions SET extracted_json=? WHERE id=?').run(JSON.stringify({ fields: empty, mode: 'error', candidates: [] }), id);
    return send(res, 200, { id, filename, mode: 'error', fields: empty, candidates: [], extractError: 'extraction failed — enter details manually' });
  }
}

function valuesEqual(a, b) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  if (typeof a === 'number' || typeof b === 'number') { const na = Number(a), nb = Number(b); if (Number.isFinite(na) && Number.isFinite(nb)) return na === nb; }
  return String(a).trim() === String(b).trim();
}

// Commit USER-CONFIRMED values only. Rejects derived fields, non-CONFIG fields, and
// any field that would overwrite a DIFFERENT existing value without being listed in
// acknowledgeConflicts (no silent overwrites).
async function centralPlanCommit(req, res, id) {
  let body; try { body = await readBody(req); } catch (e) { return send(res, 400, { error: e.message }); }
  const fields = body.fields || {};
  const ack = new Set(Array.isArray(body.acknowledgeConflicts) ? body.acknowledgeConflicts : []);
  const createNew = !!body.createNew;

  const draft = db.getPlanExtraction(id);
  // Manual entry (the "enter details manually" path) has no draft and is always
  // createNew — allow it; its writes are tagged source 'manual', not 'plan'.
  const manual = !draft && createNew;
  if (!draft && !manual) return send(res, 404, { error: 'extraction not found' });
  if (draft && draft.status === 'committed') return send(res, 400, { error: 'this extraction was already committed' });

  const source = draft ? 'plan' : 'manual';
  let stored = {}; if (draft) { try { stored = JSON.parse(draft.extracted_json || '{}').fields || {}; } catch { } }

  // ---- create-new → a real campaigns row (sourceOfRecord 'plan' | 'manual') ----
  if (createNew) {
    if (!fields.client || !fields.name) return send(res, 400, { error: 'a new campaign needs at least a client and a campaign name' });
    for (const f of Object.keys(fields)) if (db.CENTRAL_DERIVED_FIELDS.includes(f)) return send(res, 400, { error: `'${f}' is a DERIVED field and cannot be set` });
    let section = fields.section;
    if (!section) { const ex = db.getCampaigns().find(c => c.client === fields.client); section = ex ? ex.section : '100% Digital'; }
    const cr = db.createCampaign(Object.assign({ section }, fields), source);
    if (!cr.ok) return send(res, 400, { error: cr.error });
    if (draft) db.setPlanStatus(id, 'committed', cr.campaign.id);
    console.log(`[CENTRAL][Plan] commit ${id} -> NEW ${cr.campaign.id} (${cr.campaign.client}/${cr.campaign.name}, ${source})`);
    return send(res, 200, { ok: true, rowId: cr.campaign.id, created: true, fieldsWritten: Object.keys(fields).length, campaign: cr.campaign });
  }

  // ---- match → UPDATE the existing campaign (source of truth) + provenance ----
  const rowId = body.rowId;
  if (!rowId) return send(res, 400, { error: 'pick a matching campaign or choose "create new" before committing' });
  if (!db.getCampaign(rowId)) return send(res, 404, { error: 'matched campaign not found' });
  const current = planReader.currentRowValues(rowId);

  const names = Object.keys(fields);
  for (const f of names) {                                   // validate BEFORE writing anything
    const chk = db.centralFieldAllowed(f, 'plan');
    if (!chk.ok) return send(res, 400, { error: chk.error });
    const existing = current[f];
    if (existing != null && !valuesEqual(existing, fields[f]) && !ack.has(f)) {
      return send(res, 400, { error: `'${f}' already has a value (${existing}) that differs from the plan — resolve it (keep/replace) before committing` });
    }
  }
  let n = 0;
  for (const f of names) {
    const meta = {
      filename: draft ? draft.filename : null,
      cellRef: stored[f] ? (stored[f].cellRef || (stored[f].page != null ? 'p' + stored[f].page : null)) : null,
      source
    };
    const r = db.updateCampaignField(rowId, f, fields[f], 'plan', meta);
    if (r.ok) n++;
  }
  if (draft) db.setPlanStatus(id, 'committed', rowId);
  console.log(`[CENTRAL][Plan] commit ${id} -> ${rowId} (${n} fields, ${source})`);
  return send(res, 200, { ok: true, rowId, fieldsWritten: n, campaign: db.getCampaign(rowId) });
}

function centralPlanDiscard(req, res, id) {
  const draft = db.getPlanExtraction(id);
  if (!draft) return send(res, 404, { error: 'extraction not found' });
  db.setPlanStatus(id, 'discarded');
  return send(res, 200, { ok: true });
}

function serveStatic(res, p) {
  if (p === '/' || p === '') p = '/the-grid.html';
  const file = path.resolve(path.join(ROOT, decodeURIComponent(p)));
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end('forbidden'); }
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404, { 'Content-Type': 'text/plain' }); return res.end('not found: ' + p); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(buf);
  });
}

server.listen(PORT, () => {
  console.log(`The Grid + Brain V3 backend on http://localhost:${PORT}/the-grid.html`);
  console.log(`  LLM mode: anthropic=${parser.HAS_ANTHROPIC ? 'LIVE' : 'offline-heuristic'} llama=${parser.HAS_LLAMA ? 'LIVE' : 'offline-mock'}`);
});
