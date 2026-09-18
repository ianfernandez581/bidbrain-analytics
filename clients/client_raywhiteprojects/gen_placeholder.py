r"""Generate dash/placeholder.json - the ILLUSTRATIVE payload the Ray White Projects preview
dashboard serves until a real raywhiteprojects.json lands in the bucket.

GENERATED. Do not hand-edit dash/placeholder.json: the point of this script is the assertions at
the bottom. Every figure on screen is derived in the browser from `daily` / `site_daily`, so a
hand-edited payload is how a KPI starts disagreeing with the table underneath it.

    .\.venv\Scripts\python.exe clients\client_raywhiteprojects\gen_placeholder.py

WHY THE PAYLOAD LOOKS LIKE THIS
-------------------------------
The shape is the DATA CONTRACT, not a convenience for the sample. It is the interface a real
pipeline fills in (sql/*.sql view column -> job/main.py env key -> dashboard.html data.* key), so
connecting GA4 / Meta / Google Ads / the portals is a DATA change and not a template rewrite:

  meta          the one `placeholder` switch, the project roster, the feed ledger
  projects[]    per-project flight, budget, targets and plan channels. PROJECT IS A DIMENSION
                (the client_geocon pattern) because Ray White Projects will run more than Monair.
  channels[]    the channel dimension: display label, colour, and the PLAN rates the vs-plan
                columns are measured against. One definition, four consumers.
  daily[]       THE FACT: one row per (date, project, channel) carrying the paid metrics only.
  site_daily[]  whole-site sessions and CRM appointments per (date, project). Deliberately NOT
                channel-grain - see "WHAT THE CHANNEL CHIPS MAY MOVE" below.
  line_items[]  the signed plan's line items, per project.
  enquiries     configuration mix, suburb-of-origin table, form-completion funnel.
  selldown      the stock board: one entry per residence.

WHAT THE CHANNEL CHIPS MAY MOVE
-------------------------------
`daily` is channel-grain, so the chips legitimately re-sum impressions, clicks, spend, enquiries
and every rate derived from them. `site_daily` is NOT: a session on monair.com.au has no
delivering channel, and an appointment comes off the CRM with no channel attribution at all. If
those sat in the channel-grain fact, unticking Meta would silently move a whole-site number - the
`client_schneider` rule that a figure moving with a control that does not own it is worse than no
figure. So they are a separate array, and the dashboard marks those tiles as whole-site.

EVERY NUMBER HERE IS ILLUSTRATIVE
---------------------------------
`meta.placeholder` is true and `projects[].targets.derived` is true, which is what puts the preview
notice, the topbar chip, the (derived) target labels and the PREVIEW_ export prefix on screen. The
real figures come from the signed media plan (Ray White Projects Monair Sydney x 100% Digital.xlsx)
- see README.md -> "Flipping preview to live".
"""
import io
import json
import os
from datetime import date, timedelta

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash", "placeholder.json")

# --- the campaign ------------------------------------------------------------------------------
# Monair goes live 25 Sep 2026; the illustrative window is its first 30 days so the metrics can be
# agreed before launch.
FLIGHT_START = date(2026, 9, 25)
DAYS = 30
BUDGET_COMMITTED = 85000.0      # committed to 31 Dec 2026
FLIGHT_END = date(2026, 12, 31)

# Daily shape. These sum EXACTLY to the headline figures the reference build showed, and the
# assertions at the bottom hold them there.
DAILY_ENQ = [3, 4, 4, 5, 8, 10, 7, 5, 6, 8, 9, 11, 10, 8, 5,
             4, 7, 9, 8, 6, 7, 10, 11, 9, 6, 5, 7, 9, 8, 5]
DAILY_SPEND = [540, 570, 580, 610, 660, 690, 650, 570, 580, 600, 620, 650, 670, 630, 570,
               550, 590, 630, 620, 580, 600, 650, 680, 640, 590, 560, 610, 650, 630, 650]
DAILY_CLICKS = [249, 285, 297, 309, 332, 368, 332, 285, 297, 321, 332, 356, 368, 332, 285,
                273, 309, 344, 332, 297, 321, 356, 380, 344, 309, 285, 332, 356, 332, 322]
DAILY_IMPS = [25000, 31000, 32000, 35000, 46000, 55000, 43000, 34000, 38000, 45000,
              49000, 57000, 55000, 46000, 34000, 30000, 42000, 50000, 46000, 38000,
              42000, 54000, 59000, 50000, 38000, 34000, 43000, 51000, 46000, 36000]
