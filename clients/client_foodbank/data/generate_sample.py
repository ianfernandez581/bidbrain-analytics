r"""Foodbank Australia - deterministic SAMPLE campaign data for the pitch dashboard.

One seeded generator, one output file (data/foodbank_sample.json). Every number the dashboard shows
is derived from this file; nothing is hardcoded in the HTML/JS. Re-running yields a byte-identical
file (fixed seed, integer allocation), so diffs stay clean.

    .\.venv\Scripts\python.exe clients\client_foodbank\data\generate_sample.py

The campaign it describes
-------------------------
National awareness burst, 8 weeks, Mon 6 Jul - Sun 30 Aug 2026 (complete flight), A$185,000 net
media across Meta / YouTube / Programmatic. Two narrative moments the charts should show:
  * Week 3 (20-26 Jul)  Hunger Report media moment - impressions + site visits spike.
  * Week 7 (17-23 Aug)  Partner appeal burst - donations + sign-ups spike, media flat.

The anchor totals are PLAUSIBILITY ANCHORS FOR A PITCH, not verified benchmarks. They are set to
look right to an experienced media buyer and are labelled illustrative wherever they are shown.

Data contract (what job/main.py must emit when this goes live)
--------------------------------------------------------------
  meta            campaign name, flight window, data_through, currency, data_mode, budget
  channels[]      the channel roster (key, name) - the UI builds its chips from this list
  plan            weekly planned spend by channel (the media plan)
  facts[]         date x channel x placement x creative delivery rows (the additive fact table)
  reach_daily[]   date x channel unique reach that day (NOT additive across days - see reach_model)
  reach_model     window-dedup exponents + cross-channel dedup, so any date window gets a reach
  reach_curve[]   flight-to-date cumulative reach + frequency per day (drawn on the Audience tab)
  site_daily[]    date x channel website outcomes (sessions, engaged, time, downloads, signups, donations)
  splits          per-channel audience shares (state / device / gender / age / frequency bucket)
  creatives[]     creative dimension (id, channel, name, format, placements)
  placements[]    placement dimension (channel, name, kind)
  totals          channel + grand totals - a CHECKSUM the dashboard can reconcile facts against

Invariants asserted below: daily rows sum exactly to channel totals, channel totals to grand
totals; clicks = impressions x CTR, CPM = spend / impressions x 1000, CPC = spend / clicks,
CPV = spend / views, frequency = impressions / reach, reach <= impressions; dedup reach < the sum of
channel reach; splits sum to 100%; no negatives, no rate > 100%, no zero-delivery days mid-flight,
no dates outside the flight.
"""
import json
import math
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "foodbank_sample.json")

SEED = 20260706
rng = random.Random(SEED)

# ------------------------------------------------------------------------------------------------
# Campaign frame
# ------------------------------------------------------------------------------------------------
CAMPAIGN_NAME = "National awareness burst"
FLIGHT_START = date(2026, 7, 6)
FLIGHT_END = date(2026, 8, 30)
DAYS = [(FLIGHT_START + timedelta(days=i)) for i in range((FLIGHT_END - FLIGHT_START).days + 1)]
assert len(DAYS) == 56 and FLIGHT_START.weekday() == 0 and FLIGHT_END.weekday() == 6
CURRENCY = "AUD"
TOTAL_BUDGET = 185_000

MOMENTS = [
    {"key": "hunger_report", "label": "Hunger Report launch", "start": "2026-07-20", "end": "2026-07-26",
     "week": 3, "kind": "media",
     "note": "Media moment - impressions and site visits step up as the Hunger Report lands."},
    {"key": "partner_appeal", "label": "Partner appeal burst", "start": "2026-08-17", "end": "2026-08-23",
     "week": 7, "kind": "outcome",
     "note": "Partner appeal - donations and sign-ups spike while media delivery stays flat."},
]
WEEK3 = set(range(14, 21))   # day index 14..20 = 20-26 Jul
WEEK7 = set(range(42, 49))   # day index 42..48 = 17-23 Aug

# ------------------------------------------------------------------------------------------------
# Channel anchors (spend, CPM -> impressions, CTR -> clicks, reach, video, viewability)
# ------------------------------------------------------------------------------------------------
CHANNELS = [
    {"key": "meta", "name": "Meta", "spend": 62_000, "cpm": 9.20, "ctr": 0.0085, "reach": 2_550_000,
     "video_share_note": "ThruPlays (15s or complete)", "views_rate_of_imps": 0.20,
     "quartiles": (0.62, 0.52, 0.46, 0.40), "viewability": None,
     "weekend_factor": 1.08, "daily_freq": 1.25},
    {"key": "youtube", "name": "YouTube", "spend": 58_000, "cpm": 14.50, "ctr": 0.0021, "reach": 1_850_000,
     "video_share_note": "Views (30s or complete)", "views_rate_of_imps": 0.32,
     "quartiles": (0.58, 0.44, 0.36, 0.30), "viewability": None,
     "weekend_factor": 1.15, "daily_freq": 1.15},
    {"key": "programmatic", "name": "Programmatic", "spend": 65_000, "cpm": 4.60, "ctr": 0.0010, "reach": 3_400_000,
     "video_share_note": "Completed OLV / CTV views", "views_rate_of_imps": None,  # = q100 on video rows
     "quartiles": (0.86, 0.80, 0.77, 0.74), "viewability": 0.68,
     "weekend_factor": 0.95, "daily_freq": 1.60},
]
CH = {c["key"]: c for c in CHANNELS}
DEDUP_REACH = 5_100_000

