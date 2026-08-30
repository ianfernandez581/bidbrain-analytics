"""Geocon export job (stage 2) — Gateway Braddon + Northbourne Gateway paid media.

REBUILT 2026-06 around a single fact table. Instead of many server-side rollup views, this job
ships ONE compact per-(date x channel x campaign x adset x ad) fact array (`rows`) plus the
flight/pacing context, the numeric benchmarks, and the raw targets. The dashboard rolls EVERYTHING
up client-side (KPIs, by-campaign / by-stage / by-creative, the daily trend, the vs-benchmark delta
table, the segment breakdown) filtered by the chosen date range — which is what makes the
date-range filter and the CSV "export all data" exact and free.

MULTI-DEVELOPMENT + MULTI-CHANNEL since 2026-08-24. The fact is now `fact_all` (Meta + LinkedIn +
Trade Desk + Google Ads), and flight / benchmarks / targets are emitted PER DEVELOPMENT under
`properties[]` — Gateway Braddon (Meta only, A$7,500) and Northbourne Gateway (five channels,
A$205,600) cannot share one plan. The top-level `flight` / `benchmarks` / `targets` keys are KEPT,
holding the DEFAULT development's values, so a job deploy that lands ahead of a dashboard deploy
leaves the live Gateway Braddon dashboard reading exactly what it read before.

Reads BigQuery views client_geocon.{fact_all, targets, budget, media_plan, breakdowns}. The raw
layer is raw_windsor.{perf_meta, perf_linkedin, perf_the_trade_desk} plus the native Google Ads
DTS export in raw_google_ads — NOT Snowflake; there is no stage-1 loader to run here.
"""
import os, json, datetime
from google.cloud import bigquery, storage

from freshness import probe_bq_last_modified, read_watermark, write_watermark, is_stale

# Freshness gate (see repo CLAUDE.md "Freshness contract"): rebuild only when an upstream raw table
# this job reads has advanced. GATING_TABLES is the "dataset.table" id probed via BQ __TABLES__
# .last_modified; watermark = GCS sidecar.
#
# ALL FOUR CHANNELS ARE GATED, not just Meta. The contract is "gate on whatever the job READS", and
# the three added in 2026-08 are what a Northbourne Trade Desk or Google launch will arrive on. The
# cost of that breadth is real but small: perf_linkedin / perf_the_trade_desk are shared with other
# clients, so THEIR delivery also trips this gate and geocon rebuilds more often than its own data
# strictly changes. The alternative — gating on Meta alone — would leave a new channel's first day
# invisible for up to 24h, which is the failure the contract exists to prevent.
#
# raw_google_ads is the native DTS export and the probe points at the BASE p_ads_ TABLE, never at
# the raw_google_ads.perf_google_ads BRIDGE VIEW, whose last_modified is frozen forever (the
# repo-wide DTS fact in CLAUDE.md).
WINDSOR_TABLES = ["raw_windsor.perf_meta", "raw_windsor.perf_linkedin",
                  "raw_windsor.perf_the_trade_desk"]
GOOGLE_TABLES  = ["raw_google_ads.p_ads_CampaignBasicStats_3451896252"]
GATING_TABLES = WINDSOR_TABLES + GOOGLE_TABLES
WATERMARK_OBJECT = "_freshness.json"

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
CLIENT  = "geocon"
DATASET     = f"client_{CLIENT}"                    # client_geocon
BUCKET      = f"bidbrain-analytics-{CLIENT}-dash"   # bidbrain-analytics-geocon-dash
DATA_OBJECT = f"{CLIENT}.json"                      # geocon.json

# The development the top-level (legacy-shape) flight/benchmarks/targets describe, and the one an
# older dashboard build will render. Keep it on the development that is actually delivering.
DEFAULT_PROPERTY = "Gateway Braddon"

# Channels whose absence is normal rather than an error: a development simply may not buy them.
CHANNELS = ["Meta", "LinkedIn", "Trade Desk", "Google Ads"]


