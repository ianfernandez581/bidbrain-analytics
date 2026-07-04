/**
 * google-ads.js — SYNCHRONOUS connector (access pattern A).
 * Read-only reporting via GAQL. No mutate calls, ever.
 *
 * Auth: OAuth2 refresh token -> access token, plus a developer token and the
 * MCC login-customer-id header. cost_micros is returned in millionths of the
 * account currency, so we divide by 1e6 (the classic silent-bug trap).
 *
 * Env required:
 *   GOOGLE_ADS_DEVELOPER_TOKEN
 *   GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN
 *   GOOGLE_ADS_LOGIN_CUSTOMER_ID   (MCC, digits only)
 *   GOOGLE_ADS_CUSTOMER_IDS        (comma-separated client accounts, digits only)
 *   GOOGLE_ADS_API_VERSION         (optional, defaults below — bump when needed)
 */

'use strict';
const { ProbeError, httpJson, need, normalizedRow } = require('./connector-base');

const DEFAULT_VERSION = 'v23'; // flagged: bump as Google's monthly releases advance

async function getAccessToken(env) {
  const body = new URLSearchParams({
    client_id: need(env, 'GOOGLE_ADS_CLIENT_ID', 'GoogleAds'),
    client_secret: need(env, 'GOOGLE_ADS_CLIENT_SECRET', 'GoogleAds'),
    refresh_token: need(env, 'GOOGLE_ADS_REFRESH_TOKEN', 'GoogleAds'),
    grant_type: 'refresh_token',
  });
  const tok = await httpJson('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  }, { platform: 'GoogleAds(oauth)' });
  if (!tok.access_token) throw new ProbeError('auth', 'GoogleAds: no access_token from refresh');
  return tok.access_token;
}

async function fetchReport({ env, start, end }) {
  const devToken = need(env, 'GOOGLE_ADS_DEVELOPER_TOKEN', 'GoogleAds');
  const mcc = need(env, 'GOOGLE_ADS_LOGIN_CUSTOMER_ID', 'GoogleAds');
  const customerIds = need(env, 'GOOGLE_ADS_CUSTOMER_IDS', 'GoogleAds')
    .split(',').map(s => s.trim()).filter(Boolean);
  const version = env.GOOGLE_ADS_API_VERSION || DEFAULT_VERSION;

  const accessToken = await getAccessToken(env);

  const query = `
    SELECT campaign.name, campaign.status, campaign_budget.amount_micros,
           metrics.impressions, metrics.cost_micros
    FROM campaign
    WHERE segments.date BETWEEN '${start}' AND '${end}'
      AND campaign.status != 'REMOVED'`.trim();

  const rows = [];
  for (const cid of customerIds) {
    const url = `https://googleads.googleapis.com/${version}/customers/${cid}/googleAds:searchStream`;
    const res = await httpJson(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'developer-token': devToken,
        'login-customer-id': mcc,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query }),
    }, { platform: 'GoogleAds' });

    const batches = Array.isArray(res) ? res : [res];
    for (const batch of batches) {
      for (const r of (batch.results || [])) {
        const impressions = Number(r.metrics?.impressions ?? 0);
        const mediaSpend = Number(r.metrics?.costMicros ?? 0) / 1e6;      // <-- /1e6
        const totalBudget = r.campaignBudget?.amountMicros != null
          ? Number(r.campaignBudget.amountMicros) / 1e6 : null;
        rows.push(normalizedRow({
          campaign: r.campaign?.name ?? null,
          channel: 'Google Ads',
          status: r.campaign?.status ?? null,
          start, end,
          impressions,
          mediaSpend,
          clientSpent: mediaSpend, // pass-through unless a client margin applies
          totalBudget,
        }));
      }
    }
  }
  if (!rows.length) throw new ProbeError('data', 'GoogleAds: auth OK but no rows for window');
  return rows;
}

module.exports = { fetchReport, accessPattern: 'sync' };
