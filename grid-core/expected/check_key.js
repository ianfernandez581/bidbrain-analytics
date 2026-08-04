// Probe the ANTHROPIC_API_KEY in grid-core/.env (or the environment) with the
// cheapest possible real call: 1 output token on Haiku. Never prints the key.
//   node grid-core/expected/check_key.js
'use strict';

const fs = require('fs');
const path = require('path');

const envPath = path.join(__dirname, '..', '.env');
if (!process.env.ANTHROPIC_API_KEY && fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = /^\s*ANTHROPIC_API_KEY\s*=\s*(.*)\s*$/.exec(line);
    if (m) process.env.ANTHROPIC_API_KEY = m[1].replace(/^["']|["']$/g, '');
  }
}
const key = process.env.ANTHROPIC_API_KEY || '';
if (!key) {
  console.log('NO KEY: nothing in the environment or grid-core/.env');
  process.exit(2);
}
console.log(`probing key: prefix=${key.slice(0, 10)}... len=${key.length}`);

const Anthropic = require('@anthropic-ai/sdk');
const client = new Anthropic({ maxRetries: 0 });

client.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 1,
  messages: [{ role: 'user', content: 'Say OK.' }],
}).then((msg) => {
  console.log(`KEY OK: call succeeded on ${msg.model} (this key is funded and usable)`);
  process.exit(0);
}).catch((e) => {
  const s = String(e && e.message || e);
  if (/credit balance is too low/i.test(s)) console.log('KEY VALID BUT NO CREDITS: the account behind this key has no API credits');
  else if (e && e.status === 401) console.log('KEY INVALID: authentication failed (wrong or revoked key)');
  else console.log('KEY CHECK FAILED: ' + s.slice(0, 200));
  process.exit(1);
});