# Placements (kind drives which rows carry video metrics)
PLACEMENTS = [
    {"channel": "meta", "name": "Feed", "kind": "mixed", "imp_share": 0.55, "cpm_mult": 1.05, "ctr_mult": 1.10},
    {"channel": "meta", "name": "Reels", "kind": "video", "imp_share": 0.30, "cpm_mult": 0.92, "ctr_mult": 0.85},
    {"channel": "meta", "name": "Stories", "kind": "mixed", "imp_share": 0.15, "cpm_mult": 0.98, "ctr_mult": 0.95},
    {"channel": "youtube", "name": "In-stream (skippable)", "kind": "video", "imp_share": 0.65, "cpm_mult": 1.00, "ctr_mult": 1.00},
    {"channel": "youtube", "name": "Bumper (6s)", "kind": "video", "imp_share": 0.15, "cpm_mult": 1.12, "ctr_mult": 0.55},
    {"channel": "youtube", "name": "Shorts", "kind": "video", "imp_share": 0.20, "cpm_mult": 0.90, "ctr_mult": 1.30},
    {"channel": "programmatic", "name": "Display", "kind": "display", "imp_share": 0.62, "cpm_mult": 0.62, "ctr_mult": 0.95},
    {"channel": "programmatic", "name": "Online video (OLV)", "kind": "video", "imp_share": 0.28, "cpm_mult": 1.55, "ctr_mult": 1.15},
    {"channel": "programmatic", "name": "Connected TV", "kind": "video", "imp_share": 0.10, "cpm_mult": 2.40, "ctr_mult": 0.35},
]

# Creatives (id, channel, name, format, is_video, placements it runs on, relative weight, ctr/vtr lift)
CREATIVES = [
    {"id": "m1", "channel": "meta", "name": "FBA_HungerReport25_Video15s_EmptyFridge_9x16", "format": "Video 15s",
     "video": True, "placements": ["Reels", "Stories"], "weight": 1.35, "ctr_lift": 1.18, "vtr_lift": 1.12},
    {"id": "m2", "channel": "meta", "name": "FBA_OneDollarTwoMeals_Static_4x5", "format": "Static",
     "video": False, "placements": ["Feed"], "weight": 1.10, "ctr_lift": 1.22, "vtr_lift": 1.0},
    {"id": "m3", "channel": "meta", "name": "FBA_EverydayAustralians_Carousel_1x1", "format": "Carousel",
     "video": False, "placements": ["Feed"], "weight": 0.85, "ctr_lift": 0.92, "vtr_lift": 1.0},
    {"id": "m4", "channel": "meta", "name": "FBA_SchoolBreakfast_Video15s_4x5", "format": "Video 15s",
     "video": True, "placements": ["Feed"], "weight": 1.00, "ctr_lift": 0.96, "vtr_lift": 0.94},
    {"id": "m5", "channel": "meta", "name": "FBA_FindFoodSupport_Static_9x16", "format": "Static",
     "video": False, "placements": ["Stories"], "weight": 0.55, "ctr_lift": 0.78, "vtr_lift": 1.0},
    {"id": "y1", "channel": "youtube", "name": "FBA_SchoolBreakfast_Video30s_16x9", "format": "Video 30s",
     "video": True, "placements": ["In-stream (skippable)"], "weight": 1.30, "ctr_lift": 1.05, "vtr_lift": 1.10},
    {"id": "y2", "channel": "youtube", "name": "FBA_HungerReport25_Video15s_EmptyFridge_16x9", "format": "Video 15s",
     "video": True, "placements": ["In-stream (skippable)"], "weight": 1.05, "ctr_lift": 1.12, "vtr_lift": 0.96},
    {"id": "y3", "channel": "youtube", "name": "FBA_OneDollarTwoMeals_Bumper6s_16x9", "format": "Bumper 6s",
     "video": True, "placements": ["Bumper (6s)"], "weight": 1.00, "ctr_lift": 0.90, "vtr_lift": 1.0},
    {"id": "y4", "channel": "youtube", "name": "FBA_EmptyFridge_Shorts_9x16", "format": "Shorts 15s",
     "video": True, "placements": ["Shorts"], "weight": 1.00, "ctr_lift": 1.08, "vtr_lift": 0.92},
    {"id": "p1", "channel": "programmatic", "name": "FBA_FindFoodSupport_Display_300x250", "format": "Display 300x250",
     "video": False, "placements": ["Display"], "weight": 1.20, "ctr_lift": 1.10, "vtr_lift": 1.0},
    {"id": "p2", "channel": "programmatic", "name": "FBA_OneDollarTwoMeals_Display_728x90", "format": "Display 728x90",
     "video": False, "placements": ["Display"], "weight": 0.90, "ctr_lift": 0.82, "vtr_lift": 1.0},
    {"id": "p3", "channel": "programmatic", "name": "FBA_HungerReport25_OLV15s_16x9", "format": "OLV 15s",
     "video": True, "placements": ["Online video (OLV)"], "weight": 1.00, "ctr_lift": 1.05, "vtr_lift": 0.97},
    {"id": "p4", "channel": "programmatic", "name": "FBA_SchoolBreakfast_CTV30s_16x9", "format": "CTV 30s",
     "video": True, "placements": ["Connected TV"], "weight": 1.00, "ctr_lift": 0.60, "vtr_lift": 1.22},
]
CREATIVE_BY_ID = {c["id"]: c for c in CREATIVES}

