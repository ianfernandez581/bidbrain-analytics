r"""On-demand: turn the live VMCH data into a Google Slides deck.

    .\.venv\Scripts\python.exe clients\client_vmch\report\report.py

Pipeline:
  1. load vmch.json  (from the GCS bucket, or --local <path>)
  2. render the dashboard charts to PNG via headless Chart.js (charts.py)
  3. build a branded Slides deck in YOUR Google Drive (deck.py)
  4. print the deck URL

Auth uses your gcloud Application Default Credentials. ADC needs Drive + Slides
scopes on top of cloud-platform; if they're missing you'll get a one-line fix.
See report/README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import google.auth
from google.auth.exceptions import RefreshError

sys.path.insert(0, str(Path(__file__).parent))
import charts          # noqa: E402
from deck import DeckBuilder   # noqa: E402

PROJECT = "bidbrain-analytics"
BUCKET = "bidbrain-analytics-vmch-dash"
DATA_OBJECT = "vmch.json"
HERE = Path(__file__).parent
OUT_DIR = HERE / "_out"

SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
]

SCOPE_HELP = (
    "\nADC is missing the Slides/Drive scopes. Run this once, then re-run:\n\n"
    "  gcloud auth application-default login --scopes="
    "openid,https://www.googleapis.com/auth/cloud-platform,"
    "https://www.googleapis.com/auth/drive,"
    "https://www.googleapis.com/auth/presentations\n"
)


def load_data(local: str | None) -> dict:
    if local:
        return json.loads(Path(local).read_text(encoding="utf-8"))
    from google.cloud import storage
    blob = storage.Client(project=PROJECT).bucket(BUCKET).blob(DATA_OBJECT)
    print(f"loading gs://{BUCKET}/{DATA_OBJECT}")
    return json.loads(blob.download_as_text())


def fmt_int(n) -> str:
    return f"{int(n or 0):,}"


def money(d: dict, n) -> str:
    return f"{d.get('currency_sym', 'A$')}{(n or 0):,.0f}"


def build_kpis(d: dict) -> list[tuple[str, str]]:
    k = d["kpi"]
    return [
        ("Ad spend (Trade Desk)", money(d, k.get("ad_spend_aud"))),
        ("Impressions delivered", fmt_int(k.get("ad_imps"))),
        ("Clicks", fmt_int(k.get("ad_clicks"))),
        ("Website sessions", fmt_int(k.get("sessions"))),
        ("Post-view conversions", fmt_int(k.get("ad_post_view"))),
        ("Post-click conversions", fmt_int(k.get("ad_post_click"))),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="path to a local vmch.json instead of GCS")
    ap.add_argument("--folder", help="Drive folder ID to create the deck in")
    ap.add_argument("--title", help="override the deck title")
    args = ap.parse_args()

    data = load_data(args.local)
    win = data.get("window", {})
    flight = f"{win.get('start', '?')} – {win.get('end', '?')}"
    title = args.title or "VMCH — Programmatic Display Performance"
    subtitle = (f"100% Digital  ·  The Trade Desk + GA4  ·  {flight}\n"
                f"Data through {data.get('data_through', '')}")

    print("rendering charts...")
    rendered = charts.render_all(data, OUT_DIR)
    chart_list = [{"key": k, **v} for k, v in rendered.items()]

    print("authenticating (ADC: Drive + Slides)...")
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
    except google.auth.exceptions.DefaultCredentialsError as e:
        print(f"ERROR: no ADC found ({e}).{SCOPE_HELP}")
        sys.exit(1)

    print("building deck...")
    try:
        url = DeckBuilder(creds).build(
            title=title, subtitle=subtitle,
            kpis=build_kpis(data), charts=chart_list, folder_id=args.folder)
    except RefreshError as e:
        print(f"ERROR: token refresh failed — likely missing scopes ({e}).{SCOPE_HELP}")
        sys.exit(1)
    except Exception as e:
        msg = str(e)
        if "insufficient" in msg.lower() or "scope" in msg.lower() or "403" in msg:
            print(f"ERROR: {e}{SCOPE_HELP}")
            sys.exit(1)
        raise

    print(f"\nDONE -> {url}")


if __name__ == "__main__":
    main()
