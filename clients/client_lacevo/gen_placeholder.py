r"""Generate `dash/placeholder.json` - the Lacevo PREVIEW payload.

Lacevo has no data pipeline yet (no BigQuery dataset, no sql/ views, no export job), so the
dashboard renders from this baked-in SAMPLE payload. It is flagged `meta.placeholder=true`, which
dashboard.html renders behind a loud preview notice.

WHY A GENERATOR AND NOT A HAND-WRITTEN JSON
-------------------------------------------
The whole point of the preview is to agree the METRICS, so the numbers on screen have to be
internally consistent - a KPI that disagrees with the table under it teaches the client to distrust
the layout before the real feeds even land. Everything here is derived from four source arrays
(daily revenue / spend / sessions, and the campaign list) and asserted at the bottom of this file:
channel totals are rolled up from campaigns, stage totals from campaigns, store totals from
products, and the headline KPIs are computed in the browser from `daily` + `channels` exactly the
way they will be once the real job writes this object.

That is also the contract: when the pipeline lands, `job/main.py` emits this SAME SHAPE from
BigQuery views and the template does not change. See README.md -> "Data contract".

    .\.venv\Scripts\python.exe clients\client_lacevo\gen_placeholder.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dash" / "placeholder.json"

# --- the sample window -------------------------------------------------------------------
# 30 delivering days, 14 Aug - 12 Sep 2026. The flight runs one day longer than the data (14 Aug -
# 13 Sep): reporting is always a day behind delivery, and it keeps the pacing card in its IN-FLIGHT
# state, which is the state the client will actually look at most days.
START, END = "2026-08-14", "2026-09-12"
FLIGHT_START, FLIGHT_END = "2026-08-14", "2026-09-13"
DAYS_TOTAL = 31          # inclusive 14 Aug -> 13 Sep
BUDGET = 100_000.0

REVENUE = [9070, 10370, 9630, 11660, 13700, 14900, 12870, 10650, 11850, 13150,
           14440, 16110, 17500, 15000, 12130, 11480, 13790, 15550, 14070, 12680,
           14720, 17030, 18240, 15830, 13520, 12220, 14630, 16570, 15180, 14140]
SPEND = [2640, 2800, 2730, 3010, 3370, 3500, 3230, 2880, 2950, 3140,
         3310, 3470, 3600, 3380, 3070, 2960, 3170, 3410, 3280, 3100,
         3230, 3500, 3670, 3460, 3180, 3010, 3250, 3470, 3340, 3230]
SESSIONS = [2050, 2290, 2170, 2520, 2890, 3110, 2770, 2310, 2460, 2700,
            2960, 3190, 3400, 3030, 2580, 2440, 2800, 3080, 2920, 2650,
            2890, 3250, 3420, 3110, 2760, 2540, 2900, 3180, 3000, 2840]
ORDERS_TOTAL = 1184

# --- campaigns are the GRAIN: channels and stages are rolled up from them -----------------
# (channel, stage, campaign, sub-label, spend, revenue, orders)
CAMPAIGNS = [
    ("Meta", "Acquisition", "S70 pump - broad prospecting", "Video and carousel", 26410, 118900, 318),
    ("Meta", "Awareness", "Mother-first brand story", "Founder video", 14980, 61240, 171),
    ("Meta", "Retargeting", "Cart and view retargeting", "Dynamic product ads", 16810, 88800, 253),
    ("Google Ads", "Capture", "Brand search", "Exact and phrase", 6120, 44850, 132),
    ("Google Ads", "Capture", "Shopping - pump and warmer", "Full catalogue", 13260, 48110, 141),
    ("Google Ads", "Mixed", "Performance Max - all products", "", 9260, 19340, 56),
    ("TikTok", "Acquisition", "Creator video - real mums", "Spark ads", 9500, 31440, 113),
]

# Channel order + colour + the prior-period delta the platform reported. Colours live in the payload
# because the legend, the table swatches and the ROAS bars must all use ONE value per channel.
CHANNELS = [
    ("Meta", "#965F48", "Prospecting and retargeting", 0.14),
    ("Google Ads", "#B08033", "Brand, shopping, performance max", 0.06),
    ("TikTok", "#6E7F68", "Creator-led video", -0.09),
]
STAGE_ORDER = ["Acquisition", "Capture", "Retargeting", "Awareness", "Mixed"]
STAGE_COLOUR = {"Acquisition": "#965F48", "Capture": "#B08033", "Retargeting": "#A98A6E",
                "Awareness": "#6E7F68", "Mixed": "#9A928A"}

# (product, units, revenue, unit_price) - units None where the line is a bundle with no unit count.
PRODUCTS = [
    ("S70 in-bra breast pump set", 612, 244188, 399.00),
    ("Bundles and multi-buy", None, 63126, None),
    ("N6 portable bottle warmer", 318, 41022, 129.00),
    ("Empower light therapy set", 96, 33504, 349.00),
    ("Flanges and replacement parts", 742, 21518, 29.00),
    ("Tote bag", 158, 9322, 59.00),
]

FUNNEL = [("Sessions", 84210), ("Product views", 38940), ("Added to cart", 9120),
          ("Reached checkout", 3480), ("Orders", ORDERS_TOTAL)]


def _days(start, n):
    from datetime import date, timedelta
    y, m, d = (int(x) for x in start.split("-"))
    d0 = date(y, m, d)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _apportion(total, weights):
    """Split an integer total across weights, largest-remainder, so the parts sum EXACTLY.
    Rounding each share independently would leave the daily orders off the headline by a few - the
    kind of one-unit drift that makes a reader doubt the whole page."""
    s = float(sum(weights))
    raw = [total * w / s for w in weights]
    out = [int(x) for x in raw]
    rem = total - sum(out)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[:rem]:
        out[i] += 1
    return out


def build():
    dates = _days(START, len(REVENUE))
    orders = _apportion(ORDERS_TOTAL, REVENUE)
    daily = [{"date": dt, "revenue": float(r), "spend": float(s),
              "sessions": int(se), "orders": int(o)}
             for dt, r, s, se, o in zip(dates, REVENUE, SPEND, SESSIONS, orders)]

    campaigns = [{"campaign": c, "sub": sub, "channel": ch, "stage": st,
                  "spend": float(sp), "revenue": float(rv), "orders": int(od)}
                 for ch, st, c, sub, sp, rv, od in CAMPAIGNS]

    def roll(key, keep):
        out = {}
        for r in campaigns:
            b = out.setdefault(r[key], {keep: r[key], "spend": 0.0, "revenue": 0.0, "orders": 0})
            b["spend"] += r["spend"]; b["revenue"] += r["revenue"]; b["orders"] += r["orders"]
        return out

    by_ch = roll("channel", "channel")
    channels = []
    for name, colour, note, delta in CHANNELS:
        b = by_ch[name]
        channels.append({"channel": name, "colour": colour, "note": note,
                         "spend": b["spend"], "revenue": b["revenue"], "orders": b["orders"],
                         "delta_vs_prior": delta})

    by_st = roll("stage", "stage")
    stages = [{"stage": s, "spend": by_st[s]["spend"], "colour": STAGE_COLOUR[s]}
              for s in STAGE_ORDER if s in by_st]

    products = [{"product": p, "units": u, "revenue": float(rv), "unit_price": up}
                for p, u, rv, up in PRODUCTS]

    payload = {
        "meta": {
            "client": "lacevo",
            "client_name": "Lacevo",
            "agency": "100% Digital",
            "currency": "AUD",
            "currency_symbol": "A$",
            # THE preview switch. The dashboard shows its notice and every "preview" chip off this
            # one flag, so the day a real lacevo.json lands in the bucket the page stops calling
            # itself a preview without a template edit.
            "placeholder": True,
            "date_min": START,
            "date_max": END,
            "data_through": END,
            "last_updated": None,
            "period_label": "14 Aug - 12 Sep 2026",
            # Nothing is connected yet. Once a feed lands its name moves into `channels_connected`
            # and the topbar stops labelling it a sample.
            "channels_connected": [],
            "channels_expected": ["Meta", "Google Ads", "TikTok", "Shopify"],
            "markets": ["Australia", "United States"],
            "market_default": "Australia",
            "sites": {"Australia": "lacevo.com", "United States": "lacevo.us"},
            # Named on screen so no one has to guess which figures the email programme is missing
            # from - it is the single most common question on a DTC revenue number.
            "excludes_note": "Email and SMS are not included until the Klaviyo feed is connected.",
        },
        "targets": {
            "roas_target": 3.50,
            "cac_ceiling": 110.0,
            # DERIVED, not committed: there is no signed media plan yet. The dashboard labels any
            # target carrying derived:true so a red delta never accuses the campaign of missing a
            # KPI nobody agreed to (the caltex rule).
            "derived": True,
        },
        "flight": {
            "start": FLIGHT_START, "end": FLIGHT_END,
            "days_total": DAYS_TOTAL,
            "days_elapsed": len(REVENUE),
            "budget": BUDGET,
            # spend_to_date / pace_expected / projected_spend are DERIVED in the browser from
            # `daily` + this block, so they can never drift from the chart above them.
        },
        "daily": daily,
        "channels": channels,
        "campaigns": campaigns,
        "stages": stages,
        "products": products,
        "funnel": [{"step": s, "value": v} for s, v in FUNNEL],
        "store": {
            # units / units_per_order / refund_rate / repeat_rate that the products table cannot
            # produce on its own. Everything else on the Store tab derives from `products`.
            "repeat_purchase_rate": 0.062,
            "refund_value": 7420.0,
            "repeat_note": "Mostly replacement flanges and duckbills",
        },
        "customers": {"new": 922, "returning": 262},
    }

    # ---- assertions: the preview must not ship a figure that contradicts another ----------
    rev = sum(d["revenue"] for d in daily)
    spd = sum(d["spend"] for d in daily)
    ses = sum(d["sessions"] for d in daily)
    ordr = sum(d["orders"] for d in daily)
    assert abs(rev - sum(c["revenue"] for c in channels)) < 0.5, "daily revenue != channel revenue"
    assert abs(spd - sum(c["spend"] for c in channels)) < 0.5, "daily spend != channel spend"
    assert ordr == sum(c["orders"] for c in channels) == ORDERS_TOTAL, "orders do not reconcile"
    assert abs(spd - sum(s["spend"] for s in stages)) < 0.5, "stage spend != channel spend"
    assert abs(rev - sum(p["revenue"] for p in products)) < 0.5, "product revenue != store revenue"
    assert ses == FUNNEL[0][1], "funnel sessions != daily sessions"
    assert ordr == FUNNEL[-1][1], "funnel orders != daily orders"
    assert payload["customers"]["new"] + payload["customers"]["returning"] == ordr, \
        "new + returning customers != orders"
    return payload, dict(revenue=rev, spend=spd, sessions=ses, orders=ordr)


if __name__ == "__main__":
    data, totals = build()
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
    print(f"  revenue A${totals['revenue']:,.0f} | spend A${totals['spend']:,.0f} | "
          f"orders {totals['orders']:,} | sessions {totals['sessions']:,}")
    print(f"  ROAS {totals['revenue']/totals['spend']:.2f}x | "
          f"AOV A${totals['revenue']/totals['orders']:.2f} | "
          f"CVR {totals['orders']/totals['sessions']*100:.2f}%")
    print("  all reconciliation assertions passed")