DAILY_SESSIONS = [210, 240, 250, 260, 280, 310, 280, 240, 250, 270, 280, 300, 310, 280, 240,
                  230, 260, 290, 280, 250, 270, 300, 320, 290, 260, 240, 280, 300, 280, 270]
DAILY_APPTS = [1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 2, 2, 2, 1, 1,
               1, 1, 2, 1, 1, 1, 2, 2, 2, 1, 1, 1, 2, 1, 0]

# --- channels ----------------------------------------------------------------------------------
# `plan_ctr` / `plan_cpe` are the media-plan rates the vs-plan columns measure against. ONE
# definition: the table, the cost-per-enquiry chart, the donut and the share bar all read this.
# Colours are brand tokens - ink, Ray White yellow, sand, concrete.
CHANNELS = [
    dict(key="meta", label="Meta", sublabel="Downsizer and lookalike audiences",
         colour="#131311", plan_ctr=0.600, plan_cpe=90.0,
         totals=dict(spend=8200, impressions=742000, clicks=4980, enquiries=96)),
    dict(key="google_ads", label="Google Ads", sublabel="Search, brand and competitor",
         colour="#FFE512", plan_ctr=1.200, plan_cpe=85.0,
         totals=dict(spend=5320, impressions=186000, clicks=2640, enquiries=61)),
    dict(key="rea", label="realestate.com.au", sublabel="Project profile and Highlight",
         colour="#C4B49C", plan_ctr=0.500, plan_cpe=80.0,
         totals=dict(spend=3400, impressions=248000, clicks=1420, enquiries=41)),
    dict(key="domain", label="Domain", sublabel="Project listing",
         colour="#8E8B83", plan_ctr=0.550, plan_cpe=100.0,
         totals=dict(spend=1500, impressions=108000, clicks=600, enquiries=16)),
]

LINE_ITEMS = [
    ("Greenwich 8km radius, 55+", "Video and carousel", "meta", "Enquiry", 4600, 2810, 54),
    ("Downsizer lookalike, Lower North Shore", "", "meta", "Enquiry", 2340, 1490, 29),
    ("Site retargeting, form abandoners", "", "meta", "Enquiry", 1260, 680, 13),
    ("Search, over 55s apartments Sydney", "", "google_ads", "Enquiry", 3180, 1540, 36),
    ("Search, brand and project name", "", "google_ads", "Capture", 980, 620, 17),
    ("Performance Max, Greenwich", "", "google_ads", "Enquiry", 1160, 480, 8),
    ("Project profile, Highlight package", "", "rea", "Enquiry", 3400, 1420, 41),
    ("Project listing", "", "domain", "Enquiry", 1500, 600, 16),
]

CONFIGURATION = [("1 bedroom", 24), ("2 bedroom", 96), ("3 bedroom", 94)]

SUBURBS = [
    ("Greenwich", 34, 9, "3 bedroom"),
    ("Lane Cove", 29, 7, "2 bedroom"),
    ("Northwood and Longueville", 26, 6, "3 bedroom"),
    ("Hunters Hill", 22, 4, "3 bedroom"),
    ("Crows Nest and Wollstonecraft", 21, 4, "2 bedroom"),
    ("Other Lower North Shore", 48, 6, "2 bedroom"),
    ("Outside catchment", 34, 2, "1 bedroom"),
]

# Form completion. The last step IS the enquiry count and the assertions hold it there.
FUNNEL = [("Sessions", None), ("Viewed the form", 2440), ("Started the form", 604), ("Submitted", None)]

# Stock board: 48 residences, 24 in the stage-one release.
SELLDOWN = [("exchanged", 2), ("reserved", 3), ("eoi", 6), ("available", 13), ("unreleased", 24)]


def spread_int(total, weights):
    """Split an integer TOTAL across WEIGHTS so the parts sum to exactly TOTAL (largest
    remainder). Used so per-channel daily rows re-sum to the channel totals byte for byte -
    a rounded-per-row split drifts, and the drift shows up as a KPI that disagrees with its
    own table."""
    s = float(sum(weights))
    if s <= 0:
        return [0] * len(weights)
    raw = [total * w / s for w in weights]
    out = [int(x) for x in raw]
    short = total - sum(out)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in range(short):
        out[order[i % len(order)]] += 1
    return out


