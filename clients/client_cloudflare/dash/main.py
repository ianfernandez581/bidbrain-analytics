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

  /* Client mark. The supplied artwork is white-on-ORANGE, and dropping a bright orange block
     into this dark card would fight it - so the orange field is knocked out to transparency
     (alpha taken from the blue channel, which separates the pure-white mark from the orange at
     ~40) and the mark is repainted pure white, which also kills the JPEG's orange edge chroma.
     INLINED as base64 on purpose: `creatives/` is not in the dash/ build context, so a file path
     or a /logo route 404s once deployed - the same reason the dashboard inlines its own copy.
     Left-aligned at 142px because this card is left-aligned throughout. */
  .cf-logo{display:block;width:142px;height:auto;margin:0 0 15px}
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
    <img class="cf-logo" src="data:image/png;base64,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" alt="Cloudflare">
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
