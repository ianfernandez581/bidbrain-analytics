"""Adriatic Furniture sample dashboard web app (Cloud Run service).

A minimal static server. It serves the self-contained `dashboard.html`, which
carries its own illustrative sample data inline — so unlike the client_STT /
client_mongodb services there is NO GCS bucket, no `/data.json` proxy and no SQL
pipeline behind it. There is also NO password gate: this is an open pitch/sample
dashboard, deliberately shareable by link.

Cloud Run's org policy (Domain Restricted Sharing) blocks
--allow-unauthenticated, so the deploy flips --no-invoker-iam-check instead to
make the service reachable; with no login screen the page is then fully open.
"""
import os
from pathlib import Path
from flask import Flask, Response

app = Flask(__name__)

# Dashboard HTML is baked into the container at build time, next to this file.
# Anchor to __file__ so it loads regardless of the process working directory.
try:
    DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")
except FileNotFoundError:
    DASHBOARD_HTML = None


@app.get("/")
def home():
    if DASHBOARD_HTML is None:
        return Response("dashboard.html is missing from the deploy.", status=500)
    # no-store so a redeploy of the dashboard is picked up immediately, never
    # served stale from the browser or any proxy.
    return Response(DASHBOARD_HTML, mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
