#!/usr/bin/env python
"""build_exec_kpis.py - build config/exec-kpis.json for The Grid's Executive tab.

The Executive tab shows each client's ONE headline KPI (leads / ROAS / impressions / clicks /
enquiries) vs target, with a daily/weekly/monthly trend + supporting metrics. This script produces
the LIVE data for it: it reads each client's own data.json from GCS
(gs://bidbrain-analytics-<c>-dash/<c>.json - the EXACT JSON that client's dashboard serves, built
from the BigQuery layer, so the exec numbers match the dashboards to the digit) and writes
grid-core/config/exec-kpis.json in the SAME shape as the front-end's `EXC` preview array. The grid
serves that file statically; `renderExec()` fetches it and drops it in over the preview
(EX_SRC -> 'live'), falling back to the baked preview if it is absent/offline.

Run (needs Application Default Credentials with objectViewer on the client buckets, e.g.
`gcloud auth application-default login` as ian@100.digital):

    .venv/Scripts/python.exe grid-core/scripts/build_exec_kpis.py            # write the file
    .venv/Scripts/python.exe grid-core/scripts/build_exec_kpis.py --check    # print, do NOT write

Robustness: each client is extracted in its own try/except; a client that fails is SKIPPED (the
front-end keeps its preview card for it), so a partial pull never breaks the tab. The per-client
extraction paths below are transcribed from the data-contract analysis; VALIDATE the printed numbers
against each dashboard once, with creds, before trusting them (nested field names in the daily[]
arrays that were not 100% pinned in analysis are marked #VERIFY).

Currency is per client (kept in the label, e.g. "S$4.10"); values are raw numbers.
"""
import os, sys, json, datetime as dt

REGION_BUCKET = "bidbrain-analytics-{c}-dash"
OUT = os.path.join(os.path.dirname(__file__), "..", "config", "exec-kpis.json")

PHONE_EMAIL_CONTACT = ("phone", "email", "contact")   # vmch enquiry key-event name substrings


