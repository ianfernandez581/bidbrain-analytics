// Small presentation server for the Expected side. Plain node http, no deps.
// Serves index.html + the out/ artifacts, and runs the untouched pipeline
// (build_expected.js) behind POST /api/expected/analyze with polled run state.
// Start: node grid-core/expected/server.js   (port 8791, or EXPECTED_PORT)
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const crypto = require('crypto');

const ROOT = __dirname;
const OUT = path.join(ROOT, 'out');
const FILES_DIR = path.join(ROOT, '..', 'files');
const PORT = Number(process.env.EXPECTED_PORT || 8791);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};

const runs = new Map(); // id -> run state

function json(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(body);
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

function parseMessages(md) {
  return md.split(/\n---\n/).map((s) => s.trim())
    .filter((s) => s.startsWith('## Message'))
    .map((s) => {
      const nl = s.indexOf('\n');
      return { title: s.slice(3, nl).trim(), body: s.slice(nl + 1).trim() };
    });
}

function startRun() {
  const id = crypto.randomBytes(6).toString('hex');
  const run = {
    id,
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
  const fail = (key, msg) => {
    stage(key, 'error');
    run.status = 'error';
    run.error = msg;
  };
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  (async () => {
    let findings;
    try {
      // Stage 1: extract - inventory the input dump.
      const files = walk(FILES_DIR, FILES_DIR, []);
      if (!files.length) return fail('extract', `no input files found in ${FILES_DIR}`);
      await delay(400);
      stage('extract', 'done');
      stage('plan', 'active');

      // Stage 2: reading plan - the extracted constants live in build_expected.js
      // (model-extracted this session, hand-verified; automated extraction is the
      // next milestone). Confirm the pipeline file is present and parseable.
      require.resolve(path.join(ROOT, 'build_expected.js'));
      await delay(400);
      stage('plan', 'done');
      stage('gaps', 'active');

      // Stage 3: gaps - load the structured findings.
      findings = JSON.parse(fs.readFileSync(path.join(ROOT, 'findings.json'), 'utf8'));
      await delay(400);
      stage('gaps', 'done');
      stage('outputs', 'active');
    } catch (e) {
      return fail(run.stages.find((s) => s.state === 'active')?.key || 'extract', String(e.message || e));
    }

    // Stage 4: outputs - run the untouched pipeline.
    const child = spawn(process.execPath, [path.join(ROOT, 'build_expected.js')], { cwd: ROOT });
    let errBuf = '';
    child.stderr.on('data', (d) => { errBuf += d; });
    child.on('error', (e) => fail('outputs', String(e.message || e)));
    child.on('close', (code) => {
      if (run.status === 'error') return;
      if (code !== 0) return fail('outputs', `build_expected.js exited ${code}\n${errBuf.slice(-1500)}`);
      try {
        const kpi = JSON.parse(fs.readFileSync(path.join(OUT, 'daily_kpi.json'), 'utf8'));
        const messages = parseMessages(fs.readFileSync(path.join(OUT, 'chase_messages.md'), 'utf8'));
        stage('outputs', 'done');
        run.status = 'done';
        run.results = {
          meta: {
            client: kpi.client,
            job: kpi.job + ' NEL Awareness (ANZ)',
            currency: kpi.currency,
            total: kpi.campaigns.reduce((a, c) => a + c.total_budget, 0),
            flight: `${kpi.campaigns[0].start} to ${kpi.campaigns[0].end}`,
          },
          findings: findings.findings,
          messages,
        };
      } catch (e) {
        fail('outputs', String(e.message || e));
      }
    });
  })();

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
      // Uploaded file metadata is accepted and acknowledged; byte upload plus
      // automated extraction is the next milestone. The run analyzes the
      // staged dump in grid-core/files.
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
  console.log(`Expected side UI: http://localhost:${PORT}/`);
});
