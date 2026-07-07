/*
 * scripts/brain-seed-historical.js — reproducible end-to-end test of the V3 flow.
 * Ensures the three fixtures exist, uploads them via the running server's API
 * (base64 JSON), polls each parse job to completion, and prints extraction
 * accuracy vs the fixtures' known totals.
 *
 * Usage:  node scripts/brain-seed-historical.js   (server must be running on PORT/8787)
 */
'use strict';
const fs = require('fs');
const path = require('path');
const fx = require('../test-fixtures/brain-historical/make-fixtures');

const BASE = `http://localhost:${process.env.PORT || 8787}`;
const DIR = path.join(__dirname, '..', 'test-fixtures', 'brain-historical');
const FILES = ['resetdata-print-2024.xlsx', 'resetdata-ooh-jcdecaux-2025.csv', 'resetdata-tv-q4-2024-media-plan.pdf'];
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  fx.makeAll();
  console.log('fixtures ready:', FILES.join(', '));

  const payload = {
    client_id: 'resetdata', channel_hint: null,
    files: FILES.map(f => ({ filename: f, data_base64: fs.readFileSync(path.join(DIR, f)).toString('base64') }))
  };
  const up = await (await fetch(`${BASE}/api/brain/historical/upload`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  })).json();
  if (up.error) { console.error('upload failed:', up.error); process.exit(1); }
  console.log(`uploaded ${up.files.length} files · LLM mode: anthropic=${up.llm.anthropic} llama=${up.llm.llama}\n`);

  for (const f of up.files) {
    let job, tries = 0;
    do {
      await sleep(1500);
      job = await (await fetch(`${BASE}/api/brain/historical/jobs/${f.job_id}`)).json();
      process.stdout.write(`\r  ${f.filename}: ${job.status} ${job.progress_pct}%   `);
    } while (job.status !== 'complete' && job.status !== 'failed' && ++tries < 200);
    console.log('');
    if (job.status === 'failed') { console.log(`  -> FAILED: ${job.error_message}`); continue; }
    const { rows } = await (await fetch(`${BASE}/api/brain/historical/files/${f.id}/rows`)).json();
    const total = rows.reduce((a, r) => a + (r.spend_aud || 0), 0);
    const key = f.filename.includes('print') ? 'print' : f.filename.includes('ooh') ? 'ooh' : 'tv';
    const expected = fx.EXPECTED[key];
    const acc = expected ? (100 - Math.min(100, Math.abs(total - expected) / expected * 100)) : null;
    console.log(`  -> ${rows.length} rows · conf=${job.overall_confidence} · spend extracted=$${total} vs expected=$${expected}` +
      (acc != null ? ` · accuracy=${acc.toFixed(1)}%` : ''));
  }
  console.log('\nRecent uploads:', (await (await fetch(`${BASE}/api/brain/historical/files?client_id=resetdata`)).json()).files.map(f => `${f.filename}[${f.status}]`).join(', '));
}
main().catch(e => { console.error(e); process.exit(1); });