# ---------- tiny helpers -------------------------------------------------------
def g(d, path, default=None):
    """dotted get: g(d,'a.b.c')."""
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def num(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _date(v):
    if not v:
        return None
    s = str(v)[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def _bucket_key(d, grain):
    if grain == "d":
        return d.isoformat()
    if grain == "w":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{d.year}-{d.month:02d}"   # month


def _spark(series, grain, kind):
    """Calendar-bucket sparkline (<=12 points): sum per day/week/month; ratio => num/den per bucket."""
    buckets = {}
    for row in series:
        d0 = row[0]
        if d0 is None:
            continue
        b = buckets.setdefault(_bucket_key(d0, grain), [0.0, 0.0])
        b[0] += num(row[1], 0) or 0
        if kind == "ratio":
            b[1] += num(row[2], 0) or 0
    vals = [((b[0] / b[1]) if (kind == "ratio" and b[1]) else b[0]) for k in sorted(buckets) for b in [buckets[k]]]
    return [round(v, 4) for v in vals[-12:]]


def _roll_delta(series, kind, days):
    """% change of the last `days` vs the prior `days`, as ROLLING day-windows anchored at the latest
    date. Robust to a partial final calendar period AND to weekly-grained series (so a false -90% MoM
    from comparing an incomplete month against a full one can't happen)."""
    pts = [r for r in series if r[0] is not None]
    if not pts:
        return 0
    last = max(r[0] for r in pts)
    cur, prev = [0.0, 0.0], [0.0, 0.0]
    for r in pts:
        off = (last - r[0]).days
        tgt = cur if off < days else (prev if off < 2 * days else None)
        if tgt is None:
            continue
        tgt[0] += num(r[1], 0) or 0
        if kind == "ratio":
            tgt[1] += num(r[2], 0) or 0
    if kind != "ratio" and prev[0] and cur[0] < 0.02 * prev[0]:
        return 0   # recent delivery essentially stopped (flight ended / dormant) -> neutral, not a decline to flag
    if kind == "ratio":
        c = cur[0] / cur[1] if cur[1] else 0
        p = prev[0] / prev[1] if prev[1] else 0
    else:
        c, p = cur[0], prev[0]
    return int(round((c - p) / p * 100)) if p else 0


def trend(series, kind="sum", no_daily=False):
    win = {"d": 3, "w": 7, "m": 30}
    gd, sk = {}, {}
    for grain in ("d", "w", "m"):
        if no_daily and grain == "d":
            gd["d"], sk["d"] = None, None      # front-end falls back d->w
            continue
        gd[grain] = _roll_delta(series, kind, win[grain])
        sk[grain] = _spark(series, grain, kind)
    if no_daily:
        gd["d"], sk["d"] = gd["w"], sk["w"]
    return gd, sk


# ---------- per-client extraction ---------------------------------------------
# Each entry returns the DYNAMIC fields (val,target,series,kind,noDaily,sec) from that client's
# data.json; the static template (name/agency/group/obj/mlbl/unit/fmt/labels/dash) lives in BASE.
def ex_cloudflare(d):
    rows = g(d, "pacing.rows", []) or []
    val = num(g(d, "qoq.q3.accepted"))
    target = sum(num(r.get("ALLOCATED_TARGET"), 0) or 0 for r in rows) or None
    # weekly accepted series from pacing.rows (STATUS accepted, keyed on the Monday DAY)
    ser = [(_date(r.get("DAY")), num(r.get("LEAD_VALUE"), 0))
           for r in rows if str(r.get("STATUS", "")).lower() == "accepted"]
    by = g(d, "qoq.q3.by_status", {}) or {}
    acc = num(by.get("Accepted"), 0) or 0
    rej = num(by.get("Rejected"), 0) or 0
    ar = round(acc / (acc + rej) * 100) if (acc + rej) else None
    sec = [[f"{ar}%" if ar is not None else "-", "Acceptance rate", None]]
    return dict(val=val, target=target, series=ser, kind="sum", noDaily=True, sec=sec)


def ex_schneider(d):
    camps = g(d, "campaigns", []) or []
    leadgen = [c for c in camps if num(c.get("target"))]
    val = sum(num(c.get("leads"), 0) or 0 for c in leadgen) or None
    target = sum(num(c.get("target"), 0) or 0 for c in leadgen) or None
    ser = [(_date(r.get("week_start")), num(r.get("leads"), 0)) for r in (g(d, "cs_weekly", []) or [])]
    sec = [[f"{len(leadgen)} of {len(leadgen)}", "Programs on pace", None]]
    return dict(val=val, target=target, series=ser, kind="sum", noDaily=True, sec=sec)


def ex_resetdata(d):
    val = (num(g(d, "kpi.ga_conv"), 0) or 0) + (num(g(d, "kpi.me_conv"), 0) or 0) + (num(g(d, "kpi.rd_conv"), 0) or 0)
    ser = [(_date(r.get("date") or r.get("day")), num(r.get("conversions"), 0))
           for r in (g(d, "ad_campaign_daily", []) or [])
           if str(r.get("platform", "")).lower() in ("google", "meta", "reddit")]
    paying = num(g(d, "crm.kpi.paying"))
    sec = [[str(int(paying)) if paying is not None else "-", "Paying customers", None]]
    return dict(val=val or None, target=None, series=ser, kind="sum", noDaily=False, sec=sec)


def ex_vmch(d):
    # Headline = TTD ad-ATTRIBUTED conversions (post-view + post-click), NOT raw GA4 key events (the
    # raw all-time enquiry count includes the non-comparable 2025 taxonomy ~110k - not a KPI).
    val = (num(g(d, "kpi.ad_post_view"), 0) or 0) + (num(g(d, "kpi.ad_post_click"), 0) or 0)
    # trend proxy: GA4 enquiry key events, CLAMPED to the flight (>= 2026-04-01) to drop the old taxonomy.
    FLIGHT = dt.date(2026, 4, 1)
    ser = [(_date(r.get("day") or r.get("date")), num(r.get("key_events"), 0))
           for r in (g(d, "ga4_key_events_daily", []) or [])
           if any(t in str(r.get("event_name", "")).lower() for t in PHONE_EMAIL_CONTACT)
           and (_date(r.get("day") or r.get("date")) or dt.date(2000, 1, 1)) >= FLIGHT]
    imps = num(g(d, "kpi.ad_imps"))
    sec = [[_compact(imps) if imps else "-", "Impressions", None]]
    return dict(val=(val or None), target=None, series=ser, kind="sum", noDaily=False, sec=sec)


def ex_mongodb(d):
    rows = g(d, "rows", []) or []
    val = sum(num(r.get("imps"), 0) or 0 for r in rows) or None
    ser = [(_date(r.get("date")), num(r.get("imps"), 0)) for r in rows]
    leads = sum(num(c.get("total"), 0) or 0 for c in (g(d, "cs_by_programme", []) or []))
    sec = [[_thousands(leads), "CS leads", None]]
    return dict(val=val, target=None, series=ser, kind="sum", noDaily=False, sec=sec)


def ex_stt(d):
    val = num(g(d, "kpi.ad_clicks"))
    ser = [(_date(r.get("day") or r.get("date")), num(r.get("ad_clicks", r.get("clicks")), 0))  # VERIFY daily click field
           for r in (g(d, "daily", []) or [])]
    conv = num(g(d, "kpi.conversions"))
    sec = [[_compact(conv) if conv else "-", "Leads - key events", None]]
    return dict(val=val, target=None, series=ser, kind="sum", noDaily=False, sec=sec)


def ex_schneiderlqai(d):
    dv = g(d, "delivery", []) or []
    val = sum(num(r.get("imps"), 0) or 0 for r in dv) or None
    target = sum(num(ch.get("imp_target", ch.get("impressions_target")), 0) or 0
                 for ch in (g(d, "plan.channels", []) or [])) or None
    ser = [(_date(r.get("date")), num(r.get("imps"), 0)) for r in dv]
    return dict(val=val, target=target, series=ser, kind="sum", noDaily=False, sec=[])


def ex_proptrack(d):
    val = num(g(d, "kpi.ad_imps"))
    ser = [(_date(r.get("date") or r.get("day")), num(r.get("imps"), 0)) for r in (g(d, "ad_campaign_daily", []) or [])]
    clicks = num(g(d, "kpi.ad_clicks"))
    sec = [[_compact(clicks) if clicks else "-", "Clicks - site traffic", None]]
    return dict(val=val, target=None, series=ser, kind="sum", noDaily=False, sec=sec)


def ex_tlm(d):
    rev = num(g(d, "kpi.g_revenue")); spend = num(g(d, "kpi.g_spend_aud"))
    val = round(rev / spend, 2) if (rev and spend) else None
    ser = [(_date(r.get("date")), num(r.get("g_revenue"), 0), num(r.get("g_spend_aud"), 0))
           for r in (g(d, "daily", []) or [])]
    sec = [[f"A${_compact(rev)}" if rev else "-", "Revenue", None]]
    return dict(val=val, target=None, series=ser, kind="ratio", noDaily=False, sec=sec)


def _compact(n):
    if n is None:
        return "-"
    n = float(n); a = abs(n)
    if a >= 1e6:
        return f"{n/1e6:.1f}".rstrip("0").rstrip(".") + "M"
    if a >= 1e4:
        return f"{round(n/1e3)}k"
    return f"{n:,.0f}"


def _thousands(n):
    return f"{int(n):,}" if n is not None else "-"


# static template per client (labels/structure the front-end EXC uses); numbers are overlaid.
BASE = [
    {"key": "cloudflare", "extract": ex_cloudflare, "mono": "CF", "name": "Cloudflare", "agency": "Transmission",
     "group": "lead", "dash": "Cloudflare", "obj": "Lead gen + Site traffic", "mlbl": "Accepted CS leads (Q3 to date)",
     "unit": "", "fmt": "int", "targetLbl": "Q3 target"},
    {"key": "schneider", "extract": ex_schneider, "mono": "SE", "name": "Schneider", "agency": "Transmission",
     "group": "lead", "dash": "Schneider", "obj": "Awareness + Site traffic + LGF", "mlbl": "MQL + HQL leads",
     "unit": "", "fmt": "int", "targetLbl": "Plan target (to date)"},
    {"key": "resetdata", "extract": ex_resetdata, "mono": "RD", "name": "Reset Data", "agency": "100% Digital",
     "group": "lead", "dash": "ResetData", "obj": "Leads", "mlbl": "Ad-reported leads", "unit": "", "fmt": "int",
     "targetLbl": None},
    {"key": "vmch", "extract": ex_vmch, "mono": "VM", "name": "Villa Maria (VMCH)", "agency": "100% Digital",
     "group": "lead", "dash": "VMCH", "obj": "Leads", "mlbl": "Ad-attributed enquiries", "unit": "", "fmt": "int",
     "targetLbl": None},
    {"key": "stt", "extract": ex_stt, "mono": "STT", "name": "STT", "agency": "Transmission", "group": "reach",
     "dash": "STT", "obj": "Clicks / site traffic", "mlbl": "Clicks", "unit": "", "fmt": "int", "targetLbl": None},
    {"key": "mongodb", "extract": ex_mongodb, "mono": "MDB", "name": "MongoDB", "agency": "Transmission",
     "group": "reach", "dash": "MongoDB", "obj": "Site traffic + Engagement", "mlbl": "Impressions", "unit": "",
     "fmt": "int", "targetLbl": None},
    {"key": "schneiderlqai", "extract": ex_schneiderlqai, "mono": "LQ", "name": "Schneider LQAIDC",
     "agency": "Transmission", "group": "reach", "dash": None, "obj": "Site traffic / Awareness", "mlbl": "Impressions",
     "unit": "", "fmt": "int", "targetLbl": "Plan (LinkedIn + TTD)"},
    {"key": "proptrack", "extract": ex_proptrack, "mono": "PT", "name": "PropTrack", "agency": "Transmission",
     "group": "reach", "dash": None, "obj": "Awareness / Consideration (site traffic)", "mlbl": "Impressions (flight)",
     "unit": "", "fmt": "int", "targetLbl": None},
    {"key": "tlm", "extract": ex_tlm, "mono": "TLM", "name": "The Little Marionette", "agency": "100% Digital",
     "group": "sales", "dash": "The Little Marionette", "obj": "ROAS", "mlbl": "ROAS (Google)", "unit": "×",
     "fmt": "x", "targetLbl": "Target ROAS"},
]


def _note(b, val, target, gd):
    """A short, honest 'what's happening' line computed from the numbers (AI-written later)."""
    if val is None:
        return "No data yet for this client's headline metric."
    m = gd.get("m") or 0
    dirn = "up" if m > 1 else "down" if m < -1 else "flat"
    lead = {"up": f"Trending up, about {m}% month over month.",
            "down": f"Trending down, about {abs(m)}% month over month.",
            "flat": "Holding roughly flat month over month."}[dirn]
    if target:
        pct = round(val / target * 100)
        return f"{lead} At {pct}% of the {b['targetLbl'].lower()}."
    return lead


def fetch_json(key):
    from google.cloud import storage
    bucket = REGION_BUCKET.format(c=key)
    blob = storage.Client().bucket(bucket).blob(f"{key}.json")
    return json.loads(blob.download_as_bytes())


def build(check=False, to_stdout=False):
    verbose = check and not to_stdout   # --stdout must emit ONLY the JSON doc (server captures it)
    out, skipped = [], []
    for b in BASE:
        try:
            data = fetch_json(b["key"])
            dyn = b["extract"](data)
            gd, sk = trend(dyn["series"], dyn.get("kind", "sum"), dyn.get("noDaily", False))
            val, target = dyn["val"], dyn.get("target")
            pace = round(val / target, 4) if (val is not None and target) else None
            client = {
                "key": b["key"], "mono": b["mono"], "name": b["name"], "agency": b["agency"], "group": b["group"],
                "dash": b["dash"], "obj": b["obj"], "mlbl": b["mlbl"], "unit": b["unit"], "fmt": b["fmt"],
                "val": (round(val, 2) if val is not None else 0),
                "target": (round(target, 2) if target else None),
                "targetLbl": b["targetLbl"], "pace": pace,
                "noDaily": dyn.get("noDaily", False), "gd": gd, "sk": sk,
                "sec": dyn.get("sec", []), "sum": _note(b, val, target, gd),
            }
            out.append(client)
            if verbose:
                print(f"  {b['key']:16} val={val} target={target} gd={gd.get('m')}%/mo  ({b['mlbl']})")
        except Exception as e:                              # skip -> front-end keeps its preview card
            skipped.append((b["key"], str(e)[:120]))
            if verbose:
                print(f"  {b['key']:16} SKIPPED: {str(e)[:120]}")
    doc = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "source": "client data.json (GCS)", "clients": out}
    if to_stdout:                       # server-spawn path: emit ONLY the JSON on stdout
        sys.stdout.write(json.dumps(doc))
        return doc
    if not check:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        print(f"wrote {os.path.relpath(OUT)} - {len(out)} clients live, {len(skipped)} skipped")
    if skipped and verbose:
        print("skipped:", ", ".join(k for k, _ in skipped))
    return doc


if __name__ == "__main__":
    build(check="--check" in sys.argv, to_stdout="--stdout" in sys.argv)