# Media plan: weekly plan weights (week 3 is bought heavier on purpose - the Hunger Report moment)
PLAN_WEEK_WEIGHTS = [0.110, 0.120, 0.160, 0.125, 0.125, 0.125, 0.125, 0.110]
assert abs(sum(PLAN_WEEK_WEIGHTS) - 1.0) < 1e-9

# Website outcomes (channel splits sum to the anchors)
SITE = {
    "sessions": {"meta": 26_500, "youtube": 9_200, "programmatic": 18_500},          # 54,200
    "engaged_share": 0.58,
    "avg_engagement_sec": 48.0,
    "downloads": {"meta": 1_520, "youtube": 640, "programmatic": 1_020},              # 3,180
    "signups": {"meta": 720, "youtube": 290, "programmatic": 460},                    # 1,470
    "donations": {"meta": 312, "youtube": 128, "programmatic": 184},                  # 624
    "avg_gift": 46.80,
}

# Audience splits - overall anchors; per-channel deltas weighted-average back to these exactly.
SPLIT_ANCHORS = {
    "state": [("NSW-ACT", 0.32), ("VIC", 0.26), ("QLD", 0.19), ("WA", 0.10), ("SA-NT", 0.08), ("TAS", 0.05)],
    "device": [("Mobile", 0.71), ("Desktop", 0.21), ("Tablet", 0.04), ("Connected TV", 0.04)],
    "gender": [("Female", 0.58), ("Male", 0.41), ("Unknown", 0.01)],
    "age": [("18-24", 0.12), ("25-34", 0.22), ("35-44", 0.21), ("45-54", 0.18), ("55-64", 0.15), ("65+", 0.12)],
    "frequency": [("1x", 0.34), ("2-3x", 0.29), ("4-6x", 0.21), ("7-10x", 0.11), ("11+", 0.05)],
}
# Per-channel deltas (meta, youtube); programmatic is solved so the impression-weighted mean holds.
SPLIT_DELTAS = {
    "state": {"meta": [0.01, 0.00, 0.01, -0.01, -0.01, 0.00], "youtube": [-0.01, 0.01, 0.00, 0.00, 0.00, 0.00]},
    "device": {"meta": [0.14, -0.12, -0.01, -0.01], "youtube": [-0.06, 0.04, 0.02, 0.00]},
    "gender": {"meta": [0.04, -0.04, 0.00], "youtube": [-0.05, 0.05, 0.00]},
    "age": {"meta": [0.02, 0.04, 0.01, -0.02, -0.03, -0.02], "youtube": [0.03, 0.01, -0.01, -0.01, -0.01, -0.01]},
    "frequency": {"meta": [0.06, 0.02, -0.03, -0.03, -0.02], "youtube": [0.10, 0.02, -0.06, -0.04, -0.02]},
}


# ------------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------------
def fit_to_total(values, total, caps=None):
    """Scale a list of non-negative floats so they sum EXACTLY to an integer total, using
    largest-remainder rounding. `caps` are optional per-item ceilings: an item that would exceed
    its cap is pinned to it and the excess is water-filled across the unpinned items, so the total
    still holds exactly AND every bound holds (a quartile can never exceed the impressions it is a
    quartile of). Fails loudly if the caps cannot hold the total at all."""
    total = int(round(total))
    n = len(values)
    if sum(values) <= 0:
        raise ValueError("cannot fit an all-zero weight vector")
    if caps is not None:
        assert sum(caps) >= total, f"caps ({sum(caps)}) cannot hold the total ({total})"
    pinned = {}
    free = list(range(n))
    for _ in range(n + 1):
        rem_total = total - sum(pinned.values())
        s = sum(values[i] for i in free)
        if s <= 0:
            # everything left has zero weight: spread the remainder evenly across free items
            scaled = {i: rem_total / len(free) for i in free} if free else {}
        else:
            scaled = {i: values[i] * rem_total / s for i in free}
        if caps is None:
            break
        over = [i for i in free if scaled[i] > caps[i]]
        if not over:
            break
        for i in over:
            pinned[i] = caps[i]
        free = [i for i in free if i not in pinned]
    rem_total = total - sum(pinned.values())
    floors = {i: int(math.floor(scaled[i])) for i in free}
    rem = rem_total - sum(floors.values())
    order = sorted(free, key=lambda i: (scaled[i] - floors[i]), reverse=True)
    # give the remainder to the largest fractional parts that still have headroom
    k = 0
    while rem > 0 and k < 4 * max(1, len(order)):
        i = order[k % len(order)]
        if caps is None or floors[i] + 1 <= caps[i]:
            floors[i] += 1
            rem -= 1
        k += 1
    assert rem == 0, "could not place the remainder under the caps"
    out = [pinned.get(i, floors.get(i, 0)) for i in range(n)]
    assert sum(out) == total
    assert min(out) >= 0
    if caps is not None:
        assert all(v <= c for v, c in zip(out, caps))
    return out


