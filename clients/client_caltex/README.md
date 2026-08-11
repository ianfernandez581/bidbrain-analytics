# client_caltex — Caltex Star Card (100% Digital) — The Trade Desk display, QLD+WA

> **Status (2026-07-30): LIVE on real data.** Campaign **"Caltex Star Card | QLD+WA | Jul-Oct 2026"**
> (`campaign_id` `85k1vmm`, TTD advertiser **`0lw3hp6`**), AUD, all three ad groups delivering.
> The tile is **active** on the 100% Digital portal (`bidbrain-platform/dash/set_caltex_tile.py`),
> the export self-gates `*/10`, and the dashboard is in `status_dashboard` BQ_CLIENTS (5 accuracy
> checks) and `SLIDES_CLIENTS` (AI deck enabled: Vertex IAM + 900s timeout via
> `dash/enable_report_caltex.ps1`).
>
> **First delivery was 2026-07-28.** The shared TTD loader walks back from *yesterday*, so its
> 07-28 21:35 UTC run stopped at 07-27 and the raw table briefly looked empty — that was NOT a
> Windsor grant problem (the advertiser is granted; verified against the API). It self-heals nightly;
> force a range with `tradedesk_loader.py <from> <to>` (TTD refuses same-day dates).
> `job/main.py` also REFUSES to upload an empty fact, so a premature run can never blank the
> dashboard. Runbook: [`dash/LIVE_URL.md`](dash/LIVE_URL.md).

## What the conversion pixel can and cannot measure (read before promising numbers)

**Site visits became measurable on 2026-08-10**, when the client attached the URL-scoped
**`Landing Page Visit`** tracking tag (`4tyuvnj`, TTD event type **Site visit**, rule contains
`business-solutions/starcard/caltex-starcard`) to the **campaign's conversion reporting**. That was
the one missing step diagnosed below — the tag had always been firing at the *pixel* level, it just
never reached the campaign report, and therefore never reached Windsor.

All the underlying tags sit on the sitewide TTD Universal Pixel `z3eu6oa` (advertiser `0lw3hp6`):

```html
ttdConversionEvents("init",  { advertiserId: "0lw3hp6", pixelIds: ["z3eu6oa"] });
ttdConversionEvents("event", { advertiserId: "0lw3hp6", pixelIds: ["z3eu6oa"] });
```

Consequences, and the exact claim the dashboard is allowed to make:

- What we CAN report: **ad-attributed visits to the Star Card LANDING PAGE** — post-view (saw an
  ad, later landed) and post-click. Because the attached tracker is **URL-scoped**, this is NOT
  "all site traffic": it is specifically the Star Card page. The UI, the AI report and the
  `action_source_label` badge ("Star Card page · TTD-attributed") all say so.
- **Never substitute the sitewide `Universal Pixel - Default` tag (`8za7r9n`)** for this number. At
  ~429k hits/30d it is ~150x the landing-page figure and counts all traffic, ad-exposed or not.
- What we CANNOT report: **Star Card applications / sign-ups.** A tracking tag for them EXISTS
  (`7y9naeh`) but has never fired, because the pixel is not installed on the application domain
  `oa.starcard.com.au` — see **Pixel wiring status** below. The client has agreed to attribute
  post-launch applications to the campaign in their own reporting, but that is a commercial
  agreement, **not** a measurement we hold — never surface an application count, rate or cost
  from this dashboard.
- When the application tag IS installed it will appear as a **new numbered slot** in Windsor's
  anonymous conversion slots; split it out in `sql/01_stg_ttd.sql` (and mirror the split in the
  status-dash check) to report applications as their own metric.
- `conversion_touch_*` stays unused: it counts ALL pixel fires, which this base pixel makes large
  and emphatically not ad-attributed.
- Slots are summed across all 12 per kind. **When they first fire, verify the layout** — TTD can
  export one tracker as a duplicate column pair (the VMCH `{01,03,05}` case); if so, switch both
  `sql/01_stg_ttd.sql` and the status-dash check to one column per pair.

## Pixel wiring status — site visits RESOLVED 2026-08-10, applications still blocked

**Half of this is now fixed.** The 2026-08-05 diagnosis below was correct and its **step (1) has
been actioned**: the client attached `Landing Page Visit` (`4tyuvnj`) to the campaign's conversion
reporting on 2026-08-10, so ad-attributed **Star Card landing-page visits** now flow
TTD → Windsor → `raw_windsor.perf_the_trade_desk.conversions` → `stg_ttd` → the dashboard KPI with
no code change (the pipeline had been built and waiting since 2026-07-30).

