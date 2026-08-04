// Greenlight HTTP handlers - the plan-side campaign checker, shared by TWO
// servers so there is exactly one implementation:
//   - grid-core/server.js mounts it at /api/greenlight/* (feature-flagged by
//     GREENLIGHT_ENABLED; auth = the Grid's model: platform proxy + Cloud Run
//     IAM, zero auth code here)
//   - grid-core/expected/server.js keeps the standalone dev harness on :8791
//     (test_regression.js targets its legacy /api/expected/* paths)
//
// Data model (store.js): an ANALYSIS is a named workspace per campaign - its
// own isolated file dump that persists across runs, plus a run history. That
// is what keeps different campaigns' files from mixing. Names are optional;
// an auto-named analysis adopts the extracted "<client> <job>" after its
// first successful run. Storage is local FS with an optional GCS mirror
// (GREENLIGHT_BUCKET -> gs://bidbrain-campaign-dumps) so the library survives
// Cloud Run cold starts.
'use strict';

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const crypto = require('crypto');
const store = require('./store');

const ROOT = __dirname;
const OUT = process.env.GREENLIGHT_OUT_DIR || path.join(ROOT, 'out');
const FILES_DIR = process.env.EXPECTED_FILES_DIR || path.join(ROOT, '..', 'files');
const MAX_UPLOAD_BYTES = 15 * 1024 * 1024; // per file; the platform proxy caps forwarded POSTs ~16MB

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};

const runs = new Map(); // in-flight + recent run state, id -> run

function send(res, code, obj) {
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(obj));
}

function readBody(req, cap) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > (cap || 64 * 1024 * 1024)) { reject(new Error('body too large')); req.destroy(); } else chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}); }
      catch { reject(new Error('invalid JSON body')); }
    });
    req.on('error', reject);
  });
}

// ---------------------------------------------------------------- run engine
function startRun(analysisId, inputDir, filesHash) {
  const id = crypto.randomBytes(6).toString('hex');
  const run = {
    id,
    analysis_id: analysisId,
    started_at: new Date().toISOString(),
    status: 'running',
    stages: [
      { key: 'extract', label: 'Extracting files', state: 'active' },
      { key: 'plan', label: 'Reading plan', state: 'pending' },
      { key: 'gaps', label: 'Checking gaps', state: 'pending' },
      { key: 'outputs', label: 'Building outputs', state: 'pending' },
    ],
    error: null,
    results: null,
  };
  runs.set(id, run);

  const stage = (key, state) => {
    const s = run.stages.find((x) => x.key === key);
    if (s) s.state = state;
  };
  const fail = (msg) => {
    const active = run.stages.find((s) => s.state === 'active');
    if (active) active.state = 'error';
    run.status = 'error';
    run.error = msg;
  };

  // TODO(background-job): extract + build run synchronously inside this
  // request lifecycle (~320s for the model call). Cloud Run's default request
  // timeout is 300s - the service needs --timeout 600 while this stays
  // synchronous; the real fix is a background job once Greenlight sees
  // real traffic. Deliberately not built yet.
  const env = { ...process.env, GREENLIGHT_OUT_DIR: OUT };
  const ex = spawn(process.execPath, [path.join(ROOT, 'extract.js'), '--files', inputDir], { cwd: ROOT, env });
  let exErr = '';
  let exOut = '';
  ex.stderr.on('data', (d) => { exErr += d; });
  ex.stdout.on('data', (d) => {
    exOut += d;
    const s = String(d);
    if (s.includes('[stage] preprocess-done')) { stage('extract', 'done'); stage('plan', 'active'); }
    if (s.includes('[stage] model-done')) { stage('plan', 'done'); stage('gaps', 'active'); }
    if (s.includes('[stage] validate-done')) { stage('gaps', 'done'); }
  });
  ex.on('error', (e) => fail(String(e.message || e)));
  ex.on('close', (code) => {
    if (run.status === 'error') return;
    if (code === 2) return fail('No ANTHROPIC_API_KEY available. Locally: grid-core/.env. Deployed: the anthropic-api-key secret binding (see expected/README.md).');
    if (code !== 0) return fail(`extract.js exited ${code}\n${(exErr || exOut).slice(-1500)}`);

    stage('outputs', 'active');
    const b = spawn(process.execPath, [path.join(ROOT, 'build_expected.js')], { cwd: ROOT, env });
    let bErr = '';
    let bOut = '';
    b.stderr.on('data', (d) => { bErr += d; });
    b.stdout.on('data', (d) => { bOut += d; });
    b.on('error', (e) => fail(String(e.message || e)));
    b.on('close', async (bcode) => {
      if (run.status === 'error') return;
      if (bcode !== 0) return fail(`build_expected.js exited ${bcode}\n${(bErr || bOut).slice(-1500)}`);
      try {
        const plan = JSON.parse(fs.readFileSync(path.join(OUT, 'plan.json'), 'utf8'));
        const kpi = JSON.parse(fs.readFileSync(path.join(OUT, 'daily_kpi.json'), 'utf8'));
        const findingsDoc = JSON.parse(fs.readFileSync(path.join(OUT, 'findings.json'), 'utf8'));
        const messages = JSON.parse(fs.readFileSync(path.join(OUT, 'messages.json'), 'utf8'));
        const v = (node) => (node && node.value != null ? node.value : null);
        const results = {
          run: {
            id,
            analysis_id: analysisId,
            started_at: run.started_at,
            finished_at: new Date().toISOString(),
            model: plan.extractor ? plan.extractor.model : 'unknown',
          },
          meta: {
            client: kpi.client,
            job: kpi.job,
            campaign: v(plan.campaign_name) || '',
            currency: kpi.currency,
            total: kpi.campaigns.reduce((a, c) => a + (c.total_budget || 0), 0),
            flight: kpi.campaigns.length ? `${kpi.campaigns[0].start} to ${kpi.campaigns[0].end}` : 'unresolved',
            exceptions: kpi.exceptions || [],
            guard: plan.identity_guard || null,
          },
          findings: findingsDoc.findings,
          origins: findingsDoc.origins,
          messages,
        };
        await store.archiveRun(analysisId, id, OUT, results);
        const label = `${kpi.client || 'Unknown client'} ${kpi.job || ''}`.trim();
        store.recordRun(analysisId, id, filesHash, label);
        stage('outputs', 'done');
        run.status = 'done';
        run.results = results;
      } catch (e) {
        fail(String(e.message || e));
      }
    });
  });
  return id;
}