def noise(sd):
    return max(0.55, rng.gauss(1.0, sd))


def day_shape(ch, i, d):
    """Delivery weight for channel `ch` on flight day index i (0-based). Launch ramp, weekday
    rhythm, week-3 media pulse, otherwise flat - the plan buys week 3 heavier."""
    w = 1.0
    if i == 0:
        w *= 0.70
    elif i == 1:
        w *= 0.86
    if d.weekday() >= 5:
        w *= ch["weekend_factor"]
    if i in WEEK3:
        w *= {"meta": 1.38, "youtube": 1.18, "programmatic": 1.36}[ch["key"]]
    # very last day tails off a little as line items close out
    if i == len(DAYS) - 1:
        w *= 0.88
    return w


def week_of(i):
    return i // 7 + 1


# ------------------------------------------------------------------------------------------------
# 1. Delivery facts: date x channel x placement x creative
# ------------------------------------------------------------------------------------------------
facts = []
for ch in CHANNELS:
    key = ch["key"]
    imps_total = int(round(ch["spend"] / ch["cpm"] * 1000))
    clicks_total = int(round(imps_total * ch["ctr"]))
    spend_cents_total = ch["spend"] * 100

    pls = [p for p in PLACEMENTS if p["channel"] == key]
    crs = [c for c in CREATIVES if c["channel"] == key]
    # creative x placement combos that actually run
    combos = [(c, p) for c in crs for p in pls if p["name"] in c["placements"]]

    # Per-combo base weight: placement share split across the creatives on it by creative weight.
    combo_w = {}
    for p in pls:
        on_p = [c for c in crs if p["name"] in c["placements"]]
        tw = sum(c["weight"] for c in on_p)
        for c in on_p:
            combo_w[(c["id"], p["name"])] = p["imp_share"] * c["weight"] / tw

    rows = []
    for i, d in enumerate(DAYS):
        ds = day_shape(ch, i, d)
        for c, p in combos:
            base = combo_w[(c["id"], p["name"])] * ds * noise(0.09)
            rows.append({"i": i, "date": d.isoformat(), "week": week_of(i), "channel": key,
                         "placement": p["name"], "creative_id": c["id"], "_w": base,
                         "_p": p, "_c": c})

    # impressions
    imps = fit_to_total([r["_w"] for r in rows], imps_total)
    for r, v in zip(rows, imps):
        r["impressions"] = v
    # spend (cents) - CPM varies by placement, wobbles by day
    spend_w = [r["impressions"] * r["_p"]["cpm_mult"] * noise(0.05) for r in rows]
    spend_c = fit_to_total(spend_w, spend_cents_total)
    for r, v in zip(rows, spend_c):
        r["spend"] = v / 100.0
    # clicks - CTR varies by placement + creative, wobbles by day
    click_w = [r["impressions"] * r["_p"]["ctr_mult"] * r["_c"]["ctr_lift"] * noise(0.10) for r in rows]
    clicks = fit_to_total(click_w, clicks_total, caps=[r["impressions"] for r in rows])
    for r, v in zip(rows, clicks):
        r["clicks"] = v

    # video: only rows whose creative is a video carry video metrics; others are NULL (not measured)
    vrows = [r for r in rows if r["_c"]["video"]]
    for r in rows:
        r["video_impressions"] = r["impressions"] if r["_c"]["video"] else None
    vimps_total = sum(r["impressions"] for r in vrows)
    q_rates = ch["quartiles"]
    q_totals = [int(round(vimps_total * q)) for q in q_rates]
    prev = [r["video_impressions"] for r in vrows]
    prev_key = "video_impressions"
    for qi, (qname, qt) in enumerate(zip(("q25", "q50", "q75", "q100"), q_totals)):
        w = [r[prev_key] * r["_c"]["vtr_lift"] * (1.18 if r["_p"]["name"] == "Connected TV" else 1.0)
             * (1.10 if r["_p"]["name"] == "Bumper (6s)" else 1.0) * noise(0.04) for r in vrows]
        vals = fit_to_total(w, qt, caps=[r[prev_key] for r in vrows])
        for r, v in zip(vrows, vals):
            r[qname] = v
        prev_key = qname
    if ch["views_rate_of_imps"] is None:
        for r in vrows:
            r["video_views"] = r["q100"]
    else:
        views_total = int(round(imps_total * ch["views_rate_of_imps"]))
        w = [r["video_impressions"] * r["_c"]["vtr_lift"] * noise(0.05) for r in vrows]
        vals = fit_to_total(w, views_total, caps=[r["video_impressions"] for r in vrows])
        for r, v in zip(vrows, vals):
            r["video_views"] = v
    for r in rows:
        if not r["_c"]["video"]:
            r["q25"] = r["q50"] = r["q75"] = r["q100"] = r["video_views"] = None

    # viewability - programmatic only (the other two do not report MRC viewability here)
    if ch["viewability"] is not None:
        vt = int(round(imps_total * ch["viewability"]))
        w = [r["impressions"] * (1.12 if r["_p"]["kind"] == "video" else 0.95) * noise(0.03) for r in rows]
        vals = fit_to_total(w, vt, caps=[r["impressions"] for r in rows])
        for r, v in zip(rows, vals):
            r["viewable_impressions"] = v
    else:
        for r in rows:
            r["viewable_impressions"] = None

    facts.extend(rows)

