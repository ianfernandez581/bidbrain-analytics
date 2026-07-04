// 4. REDDIT ADS — OAuth2 refresh-token flow, then a reporting query.
//    Token: HTTP Basic (client_id:client_secret) against reddit.com.
//    Report: POST .../reports is a reporting READ (no campaign mutation).

import { httpFetch, readJson, form } from '../lib/http.js';
import { ProbeError } from '../lib/errors.js';
import { normalizeRow } from '../lib/normalize.js';

export const platform = 'Reddit Ads';
export const channel = 'Reddit';

export const requiredEnv = [
  'REDDIT_CLIENT_ID',
  'REDDIT_CLIENT_SECRET',
  'REDDIT_REFRESH_TOKEN',
  'REDDIT_AD_ACCOUNT_ID',
];

export const setup = `Reddit Ads API:
  1. Create a "web app" OAuth client at https://www.reddit.com/prefs/apps .
  2. Complete the OAuth2 flow with scope "ads.read" to obtain a refresh token
     (offline access), as a user with access to the ad account.
  3. REDDIT_AD_ACCOUNT_ID = the ad account id from the Reddit Ads dashboard.
  4. REDDIT_USER_AGENT — Reddit requires a descriptive, unique User-Agent.
  Docs: https://ads-api.reddit.com/docs/`;

const TOKEN_URL = 'https://www.reddit.com/api/v1/access_token';
const API_BASE = 'https://ads-api.reddit.com/api/v3';

export function isConfigured(env) {
  return requiredEnv.every((k) => env[k]);
}

export async function fetchReport({ env, start, end }) {
  const ua = env.REDDIT_USER_AGENT || 'bidbrain-api-probe/0.1';

  // ── AUTH ──
  const basic = Buffer.from(
    `${env.REDDIT_CLIENT_ID}:${env.REDDIT_CLIENT_SECRET}`
  ).toString('base64');

  const tokRes = await httpFetch(TOKEN_URL, {
    method: 'POST',
    headers: {
      Authorization: `Basic ${basic}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': ua,
    },
    body: form({
      grant_type: 'refresh_token',
      refresh_token: env.REDDIT_REFRESH_TOKEN,
    }),
    stageOnError: 'auth',
  });
  const tok = await readJson(tokRes);
  if (!tokRes.ok || !tok.access_token) {
    throw new ProbeError(`token exchange failed: ${tok.error || `HTTP ${tokRes.status}`}`, {
      stage: 'auth',
      status: tokRes.status,
      detail: JSON.stringify(tok).slice(0, 500),
      hint: 'Check client id/secret and that the refresh token has ads.read.',
    });
  }

  // ── REPORT ── (last 7 days spend + impressions, grouped by campaign)
  const acct = env.REDDIT_AD_ACCOUNT_ID;
  const url = `${API_BASE}/ad_accounts/${acct}/reports`;
  const reqBody = {
    data: {
      starts_at: `${start}T00:00:00Z`,
      ends_at: `${end}T00:00:00Z`,
      time_zone_id: 'GMT',
      breakdowns: ['CAMPAIGN_ID'],
      fields: ['spend', 'impressions'],
    },
  };

  const res = await httpFetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${tok.access_token}`,
      'Content-Type': 'application/json',
      'User-Agent': ua,
    },
    body: JSON.stringify(reqBody),
  });
  const body = await readJson(res);

  if (!res.ok) {
    const msg =
      body?.error?.message || body?.message || body.__nonJson || `HTTP ${res.status}`;
    let stage = 'data';
    if (res.status === 401) stage = 'auth';
    else if (res.status === 403) stage = 'scope';
    throw new ProbeError(msg, {
      stage,
      status: res.status,
      detail: JSON.stringify(body).slice(0, 800),
    });
  }

  const rows = body?.data?.metrics || body?.data || [];
  const arr = Array.isArray(rows) ? rows : [];
  return arr.map((r) =>
    normalizeRow({
      campaign: r.campaign_id ?? null,
      channel,
      // Reddit returns spend in microcurrency — verify against the UI; scaling
      // doesn't affect the DATA-OK check but matters for the real app.
      spend: (Number(r.spend) || 0) / 1_000_000,
      impressions: r.impressions ?? 0,
      start,
      end,
    })
  );
}