def iso(v):
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return str(v)


def num(v):
    if v is None: return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rows(bq, sql):
    return [dict(r) for r in bq.query(sql, location=LOC).result()]


def _targets_for(tgt_rows, prop):
    """Flat {key: {value, status}} for one development; value parsed to float where possible
    (dates stay strings, and an EMPTY value — a PENDING target with no agreed number — stays the
    empty string, which reads through as null and renders as '-', never as zero)."""
    def tgt_value(raw):
        f = num(raw)
        return f if f is not None else raw
    return {r["key"]: {"value": tgt_value(r["value"]), "status": r["status"]}
            for r in tgt_rows if r.get("property_key") == prop}


def _benchmarks(targets):
    """The numeric benchmarks the UI compares actuals against (the vs-benchmark delta table reads
    these). A key the development has no agreed number for comes back None, and every consumer
    already renders None as 'no target' rather than as a zero to miss."""
    def bnum(k):
        return num((targets.get(k) or {}).get("value"))
    return {
        "cpl":          bnum("cpl_target_aud"),
        "cpl_stretch":  bnum("cpl_stretch_aud"),
        "ctr":          bnum("ctr_target"),
        "cpm":          bnum("cpm_target_aud"),
        "cpc":          bnum("cpc_target_aud"),
        "cost_per_lpv": bnum("cost_per_lpv_target_aud"),
        "lead_target":  bnum("monthly_lead_target"),
        "qualified_lead_target": bnum("qualified_lead_target"),
        "daily_pace":   bnum("daily_pace_aud"),
        "flight_budget": bnum("flight_budget_aud"),
        "measurable_budget": bnum("measurable_budget_aud"),
        "imp_target":   bnum("imp_target"),
        "click_target": bnum("click_target"),
        "video_view_target": bnum("video_view_target"),
        "reach_target": bnum("reach_target"),
    }