for r in facts:
    r.pop("_w"); r.pop("_p"); r.pop("_c"); r.pop("i")

# ------------------------------------------------------------------------------------------------
# 2. Reach: daily unique reach per channel + a window-dedup model + the flight-to-date curve
# ------------------------------------------------------------------------------------------------
daily_imps = {}
for r in facts:
    daily_imps[(r["date"], r["channel"])] = daily_imps.get((r["date"], r["channel"]), 0) + r["impressions"]

reach_daily = []
reach_model = {"window_exponent": {}, "cross_channel_dedup": round(DEDUP_REACH / sum(c["reach"] for c in CHANNELS), 6),
               "note": "reach(window) = sum(daily reach) x n_days^(-exponent) per channel; multi-channel reach "
                       "is the sum x an interpolated cross-channel dedup factor (1 channel = 1.0, all = cross_channel_dedup)."}
for ch in CHANNELS:
    key = ch["key"]
    dr = [daily_imps[(d.isoformat(), key)] / ch["daily_freq"] * noise(0.03) for d in DAYS]
    dr = [int(round(x)) for x in dr]
    for d, v in zip(DAYS, dr):
        assert v <= daily_imps[(d.isoformat(), key)]
        reach_daily.append({"date": d.isoformat(), "channel": key, "reach": v})
    s = sum(dr)
    k = -math.log(ch["reach"] / s) / math.log(len(DAYS))
    reach_model["window_exponent"][key] = round(k, 6)


def window_reach(ch_keys, start_i, end_i):
    """Same formula the dashboard uses - kept here so the generator's curve and the UI agree."""
    n = end_i - start_i + 1
    tot = 0.0
    for key in ch_keys:
        s = sum(r["reach"] for r in reach_daily if r["channel"] == key and start_i <= DAYS.index(date.fromisoformat(r["date"])) <= end_i)
        tot += s * (n ** (-reach_model["window_exponent"][key]))
    m = len(ch_keys)
    if m > 1:
        f = 1.0 - (1.0 - reach_model["cross_channel_dedup"]) * (m - 1) / (len(CHANNELS) - 1)
        tot *= f
    return tot


reach_curve = []
cum_imps = 0
by_day_total_imps = {d.isoformat(): sum(daily_imps[(d.isoformat(), c["key"])] for c in CHANNELS) for d in DAYS}
for i, d in enumerate(DAYS):
    cum_imps += by_day_total_imps[d.isoformat()]
    rc = window_reach([c["key"] for c in CHANNELS], 0, i)
    reach_curve.append({"date": d.isoformat(), "cum_impressions": cum_imps,
                        "cum_reach": int(round(rc)), "frequency": round(cum_imps / rc, 3)})

# ------------------------------------------------------------------------------------------------
# 3. Website outcomes: date x channel
# ------------------------------------------------------------------------------------------------
daily_clicks = {}
for r in facts:
    daily_clicks[(r["date"], r["channel"])] = daily_clicks.get((r["date"], r["channel"]), 0) + r["clicks"]

