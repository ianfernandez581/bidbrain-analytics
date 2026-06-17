"""Build Chart.js configs from the VMCH data payload and render them to PNG.

Rendering is done by a headless Chromium (Playwright) loading chart_page.html and
screenshotting the <canvas> after Chart.js paints — so the PNGs are the *real*
Chart.js visuals (same library + palette as dash/dashboard.html), not a matplotlib
look-alike. This is the "PNG of Chart.js charts" path: pixel-faithful to the live
dashboards.

Each builder returns a dict {key, title, cfg} where cfg is a Chart.js
configuration object (type/data/options + width/height). render_all() turns the
list into {key: png_path}.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CHART_JS = HERE / "chart.umd.min.js"
CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
PAGE = HERE / "chart_page.html"

# Palette (mirror of dash/dashboard.html :root)
ORANGE, ORANGE_DEEP, ORANGE_SOFT = "#EB3300", "#C22A00", "#FCE3DA"
MAROON, MAROON2, MAROON_SOFT = "#4C2736", "#7A4154", "#F3E7EB"
INK, INK2, MUTE, LINE = "#2A1E20", "#574A4C", "#8C7E80", "#E7DDD8"
RAMP = [ORANGE, MAROON, MAROON2, ORANGE_DEEP, "#D98A2B", "#6E8B6F", "#9C6B8E", "#B8B0A6"]

W, H = 1000, 520  # default chart size (2x DPR -> 2000x1040 PNG)


def _ensure_chart_js() -> None:
    if not CHART_JS.exists():
        print(f"  fetching Chart.js -> {CHART_JS.name}")
        urllib.request.urlretrieve(CHART_JS_CDN, CHART_JS)


def _money_axis(sym: str) -> dict:
    return {"ticks": {"callback": "__MONEY__"}}  # replaced with a JS fn at render


# --- chart builders ----------------------------------------------------------
# Each takes the parsed data dict and returns a Chart.js config (or None to skip).

def chart_spend_sessions(d: dict) -> dict | None:
    """Monthly TTD spend (bars) vs website sessions (line) — the hero story."""
    months = [m["month"] for m in d["monthly"]]
    if not months:
        return None
    spend = [round(m.get("ad_spend_aud") or 0, 2) for m in d["monthly"]]
    sessions = [m.get("sessions") or 0 for m in d["monthly"]]
    return {
        "title": "Ad spend vs website sessions, by month",
        "width": W, "height": H,
        "type": "bar",
        "data": {
            "labels": months,
            "datasets": [
                {"type": "bar", "label": "TTD spend (A$)", "data": spend,
                 "backgroundColor": ORANGE_SOFT, "borderColor": ORANGE,
                 "borderWidth": 1, "yAxisID": "y", "order": 20},
                {"type": "line", "label": "Website sessions", "data": sessions,
                 "borderColor": MAROON, "backgroundColor": MAROON,
                 "borderWidth": 3, "tension": 0.3, "pointRadius": 3,
                 "yAxisID": "y1", "order": 1},
            ],
        },
        "options": {
            "scales": {
                "y": {"position": "left", "title": {"display": True, "text": "Spend (A$)"},
                      "grid": {"color": LINE}},
                "y1": {"position": "right", "title": {"display": True, "text": "Sessions"},
                       "grid": {"display": False}},
                "x": {"grid": {"display": False}},
            },
        },
    }


def chart_spend_by_campaign(d: dict) -> dict | None:
    """Doughnut of TTD spend split across the 4 service-line campaigns."""
    camps = [c for c in d.get("ad_campaigns", []) if (c.get("spend_aud") or 0) > 0]
    if not camps:
        return None
    camps.sort(key=lambda c: c.get("spend_aud") or 0, reverse=True)
    return {
        "title": "Trade Desk spend by campaign",
        "width": 760, "height": 520,
        "type": "doughnut",
        "data": {
            "labels": [c["campaign"] for c in camps],
            "datasets": [{
                "data": [round(c["spend_aud"], 2) for c in camps],
                "backgroundColor": RAMP[:len(camps)],
                "borderColor": "#fff", "borderWidth": 2,
            }],
        },
        "options": {
            "cutout": "55%",
            "plugins": {"legend": {"position": "right"}},
        },
    }


def chart_enquiries_by_type(d: dict) -> dict | None:
    """Website enquiries (GA4 key events) by type, summed over the flight."""
    agg: dict[str, float] = {}
    for r in d.get("ga4_key_events", []):
        agg[r["event_name"]] = agg.get(r["event_name"], 0) + (r.get("key_events") or 0)
    items = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:8]
    if not items:
        return None
    return {
        "title": "Website enquiries by type",
        "width": W, "height": 520,
        "type": "bar",
        "data": {
            "labels": [k for k, _ in items],
            "datasets": [{
                "label": "Enquiries", "data": [round(v) for _, v in items],
                "backgroundColor": MAROON, "borderColor": MAROON2, "borderWidth": 1,
            }],
        },
        "options": {
            "indexAxis": "y",
            "plugins": {"legend": {"display": False}},
            "scales": {"x": {"grid": {"color": LINE}, "beginAtZero": True},
                       "y": {"grid": {"display": False}}},
        },
    }


def chart_imps_sessions_trend(d: dict) -> dict | None:
    """Monthly impressions vs sessions — reach vs site traffic."""
    months = [m["month"] for m in d["monthly"]]
    if not months:
        return None
    imps = [m.get("ad_imps") or 0 for m in d["monthly"]]
    sessions = [m.get("sessions") or 0 for m in d["monthly"]]
    return {
        "title": "Impressions vs website sessions, by month",
        "width": W, "height": H,
        "type": "line",
        "data": {
            "labels": months,
            "datasets": [
                {"label": "TTD impressions", "data": imps, "borderColor": ORANGE,
                 "backgroundColor": ORANGE_SOFT, "borderWidth": 3, "tension": 0.3,
                 "pointRadius": 3, "yAxisID": "y", "fill": True},
                {"label": "Website sessions", "data": sessions, "borderColor": MAROON,
                 "backgroundColor": MAROON, "borderWidth": 3, "tension": 0.3,
                 "pointRadius": 3, "yAxisID": "y1"},
            ],
        },
        "options": {
            "scales": {
                "y": {"position": "left", "title": {"display": True, "text": "Impressions"},
                      "grid": {"color": LINE}},
                "y1": {"position": "right", "title": {"display": True, "text": "Sessions"},
                       "grid": {"display": False}},
                "x": {"grid": {"display": False}},
            },
        },
    }


BUILDERS = [
    ("spend_sessions", chart_spend_sessions),
    ("spend_by_campaign", chart_spend_by_campaign),
    ("enquiries_by_type", chart_enquiries_by_type),
    ("imps_sessions", chart_imps_sessions_trend),
]


def build_configs(data: dict) -> list[dict]:
    out = []
    for key, fn in BUILDERS:
        cfg = fn(data)
        if cfg:
            cfg["key"] = key
            out.append(cfg)
    return out


def render_all(data: dict, out_dir: Path) -> dict[str, dict]:
    """Render every chart to PNG. Returns {key: {"title":..., "path":...}}."""
    from playwright.sync_api import sync_playwright

    _ensure_chart_js()
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = build_configs(data)
    result: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)
        page.goto(PAGE.resolve().as_uri())
        page.wait_for_function("typeof window.renderChart === 'function'")

        for cfg in configs:
            key = cfg["key"]
            page.evaluate(_inject_money_fn(cfg))
            page.evaluate("(cfg) => window.renderChart(cfg)", cfg)
            page.wait_for_function("window.chartReady && window.chartReady()")
            page.wait_for_timeout(120)  # let the canvas settle
            png = out_dir / f"{key}.png"
            page.locator("#stage").screenshot(path=str(png))
            result[key] = {"title": cfg["title"], "path": png}
            print(f"  rendered {key} -> {png.name}")

        browser.close()
    return result


def _inject_money_fn(cfg: dict) -> str:
    # Placeholder hook if we later want JS tick callbacks; kept minimal for now.
    return "() => true"
