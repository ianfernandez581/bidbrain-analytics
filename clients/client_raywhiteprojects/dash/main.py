"""Ray White Projects dashboard web app (Cloud Run service).

Thin password gate + static server, the same shape as every other tenant in the estate: it renders
a login screen, and once a session is authenticated it serves `dashboard.html` and proxies the
private `raywhiteprojects.json` from GCS at `/data.json`. All presentation logic lives in
`dashboard.html`; this file only decides *who* may see it, not *what* it shows.

SESSION SCOPE. A session here opens Ray White Projects and nothing else. There are two ways in and
neither crosses a tenant boundary: this dashboard's OWN password (`session["ok"]`, signed with a
Ray-White-only SESSION_SECRET, so a cookie minted by another dashboard cannot be read here), or
the platform's `bb_sso` cookie, which carries the list of clients that session may open and is
checked against CLIENT_KEY below. Everything private is behind `authed()` - the dashboard, the
payload and the internal notes - and the data bucket itself stays private, read only by this
service's own service account.

PROJECT IS A FILTER, NOT A ROUTE. Monair, Greenwich is the first campaign, not the client. Ray
White Projects is expected to run more, so the dashboard treats project as a DIMENSION on the
payload (`meta.projects` + a `project` column on every fact row) and this service has no
per-project route, password or session. A second project is a data change.

A SECOND, NARROWER LOGIN. The developer (Realside) is a separate stakeholder and may need a login
that does NOT see agency commentary. Two-thirds of that already holds: the Internal notes tab is
gated on `window.BB_INTERNAL` (which only the platform proxy sets, for staff sessions) and its
content is served from its own route rather than riding on `/data.json`. What is NOT yet possible
is a genuinely narrower CLIENT view, because the `bb_sso` cookie carries the allowed-client list
and not the role - see README.md -> "A login for the developer".

PREVIEW TENANT. Ray White Projects has no data pipeline yet (no BigQuery dataset, no sql/ views,
no export job), so the bucket is empty and `/data.json` falls back to the baked-in sample payload
`placeholder.json`, which carries `meta.placeholder=true`. The dashboard renders its preview notice
and every placeholder marker off that one flag. The moment an export job writes a real
raywhiteprojects.json to the bucket, that wins and all of it disappears - no code change, no
redeploy. See README.md -> "Flipping preview to live".

There is deliberately NO `/report` endpoint: the AI deck needs `roles/aiplatform.user` and a
client-specific prompt set, and neither is warranted while every number on the page is illustrative.
"""
import hmac
import json
import os
from pathlib import Path

from flask import (
    Flask, Response, abort, redirect, render_template_string, request, session
)
from google.cloud import storage

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None",  # cross-site iframe on dashboards.bidbrain.ai (None requires Secure)
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # stay logged in 12h
    MAX_CONTENT_LENGTH=64 * 1024,             # nothing here takes a sizeable body
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")                 # from Secret Manager
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")                              # private data bucket (empty until a job exists)
DATA_OBJECT = os.environ.get("DATA_OBJECT", "raywhiteprojects.json")       # object inside it

_storage = storage.Client()

# Baked into the container at build time, next to this file. Anchored to __file__ so they load
# regardless of the process working directory.
_dash_dir = Path(__file__).resolve().parent


def _read_bytes(name):
    try:
        return (_dash_dir / name).read_bytes()
    except FileNotFoundError:
        return None


def _read_text(name):
    try:
        return (_dash_dir / name).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


DASHBOARD_HTML = _read_text("dashboard.html")
PLACEHOLDER_JSON = _read_bytes("placeholder.json")

# NO BRAND ASSET FILES, DELIBERATELY. No Ray White Projects artwork has been supplied, and a
# fabricated mark is worse than an obvious stand-in: the estate has twice had to delete a generated
# logo the day the real one arrived. So the lockup on BOTH surfaces is the typographic stand-in
# from the design reference - pure markup, no binary in the repo to rot, and no /logo.svg route to
# 404 behind the platform proxy. When Ray White supply the artwork, gen_brand_assets.py writes
# logo.svg + icon.png and injects the lockup into dashboard.html between its markers; add the
# routes back in the same change. See README.md -> "Brand assets".

