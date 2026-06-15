"""Seed configuration for the Bidbrain platform front-door (dashboards.bidbrain.ai).

This is the *source of truth in code*. `seed_firestore.py` pushes it into Firestore on
first standup; after that the admin UI edits the live Firestore copy (so the running config
can diverge from this file — re-seed only deliberately, with `seed_firestore.py --force`).

The platform never stores a row of client data. It stores only:
  - which AGENCIES exist, their login password, and which CLIENTS belong to each;
  - per CLIENT: its dashboard key `<c>`, the friendly subdomain it serves on, its own
    dashboard password (so a single-dashboard login at the platform can resolve it), and
    its CAMPAIGNS (display rows in the admin tree — name + path + the live URL + status).

Passwords here are PLAINTEXT only in this seed file (gitignored from real values via the
`*_PW` env overrides below). `seed_firestore.py` hashes them before writing to Firestore.

Client keys derive everything else (CLAUDE.md "Fixed facts"): dataset `client_<c>`, bucket
`bidbrain-analytics-<c>-dash`, service `<c>-dash`, subdomain `<c>.bidbrain.ai`.
"""
import os

# --- agency + admin passwords (override via env/Secret Manager in production) -------------
# In production these are injected from Secret Manager and the Firestore copy is hashed;
# these literals are the documented defaults the user gave and the local-dev fallback.
ADMIN_PW = os.environ.get("ADMIN_PW", "bidbrain-admin-2026")
AGENCY_100D_PW = os.environ.get("AGENCY_100D_PW", "100d2026")
AGENCY_TRANSMISSION_PW = os.environ.get("AGENCY_TRANSMISSION_PW", "Transmission2026")

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
    "bellshakespeare": {
        "name": "Bell Shakespeare", "slug": "bell-shakespeare", "status": "coming_soon",
        "url": "",
        "campaigns": [
            {"name": "Campaign", "path": "/campaign", "status": "coming_soon"},
        ],
    },
    "geocon": {
        "name": "Geocon", "slug": "geocon", "status": "coming_soon",
        "url": "",
        "campaigns": [
            {"name": "Campaign", "path": "/campaign", "status": "coming_soon"},
        ],
    },
    "schneider": {
        "name": "Schneider Electric", "slug": "schneider-electric", "status": "active",
        "url": _runapp("schneider"),
        "campaigns": [
            {"name": "Plan vs Actual", "path": "/plan-vs-actual", "status": "active"},
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
        "clients": ["cityperfume", "vmch", "tlm", "resetdata", "bellshakespeare", "geocon"],
    },
    {
        "name": "Transmission", "slug": "transmission", "password": AGENCY_TRANSMISSION_PW,
        "clients": ["schneider", "cloudflare", "proptrack", "mongodb"],
    },
]

# Clients deliberately NOT in any agency (still reachable directly with their own password,
# but never surfaced in an agency portal). STT is on hold; HireRight has no assigned agency.
UNASSIGNED_CLIENTS = ["stt", "hireright"]
