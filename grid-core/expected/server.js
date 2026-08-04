// Presentation server for the Expected side. Plain node http, no deps.
// POST /api/expected/analyze runs the real pipeline: extract.js (preprocess +
// one Claude call + generic validation) then build_expected.js (outputs).
// Stage state comes from the child processes' stdout markers, not timers.
// Start: node grid-core/expected/server.js   (port 8791, or EXPECTED_PORT)
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const crypto = require('crypto');

const ROOT = __dirname;
const OUT = path.join(ROOT, 'out');
const FILES_DIR = process.env.EXPECTED_FILES_DIR || path.join(ROOT, '..', 'files');
const PORT = Number(process.env.EXPECTED_PORT || 8791);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};

const runs = new Map();

function json(res, code, obj) {
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(obj));
}

function walk(dir, base, acc) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, base, acc);
    else if (e.name.toLowerCase() !== 'desktop.ini') {
      acc.push({ name: path.relative(base, p).split(path.sep).join('/'), bytes: fs.statSync(p).size });
    }
  }
  return acc;
}

function startRun() {
  const id = crypto.randomBytes(6).toString('hex');
  const run = {
    id,
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

  // Phase 1: extract.js drives the first three stages via stdout markers.
  const ex = spawn(process.execPath, [path.join(ROOT, 'extract.js'), '--files', FILES_DIR], { cwd: ROOT, env: process.env });
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
    if (code === 2) return fail('No ANTHROPIC_API_KEY found (environment or grid-core/.env). The extraction call cannot run without it.');
    if (code !== 0) return fail(`extract.js exited ${code}\n${(exErr || exOut).slice(-1500)}`);

    // Phase 2: build outputs.
    stage('outputs', 'active');
    const b = spawn(process.execPath, [path.join(ROOT, 'build_expected.js')], { cwd: ROOT });
    let bErr = '';
    let bOut = '';
    b.stderr.on('data', (d) => { bErr += d; });
    b.stdout.on('data', (d) => { bOut += d; });
    b.on('error', (e) => fail(String(e.message || e)));
    b.on('close', (bcode) => {
      if (run.status === 'error') return;
      if (bcode !== 0) return fail(`build_expected.js exited ${bcode}\n${(bErr || bOut).slice(-1500)}`);
      try {
        const plan = JSON.parse(fs.readFileSync(path.join(OUT, 'plan.json'), 'utf8'));
        const kpi = JSON.parse(fs.readFileSync(path.join(OUT, 'daily_kpi.json'), 'utf8'));
        const findingsDoc = JSON.parse(fs.readFileSync(path.join(OUT, 'findings.json'), 'utf8'));
        const messages = JSON.parse(fs.readFileSync(path.join(OUT, 'messages.json'), 'utf8'));
        const v = (node) => (node && node.value != null ? node.value : null);
        stage('outputs', 'done');
        run.status = 'done';
        run.results = {
          run: {
            id,
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
          },
          findings: findingsDoc.findings,
          origins: findingsDoc.origins,
          messages,
        };
      } catch (e) {
        fail(String(e.message || e));
      }
    });
  });

  return id;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;

  if (req.method === 'GET' && (p === '/' || p === '/index.html')) {
    res.writeHead(200, { 'content-type': MIME['.html'] });
    return res.end(fs.readFileSync(path.join(ROOT, 'index.html')));
  }

  if (req.method === 'GET' && p.startsWith('/out/')) {
    const name = path.basename(p); // flat dir, no traversal
    const file = path.join(OUT, name);
    const ext = path.extname(name).toLowerCase();
    if (!MIME[ext] || !fs.existsSync(file)) return json(res, 404, { error: 'not found' });
    res.writeHead(200, { 'content-type': MIME[ext] });
    return res.end(fs.readFileSync(file));
  }

  if (req.method === 'GET' && p === '/api/expected/files') {
    try {
      return json(res, 200, { files: walk(FILES_DIR, FILES_DIR, []) });
    } catch (e) {
      return json(res, 500, { error: String(e.message || e) });
    }
  }

  if (req.method === 'POST' && p === '/api/expected/analyze') {
    let body = '';
    req.on('data', (d) => { body += d; });
    req.on('end', () => {
      // Uploaded file metadata is acknowledged; byte upload into a per-run
      // staging dir is the next milestone. The run analyzes FILES_DIR.
      const running = [...runs.values()].some((r) => r.status === 'running');
      if (running) return json(res, 409, { error: 'a run is already in progress' });
      const id = startRun();
      json(res, 200, { runId: id });
    });
    return;
  }

  const m = /^\/api\/expected\/runs\/([a-f0-9]+)$/.exec(p);
  if (req.method === 'GET' && m) {
    const run = runs.get(m[1]);
    if (!run) return json(res, 404, { error: 'unknown run id' });
    return json(res, 200, run);
  }

  json(res, 404, { error: 'not found' });
});

server.listen(PORT, () => {
  console.log(`Expected side UI: http://localhost:${PORT}/  (files: ${FILES_DIR})`);
});
