// Shared Google OAuth2 refresh-token exchange — used by BOTH Google Ads and
// DV360 (they can even share one OAuth client if it carries both scopes).

import { httpFetch, readJson, form } from './http.js';
import { ProbeError } from './errors.js';

const TOKEN_URL = 'https://oauth2.googleapis.com/token';

/**
 * Exchange a refresh token for a short-lived access token.
 * @returns {Promise<string>} access_token
 * @throws {ProbeError} stage 'auth' on any failure (this IS the auth step).
 */
export async function refreshAccessToken({ clientId, clientSecret, refreshToken }) {
  const res = await httpFetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token',
    }),
    stageOnError: 'auth',
  });

  const body = await readJson(res);
  if (!res.ok || !body.access_token) {
    // e.g. invalid_grant (revoked/expired refresh token), invalid_client
    const code = body.error || `HTTP ${res.status}`;
    throw new ProbeError(`OAuth token refresh failed: ${code}`, {
      stage: 'auth',
      status: res.status,
      detail: body.error_description || body.__nonJson || JSON.stringify(body),
      hint:
        body.error === 'invalid_grant'
          ? 'Refresh token is expired/revoked — re-run the consent flow to mint a new one.'
          : 'Check client_id / client_secret and that the OAuth client is authorized.',
    });
  }
  return body.access_token;
}
