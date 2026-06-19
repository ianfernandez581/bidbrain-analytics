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
    Flask, request, redirect, session, render_template, abort, jsonify, make_response, Response
)

import config as cfg
import platform_sso
import feedback
from store import Store

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]            # platform's own session (separate from SSO)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("DEV") != "1",
    SESSION_COOKIE_SAMESITE="Lax",                       # platform is top-level, not iframed
    PERMANENT_SESSION_LIFETIME=platform_sso.DEFAULT_MAX_AGE,
    # Bound request bodies. The only sizeable one is a feedback voice note (capped ~16 MB); the
    # proxy's forwarded POSTs (login, the mongodb /report) are all tiny.
    MAX_CONTENT_LENGTH=feedback.MAX_AUDIO_BYTES + 256 * 1024,
)

# --- config injected by Cloud Run ---------------------------------------------------------
SSO_SECRET = os.environ["SSO_SECRET"]                    # shared with every dashboard
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", ".bidbrain.ai")  # parent domain so the cookie spans subdomains
_SECURE = os.environ.get("DEV") != "1"

# Logo + Flask templates are baked into the container next to this file.
LOGO_SVG = ""
try:
    LOGO_SVG = (Path(__file__).resolve().parent / "logo.svg").read_text(encoding="utf-8")
except FileNotFoundError:
    LOGO_SVG = "<span style='font-weight:800'>Bidbrain.ai</span>"

store = Store()


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
                logos[slug] = {"html": f'<img src="data:image/{mime};base64,{b64}" alt="">', "light": True}
        except OSError:
            pass
    return logos


AGENCY_LOGOS = _load_agency_logos()


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
@app.get("/")
def home():
    kind = session.get("kind")
    if kind == "superadmin":
        return _render_super()
    if kind == "admin":
        st = store.get_state()
        return render_template("admin.html", logo_svg=LOGO_SVG, is_super=False, **st)
    if kind == "agency":
        agency = store.get_agency(session.get("agency_slug", ""))
        if not agency:
            session.clear()
            return render_template("login.html", logo_svg=LOGO_SVG, error=None, next_url="")
        clients = store.agency_clients(agency)
        return render_template("portal.html", logo_svg=LOGO_SVG,
                               agency={"name": agency["name"], "slug": agency["slug"]},
                               agency_logo=AGENCY_LOGOS.get(agency["slug"]),
                               clients=clients)
    if kind == "client":
        key = session.get("client_key")
        if key:
            return redirect(f"/d/{key}/")
        session.clear()
    return render_template("login.html", logo_svg=LOGO_SVG, error=None, next_url="")


@app.post("/login")
def login():
    pw = request.form.get("password", "")
    kind, payload = store.resolve_password(pw)
    if kind is None:
        return render_template("login.html", logo_svg=LOGO_SVG,
                               error="Incorrect password.", next_url=""), 401

    session.permanent = True
    if kind in ("admin", "superadmin"):
        session["kind"] = kind
        allowed = store.active_client_keys()  # every LIVE dashboard (incl. unassigned, excl. coming_soon)
        resp = make_response(redirect("/"))
        return _set_sso(resp, allowed)

    if kind == "agency":
        session["kind"] = "agency"
        session["agency_slug"] = payload["slug"]
        allowed = list(payload.get("client_keys", []))
        resp = make_response(redirect("/"))
        return _set_sso(resp, allowed)

    # single dashboard -> straight into the proxied dashboard
    session["kind"] = "client"
    session["client_key"] = payload["key"]
    resp = make_response(redirect(f"/d/{payload['key']}/"))
    return _set_sso(resp, [payload["key"]])


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
    if not text.strip() and not audio_bytes:
        return jsonify(ok=False, error="empty feedback"), 400
    try:
        feedback.save(client, text, audio_bytes, audio_ctype,
                      request.form.get("page", ""), session.get("kind", ""))
    except Exception:
        app.logger.exception("feedback save failed")
        return jsonify(ok=False, error="could not store feedback"), 500
    return jsonify(ok=True)


@app.get("/feedback/admin")
def feedback_admin():
    """The simple tracker: every feedback note across all dashboards, newest first. Admin/super only."""
    _require_admin()
    try:
        rows = feedback.list_recent()
    except Exception:
        app.logger.exception("feedback list failed")
        rows = []
    names = {k: c.get("name", k) for k, c in store._all_clients().items()}
    return render_template_string(_FEEDBACK_ADMIN_HTML, rows=rows, names=names, count=len(rows))


@app.get("/feedback/audio/<client>/<fname>")
def feedback_audio(client, fname):
    """Stream one stored voice note for playback on the tracker page. Admin/super only."""
    _require_admin()
    data, ctype = feedback.load_audio(client, fname)
    if data is None:
        abort(404)
    return Response(data, mimetype=ctype, headers={"Cache-Control": "no-store"})