def _flight(bud_row, benchmarks, fact, prop, today, plan=None):
    """Flight / pacing for one development — flight-window based, independent of the dashboard's
    date filter.

    PACING IS AGAINST THE BUDGET THAT IS ACTUALLY IN MARKET. Two reductions, each for the same
    reason — a denominator no amount of delivery could ever close is not a pace, it is a permanent
    accusation:

      1. committed -> measurable. Northbourne commits A$205,600 but A$17,100 of that (the SEO
         retainer and the Google Search management fee) reaches no ad server at all.
      2. measurable -> IN MARKET. Only the media-plan lines that have actually started can spend.
         Northbourne is a nine-line plan with one line running (Trade Desk High Impact, A$40,000),
         so pacing its A$3.8k against the full A$188,500 read 11% of pace on a line that is
         performing to plan — the eight lines waiting on creative and approvals were being counted
         as a shortfall against the one that launched.

    `budget` is the PACING denominator (the existing convention, so every consumer keeps its
    meaning); `budget_in_market`, `budget_measurable` and `budget_committed` carry the other three
    figures beside it so the whole commitment stays on screen and the gap is stated, never hidden.
    A development with no seeded media plan (Gateway Braddon) has no line detail to reduce by and
    paces on its measurable budget exactly as before.
    """
    b = bud_row or {}
    fstart = b.get("flight_start")
    fend   = b.get("flight_end")
    committed  = num(b.get("budget_aud")) or benchmarks["flight_budget"]
    measurable = num(b.get("measurable_budget_aud")) or benchmarks["measurable_budget"] or committed

    prows = [r for r in fact if (r.get("property") == prop)]
    # Pacing must compare like-with-like: Gateway Braddon's fact rows start 2026-05-05 (pre-flight
    # activity) but its budget/pace anchors come from the seeded flight window, so the pacing inputs
    # are CLAMPED to flight_start..flight_end. All-time rollups (rows[], breakdowns, meta.date_min/
    # max, the log summary) stay unclamped.
    in_flight = lambda d: d is not None and (fstart is None or d >= fstart) and (fend is None or d <= fend)
    if fstart is None and fend is None:      # no seeded window -> all-time (old behaviour)
        sel = prows
    else:
        sel = [r for r in prows if in_flight(r.get("date"))]
    flight_spend = sum(num(r["spend"]) or 0 for r in sel)
    flight_leads = sum(int(r["leads"] or 0) for r in sel)
    flight_imps  = sum(int(r["impressions"] or 0) for r in sel)

    # ---- which media-plan lines are IN MARKET ----------------------------------------------
    # Delivery-derived, never the plan's own dates: a line is in market when rows carrying its
    # `plan_line` have delivered inside the flight. Measured on the UNFILTERED fact, so the figure
    # is stable — pacing is full-flight and must not move when someone unticks a platform chip.
    plan = plan or []
    lines_live = {r.get("plan_line") for r in sel if r.get("plan_line")}
    live_lines = [l for l in plan if l.get("line") in lines_live and l.get("measurable")]
    budget_in_market = round(sum(num(l.get("budget")) or 0 for l in live_lines), 2) if live_lines else None
    # Reduce only when we actually know better: a seeded plan, at least one line live, and a figure
    # smaller than the measurable budget. Anything else keeps the old denominator.
    use_in_market = bool(plan and budget_in_market and measurable and budget_in_market < measurable)
    pace_budget = budget_in_market if use_in_market else measurable
    first_delivery = min((r.get("date") for r in sel if r.get("date")), default=None)

    days_total = (fend - fstart).days + 1 if (fstart and fend) else None
    days_elapsed = None
    if fstart:
        days_elapsed = (today - fstart).days + 1
        if days_total:
            days_elapsed = max(0, min(days_elapsed, days_total))
        else:
            days_elapsed = max(0, days_elapsed)
    # The seeded `daily_pace_aud` describes the WHOLE plan, so it cannot be used once the
    # denominator is the in-market subset — it would pace A$40,000 at A$2,356/day.
    daily_pace = ((pace_budget / days_total) if (use_in_market and pace_budget and days_total)
                  else (benchmarks["daily_pace"]
                        or (measurable / days_total if (measurable and days_total) else None)))
    pace_expected = (daily_pace * days_elapsed) if (daily_pace and days_elapsed) else None
    # Projection runs on the DELIVERING window, not the elapsed flight, whenever a line started
    # late. Northbourne's flight opened 08-13 and its one line began 08-20: averaging over the
    # seven dead days projected A$20.5k of a A$40k line that is in fact running slightly ABOVE
    # plan rate and lands on budget. A projection that contradicts the campaign's own run-rate is
    # worse than none — it argues for topping up a line that needs nothing.
    run_days = ((today - first_delivery).days + 1) if first_delivery else None
    if run_days and days_total and days_elapsed and run_days < days_elapsed:
        projected_spend = flight_spend + (flight_spend / run_days) * max(0, days_total - days_elapsed)
    else:
        projected_spend = (flight_spend / days_elapsed * days_total) if (days_elapsed and days_total) else None
    return {
        "start": iso(fstart), "end": iso(fend),
        # `budget` stays the PACING budget so every existing consumer keeps its meaning; the
        # in-market, measurable and committed totals are additive information beside it.
        "budget": pace_budget, "budget_committed": committed, "budget_measurable": measurable,
        "budget_in_market": budget_in_market,
        # What the pacing denominator IS, so the dashboard can label it rather than leave the
        # reader to work out which of four budget figures the bar is drawn against.
        "pace_basis": "in_market" if use_in_market else "flight",
        "plan_lines_total": len(plan) or None,
        "plan_lines_live": len(live_lines) if plan else None,
        "first_delivery": iso(first_delivery),
        "budget_unmeasurable": (round(committed - measurable, 2)
                                if (committed is not None and measurable is not None) else None),
        "days_total": days_total, "days_elapsed": days_elapsed,
        "daily_pace": daily_pace, "pace_expected": pace_expected,
        "projected_spend": projected_spend, "spend_to_date": round(flight_spend, 2),
        "leads_to_date": flight_leads, "impressions_to_date": flight_imps,
        # "planned" = the flight window came from a signed plan; "observed" would mean we inferred
        # it from first delivery. Both developments here have signed dates.
        "source": "planned" if fstart else "observed",
    }


