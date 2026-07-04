// 2. META (Facebook / Instagram) — Marketing API Insights edge.
//    Read-only: GET .../insights just reads reporting.

import { httpFetch, readJson } from '../lib/http.js';
import { ProbeError } from '../lib/errors.js';
import { normalizeRow } from '../lib/normalize.js';

export const platform = 'Meta';
export const channel = 'Meta';

export const requiredEnv = ['META_ACCESS_TOKEN', 'META_AD_ACCOUNT_ID'];

export const setup = `Meta Marketing API (Insights):
  1. In Business Manager > Business Settings > Users > System Users, create a
     System User and generate a token with ads_read (+ read_insights).
  2. Assign the ad account to that System User.
  3. META_AD_ACCOUNT_ID = the account id digits ONLY (the code adds "act_").
  Docs: https://developers.facebook.com/docs/marketing-api/insights`;

export function isConfigured(env) {
  return requiredEnv.every((k) => env[k]);
}

export async function fetchReport({ env, start, end }) {
  const version = env.META_API_VERSION || 'v19.0';
  const acct = String(env.META_AD_ACCOUNT_ID).replace(/^act_/, '');

  const params = new URLSearchParams({
    fields: 'campaign_name,spend,impressions',
    level: 'campaign',
    date_preset: 'last_7d',
    limit: '1',
    access_token: env.META_ACCESS_TOKEN,
  });
  const url = `https://graph.facebook.com/${version}/act_${acct}/insights?${params}`;

  const res = await httpFetch(url, { method: 'GET' });
  const body = await readJson(res);

  if (!res.ok || body.error) {
    const e = body.error || {};
    const msg = e.message || body.__nonJson || `HTTP ${res.status}`;
    // code 190 = invalid/expired token; type OAuthException = auth.
    const authish =
      res.status === 401 ||
      e.code === 190 ||
      e.type === 'OAuthException' ||
      /token|permission|OAuth/i.test(msg);
    throw new ProbeError(msg, {
      stage: authish ? 'auth' : 'data',
      status: res.status,
      detail: JSON.stringify(e).slice(0, 800),
      hint:
        e.code === 190
          ? 'System User token invalid/expired — regenerate it.'
          : undefined,
    });
  }

  const rows = body.data || [];
  return rows.map((r) =>
    normalizeRow({
      campaign: r.campaign_name ?? null,
      channel,
      spend: r.spend ?? 0,
      impressions: r.impressions ?? 0,
      start: r.date_start || start,
      end: r.date_stop || end,
    })
  );
}