site_daily = []
for ch in CHANNELS:
    key = ch["key"]
    rows = [{"date": d.isoformat(), "week": week_of(i), "channel": key} for i, d in enumerate(DAYS)]
    # sessions: click-driven + a view-through component; week 3 lifts strongly, week 7 modestly
    w = []
    for i, d in enumerate(DAYS):
        base = daily_clicks[(d.isoformat(), key)] * 0.55 + daily_imps[(d.isoformat(), key)] / 1000.0 * 0.9
        if i in WEEK3:
            base *= 1.55
        if i in WEEK7:
            base *= 1.22
        w.append(base * noise(0.08))
    sess = fit_to_total(w, SITE["sessions"][key])
    for r, v in zip(rows, sess):
        r["sessions"] = v
    eng = fit_to_total([r["sessions"] * noise(0.03) for r in rows],
                       int(round(SITE["sessions"][key] * SITE["engaged_share"])), caps=[r["sessions"] for r in rows])
    for r, v in zip(rows, eng):
        r["engaged_sessions"] = v
    tsec = fit_to_total([r["sessions"] * noise(0.06) for r in rows],
                        int(round(SITE["sessions"][key] * SITE["avg_engagement_sec"])))
    for r, v in zip(rows, tsec):
        r["engagement_time_sec"] = v
    # downloads: follow sessions, spike in week 3 (the report itself launches)
    w = [r["sessions"] * (1.9 if i in WEEK3 else 1.0) * noise(0.10) for i, r in enumerate(rows)]
    dl = fit_to_total(w, SITE["downloads"][key], caps=[r["sessions"] for r in rows])
    for r, v in zip(rows, dl):
        r["downloads"] = v
    # sign-ups + donations: follow sessions, spike in week 7 (partner appeal)
    w = [r["sessions"] * (2.3 if i in WEEK7 else 1.0) * noise(0.12) for i, r in enumerate(rows)]
    su = fit_to_total(w, SITE["signups"][key], caps=[r["sessions"] for r in rows])
    for r, v in zip(rows, su):
        r["signups"] = v
    w = [r["sessions"] * (2.7 if i in WEEK7 else 1.0) * noise(0.15) for i, r in enumerate(rows)]
    dn = fit_to_total(w, SITE["donations"][key], caps=[r["sessions"] for r in rows])
    for r, v in zip(rows, dn):
        r["donations"] = v
    gift_cents_total = int(round(SITE["donations"][key] * SITE["avg_gift"] * 100))
    w = [r["donations"] * noise(0.10) if r["donations"] > 0 else 0 for r in rows]
    gv = fit_to_total(w, gift_cents_total)
    for r, v in zip(rows, gv):
        assert (v == 0) == (r["donations"] == 0)
        r["donation_value"] = v / 100.0
    site_daily.extend(rows)

# ------------------------------------------------------------------------------------------------
# 4. Media plan (weekly, by channel) - planned spend; actual comes from facts
# ------------------------------------------------------------------------------------------------
plan_weeks = []
for wi in range(8):
    ws = DAYS[wi * 7]
    we = DAYS[wi * 7 + 6]
    row = {"week": wi + 1, "start": ws.isoformat(), "end": we.isoformat(), "planned": {}}
    plan_weeks.append(row)
for ch in CHANNELS:
    alloc = fit_to_total(PLAN_WEEK_WEIGHTS, ch["spend"] * 100)
    for row, cents in zip(plan_weeks, alloc):
        row["planned"][ch["key"]] = cents / 100.0
for row in plan_weeks:
    row["planned_total"] = round(sum(row["planned"].values()), 2)
plan = {"total_budget": TOTAL_BUDGET, "channel_budget": {c["key"]: c["spend"] for c in CHANNELS},
        "weeks": plan_weeks}

# ------------------------------------------------------------------------------------------------
# 5. Audience splits - per channel, impression-weighted mean == anchors
# ------------------------------------------------------------------------------------------------
ch_imps = {c["key"]: sum(r["impressions"] for r in facts if r["channel"] == c["key"]) for c in CHANNELS}
tot_imps = sum(ch_imps.values())
wsh = {k: v / tot_imps for k, v in ch_imps.items()}
splits = {"dimensions": {}, "by_channel": {c["key"]: {} for c in CHANNELS}, "overall": {}}
for dim, anchors in SPLIT_ANCHORS.items():
    labels = [a for a, _ in anchors]
    base = [v for _, v in anchors]
    assert abs(sum(base) - 1.0) < 1e-9, dim
    splits["dimensions"][dim] = labels
    dm = SPLIT_DELTAS[dim]["meta"]
    dy = SPLIT_DELTAS[dim]["youtube"]
    assert abs(sum(dm)) < 1e-9 and abs(sum(dy)) < 1e-9, dim
    dp = [-(wsh["meta"] * a + wsh["youtube"] * b) / wsh["programmatic"] for a, b in zip(dm, dy)]
    for key, delta in (("meta", dm), ("youtube", dy), ("programmatic", dp)):
        sh = [round(b + d, 6) for b, d in zip(base, delta)]
        # absorb rounding drift on the largest bucket so each channel sums to exactly 1
        drift = round(1.0 - sum(sh), 6)
        sh[sh.index(max(sh))] = round(sh[sh.index(max(sh))] + drift, 6)
        assert min(sh) >= 0, (dim, key, sh)
        assert abs(sum(sh) - 1.0) < 1e-6
        splits["by_channel"][key][dim] = dict(zip(labels, sh))
    splits["overall"][dim] = dict(zip(labels, base))
splits["note"] = ("Shares of impressions (frequency: share of people reached) per channel. The dashboard "
                  "multiplies them by the impressions / reach in the selected window and channels. "
                  "Platform-reported, illustrative.")

# ------------------------------------------------------------------------------------------------
# 6. Totals (checksum) + reconciliation
# ------------------------------------------------------------------------------------------------
def agg(rows, keys):
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = round(sum(vals), 2) if vals else None
    return out