**Step (2) is still open:** applications remain unmeasurable until the pixel is installed on
`oa.starcard.com.au`. Keep the rest of this section — it is the standing diagnosis for that half,
and the reference for anyone who sees a zero and assumes a loader bug.

**Do not re-diagnose this as "the pixel is broken" or "Windsor is missing conversions" — neither is
true.** Measured state as of the 2026-08-05 investigation, both sides:

**TTD UI** — pixel `z3eu6oa` is firing hard: **52,337 hits/1d · 213,344/7d · 429,374/30d**. It has
three child tracking tags:

| Tag | ID | Rule | Event type | 30-day hits | Active IDs |
|---|---|---|---|---|---|
| Universal Pixel - Default | `8za7r9n` | `*` (sitewide) | Other | 429,374 | 30.2K |
| Landing Page Visit | `4tyuvnj` | contains `business-solutions/starcard/caltex-starcard` | Site visit | 2,851 | 800 |
| StarCard Apply Click | `7y9naeh` | contains `oa.starcard.com.au/OnlineApplicat…` | Purchase | **0** | **0** |

**Our side** — `raw_windsor.perf_the_trade_desk` carries **0 of 48 Caltex rows with any conversion
slot populated**, across the whole flight. That is NOT a loader gap: `tradedesk_loader.py` requests
all 36 slots (3 kinds x 12), and through the identical loader, fields and Windsor seat, **WEHI
returns `{"view_through_conversion_01": 2.0, "conversion_touch_01": 22.0}`** on the same dates.

**So the diagnosis is:** TTD fills the numbered conversion slots from the tracking tags attached to
a **campaign's conversion reporting**. Caltex's tags exist and fire at the *pixel* level but are not
attached to the *campaign*, so the report — and therefore Windsor, and therefore this dashboard —
sees nothing. Nothing in this repo can fix that; it is a TTD-UI setting, exactly like viewability.

**Two separate problems, do not conflate them:**

1. **Site visits — DONE 2026-08-10.** `4tyuvnj` was healthy all along (right URL scope, right event
   type, 2,851 hits/30d); it only needed **attaching to the campaign's conversion tracking**. That
   single change lit up the "Site visits (ad-attributed)" KPI with no code change here, exactly as
   predicted. Because the tracker is URL-scoped, the KPI means **Star Card landing-page visits**,
   not all site traffic — label it that way.
2. **Applications are not, and the reason is the DOMAIN.** `7y9naeh` shows 0 hits *and* 0 active IDs
   in every window. Its rule targets `oa.starcard.com.au`, a different host from the landing page —
   and a Universal Pixel only fires where its snippet is installed. Zero-hits-with-zero-active-IDs is
   the signature of the pixel being **absent from that domain** (a merely wrong URL rule would still
   show active IDs from near-misses). **The ask to the client is the existing universal pixel snippet
   on the application domain — NOT a bespoke sign-up tag.** The URL rule is already written and would
   start counting applications by itself.

**Never substitute the sitewide Default tag for either.** At 429,374/30d it is ~150x the landing-page
number and is all site traffic, ad-exposed or not. The client's "attribute all sign-ups to the
campaign" position is a commercial agreement, not a measurement — it still needs something firing on
the apply page, and today nothing is.

**Order of operations in TTD:** ~~(1) attach `4tyuvnj` to the campaign → site visits flow~~ **DONE
2026-08-10**; (2) get the pixel onto `oa.starcard.com.au` → `7y9naeh` starts counting → attach it
too; (3) confirm the post-view / post-click attribution windows. The duplicate-pair caveat above was
checked against the first real totals — see the slot-layout note in `sql/01_stg_ttd.sql`.

## Funnel stage is HARD-CODED to Awareness (2026-07-31)

All three ad groups are set to **Awareness** in The Trade Desk (client-confirmed). An earlier version
inferred the stage from the ad-group NAME and wrongly tagged `AI Contextual` and
`Attention-Optimised` as Consideration - our inference, never TTD's setting.

