// 6. DV360 (Display & Video 360) — OAuth2, then READ-ONLY reachability checks
//    against both the DV360 API (advertiser access) and the Bid Manager API
//    (reporting access).
//
//    DV360's actual spend numbers come from RUNNING a Bid Manager query, which
//    creates/executes a report resource — a write. To honour "reads only" we do
//    NOT run a query; instead we confirm auth + that both APIs are reachable
//    with our credentials, then report YELLOW ("auth works, reporting reachable,
//    spend needs a report run"). That's the true feasibility signal.

import { refreshAccessToken } from '../lib/google-oauth.js';
import { httpFetch, readJson } from '../lib/http.js';
import { ProbeError } from '../lib/errors.js';

export const platform = 'DV360';
export const channel = 'DV360';

export const requiredEnv = [
  'DV360_CLIENT_ID',
  'DV360_CLIENT_SECRET',
  'DV360_REFRESH_TOKEN',
  'DV360_PARTNER_ID',
];

export const setup = `DV360 (Display & Video 360 + Bid Manager):
  1. OAuth2 client (Google Cloud Console) with BOTH scopes:
       https://www.googleapis.com/auth/display-video
       https://www.googleapis.com/auth/doubleclickbidmanager
     (Can reuse the Google Ads OAuth client if it carries these scopes.)
  2. Mint a refresh token as a user with DV360 access.
  3. DV360_PARTNER_ID (required) and optionally DV360_ADVERTISER_ID.
  Docs: https://developers.google.com/display-video/api/guides/getting-started/overview`;

export function isConfigured(env) {
  return requiredEnv.every((k) => env[k]);
}

export async function fetchReport({ env }) {
  // ── AUTH ──
  const accessToken = await refreshAccessToken({
    clientId: env.DV360_CLIENT_ID,
    clientSecret: env.DV360_CLIENT_SECRET,
    refreshToken: env.DV360_REFRESH_TOKEN,
  });
  const auth = { Authorization: `Bearer ${accessToken}` };

  // ── DV360 API: confirm advertiser/partner access (read-only) ──
  const dvUrl = env.DV360_ADVERTISER_ID
    ? `https://displayvideo.googleapis.com/v3/advertisers/${env.DV360_ADVERTISER_ID}`
    : `https://displayvideo.googleapis.com/v3/advertisers?partnerId=${env.DV360_PARTNER_ID}&pageSize=1`;

  const dvRes = await httpFetch(dvUrl, { method: 'GET', headers: auth });
  if (!dvRes.ok) {
    const b = await readJson(dvRes);
    const msg = b?.error?.message || b.__nonJson || `HTTP ${dvRes.status}`;
    throw new ProbeError(msg, {
      stage: dvRes.status === 401 ? 'auth' : dvRes.status === 403 ? 'scope' : 'data',
      status: dvRes.status,
      detail: JSON.stringify(b?.error || b).slice(0, 800),
      hint:
        dvRes.status === 403
          ? 'Token likely missing the display-video scope, or no access to this partner/advertiser.'
          : undefined,
    });
  }

  // ── Bid Manager API: confirm the reporting API is reachable (read-only) ──
  const bmRes = await httpFetch(
    'https://doubleclickbidmanager.googleapis.com/v2/queries?pageSize=1',
    { method: 'GET', headers: auth }
  );
  if (!bmRes.ok) {
    const b = await readJson(bmRes);
    const msg = b?.error?.message || b.__nonJson || `HTTP ${bmRes.status}`;
    throw new ProbeError(`Bid Manager (reporting) unreachable: ${msg}`, {
      stage: bmRes.status === 403 ? 'scope' : 'data',
      status: bmRes.status,
      detail: JSON.stringify(b?.error || b).slice(0, 800),
      hint:
        bmRes.status === 403
          ? 'Token likely missing the doubleclickbidmanager scope.'
          : undefined,
    });
  }

  // Both reachable — auth + reporting access confirmed. No spend pulled because
  // that needs a Bid Manager query RUN (a write), which read-only mode skips.
  throw new ProbeError(
    'DV360 + Bid Manager reachable ✓ — spend needs a Bid Manager query run (a write; skipped in read-only probe)',
    { stage: 'data', status: 200 }
  );
}
