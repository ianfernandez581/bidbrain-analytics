// Structured error so the runner can tell an AUTH failure from a DATA failure
// from an "account team must enable this" failure — that distinction is the
// whole product of this probe.

/**
 * @typedef {'auth'|'data'|'scope'|'enablement'} Stage
 *   auth       – could not even authenticate (bad/expired creds, wrong client) → RED
 *   scope      – authenticated, but the token lacks the reporting scope        → YELLOW
 *   data       – authenticated + scoped, but the report call failed / no rows  → YELLOW
 *   enablement – blocked pending an account-team / rep action (e.g. TTD)       → RED
 */

export class ProbeError extends Error {
  /**
   * @param {string} message  short, human-readable
   * @param {{stage?: Stage, detail?: string, hint?: string, status?: number}} [opts]
   */
  constructor(message, { stage = 'data', detail, hint, status } = {}) {
    super(message);
    this.name = 'ProbeError';
    this.stage = stage;
    this.detail = detail;   // raw provider error text, for --verbose
    this.hint = hint;       // what the operator should do next
    this.status = status;   // HTTP status, if any
  }
}

/** Did we get past authentication? auth-stage failures are the only "no". */
export function authOk(err) {
  return !(err instanceof ProbeError) || err.stage !== 'auth';
}
