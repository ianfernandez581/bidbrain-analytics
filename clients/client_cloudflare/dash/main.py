"""Cloudflare APAC dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`cloudflare.json` from GCS at `/data.json`. All presentation logic -- the
Paid Media / Content Syndication tabs, the region filter, and every chart --
lives in `dashboard.html`; this file only decides *who* may see it, not *what*
it shows.

This is the same service pattern as client_mongodb/dash/main.py (byte-for-byte
on the auth/serve/proxy logic); only the branding on the login page and the
default data object differ. The org policy that blocks --allow-unauthenticated
is handled the same way too -- the build flips --no-invoker-iam-check so this
app's own password gate is the only door (see cloudbuild.yaml).
"""
import os
import hmac
import json
import hashlib
from pathlib import Path
from flask import (
    Flask, request, redirect, session, Response, render_template_string, abort
)
from google.cloud import storage

from report import generate_report
import feedback_widget

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None",  # cross-site iframe on dashboards.bidbrain.ai (None requires Secure)
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # stay logged in 12h
    # Bodies are tiny except two: the /report POST, and a feedback submission (a voice note capped
    # at 2 min plus a JPEG screenshot). Same allowance the platform makes for the same widget.
    MAX_CONTENT_LENGTH=(feedback_widget.MAX_AUDIO_BYTES + feedback_widget.MAX_IMAGE_BYTES
                        + 256 * 1024),
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")     # from Secret Manager
GCS_BUCKET = os.environ["GCS_BUCKET"]                          # private data bucket
DATA_OBJECT = os.environ.get("DATA_OBJECT", "cloudflare.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# Splice the Feedback pill in once, at import (see feedback_widget.py for why this service carries
# its own copy at all: a DIRECT visitor never passes through the platform proxy that normally
# injects one). No PLATFORM_BUCKET on the service => no pill, so it can never be shown without
# somewhere to store what it collects. The pill itself also stands down when it finds itself
# running behind the proxy, so the two can never both draw.
if DASHBOARD_HTML and feedback_widget.enabled() and "</body>" in DASHBOARD_HTML:
    DASHBOARD_HTML = DASHBOARD_HTML.replace(
        "</body>", feedback_widget.widget("cloudflare") + "</body>", 1)

# Shared, theme-driven slide-deck builder (vendored — the canonical copy is re-copied into each dash
# folder). Served as a static asset so the dashboard's <script src="bb_deck.js"> loads it.
try:
    BB_DECK_JS = (Path(__file__).resolve().parent / "bb_deck.js").read_text(encoding="utf-8")
except FileNotFoundError:
    BB_DECK_JS = ""

# Bump to invalidate every cached report when the prompts/schema change (see report.py).
REPORT_CACHE_VERSION = "1"

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cloudflare APAC Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..800&display=swap" rel="stylesheet">
<style>
  /* The gate now matches the dashboard behind it: the same dark-glow theme, the same warm
     aurora, the same interaction vocabulary (2026-08-20). It used to be a white card on a
     bright orange gradient - the last surviving piece of the retired light theme, and the
     first thing a client saw before landing on a near-black page.
     The aurora here is CSS ONLY - no canvas, no requestAnimationFrame. A login screen has one
     job and should not run an animation loop to do it (the sophiie login rule). */
  :root{
    color-scheme:dark;
    --bg:#150A04; --bg-2:#1F0F06; --surface:#27150B; --surface-2:#352110;
    --line:rgba(255,255,255,.10); --ink:#FBF1E7; --muted:#C6AB98;
    --accent:#F38020; --accent-2:#E06820; --glow:rgba(243,128,32,.5);
    --ease:cubic-bezier(.22,1,.36,1);
  }
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       padding:24px;color:var(--ink);overflow:hidden;letter-spacing:-.011em;
       -webkit-font-smoothing:antialiased;
       font-family:"Inter","Inter Variable",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:
         radial-gradient(1100px 620px at 50% -180px, rgba(243,128,32,.36), transparent 64%),
         radial-gradient(800px 460px at 88% -40px, rgba(243,128,32,.20), transparent 64%),
         linear-gradient(180deg,#2A160B 0%,#1E1007 56%,#170B04 100%)}

  /* aurora: three blurred brand orbs + one slow diagonal band, all fixed and inert */
  .aur{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .orb{position:absolute;border-radius:50%;filter:blur(120px)}
  .orb1{width:64vw;height:54vh;top:-16%;left:-10%;animation:o1 18s ease-in-out infinite;
        background:radial-gradient(circle,rgba(243,128,32,.26) 0%,transparent 68%)}
  .orb2{width:52vw;height:46vh;bottom:-14%;right:-8%;animation:o2 22s ease-in-out infinite;
        background:radial-gradient(circle,rgba(251,173,65,.16) 0%,transparent 68%)}
  .orb3{width:46vw;height:42vh;top:38%;left:22%;animation:o3 26s ease-in-out infinite;
        background:radial-gradient(circle,rgba(230,11,127,.06) 0%,transparent 70%)}
  @keyframes o1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(150px,110px) scale(1.16)}}
  @keyframes o2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-130px,-96px) scale(1.18)}}
  @keyframes o3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(110px,-120px) scale(1.12)}}
  .band{position:absolute;width:180%;height:300px;top:8%;left:-40%;transform:rotate(-18deg);
        animation:bd 24s ease-in-out infinite;
        background:linear-gradient(180deg,transparent,rgba(243,128,32,.07) 48%,transparent)}
  @keyframes bd{0%{transform:rotate(-18deg) translate(0,0);opacity:.6}45%{transform:rotate(-18deg) translate(80px,90px);opacity:1}100%{transform:rotate(-18deg) translate(0,0);opacity:.6}}
  /* VIGNETTE - without it the orbs bloom edge to edge and the whole screen reads as brown fog
     with a card floating in it. Deepening everything outside the middle is what makes the glow
     read as light and gives the card a ground. */
  .scrim{position:absolute;inset:0;
    background:radial-gradient(860px 600px at 50% 48%,transparent 0%,rgba(8,3,1,.30) 68%,rgba(5,2,0,.58) 100%)}
  /* film grain over the gradients - they band visibly on a dark screen without it */
  .grain{position:absolute;inset:0;opacity:.04;mix-blend-mode:overlay;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23n)'/></svg>")}

  /* the card: solid (not glass - it sits over moving light), inside a rotating accent ring */
  .card{position:relative;z-index:1;width:100%;max-width:372px;padding:32px 30px 28px;
        background:linear-gradient(180deg,#35210F 0%,#211208 100%);
        border:1px solid rgba(255,255,255,.13);border-radius:16px;overflow:hidden;
        box-shadow:0 30px 80px -30px rgba(0,0,0,.9),0 0 60px -30px var(--glow),
                   inset 0 1px 0 rgba(255,255,255,.06);
        animation:in .7s var(--ease) both}
  @keyframes in{from{opacity:0;transform:translateY(14px) scale(.985)}to{opacity:1;transform:none}}
  /* The travelling highlight goes all the way AROUND the card, not just across the top edge.
     Mechanic: ::before is an oversized square painted with a conic gradient (one bright arc, the
     rest transparent) and spun by `transform:rotate` - a transform, so it stays on the
     compositor. ::after then covers the middle with the card's own surface, leaving only a
     1.5px ring of the spinning gradient visible as the border. The square is 200% x 200% so
     that at every angle it still covers the card's diagonal; a non-square pseudo would leave
     bald corners as it turned. Deliberately NOT done with an animated @property angle - that
     needs a registered custom property and silently does nothing where it is unsupported. */
  .card::before{content:"";position:absolute;top:-50%;left:-50%;width:200%;height:200%;z-index:0;
        background:conic-gradient(from 0turn,
            rgba(243,128,32,0) 0%, rgba(243,128,32,0) 58%,
            rgba(243,128,32,.55) 72%, rgba(255,196,137,1) 82%, rgba(243,128,32,.55) 90%,
            rgba(243,128,32,0) 100%);
        animation:ring 6.5s linear infinite;will-change:transform}
  @keyframes ring{to{transform:rotate(1turn)}}
  .card::after{content:"";position:absolute;inset:1.5px;z-index:1;border-radius:14.5px;
        background:linear-gradient(180deg,#35210F 0%,#211208 100%)}
  /* content above both pseudo-elements */
  .card > *{position:relative;z-index:2}
  .card.shake{animation:in .7s var(--ease) both, shake .45s cubic-bezier(.36,.07,.19,.97) .1s}
  @keyframes shake{10%,90%{transform:translateX(-2px)}20%,80%{transform:translateX(4px)}30%,50%,70%{transform:translateX(-7px)}40%,60%{transform:translateX(7px)}}

  .brand{display:flex;align-items:center;gap:9px;font-size:10.5px;font-weight:700;
         letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;margin-bottom:20px}
  .brand .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);
              box-shadow:0 0 0 4px rgba(243,128,32,.18);animation:pulse 2.6s ease-in-out infinite}
  @keyframes pulse{0%,100%{box-shadow:0 0 0 4px rgba(243,128,32,.16)}50%{box-shadow:0 0 0 8px rgba(243,128,32,.04)}}
  h1{font-size:21px;font-weight:700;margin:0 0 5px;letter-spacing:-.4px}
  p{font-size:13px;color:var(--muted);margin:0 0 22px;line-height:1.5}
  label{display:block;font-size:10.5px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;
        color:var(--muted);margin-bottom:7px}
  input{width:100%;padding:13px 14px;font-size:15px;font-family:inherit;color:var(--ink);
        background:rgba(0,0,0,.32);border:1px solid var(--line);border-radius:10px;outline:none;
        transition:border-color .2s var(--ease),box-shadow .28s var(--ease),background-color .2s}
  input::placeholder{color:#8B7263}
  input:hover{border-color:rgba(255,255,255,.2)}
  /* Focus is a BORDER TINT and nothing else. The field is autofocused, so a bright ring plus a
     4px glow was the loudest thing on the page from the moment it loaded - and it stacked with
     the :focus-visible outline below for a double ring. */
  input:focus{border-color:rgba(243,128,32,.55);background:rgba(0,0,0,.42)}
  button{position:relative;overflow:hidden;width:100%;margin-top:16px;padding:13px;font-size:14.5px;
         font-weight:700;font-family:inherit;letter-spacing:.2px;cursor:pointer;color:#25120A;
         background:linear-gradient(180deg,#FBAD41,var(--accent));border:none;border-radius:10px;
         box-shadow:0 10px 26px -12px var(--glow);
         transition:transform .18s var(--ease),box-shadow .28s var(--ease),filter .2s}
  button:hover{transform:translateY(-1px);filter:brightness(1.06);
               box-shadow:0 16px 34px -14px var(--glow)}
  button:active{transform:translateY(0) scale(.985);transition-duration:.06s}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
  /* the sheen sweeps once on hover - same gesture as the dashboard's KPI tiles */
  button::after{content:"";position:absolute;inset:-40% -60%;
        background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,.42) 50%,transparent 60%);
        transform:translateX(-115%);transition:transform 0s}
  button:hover::after{transform:translateX(115%);transition:transform .95s cubic-bezier(.4,0,.2,1)}
  .err{margin-top:14px;font-size:12.5px;color:#FB8E80;min-height:16px;font-weight:600}

  @media (prefers-reduced-motion: reduce){
    .orb,.band,.card,.card::before,.card::after,.brand .dot,button::after{animation:none !important}
    .card.shake{animation:none !important}
    input,button{transition:none !important}
    button:hover{transform:none}
  }
</style>
</head>
<body>
  <div class="aur" aria-hidden="true">
    <div class="orb orb1"></div>
    <div class="orb orb2"></div>
    <div class="orb orb3"></div>
    <div class="band"></div>
    <div class="scrim"></div>
    <div class="grain"></div>
  </div>
  <form class="card {{ 'shake' if error else '' }}" method="POST" action="/login">
    <div class="brand"><span class="dot"></span>Transmission &middot; Cloudflare APAC</div>
    <h1>Dashboard access</h1>
    <p>Enter the password to open the Core DG performance dashboard.</p>
    <label for="pw">Password</label>
    <input id="pw" type="password" name="password" placeholder="Enter password" autofocus
           autocomplete="current-password">
    <button type="submit">Unlock dashboard</button>
    <div class="err">{{ error or "" }}</div>
  </form>
</body>
</html>"""


def authed():
    # Authenticated by THIS dashboard's own password (session["ok"]) OR by a platform-issued
    # SSO cookie from dashboards.bidbrain.ai that lists this client. Fail-closed + fail-safe:
    # any problem falls back to password-only, so this can never break the existing gate.
    if session.get("ok") is True:
        return True
    try:
        from platform_sso import sso_allows
        return sso_allows(request)
    except Exception:
        return False


@app.get("/")
def home():
    if not authed():
        return render_template_string(LOGIN_HTML, error=None)
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    # no-store so a redeploy of the dashboard is picked up immediately, never
    # served stale from the browser or the Cloudflare proxy (matches /data.json).
    return Response(DASHBOARD_HTML, mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.post("/login")
def login():
    if hmac.compare_digest(request.form.get("password", ""), DASH_PASSWORD):
        session["ok"] = True
        session.permanent = True
        return redirect("/")
    return render_template_string(LOGIN_HTML, error="Incorrect password."), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/data.json")
def data():
    # The dashboard fetches this. Only an authenticated session gets it;
    # everyone else gets 401. The bucket itself stays private.
    if not authed():
        abort(401)
    blob = _storage.bucket(GCS_BUCKET).blob(DATA_OBJECT)
    if not blob.exists():
        abort(404)
    return Response(
        blob.download_as_bytes(),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/bb_deck.js")
def bb_deck_js():
    """The slide-deck builder. Auth-gated like the dashboard (the deck reveals report content)."""
    if not authed():
        abort(401)
    if not BB_DECK_JS:
        return Response("// bb_deck.js missing from the deploy", status=500, mimetype="application/javascript")
    return Response(BB_DECK_JS, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store"})


def _json_err(msg, code):
    return Response(json.dumps({"error": msg}), status=code, mimetype="application/json")


@app.post("/report")
def report_route():
    # AI account report (the portal "Download slides" deck). Auth-gated like the dashboard. The browser
    # POSTs the current view's numbers (the same figures it renders); we cache the generated report in the
    # private bucket keyed by VIEW IDENTITY + DATA VERSION, so re-downloading the same view costs no model
    # calls and regenerates only when the underlying data advances.
    if not authed():
        abort(401)
    if request.content_length and request.content_length > 256 * 1024:
        return _json_err("request too large", 413)
    summary = request.get_json(silent=True)
    if not isinstance(summary, dict):
        return _json_err("invalid request body", 400)

    ctx = summary.get("context") or {}
    key_src = json.dumps({
        "client": summary.get("client"),
        "campaign": ctx.get("campaign_key"),
        "markets": sorted(ctx.get("markets") or []),
        "date_filter": ctx.get("date_filter") or {},
        "data_through": ctx.get("data_through"),
        "v": REPORT_CACHE_VERSION,
    }, sort_keys=True)
    h = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    ckey = "".join(c for c in str(summary.get("client") or "cloudflare").lower()
                   if c.isalnum() or c in "-_")[:40] or "client"
    blob = _storage.bucket(GCS_BUCKET).blob(f"reports/{ckey}_{h}.json")

    try:
        if blob.exists():
            cached = json.loads(blob.download_as_bytes())
            cached["cached"] = True
            return Response(json.dumps(cached), mimetype="application/json",
                            headers={"Cache-Control": "no-store"})
    except Exception:
        app.logger.exception("report cache read failed")

    try:
        rpt = generate_report(summary)
    except Exception as e:
        app.logger.exception("report generation failed")
        msg = str(e) if isinstance(e, RuntimeError) else "report generation failed"
        return _json_err(msg or "report generation failed", 502)

    rpt["cached"] = False
    try:
        blob.upload_from_string(json.dumps(rpt), content_type="application/json")
    except Exception:
        app.logger.exception("report cache write failed")
    return Response(json.dumps(rpt), mimetype="application/json", headers={"Cache-Control": "no-store"})


@app.post("/feedback")
def feedback_route():
    """Store one note from the injected Feedback pill. Auth-gated exactly like the dashboard itself,
    so only someone who may READ this dashboard may file feedback against it. The `client` form field
    the widget sends is IGNORED: this service serves one client, so the key is pinned here and a
    caller cannot file a note into another client's folder. Records land in the platform's bucket and
    surface in the existing tracker at dashboards.bidbrain.ai/feedback/admin."""
    if not authed():
        abort(401)
    if not feedback_widget.enabled():
        return _json_err("feedback is not configured on this service", 503)
    text = request.form.get("text") or ""
    audio_bytes, audio_ctype = None, ""
    f = request.files.get("audio")
    if f is not None:
        audio_bytes = f.read()
        audio_ctype = f.mimetype or "audio/webm"
        if len(audio_bytes) > feedback_widget.MAX_AUDIO_BYTES:
            return _json_err("recording too large", 413)
    shot_bytes = None
    sf = request.files.get("screenshot")
    if sf is not None:
        shot_bytes = sf.read()
        if len(shot_bytes) > feedback_widget.MAX_IMAGE_BYTES:
            shot_bytes = None            # drop an oversized screenshot; never fail the note over it
    if not text.strip() and not audio_bytes:
        return _json_err("empty feedback", 400)
    try:
        feedback_widget.save("cloudflare", text, audio_bytes, audio_ctype,
                             request.form.get("page", ""), "client-direct", shot_bytes,
                             reporter=request.form.get("reporter", ""),
                             deadline=request.form.get("deadline", ""))
    except Exception:
        app.logger.exception("feedback save failed")
        return _json_err("could not store feedback", 500)
    return Response(json.dumps({"ok": True}), mimetype="application/json")


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