TTD's ad-group **"Funnel location"** column is **not exposed by the Windsor connector** (verified
against `raw_windsor.windsor_fields`; the only funnel-ish field is `campaign_objective`, which is
CAMPAIGN-level and so cannot distinguish ad groups once a consideration phase is added inside the
same campaign). So the mapping is an explicit per-tactic `CASE` in `sql/01_stg_ttd.sql` - change the
one line for an ad group when its stage really changes. The three-way split still lives on the
**Spend by tactic** donut; the funnel-stage table intentionally shows a single Awareness row until a
consideration phase exists.

## Two measurement gaps, both with a verified path (2026-07-31)

### 1. Viewability - now carried end-to-end; the remaining step is inside TTD

The media plan commits to **70%+ viewability, IAS / DoubleVerify verified**. State as of 2026-07-31:

- Windsor DOES expose TTD viewability: `sampled_viewed_impressions` / `sampled_tracked_impressions`.
  Viewability rate = **viewed / tracked** (never viewed/impressions - only a sample is measured).
- Both field names were probed live and **accepted** (HTTP 200) BEFORE being added to the shared
  loader, because an unknown field name 400s the whole request and would break ingest for all five
  TTD clients.
- **BUILT (2026-07-31):** two nullable columns on `raw_windsor.perf_the_trade_desk`; the pair added
  to `tradedesk_loader.py` (`WINDSOR_FIELDS`, `transform()`, `_MERGE_SET_COLS` - so a re-pull
  refreshes it as TTD's sample settles); surfaced through `sql/01_stg_ttd.sql` ->
  `sql/02_fact.sql` (SUM both sides, divide once) -> `job/main.py` (`vw_viewed`/`vw_tracked` on
  `rows[]` + flight totals) -> the goal-panel row measured against the 70% target. Benefits every
  TTD client, not just caltex. **The "Viewability (sampled)" KPI TILE was removed 2026-08-05**
  (client request, alongside "Video completion"): with no sample returned and no video creatives,
  both only ever rendered a "-". The data path is untouched - `vw_viewed`/`vw_tracked`/`vcr` are
  still computed all the way to `rows[]`, so reinstating the tiles is a UI-only edit in
  `renderKpis()` (`dash/dashboard.html`), and the goal-panel caveat row still states the
  70% plan commitment.
- **Caltex still returns NO sample** (`sampled_tracked = 0`), while other advertisers on the same
  seat return real numbers (**72.0%** account-wide over 2026-07-29..30). So the metric works; it is
  simply **not enabled on these ad groups in TTD**.

**THE ONE REMAINING ACTION IS IN THE TTD UI**, not in this repo: enable viewability measurement on
the Caltex ad groups (or obtain the IAS/DoubleVerify report the plan references). The pipeline will
pick it up on the next nightly run with no code change.

Because "not measured" and "0% viewable" are very different claims against a 70% commitment, the UI
distinguishes them: a real rate when `tracked > 0`, and "not measured yet / enable in TTD" when the
sample is absent. It never renders 0%.

### 2. Star Card applications - STILL not measurable (site visits ARE, since 2026-08-10)

> **Superseded in part.** Route 1 below was the correct diagnosis and has been actioned: a tracker
> (`Landing Page Visit`) is now attached, so **landing-page visits are measured**. What remains
> unsolved is *applications specifically* - the apply step lives on `oa.starcard.com.au`, a domain
> the pixel is not installed on, so no tracker can see it. Route 3 (or simply the pixel snippet on
> that domain) is the remaining ask; route 2 is the fallback. History kept for the reasoning.

The measured tracker is scoped to the Star Card landing page, so it cannot see an application
completing on a different host (see the pixel section above). Three routes, cheapest first:

1. **Define a conversion tracker on the EXISTING pixel - almost certainly the real blocker, and it
   needs NO site access.** EVIDENCE (2026-07-31): all 18 Caltex rows return `conversions` = JSON
   **null** - not zeros, no slots at all - while VMCH, on the same connector and the same TTD seat,
   returns real slots (e.g. `{"view_through_conversion_01": 3.0, "conversion_touch_01": 3.0}`).
   Windsor's numbered slots mirror the advertiser's DEFINED conversion trackers, so null across every
   row means **no tracking tag has been created against pixel `z3eu6oa`**. The snippet on its own
   only collects fires; TTD reports nothing until at least one tracker is defined on it. Creating one
   is a TTD-UI task - no developer, no application-container access - and a tracker can be
   **URL-matched**, so if the application confirmation page has its own URL on the pixel's domain,
   "Star Card Application" can be captured today. Check two things first: that the pixel is actually
   firing (TTD shows fire counts per pixel), and that the confirmation page is a real URL on that
   domain rather than a separate portal or an SPA state with no URL change. Even a plain "all site
   visits" tracker is worth creating immediately - it lights up the dashboard's Site visits KPI,
   which currently reads "none attributed yet". When slots DO appear, check for TTD's duplicate-pair
   export (VMCH shows `_01`/`_02` byte-identical) before summing them.
2. **A client-supplied application count** (weekly CSV -> seed table, the `client_cloudflare` LINE
   pattern). This matches what the client already proposes - crediting post-launch applications to
   the campaign - but it is a TOTAL, not ad-attributed, and must be labelled as such.
3. **The application-container tag** they are still seeking access for - the only route giving true
   per-application attribution, and the one that also unlocks the plan's Phase 2 retargeting.

Until one of these lands, the dashboard must not show an application count. It currently says so.

Self-hosted paid-media dashboard. **Single channel** (The Trade Desk programmatic display),
**mixed awareness + consideration** brand campaign for Caltex fuel retail across **QLD+WA**,
bought via three tactics = the three TTD ad groups:

| Ad group | Tactic | Funnel stage (assumption — revisit with the media plan) |
|---|---|---|
| `Display Standard \| QLD+WA` | Display Standard | **Awareness** (broad, cheap reach — judged on CPM + volume) |
| `AI Contextual \| QLD+WA` | AI Contextual | **Consideration** (contextually-relevant moments — judged on CTR/CPC/actions) |
| `Attention-Optimised \| QLD+WA` | Attention-Optimised | **Consideration** (paying for engaged attention — judged on engagement quality, not raw CPM) |

The tactic + market are **parsed from the ad group name** (`"Tactic | Market"`) in
`sql/01_stg_ttd.sql`; a new ad group flows in automatically (unmatched tactics default to
Awareness). The stage mapping is a one-line CASE — change it there if the client disagrees.

## Architecture — one fact table, rolled up in the browser

The MongoDB/geocon pattern: the export ships ONE compact per-(date × campaign × ad group ×
creative) **fact table** (`rows[]`) and the dashboard rolls EVERYTHING up **client-side** — KPIs,
by-stage / by-tactic / by-creative, the daily trend, the vs-target Δ table — filtered by the
chosen **date range** + **stage chips**. Ratios (CTR/CPM/CPC/cost-per-action/video completion)
are never stored, always recomputed from summed components, so any sub-range is exact.

```
 raw_windsor.perf_the_trade_desk   sql: 01_stg_ttd -> 02_fact      job/main.py            dash/dashboard.html
 (Windsor TTD connector, shared →  advertiser 0lw3hp6 slice,   →   reads fact+targets, →  fetches /data.json, rolls
  windsor-tradedesk-ingest job)    tactic/market/stage parse,      writes fact + flight    up rows[] per the date/stage
        │                          conversion-slot sums            + benchmarks            filter; draws everything
   (stage-1 loader is shared)      + 03_targets / 04_budget            │                          │
                                        │                    caltex-export JOB (2)      caltex-dash SERVICE (3)
```

| I want to change… | Edit |
|---|---|
| Advertiser filter / tactic parse / stage mapping / conversion slots | `sql/01_stg_ttd.sql` |
| The fact grain / fields shipped to the browser | `sql/02_fact.sql` + `job/main.py` `rows[]` |
| CPM / CTR / CPC / impression / budget **targets** (all `PENDING` until the media plan lands) | `targets/targets.csv` · `targets/budget.csv` → `seed_static.py` → export `FORCE_REBUILD=1` |
| Flight / pacing math | `job/main.py` (`flight = {...}`) |
| Charts, tabs, glow, CSV export, the AI deck payload | `dash/dashboard.html` |
| AI-report framing | `dash/report.py` (retemplated for TTD awareness+consideration) |

## Honesty rules baked in

- **Site visits = TTD-attributed visits to the Star Card LANDING PAGE** (post-view + post-click),
  summed from Windsor's anonymous conversion slots and fed by the URL-scoped `Landing Page Visit`
  tracker. NOT all site traffic, and NOT applications. `conversion_touch_*` (total pixel fires,
  mostly not ad-attributed) is never used. Post-view dominating is *normal* for display and the UI
  says so.
- **Conversion-slot caveat:** once Caltex pixels actually fire, verify the slot layout — TTD can
  export one tracker as a duplicate column pair (VMCH's did; see `sql/01_stg_ttd.sql` header).
- **No reach/frequency** exists in the Windsor TTD feed → creative wear-out is read from weekly
  **CTR decay** (≥5k impressions/week), not frequency.
- **Targets marked `PENDING`** (all of them today, incl. the flight window 2026-07-14→09-30 and
  the A$30k budget — placeholders) render with a "pending" marker so nobody mistakes an
  assumption for an agreed KPI. Update `targets/*.csv` when the signed media plan arrives.

## The dashboard (`dash/dashboard.html`)

Caltex red (`#E4002B`) on the dark petrol-teal Bidbrain canvas, with the **2026-07 glow package**
(animated north-star KPI bloom, halos on active controls, lit pacing bar, card hover bloom;
disabled under `prefers-reduced-motion`). Three tabs — **Overview · Delivery · Creative** — all
honouring the shared Looker date-range picker, Awareness/Consideration stage chips and search;
time-series charts carry **VIEW BY Month/Week/Day + AXIS Relative/Absolute** (default Relative +
Week). Ships the house helpers: `bbApplySpendMult` (channel **`ttd`**), `bb-sortable` tables,
`bbDonutCenter`. Full tab-by-tab detail in [`dash/README.md`](dash/README.md).

Login password lives in Secret Manager `caltex-dash-password`; agency = **100% Digital**.

## Deploy (PowerShell; project `bidbrain-analytics`, region `australia-southeast1`)

```powershell
# edited dash/* → rebuild + swap the SERVICE:
.\clients\client_caltex\dash\deploy_dash_caltex.ps1

# edited a sql/*.sql view → reapply views + re-run the JOB (FORCE_REBUILD bypasses the gate):
.\.venv\Scripts\python.exe clients\client_caltex\create_views.py
gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# edited job/main.py → rebuild + swap + run the JOB:
.\clients\client_caltex\job\deploy_job_caltex.ps1

# first-time standup (APIs/SAs/IAM/secrets/service, then -WithData for views+job+scheduler):
.\clients\client_caltex\deploy_caltex.ps1            # placeholder service
.\clients\client_caltex\deploy_caltex.ps1 -WithData  # once TTD data is verified in raw_windsor
```

## Freshness

`caltex-export` is **self-gating** on a `*/10` UTC tick (`scheduler.ps1`): probes
`raw_windsor.perf_the_trade_desk` (`__TABLES__.last_modified` vs the `_freshness.json`
watermark) and rebuilds only when it advanced. Seed changes (targets/budget) and view-only edits
need `FORCE_REBUILD=1`.

**Expected lag is 1 day, never 0** — TTD refuses same-day dates, and the shared loader caps every
pull at yesterday UTC. Since 2026-08-07 `windsor-tradedesk-ingest` runs **twice daily**
(`35 1,21 * * *` UTC): the 01:35 UTC (= 11:35 AEST) run lands Sydney-yesterday data by ~midday
Sydney, so the dashboard shows through yesterday instead of 2 days back. The newest day can still
firm up slightly on the next 21:35 UTC re-pull (MERGE is idempotent). Client comms precedent: the
lag was explained to Tilly (Caltex) 2026-08-07 as a TTD platform limit.

## Coordinates

| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| Raw source | `raw_windsor.perf_the_trade_desk` (shared Windsor TTD connector; TTD advertiser **`0lw3hp6`**) |
| Views | `client_caltex.{stg_ttd, fact, targets, budget}` (+ `seed_targets` / `seed_budget` tables) |
| Job / Service | `caltex-export` / `caltex-dash` |
| Data bucket / file | `bidbrain-analytics-caltex-dash` / `caltex.json` (report cache in `reports/`) |
| Dash runtime SA | `caltex-dash-web@bidbrain-analytics.iam.gserviceaccount.com` |
| Report secrets | Vertex Gemini via ADC (default) · `anthropic-api-key` (optional Claude) |

## See also

- [Root CLAUDE.md](../../CLAUDE.md) — canonical agent fast-path: fixed facts, deploy commands, freshness contract.
- [`dash/LIVE_URL.md`](dash/LIVE_URL.md) — **status + the go-live / data-verification runbook.**
- [`dash/`](dash/README.md) · [`job/`](job/README.md) · [`sql/`](sql/README.md) — per-stage detail.