function anyRunning() {
  return [...runs.values()].some((r) => r.status === 'running');
}

// ---------------------------------------------------------------- dispatcher
/**
 * Route dispatcher. prefix e.g. '/api/greenlight' or '/api/expected'.
 * Returns true when the request was handled.
 */
async function handle(req, res, url, prefix) {
  const p = url.pathname;
  if (!p.startsWith(prefix + '/')) return false;
  const sub = p.slice(prefix.length);
  let m;

  // ---- analyses (the named per-campaign workspaces) ----
  if (sub === '/analyses' && req.method === 'GET') { send(res, 200, { analyses: store.listAnalyses() }); return true; }

  if (sub === '/analyses' && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    send(res, 200, { analysis: store.createAnalysis(body.name) });
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)$/.exec(sub)) && req.method === 'GET') {
    const d = store.analysisDetail(m[1]);
    if (!d) send(res, 404, { error: 'unknown analysis' });
    else send(res, 200, d);
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)\/rename$/.exec(sub)) && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    const a = store.renameAnalysis(m[1], body.name);
    if (!a) send(res, 404, { error: 'unknown analysis' });
    else send(res, 200, { analysis: a });
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)\/archive$/.exec(sub)) && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    const a = store.setArchived(m[1], body.archived !== false);
    if (!a) send(res, 404, { error: 'unknown analysis' });
    else send(res, 200, { analysis: a });
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)\/delete$/.exec(sub)) && req.method === 'POST') {
    send(res, store.deleteAnalysis(m[1]) ? 200 : 404, { deleted: m[1] });
    return true;
  }

  // ---- per-analysis files ----
  if ((m = /^\/analyses\/([a-f0-9]+)\/files$/.exec(sub)) && req.method === 'POST') {
    try {
      const body = await readBody(req);
      send(res, 200, store.stageFile(m[1], body.name, body.data_b64, MAX_UPLOAD_BYTES));
    } catch (e) { send(res, 400, { error: String(e.message || e) }); }
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)\/files\/remove$/.exec(sub)) && req.method === 'POST') {
    try {
      const body = await readBody(req);
      send(res, 200, store.removeFile(m[1], body.name));
    } catch (e) { send(res, 400, { error: String(e.message || e) }); }
    return true;
  }

  // ---- run within an analysis (with the unchanged-files guard) ----
  if ((m = /^\/analyses\/([a-f0-9]+)\/analyze$/.exec(sub)) && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    const a = store.analysisDetail(m[1]);
    if (!a) { send(res, 404, { error: 'unknown analysis' }); return true; }
    if (anyRunning()) { send(res, 409, { error: 'a run is already in progress' }); return true; }
    if (!a.files.length) { send(res, 400, { error: 'this analysis has no files yet - upload the campaign dump first' }); return true; }
    const hash = store.filesHash(m[1]);
    const last = a.analysis.last_run;
    if (!body.force && last && last.files_hash && last.files_hash === hash) {
      send(res, 200, { unchanged: true, last_run: last, message: 'Files are identical to the last run. Run anyway?' });
      return true;
    }
    send(res, 200, { runId: startRun(m[1], store.aFilesDir(m[1]), hash) });
    return true;
  }

  // ---- run state + per-run artifacts ----
  if ((m = /^\/runs\/([a-f0-9]+)$/.exec(sub)) && req.method === 'GET') {
    const run = runs.get(m[1]);
    if (run) { send(res, 200, run); return true; }
    // not in memory (other instance / restart): serve archived results if they exist
    const aid = store.findRun(m[1]);
    if (!aid) { send(res, 404, { error: 'unknown run id' }); return true; }
    const results = await store.runResults(aid, m[1]);
    send(res, 200, { id: m[1], analysis_id: aid, status: results ? 'done' : 'error', stages: [], error: results ? null : 'run archived without results', results });
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)\/runs\/([a-f0-9]+)\/results$/.exec(sub)) && req.method === 'GET') {
    const results = await store.runResults(m[1], m[2]);
    if (!results) send(res, 404, { error: 'no results for that run' });
    else send(res, 200, results);
    return true;
  }

  if ((m = /^\/analyses\/([a-f0-9]+)\/runs\/([a-f0-9]+)\/out\/([^/\\]+)$/.exec(sub)) && req.method === 'GET') {
    const file = await store.runArtifact(m[1], m[2], m[3]);
    serveFile(res, file);
    return true;
  }

  // ---- legacy paths (standalone index.html + test_regression.js) ----
  if (sub === '/files' && req.method === 'GET') {
    const files = fs.existsSync(FILES_DIR) ? store.walk(FILES_DIR, FILES_DIR, []) : [];
    send(res, 200, { source: files.length ? 'prestaged' : 'empty', files });
    return true;
  }

  if (sub === '/analyze' && req.method === 'POST') {
    // Legacy one-shot: auto-creates an analysis and runs the local prestage
    // dir (grid-core/files) directly - the regression's cold-run path. The
    // dump is not copied into the analysis (160MB per run); files_hash stays
    // null so the unchanged-guard never blocks it.
    await readBody(req).catch(() => ({}));
    if (anyRunning()) { send(res, 409, { error: 'a run is already in progress' }); return true; }
    if (!fs.existsSync(FILES_DIR)) { send(res, 400, { error: `no prestage directory (${FILES_DIR}) - use the analyses API` }); return true; }
    const a = store.createAnalysis(null);
    send(res, 200, { runId: startRun(a.id, FILES_DIR, null), analysisId: a.id });
    return true;
  }

  if (sub === '/library' && req.method === 'GET') {
    // Legacy flat run list, one row per archived run across all analyses.
    const flat = [];
    for (const a of store.listAnalyses()) {
      const d = store.analysisDetail(a.id);
      for (const r of d.runs) {
        flat.push({ id: r.id, client: a.name, job: '', date: r.at, has_results: true, analysis_id: a.id });
      }
    }
    flat.sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')));
    send(res, 200, { runs: flat });
    return true;
  }

  if ((m = /^\/library\/([a-f0-9]+)\/results$/.exec(sub)) && req.method === 'GET') {
    const aid = store.findRun(m[1]);
    const results = aid ? await store.runResults(aid, m[1]) : null;
    if (!results) send(res, 404, { error: 'no results for that run' });
    else send(res, 200, results);
    return true;
  }

  if ((m = /^\/dumps\/([a-f0-9]+)\/out\/([^/\\]+)$/.exec(sub)) && req.method === 'GET') {
    const aid = store.findRun(m[1]);
    serveFile(res, aid ? await store.runArtifact(aid, m[1], m[2]) : null);
    return true;
  }

  if ((m = /^\/out\/([^/\\]+)$/.exec(sub)) && req.method === 'GET') {
    serveFile(res, path.join(OUT, path.basename(m[1])));
    return true;
  }

  return false;
}

function serveFile(res, file) {
  const ext = file ? path.extname(file).toLowerCase() : '';
  if (!file || !MIME[ext] || !fs.existsSync(file)) return send(res, 404, { error: 'not found' });
  res.writeHead(200, { 'content-type': MIME[ext] });
  res.end(fs.readFileSync(file));
}

module.exports = { handle, serveFile, runs, OUT, FILES_DIR, MIME, DUMPS: store.DUMPS };
