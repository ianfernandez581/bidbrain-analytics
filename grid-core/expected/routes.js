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
  '.log': 'text/plain; charset=utf-8',
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
// opts.resume: skip the model call and rebuild outputs from the analysis's
// saved last extraction (store.saveExtract slot) - the "retry the failed
// step" path. The extract stages render as done immediately.
function startRun(analysisId, inputDir, filesHash, opts) {
  opts = opts || {};
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

  // ---- run log. Both child processes already narrate what they are doing on
  // stdout; until now that text was thrown away unless the run failed. Tee it
  // into out/run.log so it archives with the other artifacts (archiveRun copies
  // the whole OUT dir) and can be read back per run, including for a run that
  // succeeded. run.log_tail also drives the live view while the run is in
  // flight, so a five-minute model call is not a blank screen.
  run.log = [];
  const logPath = () => path.join(OUT, 'run.log');
  const log = (line) => {
    const stamped = `${new Date().toISOString()} ${line}`;
    run.log.push(stamped);
    try {
      fs.mkdirSync(OUT, { recursive: true });
      fs.appendFileSync(logPath(), stamped + '\n');
    } catch { /* logging must never break a run */ }
  };
  const logChunk = (d) => {
    for (const line of String(d).split(/\r?\n/)) if (line.trim()) log(line);
  };
  try { fs.mkdirSync(OUT, { recursive: true }); fs.writeFileSync(logPath(), ''); } catch { /* ignore */ }
  log(`[run] ${id} started for analysis ${analysisId}${opts.resume ? ' (rebuild only, no model call)' : ''}`);
  const fail = (msg) => {
    const active = run.stages.find((s) => s.state === 'active');
    if (active) active.state = 'error';
    run.status = 'error';
    run.error = msg;
    log(`[run] FAILED: ${msg}`);
  };

  // TODO(background-job): extract + build run synchronously inside this
  // request lifecycle (~320s for the model call). Cloud Run's default request
  // timeout is 300s - the service needs --timeout 600 while this stays
  // synchronous; the real fix is a background job once Greenlight sees
  // real traffic. Deliberately not built yet.
  const env = { ...process.env, GREENLIGHT_OUT_DIR: OUT };

  const runBuild = () => {
    stage('outputs', 'active');
    const b = spawn(process.execPath, [path.join(ROOT, 'build_expected.js')], { cwd: ROOT, env });
    let bErr = '';
    let bOut = '';
    b.stderr.on('data', (d) => { bErr += d; logChunk(d); });
    b.stdout.on('data', (d) => { bOut += d; logChunk(d); });
    b.on('error', (e) => fail(String(e.message || e)));
    b.on('close', async (bcode) => {
      if (run.status === 'error') return;
      // Exit 3 is build_expected's deliberate "I will not invent a baseline"
      // (no resolvable flight, or no campaign line with budget + goals + dates).
      // That is an INCOMPLETE DUMP, not a broken run: the extraction and every
      // deterministic check already succeeded, and their findings are exactly
      // the list of what the buyer still owes. Failing here threw that away and
      // showed an exit code instead. Keep the run, mark it partial, and let the
      // findings - including NOT SUPPLIED / NOT READ - reach the UI so the next
      // upload is an informed one.
      const partial = bcode === 3;
      if (bcode !== 0 && !partial) return fail(`build_expected.js exited ${bcode}\n${(bErr || bOut).slice(-1500)}`);
      try {
        const readOut = (f) => JSON.parse(fs.readFileSync(path.join(OUT, f), 'utf8'));
        const plan = readOut('plan.json');
        // daily_kpi.json only exists when a baseline was actually built.
        const kpi = partial ? null : readOut('daily_kpi.json');
        const findingsDoc = readOut('findings.json');
        const messages = readOut('messages.json');
        const v = (node) => (node && node.value != null ? node.value : null);
        const blockedReason = partial ? (bErr || bOut).trim().split('\n').filter(Boolean).pop() : null;
        const needFiles = findingsDoc.findings.filter((f) => f.chip === 'NOT SUPPLIED' || f.chip === 'NOT READ');
        const results = {
          run: {
            id,
            analysis_id: analysisId,
            started_at: run.started_at,
            finished_at: new Date().toISOString(),
            model: plan.extractor ? plan.extractor.model : 'unknown',
            partial,
            blocked_reason: blockedReason,
          },
          // What the buyer has to send before a baseline can be built. Empty on
          // a complete run; the UI's call to action when it is not.
          needs_upload: needFiles.map((f) => ({ chip: f.chip, title: f.title, detail: f.detail })),
          meta: {
            client: kpi ? kpi.client : v(plan.client) || 'Unknown client',
            job: kpi ? kpi.job : v(plan.job_number) || 'unknown-job',
            campaign: v(plan.campaign_name) || '',
            currency: kpi ? kpi.currency : v(plan.currency) || 'UNKNOWN',
            total: kpi ? kpi.campaigns.reduce((a, c) => a + (c.total_budget || 0), 0) : null,
            flight: kpi && kpi.campaigns.length ? `${kpi.campaigns[0].start} to ${kpi.campaigns[0].end}` : 'unresolved',
            exceptions: kpi ? kpi.exceptions || [] : [],
            guard: plan.identity_guard || null,
          },
          findings: findingsDoc.findings,
          origins: findingsDoc.origins,
          messages,
        };
        // Log the outcome BEFORE archiving, so the archived run.log is complete
        // rather than stopping one line short of the result.
        const bySeverity = {};
        for (const f of findingsDoc.findings) bySeverity[f.severity] = (bySeverity[f.severity] || 0) + 1;
        const summary = Object.entries(bySeverity).map(([k, v]) => `${v} ${k}`).join(', ') || 'none';
        log(`[run] ${partial ? 'PARTIAL' : 'done'}: ${findingsDoc.findings.length} finding(s) (${summary})`);
        if (partial) log(`[run] baseline not built: ${blockedReason}`);
        for (const f of needFiles) log(`[run] ACTION NEEDED - ${f.chip}: ${f.title}`);
        await store.archiveRun(analysisId, id, OUT, results);
        const label = `${results.meta.client} ${results.meta.job || ''}`.trim();
        store.recordRun(analysisId, id, filesHash, label);
        // Partial runs render as done-with-a-warning, not as a spinner stuck on
        // the last stage - the work that could be done, was done.
        stage('outputs', partial ? 'warn' : 'done');
        run.status = 'done';
        run.partial = partial;
        run.results = results;
      } catch (e) {
        fail(String(e.message || e));
      }
    });
  };

  if (opts.resume) {
    // Build-only rerun: restore the saved extraction (no model call).
    store.loadExtract(analysisId, OUT).then((meta) => {
      if (run.status === 'error') return;
      if (!meta) return fail('no saved extraction to reuse - run the full analysis');
      ['extract', 'plan', 'gaps'].forEach((k) => stage(k, 'done'));
      runBuild();
    }).catch((e) => fail(String(e.message || e)));
    return id;
  }

  const ex = spawn(process.execPath, [path.join(ROOT, 'extract.js'), '--files', inputDir], { cwd: ROOT, env });
  let exErr = '';
  let exOut = '';
  ex.stderr.on('data', (d) => { exErr += d; logChunk(d); });
  ex.stdout.on('data', (d) => {
    exOut += d;
    logChunk(d);
    const s = String(d);
    if (s.includes('[stage] preprocess-done')) { stage('extract', 'done'); stage('plan', 'active'); }
    if (s.includes('[stage] model-done')) { stage('plan', 'done'); stage('gaps', 'active'); }
    if (s.includes('[stage] validate-done')) { stage('gaps', 'done'); }
  });
  ex.on('error', (e) => fail(String(e.message || e)));
  ex.on('close', (code) => {
    if (run.status === 'error') return;
    if (code === 2) return fail('No API key available (GREENLIGHT_API_KEY or ANTHROPIC_API_KEY). Locally: grid-core/.env. Deployed: the kimi-api-key / anthropic-api-key secret bindings (see expected/README.md).');
    if (code !== 0) return fail(`extract.js exited ${code}\n${(exErr || exOut).slice(-1500)}`);

    // The model call is paid for - save its output BEFORE building, so a
    // build failure can be retried via /rebuild without another extraction.
    store.saveExtract(analysisId, OUT, filesHash)
      .catch((e) => console.error('[greenlight] saveExtract failed (rebuild will need a full run):', e.message))
      .then(() => { if (run.status !== 'error') runBuild(); });
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

  // ---- rebuild outputs only (retry the failed step; reuses the saved
  //      extraction, so it costs no model call) ----
  if ((m = /^\/analyses\/([a-f0-9]+)\/rebuild$/.exec(sub)) && req.method === 'POST') {
    await readBody(req).catch(() => ({}));
    const a = store.analysisDetail(m[1]);
    if (!a) { send(res, 404, { error: 'unknown analysis' }); return true; }
    if (anyRunning()) { send(res, 409, { error: 'a run is already in progress' }); return true; }
    const meta = await store.extractMeta(m[1]);
    if (!meta) { send(res, 409, { error: 'no saved extraction for this analysis - run the full analysis' }); return true; }
    const hash = store.filesHash(m[1]);
    if (meta.files_hash && hash && meta.files_hash !== hash) {
      send(res, 409, { error: 'files changed since the last extraction - run the full analysis so the model sees the new files' });
      return true;
    }
    send(res, 200, { runId: startRun(m[1], store.aFilesDir(m[1]), hash, { resume: true }) });
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
