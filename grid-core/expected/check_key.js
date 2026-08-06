// Probe the Greenlight API key in grid-core/.env (or the environment) with the
// cheapest possible real call: a handful of output tokens. Never prints the key.
//   node grid-core/expected/check_key.js
// Follows extract.js's provider rules: GREENLIGHT_* wins over ANTHROPIC_*, and
// GREENLIGHT_PROVIDER (or a groq base URL) selects the OpenAI-compatible wire
// format instead of Anthropic's.
'use strict';

const fs = require('fs');
const path = require('path');

const KEYS = /^\s*(GREENLIGHT_PROVIDER|GREENLIGHT_API_KEY|GREENLIGHT_BASE_URL|GROQ_API_KEY|ANTHROPIC_API_KEY|ANTHROPIC_BASE_URL|EXPECTED_MODEL)\s*=\s*(.*)\s*$/;
const envPath = path.join(__dirname, '..', '.env');
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = KEYS.exec(line);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

const key = process.env.GREENLIGHT_API_KEY || process.env.GROQ_API_KEY || process.env.ANTHROPIC_API_KEY || '';
if (!key) {
  console.log('NO KEY: nothing in the environment or grid-core/.env');
  process.exit(2);
}

const explicit = (process.env.GREENLIGHT_PROVIDER || '').trim().toLowerCase();
const baseUrl = process.env.GREENLIGHT_BASE_URL || process.env.ANTHROPIC_BASE_URL || '';
const provider = explicit || (/groq\.com/i.test(baseUrl) ? 'groq' : 'anthropic');
const model = process.env.EXPECTED_MODEL || (provider === 'groq' ? 'openai/gpt-oss-120b' : 'claude-haiku-4-5');
const shownBase = baseUrl || (provider === 'groq' ? 'api.groq.com/openai/v1' : 'api.anthropic.com');
console.log(`probing key: prefix=${key.slice(0, 10)}... len=${key.length} provider=${provider} base=${shownBase} model=${model}`);

if (provider === 'groq') {
  const base = (baseUrl || 'https://api.groq.com/openai/v1').replace(/\/$/, '');
  fetch(`${base}/chat/completions`, {
    method: 'POST',
    headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model, max_completion_tokens: 16, messages: [{ role: 'user', content: 'Say OK.' }] }),
  }).then(async (res) => {
    const body = await res.json().catch(() => ({}));
    if (res.ok) {
      console.log(`KEY OK: call succeeded on ${body.model || model} (this key is funded and usable)`);
      process.exitCode = 0;
      return;
    }
    const msg = (body.error && body.error.message) || `HTTP ${res.status}`;
    if (res.status === 401) console.log('KEY INVALID: authentication failed (wrong or revoked key)');
    else if (res.status === 429) console.log('KEY VALID BUT RATE LIMITED: ' + msg.slice(0, 200));
    else console.log('KEY CHECK FAILED: ' + msg.slice(0, 200));
    process.exitCode = 1;
  }).catch((e) => {
    console.log('KEY CHECK FAILED: ' + String(e && e.message || e).slice(0, 200));
    process.exitCode = 1;
  });
} else {
  const Anthropic = require('@anthropic-ai/sdk');
  const client = new Anthropic({ maxRetries: 0, apiKey: key, baseURL: baseUrl || undefined });

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
}
