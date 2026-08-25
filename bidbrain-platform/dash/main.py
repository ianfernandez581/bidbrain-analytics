"""Bidbrain Campaign Dashboards — the front-door platform (dashboards.bidbrain.ai).

ONE password box, four outcomes (resolved against the private GCS registry JSON by
`store.resolve_password`):
  - an AGENCY password  -> a portal of every dashboard in that agency; clicking any opens it
                           with NO further password (a `bb_sso` cookie pre-authorises them).
  - a single DASHBOARD password -> straight to that one dashboard.
  - the ADMIN password  -> the editable admin tree (the screenshot): agencies -> clients ->
                           campaigns, add/edit/remove, persisted to the registry.
  - the SUPER-ADMIN password -> the god-mode console: reveal AND rotate every password (agencies,
                           dashboards, admin) + open any dashboard. See templates/superadmin.html.

How "no second password" works: a REVERSE PROXY. Because the dashboards live on raw `*.run.app`
(a public-suffix domain where a shared SSO cookie can't apply), the platform serves each dashboard
UNDER ITS OWN ORIGIN at `/d/<client>/`. It logs into the upstream `<c>-dash` service once
(server-side, with that dashboard's own password from Secret Manager) and proxies the dashboard
through — so once you're past the platform's single login, the dashboards just open. Per-agency
scoping is enforced on `/d/<client>/` (a 100% Digital session can't open Transmission's clients).
The registry (agencies/clients/campaigns + hashed passwords) is a private JSON in GCS.

(The `bb_sso` cookie / vendored `platform_sso.py` are also in place — they take over automatically
if a real domain is ever wired and the dashboards move to `<c>.<domain>/`; inert on run.app.)

Serving pattern mirrors every other dash in this repo: thin Flask gate, gunicorn, no-store,
private by default, deployed with --no-invoker-iam-check so this app's gate is the only door.
"""
import os
import re
import time
import base64
from pathlib import Path

import requests
from flask import (
    Flask, request, redirect, session, render_template, render_template_string,
    abort, jsonify, make_response, Response
)

import config as cfg
import platform_sso
import feedback
import feedback_ai
import feedback_loop_data
import internal_notes
import internal_chat
from store import Store, verify_pw, is_external, agency_setting

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]            # platform's own session (separate from SSO)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("DEV") != "1",
    SESSION_COOKIE_SAMESITE="Lax",                       # platform is top-level, not iframed
    PERMANENT_SESSION_LIFETIME=platform_sso.DEFAULT_MAX_AGE,
    # Bound request bodies. The only sizeable one is a feedback submission (a voice note capped
    # ~16 MB plus an optional JPEG screenshot); the proxy's forwarded POSTs (login, the mongodb
    # /report) are all tiny.
    MAX_CONTENT_LENGTH=feedback.MAX_AUDIO_BYTES + feedback.MAX_IMAGE_BYTES + 256 * 1024,
)

# --- config injected by Cloud Run ---------------------------------------------------------
SSO_SECRET = os.environ["SSO_SECRET"]                    # shared with every dashboard
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", ".bidbrain.ai")  # parent domain so the cookie spans subdomains
_SECURE = os.environ.get("DEV") != "1"

# Logo + Flask templates are baked into the container next to this file.
_HERE = Path(__file__).resolve().parent
LOGO_SVG = ""
try:
    LOGO_SVG = (_HERE / "logo.svg").read_text(encoding="utf-8")
except FileNotFoundError:
    LOGO_SVG = "<span style='font-weight:800'>Bidbrain.ai</span>"

# Brand favicon — the official Bidbrain mark (brain + gavel), generated from
# Creatives/Bid Brain Logo.png and baked in next to this file. Loaded once into memory and
# served PUBLICLY (no auth) at the well-known icon paths so the tab/bookmark shows it on every
# platform page — and on any proxied dashboard that doesn't set its own icon.
def _read_icon(name):
    try:
        return (_HERE / name).read_bytes()
    except OSError:
        return b""

FAVICON_ICO = _read_icon("favicon.ico")
FAVICON_PNG = _read_icon("favicon-32.png")
APPLE_ICON = _read_icon("apple-touch-icon.png")

store = Store()

# Clients whose dashboards ship the AI "Download slides" pipeline (report.py + /report + the headless
# ?bbslides=1 bootstrap + bb_deck.js). The agency portal shows a per-client "Download slides" button for
# these (only these — others have no generator). Extend as new clients gain the pipeline.
SLIDES_CLIENTS = {"mongodb", "cloudflare", "schneider", "proptrack", "geocon", "schneiderlqai", "caltex"}

# --- Google sign-in (GIS button + ID-token verification) — a PARALLEL login to the password gate --
# The login page renders Google's button; the browser posts a signed ID token (JWT) to /auth/google
# (same-origin fetch). We verify it against this PUBLIC OAuth client id (the JWT `aud`) — no client
# secret, no redirect flow — then map the VERIFIED email to a role via store.resolve_email and set the
# SAME session the password flow sets (_establish_session). Empty client id => button hidden, route
# inert; the password login is completely unaffected. Injected by scripts/enable_google_login.ps1.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "") or getattr(cfg, "GOOGLE_OAUTH_CLIENT_ID", "")

# --- Microsoft sign-in (MSAL.js popup + ID-token verification) — twin of the Google path above -----
# The login page loads MSAL.js and shows a "Sign in with Microsoft" button; the popup returns a signed
# ID token (JWT) which the browser posts to /auth/microsoft (same-origin fetch). We verify it against
# Microsoft's per-tenant JWKS and map the VERIFIED email to a role via the SAME store.resolve_email +
# _establish_session. SINGLE-TENANT: TENANT pins the authority + the accepted issuer/`tid`, so only our
# own org's accounts can sign in. Both empty => button hidden, route inert; passwords + Google unaffected.
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_OAUTH_CLIENT_ID", "") or getattr(cfg, "MICROSOFT_OAUTH_CLIENT_ID", "")
MICROSOFT_TENANT = os.environ.get("MICROSOFT_OAUTH_TENANT", "") or getattr(cfg, "MICROSOFT_OAUTH_TENANT", "")
# Microsoft login is live only when BOTH are set (single-tenant needs the tenant).
MICROSOFT_ENABLED = bool(MICROSOFT_CLIENT_ID and MICROSOFT_TENANT)
_MS_JWKS_CLIENT = None   # lazily-built, cached jwt.PyJWKClient (fetches + caches the tenant's signing keys)


# --- Local-run safety: never mutate PRODUCTION from a laptop -------------------------------
# A local run (DEV=1) still authenticates with REAL application-default credentials and reads
# REAL buckets/secrets — so a state-changing call (a Cloud Run `jobs:run`, a definitions write,
# a password rotation) reaches PRODUCTION exactly as it would from the deployed service. That is
# how a routine endpoint probe once fired seven live export jobs. Every such call now routes
# through _prod_mutation_blocked() and FAILS LOUDLY on a local run.
#   - Blocks: triggering export/deploy jobs, writing staged definitions, rotating passwords,
#     uploading logos, saving feedback — i.e. anything that writes outside this process.
#   - Does NOT block: reads. A local run still shows live data (that is what makes it useful for
#     review), so treat anything you SEE locally as production truth.
#   - Deliberate override for a real operator task: ALLOW_PROD_MUTATIONS=1.
_LOCAL_RUN = os.environ.get("DEV") == "1"
_ALLOW_PROD_MUTATIONS = os.environ.get("ALLOW_PROD_MUTATIONS") == "1"


def _prod_mutation_blocked(what):
    """Return a 503 response when a local run must not mutate production, else None."""
    if _LOCAL_RUN and not _ALLOW_PROD_MUTATIONS:
        app.logger.error("BLOCKED production mutation from a local run: %s", what)
        return jsonify(
            ok=False, blocked=True,
            error=(f"Blocked: '{what}' would change PRODUCTION from a local run. "
                   "Re-run with ALLOW_PROD_MUTATIONS=1 only if that is genuinely intended."),
        ), 503
    return None


@app.after_request
def _no_store(resp):
    """Never cache. The proxy already sets this per-response; here it also covers the super-admin
    console and admin tree, whose HTML embeds cleartext passwords — they must not land in a browser
    disk cache or any intermediary. Don't clobber a header a view set deliberately."""
    resp.headers.setdefault("Cache-Control", "no-store")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


# Per-agency logos shown on that agency's portal (loaded once, inlined). `light=True` means the
# mark needs a light backing on the dark theme (e.g. a green-on-white raster); white/transparent
# marks render plain. Drop an `agency_<slug>.svg`/`.jpg`/`.png` next to this file to add more.
def _load_agency_logos():
    here = Path(__file__).resolve().parent
    logos = {}
    for f in here.glob("agency_*"):
        slug = f.stem[len("agency_"):]
        try:
            if f.suffix == ".svg":
                logos[slug] = {"html": f.read_text(encoding="utf-8"), "light": False}
            elif f.suffix in (".jpg", ".jpeg", ".png"):
                mime = "png" if f.suffix == ".png" else "jpeg"
                b64 = base64.b64encode(f.read_bytes()).decode()
                # PNGs are treated as transparent dark-theme marks (render plain, no white backing);
                # JPGs are opaque logos-on-white, so they get the light chip.
                logos[slug] = {"html": f'<img src="data:image/{mime};base64,{b64}" alt="">',
                               "light": f.suffix != ".png"}
        except OSError:
            pass
    return logos


AGENCY_LOGOS = _load_agency_logos()


# Per-CLIENT logos shipped in the repo, inlined into the portal tiles. Separate from the
# admin-uploaded `/logo/<client>` route (which reads the GCS bucket and stays untouched): these are
# committed assets, so a portal never depends on someone having uploaded one. Drop a
# `clientlogo_<key>.png/.svg/.jpg` beside this file and the Dockerfile's wildcard ships it.
# A client with NO file simply isn't in the map, and the template falls back to its text name -
# there is never an empty tile header.
def _load_client_logos():
    here = Path(__file__).resolve().parent
    logos = {}
    for f in here.glob("clientlogo_*"):
        key = f.stem[len("clientlogo_"):]
        try:
            if f.suffix == ".svg":
                logos[key] = {"svg": f.read_text(encoding="utf-8")}
            elif f.suffix in (".jpg", ".jpeg", ".png"):
                mime = "png" if f.suffix == ".png" else "jpeg"
                logos[key] = {"src": f"data:image/{mime};base64,"
                                     + base64.b64encode(f.read_bytes()).decode()}
        except OSError:
            pass
    return logos


CLIENT_LOGOS = _load_client_logos()


# --- Per-agency portal THEME (presentation only) --------------------------------------------
# PURELY COSMETIC: a token map the portal template paints into a scoped <style> override. An agency
# with NO entry here gets NO override block emitted at all, so every other portal renders
# byte-for-byte as before. Nothing here touches routing, auth, payloads or the registry.
#
# `header_logo` swaps the "Bidbrain.ai · Campaign Dashboards" lockup for the agency's own mark in
# the top bar (the pre-existing AGENCY_LOGOS slot is the page HERO, not the header - see the note
# in the re-skin write-up).
# `powered_by` renders a quiet "Powered by Bidbrain" line at the foot of the page; it is the
# platform's attribution once the Bidbrain lockup leaves the header. FLAGGED FOR CONFIRMATION.
#
# Semantic colours are deliberately ABSENT from this map: ACTIVE badges and health chips stay
# green because they carry meaning, not decoration.
AGENCY_THEMES = {
    "extrablack": {
        "bg": "#060606",            # page ground
        "panel": "#0e0d0c",         # card surface
        "panel_2": "#131110",
        "border": "rgba(255,255,255,.08)",
        "border_strong": "rgba(255,255,255,.16)",
        "text": "#f5f2ec",
        "muted": "rgba(245,242,236,.56)",
        "accent": "#ffa02e",        # active tab underline, hover border, focus ring
        "accent_deep": "#ff6a00",
        "cream": "#fff6ea",         # primary actions
        "chip_bg": "#141110",
        "chip_text": "rgba(245,242,236,.56)",
        "topbar": "#0a0908",
        "tile_hover": "#151211",
        "font": "'Helvetica Neue', Helvetica, -apple-system, 'Segoe UI', Arial, sans-serif",
        "header_logo": "extrablack",
        "powered_by": True,
    },
}


# Admin-tree ONLY agency badges — the black-background marks, shown on a dark square tile in the
# accordion header. Deliberately SEPARATE from AGENCY_LOGOS (the portal's) so the admin page can use
# a different, badge-shaped logo without changing the portal. Drop an `admlogo_<slug>.svg/.jpg/.png`
# next to this file. No `light` flag — these already sit on their own dark ground.
def _load_admin_agency_logos():
    here = Path(__file__).resolve().parent
    logos = {}
    for f in here.glob("admlogo_*"):
        slug = f.stem[len("admlogo_"):]
        try:
            if f.suffix == ".svg":
                logos[slug] = f.read_text(encoding="utf-8")
            elif f.suffix in (".jpg", ".jpeg", ".png"):
                mime = "png" if f.suffix == ".png" else "jpeg"
                b64 = base64.b64encode(f.read_bytes()).decode()
                logos[slug] = f'<img src="data:image/{mime};base64,{b64}" alt="">'
        except OSError:
            pass
    return logos


ADMIN_AGENCY_LOGOS = _load_admin_agency_logos()


# --- SSO cookie helpers -------------------------------------------------------------------
def _set_sso(resp, allowed):
    """Attach the signed cross-subdomain allow-list cookie to a response."""
    token = platform_sso.encode(SSO_SECRET, allowed)
    resp.set_cookie(
        platform_sso.COOKIE_NAME, token,
        max_age=platform_sso.DEFAULT_MAX_AGE,
        domain=COOKIE_DOMAIN or None, path="/",
        secure=_SECURE, httponly=True, samesite="None" if _SECURE else "Lax",
    )
    return resp


def _clear_sso(resp):
    resp.set_cookie(platform_sso.COOKIE_NAME, "", expires=0,
                    domain=COOKIE_DOMAIN or None, path="/")
    return resp


# ── EXTERNAL tenants: deny every route by default ──────────────────────────────────────────
# An external agency (store.is_external) may reach ONLY the endpoints named here. This is keyed on
# Flask ENDPOINT NAMES (the view function), not URL strings, so a route added in future is CLOSED
# to external tenants until someone deliberately adds it to this set — unknown surface is shut by
# construction rather than by remembering to gate it. Every denial is logged.
#
# What is permitted, and why: the branded login, the portal shell, the Data Accuracy data
# (/api/status, already scoped to the session's own clients), their own clients' logos, the
# proxied dashboards for their own clients (the proxy independently enforces _may_open), logout,
# and the public health/icon routes.
_EXTERNAL_ALLOWED_ENDPOINTS = frozenset({
    "home", "logout", "healthz", "static",
    "login", "extrablack_login_form", "extrablack_login", "auth_google", "auth_microsoft",
    "api_status", "client_logo", "proxy",
    "favicon_ico", "favicon_png", "apple_touch_icon",
})

# Proxy sub-paths an external tenant may NOT request on a dashboard it can otherwise open.
# `report` runs the paid AI deck generator server-side; the button is already suppressed for
# external tenants, and this closes the direct call behind it.
_EXTERNAL_BLOCKED_SUBPATHS = frozenset({"report"})


def _session_agency():
    """The registry agency dict for an agency session, else None (admin/super/client/anon)."""
    if session.get("kind") != "agency":
        return None
    return store.get_agency(session.get("agency_slug", ""))


def _is_external_session():
    return is_external(_session_agency())


def _ext_setting(name):
    """Resolve a per-agency setting for the CURRENT session. Admin/super/client sessions and
    internal agencies resolve to today's (permissive) behaviour."""
    return agency_setting(_session_agency(), name)


@app.before_request
def _external_deny_by_default():
    a = _session_agency()
    if not is_external(a):
        return None                      # internal agency / admin / client / anonymous: unchanged
    ep = request.endpoint or ""
    if ep in _EXTERNAL_ALLOWED_ENDPOINTS:
        return None
    app.logger.warning("external-deny agency=%s endpoint=%s method=%s path=%s",
                       a.get("slug"), ep or "<unmatched>", request.method, request.path)
    return jsonify(ok=False, error="Not available for this account."), 403


def _require_admin():
    # super admin can do everything an admin can (and more)
    if session.get("kind") not in ("admin", "superadmin"):
        abort(403)


def _require_super():
    if session.get("kind") != "superadmin":
        abort(403)


# --- views --------------------------------------------------------------------------------
def _login_page(error=None):
    """Render the login screen (also tells the template whether to show the Google/Microsoft buttons)."""
    return render_template("login.html", logo_svg=LOGO_SVG, error=error, next_url="",
                           google_client_id=GOOGLE_CLIENT_ID,
                           ms_client_id=MICROSOFT_CLIENT_ID if MICROSOFT_ENABLED else "",
                           ms_tenant=MICROSOFT_TENANT if MICROSOFT_ENABLED else "")


