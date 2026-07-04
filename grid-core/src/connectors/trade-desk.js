/**
 * trade-desk.js — CREATE-POLL connector (access pattern B).
 * The Trade Desk "My Reports" 3rd-party API. Read-only reporting.
 *
 * Access model reality (verified): there is NO self-serve signup. You need an
 * existing TTD seat/partnership and your account team must switch on 3rd-party
 * My Reports API access for your Partner. Until they do, report endpoints return
 * 403 — which we surface as stage 'enablement' (RED, "ask your rep"), NOT 'scope'.
 *
 * Flow, all hidden behind one awaited fetchReport():
 *   1. POST /v3/authentication  (username+password) -> bearer token ('TTD {token}')
 *   2. Ensure a report template / schedule exists for our metrics
 *   3. Trigger a run, poll until the download URL is ready
 *   4. Fetch + parse the result rows
 *
 * A reachable-but-not-yet-populated API (template exists, no run finished) is
 * YELLOW (data), not GREEN — real spend needs a completed scheduled report.
 *
 * Env required:
 *   TTD_API_USERNAME, TTD_API_PASSWORD, TTD_PARTNER_ID
 *   TTD_ADVERTISER_IDS   (optional, comma-separated; empty = all under partner)
 *   TTD_REPORT_TEMPLATE_ID (optional; if set we run this template instead of ad-hoc)
 */

'use strict';
const { ProbeError, httpJson, pollUntil, need, normalizedRow } = require('./connector-base');

const BASE = 'https://api.thetradedesk.com/v3';

async function authenticate(env) {
  const login = need(env, 'TTD_API_USERNAME', 'TradeDesk');
  const password = need(env, 'TTD_API_PASSWORD', 'TradeDesk');
  let res;
  try {
    res = await httpJson(`${BASE}/authentication`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ Login: login, Password: password, TokenExpirationInMinutes: 60 }),
    }, { platform: 'TradeDesk(auth)' });
  } catch (e) {
    // 403 at the auth stage on TTD usually means the API user isn't enabled
    if (e instanceof ProbeError && e.meta?.status === 403) {
      throw new ProbeError('enablement', 'TradeDesk: API user not enabled — ask your TTD rep to enable 3rd-party My Reports API for this Partner', e.meta);
    }
    throw e;
  }
  if (!res.Token) throw new ProbeError('auth', 'TradeDesk: authentication returned no Token');
  return res.Token;
}

function ttdHeaders(token) {
  return { 'Authorization': `TTD ${token}`, 'Content-Type': 'application/json' };
}

async function fetchReport({ env, start, end }) {
  const partnerId = need(env, 'TTD_PARTNER_ID', 'TradeDesk');
  const advertiserIds = (env.TTD_ADVERTISER_IDS || '').split(',').map(s => s.trim()).filter(Boolean);
  const templateId = env.TTD_REPORT_TEMPLATE_ID || null;

  const token = await authenticate(env);
  const headers = ttdHeaders(token);

  // Step 2/3: trigger a report run. If a template is provided, run it; otherwise
  // this is where an ad-hoc My Reports request body goes. Body schema is
  // partner-specific; the create-then-poll STRUCTURE is what matters here.
  let runId;
  try {
    const runBody = templateId
      ? { ReportScheduleId: templateId, StartDate: start, EndDate: end }
      : {
          PartnerId: partnerId,
          AdvertiserIds: advertiserIds,        // empty = all
          ReportStartDateInclusive: start,
          ReportEndDateExclusive: end,
          // Metrics/dimensions are defined on the template in practice; ad-hoc
          // report creation may require a saved ReportTemplate first.
        };
    const created = await httpJson(`${BASE}/myreports/reportexecution/query`, {
      method: 'POST', headers, body: JSON.stringify(runBody),
    }, { platform: 'TradeDesk(run)' });
    runId = created.ReportExecutionId || created.ExecutionId || created.Id;
    if (!runId) {
      // Reachable, authenticated, but nothing to run yet -> YELLOW, not RED.
      throw new ProbeError('data', 'TradeDesk: auth OK, but no report template/run available — create a My Reports template to populate spend');
    }
  } catch (e) {
    if (e instanceof ProbeError && e.meta?.status === 403) {
      throw new ProbeError('enablement', 'TradeDesk: report API returned 403 — 3rd-party My Reports API not enabled for this Partner', e.meta);
    }
    throw e;
  }

  // Step 3 (cont): poll for completion + download URL
  const downloadUrl = await pollUntil(async () => {
    const status = await httpJson(`${BASE}/myreports/reportexecution/query/${runId}`, {
      method: 'GET', headers,
    }, { platform: 'TradeDesk(poll)' });
    const state = (status.ReportExecutionState || status.State || '').toLowerCase();
    if (state === 'complete' || state === 'completed') {
      const url = status.DownloadUrl || status.ReportDownloadUrl
        || (status.ReportDeliveries && status.ReportDeliveries[0]?.DownloadUrl);
      return { done: true, result: url };
    }
    if (state === 'error' || state === 'failed') {
      throw new ProbeError('data', 'TradeDesk: report run failed');
    }
    return { done: false };
  }, { platform: 'TradeDesk', intervalMs: 4000, maxMs: 180000 });

  if (!downloadUrl) throw new ProbeError('data', 'TradeDesk: report completed but no download URL');

  // Step 4: fetch + parse. TTD reports are typically CSV; parse into rows.
  const csv = await httpJson(downloadUrl, { method: 'GET' }, { platform: 'TradeDesk(download)' })
    .catch(() => null);
  const rows = parseTtdRows(csv, { start, end });
  if (!rows.length) throw new ProbeError('data', 'TradeDesk: report empty for window');
  return rows;
}

// TTD column names depend on the template; map the common ones.
function parseTtdRows(payload, { start, end }) {
  if (!payload) return [];
  const records = Array.isArray(payload) ? payload : (payload.Rows || payload.rows || []);
  return records.map(r => normalizedRow({
    advertiser: r.AdvertiserName ?? r.Advertiser ?? null,
    campaign: r.CampaignName ?? r.Campaign ?? null,
    channel: 'TradeDesk',
    start, end,
    impressions: numOrNull(r.Impressions),
    mediaSpend: numOrNull(r.AdvertiserCostInUSD ?? r.PartnerCostInUSD ?? r.MediaCost ?? r.Spend),
    clientSpent: numOrNull(r.ClientCost ?? r.AdvertiserCostInUSD ?? r.Spend),
  }));
}
function numOrNull(v) { if (v == null || v === '') return null; const n = Number(v); return isNaN(n) ? null : n; }

module.exports = { fetchReport, accessPattern: 'create-poll' };
