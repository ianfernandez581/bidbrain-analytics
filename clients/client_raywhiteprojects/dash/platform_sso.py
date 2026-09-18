"""Cross-subdomain SSO token — shared by the platform (issuer) and every dashboard (verifier).

This exact file is VENDORED into each `clients/client_<c>/dash/` folder (like `freshness.py` /
`sf_connect`), so the encode side (platform) and the verify side (dashboards) can never drift.

Model
-----
A dashboard is normally unlocked by its OWN password (`session["ok"]=True`). In ADDITION, the
front-door at dashboards.bidbrain.ai may issue a signed `bb_sso` cookie, scoped to the shared
parent domain `.bidbrain.ai`, that lists the client keys the visitor's agency is allowed to
open. A dashboard trusts that cookie iff THIS client key is in the list and the signature +
age check pass. The dashboard's own password always remains a valid fallback.

It is deliberately fail-closed and dependency-light:
  - returns False on any missing / invalid / expired cookie, or missing env — so a dashboard
    deployed before SSO is wired keeps working on its own password and never crashes;
  - signs with itsdangerous (bundled with Flask) — no new dependency;
  - never raises into the request path.

Env injected by the deploy (dashboard side):
  SSO_SECRET   shared signing key (Secret Manager: `platform-sso-key`) — the SAME value the
               platform signs with. If unset, SSO is simply inert.
  CLIENT_KEY   this dashboard's key, e.g. "cityperfume".
  SSO_MAX_AGE  optional seconds (default 43200 = 12h); must match the platform's cookie age.
"""
import os

COOKIE_NAME = "bb_sso"
_SALT = "bidbrain-platform-sso-v1"
DEFAULT_MAX_AGE = 60 * 60 * 12  # 12h — matches the dashboards' PERMANENT_SESSION_LIFETIME


def _serializer(secret):
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(secret, salt=_SALT)


def encode(secret, allowed):
    """Platform side: sign the allow-list into a compact, tamper-evident, timed token."""
    return _serializer(secret).dumps({"allowed": list(allowed)})


def decode(secret, token, max_age=DEFAULT_MAX_AGE):
    """Raises itsdangerous.BadSignature / SignatureExpired on a bad or stale token."""
    return _serializer(secret).loads(token, max_age=max_age)


def sso_allows(request) -> bool:
    """Dashboard side: True iff a valid platform cookie grants THIS client (env CLIENT_KEY)."""
    secret = os.environ.get("SSO_SECRET")
    client_key = os.environ.get("CLIENT_KEY")
    if not secret or not client_key:
        return False
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        max_age = int(os.environ.get("SSO_MAX_AGE", str(DEFAULT_MAX_AGE)))
        data = decode(secret, token, max_age)
    except Exception:
        return False
    allowed = data.get("allowed") if isinstance(data, dict) else None
    return isinstance(allowed, list) and client_key in allowed