def _safe_next(raw):
    """The login form's hidden 'next' deep link. Returned ONLY when it is a same-origin relative
    path: a single leading '/' (never '//', which browsers treat as scheme-relative host escape),
    no backslashes, no control chars (CR/LF header splitting). A scheme ('https:', 'javascript:')
    can't survive the leading-'/' rule. Anything else -> None, the role-based redirect stands."""
    nxt = (raw or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        return None
    if "\\" in nxt or any(ord(ch) < 0x20 for ch in nxt):
        return None
    return nxt


def _establish_session(kind, payload, json_mode=False, next_path=None):
    """Set the session for a resolved login and return the response with the SSO cookie. The SINGLE
    place that turns a (kind, payload) — from EITHER store.resolve_password or store.resolve_email —
    into a logged-in session, so password and Google sign-in are identical from here on. json_mode
    returns {ok, next} JSON (for the same-origin Google fetch); otherwise a 302 (password form POST).
    next_path, when given, MUST already be validated via _safe_next; it overrides the role redirect."""
    session.clear()
    session.permanent = True
    if kind in ("admin", "superadmin"):
        session["kind"] = kind
        allowed = store.active_client_keys()  # every LIVE dashboard (incl. unassigned, excl. coming_soon)
        nxt = "/"
    elif kind == "agency":
        session["kind"] = "agency"
        session["agency_slug"] = payload["slug"]
        allowed = list(payload.get("client_keys", []))
        nxt = "/"
    else:  # single dashboard -> straight into the proxied dashboard
        session["kind"] = "client"
        session["client_key"] = payload["key"]
        allowed = [payload["key"]]
        nxt = f"/d/{payload['key']}/"
    if next_path:
        nxt = next_path   # pre-validated same-origin deep link (see _safe_next)
    resp = make_response(jsonify(ok=True, next=nxt) if json_mode else redirect(nxt))
    return _set_sso(resp, allowed)


# ── Feedback Loop (Transmission-only portal tab) ─────────────────────────────────────────────
# The pane renders INLINE in portal.html (templates/_feedback_loop_pane.html, a sibling .bbpane —
# not an iframe), so the portal's background, cursor glow and hover feel run across it unbroken.
# Canonical source is prototypes/transmission-feedback-v0/; re-vendor with its
# make_portal_template.py after any edit. The template carries a __FEEDBACK_DATA_JSON__ sentinel
# that this fills at request time; it is a no-op for any agency whose portal omits the pane.
# The data is READ LIVE from the compilation sheet on request (feedback_loop_data.load_json:
# CSV export -> the pane's contract, cached ~60s per instance, last-known-good mirrored to
# gs://<platform bucket>/feedback-loop/data.json). Client verbatims therefore never enter git.
# The vendored sample file is the LAST resort only - it flies the amber SAMPLE DATA pill, so a
# reader can always tell a degraded pane from a real one. `?fbl=fresh` bypasses the cache.
FEEDBACK_LOOP_AGENCY = "transmission"     # the one portal that carries the tab today


def _feedback_loop_flags(agency):
    """The three template flags behind the tab, resolved in ONE place so the gate, the button and
    the button's state can never disagree:

      show_feedback_loop   render the tab + pane at all (staff always; the agency only when the
                           `feedback_loop` setting is on). This is the real gate - the pane is
                           inlined into the page, so a merely hidden tab would still leak the
                           verbatims into view source, and skipping the include also means the
                           sheet is never read for that session.
      fbl_can_toggle       show the staff visibility button (100% Digital admin/super-admin only,
                           incl. while viewing the portal via /enter-agency).
      fbl_agency_visible   what that button currently reads, i.e. can the agency's own login see it.
    """
    staff = _admin_kind() in ("admin", "superadmin")
    visible_to_agency = agency_setting(agency, "feedback_loop")
    return {
        "show_feedback_loop": (agency["slug"] == FEEDBACK_LOOP_AGENCY
                               and (staff or visible_to_agency)),
        "fbl_can_toggle": staff,
        "fbl_agency_visible": bool(visible_to_agency),
    }


@app.post("/admin/api/feedback-loop-visibility")
def api_feedback_loop_visibility():
    """Turn the Feedback Loop tab on/off for the AGENCY's own login. 100% Digital staff only -
    and `_admin_kind()`, not `_require_admin()`, because the button is clicked from inside the
    agency portal, where session["kind"] is "agency" for the duration of the visit."""
    if _admin_kind() not in ("admin", "superadmin"):
        abort(403)
    d = request.get_json(silent=True) or {}
    slug = (d.get("slug") or FEEDBACK_LOOP_AGENCY).strip()
    visible = bool(d.get("visible"))
    try:
        stored = store.set_agency_setting(slug, "feedback_loop", visible)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    if stored is None:
        return jsonify(ok=False, error="Unknown agency '%s'." % slug), 404
    app.logger.info("feedback-loop: visibility for %s set to %s by %s",
                    slug, stored, _admin_kind())
    return jsonify(ok=True, visible=stored)


def _fill_feedback_loop(page):
    if "__FEEDBACK_DATA_JSON__" not in page:
        return page
    force = False
    try:
        force = request.args.get("fbl") == "fresh"
    except Exception:
        pass
    data_json, source = feedback_loop_data.load_json(force=force)
    if data_json:
        app.logger.info("feedback-loop: served from %s", source)
    else:
        app.logger.error("feedback-loop: live read failed (%s) - falling back to sample", source)
        data_json = (_HERE / "templates" / "feedback_loop_sample.json").read_text(encoding="utf-8")
    # "</" is escaped so untrusted text inside the JSON can never close the <script> block early
    return page.replace("__FEEDBACK_DATA_JSON__", data_json.replace("</", "<\\/"))


def _tools_tiles():
    """The internal-tools tile list (config.TOOLS) for the admin tree + super-admin console.
    Empty unless TOOLS is populated, so the '{% if tools %}' block stays hidden otherwise."""
    return [{"key": k, "name": v.get("name", k)}
            for k, v in getattr(cfg, "TOOLS", {}).items() if v.get("status") == "active"]


@app.get("/")
def home():
    kind = session.get("kind")
    if kind == "superadmin":
        return _render_super()
    if kind == "admin":
        st = store.get_state()
        return render_template("admin.html", logo_svg=LOGO_SVG, is_super=False,
                               agency_logos=ADMIN_AGENCY_LOGOS, tools=_tools_tiles(), **st)
    if kind == "agency":
        agency = store.get_agency(session.get("agency_slug", ""))
        if not agency:
            session.clear()
            return _login_page()
        clients = store.agency_clients(agency)
        page = render_template("portal.html", logo_svg=LOGO_SVG,
                               agency={"name": agency["name"], "slug": agency["slug"]},
                               agency_logo=AGENCY_LOGOS.get(agency["slug"]),
                               clients=clients,
                               # AI deck generator: suppressed for external tenants (paid runs,
                               # and it writes narrative commentary in our voice). Empty list =>
                               # the button renders for no client.
                               slides_clients=(list(SLIDES_CLIENTS)
                                               if agency_setting(agency, "show_slides") else []),
                               google_client_id=GOOGLE_CLIENT_ID,
                               # Per-agency settings resolved by agency TYPE (store.agency_setting):
                               # internal agencies get today's values; an `external` agency gets the
                               # restrictive ones - no sync trigger, no Grid/Brain tabs (and no
                               # pacing snapshot in the page source).
                               show_sync=agency_setting(agency, "show_sync"),
                               show_grid_brain=agency_setting(agency, "show_grid_brain"),
                               # Cosmetic per-agency theme (AGENCY_THEMES). None for every agency
                               # without an entry, and the template then emits NO override block -
                               # so those portals are byte-identical to before.
                               theme=AGENCY_THEMES.get(agency["slug"]),
                               # Committed per-client marks for the tiles; a client without one
                               # falls back to its text name in the template.
                               client_logos=CLIENT_LOGOS,
                               # Feedback Loop. The registry is a candid record of what went wrong
                               # on whose reports, so 100% Digital staff ALWAYS see it (any admin/
                               # super-admin viewing this portal via /enter-agency) while the
                               # agency's OWN login sees it only while the `feedback_loop` setting
                               # is on - default off for an external agency, flipped from the
                               # button in the tab itself (/admin/api/feedback-loop-visibility).
                               **_feedback_loop_flags(agency),
                               admin_return=session.get("admin_return"))
        return _fill_feedback_loop(page)
    if kind == "client":
        key = session.get("client_key")
        if key:
            return redirect(f"/d/{key}/")
        session.clear()
    return _login_page()


@app.post("/login")
def login():
    pw = request.form.get("password", "")
    kind, payload = store.resolve_password(pw)
    if kind is None:
        return _login_page("Incorrect password."), 401
    return _establish_session(kind, payload,
                              next_path=_safe_next(request.form.get("next", "")))


# ── Extrablack branded login (dashboards.bidbrain.ai/extrablack) ────────────────────────────
# A SEPARATE, fully-branded login page for the Extrablack agency (black field / amber glow /
# services rail, per the approved concept mock). It verifies the typed password against ONLY the
# extrablack agency's registry hash — never resolve_password — so a Transmission/admin password
# typed here is rejected rather than silently opening a different tier. A correct password
# establishes the exact same agency session the main login would (_establish_session), so the
# portal, /api/status scoping and the /d/<client>/ proxy behave identically from there on.
# Google sign-in for Extrablack rides the MAIN login page via the agency `google_allowlist`
# (store.resolve_email) once emails are added — this page stays password-only by design.
def _extrablack_login_page(error=None, status=200):
    resp = make_response(render_template("extrablack_login.html", error=error), status)
    # Belt-and-braces with the page's own <meta name="robots">: this URL is public and, being
    # named for the tenant, is guessable. Keep it out of search indexes entirely.
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return resp


# --- failed-login throttle for /extrablack --------------------------------------------------
# One shared password guards an outside company's portal on a public URL, so unlimited guessing
# is the wrong default. After _LOGIN_MAX_FAILS failures from one IP inside _LOGIN_WINDOW, that IP
# is locked out for _LOGIN_LOCKOUT and every attempt is logged.
#
# LIMITS, STATED PLAINLY: this counter is per PROCESS and in memory. Cloud Run runs several
# instances, so the effective limit is (instances x _LOGIN_MAX_FAILS), and a restart clears it.
# It stops casual and scripted guessing; it is NOT a substitute for edge rate-limiting
# (Cloudflare WAF on dashboards.bidbrain.ai), which remains the real control.
_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW = 15 * 60
_LOGIN_LOCKOUT = 15 * 60
_login_fails = {}          # ip -> [count, window_started_at, locked_until]


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "?"


def _login_locked(ip):
    """Seconds remaining on a lockout, or 0."""
    rec = _login_fails.get(ip)
    if not rec:
        return 0
    now = time.time()
    if rec[2] > now:
        return int(rec[2] - now)
    if now - rec[1] > _LOGIN_WINDOW:      # window elapsed with no lockout -> forget it
        _login_fails.pop(ip, None)
    return 0


def _login_note_failure(ip):
    now = time.time()
    rec = _login_fails.get(ip)
    if not rec or now - rec[1] > _LOGIN_WINDOW:
        rec = [0, now, 0.0]
    rec[0] += 1
    if rec[0] >= _LOGIN_MAX_FAILS:
        rec[2] = now + _LOGIN_LOCKOUT
        app.logger.warning("extrablack login LOCKED OUT ip=%s after %d failures", ip, rec[0])
    else:
        app.logger.warning("extrablack login failed ip=%s (%d/%d in window)",
                           ip, rec[0], _LOGIN_MAX_FAILS)
    _login_fails[ip] = rec


def _extrablack_login_page_locked(secs):
    mins = max(1, secs // 60)
    return _extrablack_login_page(
        f"Too many incorrect attempts. Try again in about {mins} minute"
        f"{'' if mins == 1 else 's'}.", status=429)


@app.get("/extrablack")
def extrablack_login_form():
    if session.get("kind") == "agency" and session.get("agency_slug") == "extrablack":
        return redirect("/")
    return _extrablack_login_page()


@app.post("/extrablack")
def extrablack_login():
    ip = _client_ip()
    locked = _login_locked(ip)
    if locked:
        app.logger.warning("extrablack login attempt while locked out ip=%s", ip)
        return _extrablack_login_page_locked(locked)
    pw = request.form.get("password", "")
    a = store.get_agency("extrablack")
    # Fail closed: no agency, no stored hash (password never set), or a wrong password all land
    # on the same message. verify_pw rejects an empty stored hash, so an unconfigured agency can
    # never be opened with an empty/any password.
    if not (a and pw and verify_pw(pw, a.get("password_hash", ""))):
        _login_note_failure(ip)
        if _login_locked(ip):
            return _extrablack_login_page_locked(_LOGIN_LOCKOUT)
        return _extrablack_login_page("Incorrect password.", status=401)
    _login_fails.pop(ip, None)           # clean slate on success
    app.logger.info("extrablack login ok ip=%s", ip)
    return _establish_session("agency", a)


@app.post("/auth/google")
def auth_google():
    """Native 'Sign in with Google'. The browser GIS button posts a signed ID token (JWT) here via a
    same-origin fetch; we verify it against our OAuth client id, then map the VERIFIED email to a role
    with store.resolve_email (same outcomes as a password). Additive — the password box still works."""
    if not GOOGLE_CLIENT_ID:
        return jsonify(ok=False, error="Google sign-in is not configured."), 400
    token = ((request.get_json(silent=True) or {}).get("credential") or "").strip()
    if not token:
        return jsonify(ok=False, error="Missing Google credential."), 400
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as ga_requests
        info = id_token.verify_oauth2_token(token, ga_requests.Request(), GOOGLE_CLIENT_ID,
                                             clock_skew_in_seconds=10)
    except Exception as e:   # malformed/expired token, wrong aud, clock skew, certs fetch fail, …
        app.logger.warning("google id_token verification failed: %s", e)
        return jsonify(ok=False, error="Could not verify your Google sign-in."), 401
    if not info.get("email") or not info.get("email_verified"):
        return jsonify(ok=False, error="Your Google account has no verified email."), 401
    email = info["email"].strip().lower()
    try:
        store.record_domain_admin(email)   # @100.digital (config.ADMIN_EMAIL_DOMAINS) -> auto-enrolled
                                           # as admin & recorded in the console; no-op otherwise.
    except Exception as e:  # best-effort: resolve_email's domain fallback grants admin from a pure read,
                            # so a transient registry-write error must NOT fail the login (just isn't recorded).
        app.logger.warning("record_domain_admin failed for %s (continuing): %s", email, e)
    kind, payload = store.resolve_email(email)
    if kind is None:
        return jsonify(ok=False,
                       error=f"{email} isn’t authorised yet. Ask an admin to grant your account access."), 403
    resp = _establish_session(kind, payload, json_mode=True)
    session["email"] = email   # persisted with the session cookie at response time (audit/display)
    return resp


def _verify_ms_id_token(token):
    """Verify a Microsoft ID token (JWT) for OUR single tenant and return its claims, or raise.

    Twin of google-auth's verify_oauth2_token: checks the RS256 signature against the tenant's JWKS,
    the audience (our client id) and expiry, then pins the tenant — `iss` must be this token's own
    `https://login.microsoftonline.com/{tid}/v2.0` and, when TENANT is a GUID, `tid` must equal it.
    Because the JWKS endpoint is tenant-scoped, a foreign tenant's token can't be signed by these keys
    at all; the explicit iss/tid checks are belt-and-braces so a misconfig can't widen the audience."""
    global _MS_JWKS_CLIENT
    import jwt   # PyJWT[crypto] — lazy so an idle container never imports it
    if _MS_JWKS_CLIENT is None:
        _MS_JWKS_CLIENT = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/discovery/v2.0/keys")
    signing_key = _MS_JWKS_CLIENT.get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, signing_key, algorithms=["RS256"], audience=MICROSOFT_CLIENT_ID,
                        leeway=10, options={"require": ["exp", "iss", "aud"]})
    tid = (claims.get("tid") or "").lower()
    if claims.get("iss") != f"https://login.microsoftonline.com/{tid}/v2.0":
        raise ValueError("issuer/tid mismatch")
    # When TENANT is configured as a GUID, pin the token's tenant to it too (belt-and-braces on top of
    # the tenant-scoped JWKS). A GUID is 36 chars with hyphens at 8/13/18/23; a verified domain isn't —
    # a plain `"-" in tenant` test would misfire on a hyphenated domain like my-company.com.
    t = MICROSOFT_TENANT.lower()
    is_guid = len(t) == 36 and t[8] == t[13] == t[18] == t[23] == "-" and \
        all(c in "0123456789abcdef-" for c in t)
    if is_guid and t != tid:
        raise ValueError("token is from a different tenant")
    return claims


@app.post("/auth/microsoft")
def auth_microsoft():
    """Native 'Sign in with Microsoft' (Teams/M365 accounts). The MSAL.js popup posts a signed ID token
    (JWT) here; we verify it against our single tenant's keys, then map the VERIFIED email to a role with
    store.resolve_email — identical outcomes to a password or Google. Additive: passwords still work."""
    if not MICROSOFT_ENABLED:
        return jsonify(ok=False, error="Microsoft sign-in is not configured."), 400
    token = ((request.get_json(silent=True) or {}).get("credential") or "").strip()
    if not token:
        return jsonify(ok=False, error="Missing Microsoft credential."), 400
    try:
        claims = _verify_ms_id_token(token)
    except Exception as e:   # bad signature/aud/expiry, wrong tenant, JWKS fetch fail, malformed token…
        app.logger.warning("microsoft id_token verification failed: %s", e)
        return jsonify(ok=False, error="Could not verify your Microsoft sign-in."), 401
    # Work/school ID tokens carry the address in `email` (if set) or the UPN in `preferred_username`.
    # Both are org-controlled in a single tenant, so they're authoritative (Microsoft omits a verified
    # flag). Take whichever is an email-shaped value.
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if "@" not in email:
        return jsonify(ok=False, error="Your Microsoft account has no email address."), 401
    try:
        store.record_domain_admin(email)   # @100.digital (config.ADMIN_EMAIL_DOMAINS) -> auto-enrolled;
                                            # no-op unless the tenant's UPN domain is an admin domain.
    except Exception as e:  # best-effort, exactly as /auth/google: resolve_email's domain fallback still
                            # grants admin from a pure read, so a transient write error must not fail login.
        app.logger.warning("record_domain_admin failed for %s (continuing): %s", email, e)
    kind, payload = store.resolve_email(email)
    if kind is None:
        return jsonify(ok=False,
                       error=f"{email} isn’t authorised yet. Ask an admin to grant your account access."), 403
    resp = _establish_session(kind, payload, json_mode=True)
    session["email"] = email
    return resp


@app.get("/logout")
def logout():
    session.clear()
    return _clear_sso(make_response(redirect("/")))


@app.get("/healthz")
def healthz():
    return "ok"


# --- feedback: every proxied dashboard posts here (text and/or a voice note) ---------------
@app.post("/feedback")
def feedback_submit():
    """Capture feedback from a dashboard's injected widget. Auth = the same session check the proxy
    uses, so a visitor can only file feedback against a dashboard they're allowed to open. Stored to
    the platform's private bucket via feedback.save() — no email (yet), no DB."""
    client = (request.form.get("client") or "").strip()
    if not client or not _may_open(client):
        # 401 WITH A REASON, not a bare 403. The overwhelmingly common cause is an EXPIRED platform
        # session: PERMANENT_SESSION_LIFETIME is a HARD 12h cap (Flask re-sends the cookie on each
        # request but never re-signs it, so activity does not slide it), and a dashboard already
        # rendered in the tab keeps working - its 5-min data.json poll swallows the redirect in a
        # bare catch. So the person has no idea they are signed out and the failing Feedback button
        # is the ONLY symptom they ever see. A generic "could not send - please try again" then
        # makes them retry forever, which can never succeed. Cost us a real client report
        # (Transmission, 2026-08-25) who gave up and moved to Teams. The widget branches on this
        # status to say "sign in again", keep the typed note, and resend it.
        # kind=<none> in this line means an expired/absent session (the common case); a kind that IS
        # present means the session is fine but may not open that client - two very different faults.
        app.logger.warning("feedback denied client=%s kind=%s - no session, or client not permitted",
                           client or "<empty>", session.get("kind") or "<none>")
        return jsonify(ok=False, reason="auth",
                       error=("Your sign-in has expired. Open the login page, sign in, "
                              "then press Send again - your note is kept here.")), 401
    if not _ext_setting("allow_feedback"):     # external tenants: widget suppressed + route closed
        return jsonify(ok=False, reason="disabled", error="not allowed"), 403
    blocked = _prod_mutation_blocked("save feedback")
    if blocked:
        return blocked
    text = request.form.get("text") or ""
    audio_bytes, audio_ctype = None, ""
    f = request.files.get("audio")
    if f is not None:
        audio_bytes = f.read()
        audio_ctype = f.mimetype or "audio/webm"
        if len(audio_bytes) > feedback.MAX_AUDIO_BYTES:
            return jsonify(ok=False, error="recording too large"), 413
    shot_bytes = None
    sf = request.files.get("screenshot")
    if sf is not None:
        shot_bytes = sf.read()
        if len(shot_bytes) > feedback.MAX_IMAGE_BYTES:
            shot_bytes = None  # drop an oversized screenshot; never fail the note over it
    if not text.strip() and not audio_bytes:
        return jsonify(ok=False, error="empty feedback"), 400
    try:
        feedback.save(client, text, audio_bytes, audio_ctype,
                      request.form.get("page", ""), session.get("kind", ""), shot_bytes,
                      reporter=request.form.get("reporter", ""),
                      deadline=request.form.get("deadline", ""))
    except Exception:
        app.logger.exception("feedback save failed")
        return jsonify(ok=False, reason="store", error="could not store feedback"), 500
    return jsonify(ok=True)


@app.get("/feedback/ping")
def feedback_ping():
    """"Can this session still file feedback?" - the widget calls it when the panel OPENS, so a
    signed-out visitor is told BEFORE typing a paragraph rather than after pressing Send. Deliberately
    the SAME predicate as feedback_submit above (in the same order), so the probe and the real post can
    never disagree. Cheap: one registry read, no body."""
    client = (request.args.get("client") or "").strip()
    if not client or not _may_open(client):
        return jsonify(ok=False, reason="auth"), 401
    if not _ext_setting("allow_feedback"):
        return jsonify(ok=False, reason="disabled"), 403
    return jsonify(ok=True)


def _enrich(rec):
    """Transcribe + interpret a note via Gemini (once), writing the result back to the record so
    every later view is instant. Best-effort: any failure leaves the note un-enriched to retry."""
    if rec.get("ai_done") or not feedback_ai.enabled():
        return rec
    audio_bytes, ctype = (None, "")
    if rec.get("audio"):
        audio_bytes, ctype = feedback.load_blob(rec["client"], rec["audio"])
    try:
        res = feedback_ai.interpret(audio_bytes, ctype, rec.get("text", ""),
                                    rec.get("client"), rec.get("page"))
    except Exception:
        app.logger.exception("feedback AI enrich failed")
        return rec
    fields = {"transcript": res["transcript"], "ai_summary": res["summary"],
              "ai_actions": res["actions"], "ai_done": 1}
    try:
        feedback.update_record(rec["client"], rec["id"], fields)
    except Exception:
        app.logger.exception("feedback AI write-back failed")
    rec.update(fields)
    return rec


@app.get("/feedback/admin")
def feedback_admin():
    """The tracker: every note across all dashboards, newest first, with the raw feedback, an AI
    transcript+summary, and the page screenshot. Admin/super only. AI runs lazily here (bounded per
    load) and is cached back to each record, so repeat views are instant."""
    _require_admin()
    try:
        rows = feedback.list_recent()
    except Exception:
        app.logger.exception("feedback list failed")
        rows = []
    budget = 15  # cap AI calls per page load; the rest enrich on a later view (newest first)
    for r in rows:
        if not r.get("ai_done") and budget > 0:
            _enrich(r)
            budget -= 1
    names = {k: c.get("name", k) for k, c in store._all_clients().items()}
    # Distinct clients PRESENT in the feedback (for the Client filter dropdown), name-sorted.
    # (key, display-name) pairs; built from the data so the dropdown only lists clients with notes.
    seen = {}
    for r in rows:
        k = r.get("client", "")
        if k and k not in seen:
            seen[k] = names.get(k, k)
    clients_list = sorted(seen.items(), key=lambda kv: kv[1].lower())
    # Client -> agency membership (for the Agency filter dropdown). Each card carries data-agency so
    # a note can be filtered to the agency its client belongs to (e.g. 100% Digital vs Transmission);
    # clients in no agency are "Unassigned". Like clients_list, the dropdown lists only agencies that
    # actually have notes, built from the data.
    agency_name = {a["slug"]: a["name"] for a in store._all_agencies()}
    agency_of = {}
    for a in store._all_agencies():
        for k in a.get("client_keys", []):
            agency_of[k] = a["slug"]
    seen_ag, has_unassigned = {}, False
    for r in rows:
        slug = agency_of.get(r.get("client", ""), "")
        if slug:
            seen_ag[slug] = agency_name.get(slug, slug)
        elif r.get("client"):
            has_unassigned = True
    agencies_filter = sorted(seen_ag.items(), key=lambda kv: kv[1].lower())
    return render_template_string(_FEEDBACK_ADMIN_HTML, rows=rows, names=names, count=len(rows),
                                  ai_on=feedback_ai.enabled(), statuses=feedback.STATUSES,
                                  default_status=feedback.DEFAULT_STATUS, clients_list=clients_list,
                                  agency_of=agency_of, agencies_filter=agencies_filter,
                                  has_unassigned=has_unassigned)


@app.get("/feedback/file/<client>/<fname>")
def feedback_file(client, fname):
    """Stream one stored feedback file (voice note or screenshot) for the tracker. Admin/super only.
    Honors HTTP Range so the <audio> element can seek — and, for the MediaRecorder WebM voice notes
    (which carry no duration in their header), can scan to the end to compute the real duration
    instead of showing 0:00 / 0:00."""
    _require_admin()
    data, ctype = feedback.load_blob(client, fname)
    if data is None:
        abort(404)
    total = len(data)
    headers = {"Cache-Control": "no-store", "Accept-Ranges": "bytes"}
    rng = request.headers.get("Range", "")
    if rng.startswith("bytes="):
        try:
            start_s, _, end_s = rng[6:].partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else total - 1
            start, end = max(0, start), min(end, total - 1)
            if start > end:
                start = 0
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
            headers["Content-Length"] = str(end - start + 1)
            return Response(data[start:end + 1], status=206, mimetype=ctype, headers=headers)
        except Exception:
            pass
    headers["Content-Length"] = str(total)
    return Response(data, mimetype=ctype, headers=headers)


@app.post("/feedback/status")
def feedback_status():
    """Set a note's triage status (Not yet started / Ongoing / On Hold / Completed). Admin/super."""
    _require_admin()
    d = request.get_json(silent=True) or {}
    client = (d.get("client") or "").strip()
    rid = (d.get("id") or "").strip()
    status = (d.get("status") or "").strip()
    if status not in feedback.STATUSES:
        return jsonify(ok=False, error="bad status"), 400
    if not feedback.update_record(client, rid, {"status": status}):
        return jsonify(ok=False, error="not found"), 404
    return jsonify(ok=True)


@app.post("/feedback/edit")
def feedback_edit():
    """Hand-edit a note: reporter name, the two dates (date_reported / deadline) and the notes text.
    Admin/super. Only the keys present in the body are written, so a partial save is fine. Dates are
    stored as the browser's "YYYY-MM-DD" strings (or "" to clear)."""
    _require_admin()
    d = request.get_json(silent=True) or {}
    client = (d.get("client") or "").strip()
    rid = (d.get("id") or "").strip()
    fields = {}
    if "reporter" in d:
        fields["reporter"] = (d.get("reporter") or "").strip()[:120]
    if "deadline" in d:
        fields["deadline"] = (d.get("deadline") or "").strip()[:40]
    if "date_reported" in d:
        fields["date_reported"] = (d.get("date_reported") or "").strip()[:40]
    if "text" in d:
        fields["text"] = (d.get("text") or "").strip()[:feedback.MAX_TEXT_CHARS]
    if not fields:
        return jsonify(ok=False, error="nothing to update"), 400
    if not feedback.update_record(client, rid, fields):
        return jsonify(ok=False, error="not found"), 404
    return jsonify(ok=True)


@app.post("/feedback/delete")
def feedback_delete():
    """Permanently delete a note and its audio/screenshot. Admin/super."""
    _require_admin()
    d = request.get_json(silent=True) or {}
    if not feedback.delete((d.get("client") or "").strip(), (d.get("id") or "").strip()):
        return jsonify(ok=False, error="bad request"), 400
    return jsonify(ok=True)


_FEEDBACK_ADMIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Dashboard feedback</title>
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" href="/favicon-32.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0a0e16; --panel:#101726; --panel-2:#0d1420; --border:rgba(255,255,255,.08);
    --border-strong:#2f3a52; --text:#e8ebf2; --muted:#8a93a6; --dim:#6b7280;
    /* single accent — bright cornflower blue */
    --accent:#4C8DFF; --accent-strong:#6EA8FF; --accent-bg:rgba(76,141,255,.12);
    --danger:#f87171;
    --font-sans:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  body{margin:0;color:var(--text);font-family:var(--font-sans);
    background:
      radial-gradient(840px 480px at 50% -6%, rgba(76,141,255,.18), transparent 62%),
      radial-gradient(560px 340px at 50% -2%, rgba(110,168,255,.10), transparent 66%),
      var(--bg);
    background-repeat:no-repeat;background-attachment:fixed}
  header{padding:18px 28px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:12px;
    background:rgba(12,18,30,.72);backdrop-filter:blur(6px);position:sticky;top:0;z-index:5}
  header .eyebrow{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent-strong)}
  header h1{margin:0;font-size:19px;font-weight:800} header .n{color:var(--muted);font-size:13px}
  header a{margin-left:auto;color:var(--muted);font-size:13px;text-decoration:none}
  header a:hover{color:var(--text)}
  .wrap{max-width:1180px;margin:0 auto;padding:24px 28px 80px;display:flex;flex-direction:column;gap:16px}
  .filterbar{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:2px}
  .fsel{display:inline-flex;align-items:center;gap:8px}
  .fsel .flbl{font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted)}
  .fsel select{font:600 13px/1 inherit;color:var(--text);background:var(--panel-2);border:1px solid var(--border);
    border-radius:8px;padding:8px 11px;cursor:pointer;outline:none}
  .fsel select:focus{border-color:var(--accent-strong)}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:15px 17px}
  .meta{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-bottom:12px}
  .chip{background:var(--accent-bg);color:var(--accent-strong);border-radius:999px;padding:2px 9px;font-weight:700}
  .meta .grow{flex:1}
  select.stat{font:600 12px/1 inherit;color:var(--text);background:var(--panel-2);border:1px solid var(--border);
    border-radius:7px;padding:5px 8px;cursor:pointer}
  select.stat[data-status="Completed"]{background:rgba(34,197,94,.16);border-color:#22c55e}
  select.stat[data-status="Ongoing"]{background:rgba(59,130,246,.18);border-color:#3b82f6}
  select.stat[data-status="On Hold"]{background:rgba(245,158,11,.16);border-color:#f59e0b}
  select.stat[disabled]{opacity:.5}
  button.del{font:600 12px/1 inherit;color:#fca5a5;background:transparent;border:1px solid rgba(248,113,113,.45);
    border-radius:7px;padding:5px 9px;cursor:pointer} button.del:hover{background:rgba(248,113,113,.16)}
  .edit{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap;margin-bottom:13px;
    padding:11px 13px;background:var(--panel-2);border:1px solid var(--border);border-radius:9px}
  .edit label{display:flex;flex-direction:column;gap:4px;font-size:10.5px;letter-spacing:.5px;
    text-transform:uppercase;color:var(--muted)}
  .edit input{font:14px/1 inherit;color:var(--text);background:var(--bg);border:1px solid var(--border);
    border-radius:7px;padding:7px 9px;outline:none;color-scheme:dark} .edit input:focus{border-color:var(--accent-strong)}
  .edit input.rep{min-width:170px}
  .edit .grow{flex:1}
  button.save{font:600 12px/1 inherit;color:#06132b;background:var(--accent);border:1px solid var(--accent);
    border-radius:7px;padding:8px 13px;cursor:pointer} button.save:hover{background:var(--accent-strong);border-color:var(--accent-strong)}
  button.save:disabled{opacity:.5;cursor:default}
  .saved{font-size:12px;color:var(--accent-strong);align-self:center}
  textarea.note{width:100%;min-height:70px;resize:vertical;font:14px/1.5 inherit;color:var(--text);
    background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px 10px;
    outline:none} textarea.note:focus{border-color:var(--accent-strong)}
  .cols{display:grid;grid-template-columns:1fr 1fr 220px;gap:18px}
  @media(max-width:820px){.cols{grid-template-columns:1fr}}
  .col h4{margin:0 0 7px;font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted)}
  .txt{white-space:pre-wrap;font-size:14px;line-height:1.5}
  .muted{color:var(--dim);font-style:italic;font-size:13px}
  audio{width:100%;margin-top:10px;height:38px}
  .sum{font-size:14px;line-height:1.5;margin:0 0 9px}
  .acts{margin:0;padding-left:18px;font-size:13.5px;line-height:1.55} .acts li{margin:2px 0}
  .shot{display:block;border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .shot img{display:block;width:100%;height:auto}
  .none{color:var(--muted);padding:40px 0;text-align:center}
</style></head><body>
<header><span class="eyebrow">Feedback</span><h1>Dashboard feedback</h1><span class="n">{{ count }} note(s)</span>
  <a href="/">&larr; back to platform</a></header>
<div class="wrap">
{% if rows %}
<div class="filterbar">
  <label class="fsel"><span class="flbl">Status</span>
    <select id="fStatus">
      <option value="all" data-base="All">All</option>
      {% for s in statuses %}<option value="{{ s }}" data-base="{{ s }}">{{ s }}</option>{% endfor %}
    </select>
  </label>
  <label class="fsel"><span class="flbl">Agency</span>
    <select id="fAgency">
      <option value="all" data-base="All agencies">All agencies</option>
      {% for slug, name in agencies_filter %}<option value="{{ slug }}" data-base="{{ name }}">{{ name }}</option>{% endfor %}
      {% if has_unassigned %}<option value="" data-base="Unassigned">Unassigned</option>{% endif %}
    </select>
  </label>
  <label class="fsel"><span class="flbl">Client</span>
    <select id="fClient">
      <option value="all" data-base="All clients">All clients</option>
      {% for key, name in clients_list %}<option value="{{ key }}" data-base="{{ name }}">{{ name }}</option>{% endfor %}
    </select>
  </label>
</div>
{% endif %}
{% for r in rows %}
  {% set st = r.status or default_status %}
  <div class="card" data-status="{{ st }}" data-client="{{ r.client }}" data-agency="{{ agency_of.get(r.client, '') }}">
    <div class="meta">
      <span class="chip">{{ names.get(r.client, r.client) }}</span>
      <span>{{ r.created_at | datetime }}</span>
      {% if r.page %}<span>· {{ r.page }}</span>{% endif %}
      {% if r.user_kind %}<span>· {{ r.user_kind }}</span>{% endif %}
      <span class="grow"></span>
      <select class="stat" data-status="{{ st }}" data-client="{{ r.client }}" data-id="{{ r.id }}">
        {% for s in statuses %}<option value="{{ s }}"{% if s == st %} selected{% endif %}>{{ s }}</option>{% endfor %}
      </select>
      <button class="del" data-client="{{ r.client }}" data-id="{{ r.id }}">Delete</button>
    </div>
    <div class="edit" data-client="{{ r.client }}" data-id="{{ r.id }}">
      <label>Reporter<input class="ef rep" data-field="reporter" type="text" placeholder="(none)" value="{{ r.reporter or '' }}"></label>
      <label>Date reported<input class="ef" data-field="date_reported" type="date" value="{{ r.date_reported or (r.created_at | dateonly) }}"></label>
      <label>Target deadline<input class="ef" data-field="deadline" type="date" value="{{ r.deadline or '' }}"></label>
      <span class="grow"></span>
      <button class="save" type="button">Save</button>
      <span class="saved" style="display:none">Saved &check;</span>
    </div>
    <div class="cols">
      <div class="col">
        <h4>Notes (editable)</h4>
        <textarea class="ef note" data-field="text" placeholder="Add or edit notes…">{{ r.text or '' }}</textarea>
        {% if r.transcript %}<div class="txt" style="margin-top:8px">&ldquo;{{ r.transcript }}&rdquo;</div>
        {% elif not r.text %}<div class="muted" style="margin-top:8px">{% if r.audio %}(voice note - see player){% endif %}</div>{% endif %}
        {% if r.audio %}<audio class="vn" controls preload="metadata" src="/feedback/file/{{ r.client }}/{{ r.audio }}"></audio>{% endif %}
      </div>
      <div class="col">
        <h4>AI summary</h4>
        {% if r.ai_summary %}
          <p class="sum">{{ r.ai_summary }}</p>
          {% if r.ai_actions %}<ul class="acts">{% for a in r.ai_actions %}<li>{{ a }}</li>{% endfor %}</ul>{% endif %}
        {% elif ai_on %}<div class="muted">Processing on next load…</div>
        {% else %}<div class="muted">AI not configured.</div>{% endif %}
      </div>
      <div class="col">
        <h4>Screenshot</h4>
        {% if r.screenshot %}<a class="shot" href="/feedback/file/{{ r.client }}/{{ r.screenshot }}" target="_blank" rel="noopener">
          <img loading="lazy" src="/feedback/file/{{ r.client }}/{{ r.screenshot }}" alt="page screenshot"></a>
        {% else %}<div class="muted">none</div>{% endif %}
      </div>
    </div>
  </div>
{% else %}
  <div class="none">No feedback yet.</div>
{% endfor %}
</div>
<script>
function fbPost(url,body){return fetch(url,{method:'POST',headers:{'content-type':'application/json'},
  credentials:'same-origin',body:JSON.stringify(body)});}
// Status + Client filter: show only cards matching BOTH dropdowns, with live counts (per status
// and per client) baked into each option label. Counts are computed from the actual cards, so they
// stay correct after a status change or a delete (callers re-invoke fbFilter to recompute).
var fbFilter=(function(){
  var bar=document.querySelector('.filterbar');
  if(!bar)return function(){};
  var selStatus=document.getElementById('fStatus'), selClient=document.getElementById('fClient'),
      selAgency=document.getElementById('fAgency');
  function apply(){
    var st=selStatus.value, cl=selClient.value, ag=selAgency?selAgency.value:'all';
    document.querySelectorAll('.card').forEach(function(card){
      var sOk=(st==='all'||(card.dataset.status||'')===st);
      var cOk=(cl==='all'||(card.dataset.client||'')===cl);
      var aOk=(ag==='all'||(card.dataset.agency||'')===ag);
      card.style.display=(sOk&&cOk&&aOk)?'':'none';
    });
  }
  function relabel(sel,counts,total){
    if(!sel)return;
    Array.prototype.forEach.call(sel.options,function(o){
      var n=(o.value==='all')?total:(counts[o.value]||0);
      o.textContent=(o.dataset.base||o.value)+' ('+n+')';
    });
  }
  function recount(){
    var cards=document.querySelectorAll('.card'), byStatus={}, byClient={}, byAgency={};
    cards.forEach(function(card){
      var s=card.dataset.status||'', c=card.dataset.client||'', a=card.dataset.agency||'';
      byStatus[s]=(byStatus[s]||0)+1; byClient[c]=(byClient[c]||0)+1; byAgency[a]=(byAgency[a]||0)+1;
    });
    relabel(selStatus,byStatus,cards.length);
    relabel(selClient,byClient,cards.length);
    relabel(selAgency,byAgency,cards.length);
    apply();
  }
  selStatus.addEventListener('change',apply);
  selClient.addEventListener('change',apply);
  if(selAgency)selAgency.addEventListener('change',apply);
  recount();
  return recount;   // status-change / delete handlers call fbFilter() to recompute counts + re-apply
})();
document.querySelectorAll('select.stat').forEach(function(sel){
  sel.addEventListener('change',function(){
    var prev=sel.dataset.status; sel.disabled=true;
    fbPost('/feedback/status',{client:sel.dataset.client,id:sel.dataset.id,status:sel.value})
      .then(function(r){if(!r.ok)throw 0;sel.dataset.status=sel.value;
        var card=sel.closest('.card'); if(card)card.dataset.status=sel.value;
        fbFilter();})
      .catch(function(){sel.value=prev;alert('Could not update status.');})
      .finally(function(){sel.disabled=false;});
  });
});
// Voice notes are MediaRecorder WebM blobs whose header carries no duration, so the browser reports
// duration=Infinity and the player shows 0:00 / 0:00. Forcing a seek past the end makes it scan the
// stream (Range-served) and compute the real length, which we then rewind to 0.
document.querySelectorAll('audio.vn').forEach(function(a){
  a.addEventListener('loadedmetadata',function(){
    if(a.duration===Infinity||isNaN(a.duration)){
      a.currentTime=1e101;
      a.addEventListener('timeupdate',function fix(){
        a.removeEventListener('timeupdate',fix);
        if(a.duration!==Infinity&&!isNaN(a.duration))a.currentTime=0;
      });
    }
  });
});
document.querySelectorAll('div.edit').forEach(function(bar){
  var btn=bar.querySelector('button.save'),ok=bar.querySelector('.saved'),
      card=bar.closest('.card');
  btn.addEventListener('click',function(){
    var body={client:bar.dataset.client,id:bar.dataset.id};
    card.querySelectorAll('.ef').forEach(function(el){body[el.dataset.field]=el.value;});
    btn.disabled=true;ok.style.display='none';
    fbPost('/feedback/edit',body)
      .then(function(r){if(!r.ok)throw 0;ok.style.display='';
        setTimeout(function(){ok.style.display='none';},2000);})
      .catch(function(){alert('Could not save.');})
      .finally(function(){btn.disabled=false;});
  });
});
document.querySelectorAll('button.del').forEach(function(b){
  b.addEventListener('click',function(){
    if(!confirm('Delete this feedback permanently?'))return;
    b.disabled=true;
    fbPost('/feedback/delete',{client:b.dataset.client,id:b.dataset.id})
      .then(function(r){if(!r.ok)throw 0;var c=b.closest('.card');if(c)c.remove();fbFilter();})
      .catch(function(){b.disabled=false;alert('Could not delete.');});
  });
});
</script>
</body></html>"""


@app.template_filter("datetime")
def _fmt_dt(epoch):
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


@app.template_filter("dateonly")
def _fmt_date(epoch):
    """Epoch -> 'YYYY-MM-DD' (UTC) for prefilling a <input type=date> in the tracker."""
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


# ─── Pipeline status + editable definitions (the merged-in Status dashboard) ───────────────
# The status-export job writes gs://{_STATUS_BUCKET}/status.json (data-sync health + data-accuracy
# checks per Snowflake-sourced client), and the LIVE single-source-of-truth definitions live at
# definitions/<c>.json in the same bucket. The platform reads them to render the Overview health
# badges + the Data Accuracy tab, stages an edit (definitions/<c>.staged.json) and triggers the
# status-deploy job ("Make this live"). EDITING IS OPEN — anyone who can open a client may edit its
# definitions; the only hard requirement is a typed NAME, recorded as last_edited_by (audit).
_STATUS_BUCKET = "bidbrain-analytics-status-dash"
_PLATFORM_BUCKET = os.environ.get("GCS_BUCKET", "")
_STATUS_TTL = 30.0
_status_cache = {"t": 0.0, "doc": None}
_EDIT_ROLES = ("agency", "client", "admin", "superadmin")   # who may edit (one-line flip to restrict)


def _gcs_bucket(name):
    from google.cloud import storage
    return storage.Client(project=PROJECT).bucket(name)


def _status_doc():
    """status.json (cached ~30s). Returns {} if missing/unreadable so the UI degrades gracefully."""
    now = time.time()
    if _status_cache["doc"] is not None and (now - _status_cache["t"]) < _STATUS_TTL:
        return _status_cache["doc"]
    doc = {}
    try:
        import json
        blob = _gcs_bucket(_STATUS_BUCKET).blob("status.json")
        if blob.exists():
            doc = json.loads(blob.download_as_bytes())
    except Exception:
        app.logger.exception("status.json read failed")
    _status_cache.update(t=now, doc=doc)
    return doc


def _read_definitions(client, staged=False):
    """Live (or staged) definitions doc for a client, or None."""
    import json
    obj = f"definitions/{client}.{'staged.' if staged else ''}json"
    blob = _gcs_bucket(_STATUS_BUCKET).blob(obj)
    if not blob.exists():
        return None
    return json.loads(blob.download_as_bytes())


def _has_definitions(client):
    try:
        return _gcs_bucket(_STATUS_BUCKET).blob(f"definitions/{client}.json").exists()
    except Exception:
        return False


def _can_edit(client):
    """Editing is OPEN to internal tiers: anyone who can OPEN the client may edit its definitions
    (the only hard gate is a typed name). _may_open encodes per-role visibility; _EDIT_ROLES is the
    broad knob. EXTERNAL tenants are excluded outright — staging a definitions edit and deploying
    it re-runs privileged export jobs, which an outside agency must never reach.
    (NOTE for review: internal AGENCY sessions can still reach this, which is pre-existing and
    deliberate — Transmission edits Cloudflare's CS definitions from the Data Accuracy tab. Whether
    that should become admin-only is a separate decision, flagged in the exposure notes.)"""
    return (session.get("kind") in _EDIT_ROLES and _may_open(client)
            and _ext_setting("edit_definitions"))


def _run_status_deploy(client):
    """RUN the status-deploy job with DEPLOY_CLIENT=<c> (Run Admin API v2 :run). Platform SA has
    run.invoker on the job. RUNNING a job needs no actAs, so this works from the web tier."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sess = AuthorizedSession(creds)
    url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/status-deploy:run"
    body = {"overrides": {"containerOverrides": [{"env": [{"name": "DEPLOY_CLIENT", "value": client}]}]}}
    r = sess.post(url, json=body, timeout=60)
    r.raise_for_status()


def _append_audit(client, name, action):
    """Append a who/when/what line to definitions/_audit/<c>.jsonl. Best-effort."""
    import json
    try:
        blob = _gcs_bucket(_STATUS_BUCKET).blob(f"definitions/_audit/{client}.jsonl")
        prev = blob.download_as_text() if blob.exists() else ""
        line = json.dumps({"ts": int(time.time()), "client": client, "by": name, "action": action})
        blob.upload_from_string(prev + line + "\n", content_type="application/json")
    except Exception:
        app.logger.exception("audit append failed")


def _pretty_source(name):
    """'raw_windsor.perf_meta' -> 'meta'. Strips the internal dataset/table naming an external
    tenant has no business seeing (the browser already displays it this way)."""
    s = str(name or "")
    if "." in s:
        s = s.split(".", 1)[1]
    return s[5:] if s.startswith("perf_") else s


def _status_entry_for_external(c):
    """Rebuild ONE status.json client entry from an explicit ALLOW-LIST of fields for an external
    tenant. Allow-list, not blocklist: a field added to status.json in future does not silently
    start shipping to an outside agency.

    Dropped deliberately:
      - `snowflake_query` — the full check SQL: internal dataset/table names, platform account and
        advertiser IDs, and our filtering logic. A readable map of the warehouse.
      - `note` — written for our own engineers. ResetData's Reddit note states in plain English
        that Reddit spend carries a x2 agency markup: a direct margin disclosure.
      - `error` / `computed_at` — internal diagnostics.
      - `freshness.transmission_tables`, `ingest_label` — internal table names and pipeline wording.
      - per-source table names are prettified (see _pretty_source).
    Kept: exactly what the Data Accuracy chips and metric table need to render truthfully."""
    f = c.get("freshness") or {}
    out = {
        "client": c.get("client"), "label": c.get("label"),
        "source_label": c.get("source_label"),
        "freshness": {
            "verdict": f.get("verdict"),
            "build_at": f.get("build_at"),
            "ingest_latest": f.get("ingest_latest"),
            "data_through": f.get("data_through"),
            "source_data_through": f.get("source_data_through"),
            "source_dates": [{"source": _pretty_source(s.get("source")),
                              "data_through": s.get("data_through")}
                             for s in (f.get("source_dates") or [])],
        },
        "accuracy": [{
            "label": k.get("label"), "group": k.get("group", ""),
            "metric_kind": k.get("metric_kind"),
            "snowflake_value": k.get("snowflake_value"),
            "dashboard_value": k.get("dashboard_value"),
            "match": k.get("match"),
        } for k in (c.get("accuracy") or [])],
    }
    if c.get("stale_carryforward"):
        out["stale_carryforward"] = True
    return out


@app.get("/api/status")
def api_status():
    """status.json filtered to the clients this session may open, + per-client edit/definitions flags.
    The Overview health badges and the Data Accuracy tab render from this."""
    if session.get("kind") not in _EDIT_ROLES:
        abort(403)
    doc = _status_doc()
    clients = [c for c in doc.get("clients", []) if _may_open(c.get("client", ""))]
    if not _ext_setting("show_check_internals"):
        clients = [_status_entry_for_external(c) for c in clients]
    flags = {c["client"]: {"can_edit": _can_edit(c["client"]), "has_definitions": _has_definitions(c["client"])}
             for c in clients if c.get("client")}
    # Opt-in placeholders: registry clients flagged `show_pending_row` that have NO status.json
    # entry render as a greyed "awaiting connection" row on the Data Accuracy tab (geyervalmont, sophiie).
    # Explicitly per-client so other spec-less clients (bellshakespeare/nextsmile) keep today's
    # no-row behaviour; still scoped through _may_open like everything else. Best-effort — a
    # registry read failure must not take down the status API.
    pending = []
    try:
        have = {c.get("client") for c in clients}
        for key, c in store._all_clients().items():
            if c.get("show_pending_row") and key not in have and _may_open(key):
                pending.append({"client": key, "label": c.get("name", key)})
    except Exception:
        app.logger.exception("pending-row scan failed")
    return jsonify(generated_at=doc.get("generated_at"),
                   tolerance_minutes=doc.get("tolerance_minutes"),
                   clients=clients, flags=flags, pending=pending)


def _icon_response(data, ctype):
    """Serve a baked-in brand icon. Public (no auth) and cacheable — overrides the default
    no-store so browsers don't refetch the tab icon on every navigation."""
    if not data:
        abort(404)
    return Response(data, mimetype=ctype,
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.ico")
def favicon_ico():
    return _icon_response(FAVICON_ICO, "image/x-icon")


@app.get("/favicon-32.png")
def favicon_png():
    return _icon_response(FAVICON_PNG, "image/png")


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    return _icon_response(APPLE_ICON, "image/png")


@app.get("/logo/<client>")
def client_logo(client):
    """Stream a client's uploaded logo from the platform bucket. 404 if none.

    Scoping: admin/super may fetch any client's logo (the admin tree and super console list every
    client). An AGENCY or CLIENT session is limited to clients it may open — previously any
    logged-in session could fetch any client's logo, which leaked nothing but the mark itself and
    is closed here."""
    if session.get("kind") not in _EDIT_ROLES:
        abort(403)
    if session.get("kind") not in ("admin", "superadmin") and not _may_open(client):
        abort(403)
    try:
        blob = _gcs_bucket(_PLATFORM_BUCKET).blob(f"logos/{client}")
        if not blob.exists():
            abort(404)
        return Response(blob.download_as_bytes(), mimetype=blob.content_type or "image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    except Exception:
        abort(404)


@app.post("/admin/api/client-logo")
def api_client_logo():
    """Upload/replace a client's logo (admin/super). Stored at logos/<client> in the platform bucket."""
    _require_admin()
    client = (request.form.get("client") or "").strip()
    if client not in store._all_clients():
        return jsonify(ok=False, error="Unknown client."), 404
    f = request.files.get("logo")
    if f is None:
        return jsonify(ok=False, error="No file."), 400
    data = f.read()
    if len(data) > 2 * 1024 * 1024:
        return jsonify(ok=False, error="Logo too large (max 2 MB)."), 413
    ctype = f.mimetype or "image/png"
    if not ctype.startswith("image/"):
        return jsonify(ok=False, error="File must be an image."), 400
    blocked = _prod_mutation_blocked(f"upload logo for {client}")
    if blocked:
        return blocked
    try:
        _gcs_bucket(_PLATFORM_BUCKET).blob(f"logos/{client}").upload_from_string(data, content_type=ctype)
    except Exception as e:
        return jsonify(ok=False, error=f"Upload failed: {e}"), 500
    return jsonify(ok=True)


@app.get("/definitions/<client>")
def get_definitions(client):
    """The LIVE definitions doc for the editor (visibility-gated)."""
    if not _may_open(client):
        abort(403)
    live = _read_definitions(client)
    if live is None:
        return jsonify(ok=False, error="This client has no editable definitions."), 404
    return jsonify(ok=True, definitions=live, can_edit=_can_edit(client))


@app.post("/definitions/<client>")
def stage_definitions(client):
    """Stage an edited definitions doc. Requires a typed NAME (recorded as last_edited_by). Carries
    over the identity/seed-spec fields from the live doc so the editor can only change parameters."""
    if not _can_edit(client):
        abort(403)
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    defs = d.get("definitions")
    if not name:
        return jsonify(ok=False, error="Your name is required - it is recorded as the editor."), 400
    if not isinstance(defs, dict):
        return jsonify(ok=False, error="Invalid definitions payload."), 400
    blocked = _prod_mutation_blocked(f"stage definitions for {client}")
    if blocked:
        return blocked
    live = _read_definitions(client) or {}
    for k in ("client", "dataset", "source_table_snowflake", "mirror_table_bigquery",
              "_seed_spec", "_smoke_views"):
        if k in live and k not in defs:
            defs[k] = live[k]
    from datetime import datetime, timezone
    defs["last_edited_by"] = name
    defs["last_edited_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        import json
        _gcs_bucket(_STATUS_BUCKET).blob(f"definitions/{client}.staged.json").upload_from_string(
            json.dumps(defs, indent=2), content_type="application/json")
    except Exception as e:
        return jsonify(ok=False, error=f"Could not stage: {e}"), 500
    _append_audit(client, name, "staged")
    return jsonify(ok=True, last_edited_by=name, last_edited_at=defs["last_edited_at"])


@app.post("/deploy/<client>")
def deploy_definitions(client):
    """'Make this live' — trigger the status-deploy job to validate + seed + promote the staged doc
    and rebuild the dashboards. Requires a staged doc (so a name was already captured)."""
    if not _can_edit(client):
        abort(403)
    staged = _read_definitions(client, staged=True)
    if staged is None:
        return jsonify(ok=False, error="Nothing staged - save your edits first."), 400
    blocked = _prod_mutation_blocked(f"deploy definitions for {client} (runs status-deploy)")
    if blocked:
        return blocked
    try:
        _run_status_deploy(client)
    except Exception as e:
        app.logger.exception("status-deploy trigger failed")
        return jsonify(ok=False, error=f"Could not start the deploy: {e}"), 500
    _append_audit(client, staged.get("last_edited_by", ""), "deploy-triggered")
    return jsonify(ok=True)


# The Snowflake-sourced clients whose export jobs "Sync all now" force-refreshes.
#
# EVERY NAME HERE MUST BE A JOB THAT EXISTS: the Run Admin API 404s an unknown job, which lands it in
# the response's `failed` list and makes the Overview's "Sync all" report a red failure forever. So a
# PREVIEW client (one with a deployed dashboard but no export job yet — bellshakespeare, nextsmile,
# geyervalmont, sophiie) is deliberately ABSENT, and gets added here as one line the moment its
# `<c>-export` job is deployed. That is step 8 of each client README's FLIPPING PREVIEW -> LIVE.
_SYNC_EXPORT_JOBS = ["mongodb-export", "cloudflare-export", "stt-export",
                     "hireright-export", "schneider-export", "proptrack-export"]


@app.post("/sync-all")
def sync_all():
    """'Sync all dashboards now' (Overview) — force-rebuild every Snowflake client's export + the
    status checks. Triggers each <c>-export + status-export (FORCE_REBUILD) via the Run Admin API
    (platform SA needs run.invoker on them). Returns immediately; the dashboards rebuild over the
    next few minutes and the Overview timestamps reset as each finishes."""
    if session.get("kind") not in _EDIT_ROLES:
        abort(403)
    # Defence in depth: the before_request allowlist already denies this endpoint to an external
    # tenant. This second, local check means the endpoint stays closed even if that allowlist is
    # ever bypassed or an external session reaches it by another path — an outside agency must
    # never be able to start ANOTHER agency's export pipeline.
    if not _ext_setting("show_sync"):
        app.logger.warning("sync-all denied for external agency=%s",
                           session.get("agency_slug", ""))
        return jsonify(ok=False, error="Not available for this account."), 403
    blocked = _prod_mutation_blocked("sync-all (runs every export job)")
    if blocked:
        return blocked
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sess = AuthorizedSession(creds)
    triggered, failed = [], []
    for job in _SYNC_EXPORT_JOBS + ["status-export"]:
        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{job}:run"
        body = {"overrides": {"containerOverrides": [{"env": [{"name": "FORCE_REBUILD", "value": "1"}]}]}}
        try:
            r = sess.post(url, json=body, timeout=30); r.raise_for_status(); triggered.append(job)
        except Exception as e:   # noqa: BLE001
            failed.append(job); app.logger.warning(f"sync-all: {job} failed: {e}")
    return jsonify(ok=(not failed), triggered=triggered, failed=failed)


# --- super-admin god-mode console ---------------------------------------------------------
def _pw_candidates():
    """Documented seed plaintexts (config.py), used to self-heal a hash-only registry on first
    super-admin load so existing passwords can be revealed (see Store.backfill_plaintext)."""
    cands = {"admin": getattr(cfg, "ADMIN_PW", ""), "super": getattr(cfg, "SUPER_ADMIN_PW", "")}
    for a in getattr(cfg, "AGENCIES", []):
        cands[f"agency:{a['slug']}"] = a.get("password", "")
    for k, pw in getattr(cfg, "CLIENT_PASSWORDS", {}).items():
        if pw:
            cands[f"client:{k}"] = pw
    return cands


def _safe_upstream_pw(client):
    """The REAL standalone dashboard password from Secret Manager — '' if unreadable/not set yet."""
    try:
        return _upstream_pw(client)
    except Exception:
        return ""


def _render_super():
    store.backfill_plaintext(_pw_candidates())   # recover revealable plaintexts (idempotent)
    st = store.get_super_state()
    # the dashboard password IS the standalone <c>-dash-password secret — reveal it live
    for d in st["dashboards"]:
        d["password"] = _safe_upstream_pw(d["key"]) if d.get("status") == "active" and d.get("url") else ""
    # if no super-admin password is set in the registry yet, the active login is the bootstrap env
    if not st["super_has"] and not st["super_password"]:
        st["super_password"] = getattr(cfg, "SUPER_ADMIN_PW", "")
        st["super_bootstrap"] = True
    else:
        st["super_bootstrap"] = False
    return render_template("superadmin.html", logo_svg=LOGO_SVG,
                           google_configured=bool(GOOGLE_CLIENT_ID),
                           admin_domains=getattr(cfg, "ADMIN_EMAIL_DOMAINS", []),
                           tools=_tools_tiles(), **st)


# --- Tools tile: The Grid (Central) freshness + on-demand sync -----------------------------
# The tile's "Sync now"/"Last synced" now drive Central's OWN sync directly through the proxy
# (/d/central/api/central/sync[/status], see _tools_tile.html), so there is no platform-side
# pacing sync endpoint anymore — the older pacing-grid tile + its /tools/pacing/* routes were
# retired 2026-07-20 when Central superseded it.


@app.get("/admin")
def admin_tree():
    """The editable agencies→clients→campaigns tree. Reachable by admin (its home) and by super
    admin (linked from the god-mode console)."""
    kind = session.get("kind")
    if kind not in ("admin", "superadmin"):
        return redirect("/")
    st = store.get_state()
    return render_template("admin.html", logo_svg=LOGO_SVG, is_super=(kind == "superadmin"),
                           agency_logos=ADMIN_AGENCY_LOGOS, tools=_tools_tiles(), **st)


# --- admin / super "enter agency view" -----------------------------------------------------
# Admins and super admins normally land on the admin tree / god-mode console. This lets them drop
# into ANY agency's own portal (exactly what that agency sees) with one click, and step back out.
# It flips the session to an `agency` kind — so every existing agency-scoped path (the portal render,
# /api/status, the proxy's _may_open) is reused verbatim and correctly scoped — while stashing the
# role to restore on exit. Logout still clears everything.
def _admin_kind():
    """The admin/super identity behind this session: the live kind, or — while already viewing an
    agency portal — the role we'll return to. So an impersonating admin can hop between agencies."""
    return session.get("admin_return") or session.get("kind")


@app.get("/enter-agency/<slug>")
def enter_agency(slug):
    if _admin_kind() not in ("admin", "superadmin"):
        abort(403)
    agency = store.get_agency(slug)
    if not agency:
        abort(404)
    session["admin_return"] = _admin_kind()   # idempotent across agency-to-agency hops
    session["kind"] = "agency"
    session["agency_slug"] = slug
    # Re-scope the (dormant, proxy-era) SSO allow-list to this agency too, so the impersonated view
    # is consistent end-to-end even if the cookie path is ever activated by per-client subdomains.
    return _set_sso(make_response(redirect("/")), list(agency.get("client_keys", [])))


@app.get("/exit-agency")
def exit_agency():
    """Return from an agency portal to the admin tree / god-mode console."""
    ret = session.pop("admin_return", None)
    resp = make_response(redirect("/"))
    if ret in ("admin", "superadmin"):
        session["kind"] = ret
        session.pop("agency_slug", None)
        return _set_sso(resp, store.active_client_keys())   # restore the full admin allow-list
    return resp


@app.post("/super/api/admin-password")
def super_admin_password():
    _require_super()
    pw = ((request.get_json(silent=True) or {}).get("password") or "").strip()
    if not pw:
        return jsonify(ok=False, error="Password required."), 400
    store.set_admin_password(pw)
    return jsonify(ok=True)


@app.post("/super/api/super-password")
def super_super_password():
    _require_super()
    pw = ((request.get_json(silent=True) or {}).get("password") or "").strip()
    if not pw:
        return jsonify(ok=False, error="Password required."), 400
    store.set_super_password(pw)
    return jsonify(ok=True)


@app.post("/super/api/agency-password")
def super_agency_password():
    _require_super()
    d = request.get_json(silent=True) or {}
    slug = (d.get("slug") or "").strip()
    pw = (d.get("password") or "").strip()
    if not slug or not pw:
        return jsonify(ok=False, error="Agency and password required."), 400
    if not store.set_agency_password(slug, pw):
        return jsonify(ok=False, error="Unknown agency."), 404
    return jsonify(ok=True)


@app.post("/super/api/spend-multiplier")
def super_spend_multiplier():
    """Set a client's per-channel spend multiplier (client-billed "spent to date" vs real media
    cost). Body: {key, multipliers:{google,meta,ttd,...}}. An empty/all-1.0 map removes it. The proxy
    reads this live and injects window.BB_SPEND_MULT — no dashboard redeploy needed to change a value."""
    _require_super()
    d = request.get_json(silent=True) or {}
    key = (d.get("key") or "").strip()
    if key not in store._all_clients():
        return jsonify(ok=False, error="Unknown dashboard."), 404
    if not store.set_spend_multipliers(key, d.get("multipliers") or {}):
        return jsonify(ok=False, error="Unknown dashboard."), 404
    return jsonify(ok=True, multipliers=store.get_spend_multipliers(key))


@app.post("/super/api/user")
def super_user():
    """Grant / change / revoke a Google account's access (super-admin only). Mirrors the password
    tiers: role superadmin/admin, or agency (+agency_slug), or client (+client_key)."""
    _require_super()
    d = request.get_json(silent=True) or {}
    action = (d.get("action") or "upsert").strip()
    email = (d.get("email") or "").strip().lower()
    if action == "delete":
        if not email:
            return jsonify(ok=False, error="Email required."), 400
        store.delete_user(email)
        return jsonify(ok=True)
    role = (d.get("role") or "").strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="Enter a valid email address."), 400
    if role not in ("superadmin", "admin", "agency", "client"):
        return jsonify(ok=False, error="Choose a role."), 400
    agency_slug = (d.get("agency_slug") or "").strip()
    client_key = (d.get("client_key") or "").strip()
    if role == "agency" and not store.get_agency(agency_slug):
        return jsonify(ok=False, error="Choose a valid agency."), 400
    if role == "client" and client_key not in store._all_clients():
        return jsonify(ok=False, error="Choose a valid dashboard."), 400
    store.upsert_user(email, role,
                      agency_slug if role == "agency" else "",
                      client_key if role == "client" else "")
    return jsonify(ok=True)


@app.post("/super/api/dashboard-password")
def super_dashboard_password():
    """TRUE rotation of a dashboard's REAL password: write a new Secret Manager version for
    <c>-dash-password and restart the <c>-dash service so it re-reads :latest. The platform's own
    proxy cache is updated in-process. After this the standalone dashboard's password is changed
    everywhere."""
    _require_super()
    d = request.get_json(silent=True) or {}
    client = (d.get("client") or "").strip()
    pw = (d.get("password") or "").strip()
    if not client or not pw:
        return jsonify(ok=False, error="Dashboard and password required."), 400
    blocked = _prod_mutation_blocked(f"rotate {client}-dash-password (Secret Manager + service restart)")
    if blocked:
        return blocked
    if client not in store.active_client_keys():
        return jsonify(ok=False, error="Unknown or inactive dashboard."), 404
    try:
        _add_secret_version(f"{client}-dash-password", pw)
    except Exception as e:
        return jsonify(ok=False, error=f"Could not write the secret: {e}"), 500
    _UPSTREAM_PW[client] = pw                  # proxy now logs into the upstream with the new pw
    _UPSTREAM_COOKIES.pop(client, None)
    try:
        _restart_service(f"{client}-dash")
    except Exception as e:
        # the secret is rotated but the running dashboard still serves the OLD password until it
        # restarts — tell the operator exactly how to finish the job by hand.
        return jsonify(ok=False, restart_failed=True,
                       error=(f"Password saved, but auto-restart of {client}-dash failed: {e}. "
                              f"Run:  gcloud run services update {client}-dash "
                              f"--region {REGION} --update-secrets DASH_PASSWORD={client}-dash-password:latest")), 500
    return jsonify(ok=True)


# --- admin CRUD API (admin session only) --------------------------------------------------
@app.post("/admin/api/agency")
def api_agency():
    _require_admin()
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    try:
        if action == "delete":
            slug = (d.get("orig_slug") or "").strip()
            if not slug:
                return jsonify(ok=False, error="Missing agency slug."), 400
            store.delete_agency(slug)
        else:
            name = (d.get("name") or "").strip()
            slug = (d.get("slug") or "").strip()
            if not name or not slug:
                return jsonify(ok=False, error="Name and slug are required."), 400
            store.upsert_agency(d.get("orig_slug", ""), name, slug, d.get("password", ""))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.post("/admin/api/client")
def api_client():
    _require_admin()
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    try:
        if action == "delete":
            key = (d.get("key") or "").strip()
            if not key:
                return jsonify(ok=False, error="Missing client key."), 400
            store.remove_client(key)
        else:
            key = (d.get("key") or "").strip()
            name = (d.get("name") or "").strip()
            if not key or not name:
                return jsonify(ok=False, error="Client key and name are required."), 400
            url = (d.get("url") or "").strip()
            if url and not (url.startswith("http://") or url.startswith("https://")):
                return jsonify(ok=False, error="URL must start with http:// or https://."), 400
            store.upsert_client(
                d.get("agency_slug", ""), key, name,
                (d.get("slug") or key).strip(),
                d.get("status", "active"), url,
            )
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.post("/admin/api/campaign")
def api_campaign():
    _require_admin()
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    try:
        if action == "delete":
            ck = (d.get("client_key") or "").strip()
            idx = d.get("index")
            if not ck or idx in (None, ""):
                return jsonify(ok=False, error="Missing client_key or index."), 400
            store.delete_campaign(ck, idx)
        else:
            name = (d.get("name") or "").strip()
            path = (d.get("path") or "").strip()
            if not name or not path:
                return jsonify(ok=False, error="Campaign name and path are required."), 400
            if path and not path.startswith("/"):
                path = "/" + path
            store.set_campaign(d["client_key"], d.get("index"), name, path,
                               d.get("status", "active"))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# --- reverse proxy: serve each dashboard under the platform's own origin ------------------
# Makes "no second password" work on raw run.app. The platform logs into the upstream <c>-dash
# ONCE per instance (with the dashboard's own password from Secret Manager) and proxies it under
# /d/<client>/. Visitors only ever see the platform origin + the platform's single login.
PROJECT = os.environ.get("GCP_PROJECT", "bidbrain-analytics")
REGION = os.environ.get("REGION", "australia-southeast1")
_UPSTREAM_PW = {}       # client_key -> plaintext dashboard password (cached per instance)
_UPSTREAM_COOKIES = {}  # client_key -> upstream session cookies (cached per instance)

# A floating "Log out" pill injected into every proxied dashboard page (the dashboards are
# third-party HTML with 10 different themes, so it is fully inline-styled + max z-index to never
# clash). It points at the platform's own /logout (root-relative -> dashboards.bidbrain.ai/logout,
# NOT through /d/<client>/), which clears the session + bb_sso cookie — same as the portal/admin
# pages. After logout _may_open() fails and the dashboards redirect back to the login screen.
_LOGOUT_BUTTON = (
    b'<a href="/logout" title="Log out of all dashboards" '
    b'style="position:fixed;top:14px;right:16px;z-index:2147483647;display:inline-flex;'
    b'align-items:center;gap:6px;padding:8px 13px;border-radius:999px;'
    b'font:600 13px/1 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#fff;'
    b'background:rgba(17,17,17,.82);border:1px solid rgba(255,255,255,.22);text-decoration:none;'
    b'box-shadow:0 2px 10px rgba(0,0,0,.28);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);'
    b'cursor:pointer;">'
    b'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    b'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    b'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>'
    b'<polyline points="16 17 21 12 16 7"></polyline>'
    b'<line x1="21" y1="12" x2="9" y2="12"></line></svg>Log out</a>'
)

# A self-contained Feedback widget injected into every proxied dashboard (same approach as the
# logout pill: the dashboards are 10 differently-themed third-party pages, so it is fully
# inline-styled, scoped under #bbfb*, and max z-index). A floating pill bottom-right opens a panel
# where the user types OR records a voice note (MediaRecorder; getUserMedia works because the page
# is served over the platform's https origin) and POSTs it to the platform's own /feedback. The
# client key is baked in per-dashboard at injection time (replaces __CLIENT__).
_FEEDBACK_WIDGET = (
    "<style>"
    "#bbfb-btn{position:fixed;bottom:18px;right:18px;z-index:2147483646;display:inline-flex;"
    "align-items:center;gap:7px;padding:10px 15px;border-radius:999px;border:1px solid rgba(255,255,255,.22);"
    "font:600 13px/1 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#fff;cursor:pointer;"
    "background:rgba(17,17,17,.86);box-shadow:0 2px 12px rgba(0,0,0,.32);backdrop-filter:blur(4px);"
    "-webkit-backdrop-filter:blur(4px)}"
    "#bbfb-panel{position:fixed;bottom:66px;right:18px;z-index:2147483646;width:330px;max-width:calc(100vw - 36px);"
    "display:none;flex-direction:column;gap:10px;padding:16px;border-radius:14px;"
    "background:#15171c;color:#f3f4f6;border:1px solid rgba(255,255,255,.14);box-shadow:0 12px 44px rgba(0,0,0,.5);"
    "font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}"
    "#bbfb-panel.open{display:flex}"
    "#bbfb-panel h3{margin:0;font-size:15px;font-weight:700}"
    "#bbfb-panel p.sub{margin:0;font-size:12px;color:#9ca3af}"
    "#bbfb-text{width:100%;min-height:84px;resize:vertical;padding:9px 10px;border-radius:9px;"
    "background:#0e1014;color:#f3f4f6;border:1px solid rgba(255,255,255,.16);font:inherit;outline:none}"
    "#bbfb-text:focus{border-color:#6366f1}"
    "#bbfb-name,#bbfb-deadline{width:100%;padding:9px 10px;border-radius:9px;background:#0e1014;"
    "color:#f3f4f6;border:1px solid rgba(255,255,255,.16);font:inherit;outline:none;color-scheme:dark}"
    "#bbfb-name:focus,#bbfb-deadline:focus{border-color:#6366f1}"
    ".bbfb-lbl{font-size:11px;color:#9ca3af;margin:-2px 0 -5px}"
    "#bbfb-row{display:flex;align-items:center;gap:8px}"
    ".bbfb-mini{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border-radius:9px;cursor:pointer;"
    "font:600 13px/1 inherit;border:1px solid rgba(255,255,255,.18);background:#0e1014;color:#f3f4f6}"
    ".bbfb-mini.rec{background:#7f1d1d;border-color:#ef4444}"
    "#bbfb-send{flex:1;justify-content:center;background:#6366f1;border-color:#6366f1;color:#fff}"
    "#bbfb-send:disabled{opacity:.5;cursor:default}"
    "#bbfb-status{font-size:12px;min-height:15px;color:#9ca3af}"
    "#bbfb-audio{width:100%;display:none;margin-top:2px}"
    "#bbfb-dot{width:9px;height:9px;border-radius:50%;background:#ef4444;display:inline-block;animation:bbfbpulse 1s infinite}"
    "@keyframes bbfbpulse{0%,100%{opacity:1}50%{opacity:.25}}"
    "</style>"
    "<button id='bbfb-btn' type='button' aria-label='Send feedback'>"
    "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'><path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'></path></svg>"
    "Feedback</button>"
    "<div id='bbfb-panel' role='dialog' aria-label='Send feedback'>"
    "<h3>Send feedback</h3>"
    "<p class='sub'>Type a note or record a voice message, whatever’s easiest.</p>"
    "<input id='bbfb-name' type='text' placeholder='Your name (optional)' autocomplete='name'>"
    "<textarea id='bbfb-text' placeholder='What’s working, what’s confusing, what you’d like to see…'></textarea>"
    "<p class='bbfb-lbl'>Preferred deadline (optional)</p>"
    "<input id='bbfb-deadline' type='date'>"
    "<audio id='bbfb-audio' controls></audio>"
    "<div id='bbfb-row'>"
    "<button id='bbfb-mic' type='button' class='bbfb-mini'>\U0001f3a4 Record</button>"
    "<button id='bbfb-send' type='button' class='bbfb-mini'>Send</button>"
    "</div>"
    "<div id='bbfb-status'></div>"
    "</div>"
    "<script>(function(){"
    "var CLIENT='__CLIENT__';"
    "var btn=document.getElementById('bbfb-btn'),panel=document.getElementById('bbfb-panel'),"
    "ta=document.getElementById('bbfb-text'),mic=document.getElementById('bbfb-mic'),"
    "send=document.getElementById('bbfb-send'),status=document.getElementById('bbfb-status'),"
    "audioEl=document.getElementById('bbfb-audio'),"
    "nameEl=document.getElementById('bbfb-name'),dlEl=document.getElementById('bbfb-deadline');"
    "var rec=null,chunks=[],blob=null,ctype='',timer=null,secs=0,shot=null;"
    # A typed note is NEVER lost. The commonest failure here is a dead session (see feedback_submit),
    # and recovering from it means opening the login page - so the draft has to survive a reload of
    # this tab, not just a failed fetch. Per-client key, per-origin storage, every access guarded:
    # a browser with site data blocked throws on the accessor itself.
    "var DKEY='bbfb.draft.'+CLIENT;"
    "function draftSave(){try{localStorage.setItem(DKEY,JSON.stringify("
    "{t:ta.value||'',n:nameEl.value||'',d:dlEl.value||''}));}catch(e){}}"
    "function draftClear(){try{localStorage.removeItem(DKEY);}catch(e){}}"
    "function draftLoad(){try{var d=JSON.parse(localStorage.getItem(DKEY)||'null');if(!d)return;"
    "if(d.t)ta.value=d.t;if(d.n)nameEl.value=d.n;if(d.d)dlEl.value=d.d;}catch(e){}}"
    "draftLoad();ta.addEventListener('input',draftSave);nameEl.addEventListener('input',draftSave);"
    "dlEl.addEventListener('change',draftSave);"
    # Signed-out state: flag it on the pill (so it is visible without opening the panel) and put the
    # way out - a link to the login page - directly in the panel.
    "function signedOut(on){if(on){btn.style.borderColor='#f59e0b';btn.title='Sign-in expired';"
    "status.innerHTML=\"You are signed out - this tab\\u2019s sign-in expired. \""
    "+\"<a href='/' target='_blank' rel='noopener' style='color:#fbbf24'>Sign in again</a>\""
    "+\", then press Send. Your note is saved here.\";}"
    "else{btn.style.borderColor='';btn.title='';}}"
    # Probe on OPEN, not on Send: being told you are signed out before writing a paragraph is the
    # whole point. Best-effort - a failed probe never blocks the panel or the post.
    "function probe(){fetch('/feedback/ping?client='+encodeURIComponent(CLIENT),"
    "{credentials:'same-origin',cache:'no-store'}).then(function(r){signedOut(r.status===401);})"
    ".catch(function(){});}"
    "btn.onclick=function(){var opening=!panel.classList.contains('open');panel.classList.toggle('open');"
    "if(opening){ta.focus();grabShot();probe();}};"
    # Also probe PASSIVELY, so a tab that died overnight flags itself instead of looking healthy: the
    # dashboard's own 5-min data.json poll swallows its redirect in a bare catch, so the pill is the
    # only place a stale tab can show. On re-focus (the "back from lunch" moment) and every 10 min.
    "document.addEventListener('visibilitychange',function(){if(!document.hidden)probe();});"
    "setInterval(probe,10*60*1000);probe();"
    # Lazily pull html2canvas (only when the panel first opens) and snapshot the visible viewport as
    # a compact JPEG, with the widget itself hidden so it's not in the shot. Best-effort: any failure
    # (no network, a CORS-tainted canvas) just leaves shot=null and the note sends without an image.
    "function loadH2C(){return new Promise(function(res){if(window.html2canvas)return res();"
    "var s=document.createElement('script');s.src='https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';"
    "s.onload=res;s.onerror=res;document.head.appendChild(s);});}"
    "function grabShot(){shot=null;loadH2C().then(function(){if(!window.html2canvas)return;"
    "var dB=btn.style.display,dP=panel.style.display;btn.style.display='none';panel.style.display='none';"
    "return window.html2canvas(document.body,{useCORS:true,logging:false,scale:1,"
    "x:window.scrollX,y:window.scrollY,width:window.innerWidth,height:window.innerHeight}).then(function(c){"
    "c.toBlob(function(b){shot=b;},'image/jpeg',0.82);}).catch(function(){}).finally(function(){"
    "btn.style.display=dB;panel.style.display=dP;});});}"
    "function stopRec(){if(rec&&rec.state!=='inactive')rec.stop();}"
    "function resetTimer(){clearInterval(timer);timer=null;secs=0;}"
    "mic.onclick=function(){"
    "if(rec&&rec.state==='recording'){stopRec();return;}"
    "if(!navigator.mediaDevices||!window.MediaRecorder){status.textContent='Voice recording isn\\u2019t supported in this browser \\u2014 please type instead.';return;}"
    "navigator.mediaDevices.getUserMedia({audio:true}).then(function(stream){"
    "chunks=[];blob=null;rec=new MediaRecorder(stream);ctype=rec.mimeType||'audio/webm';"
    "rec.ondataavailable=function(e){if(e.data&&e.data.size)chunks.push(e.data);};"
    "rec.onstop=function(){stream.getTracks().forEach(function(t){t.stop();});"
    "blob=new Blob(chunks,{type:ctype});audioEl.src=URL.createObjectURL(blob);audioEl.style.display='block';"
    "mic.classList.remove('rec');mic.textContent='\\ud83c\\udfa4 Re-record';resetTimer();status.textContent='Voice note ready \\u2014 add a note if you like, then Send.';};"
    "rec.start();mic.classList.add('rec');mic.innerHTML='<span id=\"bbfb-dot\"></span> Stop (0s)';"
    "secs=0;timer=setInterval(function(){secs++;mic.innerHTML='<span id=\"bbfb-dot\"></span> Stop ('+secs+'s)';if(secs>=120)stopRec();},1000);"
    "status.textContent='Recording\\u2026 (max 2 min)';"
    "}).catch(function(){status.textContent='Microphone blocked \\u2014 allow access or just type your feedback.';});"
    "};"
    "send.onclick=function(){"
    "var txt=(ta.value||'').trim();"
    "if(!txt&&!blob){status.textContent='Add a note or a voice message first.';return;}"
    "send.disabled=true;status.textContent='Sending\\u2026';"
    "var fd=new FormData();fd.append('client',CLIENT);fd.append('text',txt);fd.append('page',location.pathname);"
    "fd.append('reporter',(nameEl.value||'').trim());fd.append('deadline',dlEl.value||'');"
    "if(blob)fd.append('audio',blob,'voice.'+((ctype.indexOf('mp4')>-1)?'m4a':(ctype.indexOf('ogg')>-1)?'ogg':'webm'));"
    "if(shot)fd.append('screenshot',shot,'shot.jpg');"
    # Report what actually went wrong. A single "could not send - please try again" for every failure
    # is what turned one expired session into a client believing the feature was broken: retrying is
    # the one thing that can never fix an auth failure. 401 => the recoverable signed-out path
    # (draft kept, link to sign in, then Send works); anything else => the server's own message.
    "fetch('/feedback',{method:'POST',body:fd,credentials:'same-origin'}).then(function(r){"
    "if(r.status===401){signedOut(true);send.disabled=false;return;}"
    "if(!r.ok){return r.json().catch(function(){return null;}).then(function(j){"
    "status.textContent=(j&&j.error)?j.error:('Could not send (error '+r.status+') - please try again.');"
    "send.disabled=false;});}"
    "signedOut(false);draftClear();status.textContent='Thanks - your feedback was sent! \\u2713';"
    "ta.value='';nameEl.value='';dlEl.value='';blob=null;chunks=[];shot=null;audioEl.style.display='none';mic.textContent='\\ud83c\\udfa4 Record';"
    "setTimeout(function(){panel.classList.remove('open');status.textContent='';send.disabled=false;},1600);"
    "}).catch(function(){status.textContent='Could not send - check your connection and try again. Your note is saved here.';send.disabled=false;});"
    "};"
    "})();</script>"
).encode()


def _feedback_widget(client):
    return _FEEDBACK_WIDGET.replace(b"__CLIENT__", client.encode())


# The staff-only Internal Notes + Assistant widget, injected ONLY when _internal_allowed(client)
# (superadmin / admin / owning agency - clients never receive a byte of it). Same approach as the
# feedback widget: fully inline-styled, scoped under #bbin-*, max z-index, client key baked in at
# injection time.
# - "Internal Notes" is a REAL TAB: the script clones the last `.tab` in the dashboard's `.tabs`
#   rail (every dashboard uses that markup), strips its id/onclick/data-* wiring so the host
#   dashboard's own tab logic ignores it, labels it "Internal Notes" and appends it. Clicking it
#   opens a full-screen overlay holding the notes UI (list / add / edit / delete via
#   /internal-notes/<c>); clicking any native tab, the backdrop, Esc or the X closes it. A
#   MutationObserver re-appends the tab on dashboards that REBUILD their rail per render
#   (schneider / schneiderlqai). Fallback when no rail is found: a floating pill bottom-left.
# - If the page contains #bbNotesMount (cloudflare's native Admin-View "Internal Notes" tab), the
#   notes UI mounts inline there instead and NO generic tab is injected (it would duplicate).
# - "Assistant" stays a floating pill bottom-left (the internal chatbot - /internal-chat/<c>,
#   renders the model's thinking as a collapsible block per reply, and refreshes the notes list
#   when the assistant edits notes via its tools).
_INTERNAL_WIDGET = (
    "<style>"
    "#bbin-dock{position:fixed;bottom:18px;left:18px;z-index:2147483645;display:flex;gap:8px}"
    ".bbin-pill{display:inline-flex;align-items:center;gap:7px;padding:10px 15px;border-radius:999px;"
    "border:1px solid rgba(255,205,112,.38);font:600 13px/1 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
    "color:#ffdf9e;cursor:pointer;background:rgba(26,21,12,.9);box-shadow:0 2px 12px rgba(0,0,0,.32);"
    "backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}"
    ".bbin-panel{position:fixed;bottom:66px;left:18px;z-index:2147483645;width:420px;max-width:calc(100vw - 36px);"
    "max-height:min(74vh,640px);display:none;flex-direction:column;border-radius:14px;overflow:hidden;"
    "background:#14161b;color:#f3f4f6;border:1px solid rgba(255,255,255,.14);box-shadow:0 12px 44px rgba(0,0,0,.5);"
    "font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}"
    ".bbin-panel.open{display:flex}"
    ".bbin-hd{display:flex;align-items:center;gap:8px;padding:13px 16px;border-bottom:1px solid rgba(255,255,255,.1)}"
    ".bbin-hd h3{margin:0;font-size:15px;font-weight:700;flex:1}"
    ".bbin-badge{font:700 10px/1 system-ui,sans-serif;letter-spacing:.09em;color:#1a150c;background:#e8b955;"
    "border-radius:5px;padding:4px 7px}"
    ".bbin-x{background:none;border:none;color:#9ca3af;font-size:19px;cursor:pointer;padding:0 2px;line-height:1}"
    "#bbin-notes-body{padding:14px 16px;overflow-y:auto}"
    "#bbin-clog{flex:1;min-height:220px;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:10px}"
    "#bbin-crow{display:flex;gap:8px;padding:12px 16px;border-top:1px solid rgba(255,255,255,.1)}"
    "#bbin-cin{flex:1;resize:none;padding:9px 10px;border-radius:9px;background:#0e1014;color:#f3f4f6;"
    "border:1px solid rgba(255,255,255,.16);font:inherit;outline:none}"
    "#bbin-cin:focus{border-color:#e8b955}"
    ".bbin-send{padding:8px 14px;border-radius:9px;border:1px solid #e8b955;background:#e8b955;color:#1a150c;"
    "font:700 13px/1 inherit;cursor:pointer;align-self:flex-end}"
    ".bbin-send:disabled{opacity:.5;cursor:default}"
    ".bbin-mic{padding:8px 11px;border-radius:9px;border:1px solid rgba(255,255,255,.18);background:#0e1014;"
    "color:#f3f4f6;font:700 13px/1 inherit;cursor:pointer;align-self:flex-end}"
    ".bbin-mic.rec{background:#7f1d1d;border-color:#ef4444;animation:bbinpulse 1s infinite}"
    "@keyframes bbinpulse{0%,100%{opacity:1}50%{opacity:.55}}"
    ".bbin-mu{align-self:flex-end;max-width:86%;background:rgba(232,185,85,.16);border:1px solid rgba(232,185,85,.3);"
    "border-radius:12px 12px 3px 12px;padding:8px 11px;font-size:13px;white-space:pre-wrap}"
    ".bbin-ma{align-self:flex-start;max-width:92%;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.1);"
    "border-radius:12px 12px 12px 3px;padding:9px 12px;font-size:13px}"
    ".bbin-ma code{background:rgba(255,255,255,.09);border-radius:4px;padding:1px 4px;font-size:12px}"
    ".bbin-wait:after{display:inline-block;content:'';animation:bbindots 1.2s steps(4,end) infinite}"
    "@keyframes bbindots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}"
    "#bbin-ovl{position:fixed;inset:0;z-index:2147483644;display:none;align-items:flex-start;"
    "justify-content:center;padding:6vh 18px 18px;background:rgba(0,0,0,.55);"
    "backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}"
    "#bbin-ovl.open{display:flex}"
    "#bbin-ovl-panel{width:min(880px,94vw);max-height:84vh;display:flex;flex-direction:column;"
    "border-radius:14px;overflow:hidden;background:#14161b;color:#f3f4f6;"
    "border:1px solid rgba(255,255,255,.14);box-shadow:0 18px 60px rgba(0,0,0,.6);"
    "font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}"
    "#bbin-ovl-body{padding:16px 20px;overflow-y:auto}"
    "</style>"
    "<div id='bbin-dock'>"
    "<button id='bbin-notes-btn' class='bbin-pill' type='button'>"
    "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'><path d='M12 20h9'></path>"
    "<path d='M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z'></path></svg>Internal Notes</button>"
    "<button id='bbin-chat-btn' class='bbin-pill' type='button'>"
    "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'><path d='M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 "
    "8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5 "
    "a8.48 8.48 0 0 1 8 8v.5z'></path></svg>Assistant</button>"
    "</div>"
    "<div id='bbin-notes' class='bbin-panel' role='dialog' aria-label='Internal notes'>"
    "<div class='bbin-hd'><h3>Internal Notes</h3><span class='bbin-badge'>INTERNAL</span>"
    "<button class='bbin-x' id='bbin-notes-x' type='button' aria-label='Close'>&times;</button></div>"
    "<div id='bbin-notes-body'></div>"
    "</div>"
    "<div id='bbin-ovl' role='dialog' aria-label='Internal notes'>"
    "<div id='bbin-ovl-panel'>"
    "<div class='bbin-hd'><h3>Internal Notes</h3><span class='bbin-badge'>INTERNAL</span>"
    "<button class='bbin-x' id='bbin-ovl-x' type='button' aria-label='Close'>&times;</button></div>"
    "<div id='bbin-ovl-body'></div>"
    "</div></div>"
    "<div id='bbin-chat' class='bbin-panel' role='dialog' aria-label='Internal assistant'>"
    "<div class='bbin-hd'><h3>Assistant</h3><span class='bbin-badge'>INTERNAL</span>"
    "<button class='bbin-x' id='bbin-chat-x' type='button' aria-label='Close'>&times;</button></div>"
    "<div id='bbin-clog'></div>"
    "<div id='bbin-crow'><textarea id='bbin-cin' rows='2' "
    "placeholder='Ask about any number on this dashboard...'></textarea>"
    "<button id='bbin-cmic' class='bbin-mic' type='button' title='Speak your question' "
    "aria-label='Voice input'>\U0001f3a4</button>"
    "<button id='bbin-csend' class='bbin-send' type='button'>Send</button></div>"
    "</div>"
    "<script>(function(){"
    "var CLIENT='__CLIENT__';"
    "var TA='width:100%;min-height:64px;resize:vertical;padding:9px 10px;border-radius:9px;background:#0e1014;"
    "color:#f3f4f6;border:1px solid rgba(255,255,255,.16);font:inherit;font-size:13px;outline:none;box-sizing:border-box';"
    "var BTN='align-self:flex-start;padding:8px 14px;border-radius:9px;border:1px solid #e8b955;background:#e8b955;"
    "color:#1a150c;font:700 13px/1 system-ui,sans-serif;cursor:pointer';"
    "var LNK='background:none;border:none;color:#9ca3af;font:600 11px/1 system-ui,sans-serif;cursor:pointer;padding:2px 4px';"
    "var CARD='border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:10px 12px;background:rgba(255,255,255,.03);"
    "display:flex;flex-direction:column;gap:6px';"
    "function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')"
    ".replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}"
    "function md(s){s=esc(s);s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<b>$1</b>')"
    ".replace(/`([^`]+)`/g,'<code>$1</code>');return s.replace(/\\n/g,'<br>');}"
    "function fmtTs(t){if(!t)return'';var d=new Date(t*1000);"
    "return d.toLocaleDateString()+' '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}"
    "function post(u,b){return fetch(u,{method:'POST',credentials:'same-origin',"
    "headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})"
    ".then(function(r){return r.json();}).catch(function(){return null;});}"
    # ---- notes: one shared model, rendered into every registered list container ----
    "var notes=[],LISTS=[];"
    "function loadNotes(){fetch('/internal-notes/'+CLIENT,{credentials:'same-origin'})"
    ".then(function(r){return r.json();}).then(function(j){if(j&&j.ok){notes=j.notes||[];LISTS.forEach(renderList);}})"
    ".catch(function(){});}"
    "function mkLink(t){var b=document.createElement('button');b.type='button';b.textContent=t;"
    "b.setAttribute('style',LNK);return b;}"
    "function noteCard(n){"
    "var card=document.createElement('div');card.setAttribute('style',CARD);"
    "var meta=document.createElement('div');meta.setAttribute('style',"
    "'display:flex;align-items:center;gap:6px;font-size:11px;color:#9ca3af');"
    "var who=document.createElement('span');who.setAttribute('style','flex:1');"
    "who.textContent=(n.author||'unknown')+' \\u00b7 '+fmtTs(n.created_at)+"
    "((n.updated_at||0)>(n.created_at||0)?' \\u00b7 edited':'');"
    "var ed=mkLink('Edit'),del=mkLink('Delete');"
    "meta.appendChild(who);meta.appendChild(ed);meta.appendChild(del);"
    "var body=document.createElement('div');body.setAttribute('style',"
    "'white-space:pre-wrap;font-size:13px;color:#e5e7eb;overflow-wrap:anywhere');body.textContent=n.text;"
    "card.appendChild(meta);card.appendChild(body);"
    "del.onclick=function(){if(!confirm('Delete this internal note?'))return;"
    "post('/internal-notes/'+CLIENT+'/delete',{id:n.id}).then(loadNotes);};"
    "ed.onclick=function(){"
    "if(card.querySelector('textarea'))return;"
    "var ta=document.createElement('textarea');ta.value=n.text;ta.setAttribute('style',TA);"
    "var row=document.createElement('div');row.setAttribute('style','display:flex;gap:8px');"
    "var sv=document.createElement('button');sv.type='button';sv.textContent='Save';sv.setAttribute('style',BTN);"
    "var cx=mkLink('Cancel');"
    "row.appendChild(sv);row.appendChild(cx);"
    "card.replaceChild(ta,body);card.appendChild(row);ta.focus();"
    "cx.onclick=function(){card.replaceChild(body,ta);card.removeChild(row);};"
    "sv.onclick=function(){var t=ta.value.trim();if(!t)return;sv.disabled=true;"
    "post('/internal-notes/'+CLIENT+'/edit',{id:n.id,text:t}).then(loadNotes);};};"
    "return card;}"
    "function renderList(list){list.innerHTML='';"
    "if(!notes.length){var e=document.createElement('div');"
    "e.setAttribute('style','font-size:12px;color:#9ca3af');"
    "e.textContent='No internal notes yet - add the first one above.';list.appendChild(e);return;}"
    "notes.forEach(function(n){list.appendChild(noteCard(n));});}"
    "function buildNotesUI(host){"
    "var wrap=document.createElement('div');wrap.setAttribute('style',"
    "'display:flex;flex-direction:column;gap:12px;font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif');"
    "var ta=document.createElement('textarea');ta.setAttribute('style',TA);"
    "ta.placeholder='Add an internal note... (never visible to the client)';"
    "var add=document.createElement('button');add.type='button';add.textContent='Add note';add.setAttribute('style',BTN);"
    "add.onclick=function(){var t=ta.value.trim();if(!t)return;add.disabled=true;"
    "post('/internal-notes/'+CLIENT,{text:t}).then(function(j){add.disabled=false;"
    "if(j&&j.ok){ta.value='';loadNotes();}});};"
    "var list=document.createElement('div');list.setAttribute('style','display:flex;flex-direction:column;gap:8px');"
    "wrap.appendChild(ta);wrap.appendChild(add);wrap.appendChild(list);host.appendChild(wrap);"
    "LISTS.push(list);renderList(list);}"
    # ---- panels ----
    "function el(i){return document.getElementById(i);}"
    "var np=el('bbin-notes'),cp=el('bbin-chat');"
    "el('bbin-notes-btn').onclick=function(){cp.classList.remove('open');np.classList.toggle('open');};"
    "el('bbin-chat-btn').onclick=function(){np.classList.remove('open');cp.classList.toggle('open');"
    "el('bbin-cin').focus();};"
    "el('bbin-notes-x').onclick=function(){np.classList.remove('open');};"
    "el('bbin-chat-x').onclick=function(){cp.classList.remove('open');};"
    # ---- the Internal Notes TAB: clone a native .tab, open a full-screen overlay ----
    "var ovl=el('bbin-ovl');"
    "function injectTab(){"
    "var rails=document.querySelectorAll('.tabs'),rail=null,model=null;"
    "for(var i=0;i<rails.length;i++){var ts=rails[i].querySelectorAll('.tab');"
    "if(ts.length){rail=rails[i];model=ts[ts.length-1];break;}}"
    "if(!rail)return false;"
    "var t=model.cloneNode(true);"
    "['id','onclick','data-tab','data-view','aria-selected','style'].forEach(function(a){t.removeAttribute(a);});"
    "['active','on','selected','current'].forEach(function(c){t.classList.remove(c);});"
    "t.id='bbinTab';t.textContent='Internal Notes';t.title='Internal only - clients never see this tab';"
    "var ac=rail.querySelector('.tab.active')?'active':rail.querySelector('.tab.on')?'on':"
    "rail.querySelector('.tab.selected')?'selected':'';"
    "var remembered=null;"
    "function openOvl(){ovl.classList.add('open');"
    "if(ac){remembered=null;rail.querySelectorAll('.tab.'+ac).forEach(function(b){"
    "if(b!==t){remembered=b;b.classList.remove(ac);}});t.classList.add(ac);}}"
    "function closeOvl(){ovl.classList.remove('open');"
    "if(ac){t.classList.remove(ac);"
    "if(remembered&&!rail.querySelector('.tab.'+ac))remembered.classList.add(ac);}}"
    # capture-phase handler + stopPropagation: the host dashboard's own delegated rail listeners
    # (resetdata/tlm read e.target.dataset.tab) must never see a click on our tab
    "t.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();"
    "if(ovl.classList.contains('open')){closeOvl();}else{openOvl();}},true);"
    "rail.addEventListener('click',function(e){"
    "var tb=e.target&&e.target.closest?e.target.closest('.tab'):null;"
    "if(tb&&tb!==t&&ovl.classList.contains('open'))closeOvl();});"
    "rail.appendChild(t);"
    # schneider/schneiderlqai rebuild the rail every render - re-append when wiped
    "new MutationObserver(function(){if(!rail.contains(t))rail.appendChild(t);})"
    ".observe(rail,{childList:true});"
    "el('bbin-ovl-x').onclick=closeOvl;"
    "ovl.addEventListener('click',function(e){if(e.target===ovl)closeOvl();});"
    "document.addEventListener('keydown',function(e){"
    "if(e.key==='Escape'&&ovl.classList.contains('open'))closeOvl();});"
    "return true;}"
    "var mount=document.getElementById('bbNotesMount');"
    "if(mount){var h=document.createElement('div');"
    "h.setAttribute('style','font-size:12px;color:#9ca3af;margin:0 0 10px');"
    "h.textContent='Visible to Bidbrain staff and the owning agency only - never the client.';"
    "mount.appendChild(h);buildNotesUI(mount);"
    "el('bbin-notes-btn').style.display='none';}"
    "else if(injectTab()){buildNotesUI(el('bbin-ovl-body'));"
    "el('bbin-notes-btn').style.display='none';}"
    "else{buildNotesUI(el('bbin-notes-body'));}"
    "loadNotes();"
    # ---- assistant chat (thinking shown per reply) ----
    "var clog=el('bbin-clog'),cin=el('bbin-cin'),csend=el('bbin-csend');"
    "var hist=[],busy=false;"
    "function bubble(cls,html){var d=document.createElement('div');d.className=cls;d.innerHTML=html;"
    "clog.appendChild(d);clog.scrollTop=clog.scrollHeight;return d;}"
    "bubble('bbin-ma','Hi - ask me about any number on this dashboard. I know the data behind every '"
    "+'figure and where it comes from (raw source \\u2192 BigQuery view \\u2192 dashboard), and I can '"
    "+'add or edit the internal notes for you.');"
    "function think(t){return '<details style=\"margin:0 0 8px;border:1px dashed rgba(232,185,85,.35);'"
    "+'border-radius:8px;padding:6px 9px;background:rgba(232,185,85,.05)\">'"
    "+'<summary style=\"cursor:pointer;font:700 10px/1 system-ui,sans-serif;letter-spacing:.09em;'"
    "+'color:#e8b955\">THINKING</summary>'"
    "+'<div style=\"margin-top:6px;font-size:12px;color:#9ca3af;white-space:pre-wrap\">'+esc(t)+'</div></details>';}"
    "function doSend(){var q=cin.value.trim();if(!q||busy)return;busy=true;csend.disabled=true;"
    "hist.push({role:'user',content:q});bubble('bbin-mu',esc(q));cin.value='';"
    "var p=bubble('bbin-ma','<span class=\"bbin-wait\" style=\"color:#9ca3af\">Thinking</span>');"
    "post('/internal-chat/'+CLIENT,{messages:hist}).then(function(j){busy=false;csend.disabled=false;"
    "if(!j||!j.ok){p.innerHTML='<span style=\"color:#f87171\">'"
    "+esc((j&&j.error)||'Could not reach the assistant - please try again.')+'</span>';hist.pop();return;}"
    "var h='';if(j.thinking)h+=think(j.thinking);h+=md(j.answer);"
    "(j.actions||[]).forEach(function(a){h+='<div style=\"margin-top:7px;font:600 11px/1 system-ui,sans-serif;"
    "color:#7dd3a0\">\\u270e '+esc(a)+'</div>';});"
    "p.innerHTML=h;clog.scrollTop=clog.scrollHeight;"
    "hist.push({role:'assistant',content:j.answer});"
    "if(j.notes_changed)loadNotes();});}"
    "csend.onclick=doSend;"
    "cin.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();doSend();}});"
    # ---- voice input: Chrome's free built-in Web Speech API (webkitSpeechRecognition).
    # Dictation lands in the textarea for review - Send still submits. Button hides itself in
    # browsers without the API (Firefox); mic permission errors reset the button quietly.
    "var cmic=el('bbin-cmic');"
    "var SR=window.SpeechRecognition||window.webkitSpeechRecognition;"
    "if(!SR){cmic.style.display='none';}else{"
    "var srec=null,srBase='';"
    "function srStop(){if(srec){try{srec.stop();}catch(e){}}}"
    "function srReset(){cmic.classList.remove('rec');cmic.textContent='\\ud83c\\udfa4';srec=null;}"
    "cmic.onclick=function(){"
    "if(srec){srStop();return;}"
    "srec=new SR();srec.continuous=true;srec.interimResults=true;"
    "srec.lang=navigator.language||'en-AU';"
    "srBase=cin.value?cin.value.replace(/\\s+$/,'')+' ':'';"
    "srec.onresult=function(ev){var txt='';"
    "for(var i=0;i<ev.results.length;i++)txt+=ev.results[i][0].transcript;"
    "cin.value=srBase+txt;};"
    "srec.onerror=function(ev){srReset();"
    "if(ev.error==='not-allowed')cin.placeholder='Microphone blocked - allow access or type instead.';};"
    "srec.onend=srReset;"
    "srec.start();cmic.classList.add('rec');cmic.textContent='\\u25a0';cin.focus();};"
    "}"
    "})();</script>"
).encode()


def _internal_widget(client):
    return _INTERNAL_WIDGET.replace(b"__CLIENT__", client.encode())


def _spend_mult_script(client):
    """A tiny <script> the proxy injects into every proxied dashboard, exposing this client's
    per-channel spend multiplier as window.BB_SPEND_MULT (client-billed "spent to date" vs real
    media cost). The dashboard's vendored gross-up shim reads it. {} when unset → shim is a no-op."""
    import json
    # EXTERNAL tenants never receive the markup factor. It is the ratio between what we pay the
    # platform and what the client is billed, so shipping it alongside the raw spend in data.json
    # would let an outside agency derive our margin exactly. Suppressed at the SOURCE (nothing is
    # injected), not merely hidden in the UI.
    # CONSEQUENCE, FLAGGED FOR A COMMERCIAL DECISION: with no factor the dashboard renders RAW
    # media cost, which is what we pay - NOT the grossed figure the client sees on the same
    # dashboard. Showing the billed figure instead would mean grossing the payload server-side
    # (and never shipping raw). See EXTRABLACK_EXPOSURE_2.md - "Commercial decisions".
    m = {} if not _ext_setting("show_spend_multiplier") else store.get_spend_multipliers(client)
    payload = json.dumps(m).encode()
    return (b"<script>window.BB_SPEND_MULT=Object.assign(window.BB_SPEND_MULT||{}," + payload
            + b");</script>")


def _dev_flag_script():
    """Expose window.BB_DEV=true to the proxied dashboard IFF the viewer may see INTERNAL tooling:
    an admin / super-admin session, or the agency portal of the client's OWNING agency (Transmission
    owns the CS clients). The dashboards' dev-mode toggle (unprocessed/New leads + a Source-ID filter)
    stays hidden unless this is set, so client and other-agency sessions never see it. Nothing is
    injected for those, so window.BB_DEV stays undefined (falsey) and the client-facing view is
    unchanged. Harmless for dashboards without a dev mode — they just ignore the global."""
    kind = session.get("kind")
    allowed = kind in ("admin", "superadmin") or (
        kind == "agency" and session.get("agency_slug") == "transmission")
    return b"<script>window.BB_DEV=true;</script>" if allowed else b""


# --- Internal Notes + Internal AI assistant (staff-only, injected by the proxy) --------------
# Visible ONLY to superadmin / admin / the client's OWNING agency (per _may_open) — never to a
# client session, and never on a raw <c>-dash run.app URL (the widget only exists through the
# proxy). Notes live in the platform's private bucket (internal_notes.py); the assistant is a
# Gemini turn over the dashboard's LIVE data.json + a committed lineage digest (internal_chat.py),
# with tool access to the same notes.
def _internal_allowed(client):
    kind = session.get("kind")
    if kind in ("superadmin", "admin"):
        return _may_open(client)
    if kind == "agency":
        # Dual-visibility gate: an EXTERNAL agency never receives the staff-only Internal Notes +
        # Assistant widget — it exposes internal team notes and discusses raw-vs-billed spend
        # openly, which must not reach an outside agency that merely shares visibility of a
        # client. Internal agencies are unaffected (resolves True).
        if not _ext_setting("internal_notes"):
            return False
        return _may_open(client)
    return False


def _internal_flag_script(client):
    """Expose window.BB_INTERNAL=true to the proxied dashboard IFF this session ALSO receives the
    staff-only Internal Notes + Assistant widget - same `_internal_allowed` predicate, evaluated in
    the same request, so the flag and the widget can never disagree.

    Why it exists: a dashboard that renders its OWN internal-notes surface (cloudflare's native
    "Internal Notes" tab, which hosts #bbNotesMount) has no other way to know whether the widget
    will arrive. Without this it renders the heading and an empty mount - which is exactly what
    Transmission saw after `internal_notes:false` (an empty shell that reads as broken). Injected in
    <head>, BEFORE the dashboard's own scripts build their tab rail, so nothing flashes.

    Nothing is injected otherwise, so window.BB_INTERNAL stays undefined (falsey). Dashboards
    without such a surface ignore it, exactly like window.BB_DEV. NOT a permission - the notes
    endpoints enforce _internal_allowed server-side regardless of what any page believes."""
    return b"<script>window.BB_INTERNAL=true;</script>" if _internal_allowed(client) else b""


def _actor():
    """Who to record as a note's author: the signed-in email when there is one, else the tier."""
    return session.get("email") or session.get("kind") or ""


@app.get("/internal-notes/<client>")
def internal_notes_list(client):
    if not _internal_allowed(client):
        return jsonify(ok=False, error="not allowed"), 403
    try:
        return jsonify(ok=True, notes=internal_notes.list_notes(client))
    except Exception:
        app.logger.exception("internal notes list failed")
        return jsonify(ok=False, error="could not load notes"), 500


@app.post("/internal-notes/<client>")
def internal_notes_add(client):
    if not _internal_allowed(client):
        return jsonify(ok=False, error="not allowed"), 403
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="empty note"), 400
    try:
        return jsonify(ok=True, note=internal_notes.add_note(client, text, author=_actor()))
    except Exception:
        app.logger.exception("internal note add failed")
        return jsonify(ok=False, error="could not save note"), 500


@app.post("/internal-notes/<client>/edit")
def internal_notes_edit(client):
    if not _internal_allowed(client):
        return jsonify(ok=False, error="not allowed"), 403
    j = request.get_json(silent=True) or {}
    text = (j.get("text") or "").strip()
    if not text or not j.get("id"):
        return jsonify(ok=False, error="id and text required"), 400
    try:
        rec = internal_notes.edit_note(client, j["id"], text, author=_actor())
    except Exception:
        app.logger.exception("internal note edit failed")
        return jsonify(ok=False, error="could not save note"), 500
    if rec is None:
        return jsonify(ok=False, error="no such note"), 404
    return jsonify(ok=True, note=rec)


@app.post("/internal-notes/<client>/delete")
def internal_notes_delete(client):
    if not _internal_allowed(client):
        return jsonify(ok=False, error="not allowed"), 403
    j = request.get_json(silent=True) or {}
    try:
        ok = internal_notes.delete_note(client, j.get("id") or "")
    except Exception:
        app.logger.exception("internal note delete failed")
        return jsonify(ok=False, error="could not delete note"), 500
    return (jsonify(ok=True) if ok else (jsonify(ok=False, error="no such note"), 404))


_CHAT_DATA_CACHE = {}   # client -> (fetched_at, data.json text); 5-min TTL keeps chat turns snappy


def _upstream_data_json(client):
    """The client's live data.json, fetched through the same upstream login the proxy uses."""
    now = time.time()
    hit = _CHAT_DATA_CACHE.get(client)
    if hit and now - hit[0] < 300:
        return hit[1]
    url = f"{_upstream_base(client)}/data.json"
    hdrs = _tool_headers(client)
    cookies = _UPSTREAM_COOKIES.get(client) or _upstream_login(client)
    r = requests.get(url, cookies=cookies, headers=hdrs, timeout=30)
    if r.status_code == 401:                       # cached upstream session expired -> re-login once
        _UPSTREAM_PW.pop(client, None)
        r = requests.get(url, cookies=_upstream_login(client), headers=hdrs, timeout=30)
    r.raise_for_status()
    _CHAT_DATA_CACHE[client] = (now, r.text)
    return r.text


@app.post("/internal-chat/<client>")
def internal_chat_turn(client):
    if not _internal_allowed(client):
        return jsonify(ok=False, error="not allowed"), 403
    if not internal_chat.enabled():
        return jsonify(ok=False, error="assistant not configured (GEMINI_API_KEY unset)"), 503
    msgs = (request.get_json(silent=True) or {}).get("messages")
    if not isinstance(msgs, list) or not msgs:
        return jsonify(ok=False, error="no messages"), 400
    try:
        data_txt = _upstream_data_json(client)
    except Exception:                               # answer from lineage/notes alone rather than 500
        app.logger.exception("internal chat: data.json fetch failed")
        data_txt = "(live data.json unavailable right now)"
    try:
        res = internal_chat.chat(client, msgs, data_txt, author=_actor())
    except Exception:
        app.logger.exception("internal chat turn failed")
        return jsonify(ok=False, error="assistant error - please try again"), 502
    return jsonify(ok=True, **res)


def _upstream_base(client):
    c = store.get_client(client) or getattr(cfg, "TOOLS", {}).get(client)   # +TOOLS fallback (registry-free)
    url = (c or {}).get("url", "")
    return url.rstrip("/") if url else None


def _upstream_pw(client):
    if client not in _UPSTREAM_PW:
        from google.cloud import secretmanager
        sm = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT}/secrets/{client}-dash-password/versions/latest"
        _UPSTREAM_PW[client] = sm.access_secret_version(name=name).payload.data.decode().strip()
    return _UPSTREAM_PW[client]


# --- super-admin: rotate a dashboard's real password (write secret + restart its service) ----
def _add_secret_version(secret_id, value):
    """Add a new version to <secret_id>. Needs roles/secretmanager.secretVersionAdder on the
    platform SA (granted by scripts/enable_super_admin.ps1)."""
    from google.cloud import secretmanager
    sm = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{PROJECT}/secrets/{secret_id}"
    sm.add_secret_version(parent=parent, payload={"data": value.encode()})


def _restart_service(service):
    """Force a new Cloud Run revision of <service> so it re-reads its :latest secrets. Bumps a
    benign env var on the revision template (leaving the secret-backed envs untouched). Needs
    roles/run.developer + roles/iam.serviceAccountUser on that service's runtime SA."""
    from google.cloud import run_v2
    rc = run_v2.ServicesClient()
    name = f"projects/{PROJECT}/locations/{REGION}/services/{service}"
    svc = rc.get_service(name=name)
    stamp = str(int(time.time()))
    env = svc.template.containers[0].env
    for e in env:
        if e.name == "PW_ROTATED_AT":
            e.value = stamp
            break
    else:
        env.append(run_v2.EnvVar(name="PW_ROTATED_AT", value=stamp))
    svc.template.revision = ""           # let Cloud Run auto-name the new revision
    rc.update_service(service=svc).result(timeout=300)


_TOOL_TOKENS = {}   # audience -> (token, expiry)


def _tool_headers(client):
    """Org-private tools (config.TOOLS) sit behind Cloud Run IAM. The platform SA (run.invoker on
    the service) mints an ID token for the service's own URL as audience -> an Authorization header.
    Returns {} for normal client dashboards (public run.app), so their proxying is unchanged."""
    if client not in getattr(cfg, "TOOLS", {}):
        return {}
    aud = _upstream_base(client)
    tok, exp = _TOOL_TOKENS.get(aud, (None, 0))
    if not tok or exp < time.time() + 60:
        from google.oauth2 import id_token
        from google.auth.transport.requests import Request as GAReq
        tok = id_token.fetch_id_token(GAReq(), aud)
        _TOOL_TOKENS[aud] = (tok, time.time() + 3300)   # ~55 min (ID tokens live 1h)
    return {"Authorization": f"Bearer {tok}"}


def _upstream_login(client):
    base = _upstream_base(client)
    r = requests.post(f"{base}/login", data={"password": _upstream_pw(client)},
                      headers=_tool_headers(client),          # +IAM token for private tools ({} otherwise)
                      allow_redirects=False, timeout=30)
    _UPSTREAM_COOKIES[client] = r.cookies
    return r.cookies


def _may_open(client):
    kind = session.get("kind")
    if client in getattr(cfg, "TOOLS", {}):     # internal tool: staff only, never agency/client
        return kind in ("superadmin", "admin")
    if kind == "superadmin":
        # god-mode: open ANY dashboard that has a URL, including coming_soon structure previews
        # (Caltex / Bell Shakespeare) that aren't surfaced to clients yet.
        c = store.get_client(client)
        return bool(c and c.get("url"))
    if kind == "admin":
        return client in store.active_client_keys()
    if kind == "agency":
        a = store.get_agency(session.get("agency_slug", ""))
        return bool(a) and client in a.get("client_keys", [])
    if kind == "client":
        return session.get("client_key") == client
    return False


# --- Payload scrubbing for EXTERNAL tenants -------------------------------------------------
# The dashboards' data.json is built for the OWNING agency and the client, so it carries fields an
# outside partner should not receive. These are removed from the PAYLOAD in transit (not hidden in
# the UI), so they are absent from the network response, the browser and any CSV the page exports.
#
# WHY A BLOCK-LIST HERE, when everything else in this pass is deny-by-default: the payload is 27
# top-level blocks of dashboard data whose whole purpose is to be rendered. An allow-list of field
# names would have to enumerate ~250 metric fields per client and would silently blank a chart the
# first time a dashboard added a metric - failing unsafe in the OTHER direction (a broken client
# deliverable). So: named fields are removed, AND anything that merely LOOKS like a person or an
# email is logged (never silently passed) so a new leak surfaces in the logs instead of in a
# partner's browser. Reviewed as a deliberate exception - see EXTRABLACK_EXPOSURE_2.md.
_SCRUB_KEYS = frozenset({
    "owner", "owner_name", "owner_email", "rep", "sales_owner", "assigned_to",
    "email", "contact_email", "user_email", "contact_name", "first_name", "last_name",
    "full_name", "person", "phone",
})
_EMAILISH = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# --- BILLED-ONLY spend for EXTERNAL tenants -------------------------------------------------
# An external tenant sees the SAME figures the client sees - the client-billed (grossed) spend -
# never the raw media cost. Raw-only would have closed margin derivation but left Extrablack's
# screen showing a LOWER number than Geocon's on the same dashboard, and that discrepancy is
# itself disclosure.
#
# HOW: the client's own session receives the RAW payload plus window.BB_SPEND_MULT, and the
# dashboard's shim grosses it in the browser. For an external tenant we do the SAME arithmetic
# SERVER-SIDE and inject no factor, so the browser shim is a no-op and both sessions render
# identical numbers. Every derived metric (CPM/CPC/CPL/cost-per-LPV/pacing) is computed in the
# browser FROM these fields, so grossing the inputs grosses the whole chain by construction.
#
# The spec below mirrors each dashboard's own shim. Three fields the shims leave RAW
# (geocon `breakdowns[].spend`, resetdata `weekly` + `ga_audience`) are grossed here as well:
# none is rendered, but leaving a raw figure beside a grossed one hands over the ratio.
_EXTERNAL_SPEND_SPEC = {
    "geocon": {
        # Meta-only client; mirrors clients/client_geocon/dash/dashboard.html bbApplySpendMult().
        "fixed_arrays": {"rows": ("spend", "meta"), "breakdowns": ("spend", "meta")},
        "objects": {
            "flight": (["spend_to_date", "projected_spend", "pace_expected", "budget"], "meta"),
            # The campaign budget appears a SECOND time here, ungrossed. Raw beside the grossed
            # flight.budget would give the factor by division, so gross these too. (The dashboard's
            # own shim grosses flight.budget but NOT these - a pre-existing inconsistency in the
            # client-facing view, flagged for a human in EXTRABLACK_EXPOSURE_2.md.)
            "benchmarks": (["flight_budget", "daily_pace"], "meta"),
        },
        # `targets` entries are {value, status}; same duplicate-budget problem, one level deeper.
        "value_objects": {"targets": (["flight_budget_aud", "daily_pace_aud"], "meta")},
    },
    "resetdata": {
        # Mirrors clients/client_resetdata/dash/dashboard.html bbGrossRows/bbGrossWide.
        "platform_arrays": ["ad_campaigns", "ad_campaign_daily", "ad_campaign_weekly",
                            "ad_campaign_monthly"],
        "fixed_arrays": {
            "google_campaigns": ("spend_aud", "google"), "ga_keywords": ("spend_aud", "google"),
            "ga_audience": ("spend_aud", "google"), "meta_campaigns": ("spend_aud", "meta"),
            "meta_creative": ("spend_aud", "meta"), "meta_creatives": ("spend_aud", "meta"),
            "ttd_campaigns": ("spend_aud", "ttd"), "reddit_campaigns": ("spend_aud", "reddit"),
        },
        "wide_objects": ["kpi"],
        "wide_arrays": ["monthly", "daily", "weekly"],
    },
}
# Per-channel parts carried by the "wide" records, and the blended total rebuilt from them.
_WIDE_PARTS = [("ga_spend_aud", "google"), ("me_spend_aud", "meta"),
               ("td_spend_aud", "ttd"), ("rd_spend_aud", "reddit")]
_WIDE_TOTAL = "ad_spend_aud"
# Anything left that looks like money after the spec has run is SUPPRESSED, not passed through -
# a field added to a payload later must not leak raw cost just because this spec predates it.
_SPENDISH = re.compile(r"(^|_)(spend|cost|cpm|cpc|cpl|cpa|budget)(_|$)", re.I)
# `rd_spend` is ResetData's own customers' product spend, not media cost, and never carried a
# multiplier. It only exists inside the crm block, which is removed wholesale for external
# tenants - listed so the fail-closed sweep does not flag it if that ever changes.
_SPEND_SWEEP_EXEMPT = frozenset({
    "rd_spend", "total_rd_spend", "total_hs_revenue",
    # PER-UNIT PLAN TARGETS (cost-per-lead/click/mille goals from the media plan). They pass through
    # RAW so the external tenant's screen matches the client's, and they cannot betray the markup:
    # a plan target is an independent commitment, not a figure derived from what we paid. The
    # MONEY-level plan figures (flight_budget/daily_pace) are grossed above, because those ARE the
    # same quantity as flight.budget and would give the ratio by division.
    "cpl", "cpl_stretch", "cpc", "cpm", "cost_per_lpv",
    "cpl_target_aud", "cpl_stretch_aud", "cpc_target_aud", "cpm_target_aud",
    "cost_per_lpv_target_aud",
})


def _mult_for(mults, channel):
    """The factor for a channel, or None when none is DEFINED.

    None means "we cannot produce the billed figure for this channel", and every caller then
    SUPPRESSES the value rather than falling through to x1.0 — because x1.0 silently ships the raw
    media cost. A channel that genuinely carries no markup must therefore be set to 1.0
    EXPLICITLY, which makes "billed == raw here" a deliberate human statement instead of a default.
    Note the consequence: an undefined channel is suppressed for an external tenant while the
    client still sees it, so define a factor for EVERY channel a client runs to keep the two views
    identical."""
    if not channel or channel not in (mults or {}):
        return None
    try:
        v = float(mults[channel])
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _channel_key(platform):
    """Mirror of the dashboards' bbChannelKey()."""
    s = str(platform or "").lower()
    for token, key in (("google", "google"), ("facebook", "meta"), ("meta", "meta"),
                       ("linkedin", "linkedin"), ("reddit", "reddit"), ("trade", "ttd"),
                       ("tradedesk", "ttd"), ("dv360", "dv360"), ("display", "dv360"),
                       ("line", "line"), ("dooh", "youdooh")):
        if token in s:
            return key
    return "ttd" if s == "ttd" else ""


def _gross_external_payload(client, doc, mults):
    """Return (doc, suppressed_fields). Grosses every spend field per the client's spec, then
    SUPPRESSES (sets to None) any money-shaped field the spec did not cover - fail closed."""
    spec = _EXTERNAL_SPEND_SPEC.get(client, {})
    done = set()                                   # (id(dict), field) already handled
    no_factor = set()                              # channels seen with no defined factor

    def gross(rec, field, chan):
        """Gross one field, or SUPPRESS it when this channel has no defined factor."""
        if not isinstance(rec, dict) or rec.get(field) is None:
            return
        f = _mult_for(mults, chan)
        if f is None:                       # no factor for this channel -> never fall back to raw
            rec[field] = None
            done.add((id(rec), field))
            no_factor.add(chan or "<unmapped>")
            return
        try:
            rec[field] = float(rec[field]) * f
            done.add((id(rec), field))
        except (TypeError, ValueError):
            rec[field] = None
            done.add((id(rec), field))

    for name, (field, chan) in (spec.get("fixed_arrays") or {}).items():
        for row in (doc.get(name) or []):
            gross(row, field, chan)
    for name in (spec.get("platform_arrays") or []):
        for row in (doc.get(name) or []):
            gross(row, "spend_aud", _channel_key((row or {}).get("platform")))
    for name, (fields, chan) in (spec.get("objects") or {}).items():
        for f in fields:
            gross(doc.get(name), f, chan)
    for name, (keys, chan) in (spec.get("value_objects") or {}).items():
        container = doc.get(name) or {}
        for k in keys:
            gross(container.get(k), "value", chan)

    def wide(rec):
        if not isinstance(rec, dict):
            return
        total, has, missing = 0.0, False, False
        for key, chan in _WIDE_PARTS:
            if rec.get(key) is None:
                continue
            has = True
            gross(rec, key, chan)
            if rec[key] is None:                   # part suppressed -> the blend is unknowable
                missing = True
            else:
                total += float(rec[key])
        if has and rec.get(_WIDE_TOTAL) is not None:
            # Rebuild the blended total from the grossed parts (mirrors the dashboards' bbGrossWide).
            # If ANY part was suppressed the total would be a partial sum reading as a real figure,
            # so suppress it instead.
            rec[_WIDE_TOTAL] = None if missing else total
            done.add((id(rec), _WIDE_TOTAL))

    for name in (spec.get("wide_objects") or []):
        wide(doc.get(name))
    for name in (spec.get("wide_arrays") or []):
        for row in (doc.get(name) or []):
            wide(row)

    # Fail-closed sweep: any money-shaped field the spec missed is suppressed, never forwarded raw.
    suppressed = set()

    def sweep(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if (isinstance(v, (int, float)) and not isinstance(v, bool)
                        and _SPENDISH.search(str(k)) and str(k) not in _SPEND_SWEEP_EXEMPT
                        and (id(o), k) not in done):
                    o[k] = None
                    suppressed.add(str(k))
                else:
                    sweep(v)
        elif isinstance(o, list):
            for v in o:
                sweep(v)

    sweep(doc)
    if no_factor:
        app.logger.warning("external billed-spend: no factor defined for channel(s) %s on client=%s "
                           "- those figures were SUPPRESSED, not shown raw", sorted(no_factor), client)
        suppressed |= {f"<channel:{c}>" for c in no_factor}
    return doc, suppressed


# --- Whole blocks/tabs an EXTERNAL tenant does not receive ----------------------------------
# Nothing is excluded today. ResetData's "Signups & CRM" block+tab USED to be removed wholesale as
# a contractual exclusion; that was reversed (2026-08-09) because, despite the tab's name, what it
# reports is CAMPAIGN OUTCOME - signups, source quality, lead volumes, loaded balances and the
# paying-customer figures - which is exactly what an agency sharing the client needs. Removing it
# also produced FALSE ZEROS off-tab: the Overview "Paying customers" card and the hero's paying
# line read 0 (not 143) because they source the same block.
#
# The machinery is kept (not deleted) so a genuine future exclusion is one entry, not a rewrite.
# If you ever add one, check what ELSE reads that block first - a card whose data is withheld must
# render the withheld placeholder, never a zero. See _WITHHELD in the dashboards.
_EXTERNAL_EXCLUDED_BLOCKS = {}
# Tab buttons removed from the rail for external tenants, keyed on the dashboards' own
# `data-tab` value. Removing the button AND its pane; if the tab were the active one the
# dashboard's own default (overview) still applies because we never make it active.
_EXTERNAL_EXCLUDED_TABS = {}
_EXCLUDED_TABS_SCRIPT = (
    b"<script>(function(){try{var T=" +
    __import__("json").dumps(_EXTERNAL_EXCLUDED_TABS).encode() +
    b";var c=(location.pathname.split('/')[2]||'');var t=T[c]||[];t.forEach(function(k){"
    b"document.querySelectorAll('[data-tab=\"'+k+'\"]').forEach(function(el){el.remove();});"
    b"var p=document.getElementById('tab-'+k); if(p) p.remove();});}catch(e){}})();</script>"
)


# Top-level blocks whose named individuals are DELIBERATELY shipped to an external tenant, exempt
# from the _SCRUB_KEYS sweep.
#
# ResetData's `crm` block carries `owner` (the ResetData staffer who owns each lead) on
# lifecycle_owner + lead_queue - 17 real names. The by-owner views are the point of those two
# sections, and scrubbing the key would leave the tab rendering "undefined" rows instead of the
# identical-to-internal view that was asked for. FLAGGED FOR A HUMAN: this is the one field in the
# restored tab that names individuals; drop "crm" from this map to scrub it and the rest of the tab
# still renders (the two by-owner sections lose their split). Nothing else in `crm` is personal -
# verified no email-shaped values anywhere in the block.
_SCRUB_EXEMPT_BLOCKS = {"resetdata": ("crm",)}


def _scrub_external_payload(obj, client, _found=None):
    """Recursively drop _SCRUB_KEYS; log (don't ship) anything email-shaped. Returns the scrubbed
    object. Pure data transform - no I/O."""
    found = _found if _found is not None else {"keys": set(), "emailish": 0}
    if _found is None and isinstance(obj, dict):
        # Detach the exempt blocks, scrub the rest, then put them back untouched.
        exempt = {b: obj[b] for b in _SCRUB_EXEMPT_BLOCKS.get(client, ()) if b in obj}
        if exempt:
            rest = {k: v for k, v in obj.items() if k not in exempt}
            out = _scrub_external_payload(rest, client, found)
            out.update(exempt)
            app.logger.info("external-scrub client=%s exempt_blocks=%s (named individuals shipped "
                            "deliberately - see _SCRUB_EXEMPT_BLOCKS)", client, sorted(exempt))
            if found["keys"] or found["emailish"]:
                app.logger.info("external-scrub client=%s removed_fields=%s emailish_values_seen=%d",
                                client, sorted(found["keys"]), found["emailish"])
            return out
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in _SCRUB_KEYS:
                found["keys"].add(str(k))
                continue
            out[k] = _scrub_external_payload(v, client, found)
        result = out
    elif isinstance(obj, list):
        result = [_scrub_external_payload(v, client, found) for v in obj]
    else:
        if isinstance(obj, str) and "@" in obj and _EMAILISH.search(obj):
            found["emailish"] += 1
        result = obj
    if _found is None and (found["keys"] or found["emailish"]):
        app.logger.info("external-scrub client=%s removed_fields=%s emailish_values_seen=%d",
                        client, sorted(found["keys"]), found["emailish"])
    return result


def _forward(client, subpath, cookies):
    url = f"{_upstream_base(client)}/{subpath}"
    # /report runs a live LLM (web research + structuring, or the Gemini fallback) and can take a
    # minute-plus to generate a cold (uncached) view; The Grid (Central)'s /api/central/sync scans
    # BigQuery across every client and can run well past 30s; every other route is a fast fetch.
    timeout = 600 if subpath == "report" else (300 if subpath == "api/central/sync" else 30)
    hdrs = _tool_headers(client)                             # {} for normal dashboards (unchanged)
    if request.method == "POST":
        return requests.post(url, data=request.get_data(), params=request.args, cookies=cookies,
                             headers={"Content-Type": request.headers.get("Content-Type", ""), **hdrs},
                             allow_redirects=False, timeout=timeout)
    return requests.get(url, params=request.args, cookies=cookies, headers=hdrs,
                        allow_redirects=False, timeout=timeout)


def _unauth(resp, subpath):
    if subpath == "data.json":
        return resp.status_code == 401
    # the dashboard page always references /data.json; the upstream login page never does
    if "text/html" in resp.headers.get("Content-Type", ""):
        return b"/data.json" not in resp.content
    return False


@app.route("/d/<client>/", defaults={"subpath": ""}, methods=["GET", "POST"])
@app.route("/d/<client>/<path:subpath>", methods=["GET", "POST"])
def proxy(client, subpath):
    if not _may_open(client):
        return redirect("/")
    # External tenants: block the privileged sub-paths behind an otherwise-permitted dashboard
    # (today `report`, the paid AI deck generator). Checked on the normalised first path segment
    # so a nested or trailing-slash form can't slip past.
    if _is_external_session() and (subpath or "").strip("/").split("/")[0] in _EXTERNAL_BLOCKED_SUBPATHS:
        app.logger.warning("external-deny agency=%s client=%s subpath=%s",
                           session.get("agency_slug", ""), client, subpath)
        return jsonify(ok=False, error="Not available for this account."), 403
    if not _upstream_base(client):
        abort(404)
    cookies = _UPSTREAM_COOKIES.get(client) or _upstream_login(client)
    resp = _forward(client, subpath, cookies)
    if _unauth(resp, subpath):                      # cached upstream session expired -> re-login once
        # Drop the cached PASSWORD too, not just the cookies: an out-of-band rotation (incl. the
        # super-admin rotate, which only busts the cache on the worker that served it) means OTHER
        # workers/instances still hold the OLD pw. Popping it forces _upstream_pw to re-read
        # <c>-dash-password:latest from Secret Manager, so every worker self-heals on its next miss.
        _UPSTREAM_PW.pop(client, None)
        resp = _forward(client, subpath, _upstream_login(client))
    ctype = resp.headers.get("Content-Type", "application/octet-stream")
    body = resp.content
    if "text/html" in ctype:                        # keep the dashboard's same-origin fetches inside the proxy
        is_dashboard = b"/data.json" in body        # the real dashboard page (vs. a sub-view); see _unauth
        body = body.replace(b"/data.json", f"/d/{client}/data.json".encode())
        body = body.replace(b"'/report'", f"'/d/{client}/report'".encode())  # AI report POST (mongodb)
        body = body.replace(b"/creative-img/", f"/d/{client}/creative-img/".encode())  # cached creative images (resetdata gallery)
        if is_dashboard:
            # Expose the per-channel spend multiplier + the dev-mode flag BEFORE the dashboard's own
            # scripts run (the gross-up shim reads window.BB_SPEND_MULT; the CS dev-mode toggle reads
            # window.BB_DEV). Inject high in <head> so it wins even if a dashboard renders
            # synchronously; fall back to </body> if there's no </head>.
            head_inject = (_spend_mult_script(client) + _dev_flag_script()
                           + _internal_flag_script(client))
            if b"</head>" in body:
                body = body.replace(b"</head>", head_inject + b"</head>", 1)
            elif b"</body>" in body:
                body = body.replace(b"</body>", head_inject + b"</body>", 1)
        if is_dashboard and b"</body>" in body:     # give the proxied dashboard a logout + feedback control
            tail = _LOGOUT_BUTTON
            if _ext_setting("allow_feedback"):      # external tenants: no feedback widget (route closed too)
                tail += _feedback_widget(client)
            if _internal_allowed(client):           # staff-only: Internal Notes + Assistant widget
                tail += _internal_widget(client)
            if _ext_setting("scrub_payload"):       # external: strip excluded tabs from the rail
                tail += _EXCLUDED_TABS_SCRIPT
            body = body.replace(b"</body>", tail + b"</body>", 1)
    elif "json" in ctype and _ext_setting("scrub_payload") and resp.status_code == 200:
        # Prepare the payload for an external tenant, in one parse:
        #   1. remove excluded blocks wholesale (the ResetData CRM tab's data),
        #   2. gross spend to the CLIENT-BILLED figure and suppress anything money-shaped the spec
        #      didn't cover,
        #   3. scrub named individuals.
        # FAILS CLOSED throughout: any error returns 502 rather than forwarding the original, since
        # passing it through on error would ship exactly what this exists to remove.
        try:
            import json as _json
            doc = _json.loads(body)
            if isinstance(doc, dict):
                for blk in _EXTERNAL_EXCLUDED_BLOCKS.get(client, ()):
                    doc.pop(blk, None)
                mults = store.get_spend_multipliers(client)
                if not mults:
                    # No markup factor configured => we cannot produce the billed figure, and we must
                    # NOT fall through to raw. Suppress every money-shaped field instead.
                    doc, supp = _gross_external_payload(client, doc, {})
                    app.logger.warning("external billed-spend UNAVAILABLE client=%s (no multiplier) "
                                       "- suppressed %d money fields", client, len(supp))
                else:
                    doc, supp = _gross_external_payload(client, doc, mults)
                    if supp:
                        app.logger.warning("external spend sweep suppressed uncovered money fields "
                                           "client=%s fields=%s", client, sorted(supp))
                doc = _scrub_external_payload(doc, client)
            body = _json.dumps(doc).encode()
        except Exception:
            app.logger.exception("external payload prep failed client=%s subpath=%s", client, subpath)
            return jsonify(ok=False, error="This data could not be prepared for your account."), 502
    out = Response(body, status=resp.status_code, content_type=ctype)
    out.headers["Cache-Control"] = "no-store"
    loc = resp.headers.get("Location")
    if loc and loc.startswith("/"):
        out.headers["Location"] = f"/d/{client}{loc}"
    return out


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
