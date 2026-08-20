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
     Centred at 142px. The cloud is re-centred over the wordmark too: in the source banner it
     sits above the RIGHT end of the lockup (cloud centre x531 vs wordmark centre x397), which
     reads as misaligned once the art is lifted out and used as a standalone mark. */
  .cf-logo{display:block;width:142px;height:auto;margin:0 auto 15px}
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