# STAFF-ONLY content for the Internal notes tab, kept OUT of data.json on purpose - the precedent
# is client_schneidersecpwr's Reports tab and client_lacevo's notes tab, whose content is fetched
# from its own endpoint so that hiding the tab is not the only thing protecting it. Read the honest
# limitation on the route below.
INTERNAL_NOTES_JSON = _read_bytes("internal_notes.json")

# The favicon as an inline data URI, for the same reason as the lockup: a stand-in mark that needs
# no file and no route. Bone square, ink letterforms - it reads on both light and dark tab strips.
FAVICON = ("data:image/svg+xml,"
           "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' fill='%23F4F2ED'/%3E"
           "%3Ctext x='16' y='21' font-family='Helvetica,Arial,sans-serif' font-size='13'"
           " font-weight='600' text-anchor='middle' fill='%23131311'%3ERW%3C/text%3E%3C/svg%3E")

# =================================================================================================
# LOGIN
#
# Ported from the design reference. Two things changed on the way in, both deliberate:
#
#   1. The reference's submit handler was a DEMO - preventDefault, a 1.25s timer, then a link to
#      the dashboard file. This posts to /login for real and re-renders with {{ error }} on a bad
#      password. The JS that remains is progressive: it only disables the button and runs the
#      loading bar, so the form still submits with scripting off.
#   2. The headline names the CLIENT, not the project. The login is the tenant's front door and
#      project is a filter on the other side of it, so "Monair, Greenwich" here would be wrong the
#      day a second project lands.
#
# Ray White yellow is a FILL and a RULE here, never text: it carries the focus ring, the field's
# underline sweep and the submit hover, and the ink-on-bone button is what stays readable.
# =================================================================================================
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ray White Projects - client access</title>
<link rel="icon" href="{{ favicon }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@300;400;500;600&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#131311;--ink-2:#1C1C19;--concrete:#8E8B83;--concrete-2:#B4B0A7;
  --bone:#F4F2ED;--yellow:#FFE512;--sand:#C4B49C;--line:rgba(244,242,237,.12);
  --ease:cubic-bezier(.16,1,.3,1);
}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--ink);color:var(--bone);font-family:Archivo,"Helvetica Neue",Arial,sans-serif;
  font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;overflow:hidden}
.serif{font-family:"Instrument Serif",Georgia,serif;font-weight:400}
button,input{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--yellow);outline-offset:3px;border-radius:4px}

/* backdrop: stacked floorplates, the building itself */
.stage{position:fixed;inset:0;overflow:hidden;z-index:0}
.stage svg{position:absolute;inset:0;width:100%;height:100%}
.glow{position:absolute;width:120vmax;height:120vmax;right:-35vmax;top:-45vmax;border-radius:50%;
  background:radial-gradient(circle,rgba(196,180,156,.20) 0%,rgba(196,180,156,.06) 38%,transparent 68%);
  animation:drift 34s var(--ease) infinite alternate}
@keyframes drift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(-7vw,5vh,0) scale(1.12)}}
.sweep{position:absolute;inset:0;background:linear-gradient(105deg,transparent 30%,rgba(244,242,237,.055) 48%,transparent 62%);
  transform:translateX(-40%);animation:sweep 17s linear infinite}
@keyframes sweep{to{transform:translateX(60%)}}
.vignette{position:absolute;inset:0;background:radial-gradient(120% 90% at 30% 40%,transparent 40%,rgba(0,0,0,.6) 100%)}

.shell{position:relative;z-index:2;height:100%;display:grid;grid-template-columns:1.15fr .85fr;
  max-width:1360px;margin:0 auto;padding:40px 56px}
.col{display:flex;flex-direction:column;justify-content:space-between;min-width:0}
.col.right{align-items:flex-end;justify-content:center}

/* agency then client, the house lockup */
.lockup{display:flex;align-items:center;gap:16px}
.agency{display:flex;align-items:center;gap:9px;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--concrete-2)}
.agency i{width:6px;height:6px;border-radius:50%;background:var(--yellow);display:block;
  box-shadow:0 0 0 0 rgba(255,229,18,.6);animation:pulse 2.6s ease-out infinite}
