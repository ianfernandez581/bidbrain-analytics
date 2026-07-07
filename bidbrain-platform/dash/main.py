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
from store import Store

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
SLIDES_CLIENTS = {"mongodb", "cloudflare", "schneider", "proptrack", "geocon"}

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


def _establish_session(kind, payload, json_mode=False):
    """Set the session for a resolved login and return the response with the SSO cookie. The SINGLE
    place that turns a (kind, payload) — from EITHER store.resolve_password or store.resolve_email —
    into a logged-in session, so password and Google sign-in are identical from here on. json_mode
    returns {ok, next} JSON (for the same-origin Google fetch); otherwise a 302 (password form POST)."""
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
    resp = make_response(jsonify(ok=True, next=nxt) if json_mode else redirect(nxt))
    return _set_sso(resp, allowed)


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
        return render_template("portal.html", logo_svg=LOGO_SVG,
                               agency={"name": agency["name"], "slug": agency["slug"]},
                               agency_logo=AGENCY_LOGOS.get(agency["slug"]),
                               clients=clients,
                               slides_clients=list(SLIDES_CLIENTS),
                               google_client_id=GOOGLE_CLIENT_ID,
                               admin_return=session.get("admin_return"))
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
    return _establish_session(kind, payload)


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
        return jsonify(ok=False, error="not allowed"), 403
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
        return jsonify(ok=False, error="could not store feedback"), 500
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
    """Editing is OPEN: anyone who can OPEN the client may edit its definitions (the only hard gate
    is a typed name). _may_open already encodes per-role visibility; _EDIT_ROLES is the broad knob."""
    return session.get("kind") in _EDIT_ROLES and _may_open(client)


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


@app.get("/api/status")
def api_status():
    """status.json filtered to the clients this session may open, + per-client edit/definitions flags.
    The Overview health badges and the Data Accuracy tab render from this."""
    if session.get("kind") not in _EDIT_ROLES:
        abort(403)
    doc = _status_doc()
    clients = [c for c in doc.get("clients", []) if _may_open(c.get("client", ""))]
    flags = {c["client"]: {"can_edit": _can_edit(c["client"]), "has_definitions": _has_definitions(c["client"])}
             for c in clients if c.get("client")}
    return jsonify(generated_at=doc.get("generated_at"),
                   tolerance_minutes=doc.get("tolerance_minutes"),
                   clients=clients, flags=flags)


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
    """Stream a client's uploaded logo from the platform bucket (any logged-in session). 404 if none."""
    if session.get("kind") not in _EDIT_ROLES:
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
    try:
        _run_status_deploy(client)
    except Exception as e:
        app.logger.exception("status-deploy trigger failed")
        return jsonify(ok=False, error=f"Could not start the deploy: {e}"), 500
    _append_audit(client, staged.get("last_edited_by", ""), "deploy-triggered")
    return jsonify(ok=True)


# The Snowflake-sourced clients whose export jobs "Sync all now" force-refreshes.
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


# --- Tools tile: The Grid freshness + on-demand sync (superadmin/admin only) --------------
# "Last synced" = the mtime of the daily-refreshed GCS snapshot the Grid serves on open; "Sync now"
# triggers the Grid's /refresh (regenerate that snapshot from live BigQuery). Same run.invoker the
# proxy already has (_tool_headers) + a shared REFRESH_TOKEN (secret pacing-refresh-token).
PACING_SNAP_BUCKET = os.environ.get("PACING_SNAP_BUCKET", "bidbrain-analytics-pacing-grid")


def _pacing_refresh_token():
    from google.cloud import secretmanager
    sm = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/pacing-refresh-token/versions/latest"
    return sm.access_secret_version(name=name).payload.data.decode().strip()


@app.get("/tools/pacing/status")
def tools_pacing_status():
    if session.get("kind") not in ("superadmin", "admin"):
        abort(403)
    try:
        import google.auth
        import google.auth.transport.requests as gart
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
        creds.refresh(gart.Request())
        r = requests.get(f"https://storage.googleapis.com/storage/v1/b/{PACING_SNAP_BUCKET}/o/snapshot.json",
                         headers={"Authorization": f"Bearer {creds.token}"}, timeout=15)
        return jsonify(ok=r.ok, updated=(r.json().get("updated") if r.ok else None))
    except Exception as e:
        return jsonify(ok=False, updated=None, error=str(e)[:200])


@app.post("/tools/pacing/sync")
def tools_pacing_sync():
    if session.get("kind") not in ("superadmin", "admin"):
        abort(403)
    base = _upstream_base("pacing")
    if not base:
        return jsonify(ok=False, error="The Grid is not configured."), 400
    try:
        hdrs = _tool_headers("pacing")            # IAM Bearer for the org-private service
        hdrs["X-Refresh-Token"] = _pacing_refresh_token()
        r = requests.post(f"{base}/refresh", headers=hdrs, timeout=180)
        j = r.json() if "application/json" in r.headers.get("Content-Type", "") else {}
        return jsonify(ok=r.ok, result=(j if isinstance(j, dict) else {})), (200 if r.ok else 502)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200]), 502


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
    "btn.onclick=function(){var opening=!panel.classList.contains('open');panel.classList.toggle('open');"
    "if(opening){ta.focus();grabShot();}};"
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
    "fetch('/feedback',{method:'POST',body:fd,credentials:'same-origin'}).then(function(r){"
    "if(!r.ok)throw 0;status.textContent='Thanks \\u2014 your feedback was sent! \\u2713';"
    "ta.value='';nameEl.value='';dlEl.value='';blob=null;chunks=[];shot=null;audioEl.style.display='none';mic.textContent='\\ud83c\\udfa4 Record';"
    "setTimeout(function(){panel.classList.remove('open');status.textContent='';send.disabled=false;},1600);"
    "}).catch(function(){status.textContent='Could not send \\u2014 please try again.';send.disabled=false;});"
    "};"
    "})();</script>"
).encode()


def _feedback_widget(client):
    return _FEEDBACK_WIDGET.replace(b"__CLIENT__", client.encode())


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


def _forward(client, subpath, cookies):
    url = f"{_upstream_base(client)}/{subpath}"
    # /report runs a live LLM (web research + structuring, or the Gemini fallback) and can take a
    # minute-plus to generate a cold (uncached) view; every other route is a fast static/JSON fetch.
    timeout = 600 if subpath == "report" else 30
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
        if is_dashboard and b"</body>" in body:     # give the proxied dashboard a logout + feedback control
            body = body.replace(b"</body>", _LOGOUT_BUTTON + _feedback_widget(client) + b"</body>", 1)
    out = Response(body, status=resp.status_code, content_type=ctype)
    out.headers["Cache-Control"] = "no-store"
    loc = resp.headers.get("Location")
    if loc and loc.startswith("/"):
        out.headers["Location"] = f"/d/{client}{loc}"
    return out


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