FACT_KEYS = ["spend", "impressions", "clicks", "video_impressions", "video_views", "q25", "q50", "q75", "q100",
             "viewable_impressions"]
SITE_KEYS = ["sessions", "engaged_sessions", "engagement_time_sec", "downloads", "signups", "donations", "donation_value"]
totals = {"by_channel": {}, "grand": {}}
for ch in CHANNELS:
    key = ch["key"]
    t = agg([r for r in facts if r["channel"] == key], FACT_KEYS)
    t.update(agg([r for r in site_daily if r["channel"] == key], SITE_KEYS))
    t["reach"] = ch["reach"]
    totals["by_channel"][key] = t
g = agg(facts, FACT_KEYS)
g.update(agg(site_daily, SITE_KEYS))
g["reach"] = DEDUP_REACH
g["reach_sum_of_channels"] = sum(c["reach"] for c in CHANNELS)
totals["grand"] = g

# ---- assertions -------------------------------------------------------------------------------
report = []


def check(cond, msg):
    report.append(("PASS" if cond else "FAIL", msg))
    assert cond, msg


for ch in CHANNELS:
    key = ch["key"]
    t = totals["by_channel"][key]
    check(abs(t["spend"] - ch["spend"]) < 0.005, f"{key}: daily spend sums to A${ch['spend']:,} exactly ({t['spend']:,.2f})")
    check(t["impressions"] == int(round(ch["spend"] / ch["cpm"] * 1000)),
          f"{key}: impressions = spend/CPM x1000 = {t['impressions']:,}")
    cpm = t["spend"] / t["impressions"] * 1000
    check(abs(cpm - ch["cpm"]) < 0.005, f"{key}: CPM {cpm:.3f} vs anchor {ch['cpm']:.2f}")
    ctr = t["clicks"] / t["impressions"]
    check(abs(ctr - ch["ctr"]) < 0.00002, f"{key}: CTR {ctr*100:.3f}% vs anchor {ch['ctr']*100:.2f}%  (clicks {t['clicks']:,})")
    check(t["reach"] <= t["impressions"], f"{key}: reach {t['reach']:,} <= impressions {t['impressions']:,}")
    freq = t["impressions"] / t["reach"]
    check(freq >= 1.0, f"{key}: frequency {freq:.2f}")
    wr = window_reach([key], 0, len(DAYS) - 1)
    check(abs(wr - ch["reach"]) / ch["reach"] < 1e-4, f"{key}: reach model reproduces anchor reach {ch['reach']:,} ({wr:,.0f} from the window formula)")
    if ch["viewability"] is not None:
        check(abs(t["viewable_impressions"] / t["impressions"] - ch["viewability"]) < 1e-6,
              f"{key}: viewability {t['viewable_impressions']/t['impressions']*100:.1f}%")
    if ch["views_rate_of_imps"] is not None:
        check(t["video_views"] == int(round(t["impressions"] * ch["views_rate_of_imps"])),
              f"{key}: video views {t['video_views']:,} = {ch['views_rate_of_imps']*100:.0f}% of impressions; CPV A${t['spend']/t['video_views']:.4f}")
    else:
        check(t["video_views"] == t["q100"], f"{key}: video views = completed views {t['video_views']:,} (VCR {t['q100']/t['video_impressions']*100:.1f}%)")
    check(t["q25"] >= t["q50"] >= t["q75"] >= t["q100"] >= 0 and t["q25"] <= t["video_impressions"],
          f"{key}: completion funnel monotonic {t['q25']:,} >= {t['q50']:,} >= {t['q75']:,} >= {t['q100']:,}")
    for k in ("sessions", "downloads", "signups", "donations"):
        check(t[k] == SITE[k][key], f"{key}: {k} {t[k]:,} match anchor")
    check(t["downloads"] <= t["sessions"] and t["signups"] <= t["sessions"] and t["donations"] <= t["sessions"],
          f"{key}: outcomes <= sessions")
    check(abs(t["donation_value"] - SITE["donations"][key] * SITE["avg_gift"]) < 0.005,
          f"{key}: donation value A${t['donation_value']:,.2f} = {t['donations']} x A${SITE['avg_gift']:.2f}")
    # every day delivers on every channel, in every placement combo
    days_seen = {r["date"] for r in facts if r["channel"] == key and r["impressions"] > 0}
    check(len(days_seen) == len(DAYS), f"{key}: delivery on all {len(DAYS)} flight days (no zero-delivery days)")

# grand
gt = totals["grand"]
check(abs(gt["spend"] - TOTAL_BUDGET) < 0.005, f"grand: spend A${gt['spend']:,.2f} == budget A${TOTAL_BUDGET:,}")
check(gt["impressions"] == sum(t["impressions"] for t in totals["by_channel"].values()),
      f"grand: impressions {gt['impressions']:,} == sum of channels")
