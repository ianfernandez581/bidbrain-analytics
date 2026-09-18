r"""Build dash/placeholder.json - the sample payload the Burnet preview renders from.

GENERATED. Do not hand-edit dash/placeholder.json: the point of this script is the assertions at
the bottom, which hold the invented figures to the reconciliations THE REAL PIPELINE WILL ALSO HAVE
TO HOLD. Hand-editing a number is how a KPI starts disagreeing with the table under it, and a
preview exists to build trust in the numbers - a reviewer who spots arithmetic that does not add up
stops reviewing the layout, which is the only thing they were asked to look at.

The figures are invented but internally consistent:
    revenue / spend      = the stated return
    donations / sessions = the stated donation rate
    every split          = the same total, whichever way it is cut
The shape is the repo's three-stage contract, last leg:
    sql/*.sql view column  ->  job/main.py env dict key  ->  DATA.* key in dashboard.html
matched BY NAME. See README.md -> "Data contract".

ALMOST NOTHING IS PRECOMPUTED. CTR, CPM, CPC, cost per donation, return per $1, average gift,
donation rate, pacing and every share are DERIVED in the browser from the arrays here. A
precomputed headline sitting beside a table the user can filter out from under it is how two panels
on one page start disagreeing.

    .\.venv\Scripts\python.exe clients\client_burnet\gen_placeholder.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dash" / "placeholder.json"

# ---------------------------------------------------------------------------------------------
# The month. 16 of 30 days elapsed, and the feed covers all 16 - so days_elapsed == days_covered
# here. They are carried SEPARATELY anyway, because the moment a real feed lands they diverge (the
# repo rule: draw the expectation to the last day the DATA covers, not to today, or every ad feed's
# ordinary lag reports the campaign as permanently behind).
# ---------------------------------------------------------------------------------------------
YEAR, MONTH = 2026, 9
DAYS_TOTAL, DAYS_COVERED = 30, 16
# Day weights. The lift from the 8th is the mid-month appeal push - budget was weighted there
# deliberately, and the copy on the Overview tab says so.
W_SPEND = [1.00, 0.96, 1.07, 0.95, 0.88, 0.85, 0.94, 1.40, 1.27, 1.38, 1.28, 0.80, 0.86, 1.10, 0.96, 0.98]
W_GIFTS = [1.00, 1.07, 1.00, 0.96, 0.91, 0.74, 1.06, 1.44, 1.41, 1.41, 1.46, 0.87, 0.78, 1.00, 1.00, 0.93]
W_REV = [1.00, 0.90, 0.90, 0.93, 0.86, 0.82, 0.95, 1.61, 1.57, 1.52, 1.68, 0.87, 0.79, 1.01, 1.00, 1.06]
W_CLICK = [1.00, 0.92, 1.05, 0.88, 0.79, 0.84, 0.89, 1.34, 1.21, 1.38, 1.41, 0.81, 0.86, 0.92, 0.99, 0.97]
W_IMPS = [0.99, 0.95, 1.04, 0.93, 0.87, 0.88, 0.93, 1.33, 1.24, 1.34, 1.30, 0.83, 0.88, 1.02, 0.96, 0.97]

# ---------------------------------------------------------------------------------------------
# Channels. `budget` and every `plan_*` benchmark is INVENTED - there is no signed media plan, which
# is why targets.derived is true and the dashboard labels every delta "(derived)". The caltex rule:
# an unlabelled red delta accuses a campaign of missing a KPI nobody agreed to.
# Colours are Burnet's own accent set, not a generic chart palette.
# ---------------------------------------------------------------------------------------------
CHANNELS = [
    # channel,        colour,    spend,   imps,   clicks, gifts, revenue, budget, plan ctr/cpm/cpc/cpd
    ("Meta", "#9BBAE5", 18400, 2120000, 31800, 412, 39758, 34000, 1.20, 9.50, 0.72, 55.00),
    ("Google Ads", "#F99D46", 12600, 480000, 24000, 388, 45784, 24000, 4.00, 28.00, 0.70, 40.00),
    ("The Trade Desk", "#CC9EDE", 21000, 3640000, 10920, 96, 13632, 39000, 0.25, 6.50, 2.60, 180.00),
    ("LinkedIn", "#A1D487", 6000, 260000, 1560, 24, 5040, 11000, 0.55, 26.00, 4.70, 200.00),
]

# Appeal themes are Burnet's own published research areas, so reporting matches how the institute
# already describes its work rather than inventing a taxonomy for it.
APPEALS = [
    ("Women’s and children’s health", "Women & children", 331, 36800),
    ("Malaria and other mosquito-borne diseases", "Malaria", 212, 23900),
    ("Health emergencies and pandemic response", "Health emergencies", 158, 18200),
    ("Hepatitis B and C", "Hepatitis", 122, 14100),
    ("Young people’s health", "Young people", 97, 11214),
]
GIFT_BANDS = [
    ("Under $50", 402, 13266),
    ("$50 to $99", 268, 19028),
    ("$100 to $249", 178, 27056),
    ("$250 to $999", 61, 26230),
    ("$1,000 and over", 11, 18634),
]
SESSIONS = 78400          # site sessions in the period - the donation-rate denominator
ONE_OFF, REGULAR = 782, 138
LARGEST_GIFT, EMAIL_SIGNUPS = 5000, 1640


def spread_int(total, weights):
    """Split an integer total across days by weight, exactly - largest remainder, so the parts sum
    to the whole. Rounding each day independently is what leaves a chart that does not tie to the
    KPI above it."""
    w = sum(weights)
    raw = [total * x / w for x in weights]
    out = [int(r) for r in raw]
    rem = total - sum(out)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[:rem]:
        out[i] += 1
    return out


def spread_money(total, weights):
    """Same, in cents, so the days sum to the stated total to the cent."""
    cents = spread_int(int(round(total * 100)), weights)
    return [round(c / 100, 2) for c in cents]


def build():
    tot_spend = sum(c[2] for c in CHANNELS)
    tot_imps = sum(c[3] for c in CHANNELS)
    tot_clicks = sum(c[4] for c in CHANNELS)
    tot_gifts = sum(c[5] for c in CHANNELS)
    tot_rev = sum(c[6] for c in CHANNELS)
    tot_budget = sum(c[7] for c in CHANNELS)

    d_spend = spread_money(tot_spend, W_SPEND)
    d_rev = spread_money(tot_rev, W_REV)
    d_gifts = spread_int(tot_gifts, W_GIFTS)
    d_clicks = spread_int(tot_clicks, W_CLICK)
    d_imps = spread_int(tot_imps, W_IMPS)

    daily = [{"date": "%04d-%02d-%02d" % (YEAR, MONTH, i + 1),
              "spend": d_spend[i], "impressions": d_imps[i], "clicks": d_clicks[i],
              "donations": d_gifts[i], "revenue": d_rev[i]}
             for i in range(DAYS_COVERED)]

    doc = {
        "meta": {
            # THE single switch behind the preview notice, the topbar chip, every card's placeholder
            # tag and the PREVIEW_ export prefix. The moment a job writes a real burnet.json to the
            # bucket, that payload wins and all of it disappears - no code change, no redeploy.
            "placeholder": True,
            "client": "Burnet Institute",
            "agency": "100% Digital",
            "currency_symbol": "$",
            "period_label": "September 2026 (1–16)",
            "date_min": daily[0]["date"],
            "date_max": daily[-1]["date"],
            "data_through": daily[-1]["date"],
            # The topbar scope control is BUILT FROM THIS. With one active entry it renders as a
            # plain label, not a dropdown: a select with a single real option is a control that
            # cannot do anything. A second lane is a payload change, not a template change.
            "scopes": [
                {"key": "fundraising_au", "label": "Fundraising AU", "status": "active"},
                {"key": "research_profile", "label": "Research profile", "status": "coming_soon"},
            ],
            "scope_default": "fundraising_au",
            "feeds_connected": [],
            "feeds_expected": ["Meta Ads", "Google Ads", "The Trade Desk", "LinkedIn", "GA4",
                               "the donation platform"],
            "sessions": SESSIONS,
        },
        # DERIVED, and the dashboard says so on every delta. Drop the flag in the same edit that
        # replaces the plan_* benchmarks with the signed media plan.
        "targets": {
            "derived": True,
            "note": "Plan benchmarks and channel budgets are our own working assumptions. No media "
                    "plan has been signed, so every comparison against them is marked (derived).",
        },
        "flight": {
            "start": "%04d-%02d-01" % (YEAR, MONTH),
            "end": "%04d-%02d-%02d" % (YEAR, MONTH, DAYS_TOTAL),
            "days_total": DAYS_TOTAL,
            "days_elapsed": DAYS_COVERED,
            # Pace is drawn to the last day the DATA covers, never to today - see README.
            "days_covered": DAYS_COVERED,
            "pace_through": daily[-1]["date"],
            "budget": tot_budget,
        },
        "daily": daily,
        "channels": [{"channel": c[0], "colour": c[1], "spend": c[2], "impressions": c[3],
                      "clicks": c[4], "donations": c[5], "revenue": c[6], "budget": c[7],
                      "plan_ctr": c[8], "plan_cpm": c[9], "plan_cpc": c[10],
                      "plan_cost_per_donation": c[11]} for c in CHANNELS],
        "appeals": [{"appeal": a[0], "short": a[1], "donations": a[2], "revenue": a[3]}
                    for a in APPEALS],
        "gift_bands": [{"band": g[0], "gifts": g[1], "revenue": g[2]} for g in GIFT_BANDS],
        "fundraising": {"one_off": ONE_OFF, "regular_giving": REGULAR,
                        "largest_gift": LARGEST_GIFT, "email_signups": EMAIL_SIGNUPS,
                        "revenue_basis": "First gift value only"},
    }

    # --- the reconciliations the real job will also have to hold -----------------------------
    def close(a, b, what):
        assert abs(a - b) < 0.005, "%s: %s != %s" % (what, a, b)

    close(sum(d["donations"] for d in daily), tot_gifts, "daily vs channel donations")
    close(sum(a[2] for a in APPEALS), tot_gifts, "appeal vs channel donations")
    close(sum(g[1] for g in GIFT_BANDS), tot_gifts, "gift-band vs channel donations")
    close(ONE_OFF + REGULAR, tot_gifts, "one-off + regular vs total donations")
    close(sum(d["revenue"] for d in daily), tot_rev, "daily vs channel revenue")
    close(sum(a[3] for a in APPEALS), tot_rev, "appeal vs channel revenue")
    close(sum(g[2] for g in GIFT_BANDS), tot_rev, "gift-band vs channel revenue")
    close(sum(d["spend"] for d in daily), tot_spend, "daily vs channel spend")
    close(sum(d["clicks"] for d in daily), tot_clicks, "daily vs channel clicks")
    close(sum(d["impressions"] for d in daily), tot_imps, "daily vs channel impressions")
    close(sum(c["budget"] for c in doc["channels"]), doc["flight"]["budget"], "channel vs flight budget")
    assert len(daily) == DAYS_COVERED
    assert all(c["budget"] >= c["spend"] for c in doc["channels"]), "a channel is over its full-month budget"

    print("reconciled: %d donations | $%s revenue | $%s spend | %s return | $%s average gift"
          % (tot_gifts, format(tot_rev, ","), format(tot_spend, ","),
             round(tot_rev / tot_spend, 2), round(tot_rev / tot_gifts, 2)))
    print("            donation rate %.2f%% of %s sessions | cost per donation $%.2f"
          % (tot_gifts / SESSIONS * 100, format(SESSIONS, ","), tot_spend / tot_gifts))
    return doc


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s (%.1f KB)" % (OUT, OUT.stat().st_size / 1024))