@keyframes pulse{70%{box-shadow:0 0 0 9px rgba(255,229,18,0)}100%{box-shadow:0 0 0 0 rgba(255,229,18,0)}}
.divider{width:1px;height:26px;background:var(--line)}
.client{display:flex;align-items:center;gap:11px}
.client .sq{width:30px;height:30px;background:var(--bone);display:grid;place-items:center;flex:none}
.client .sq span{font-weight:600;font-size:11px;letter-spacing:-.04em;color:var(--ink)}
.client .wm{font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--concrete);line-height:1.5}
.client .wm b{display:block;color:var(--bone);font-weight:500;letter-spacing:.17em}

h1{font-size:clamp(46px,6.8vw,92px);line-height:.96;margin:0;letter-spacing:-.015em}
h1 em{font-style:italic;color:var(--sand)}
.foot{font-size:11px;color:#5F5C56;letter-spacing:.04em}

.card{width:100%;max-width:372px;background:rgba(28,28,25,.72);backdrop-filter:blur(18px);
  border:1px solid var(--line);padding:38px 36px 32px}
.card h2{font-size:22px;margin:0 0 30px;letter-spacing:-.01em;font-weight:400}
.field{margin-bottom:30px;position:relative}
.field label{display:block;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--concrete);margin-bottom:9px}
.field input{width:100%;background:transparent;border:0;border-bottom:1px solid var(--line);
  padding:8px 0 10px;font-size:15px;transition:border-color .4s var(--ease)}
