"""Seed configuration for the Bidbrain platform front-door (dashboards.bidbrain.ai).

This is the *source of truth in code*. `seed_registry.py` pushes it into the private GCS registry
JSON (`gs://$GCS_BUCKET/platform.json`) on first standup; after that the admin/super-admin UI edits
the live registry copy (so the running config can diverge from this file — re-seed only
deliberately, with `seed_registry.py --force`).

The platform never stores a row of client data. It stores only:
  - which AGENCIES exist, their login password, and which CLIENTS belong to each;
  - per CLIENT: its dashboard key `<c>`, the friendly subdomain it serves on, its own
    dashboard password (so a single-dashboard login at the platform can resolve it), and
    its CAMPAIGNS (display rows in the admin tree — name + path + the live URL + status).

Passwords here are PLAINTEXT only in this seed file (gitignored from real values via the
`*_PW` env overrides below). `seed_registry.py` hashes them (pbkdf2) before writing to the registry,
and also keeps a recoverable `*_plain` copy there so the super-admin console can reveal them.

Client keys derive everything else (CLAUDE.md "Fixed facts"): dataset `client_<c>`, bucket
`bidbrain-analytics-<c>-dash`, service `<c>-dash`, subdomain `<c>.bidbrain.ai`.
"""
import os

# --- agency + admin passwords (override via env/Secret Manager in production) -------------
# In production these are injected from Secret Manager and the Firestore copy is hashed;
# these literals are the documented defaults the user gave and the local-dev fallback.
ADMIN_PW = os.environ.get("ADMIN_PW", "bidbrain-admin-2026")
# SUPER_ADMIN_PW opens the god-mode console: reveal/rotate EVERY password (agencies, dashboards,
# admin) and open any dashboard. It is injected from Secret Manager `platform-super-admin-password`
# (set up by scripts/enable_super_admin.ps1). It DEFAULTS TO EMPTY ON PURPOSE — never a committed
# literal: when the registry has no super-admin hash yet, resolve_password falls back to comparing
# against this env, so a shipped default would fail OPEN (anyone reading the repo could log in as god).
# Empty => fail CLOSED (no super-admin login until the secret is injected or one is set in the UI).
SUPER_ADMIN_PW = os.environ.get("SUPER_ADMIN_PW", "")
AGENCY_100D_PW = os.environ.get("AGENCY_100D_PW", "100d2026")
AGENCY_TRANSMISSION_PW = os.environ.get("AGENCY_TRANSMISSION_PW", "transmission2026")

# --- Google sign-in (native "Sign in with Google" alongside the password box) --------------
# A user can log in EITHER with a password (above) OR with their Google account. Google login is
# an ADDITIVE second path: it never replaces the password box. The OAuth *Client ID* is public
# (it ships in the login page HTML) — there is no client secret, because we verify Google's signed
# ID token (JWT) server-side against this client ID (the JWT `aud`). Empty => the Google button is
# simply not shown and /auth/google is disabled (password login is unaffected). Create a "Web
# application" OAuth client in the Cloud Console and inject its ID with scripts/enable_google_login.ps1.
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")

# --- Microsoft sign-in (native "Sign in with Microsoft" — Teams/M365 accounts) --------------
# The exact twin of Google above, for the team's Microsoft world (a "Sign in with Teams" login is just
# a Microsoft work/school account). The login page loads MSAL.js and renders a "Sign in with Microsoft"
# button; a popup returns a signed ID token (JWT) which the browser posts to /auth/microsoft, and the
# server verifies it against Microsoft's per-tenant JWKS (no client secret — same public-client model as
# Google) then maps the verified email to a role via the SAME store.resolve_email. Empty CLIENT_ID =>
# the button is hidden and /auth/microsoft is disabled (password + Google login unaffected).
#
# SINGLE-TENANT by design: MICROSOFT_OAUTH_TENANT must be OUR Entra tenant (its GUID, or a verified
# domain like `100.digital` / `<org>.onmicrosoft.com`). It pins BOTH the authority the button talks to
# AND the issuer/`tid` the server accepts — so only accounts in our own organisation can sign in, and a
# work/school UPN is org-controlled (authoritative), which is why no `email_verified` claim is needed
# (Microsoft ID tokens don't carry one). This is what makes the @100.digital domain-auto-admin rule
# below safe over Microsoft too: a foreign tenant can't mint a token our tenant-scoped keys will verify.
# Both are injected by scripts/enable_microsoft_login.ps1 (create the Entra app registration first).
MICROSOFT_OAUTH_CLIENT_ID = os.environ.get("MICROSOFT_OAUTH_CLIENT_ID", "")
MICROSOFT_OAUTH_TENANT = os.environ.get("MICROSOFT_OAUTH_TENANT", "")

