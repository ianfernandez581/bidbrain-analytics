/**
 * connector-base.js — the contract every platform connector implements, plus
 * shared machinery for the two access patterns we see across platforms:
 *
 *   (A) SYNCHRONOUS   — Google Ads, Meta, LinkedIn, Reddit:
 *                       one authenticated call returns rows directly.
 *   (B) CREATE-POLL   — The Trade Desk (My Reports), DV360 (Bid Manager):
 *                       you define a report, trigger a run, poll until ready,
 *                       then download results. This latency is HIDDEN inside
 *                       fetchReport() so the orchestrator just awaits an array.
 *
 * Every connector exports:
 *     async fetchReport({ env, start, end, advertiserIds }) -> RawRow[]
 *
 * and throws ProbeError(stage, message) on failure so callers can tell
 * "bad password" (auth) from "missing permission" (scope) from
 * "platform hasn't switched it on" (enablement) from "auth fine, no data" (data).
 */

'use strict';

class ProbeError extends Error {
  /** @param {'auth'|'scope'|'data'|'enablement'|'config'|'network'} stage */
  constructor(stage, message, meta = {}) {
    super(message);
    this.name = 'ProbeError';
    this.stage = stage;
    this.meta = meta;
  }
}

/**
 * httpJson — fetch with timeout + structured error classification.
 * Maps HTTP status codes to ProbeError stages so every connector
 * classifies failures consistently.
 */
async function httpJson(url, opts = {}, { timeoutMs = 20000, platform = '' } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, { ...opts, signal: ctrl.signal });
  } catch (e) {
    clearTimeout(t);
    if (e.name === 'AbortError') throw new ProbeError('network', `${platform}: request timed out after ${timeoutMs}ms`);
    throw new ProbeError('network', `${platform}: ${e.message}`);
  }
  clearTimeout(t);

  const text = await res.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { raw: text }; }

  if (!res.ok) {
    const stage =
      res.status === 401 ? 'auth' :
      res.status === 403 ? 'scope' :        // caller may re-tag as 'enablement'
      res.status === 429 ? 'network' :      // rate limited — transient
      res.status >= 500  ? 'network' : 'data';
    throw new ProbeError(stage, `${platform}: HTTP ${res.status} ${res.statusText}`, { status: res.status, body });
  }
  return body;
}

/**
 * pollUntil — generic poll loop for CREATE-POLL platforms.
 * checkFn() should return { done: boolean, result?: any } or throw.
 * Backs off, respects a wall-clock budget, surfaces timeouts as 'data' stage
 * (auth already succeeded by the time we're polling).
 */
async function pollUntil(checkFn, { platform = '', intervalMs = 3000, maxMs = 120000 } = {}) {
  const start = Date.now();
  let delay = intervalMs;
  for (;;) {
    const { done, result } = await checkFn();
    if (done) return result;
    if (Date.now() - start > maxMs) {
      throw new ProbeError('data', `${platform}: report did not finish within ${Math.round(maxMs / 1000)}s`);
    }
    await new Promise(r => setTimeout(r, delay));
    delay = Math.min(delay * 1.4, 15000); // gentle backoff, cap 15s
  }
}

/** Require an env var or fail with a clear 'config' error (probe -> NOT CONFIGURED). */
function need(env, key, platform) {
  const v = env[key];
  if (v == null || v === '') throw new ProbeError('config', `${platform}: missing ${key}`, { key });
  return v;
}

/**
 * The normalized row every connector must produce. Kept identical to the
 * derive.js raw-input shape so results flow straight into derive() untouched.
 * Connectors fill what they know; missing fields stay null (derive handles nulls).
 */
function normalizedRow(partial) {
  return {
    agency: null, advertiser: null, jobNumber: null, campaign: null,
    objective: null, channel: null, managedBy: null, status: null,
    start: null, end: null,
    platformMargin: null, adServingRate: null, forecastCPM: null,
    keyKPI: null, kpiPerf: null,
    budgetGross: null, totalBudget: null,
    impressions: null, mediaSpend: null, clientSpent: null,
    campaignLink: null, nextReport: null, notes: null,
    ...partial,
  };
}

module.exports = { ProbeError, httpJson, pollUntil, need, normalizedRow };
