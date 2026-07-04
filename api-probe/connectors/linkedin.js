// 3. LINKEDIN — Marketing API adAnalytics finder (read-only reporting).
//    Needs an OAuth2 token carrying the r_ads_reporting scope; a missing scope
//    surfaces as a 403 → classified 'scope' (YELLOW), not a hard auth failure.

import { httpFetch, readJson } from '../lib/http.js';
import { ProbeError } from '../lib/errors.js';
import { normalizeRow } from '../lib/normalize.js';

export const platform = 'LinkedIn';
export const channel = 'LinkedIn';

export const requiredEnv = ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AD_ACCOUNT_ID'];

export const setup = `LinkedIn Marketing API (adAnalytics):
  1. Create an app at https://developer.linkedin.com and request the
     "Advertising API" product (approval required).
  2. Mint an OAuth2 3-legged token that includes the r_ads_reporting scope,
     authorized by a user with access to the ad account.
  3. LINKEDIN_AD_ACCOUNT_ID = the sponsored account id (digits only).
  4. LINKEDIN_API_VERSION = a valid monthly version header, e.g. 202401.
  Docs: https://learn.microsoft.com/linkedin/marketing/integrations/ads-reporting/ads-reporting`;

export function isConfigured(env) {
  return requiredEnv.every((k) => env[k]);
}

// LinkedIn wants date parts, not ISO strings, inside the Rest.li dateRange.
function parts(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return { y, m, d };
}

export async function fetchReport({ env, start, end }) {
  const version = env.LINKEDIN_API_VERSION || '202401';
  const acctId = String(env.LINKEDIN_AD_ACCOUNT_ID).replace(/\D/g, '');
  const s = parts(start);
  const e = parts(end);

  // Rest.li query. The account urn's colons must be %3A-encoded; the rest of
  // the tuple syntax LinkedIn accepts as-is.
  const acctUrn = encodeURIComponent(`urn:li:sponsoredAccount:${acctId}`);
  const dateRange =
    `(start:(year:${s.y},month:${s.m},day:${s.d}),` +
    `end:(year:${e.y},month:${e.m},day:${e.d}))`;

  const qs =
    `q=analytics` +
    `&timeGranularity=ALL` +
    `&pivot=CAMPAIGN` +
    `&dateRange=${dateRange}` +
    `&accounts=List(${acctUrn})` +
    `&fields=costInLocalCurrency,impressions,pivotValues`;

  const url = `https://api.linkedin.com/rest/adAnalytics?${qs}`;

  const res = await httpFetch(url, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${env.LINKEDIN_ACCESS_TOKEN}`,
      'LinkedIn-Version': version,
      'X-Restli-Protocol-Version': '2.0.0',
    },
  });

  const body = await readJson(res);
  if (!res.ok) {
    const msg = body.message || body.__nonJson || `HTTP ${res.status}`;
    let stage = 'data';
    if (res.status === 401) stage = 'auth';
    // 403 with a permission/scope shape ⇒ token lacks r_ads_reporting.
    else if (res.status === 403 || /scope|permission|ACCESS_DENIED/i.test(msg))
      stage = 'scope';
    throw new ProbeError(msg, {
      stage,
      status: res.status,
      detail: JSON.stringify(body).slice(0, 800),
      hint:
        stage === 'scope'
          ? 'Re-consent the token WITH r_ads_reporting (and confirm the app has the Advertising API product).'
          : undefined,
    });
  }

  const elements = body.elements || [];
  return elements.map((el) =>
    normalizeRow({
      // pivotValues holds the campaign urn; the human name needs a second call
      // we deliberately skip in a probe.
      campaign: Array.isArray(el.pivotValues) ? el.pivotValues[0] : null,
      channel,
      spend: el.costInLocalCurrency ?? 0,
      impressions: el.impressions ?? 0,
      start,
      end,
    })
  );
}