def build_env(bq, observed):
    """Read the views and assemble the JSON the dashboard consumes. Pure (no upload), so a dev
    harness can dump it to disk without touching the live bucket. `observed` is the freshness
    probe result (used for meta.data_through)."""
    t = lambda n: f"`{PROJECT}.{DATASET}.{n}`"
    fact = rows(bq, f"SELECT * FROM {t('fact_all')} "
                    f"ORDER BY date, channel, campaign_name, adset_name, ad_name")
    tgt  = rows(bq, f"SELECT * FROM {t('targets')}")
    bud  = rows(bq, f"SELECT * FROM {t('budget')}")
    plan = rows(bq, f"SELECT * FROM {t('media_plan')} ORDER BY property_key, seq")
    # The development (property) map, shipped so the dashboard's selector is fully data-driven:
    # adding a development is then a targets/property_map.csv edit + re-seed, with NO SQL and NO
    # dashboard change. `status` ('live' | 'coming_soon') is the seeded intent.
    props = rows(bq, f"SELECT seq, property_key, display_name, status "
                     f"FROM `{PROJECT}.{DATASET}.seed_property_map` ORDER BY seq")
    # Isolated Meta breakdown facts (audience age/gender + placement) — geocon-only table.
    # Tolerate absence so the export never breaks if the breakdown pull hasn't run.
    try:
        bd = rows(bq, f"SELECT * FROM {t('breakdowns')} ORDER BY date")
    except Exception:
        bd = []

    today = datetime.datetime.now(datetime.timezone.utc).date()
    bud_by_prop = {r.get("property_key"): r for r in bud}

    # ---- per-development plan + pacing context ------------------------------------------------
    # Every development gets its OWN flight, benchmarks and targets. The dashboard picks the set
    # matching the selected development; nothing is shared and nothing is blended.
    plan_lines = {}
    for r in plan:
        plan_lines.setdefault(r["property_key"], []).append({
            "seq": r.get("seq"), "phase": r.get("phase"), "line": r.get("line_name"),
            "media": r.get("media"), "channel": r.get("channel"),
            "description": r.get("description"), "targeting": r.get("targeting"),
            "geo": r.get("geo"),
            "imp_target": num(r.get("imp_target")), "video_view_target": num(r.get("video_view_target")),
            "reach_target": num(r.get("reach_target")), "freq_cap": num(r.get("freq_cap")),
            "cpm_target": num(r.get("cpm_target")), "cpv_target": num(r.get("cpv_target")),
            "ctr_target": num(r.get("ctr_target")), "click_target": num(r.get("click_target")),
            "budget": num(r.get("budget_aud")), "cost_type": r.get("cost_type"),
            "measurable": bool(r.get("measurable")),
        })

    properties = []
    for p in props:
        key = p["property_key"]
        ptargets = _targets_for(tgt, key)
        pbench   = _benchmarks(ptargets)
        properties.append({
            "key": key,
            "label": p.get("display_name") or key,
            "status": p.get("status") or "live",
            "flight": _flight(bud_by_prop.get(key), pbench, fact, key, today,
                              plan_lines.get(key, [])),
            "benchmarks": pbench,
            "targets": ptargets,
            "plan": plan_lines.get(key, []),
            # Channels the PLAN buys, in plan order — the roster the dashboard renders a lane for
            # even before a channel has delivered. Distinct from the channels actually DELIVERING,
            # which the dashboard derives from rows[] so it can never claim delivery we don't have.
            "plan_channels": list(dict.fromkeys(
                l["channel"] for l in plan_lines.get(key, []) if l.get("channel"))),
        })

    # ---- SCOPE AUDIT -------------------------------------------------------------------------
    # 'Unmapped' means a Geocon row on a SHARED platform table matched no development by name (see
    # sql/10_fact_all). It is excluded from every KPI by construction, so it must be LOUD here or a
    # whole channel could go missing in silence. Same for delivery that matched no media-plan line.
    unmapped = [r for r in fact if r.get("property") == "Unmapped"]
    off_plan = [r for r in fact if r.get("property") != "Unmapped" and r.get("channel") != "Meta"
                and not r.get("plan_line")]
    if unmapped:
        names = sorted({f"{r.get('channel')}: {r.get('campaign_name')}" for r in unmapped})
        print(f"  WARNING scope audit: {len(unmapped)} row(s), "
              f"${round(sum(num(r['spend']) or 0 for r in unmapped), 2)} spend matched NO "
              f"development and are excluded from every KPI -> {names[:10]}")
        print("           fix: add the token to targets/property_map.csv, re-seed, FORCE_REBUILD=1")
    if off_plan:
        names = sorted({f"{r.get('channel')}: {r.get('campaign_name')}" for r in off_plan})
        print(f"  WARNING plan audit: {len(off_plan)} row(s), "
              f"${round(sum(num(r['spend']) or 0 for r in off_plan), 2)} spend matched no media-plan "
              f"line (delivery is counted, but it paces against nothing) -> {names[:10]}")

    dates = [r["date"] for r in fact if r.get("date")]
    spend_total = sum(num(r["spend"]) or 0 for r in fact)
    leads_total = sum(int(r["leads"] or 0) for r in fact)

    # Legacy top-level shape: the DEFAULT development's plan. Kept so a job deploy landing ahead of
    # a dashboard deploy leaves the live Gateway Braddon dashboard reading exactly what it read
    # before. The new dashboard reads properties[] and ignores these.
    dflt = next((p for p in properties if p["key"] == DEFAULT_PROPERTY), None) or (properties[0] if properties else None)

    env = {
        "meta": {
            "client": CLIENT,
            "title": "Geocon",
            "currency": (fact[0].get("currency") if fact else None) or "AUD",
            # Stays "Meta-reported": this legacy top-level field describes the DEFAULT development
            # (Gateway Braddon), which is Meta-only, and an older dashboard build prints it
            # verbatim. The current dashboard derives its own label from the channels actually
            # delivering, so it is correct for a multi-channel development without this changing.
            "lead_source_label": "Meta-reported",
            "channel": "Meta · LinkedIn · Trade Desk · Google Ads",
            "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_through": (lambda sf: max(sf).strftime("%Y-%m-%dT%H:%M:%SZ") if sf else None)(
                [observed[k] for k in GATING_TABLES if observed.get(k)]),
            "date_min": iso(min(dates)) if dates else None,
            "date_max": iso(max(dates)) if dates else None,
            "row_count": len(fact),
            "default_property": DEFAULT_PROPERTY,
        },
        # Per-development plan + pacing + targets. THE dashboard's source of truth.
        "properties": properties,
        # --- legacy flat keys (default development) — see the note above -------------------------
        "flight": (dflt or {}).get("flight", {}),
        "benchmarks": (dflt or {}).get("benchmarks", {}),
        "targets": (dflt or {}).get("targets", {}),
        # The single fact table — one row per (date x channel x campaign x adset x ad). The
        # dashboard rolls up everything from this, filtered by the date range. Ratios are
        # recomputed client-side, never stored.
        "rows": [{
            "date": iso(r["date"]),
            # The delivering platform. Gateway Braddon is Meta-only, so its rows all read 'Meta'
            # and every existing rollup is unchanged.
            "channel": r.get("channel") or "Meta",
            "campaign_id": r.get("campaign_id"), "campaign": r.get("campaign_name"),
            "adset_id": r.get("adset_id"), "adset": r.get("adset_name"),
            "ad_id": r.get("ad_id"), "ad": r.get("ad_name"),
            "stage": r.get("funnel_stage") or "Other",
            # The development this campaign sells. Falls back to Gateway Braddon so a row from
            # before the column existed can never land in the wrong property (see sql/01_stg_meta).
            "property": r.get("property") or "Gateway Braddon",
            # The media-plan line that bought this delivery (null = outside the signed plan).
            "plan_line": r.get("plan_line"), "plan_seq": r.get("plan_seq"),
            "creative_id": r.get("creative_id"), "creative_title": r.get("creative_title"),
            "creative_body": r.get("creative_body"), "creative_thumbnail_url": r.get("creative_thumbnail_url"),
            "destination_url": r.get("destination_url"),
            "spend": num(r["spend"]), "impressions": num(r["impressions"]), "reach": num(r["reach"]),
            "clicks": num(r["clicks"]), "link_clicks": num(r["link_clicks"]),
            "lpv": num(r["landing_page_views"]), "leads": num(r["leads"]),
            "video_3s_views": num(r.get("video_3s_views")), "video_completes": num(r.get("video_completes")),
            "thruplays": num(r.get("thruplays")),
            "leads_website": num(r.get("leads_website")), "leads_onfacebook": num(r.get("leads_onfacebook")),
            # Google-reported conversions. Carried and LABELLED, never folded into `leads` — a
            # search conversion and a Meta lead form can be the same human enquiring twice.
            "conversions": num(r.get("conversions")),
            "view_through_conversions": num(r.get("view_through_conversions")),
            "objective": r.get("objective"), "effective_status": r.get("effective_status"),
        } for r in fact],
        # Audience (age x gender) + placement breakdowns — per (date x campaign x seg); the
        # dashboard date-filters + rolls up. seg2 is gender for age_gender, null otherwise.
        # META ONLY: these come from the geocon-only Meta breakdown pull, so a development with no
        # Meta delivery yet simply has none and the dashboard hides the charts.
        "breakdowns": [{
            "date": iso(r["date"]), "breakdown": r.get("breakdown"),
            "seg1": r.get("seg1"), "seg2": r.get("seg2"),
            # Same fallback as rows[] - a pre-column row can never land in the wrong property.
            "property": r.get("property") or "Gateway Braddon",
            "impressions": num(r["impressions"]), "reach": num(r["reach"]),
            "clicks": num(r["clicks"]), "link_clicks": num(r["link_clicks"]),
            "spend": num(r["spend"]), "leads": num(r["leads"]),
        } for r in bd],
    }
    by_prop = {}
    for r in fact:
        k = (r.get("property"), r.get("channel"))
        o = by_prop.setdefault(k, [0, 0.0])
        o[0] += 1
        o[1] += num(r["spend"]) or 0
    per = "; ".join(f"{p}/{c}: {v[0]} rows ${round(v[1], 2)}" for (p, c), v in sorted(by_prop.items(), key=lambda x: str(x[0])))
    summary = (f"{len(fact)} fact rows, {leads_total} platform-reported leads, "
               f"${round(spend_total,2)} spend ({env['meta']['date_min']}..{env['meta']['date_max']}) | {per}")
    return env, summary


