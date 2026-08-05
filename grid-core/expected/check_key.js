// Probe the ANTHROPIC_API_KEY in grid-core/.env (or the environment) with the
// cheapest possible real call: 1 output token on Haiku. Never prints the key.
//   node grid-core/expected/check_key.js
'use strict';

const fs = require('fs');
const path = require('path');

const envPath = path.join(__dirname, '..', '.env');
if (!process.env.ANTHROPIC_API_KEY && fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = /^\s*(ANTHROPIC_API_KEY|ANTHROPIC_BASE_URL|EXPECTED_MODEL)\s*=\s*(.*)\s*$/.exec(line);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}
const key = process.env.ANTHROPIC_API_KEY || '';
if (!key) {
  console.log('NO KEY: nothing in the environment or grid-core/.env');
  process.exit(2);
}
// Probe whatever provider .env points at (ANTHROPIC_BASE_URL may route to a
// Claude-compatible endpoint, e.g. Kimi's api.kimi.com/coding).
const model = process.env.EXPECTED_MODEL || 'claude-haiku-4-5';
console.log(`probing key: prefix=${key.slice(0, 10)}... len=${key.length} base=${process.env.ANTHROPIC_BASE_URL || 'api.anthropic.com'} model=${model}`);

const Anthropic = require('@anthropic-ai/sdk');
const client = new Anthropic({ maxRetries: 0 });

// process.exitCode + natural exit, never process.exit(): an explicit exit
// while the HTTP client still holds handles trips a libuv teardown assertion
// on Node/Windows and corrupts the exit code even on success.
client.messages.create({
  model,
  max_tokens: 16,
  messages: [{ role: 'user', content: 'Say OK.' }],
}).then((msg) => {
  console.log(`KEY OK: call succeeded on ${msg.model} (this key is funded and usable)`);
  process.exitCode = 0;
}).catch((e) => {
  const s = String(e && e.message || e);
  if (/credit balance is too low/i.test(s)) console.log('KEY VALID BUT NO CREDITS: the account behind this key has no API credits');
  else if (e && e.status === 401) console.log('KEY INVALID: authentication failed (wrong or revoked key)');
  else console.log('KEY CHECK FAILED: ' + s.slice(0, 200));
  process.exitCode = 1;
});