_FEEDBACK_ADMIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Dashboard feedback</title>
<style>
  *{box-sizing:border-box} body{margin:0;background:#0e1014;color:#f3f4f6;
    font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}
  header{padding:22px 28px;border-bottom:1px solid rgba(255,255,255,.1);display:flex;
    align-items:baseline;gap:14px}
  header h1{margin:0;font-size:19px} header .n{color:#9ca3af;font-size:13px}
  header a{margin-left:auto;color:#9ca3af;font-size:13px;text-decoration:none}
  .wrap{max-width:860px;margin:0 auto;padding:24px 28px;display:flex;flex-direction:column;gap:14px}
  .card{background:#15171c;border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:15px 17px}
  .meta{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:#9ca3af;margin-bottom:8px}
  .chip{background:#1f2937;color:#c7d2fe;border-radius:999px;padding:2px 9px;font-weight:600}
  .txt{white-space:pre-wrap;font-size:14px;line-height:1.5} .txt.empty{color:#6b7280;font-style:italic}
  audio{width:100%;margin-top:10px} .none{color:#9ca3af;padding:40px 0;text-align:center}
</style></head><body>
<header><h1>Dashboard feedback</h1><span class="n">{{ count }} note(s)</span>
  <a href="/">&larr; back to platform</a></header>
<div class="wrap">
{% for r in rows %}
  <div class="card">
    <div class="meta">
      <span class="chip">{{ names.get(r.client, r.client) }}</span>
      <span>{{ r.created_at | datetime }}</span>
      {% if r.page %}<span>· {{ r.page }}</span>{% endif %}
      {% if r.user_kind %}<span>· {{ r.user_kind }}</span>{% endif %}
    </div>
    {% if r.text %}<div class="txt">{{ r.text }}</div>{% else %}<div class="txt empty">(voice note only)</div>{% endif %}
    {% if r.audio %}<audio controls preload="none" src="/feedback/audio/{{ r.client }}/{{ r.audio }}"></audio>{% endif %}
  </div>
{% else %}
  <div class="none">No feedback yet.</div>
{% endfor %}
</div></body></html>"""


@app.template_filter("datetime")
def _fmt_dt(epoch):
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


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
    return render_template("superadmin.html", logo_svg=LOGO_SVG, **st)


@app.get("/admin")
def admin_tree():
    """The editable agencies→clients→campaigns tree. Reachable by admin (its home) and by super
    admin (linked from the god-mode console)."""
    kind = session.get("kind")
    if kind not in ("admin", "superadmin"):
        return redirect("/")
    st = store.get_state()
    return render_template("admin.html", logo_svg=LOGO_SVG, is_super=(kind == "superadmin"), **st)


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
    "<p class='sub'>Type a note or record a voice message — whatever’s easiest.</p>"
    "<textarea id='bbfb-text' placeholder='What’s working, what’s confusing, what you’d like to see…'></textarea>"
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
    "audioEl=document.getElementById('bbfb-audio');"
    "var rec=null,chunks=[],blob=null,ctype='',timer=null,secs=0;"
    "btn.onclick=function(){panel.classList.toggle('open');if(panel.classList.contains('open'))ta.focus();};"
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
    "if(blob)fd.append('audio',blob,'voice.'+((ctype.indexOf('mp4')>-1)?'m4a':(ctype.indexOf('ogg')>-1)?'ogg':'webm'));"
    "fetch('/feedback',{method:'POST',body:fd,credentials:'same-origin'}).then(function(r){"
    "if(!r.ok)throw 0;status.textContent='Thanks \\u2014 your feedback was sent! \\u2713';"
    "ta.value='';blob=null;chunks=[];audioEl.style.display='none';mic.textContent='\\ud83c\\udfa4 Record';"
    "setTimeout(function(){panel.classList.remove('open');status.textContent='';send.disabled=false;},1600);"
    "}).catch(function(){status.textContent='Could not send \\u2014 please try again.';send.disabled=false;});"
    "};"
    "})();</script>"
).encode()


def _feedback_widget(client):
    return _FEEDBACK_WIDGET.replace(b"__CLIENT__", client.encode())


def _upstream_base(client):
    c = store.get_client(client)
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


def _upstream_login(client):
    base = _upstream_base(client)
    r = requests.post(f"{base}/login", data={"password": _upstream_pw(client)},
                      allow_redirects=False, timeout=30)
    _UPSTREAM_COOKIES[client] = r.cookies
    return r.cookies


def _may_open(client):
    kind = session.get("kind")
    if kind in ("admin", "superadmin"):
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
    if request.method == "POST":
        return requests.post(url, data=request.get_data(), params=request.args, cookies=cookies,
                             headers={"Content-Type": request.headers.get("Content-Type", "")},
                             allow_redirects=False, timeout=timeout)
    return requests.get(url, params=request.args, cookies=cookies, allow_redirects=False, timeout=timeout)


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