def spread_money(total, weights):
    """As spread_int but to cents, so money also sums exactly."""
    cents = spread_int(int(round(total * 100)), weights)
    return [c / 100.0 for c in cents]


def _units():
    """One entry per residence, in SELLDOWN order, so the stock board reads level by level.
    Written as a plain loop on purpose: as a nested generator expression this silently picked up
    an unrelated loop variable from the enclosing scope and emitted 48 copies of it, which the
    "one square per residence" assertion below is what caught."""
    out = []
    for status, count in SELLDOWN:
        for _ in range(count):
            out.append({"index": len(out) + 1, "status": status})
    return out


def build():
    dates = [FLIGHT_START + timedelta(days=i) for i in range(DAYS)]
    iso = [d.isoformat() for d in dates]
    project = "monair"

    # --- the fact: one row per (date, project, channel) ---------------------------------------
    # Each channel's WHOLE-FLIGHT total is authoritative (it is what the media plan is read
    # against), so the daily shape is used only as the weighting and each metric is spread to
    # hit that total exactly.
    daily = []
    per_channel_series = {}
    for ch in CHANNELS:
        t = ch["totals"]
        per_channel_series[ch["key"]] = dict(
            spend=spread_money(float(t["spend"]), DAILY_SPEND),
            impressions=spread_int(t["impressions"], DAILY_IMPS),
            clicks=spread_int(t["clicks"], DAILY_CLICKS),
            enquiries=spread_int(t["enquiries"], DAILY_ENQ),
        )
    for i, day in enumerate(iso):
        for ch in CHANNELS:
            s = per_channel_series[ch["key"]]
            daily.append(dict(
                date=day, project=project, channel=ch["key"],
                impressions=s["impressions"][i], clicks=s["clicks"][i],
                spend=round(s["spend"][i], 2), enquiries=s["enquiries"][i],
            ))

    # --- whole-site: no delivering channel ----------------------------------------------------
    site_daily = [dict(date=day, project=project,
                       sessions=DAILY_SESSIONS[i], appointments=DAILY_APPTS[i])
                  for i, day in enumerate(iso)]

    tot_spend = round(sum(r["spend"] for r in daily), 2)
    tot_enq = sum(r["enquiries"] for r in daily)
    tot_sessions = sum(r["sessions"] for r in site_daily)
    tot_appts = sum(r["appointments"] for r in site_daily)

    # --- pacing -------------------------------------------------------------------------------
    # Expected-to-date is drawn to the last day the DATA COVERS, never to today (the repo-wide
    # "pace over the window the actuals cover" rule). On a preview both are the illustrative
    # window's end, but the field is carried so a real feed cannot silently re-introduce the bug.
    #
    # `pace_basis` is the honest label, and it matters: nobody has given us the plan's FLIGHTING,
    # only its total, so expected-to-date here is an EVEN SPREAD across the flight - our
    # assumption, not the client's plan. Media plans are rarely flighted evenly (a launch burst is
    # normally front-loaded), so the dashboard prints the basis beside the figure rather than
    # asserting a pacing position the plan does not support. Same rule as a derived target: if we
    # inferred it, say so on screen. Replace with the plan's real monthly splits when the signed
    # plan is read in, and change this string in the same edit.
    #
    # NOTE, and do NOT "fix" this by nudging a number: the reference figures are mutually
    # inconsistent. 214 enquiries at the A$95 plan rate is ~A$20,330 of spend for 30 days, which
    # over the 98-day flight is ~A$66k, not the A$85,000 committed. So the illustrative run rate
    # is genuinely below the committed total and the card genuinely reads under pace. That is a
    # question for the signed plan, not a rounding error to paper over.
    flight_days = (FLIGHT_END - FLIGHT_START).days + 1
    daily_pace = BUDGET_COMMITTED / flight_days
    days_covered = DAYS
    expected = round(daily_pace * days_covered, 2)

    doc = {
        "meta": {
            "placeholder": True,
            "client": "Ray White Projects",
            "agency": "100% Digital",
            "currency_symbol": "A$",
            "currency": "AUD",
            "period_label": "First 30 days",
            "date_min": iso[0],
            "date_max": iso[-1],
            "data_through": iso[-1],
            "generated": date.today().isoformat(),
            # The project roster. `initProject()` builds the selector from this and renders a
            # plain label while there is only one, so a second project is a DATA change.
            "projects": [{"key": project, "label": "Monair, Greenwich", "status": "live"}],
            "project_default": project,
            # The feed ledger drives the Internal notes tab's "what is connected" list. Nothing
            # is connected yet, which is why the whole payload is illustrative.
            "feeds_connected": [],
            "feeds_expected": ["GA4", "Google Tag Manager", "Meta Ads", "Google Ads",
                               "realestate.com.au", "Domain", "the CRM"],
        },
        "projects": [{
            "key": project,
            "label": "Monair, Greenwich",
            "status": "live",
            "headline": "Monair, Greenwich",
            "address": "170 Pacific Highway",
            "locality": "Greenwich NSW",
            "residences": 48,
            "cohort": "Over 55s",
            "site": "monair.com.au",
            "completion": "Move in mid 2028",
            "live_from": "2026-09-25",
            # Named on the hero. Order is the order they are credited in.
            "credits": [
                {"role": "Developer", "name": "Realside"},
                {"role": "Architect", "name": "WMK Architecture"},
                {"role": "Builder", "name": "FDC"},
                {"role": "Brand and site", "name": "Heard"},
            ],
            "flight": {
                "start": FLIGHT_START.isoformat(),
                "end": FLIGHT_END.isoformat(),
                "budget_committed": BUDGET_COMMITTED,
                # Every committed dollar here reaches an ad server or a portal, so there is no
                # measurable/committed split yet (the client_geocon rule). If a retainer or a
                # management fee joins the plan, it belongs OUT of budget_measurable.
                "budget_measurable": BUDGET_COMMITTED,
                "spend_to_date": tot_spend,
                "expected_to_date": expected,
                "pace_basis": "even spread",     # not the plan's flighting - see the note above
                "days_elapsed": DAYS,
                "days_covered": days_covered,
                "pace_through": iso[-1],
            },
            # DERIVED, not committed: no signed plan has been read into this build yet, so the UI
            # labels every one of these "(derived)" (the client_caltex rule).
            "targets": {
                "derived": True,
                "cost_per_enquiry": 95.0,
                "enquiry_rate_low": 2.0,
                "enquiry_rate_high": 3.0,
            },
            "plan_channels": [c["key"] for c in CHANNELS],
        }],
        "channels": [
            {k: ch[k] for k in ("key", "label", "sublabel", "colour", "plan_ctr", "plan_cpe")}
            for ch in CHANNELS
        ],
        "daily": daily,
        "site_daily": site_daily,
        "line_items": [
            dict(project=project, label=l, sublabel=sub, channel=ch, objective=obj,
                 spend=float(sp), clicks=cl, enquiries=eq)
            for (l, sub, ch, obj, sp, cl, eq) in LINE_ITEMS
        ],
        "enquiries": {
            "by_configuration": [dict(label=l, enquiries=n) for (l, n) in CONFIGURATION],
            "by_suburb": [dict(suburb=s, enquiries=n, appointments=a, most_requested=m)
                          for (s, n, a, m) in SUBURBS],
            "funnel": [dict(label=l, count=(tot_sessions if l == "Sessions"
                                            else tot_enq if l == "Submitted" else n))
                       for (l, n) in FUNNEL],
            # Stated, not inferred: the supply mix across the 48 residences is not confirmed, so
            # the configuration chart is DEMAND ONLY and must not imply an over/under-supply call.
            "supply_mix_known": False,
        },
        "selldown": {
            "total": 48,
            "released": 24,
            "units": _units(),
        },
    }

    # ---------------------------------------------------------------------------------------
    # ASSERTIONS. The reason this file is generated. Each one is a KPI that would otherwise be
    # free to disagree with the table under it.
    # ---------------------------------------------------------------------------------------
    def close(a, b, what):
        assert abs(a - b) < 0.005, "%s: %s != %s" % (what, a, b)

    # 1. the fact re-sums to each channel's authoritative total
    for ch in CHANNELS:
        rows = [r for r in daily if r["channel"] == ch["key"]]
        close(sum(r["spend"] for r in rows), float(ch["totals"]["spend"]),
              "daily spend for %s" % ch["key"])
        assert sum(r["impressions"] for r in rows) == ch["totals"]["impressions"], ch["key"]
        assert sum(r["clicks"] for r in rows) == ch["totals"]["clicks"], ch["key"]
        assert sum(r["enquiries"] for r in rows) == ch["totals"]["enquiries"], ch["key"]

    # 2. the channel totals re-sum to the campaign headline
    close(tot_spend, float(sum(c["totals"]["spend"] for c in CHANNELS)), "total spend")
    assert tot_enq == sum(c["totals"]["enquiries"] for c in CHANNELS)
    assert sum(r["impressions"] for r in daily) == sum(c["totals"]["impressions"] for c in CHANNELS)
    assert sum(r["clicks"] for r in daily) == sum(c["totals"]["clicks"] for c in CHANNELS)

    # 3. the plan's line items re-sum to their channel, per channel AND overall. A line item
    #    that drifts from its channel is how the Media tab starts contradicting the Overview.
    for ch in CHANNELS:
        li = [r for r in doc["line_items"] if r["channel"] == ch["key"]]
        close(sum(r["spend"] for r in li), float(ch["totals"]["spend"]),
              "line items spend for %s" % ch["key"])
        assert sum(r["clicks"] for r in li) == ch["totals"]["clicks"], ch["key"]
        assert sum(r["enquiries"] for r in li) == ch["totals"]["enquiries"], ch["key"]

    # 4. every enquiry breakdown accounts for every enquiry
    assert sum(r["enquiries"] for r in doc["enquiries"]["by_configuration"]) == tot_enq, "configuration mix"
    assert sum(r["enquiries"] for r in doc["enquiries"]["by_suburb"]) == tot_enq, "suburb table"
    assert sum(r["appointments"] for r in doc["enquiries"]["by_suburb"]) == tot_appts, "suburb appointments"

    # 5. the funnel is bounded by the figures it sits between, and it only ever narrows
    f = doc["enquiries"]["funnel"]
    assert f[0]["count"] == tot_sessions, "funnel starts at sessions"
    assert f[-1]["count"] == tot_enq, "funnel ends at enquiries"
    for a, b in zip(f, f[1:]):
        assert b["count"] <= a["count"], "funnel step %r exceeds %r" % (b["label"], a["label"])

    # 6. the stock board is one square per residence, and the release is not over-subscribed
    assert len(doc["selldown"]["units"]) == doc["selldown"]["total"], "stock board size"
    sold = [u for u in doc["selldown"]["units"] if u["status"] != "unreleased"]
    assert len(sold) == doc["selldown"]["released"], "released count"

    # 7. pacing cannot promise more than is committed, and must be drawn to the covered window
    assert tot_spend <= BUDGET_COMMITTED, "spend exceeds the committed budget"
    assert expected <= BUDGET_COMMITTED, "expected-to-date exceeds the committed budget"
    assert doc["projects"][0]["flight"]["pace_through"] == doc["meta"]["data_through"], \
        "pacing window must end where the data does"

    # 8. the project roster and the fact agree. A project in one and not the other is either an
    #    invisible tab or an empty one.
    assert {p["key"] for p in doc["meta"]["projects"]} == {r["project"] for r in daily}, \
        "meta.projects does not match the projects present in daily[]"
    assert {p["key"] for p in doc["projects"]} == {p["key"] for p in doc["meta"]["projects"]}

    # 9. every fact row names a channel that exists in the dimension
    known = {c["key"] for c in CHANNELS}
    assert {r["channel"] for r in daily} <= known, "daily[] names an unknown channel"
    assert {r["channel"] for r in doc["line_items"]} <= known, "line_items[] names an unknown channel"

    return doc


if __name__ == "__main__":
    doc = build()
    # ensure_ascii so the file is byte-identical on every platform and no accented character can
    # arrive double-encoded (a sibling generator in this estate shipped a mojibake en-dash that
    # way). The copy is ASCII by house rule anyway.
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=True)
        fh.write("\n")
    d = doc["daily"]
    print("wrote %s" % OUT)
    print("  %d fact rows (%d days x %d channels), %d site rows"
          % (len(d), len({r['date'] for r in d}), len({r['channel'] for r in d}), len(doc["site_daily"])))
    print("  enquiries %d | spend A$%s | sessions %s | appointments %d"
          % (sum(r["enquiries"] for r in d), format(sum(r["spend"] for r in d), ",.2f"),
             format(sum(r["sessions"] for r in doc["site_daily"]), ","),
             sum(r["appointments"] for r in doc["site_daily"])))
    print("  all assertions passed")