def cache_creative_images(bucket, creatives):
    """Best-effort: download each top creative's live Meta thumbnail and store the bytes in the bucket
    under creatives/<creative_id>, so the Creative gallery keeps showing the real ad after Meta's signed
    CDN URL expires (which happens once an ad ends). Returns the set of creative_ids with a cached image
    (this run or a prior one). Never raises — a miss just falls back to the CDN URL / branded tile. An
    already-expired URL 403s here and is skipped, so this preserves creatives whose URL is still live."""
    import urllib.request
    prefix = "creatives/"
    have = set()
    try:
        for b in bucket.list_blobs(prefix=prefix):
            cid = b.name[len(prefix):]
            if cid:
                have.add(cid)
    except Exception as e:
        print(f"  creative cache: list skipped ({e})")
    for c in creatives:
        cid = str(c.get("creative_id") or "")
        url = c.get("thumbnail_url")
        if not cid or not url or cid in have:      # skip if no url or already cached (keep the good copy)
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "image/jpeg")
            if data and ctype.startswith("image/"):
                bucket.blob(prefix + cid).upload_from_string(data, content_type=ctype)
                have.add(cid)
                print(f"  creative {cid}: cached ({len(data)} bytes)")
        except Exception as e:
            print(f"  creative {cid}: cache skip ({e})")
    return have


