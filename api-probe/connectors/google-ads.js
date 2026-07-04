// 1. GOOGLE ADS — GAQL search over the REST endpoint.
//    Read-only: googleAds:search returns report rows, it never mutates.
//    cost_micros is returned as micros → divide by 1,000,000 for real currency.

import { refreshAccessToken } from '../lib/google-oauth.js';
import { httpFetch, readJson } from '../lib/http.js';
import { ProbeError } from '../lib/errors.js';
import { normalizeRow } from '../lib/normalize.js';

export const platform = 'Google Ads';
export const channel = 'Google Ads';

export const requiredEnv = [
  'GOOGLE_ADS_DEVELOPER_TOKEN',
  'GOOGLE_ADS_CLIENT_ID',
  'GOOGLE_ADS_CLIENT_SECRET',
  'GOOGLE_ADS_REFRESH_TOKEN',
  'GOOGLE_ADS_LOGIN_CUSTOMER_ID',
];

export const setup = `Google Ads (GAQL reporting):
  1. Get a developer token: Google Ads UI > Tools > API Center (needs "Basic
     access" approved for production; "Test account" access works for testing).
  2. Create an OAuth2 client (Desktop or Web) in Google Cloud Console and add
     the scope  https://www.googleapis.com/auth/adwords .
  3. Mint a refresh token for that client (OAuth playground or a one-off script),
     signing in as a user who can see the accounts.
  4. Set GOOGLE_ADS_LOGIN_CUSTOMER_ID to the MCC (manager) id, digits only.
     Set GOOGLE_ADS_CUSTOMER_ID to the leaf account you want spend for.
  Docs: https://developers.google.com/google-ads/api/docs/start`;

const QUERY =
  'SELECT campaign.name, metrics.cost_micros, metrics.impressions ' +
  'FROM campaign WHERE segments.date DURING LAST_7_DAYS LIMIT 1';

export function isConfigured(env) {
  return requiredEnv.every((k) => env[k]);
}

export async function fetchReport({ env, start, end }) {
  // ── AUTH ── (throws stage 'auth' on failure)
  const accessToken = await refreshAccessToken({
    clientId: env.GOOGLE_ADS_CLIENT_ID,
    clientSecret: env.GOOGLE_ADS_CLIENT_SECRET,
    refreshToken: env.GOOGLE_ADS_REFRESH_TOKEN,
  });

  // ── REPORT ──
  const version = env.GOOGLE_ADS_API_VERSION || 'v18';
  const loginId = String(env.GOOGLE_ADS_LOGIN_CUSTOMER_ID).replace(/-/g, '');
  const customerId = String(
    env.GOOGLE_ADS_CUSTOMER_ID || env.GOOGLE_ADS_LOGIN_CUSTOMER_ID
  ).replace(/-/g, '');

  const url = `https://googleads.googleapis.com/${version}/customers/${customerId}/googleAds:search`;
  const res = await httpFetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'developer-token': env.GOOGLE_ADS_DEVELOPER_TOKEN,
      'login-customer-id': loginId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query: QUERY }),
  });

  const body = await readJson(res);
  if (!res.ok) {
    const gerr = body?.error;
    const msg = gerr?.message || body.__nonJson || `HTTP ${res.status}`;
    // Auth-shaped failures (token/dev-token/permission) vs a report-shaped one.
    const authish =
      res.status === 401 ||
      /developer token|not authorized|permission|authentication/i.test(msg);
    throw new ProbeError(msg, {
      stage: authish ? 'auth' : 'data',
      status: res.status,
      detail: JSON.stringify(gerr || body).slice(0, 800),
      hint:
        res.status === 404
          ? `API version ${version} may be deprecated — try bumping GOOGLE_ADS_API_VERSION.`
          : undefined,
    });
  }

  const results = body.results || [];
  return results.map((r) =>
    normalizeRow({
      campaign: r.campaign?.name ?? null,
      channel,
      spend: Number(r.metrics?.costMicros ?? 0) / 1_000_000, // micros → currency
      impressions: r.metrics?.impressions ?? 0,
      start,
      end,
    })
  );
}
