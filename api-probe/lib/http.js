// Thin wrapper over the built-in global fetch (Node 18+): adds a timeout and
// tidy JSON/text parsing so connectors read cleanly.

import { ProbeError } from './errors.js';

const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * fetch with an AbortController timeout. Returns the raw Response.
 * Throws a ProbeError (stage 'data') on network error / timeout so a single
 * dead endpoint never hangs or crashes the whole probe.
 */
export async function httpFetch(url, opts = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, stageOnError = 'data', ...init } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new ProbeError(`request timed out after ${timeoutMs / 1000}s`, {
        stage: stageOnError,
        detail: url,
      });
    }
    throw new ProbeError(`network error: ${e.message}`, {
      stage: stageOnError,
      detail: `${url}\n${e.stack || ''}`,
    });
  } finally {
    clearTimeout(timer);
  }
}

/** Read a Response body as JSON, tolerating empty/HTML error pages. */
export async function readJson(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    // Provider returned non-JSON (often an HTML 403/502 page). Return the raw
    // text under a sentinel so callers can still surface something useful.
    return { __nonJson: text.slice(0, 500) };
  }
}

/** Build a application/x-www-form-urlencoded body from an object. */
export function form(obj) {
  return new URLSearchParams(obj).toString();
}