# Emails on these domains are granted the ADMIN role AUTOMATICALLY the first time they sign in with
# Google — no super admin has to add them first. On that first login the verified email is written
# into the registry's `users` map (see store.record_domain_admin), so the account then shows up in the
# super-admin console's "Google sign-in access" panel like any other, and can be re-scoped or removed
# there (removing it just re-grants admin on the next login while the domain rule is in force). This is
# only as trustworthy as the domain: it must be a Google Workspace domain the team controls (Google
# verifies domain ownership, and we require `email_verified`), so a stranger can't mint a `@100.digital`
# Google account. Comma-separated env override; default = the 100% Digital team domain. Empty => no
# auto-admin (Google login then works only for explicitly-granted emails, as before).
ADMIN_EMAIL_DOMAINS = [d.strip().lower().lstrip("@")
                       for d in os.environ.get("ADMIN_EMAIL_DOMAINS", "100.digital").split(",")
                       if d.strip()]

# Each dashboard is its own Cloud Run service `<key>-dash`. Until a custom domain is registered
# there are NO `<key>.bidbrain.ai` subdomains — link straight to the live GCP run.app URL
# (deterministic project-number form). The platform is therefore a password-gated LAUNCHER:
# clicking a tile opens that dashboard's OWN login. The seamless "no second password" SSO can't
# work across run.app hosts (run.app is a public-suffix domain, so the shared `.bidbrain.ai`
# cookie cannot apply) — it only switches on once these become https://<key>.<domain>/ behind a
# registered domain (Cloud DNS + Cloud Run domain mappings). Flip _runapp -> a subdomain helper then.
PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER", "516554645957")
REGION = os.environ.get("REGION", "australia-southeast1")


def _runapp(client_key: str) -> str:
    return f"https://{client_key}-dash-{PROJECT_NUMBER}.{REGION}.run.app/"


# --- clients ------------------------------------------------------------------------------
# status: "active"   -> live dashboard, link enabled, SSO-trusted
#         "coming_soon" -> shown in tree, disabled link, no dashboard built yet
# `pw` is the client's OWN dashboard password (mirrors Secret Manager `<c>-dash-password`);
# typing it at the platform login opens just that client. Seeded; rotate in Firestore/secrets.
CLIENTS = {
    "cityperfume": {
        "name": "City Perfume", "slug": "city-perfume", "status": "active",
        "url": _runapp("cityperfume"),
        "campaigns": [
            {"name": "Ads to Sales", "path": "/ads-to-sales", "status": "active"},
        ],
    },
    "vmch": {
        "name": "VMCH", "slug": "vmch", "status": "active",
        "url": _runapp("vmch"),
        "campaigns": [
            {"name": "Brand Awareness", "path": "/brand-awareness", "status": "active"},
        ],
    },
    "tlm": {
        "name": "The Little Marionette", "slug": "the-little-marionette", "status": "active",
        "url": _runapp("tlm"),
        "campaigns": [
            {"name": "Coffee Sales", "path": "/coffee-sales", "status": "active"},
        ],
    },
    "resetdata": {
        "name": "ResetData", "slug": "reset-data", "status": "active",
        "url": _runapp("resetdata"),
        "campaigns": [
            {"name": "Lead Generation", "path": "/lead-generation", "status": "active"},
        ],
    },
    # Onboarding: client_bellshakespeare/ is a built, LIGHT-themed (Bell's white/black/sage brand)
    # placeholder dashboard that renders SAMPLE data behind a "not connected yet" banner. Keep
    # coming_soon until the bellshakespeare-dash service is surfaced; then flip to "active".
    "bellshakespeare": {
        "name": "Bell Shakespeare", "slug": "bell-shakespeare", "status": "coming_soon",
        "url": _runapp("bellshakespeare"),   # deployed preview: super-admin-openable, hidden from clients (coming_soon)
        "note": "Dashboard isn't live yet - the structure is ready.",
        "campaigns": [
            {"name": "Season 2026", "path": "/paid-media", "status": "coming_soon"},
        ],
    },
    "geocon": {
        "name": "Geocon", "slug": "geocon", "status": "coming_soon",
        "url": "",
        "campaigns": [
            {"name": "Campaign", "path": "/campaign", "status": "coming_soon"},
        ],
    },
    # Onboarding (client_caltex/ is a built, Caltex-branded placeholder dashboard that renders SAMPLE
    # data behind a "not connected yet" banner). Keep coming_soon (greyed tile, no dead link) until the
    # caltex-dash service is stood up; then flip status->"active" + url->_runapp("caltex") to surface it.
    "caltex": {
        "name": "Caltex", "slug": "caltex", "status": "coming_soon",
        "url": _runapp("caltex"),   # deployed preview: super-admin-openable, still hidden from clients (coming_soon)
        "note": "Dashboard isn't live yet - the structure is ready.",
        "campaigns": [
            {"name": "Paid Media", "path": "/paid-media", "status": "coming_soon"},
        ],
    },
    # Onboarding: client_nextsmile/ is a built, Next Smile-branded (warm sand + royal blue) placeholder
    # dashboard on SAMPLE data. coming_soon (hidden from clients) but deployed, so super-admin can preview.
    "nextsmile": {
        "name": "Next Smile Australia", "slug": "next-smile", "status": "coming_soon",
        "url": _runapp("nextsmile"),   # deployed preview: super-admin-openable, hidden from clients (coming_soon)
        "note": "Dashboard isn't live yet - the structure is ready.",
        "campaigns": [
            {"name": "Consult Bookings", "path": "/all-on-4", "status": "coming_soon"},
        ],
    },
    "schneider": {
        "name": "Schneider Electric", "slug": "schneider-electric", "status": "active",
        "url": _runapp("schneider"),
        "campaigns": [
            {"name": "Plan vs Actual", "path": "/plan-vs-actual", "status": "active"},
        ],
    },
    "schneiderlqai": {
        "name": "Schneider - Liquid AI Data Center", "slug": "schneider-liquid-ai", "status": "active",
        "url": _runapp("schneiderlqai"),
        "campaigns": [
            {"name": "AI & Liquid Cooling", "path": "/", "status": "active"},
        ],
    },
    "cloudflare": {
        "name": "Cloudflare", "slug": "cloudflare", "status": "active",
        "url": _runapp("cloudflare"),
        "campaigns": [
            {"name": "Always-On Media", "path": "/always-on-media", "status": "active"},
        ],
    },
    "proptrack": {
        "name": "PropTrack", "slug": "proptrack", "status": "active",
        "url": _runapp("proptrack"),
        "campaigns": [
            {"name": "Banking ABM", "path": "/banking-abm", "status": "active"},
        ],
    },
    "mongodb": {
        "name": "MongoDB", "slug": "mongodb", "status": "active",
        "url": _runapp("mongodb"),
        "campaigns": [
            {"name": "Paid Media + CS", "path": "/paid-media", "status": "active"},
        ],
    },
    # NOTE: the meta Pipeline-Status dashboard is no longer a tile here. Its data-sync health and
    # data-accuracy are now shown NATIVELY in the platform's Overview + Data Accuracy tabs (reading
    # the status pipeline's status.json directly). The standalone status-dash web service + the
    # /d/status/ proxy are retired; the status-export job still runs and feeds status.json.
}