def main():
    bq = bigquery.Client(project=PROJECT)

    # --- Freshness gate: cheap metadata probe; skip the rebuild unless the upstream advanced. ---
    observed = probe_bq_last_modified(bq, GATING_TABLES)
    wm = read_watermark(BUCKET, WATERMARK_OBJECT)
    times = ", ".join(f"{k}={observed[k].strftime('%Y-%m-%dT%H:%M:%SZ')}"
                      for k in sorted(observed)) or "(no tables found)"
    if os.environ.get("FORCE_REBUILD") == "1":
        print(f"FORCE_REBUILD=1 -> rebuilding regardless of freshness | {times}")
    elif not is_stale(observed, wm):
        print(f"no change, skipping rebuild | {times}")
        return
    else:
        print(f"upstream advanced -> rebuilding | {times}")

    env, summary = build_env(bq, observed)
    # Refuse to publish an empty fact (the caltex/schneidersecpwr pattern): a transient upstream
    # failure must not blank a live dashboard by overwriting good JSON with nothing.
    if not env["rows"]:
        raise SystemExit("REFUSING to publish: fact_all returned zero rows — the previous "
                         "geocon.json is left in place. Check the four upstream tables.")
    bkt = storage.Client(project=PROJECT).bucket(BUCKET)
    # Cache the top creatives' Meta thumbnails into our bucket (served at /creative-img/<id>) while the
    # signed CDN URLs are still live, so the Creative gallery keeps showing the real ad after Meta expires
    # the link. Dedup by creative_id, prioritise by spend, cap the set (covers the dashboard's top-10 for
    # any date range).
    # Meta signs thumbnail_url with only a ~4-day validity, and rows are ordered date-ASC, so keep the
    # LATEST (freshest) URL per creative -- the earliest row's URL is usually already expired. cache_-
    # creative_images only fetches creatives not already cached, so an active creative gets a permanent
    # copy the first export that runs while its freshly-repulled URL is still live.
    cc = {}
    for r in env["rows"]:
        cid = str(r.get("creative_id") or "")
        url = r.get("creative_thumbnail_url")
        if not cid or not url:
            continue
        o = cc.setdefault(cid, {"creative_id": cid, "thumbnail_url": url, "_date": "", "spend": 0.0})
        o["spend"] += num(r.get("spend")) or 0
        d = r.get("date") or ""
        if d >= o["_date"]:                 # freshest signed URL wins (ISO dates compare lexically)
            o["thumbnail_url"], o["_date"] = url, d
    top = sorted(cc.values(), key=lambda x: x["spend"], reverse=True)[:30]
    cached = cache_creative_images(bkt, top)
    bkt.blob(DATA_OBJECT).upload_from_string(json.dumps(env), content_type="application/json")
    # Watermark only after a successful upload (upload first, watermark second).
    write_watermark(BUCKET, WATERMARK_OBJECT, observed)
    print(f"wrote gs://{BUCKET}/{DATA_OBJECT} | {summary} | creatives cached: {len(cached)}")


if __name__ == "__main__":
    main()
