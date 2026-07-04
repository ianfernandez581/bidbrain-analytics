// 5. THE TRADE DESK — /authentication for a bearer token, then a My Reports
//    query. The 3rd-party My Reports API is OFF by default: a TTD rep must
//    enable it for your partner. We surface that as an 'enablement' failure
//    (RED) with a clear message, which is the specific risk being checked.
//
//    Note: the probe confirms (a) auth and (b) that My Reports responds. Actual
//    spend numbers come from downloading a *scheduled, completed* report — out
//    of scope for a read-only feasibility probe, so a reachable-but-empty API
//    lands YELLOW ("auth works, no data yet"), not GREEN.

import { httpFetch, readJson } from '../lib/http.js';
import { ProbeError } from '../lib/errors.js';

export const platform = 'The Trade Desk';
export const channel = 'The Trade Desk';

export const requiredEnv = ['TTD_API_USERNAME', 'TTD_API_PASSWORD', 'TTD_PARTNER_ID'];

export const setup = `The Trade Desk (My Reports API):
  1. Ask your TTD account rep for API user credentials (a Login/Password
     distinct from the UI login) AND to ENABLE 3rd-party My Reports API access
     for your PartnerId — it is off by default.
  2. TTD_PARTNER_ID = your partner id.
  3. To pull actual spend, schedule a Report Template in the TTD UI; the API
     then exposes its completed executions for download.
  Docs: https://api.thetradedesk.com/v3/portal/api/doc/ApiReference`;

export function isConfigured(env) {
  return requiredEnv.every((k) => env[k]);
}

export async function fetchReport({ env /*, start, end */ }) {
  const base = (env.TTD_API_BASE || 'https://api.thetradedesk.com/v3').replace(/\/$/, '');

  // ── AUTH ──
  const authRes = await httpFetch(`${base}/authentication`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      Login: env.TTD_API_USERNAME,
      Password: env.TTD_API_PASSWORD,
      TokenExpirationInMinutes: 60,
    }),
    stageOnError: 'auth',
  });
  const authBody = await readJson(authRes);
  const token = authBody.Token;
  if (!authRes.ok || !token) {
    const msg = authBody.Message || authBody.__nonJson || `HTTP ${authRes.status}`;
    throw new ProbeError(`authentication failed: ${msg}`, {
      stage: 'auth',
      status: authRes.status,
      detail: JSON.stringify(authBody).slice(0, 500),
      hint: 'Verify the API user Login/Password (not the UI login) with your TTD rep.',
    });
  }

  // ── MY REPORTS query (scoped to our partner) ──
  const res = await httpFetch(`${base}/myreports/reportexecution/query/partners`, {
    method: 'POST',
    headers: { 'TTD-Auth': token, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      PartnerIds: [String(env.TTD_PARTNER_ID)],
      PageStartIndex: 0,
      PageSize: 10,
    }),
  });
  const body = await readJson(res);

  if (!res.ok) {
    const msg = body.Message || body.__nonJson || `HTTP ${res.status}`;
    // 403 / not-authorized ⇒ My Reports API not enabled for this partner.
    if (res.status === 403 || /not authorized|forbidden|access/i.test(msg)) {
      throw new ProbeError(
        'My Reports API not enabled for this PartnerId',
        {
          stage: 'enablement',
          status: res.status,
          detail: msg,
          hint: 'Ask your TTD rep to enable 3rd-party My Reports API access for the partner.',
        }
      );
    }
    throw new ProbeError(msg, {
      stage: res.status === 401 ? 'auth' : 'data',
      status: res.status,
      detail: JSON.stringify(body).slice(0, 800),
    });
  }

  // 200: the My Reports API is reachable + enabled. We do not download report
  // CSVs here, so we cannot return real spend rows — report that honestly as a
  // 'data' (YELLOW) state rather than pretending it's GREEN.
  const execs = body.Result || body.ReportExecutionStates || [];
  throw new ProbeError(
    `My Reports API enabled ✓ (${execs.length} report execution(s) visible); ` +
      `no spend pulled — schedule a report template to read numbers`,
    { stage: 'data', status: 200 }
  );
}
