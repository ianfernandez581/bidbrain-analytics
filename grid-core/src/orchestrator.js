/**
 * orchestrator.js — the single call the live app makes.
 * Fans out to every configured connector in parallel, tags provenance, runs the
 * shared derive() on every row, and returns dashboard-ready data plus a per-source
 * status map (so the "Data sources" strip can show LIVE/MANUAL + freshness + errors).
 *
 * Connectors that throw are isolated: one platform failing (e.g. TTD not enabled)
 * never blocks the others. Its rows are simply absent and its status carries the
 * stage/message so the UI can show exactly why.
 */

'use strict';
// PHASE 1: src/derive.js is QUARANTINED (src/_retired/) — nothing may import it.
// This layer is DORMANT (only the retired reconcile.js CLI ever loaded it; actuals
// come via the BQ sync, not connectors). If someone revives it, fail loudly and
// point at the single engine instead of silently computing with retired formulas.
const derive = () => { throw new Error('orchestrator: derive.js was retired in Phase 1 - use src/central/calc.js (computeRow) instead'); };
const { ProbeError } = require('./connectors/connector-base');

const PLATFORMS = {
  google:   { module: './connectors/google-ads',  label: 'Google Ads',     api: 'Google Ads API',          channelMatch: c => c === 'Google Ads' },
  meta:     { module: './connectors/meta',         label: 'Meta',           api: 'Meta Marketing API',      channelMatch: c => c === 'Meta' },
  ttd:      { module: './connectors/trade-desk',   label: 'The Trade Desk', api: 'TTD My Reports API',       channelMatch: c => c === 'TradeDesk' },
  dv360:    { module: './connectors/dv360',        label: 'DV360',          api: 'Display & Video 360 API',  channelMatch: c => c === 'DV360' },
  linkedin: { module: './connectors/linkedin',     label: 'LinkedIn',       api: 'LinkedIn Marketing API',   channelMatch: c => c === 'Linkedin' },
  reddit:   { module: './connectors/reddit',       label: 'Reddit',         api: 'Reddit Ads API',           channelMatch: c => c === 'Reddit' },
};

function loadConnector(key) {
  try { return require(PLATFORMS[key].module); }
  catch { return null; } // module not present yet (Google + TTD are the two shipped as examples)
}

/**
 * fetchLiveCampaigns({ env, start, end, only, asOf, onProgress })
 *   -> { rows: DerivedRow[], status: {key: {...}}, fetchedAt }
 */
async function fetchLiveCampaigns({ env, start, end, only = null, asOf = null, onProgress = null } = {}) {
  const keys = Object.keys(PLATFORMS).filter(k => !only || only.includes(k));
  const fetchedAt = Date.now();

  const settled = await Promise.all(keys.map(async key => {
    const meta = PLATFORMS[key];
    const conn = loadConnector(key);
    if (!conn) {
      const st = { key, label: meta.label, api: meta.api, ok: false, stage: 'config', message: 'connector not implemented yet', count: 0, syncMode: 'manual' };
      onProgress && onProgress(key, st);
      return { rows: [], status: st };
    }
    try {
      const raw = await conn.fetchReport({ env, start, end });
      const rows = raw.map(r => {
        const tagged = { ...r, sourceKey: key, sourceLabel: meta.label, sourceApi: meta.api, syncMode: 'api', syncedAt: fetchedAt };
        return derive(tagged, { asOf });
      });
      const st = { key, label: meta.label, api: meta.api, ok: true, stage: null, message: null, count: rows.length, syncMode: 'api', syncedAt: fetchedAt };
      onProgress && onProgress(key, st);
      return { rows, status: st };
    } catch (e) {
      const stage = e instanceof ProbeError ? e.stage : 'network';
      const st = { key, label: meta.label, api: meta.api, ok: false, stage, message: e.message, count: 0, syncMode: 'api' };
      onProgress && onProgress(key, st);
      return { rows: [], status: st };
    }
  }));

  const rows = settled.flatMap(s => s.rows);
  const status = Object.fromEntries(settled.map(s => [s.status.key, s.status]));
  return { rows, status, fetchedAt };
}

module.exports = { fetchLiveCampaigns, PLATFORMS };