.field input::placeholder{color:#5F5C56}
.field input:focus{outline:none}
.field .rule{position:absolute;left:0;bottom:0;height:1px;width:0;background:var(--yellow);transition:width .5s var(--ease)}
.field input:focus ~ .rule{width:100%}
.submit{width:100%;background:var(--bone);color:var(--ink);border:0;padding:15px 20px;cursor:pointer;
  display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:13px;font-weight:500;
  letter-spacing:.06em;text-transform:uppercase;position:relative;overflow:hidden;
  transition:background .35s var(--ease)}
.submit:hover{background:var(--yellow)}
.submit .arrow{transition:transform .45s var(--ease)}
.submit:hover .arrow{transform:translateX(5px)}
.submit[disabled]{cursor:progress;opacity:.9}
.submit .bar{position:absolute;left:0;bottom:0;height:2px;width:0;background:var(--ink);opacity:.35}
.submit.loading .bar{width:100%;transition:width 1.15s linear}
.msg{font-size:12px;margin:14px 0 0;min-height:18px;color:var(--concrete)}
.msg.err{color:#E5A3A3}

.rise{opacity:0;transform:translateY(16px);animation:rise .95s var(--ease) forwards}
.d1{animation-delay:.05s}.d3{animation-delay:.30s}.d4{animation-delay:.42s}.d6{animation-delay:.66s}
@keyframes rise{to{opacity:1;transform:none}}
.plate{opacity:0;animation:plate 1.5s var(--ease) forwards}
@keyframes plate{to{opacity:1}}

@media (max-width:980px){
  body{overflow:auto}
  .shell{grid-template-columns:1fr;gap:48px;padding:32px 26px 44px;height:auto;min-height:100%}
  .col.right{align-items:stretch;justify-content:flex-start}
  .card{max-width:none}
}
/* `*` matches ELEMENTS, never pseudo-elements, so name them explicitly - otherwise a decorative
   animation on a ::before keeps looping for exactly the visitors this rule exists to protect. */
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none !important;transition:none !important}
  .rise,.plate{opacity:1;transform:none}
}
/* BB-LOGIN-KIT:css v1 */

  /* ==========================================================================
     BB LOGIN KIT v1 - the client-facing front door.
     Canonical source: scripts/motion_kit/ (re-apply with scripts/apply_login_kit.py).
     Do NOT hand-edit this block in a main.py - edit the template and re-run.

     Mostly presentation - a slow brand-tinted wash, a card that arrives rather than appears, and
     one press/hover/focus vocabulary - plus three small pieces of REAL behaviour that a password
     gate should have had all along: a show/hide toggle, a Caps Lock warning (the most common
     reason a correct password is typed wrong), and a submit state so nobody double-posts and
     wonders whether the click registered. Those three live in the script at the end of the page.

     Geometry uses `translate`/`scale`, never the `transform` shorthand, so it composes with an
     existing transform instead of replacing it. Everything stops under prefers-reduced-motion.
     ========================================================================== */
  :root{--bl-accent:rgb(255,229,18);--bl-glow:rgba(255,229,18,0.42);--bl-ease:cubic-bezier(.22,1,.36,1)}

  /* the wash: three big soft orbs on their own slow cycles, behind everything, transform-only.
     position:fixed keeps them out of the flex flow of the centred body. */
  .bb-lgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .bb-lgfx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-lgfx .o1{width:62vw;height:56vh;top:-16%;left:-10%;animation:blOrb1 24s ease-in-out infinite;
    background:radial-gradient(circle,rgba(255,229,18,0.2) 0%,transparent 68%)}
  .bb-lgfx .o2{width:54vw;height:48vh;bottom:-18%;right:-12%;animation:blOrb2 29s ease-in-out infinite;
    background:radial-gradient(circle,rgba(196,180,156,0.14) 0%,transparent 68%)}
  .bb-lgfx .o3{width:46vw;height:42vh;top:28%;right:4%;animation:blOrb3 33s ease-in-out infinite;
    background:radial-gradient(circle,rgba(244,242,237,0.11) 0%,transparent 70%)}
  @keyframes blOrb1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(70px,54px) scale(1.10)}}
  @keyframes blOrb2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-64px,-48px) scale(1.09)}}
  @keyframes blOrb3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-52px,44px) scale(1.08)}}

  /* the card arrives */
  form.card,main.cell{position:relative;z-index:1;animation:blIn .66s var(--bl-ease) both}
  @keyframes blIn{from{opacity:0;translate:0 12px;scale:.99}to{opacity:1;translate:none;scale:none}}

  /* Inputs: a brand caret, a legible placeholder, and the field's own focus treatment eased in
     rather than snapped on. Deliberately NO focus ring added here - every one of these logins
     already styles input:focus, and a second offset outline on top of it reads as an error
     state. The ring below is for the two controls that had no focus style at all. */
  input{transition:border-color .18s var(--bl-ease),box-shadow .22s var(--bl-ease),
                   background-color .18s var(--bl-ease);caret-color:var(--bl-accent)}
  input::placeholder{color:rgba(255,255,255,.52);opacity:1}

  /* the password field carries its own reveal control */
  .bb-pw{position:relative;display:block}
  .bb-pw input{padding-right:58px}
  /* Centred with `translate`, NOT `transform`: four of these logins carry a
     `button:hover{transform:translateY(-1px)}` on the bare element selector, which is MORE
     specific than this class rule and would replace a `transform` here outright - dropping the
     -50% and making the control jump half its height down the field the moment you hover it.
     `translate` is a separate property, so their lift composes with the centring instead. */
  .bb-pw-t{position:absolute;right:6px;top:50%;translate:0 -50%;
    height:21px;padding:0 7px;margin:0;width:auto;cursor:pointer;
    /* LONGHANDS, never the `font` shorthand: `font:600 10.5px/1 inherit` is INVALID - `inherit`
       is not a legal component of the shorthand - so the whole declaration was dropped and the
       control inherited the client's own `button{font-size:15px}`. That is why it rendered at
       15px in a 76x30 slab instead of the small pill it was meant to be. */
    font-family:inherit;font-size:9px;font-weight:600;line-height:1;
    letter-spacing:.06em;text-transform:uppercase;
    color:rgba(255,255,255,.52);background:transparent;border:1px solid rgba(255,255,255,.20);border-radius:6px;
    transition:color .18s var(--bl-ease),border-color .18s var(--bl-ease),
               background-color .18s var(--bl-ease),scale .12s var(--bl-ease)}
  .bb-pw-t:hover{color:var(--bl-accent);border-color:var(--bl-accent);background:rgba(255,229,18,0.1)}
  .bb-pw-t:active{scale:.94}
  .bb-pw-t:focus-visible{outline:2px solid var(--bl-accent);outline-offset:2px}

  /* Caps Lock: silent until it matters, and it never moves the layout when it appears */
  .bb-caps{overflow:hidden;max-height:0;opacity:0;margin:0;text-align:center;
    font-size:11.5px;font-weight:600;letter-spacing:.02em;color:#F5B942;
    transition:max-height .24s var(--bl-ease),opacity .24s var(--bl-ease),margin .24s var(--bl-ease)}
  .bb-caps.on{max-height:24px;opacity:1;margin:9px 0 0}

  /* the button depresses, lifts and glows - and says something while the round trip happens */
  button[type="submit"]{transition:background-color .18s var(--bl-ease),box-shadow .24s var(--bl-ease),
    filter .18s var(--bl-ease),translate .16s var(--bl-ease),scale .1s var(--bl-ease),opacity .18s}
  button[type="submit"]:hover{translate:0 -1px;box-shadow:0 12px 28px -14px var(--bl-glow);filter:brightness(1.05)}
  button[type="submit"]:active{translate:0 0;scale:.985}
  button[type="submit"]:focus-visible{outline:2px solid var(--bl-accent);outline-offset:3px}
  button[type="submit"][disabled]{opacity:.72;cursor:progress;translate:none;scale:none;
    box-shadow:none;filter:none}

  /* A server-rendered error shakes ONCE, on load, flagged by the script. It is deliberately not
     `.err:not(:empty)` - the Google sign-in flow writes progress text into the same element, and
     shaking an informational message is wrong. */
  .err.bb-shake{animation:blShake .42s var(--bl-ease) both}
  @keyframes blShake{0%,100%{translate:0}18%{translate:-5px}38%{translate:4px}58%{translate:-3px}78%{translate:2px}}

  @media (prefers-reduced-motion: reduce){
    .bb-lgfx span{animation:none !important}
    form.card,main.cell{animation:none !important}
    .err.bb-shake{animation:none !important}
    input,button[type="submit"],.bb-pw-t,.bb-caps{transition:none !important}
    button[type="submit"]:hover,button[type="submit"]:active{translate:none !important;scale:none !important}
    /* NOT `translate:none` on the toggle - that IS its vertical centring, not an animation */
    .bb-pw-t:active{scale:none !important}
  }
  /* BB LOGIN KIT v1 ends */
