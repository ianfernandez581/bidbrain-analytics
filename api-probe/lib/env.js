// Tiny, zero-dependency .env loader.
// Kept deliberately dependency-free so the probe runs with just `node index.js`
// (no `npm install` needed) — the whole point is a fast feasibility check.

import { readFileSync, existsSync } from 'node:fs';

/**
 * Parse .env text into a plain object.
 * Supports: KEY=value, quoted values, `export KEY=`, `#` comments, blank lines.
 * Does NOT do variable interpolation (${FOO}) — secrets are literal.
 */
export function parseEnv(text) {
  const out = {};
  for (let raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;

    const stripped = line.startsWith('export ') ? line.slice(7).trim() : line;
    const eq = stripped.indexOf('=');
    if (eq === -1) continue;

    const key = stripped.slice(0, eq).trim();
    if (!key) continue;

    let val = stripped.slice(eq + 1).trim();
    // Strip a trailing inline comment on UNquoted values only.
    if (!/^["']/.test(val)) {
      const hash = val.indexOf(' #');
      if (hash !== -1) val = val.slice(0, hash).trim();
    }
    // Unwrap matching quotes.
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    out[key] = val;
  }
  return out;
}

/**
 * Load env from a .env file (if present) merged over process.env.
 * process.env wins is intentionally reversed: real env vars OVERRIDE the file
 * so CI / shell exports can override without editing .env.
 */
export function loadEnv(path = '.env') {
  const fileVars = existsSync(path) ? parseEnv(readFileSync(path, 'utf8')) : {};
  const merged = { ...fileVars };
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && v !== '') merged[k] = v;
  }
  // Treat empty strings as "not set" so blank .env lines read as unconfigured.
  const clean = {};
  for (const [k, v] of Object.entries(merged)) {
    if (v !== undefined && String(v).trim() !== '') clean[k] = String(v);
  }
  return { vars: clean, fileFound: existsSync(path) };
}