check(gt["clicks"] == sum(t["clicks"] for t in totals["by_channel"].values()), f"grand: clicks {gt['clicks']:,} == sum of channels")
check(gt["sessions"] == 54_200, f"grand: website visits {gt['sessions']:,}; cost per visit A${gt['spend']/gt['sessions']:.2f}")
check(gt["downloads"] == 3_180 and gt["signups"] == 1_470 and gt["donations"] == 624,
      f"grand: downloads {gt['downloads']:,} / sign-ups {gt['signups']:,} (A${gt['spend']/gt['signups']:.0f} each) / donations {gt['donations']}")
check(abs(gt["donation_value"] - 624 * 46.80) < 0.005, f"grand: donation value A${gt['donation_value']:,.2f}")
check(gt["reach"] < gt["reach_sum_of_channels"], f"grand: dedup reach {gt['reach']:,} < sum of channel reach {gt['reach_sum_of_channels']:,}")
bf = gt["impressions"] / gt["reach"]
check(4.5 < bf < 5.2, f"grand: blended frequency {bf:.2f}; blended CPM A${gt['spend']/gt['impressions']*1000:.2f}; blended CTR {gt['clicks']/gt['impressions']*100:.2f}%")
check(abs(reach_curve[-1]["cum_reach"] - DEDUP_REACH) / DEDUP_REACH < 1e-4,
      f"grand: reach curve ends at the dedup total ({reach_curve[-1]['cum_reach']:,})")
mono = all(reach_curve[i]["cum_reach"] <= reach_curve[i + 1]["cum_reach"] for i in range(len(reach_curve) - 1))
check(mono, "grand: cumulative reach curve is monotonic")

# row-level bounds
for r in facts:
    assert FLIGHT_START.isoformat() <= r["date"] <= FLIGHT_END.isoformat()
    assert r["impressions"] > 0 and r["clicks"] >= 0 and r["spend"] >= 0
    assert r["clicks"] <= r["impressions"]
    if r["video_impressions"] is not None:
        assert r["video_views"] <= r["video_impressions"]
        assert r["video_impressions"] >= r["q25"] >= r["q50"] >= r["q75"] >= r["q100"] >= 0
    if r["viewable_impressions"] is not None:
        assert r["viewable_impressions"] <= r["impressions"]
for r in site_daily:
    assert r["engaged_sessions"] <= r["sessions"]
    assert 0 <= r["downloads"] <= r["sessions"] and 0 <= r["signups"] <= r["sessions"] and 0 <= r["donations"] <= r["sessions"]
check(True, f"rows: {len(facts):,} delivery facts, {len(site_daily)} site rows, {len(reach_daily)} reach rows - all inside the flight, all bounded")
for key in splits["by_channel"]:
    for dim, sh in splits["by_channel"][key].items():
        assert abs(sum(sh.values()) - 1.0) < 1e-6 and min(sh.values()) >= 0
# impression-weighted mean of the per-channel splits reproduces the anchors
for dim, labels in splits["dimensions"].items():
    for lab in labels:
        m = sum(splits["by_channel"][k][dim][lab] * wsh[k] for k in wsh)
        assert abs(m - splits["overall"][dim][lab]) < 1e-4, (dim, lab, m)
check(True, "splits: every channel's shares sum to 100%; impression-weighted mean matches the anchors")

# ------------------------------------------------------------------------------------------------
# 7. Write
# ------------------------------------------------------------------------------------------------
payload = {
    "meta": {
        "data_mode": "sample",
        "schema_version": 1,
        "generator": "clients/client_foodbank/data/generate_sample.py",
        "seed": SEED,
        "campaign_name": CAMPAIGN_NAME,
        "campaign_objective": "Awareness",
        "flight_start": FLIGHT_START.isoformat(),
        "flight_end": FLIGHT_END.isoformat(),
        "data_through": FLIGHT_END.isoformat(),
        "flight_days": len(DAYS),
        "currency": CURRENCY,
        "currency_prefix": "A$",
        "budget_planned": TOTAL_BUDGET,
        "moments": MOMENTS,
        "illustrative_note": ("Sample data. Every figure is illustrative and generated to plausible "
                              "magnitudes for a pitch; none is a verified benchmark or a live result."),
    },
    "channels": [{"key": c["key"], "name": c["name"], "video_views_definition": c["video_share_note"],
                  "reports_viewability": c["viewability"] is not None} for c in CHANNELS],
    "placements": [{"channel": p["channel"], "name": p["name"], "kind": p["kind"]} for p in PLACEMENTS],
    "creatives": [{"id": c["id"], "channel": c["channel"], "name": c["name"], "format": c["format"],
                   "video": c["video"], "placements": c["placements"]} for c in CREATIVES],
    "plan": plan,
    "facts": facts,
    "reach_daily": reach_daily,
    "reach_model": reach_model,
    "reach_curve": reach_curve,
    "site_daily": site_daily,
    "splits": splits,
    "totals": totals,
}
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(payload, f, indent=1, sort_keys=False)
    f.write("\n")

print(f"wrote {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")
print("\nRECONCILIATION")
for status, msg in report:
    print(f"  [{status}] {msg}")
print(f"\n{sum(1 for s,_ in report if s=='PASS')}/{len(report)} checks passed")