/* /BB-LOGIN-KIT:css */
</style>
</head>
<body>

<div class="stage" aria-hidden="true">
  <div class="glow"></div>
  <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice">
    <defs>
      <linearGradient id="plate" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#F4F2ED" stop-opacity=".10"/>
        <stop offset="70%" stop-color="#F4F2ED" stop-opacity=".02"/>
        <stop offset="100%" stop-color="#F4F2ED" stop-opacity="0"/>
      </linearGradient>
      <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="3"/>
        <feColorMatrix type="saturate" values="0"/></filter>
    </defs>
    <g id="plates"></g>
    <rect width="1600" height="900" filter="url(#grain)" opacity=".035"/>
  </svg>
  <div class="sweep"></div>
  <div class="vignette"></div>
</div>

<main class="shell">
  <div class="col">
    <div class="lockup rise d1">
      <div class="agency"><i></i>100% Digital</div>
      <div class="divider"></div>
      <!-- Typographic stand-in until artwork is supplied; see the note above LOGIN_HTML. -->
      <div class="client">
        <div class="sq"><span>RW</span></div>
        <div class="wm"><b>Ray White</b>Projects</div>
      </div>
    </div>

    <h1 class="serif rise d3">Ray White<br><em>Projects</em></h1>

    <div class="foot rise d6">dashboards.bidbrain.ai</div>
  </div>

  <div class="col right">
    <form class="card rise d4" id="form" method="post" action="login" autocomplete="on">
      <h2 class="serif">Client access</h2>
      <div class="field">
        <label for="code">Access code</label>
        <!-- BB-LOGIN-KIT:pw v1 --><div class="bb-pw">
    <input id="code" name="password" type="password" placeholder="Password" autofocus
               autocomplete="current-password" required>
    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>
  </div>
  <div class="bb-caps" role="status" aria-live="polite"></div>
  <!-- /BB-LOGIN-KIT:pw -->
        <span class="rule"></span>
      </div>
      <button class="submit" id="go" type="submit">
        <span id="golabel">Enter</span>
        <span class="arrow">&#8594;</span>
        <span class="bar"></span>
      </button>
      <p class="msg err" id="msg" role="status" aria-live="polite">{{ error if error }}</p>
    </form>
  </div>
</main>

<script>
/* stacked floorplates, faded in level by level */
(function () {
  var g = document.getElementById('plates');
  var NS = 'http://www.w3.org/2000/svg';
  var levels = 11, top = 150, h = 46, gap = 12;
  for (var i = 0; i < levels; i++) {
    var r = document.createElementNS(NS, 'rect');
    var inset = i * 16;
    r.setAttribute('x', 820 + inset);
    r.setAttribute('y', top + i * (h + gap));
    r.setAttribute('width', 700 - inset);
    r.setAttribute('height', h);
    r.setAttribute('fill', 'url(#plate)');
    r.setAttribute('class', 'plate');
    r.style.animationDelay = (0.35 + i * 0.09) + 's';
    g.appendChild(r);
  }
})();

