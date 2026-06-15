"""PropTrack (Transmission) dashboard web app (Cloud Run service).

Thin password gate + static server. It renders a login screen, and once a
session is authenticated it serves `dashboard.html` and proxies the private
`proptrack.json` from GCS at `/data.json`. All presentation logic — the Overview /
Programmatic / Paid Social tabs and every chart — lives in `dashboard.html`; this
file only decides *who* may see it, not *what* it shows.

Same service pattern as client_STT/dash/main.py (byte-for-byte on the auth/serve/proxy
logic); only the login-page branding and the default data object differ. The org policy
that blocks --allow-unauthenticated is handled the same way — the deploy flips
--no-invoker-iam-check so this app's own password gate is the only door.
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
DATA_OBJECT = os.environ.get("DATA_OBJECT", "proptrack.json")  # object inside it

_storage = storage.Client()

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None

LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PropTrack · Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;
       font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:radial-gradient(1200px 600px at 50% -10%,#1B2230 0%,#0F141C 55%,#080A0E 100%);
       -webkit-font-smoothing:antialiased}
  .card{width:100%;max-width:360px;padding:36px 32px;background:#fff;
        border:1px solid rgba(0,0,0,.06);border-radius:16px;
        box-shadow:0 20px 64px rgba(0,0,0,.45)}
  .logo{display:flex;justify-content:center;margin-bottom:16px}
  .logo svg{height:34px;width:auto;display:block}
  .brand{font-size:11px;font-weight:700;letter-spacing:1.6px;color:#1F6FEB;margin-bottom:14px;text-align:center}
  h1{font-size:18px;font-weight:700;margin:0 0 4px;color:#171A20;text-align:center}
  p{font-size:13px;color:#667085;margin:0 0 22px;text-align:center}
  input{width:100%;padding:12px 13px;font-size:15px;color:#171A20;background:#fff;
        border:1px solid #E6E8EC;border-radius:10px;outline:none;font-family:inherit}
  input:focus{border-color:#1F6FEB;box-shadow:0 0 0 3px rgba(31,111,235,.14)}
  button{width:100%;margin-top:12px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;
         background:#1F6FEB;color:#fff;border:none;border-radius:10px;font-family:inherit}
  button:hover{background:#1450B5}
  .err{margin-top:12px;font-size:13px;color:#C8362A;min-height:16px;text-align:center}
  .agency-credit{display:flex;align-items:center;gap:9px;color:rgba(255,255,255,.62);
                 font-size:10.5px;font-weight:700;letter-spacing:1px}
  .agency-credit svg{height:15px;width:auto;display:block;opacity:.85}
</style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <div class="logo">
      <svg viewBox="0 0 165 44" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="PropTrack">
        <path d="M0.653937 21.8825C0.585554 33.596 9.93587 43.1446 21.5292 43.2044C33.1225 43.2735 42.5685 33.8217 42.6278 22.1082C42.6871 10.3993 33.3459 0.855292 21.7526 0.795412C21.7161 0.795412 21.6796 0.795412 21.634 0.795412C10.1 0.790806 0.713203 10.2104 0.653937 21.8825Z" fill="#1F6FEB"/>
        <path d="M29.015 34.3606H14.3353C13.1728 34.3606 12.2291 33.4071 12.2291 32.2325V23.5131H10.4693C9.6168 23.5131 8.85547 22.9972 8.52723 22.2049C8.19898 21.408 8.37678 20.5006 8.97856 19.888L20.1798 8.51536C20.5719 8.11922 21.1144 7.88892 21.6706 7.88892C22.2267 7.88892 22.7693 8.11922 23.1613 8.51536L34.3626 19.888C34.9643 20.5006 35.1421 21.408 34.8139 22.2049C34.4856 23.0018 33.7243 23.5131 32.8718 23.5131H31.1121V32.2325C31.1212 33.4071 30.1729 34.3606 29.015 34.3606ZM21.6751 9.73138C21.5976 9.73138 21.5292 9.75902 21.4745 9.8143L10.2733 21.1869C10.1912 21.2698 10.1684 21.3896 10.214 21.4955C10.2596 21.6015 10.3599 21.6706 10.4739 21.6706H13.1454C13.6469 21.6706 14.0572 22.0851 14.0572 22.5918V32.2325C14.0572 32.3891 14.1848 32.5181 14.3398 32.5181H29.0195C29.1745 32.5181 29.3022 32.3891 29.3022 32.2325V22.5918C29.3022 22.0851 29.7125 21.6706 30.2139 21.6706H32.8855C32.9994 21.6706 33.0997 21.6015 33.1453 21.4955C33.1909 21.3896 33.1636 21.2698 33.0861 21.1869L21.8757 9.8143C21.821 9.75902 21.7526 9.73138 21.6751 9.73138Z" fill="#fff"/>
        <path d="M50.0862 31.6568V13.1216H53.6512V31.6568H50.0862ZM52.393 25.2727V22.1773H56.9519C58.0369 22.1773 58.8758 21.9286 59.4821 21.4357C60.0839 20.9429 60.3848 20.2105 60.3848 19.2386C60.3848 18.2667 60.0839 17.5389 59.4821 17.0553C58.8803 16.5716 58.0369 16.3275 56.9519 16.3275H52.3383V13.1216H57.2118C59.4137 13.1216 61.1187 13.6743 62.3223 14.7752C63.5258 15.8807 64.1322 17.3639 64.1322 19.2386C64.1322 21.0903 63.535 22.5596 62.336 23.6467C61.137 24.7337 59.4411 25.2727 57.2391 25.2727H52.393Z" fill="#171A20"/>
        <path d="M69.3522 18.018V21.3022V21.8319V31.6569H65.9695V18.0226H69.3522V18.018ZM72.7577 17.7002H73.4643V21.3529H72.0511C71.2669 21.3529 70.6196 21.6247 70.1135 22.1728C69.6075 22.7209 69.3522 23.4948 69.3522 24.5035H68.5407C68.5407 22.8637 68.7276 21.5463 69.106 20.556C69.4798 19.5703 69.9859 18.8425 70.6241 18.3865C71.2578 17.9305 71.969 17.7002 72.7577 17.7002Z" fill="#171A20"/>
        <path d="M80.6993 31.9747C79.3544 31.9747 78.1509 31.6753 77.0978 31.0765C76.0401 30.4777 75.2149 29.6393 74.6223 28.5615C74.0296 27.4837 73.7333 26.24 73.7333 24.8305C73.7333 23.4164 74.0296 22.1773 74.6223 21.1087C75.2149 20.0401 76.0401 19.2064 77.0978 18.6076C78.1554 18.0088 79.3453 17.7094 80.6765 17.7094C82.0396 17.7094 83.2432 18.0088 84.2917 18.6076C85.3403 19.2064 86.1654 20.0401 86.7672 21.1087C87.369 22.1773 87.6699 23.4164 87.6699 24.8305C87.6699 26.2446 87.369 27.4883 86.7672 28.5615C86.1654 29.6393 85.3403 30.4777 84.2917 31.0765C83.2386 31.6707 82.0442 31.9747 80.6993 31.9747ZM80.6719 28.953C81.3512 28.953 81.9621 28.7918 82.4955 28.4648C83.0289 28.1377 83.4483 27.6725 83.7538 27.0599C84.0592 26.4519 84.2142 25.7057 84.2142 24.8213C84.2142 23.9553 84.0592 23.2183 83.7538 22.6103C83.4483 22.0023 83.0289 21.5371 82.4955 21.2193C81.9621 20.9014 81.3558 20.7402 80.6719 20.7402C80.0063 20.7402 79.4137 20.9014 78.8894 21.2193C78.3651 21.5371 77.9503 22.0023 77.6448 22.6103C77.3394 23.2183 77.1844 23.9553 77.1844 24.8213C77.1844 25.7057 77.3394 26.4519 77.6448 27.0599C77.9503 27.6679 78.3651 28.1377 78.8894 28.4648C79.4137 28.7918 80.0063 28.953 80.6719 28.953Z" fill="#171A20"/>
        <path d="M89.7122 36.1295V18.018H93.0949V22.1774L92.4931 24.8259L93.0949 27.1843V36.1341H89.7122V36.1295ZM97.2845 31.9747C96.2542 31.9747 95.3834 31.749 94.6768 31.2976C93.9702 30.8462 93.4094 30.2566 92.9991 29.5242C92.5888 28.7919 92.2971 28.0088 92.1193 27.1797C91.946 26.3506 91.8594 25.5583 91.8594 24.7983C91.8594 24.0567 91.946 23.2737 92.1193 22.4399C92.2925 21.6108 92.5888 20.837 92.9991 20.123C93.4094 19.4091 93.9656 18.8241 94.6631 18.3773C95.3606 17.9259 96.236 17.7002 97.2845 17.7002C98.4561 17.7002 99.4956 18.0088 100.403 18.626C101.31 19.2433 102.026 20.0908 102.55 21.1686C103.074 22.2465 103.334 23.4625 103.334 24.8213C103.334 26.1802 103.074 27.4008 102.55 28.4879C102.026 29.5749 101.31 30.4271 100.403 31.0443C99.4956 31.6615 98.4561 31.9747 97.2845 31.9747ZM96.473 28.9254C97.4669 28.9254 98.2875 28.5708 98.9212 27.866C99.5594 27.1613 99.8785 26.1525 99.8785 24.849C99.8785 23.5408 99.5594 22.5321 98.9212 21.8181C98.2829 21.1042 97.4669 20.7449 96.473 20.7449C95.4609 20.7449 94.6358 21.1042 93.9975 21.8181C93.3593 22.5321 93.0402 23.5454 93.0402 24.849C93.0402 26.1571 93.3593 27.1613 93.9975 27.866C94.6358 28.5754 95.4609 28.9254 96.473 28.9254Z" fill="#171A20"/>
        <path d="M115.972 13.1216V16.3505H101.137V13.1216H115.972ZM110.337 14.7337V31.6522H106.772V14.7337H110.337Z" fill="#171A20"/>
        <path d="M117.886 18.018V21.3022V21.8319V31.6569H114.504V18.0226H117.886V18.018ZM121.292 17.7002H121.998V21.3529H120.585C119.801 21.3529 119.154 21.6247 118.648 22.1728C118.142 22.7209 117.886 23.4948 117.886 24.5035H117.075C117.075 22.8637 117.262 21.5463 117.64 20.556C118.014 19.5703 118.52 18.8425 119.158 18.3865C119.792 17.9305 120.508 17.7002 121.292 17.7002Z" fill="#171A20"/>
        <path d="M127.87 31.9746C126.822 31.9746 125.91 31.8042 125.13 31.4587C124.351 31.1133 123.744 30.625 123.307 29.9894C122.869 29.3537 122.65 28.5937 122.65 27.7139C122.65 26.8664 122.878 26.1202 123.33 25.4753C123.785 24.8305 124.419 24.3376 125.244 23.9921C126.065 23.6467 127.018 23.4762 128.103 23.4762C129.571 23.4762 130.706 23.8401 131.508 24.5633C132.311 25.2865 132.712 26.2307 132.712 27.3961C132.712 28.9161 132.274 30.0585 131.403 30.8231C130.533 31.5877 129.356 31.9746 127.87 31.9746ZM131.855 31.6568V29.2478L131.695 28.8516V25.807L131.618 25.5951V23.4256C131.618 22.8083 131.508 22.3017 131.289 21.9009C131.071 21.5048 130.751 21.2146 130.332 21.0258C129.913 20.8415 129.407 20.7494 128.814 20.7494C128.08 20.7494 127.455 20.9382 126.94 21.3206C126.425 21.6983 126.047 22.2326 125.8 22.9235L122.997 21.7305C123.453 20.2842 124.219 19.2524 125.304 18.6305C126.389 18.0133 127.601 17.7047 128.946 17.7047C130.031 17.7047 131.03 17.8936 131.946 18.2759C132.862 18.6536 133.601 19.2432 134.162 20.0354C134.722 20.8323 135 21.8457 135 23.0801V31.6568H131.855ZM128.919 29.4827C129.739 29.4827 130.41 29.3215 130.925 29.0037C131.44 28.6858 131.7 28.2436 131.7 27.6817C131.7 27.1013 131.44 26.6499 130.925 26.3321C130.41 26.0142 129.739 25.8576 128.919 25.8576C128.098 25.8576 127.428 26.0142 126.913 26.3229C126.398 26.6315 126.138 27.0875 126.138 27.6863C126.138 28.2528 126.393 28.6904 126.913 29.0083C127.428 29.3261 128.098 29.4827 128.919 29.4827Z" fill="#171A20"/>
        <path d="M143.672 31.9746C142.395 31.9746 141.251 31.6752 140.239 31.0764C139.227 30.4776 138.415 29.6439 137.813 28.5753C137.212 27.5066 136.911 26.2584 136.911 24.8305C136.911 23.4164 137.212 22.1727 137.813 21.0949C138.415 20.017 139.222 19.1833 140.239 18.5937C141.251 18.0041 142.395 17.7047 143.672 17.7047C144.684 17.7047 145.618 17.8705 146.475 18.2068C147.332 18.543 148.08 19.0681 148.714 19.7821C149.352 20.496 149.817 21.4219 150.118 22.5504L147.132 23.6375C146.817 22.578 146.37 21.8272 145.796 21.385C145.222 20.9428 144.51 20.7218 143.672 20.7218C143.111 20.7218 142.582 20.8784 142.085 21.187C141.588 21.4956 141.182 21.9516 140.868 22.5504C140.553 23.1492 140.398 23.9092 140.398 24.8259C140.398 25.7425 140.558 26.5071 140.868 27.1151C141.182 27.7231 141.588 28.1791 142.085 28.4785C142.582 28.7779 143.111 28.93 143.672 28.93C144.51 28.93 145.217 28.7089 145.796 28.2667C146.37 27.8245 146.817 27.0829 147.132 26.0419L150.118 27.1289C149.821 28.2252 149.352 29.1326 148.714 29.8558C148.075 30.579 147.328 31.1133 146.475 31.4587C145.623 31.7996 144.684 31.9746 143.672 31.9746Z" fill="#171A20"/>
        <path d="M151.823 31.6568V13.1216H155.228V31.6568H151.823ZM160.207 31.6568L154.914 24.4528L160.129 18.0179H164.269L157.745 25.6688L157.822 23.1815L164.346 31.6568H160.207Z" fill="#171A20"/>
      </svg>
    </div>
    <div class="brand">PROPTRACK · PAID MEDIA</div>
    <h1>Dashboard access</h1>
    <p>Enter the password to continue.</p>
    <input type="password" name="password" placeholder="Password" autofocus
           autocomplete="current-password">
    <button type="submit">Unlock</button>
    <div class="err">{{ error or "" }}</div>
  </form>
  <div class="agency-credit">
    <span>BY</span>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 255.629 39.901" role="img" aria-label="Transmission"><g fill-rule="evenodd"><path d="M226.901 11.201h-.116v28.253h-5.672V.444h7.908l6.359 23.35h.114V.444h5.616v39.01h-6.473zm-18.28 28.7c-6.186 0-9.568-3.567-9.568-9.808V9.807c-.004-6.242 3.381-9.806 9.568-9.806s9.57 3.566 9.57 9.808v20.283c0 6.241-3.38 9.809-9.57 9.809zm3.267-30.484c0-2.786-1.262-3.845-3.267-3.845s-3.266 1.059-3.266 3.845v21.065c0 2.786 1.263 3.845 3.266 3.845s3.267-1.059 3.267-3.845zM189.771.444h6.3v39.01h-6.3zm-2.522 29.648c0 6.241-3.208 9.808-9.4 9.808s-9.4-3.567-9.4-9.808v-2.4h5.959v2.787c0 2.786 1.261 3.789 3.266 3.789s3.265-1 3.265-3.789c0-2.842-1.261-4.96-5.385-8.471-5.271-4.514-6.933-7.746-6.933-12.2 0-6.242 3.15-9.808 9.282-9.808s9.281 3.566 9.281 9.808v1.226h-5.959V9.417c0-2.787-1.145-3.846-3.15-3.846s-3.151 1.059-3.151 3.846c0 2.842 1.261 4.959 5.385 8.47 5.279 4.514 6.94 7.746 6.94 12.205zm-20.283 0c0 6.241-3.209 9.808-9.4 9.808s-9.4-3.567-9.4-9.808v-2.4h5.959v2.787c0 2.786 1.261 3.789 3.265 3.789s3.266-1 3.266-3.789c0-2.842-1.261-4.96-5.386-8.471-5.271-4.514-6.933-7.746-6.933-12.2.012-6.243 3.158-9.807 9.289-9.807s9.282 3.566 9.282 9.808v1.226h-5.959V9.417c0-2.787-1.145-3.846-3.15-3.846s-3.15 1.059-3.15 3.846c0 2.842 1.261 4.959 5.387 8.47 5.269 4.514 6.93 7.746 6.93 12.205zM139.349.444h6.3v39.01h-6.3zm-9.455 11.035h-.114l-4.241 27.975h-5.958l-4.584-27.585h-.115v27.585h-5.5V.444h8.767l4.584 27.7h.114l4.24-27.7h8.762v39.01h-5.958zm-22.92 18.613c0 6.241-3.209 9.808-9.4 9.808s-9.4-3.567-9.4-9.808v-2.4h5.959v2.787c0 2.786 1.261 3.789 3.266 3.789s3.265-1 3.265-3.789c0-2.842-1.261-4.96-5.385-8.471-5.271-4.514-6.933-7.746-6.933-12.2.003-6.243 3.16-9.807 9.291-9.807s9.282 3.566 9.282 9.808v1.226h-5.959V9.417c0-2.787-1.146-3.846-3.151-3.846s-3.151 1.059-3.151 3.846c0 2.842 1.261 4.959 5.385 8.47 5.271 4.514 6.932 7.746 6.932 12.2zM71.508 11.201h-.114v28.253h-5.672V.444h7.907l6.36 23.35h.115V.444h5.615v39.01h-6.475zM56.549 32.376h-7.731l-1.089 7.078h-5.786L48.359.444h9.226l6.417 39.01h-6.36zM52.714 7.355h-.115l-2.98 19.728h6.073zM33.749 34.662v-6.131c0-3.622-1.261-4.959-4.125-4.959h-2.175v15.882h-6.3V.444h9.511C37.192.444 40 3.398 40 9.416v3.066c0 4.012-1.318 6.576-4.126 7.857v.112c3.145 1.281 4.175 4.179 4.175 8.25v6.018a11.2 11.2 0 0 0 .688 4.737h-6.415c-.345-1.005-.573-1.618-.573-4.794zm-.057-24.633c0-2.786-.975-4.012-3.209-4.012h-3.034v11.984h2.46c2.349 0 3.783-1 3.783-4.124zm-20.8 29.425H6.589V6.017H0V.444h19.481v5.573h-6.589z" fill="#fff"></path><path d="M244.628 39.454v-10.7h11v10.7z" fill="#e60b7f"></path></g></svg>
  </div>
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