# Per-client dashboard passwords (seed only; real values come from `<c>-dash-password`
# secrets / Firestore). A login with one of these opens exactly that client.
CLIENT_PASSWORDS = {
    c: os.environ.get(f"{c.upper()}_DASH_PW", "") for c in CLIENTS
}

# --- agencies -----------------------------------------------------------------------------
AGENCIES = [
    {
        "name": "100% Digital", "slug": "x100-digital", "password": AGENCY_100D_PW,
        "clients": ["cityperfume", "vmch", "tlm", "resetdata", "bellshakespeare", "geocon", "caltex", "nextsmile"],
    },
    {
        "name": "Transmission", "slug": "transmission", "password": AGENCY_TRANSMISSION_PW,
        "clients": ["schneider", "schneiderlqai", "cloudflare", "proptrack", "mongodb", "stt"],
    },
]

# Clients deliberately NOT in any agency (still reachable directly with their own password,
# but never surfaced in an agency portal). HireRight has no assigned agency.
UNASSIGNED_CLIENTS = ["hireright"]

# --- internal tools (NOT client dashboards) -----------------------------------------------
# Shown in a "Tools" group visible ONLY to superadmin + admin (internal 100% Digital staff),
# never to an agency/single-client login — the Grid exposes cross-CLIENT margins.
# The Grid (Central) is the grid-core app (the-grid.html Pulse/Brain/Central/Register/Dashboards).
# Its org-private Cloud Run service `central-grid` (DRS policy forbids allUsers) is proxied with an
# IAM Bearer token (see main.py _tool_headers) ON TOP OF the normal form-login; its password mirrors
# Secret Manager `central-dash-password` (read by _upstream_pw), like any <c>-dash. Staff-only via
# _may_open. (The older `pacing`/pacing-grid tile was retired 2026-07-20 — Central supersedes it.)
TOOLS = {
    "central": {
        "name": "The Grid (Central)", "slug": "central-grid", "status": "active",
        "url": "https://central-grid-p32gk2wuia-ts.a.run.app/",
    },
}

# --- Google-account access (email -> what they can open) ----------------------------------
# A signed-in Google account is matched BY EMAIL against the registry's `users` map (managed live
# in the super-admin console) — exactly like a typed password is matched by `resolve_password`. The
# entries below are the SEED + the permanent baked-in super admin: they always resolve even on a
# pre-existing registry (config fallback in `store.resolve_email`), so you can never lock the super
# admin out, and they are back-filled into the live registry on the first super-admin console load
# so they show up there and the rest become editable.
#   role: "superadmin" | "admin" | "agency" (needs agency_slug) | "client" (needs client_key)
# Emails are matched case-insensitively. Add/assign more accounts in the super-admin console.
USERS = [
    {"email": "ian@100.digital", "role": "superadmin"},
]
