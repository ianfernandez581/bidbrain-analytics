// Standalone dev harness for Greenlight (the Expected side). All logic lives
// in routes.js, which grid-core/server.js also mounts at /api/greenlight/*;
// this wrapper only preserves the original standalone paths on :8791 -
// /api/expected/*, /out/*, /dumps/* - which index.html and test_regression.js
// target. Production runs inside The Grid, not this server.
// Start: node grid-core/expected/server.js   (port 8791, or EXPECTED_PORT)
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const gl = require('./routes');

const ROOT = __dirname;
const PORT = Number(process.env.EXPECTED_PORT || 8791);

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    const p = url.pathname;

    if (req.method === 'GET' && (p === '/' || p === '/index.html')) {
      res.writeHead(200, { 'content-type': gl.MIME['.html'] });
      return res.end(fs.readFileSync(path.join(ROOT, 'index.html')));
    }

    // Shared handlers under the legacy prefix (analyses API included).
    if (await gl.handle(req, res, url, '/api/expected')) return;

    // Legacy unprefixed artifact paths used by index.html + the regression.
    let m;
    if (req.method === 'GET' && (m = /^\/out\/([^/\\]+)$/.exec(p))) {
      return gl.serveFile(res, path.join(gl.OUT, path.basename(m[1])));
    }
    if (req.method === 'GET' && (m = /^\/dumps\/([a-f0-9]+)\/out\/([^/\\]+)$/.exec(p))) {
      // route through the prefixed handler's logic by rewriting the URL
      const rewritten = new URL(`http://localhost:${PORT}/api/expected/dumps/${m[1]}/out/${m[2]}`);
      if (await gl.handle(req, res, rewritten, '/api/expected')) return;
    }

    res.writeHead(404, { 'content-type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: 'not found' }));
  } catch (err) {
    console.error('[expected] error', err.message);
    if (!res.headersSent) {
      res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: String(err.message || err) }));
    }
  }
});

server.listen(PORT, () => {
  console.log(`Greenlight standalone harness: http://localhost:${PORT}/  (prestage: ${gl.FILES_DIR})`);
});