/* Submit-once. PROGRESSIVE: the form posts on its own, this only reflects that it is in flight,
   so the page still works with scripting off. */
document.getElementById('form').addEventListener('submit', function () {
  var btn = document.getElementById('go');
  btn.classList.add('loading');
  document.getElementById('golabel').textContent = 'Checking';
  /* Disable AFTER this tick: disabling a submit button during its own submit event cancels the
     submission in some browsers. */
  setTimeout(function () { btn.disabled = true; }, 0);
});
</script>
<!-- BB-LOGIN-KIT:js v1 -->
<script>
/* BB LOGIN KIT v1 - the three behavioural bits. Canonical source scripts/motion_kit/.
   Everything here degrades to the plain form if any of it is missing: the input, the button and
   the POST are untouched, so a login can never fail because of this script. */
(function(){
  var form = document.querySelector('form[action="/login"]') || document.querySelector('form');
  var pw   = document.querySelector('.bb-pw input') ||
             document.querySelector('input[name="password"]');
  var togg = document.querySelector('.bb-pw-t');
  var caps = document.querySelector('.bb-caps');
  var btn  = form && (form.querySelector('button[type="submit"]') || form.querySelector('button'));

  /* 1. show / hide. Type is flipped in place, so the field keeps its value, its name and its
        position in the tab order; the caret is put back where the user was. */
  if (togg && pw){
    togg.addEventListener('click', function(){
      var hidden = pw.type === 'password';
      var at = pw.value.length;
      pw.type = hidden ? 'text' : 'password';
      togg.textContent = hidden ? 'Hide' : 'Show';
      togg.setAttribute('aria-label', (hidden ? 'Hide' : 'Show') + ' password');
      pw.focus();
      try { pw.setSelectionRange(at, at); } catch(e){}
    });
  }

  /* 2. Caps Lock. getModifierState is only meaningful on a real key event, so it is read on the
        field's own keys - no global listener, nothing polled.
        The TEXT is written here rather than sitting in the markup: the element is a live region,
        and a permanent "Caps Lock is on" string would be read out by a screen reader whenever the
        form is traversed, whether it is on or not. Empty when off, filled when on - which is also
        what makes role=status announce it at the right moment. */
  if (caps && pw){
    var CAPS_MSG = 'Caps Lock is on';
    var set = function(on){
      if (caps.classList.contains('on') === on) return;
      caps.classList.toggle('on', on);
      caps.textContent = on ? CAPS_MSG : '';
    };
    var check = function(e){
      if (typeof e.getModifierState !== 'function') return;
      set(e.getModifierState('CapsLock'));
    };
    pw.addEventListener('keydown', check);
    pw.addEventListener('keyup', check);
    pw.addEventListener('blur', function(){ set(false); });
  }

  /* 3. Submit state. The disable happens on the NEXT tick, after the browser has already started
        the POST, so it stops a second submission without ever blocking the first. Only the label
        of a plain text button is swapped - a button with markup inside (an arrow, an icon) keeps
        its contents.
        The `pageshow` reset is NOT optional: log in, then press Back, and the browser restores
        this page from its cache exactly as it was - disabled button, "Checking..." still on it -
        which would strand someone on a login form they cannot submit. pageshow fires on every
        restore, so the control is always live again. */
  if (form && btn){
    var label0 = btn.textContent;
    form.addEventListener('submit', function(){
      setTimeout(function(){
        btn.disabled = true;
        if (!btn.children.length) btn.textContent = 'Checking...';
      }, 0);
    });
    window.addEventListener('pageshow', function(){
      btn.disabled = false;
      if (!btn.children.length) btn.textContent = label0;
    });
  }

  /* 4. A server-rendered error announces itself once. */
  var err = document.querySelector('.err');
  if (err && err.textContent.trim()) err.classList.add('bb-shake');
})();
</script>
<!-- /BB-LOGIN-KIT:js --></body>
</html>"""


def authed():
    """Authenticated by THIS dashboard's own password (session["ok"]) OR by a platform-issued SSO
    cookie from dashboards.bidbrain.ai that names this client. Fail-closed and fail-safe: any
    problem falls back to password-only, so this can never break the existing gate, and neither
    path can be satisfied by a session belonging to another tenant."""
    if session.get("ok") is True:
        return True
    try:
        from platform_sso import sso_allows
        return sso_allows(request)
    except Exception:
        return False


def _login_page(error=None, status=200):
    return render_template_string(LOGIN_HTML, error=error, favicon=FAVICON), status


@app.get("/")
def home():
    if not authed():
        return _login_page()
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    # no-store so a redeploy is picked up immediately, never served stale from the browser or the
    # platform proxy (matches /data.json).
    return Response(DASHBOARD_HTML, mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.post("/login")
def login():
    if hmac.compare_digest(request.form.get("password", ""), DASH_PASSWORD):
        session["ok"] = True
        session.permanent = True
        return redirect("/")
    return _login_page("Incorrect password.", 401)


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


def _bucket_blob():
    if not GCS_BUCKET:
        return None
    return _storage.bucket(GCS_BUCKET).blob(DATA_OBJECT)


@app.get("/data.json")
def data():
    """The dashboard fetches this. Only an authenticated session gets it; everyone else gets 401,
    and the bucket itself stays private.

    PLACEHOLDER FALLBACK: until an export job has written a real raywhiteprojects.json to the
    bucket, serve the baked-in SAMPLE payload so the dashboard renders end to end behind its
    preview notice. Real data always wins the moment it exists."""
    if not authed():
        abort(401)
    blob = _bucket_blob()
    if blob is not None:
        try:
            if blob.exists():
                return Response(blob.download_as_bytes(), mimetype="application/json",
                                headers={"Cache-Control": "no-store"})
        except Exception:
            app.logger.exception("data.json bucket read failed; serving placeholder")
    if PLACEHOLDER_JSON is not None:
        return Response(PLACEHOLDER_JSON, mimetype="application/json",
                        headers={"Cache-Control": "no-store"})
    abort(404)


@app.get("/data-version.json")
def data_version():
    """Just the payload's timestamp, for the dashboard's 5-minute refresh poll.

    The poll used to re-download the WHOLE payload to compare one field, which on a sibling
    dashboard cost ~134 MB/hour for every tab left open. This answers from blob METADATA
    (`blob.reload()` is a metadata-only call - no object download), so the common case of nothing
    having changed costs one small API round trip."""
    if not authed():
        abort(401)
    blob = _bucket_blob()
    if blob is not None:
        try:
            blob.reload()
            if blob.updated:
                return Response(json.dumps({"last_updated": blob.updated.isoformat()}),
                                mimetype="application/json", headers={"Cache-Control": "no-store"})
        except Exception:
            pass        # no object yet, or no permission: fall through to the baked payload
    if PLACEHOLDER_JSON is not None:
        try:
            m = json.loads(PLACEHOLDER_JSON.decode("utf-8")).get("meta", {})
            return Response(json.dumps({"last_updated": m.get("last_updated") or m.get("generated")}),
                            mimetype="application/json", headers={"Cache-Control": "no-store"})
        except Exception:
            pass
    abort(404)


@app.get("/internal/notes.json")
def internal_notes():
    """Content for the staff-only Internal notes tab, fetched lazily when that tab is opened.

    It is a SEPARATE object from /data.json on purpose: keeping it off the payload every session
    downloads means hiding the tab is not the only thing standing between a client and it. The
    limitation to be honest about is that this route AUTHENTICATES BUT DOES NOT AUTHORIZE BY ROLE -
    the bb_sso cookie carries the allowed-client list, not the role - so a logged-in client who
    guessed the path would be served it. Closing that gap means putting the role in the SSO token in
    bidbrain-platform/dash/platform_sso.py, which is vendored into every dashboard in the estate.

    Until then, nothing genuinely sensitive goes in internal_notes.json. That ceiling matters more
    here than on most tenants, because the notes name the developer as a separate stakeholder and
    record which plan figures are still placeholders - agency commentary, not client reporting."""
    if not authed():
        abort(401)
    if INTERNAL_NOTES_JSON is None:
        abort(404)
    return Response(INTERNAL_NOTES_JSON, mimetype="application/json",
                    headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz():
    return Response("ok", mimetype="text/plain")
