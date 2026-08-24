"""HireRight paid-media dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`hireright.json` from GCS at `/data.json`. All presentation logic — the Overview
and Paid Media tabs and every chart — lives in `dashboard.html`; this file only
decides *who* may see it, not *what* it shows.

Same service pattern as client_STT/dash/main.py (byte-for-byte on the
auth/serve/proxy logic); only the login-page branding and the default data
object differ. The org policy that blocks --allow-unauthenticated is handled the
same way — the deploy flips --no-invoker-iam-check so this app's own password
gate is the only door.
"""
import os
import hmac
from pathlib import Path
from flask import (
    Flask, request, redirect, session, Response, render_template_string, abort
)
from google.cloud import storage

app = Flask(__name__)
app.secret_key = os.environ["SESSION_SECRET"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None",  # cross-site iframe on dashboards.bidbrain.ai (None requires Secure)
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # stay logged in 12h
)

# --- config (injected by Cloud Run) ------------------------------------------
DASH_PASSWORD = os.environ["DASH_PASSWORD"].rstrip("\r\n")   # from Secret Manager
GCS_BUCKET = os.environ["GCS_BUCKET"]                        # private data bucket
DATA_OBJECT = os.environ.get("DATA_OBJECT", "hireright.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

# HireRight wordmark - the SUPPLIED artwork (creatives/hireright_logo.png), inlined as a
# base64 data URI. It replaced a hand-drawn SVG approximation that rendered as "HIRE RIGH":
# 9 characters at font-size 52 overflowed its 300-unit viewBox and clipped the final T.
# Inlined rather than served as a file so it cannot 404 behind the platform proxy.
LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HireRight · Paid Media Dashboard</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;
       background:radial-gradient(1200px 600px at 50% -12%,rgba(237,28,36,.22) 0%,#0A0E17 62%),#0A0E17}
  .card{width:100%;max-width:360px;padding:36px 32px;background:#fff;
        border:1px solid rgba(0,0,0,.06);border-radius:16px;
        box-shadow:0 20px 64px rgba(0,0,0,.34)}
  .logo{display:flex;justify-content:center;margin-bottom:22px}
  .logo img{height:38px;width:auto;display:block}
  .brand{font-size:11px;font-weight:700;letter-spacing:1.6px;color:#ED1C24;margin-bottom:14px;text-align:center}
  h1{font-size:18px;font-weight:700;margin:0 0 4px;color:#1A1A1A;text-align:center}
  p{font-size:13px;color:#6B7480;margin:0 0 22px;text-align:center}
  input{width:100%;padding:12px 13px;font-size:15px;color:#1A1A1A;background:#fff;
        border:1px solid #E6E9ED;border-radius:10px;outline:none}
  input:focus{border-color:#ED1C24;box-shadow:0 0 0 3px rgba(237,28,36,.14)}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#ED1C24;color:#fff;border:none;border-radius:10px}
  button:hover{background:#C41019}
  .err{margin-top:12px;font-size:13px;color:#C8362A;min-height:16px;text-align:center}


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
  :root{--bl-accent:rgb(237,28,36);--bl-glow:rgba(237,28,36,0.42);--bl-ease:cubic-bezier(.22,1,.36,1)}

  /* the wash: three big soft orbs on their own slow cycles, behind everything, transform-only.
     position:fixed keeps them out of the flex flow of the centred body. */
  .bb-lgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
  .bb-lgfx span{position:absolute;display:block;border-radius:50%;will-change:transform}
  .bb-lgfx .o1{width:62vw;height:56vh;top:-16%;left:-10%;animation:blOrb1 24s ease-in-out infinite;
    background:radial-gradient(circle,rgba(237,28,36,0.2) 0%,transparent 68%)}
  .bb-lgfx .o2{width:54vw;height:48vh;bottom:-18%;right:-12%;animation:blOrb2 29s ease-in-out infinite;
    background:radial-gradient(circle,rgba(74,131,199,0.14) 0%,transparent 68%)}
  .bb-lgfx .o3{width:46vw;height:42vh;top:28%;right:4%;animation:blOrb3 33s ease-in-out infinite;
    background:radial-gradient(circle,rgba(42,165,176,0.11) 0%,transparent 70%)}
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
  input::placeholder{color:rgba(0,0,0,.45);opacity:1}

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
    color:rgba(0,0,0,.45);background:transparent;border:1px solid rgba(0,0,0,.14);border-radius:6px;
    transition:color .18s var(--bl-ease),border-color .18s var(--bl-ease),
               background-color .18s var(--bl-ease),scale .12s var(--bl-ease)}
  .bb-pw-t:hover{color:var(--bl-accent);border-color:var(--bl-accent);background:rgba(237,28,36,0.1)}
  .bb-pw-t:active{scale:.94}
  .bb-pw-t:focus-visible{outline:2px solid var(--bl-accent);outline-offset:2px}

  /* Caps Lock: silent until it matters, and it never moves the layout when it appears */
  .bb-caps{overflow:hidden;max-height:0;opacity:0;margin:0;text-align:center;
    font-size:11.5px;font-weight:600;letter-spacing:.02em;color:#9A6400;
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
<body><!-- BB-LOGIN-KIT:fx v1 -->
<div class="bb-lgfx" aria-hidden="true"><span class="o1"></span><span class="o2"></span><span class="o3"></span></div><!-- /BB-LOGIN-KIT:fx -->
  <form class="card" method="POST" action="/login">
    <div class="logo">
      <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAS4AAABDCAIAAACtP38kAAAOHklEQVR42u2df0wUZxrH3113h11ml0EdkWzAokvsD7QCXdJ4kibEVU8SGjWuiSVpSzShJWlB6y8oQs8Cpr1T6PWAUhvbeNKe+EdpqbQUGhJY9A8RMPZsuIJ/uGS7wooM7DLLsj/ujz25YXZ2dnbdZRGeT/gDx3nnnRnmO8/7Pu/zPCNyu90IAIBII4ZbAAAgRQAAQIoAAFIEAACkCACLEQncAmBp09/fbzKZpFLpwnSn1Wo5z+Hhw4erV6/euHEjjuOcDUWwmAEsYaxW64kTJ5qamgiCCHdfNE3Hx8ffunWLudFsNnd3dyclJSUmJk5OTt6+fXvnzp2cagSrCCx9zGazxWIJ3/EVCgVCyGKxxMbGsl4EAwMDSUlJXV1do6OjGo1my5Yt33333WuvvQZSBJYdKpVKp9OFtYvh4eH79+9HRUV528mpqanU1NS2trbKysrLly8rlUq5XD4yMpKQkABSBJYROI7n5+eHu5fq6uqqqirOMbBMJvP80traihBKTU0dGBiw2+1gFYFlB0mS4e4iOjra13/ZbDbPL9nZ2TU1NQih0dHRrVu3ghQBIPRMT0/7egsolUqDwXDp0iWSJOvq6m7cuCGXy8FtAwALjVar7ejoMJlM8fHxJpMJIbRz504E64oAEBE1ms1mg8GQkZHBM1oGKQLAQsxX/U5ZIfANABDEoAIAAANUIHS4KMpN0wghkVwuwjCRXL4MbwJFUTMzMyGW4ueff87akpGRkZaWhnwHFjU2Nsrn/wG0Wu2GDRuQ7+DAxsZGND80IScnJ6AmPKxZsyYpKYkn+tabe/futbS0yIN6jGiaTklJ4QwFDpSZjg7H0JCgIY1SKX7mGUly8or4eOHHtzU3O00m5pYV8fFRu3YFoZ/Z3l57b6/TaHRPW93jjzwbRatWisg1K2JjMY1GqtEIFzP9zTfMLc6JCblWy3MEp8lka25mNYnW6SRq9dwWN03PtLWxrjcI5AcPin1HsWZlZcXFxSGE5E/yDnJ7MTY2hh4HCnhACDU2Nrp9YzAYmPt7mrS3t/ttwuqltbWVv4knoEEmAJIkX3jhhczMzJKSEoPB4BZAe3u7wIN7gxCqqKhwPzGu6Wnq9OkHCAn8GUtWm7f+afzAARvv3WYy8d5R1kEe5eU5JyYCOk9be/vDnJyxZLXfcxN4Yo4//vA+2vTlyzxNZoeGvDu1dXez7uejvDzh95PzZzSWmB0acocZbqtIEIRUKsUwzPNPo9EoRNWrVq2a+11gE5IkA+oFx3HmifEzOjo6Ojqq1+urqqoqKiqKioqEWEjmVQhH4PUKRxQrKJPAbTa7hoadNxDV1CTJyoq5cIFpE4Qc3z1BBWYJ79yZKix0dHZ6DsJznp5zo3bskGRlKT/5RLp5c5hOTEgTgfeT4yoCvD/LxW0T0AAAwzAMw1QqlUqlKi0tPXHihNVqXXpTFI8eRLGEo7Nz4sCB2d7e8PVla25+9OKLjs5OfhGyzs3R2Unt20sLnlyE450FHlS0eMLzL1682Biep2HxaNLV1zd15oyLosKkw8m9e4N4+kWxhGto2N7fB/6tpexB9TUyJAiCNRyNiopqaGjg9z+xsNvtZrMZPVkgYkjwNUxiqUIUSzhaWmZ++EGemxvaE5jR6y3Hj3n3KOTE3BOU9MABxbHjEXxOOM/T+53CudvCjFElT7sOCwoKtm3bxkoMHRsb6+np6ezsZE78cBzv6+u7efOmQCna7fa4uLjS0tJ169YJ2T8pKSlc5o4kFf+odU1NseXR2urs7nJPUKxHyvpBeWil6BgetpaVuYaGvXUoTk/HdLqozEzPVND5+++OwUH6yhXXb3c9+7snKElOjrKqKiA3bwiJ2r5d7JUciBByDAw4WlqYVyQiSezQIVE0h0NBJNgPv3ytolar3bt3L+Ja+fjiiy+KiopUKhVze09PT25ursAVDplM9sorrwi3omF6nYs2qDmlhb/1lq252XL8GFMkntGgY3hYoP9GkMG/etUzP2SdmOz06eg33mB2JNZopBqNPDd3Rq+nL160f/mlKJZQlpWF8GQCe4vJ5fLcXE4Hg/WzzxwtLfNeK8+nxHxYEalFUckSzhktLCxsa2tj2kaCIH799VeapvHwv+QWBtmePU6Tyfr222wBP3oUqi6cJpOtuNhbh1HvHVUWF/t6cD120rJxozQxUfjqYsRx2+2RkuISd9vs2bNnLncTISSVSu/evbvErhHTaMTJatZ8xjUxEUJvjbehluTkKE+X8T+1YoJQFhaGfNYKbhvkayUAx/G5qgGLDZqmUSiWDdHT4D4N05Ftl/7pvVFZWSkWUEMtJBbG7fVH9BzZPT29ZFYyhEqRJMn6+vqenh5fO4yNjS1AcbsgYJ2zxWLJysoSuDiJYRhFUTU1NQkJCUzT6s26desOHz4cqUGvY3DQ26EiXrsWhSi41HnjOssdiuXlides8d7TJcDbHNCkcbq2buaXX3xKdGmtEksEPpR37tzR6/WId+FusV3b119/ffXqVeaJ2Wy2bdu2BWRUL1265Hc3nU4n3BWEQr3GMF1b5719hTCvr/+J4v37HCPPjRu93aGzN29OnTzpx1QqFCuvXBFoKkWxhPPGdeeN68thfT+AASqO44vT1dHb26tUKuc9E7OzBoPh9u3bTU1N3vma6enpAV2I31fM+Pi4PNwT/UlqpqMDIeS2WEQKxf+s0IMHs4OD9mvXXH193ot44hANUlwPHnhvlCYmctgoi8XV1+fi90wkq5dnJM3S96CqVKra2trz5897l9mSyWQKhYIZrWo0Gl9//fWMjIynbhLoNpsndfsFLqYjhBTHQ7aY7g6wku+yEk/EpMhZvJE5iEURWrQQYuWsVqtarS4qKgq0FB//VTOr6y0SxwxeXy9JSQlZp4+NMLCIpIhhGOdzGSkRokCCckiS/PTTT4NYrCcIwrvqM2sHxSJ4Xj32UHb2rPzgwRCujHG6f2YHB2U0zdkLy3SDkQyxFI1GY0VFRXZ2tq8dTCZTdnb2IvTceOxhQUHB4cOHA9WhJ/CtoqJiy5YtaBHUvUX+pmGKv/4tuAxgHjjdPw693mk0snyhKxISsLw80aqV/3f5/Od3Z3fXk7xcZGfPyn1nYztHRqby3lx2VnH9+vU8j/LIyEgElUYxEhFYrwPPS0RgpiLiCnxLSkriKSwQqWhm1vxQnJ4e29QUjuAyMUFIsrKYUW+epCfHnTus7qQaDVFby1z3oxsbp+YHeQYKf6SOaOVKcNssopHn0aNHX3rpJYvFolAoxsbGTp06xVzEJ0mypqbm5ZdfDkmpi4h5buaHg9MXLjC9pp7cqOmrV2NOnQpH7/JDh6Y6O1kbLcePSTZvZqlx4UPGvEPhQYoRY/fu3UyZWSyW0tLSOduIYZjRaDx//nxqamrEx5ChCgeXJCd7HKpMNdqKi/krwQQNtn07Z/7h5JEjMdXVkYrzRlB8cbExOzvL/Gd+fn5mZub4+DhzyPrjjz9WV1cvmb9ZlFYbdZLDAE6dOfPk9ZQ4povx8bKzZ71HyI6WlskjR2zNzZyBaTMdHbbvvweBLd/MDJIky8vLd+zYYbfb51y7KpWqqqpq//79AXluMAwzmUzvv/++EAepxWJJS0urrKxcmMvE33zT2d8/29Q0bwrX0mL96qtwDFOjdTrHzz+z8qQ8PU51d1mfT5Fqt0uffVaE426rddZgmP2+xfXbv5fS6BGkiILLYGxoaMjPz2e6cAiCePfdd7/99ttAh6nXr18XUtxywVYX5yxV9DvvTPXdYmUq2oqLseeek+3ZE+KnRK1WfvwxlZ/Piuzx/O4JT7NxVbVhj7SfzjkCDFCDZ9++fTqdjjlMxXFcr9c3NDQEWmkKx/FVAkCPvwK9cMPUzEzs0GHv7dN//7tjeDjk3Uk1GuVHH3lnYzHrXDF/OP0r+Ad/WZ7VipevFEmSLC4uZlmquQ/cLZnLVBYWitPTmdrwrDRY6+vCNEclvvkXq0ckzPMkycmJafkBchcDHqAGV2/cb4yYX6cLEpAqIbBJWlpaSUlJVVUVc0RqNBpPnjzZ1dXFs8wYxFWgBawrxVo8IBoaHmVksHaeOXd+5s+7o/yt3wRRPUmq0ay8ds1aV2f78EP+eBrmwfH6ev7q2t4NhU8y5zoKbl66YGVOg5Tihg0bmNnABEH4TT5QqVTxjMQZv+mLMplMrVYzd/PUQeZvFT8/N4e/SWVl5U8//YTmJxZSFFVWVnbu3DnOJunp6cHdx7i4OL+3yGq10jTt2Y0v5CA6WpysRjEEc52db9x4+bL1g3Lm/gghS1m5ZNMmzspOomjcc3zR3JZVKwOapsacOYMXFFjr6hx6vYui3PeGWQ+0OFktfj5FnJgge/VV4ZZQtGatmHEVoknKb3En1o0STVLiQLLY2c3J1RGUosjtdiOur0ewtqxdu5Y/YCVSTWJiYng8MWazeXJykvNdwymVB1w5QUiwxzWBq7LY3MFramo8qcy7du0qLCxEvmvJeCfF8izfuWnayVWBUkySnBr2Pr4Ix4Mrx+amacfQkHN42GkyOR+X8FgRGyvZtCnQL3lwXoWvSwi6CfKX6xzBZVJuKQIhx2w2l5eX19XVIYRKSkoWbNkDALcNAAAgRQAAKQIAAFIEAJAiAAAgRQAAKQIAgCAz4+mDIIiRkZH+/v6HDx+Gr5fVq1dH9gNYAEgRLf5PXHV0dPB89eDJoSgqKyurqakJ7jZIEUD8XwFiJnCFHJvNZgmwlDAAUlwuyOVylUqVmZnJ+qxAmFi/fj3c86cLiEFdOBa4RCVPbDoAUgQAAMFiBgCAFAEAACkCAEgRAACQIgA8PfwXZKbMx8Vxan8AAAAASUVORK5CYII=" alt="HireRight" />
    </div>
    <div class="brand">TRANSMISSION · HIRERIGHT PAID MEDIA</div>
    <h1>Dashboard access</h1>
    <p>Enter the password to continue.</p>
    <!-- BB-LOGIN-KIT:pw v1 --><div class="bb-pw">
    <input type="password" name="password" placeholder="Password" autofocus
           autocomplete="current-password">
    <button class="bb-pw-t" type="button" aria-label="Show password">Show</button>
  </div>
  <div class="bb-caps" role="status" aria-live="polite"></div>
  <!-- /BB-LOGIN-KIT:pw -->
    <button type="submit">Unlock</button>
    <div class="err">{{ error or "" }}</div>
  </form>
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
    # served stale from the browser or any proxy (matches /data.json).
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


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
