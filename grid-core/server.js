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

const ROOT = __dirname;
const PORT = process.env.PORT || 8787;
const TMP = path.join(ROOT, 'tmp', 'brain-uploads');
fs.mkdirSync(TMP, { recursive: true });

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
  console.log(`[BRAIN][Commit] file=${fileId} rows=${snap.row_count} spend=$${snap.total_spend_aud} -> ${snap.target_bq_dataset}.${snap.target_bq_table} (staging only; BQ write is V3.5)`);
  send(res, 200, { snapshot: snap });
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
