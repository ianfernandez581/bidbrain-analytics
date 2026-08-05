# Executive Dashboard — handover

A precise spec for rebuilding the **Executive dashboard** in another project (**bidbrain**, the
**Report** tab). Reference implementation: **The Grid's Executive tab** (`grid-core/the-grid.html`
→ `renderExec()` + the `#exec-css` block; server route in `grid-core/server.js`; data builder
`grid-core/scripts/build_exec_kpis.py`). A single self-contained copy of the whole thing, with real
data, is **`executive-dashboard-demo.html`** (open it in a browser — that IS the design + behaviour to
match). Read this doc first; the demo file is the working answer key.

---

## 1. The goal (do not lose this)

An **agency-level, at-a-glance overview of every client on one screen**. Each client is shown by the
ONE (or two) metrics it is actually paid to move — **ROAS** for e-commerce, **leads** for lead-gen,
**impressions/reach** for awareness, **clicks/traffic** for traffic — so a stakeholder can tell, in a
single glance, **which clients are performing and which need a look**, without opening each dashboard.

It is the **overview layer above the per-client dashboards**:

> All clients, most-important-KPI-first → click a client's cell → that client's **full dashboard**
> (the same headline number, now with all its supporting metrics).

In **bidbrain**: this replaces / fills the **Report** tab. The Report tab = this overview.

**One-line test of correctness:** if a client is quietly slipping, it shows up at the top of Report
*before* anyone opens that client's dashboard. If everything's fine, Report is calm (few/no flags).

---

## 2. Anatomy of one client cell (card)

Each cell is one client. Top-to-bottom:

1. **Monogram + name + agency**, and a **verdict pill** (On track / Watch / Behind / At risk).
2. **Plan objective** (small label, e.g. "ROAS", "Lead gen + Site traffic") — what this client is bought for.
3. **The headline KPI**: a big number (the client's main metric) + its **unit**, and a **trend delta**
   ("▲7% month over month").
4. **Sparkline** of that KPI over the recent window.
5. A one-sentence **plain-English read** ("Trending up ~7% MoM; at 55% of the plan target").
6. **KPI-vs-target meter** (only when a target exists), e.g. `618 / 1,117`.
7. **Supporting metrics** (1–2) with a **context chip** (e.g. "Cost / lead · 20% under target").
8. The **whole cell is clickable → opens that client's full dashboard.**

Cells are **grouped by objective** (Acquisition / Awareness & Traffic / Sales), and any non-"On track"
cell also appears in a **"Needs attention"** section pinned at the top.

Controls above the grid: **Reading** toggle (Daily / Weekly / Monthly), **Objective** dropdown,
**Agency** filter, clickable **verdict summary cards** (filter by status), and **Sync now**.

---

## 3. The per-client data contract (build this shape per client)

Everything renders from an array of these objects (`EXC` in the code). Match this shape and the view
works; the whole design is downstream of it.

```js
{
  key: "cloudflare",                 // stable id
  mono: "CF",                        // monogram
  name: "Cloudflare",
  agency: "Transmission",            // for the agency filter
  group: "lead",                     // objective BUCKET: "lead" | "reach" | "sales" (drives grouping)
  dash: "Cloudflare",                // click-through target key (see §8); null = no drill-down
  obj: "Lead gen + Site traffic",    // human plan-objective label

  mlbl: "Accepted CS leads (Q3 to date)",  // headline KPI label
  val: 294,                          // headline KPI value
  unit: "",                          // "" | "×" (ROAS) | "%" ...
  fmt: "int",                        // "int" (compact 1.2k/3.4M) | "x" (1 decimal, ROAS)

  target: 5506,                      // KPI target (full-flight); null => trend-only, no meter
  targetLbl: "Q3 target",
  pace: 0.0534,                      // val/target (progress); drives the meter fill + verdict nudge

  gd: { d: 0, w: 0, m: 70 },         // trend % per grain (daily/weekly/monthly) — see §6
  sk: { d:[…12], w:[…12], m:[…12] }, // sparkline series per grain (see §6)
  noDaily: true,                     // true when this metric has no daily series (Daily falls back to Weekly)

  sec: [ ["83%","Acceptance rate", null],          // supporting metric: [value, label, chip|null]
         ["$150","Cost / lead", {t:"12% over target", tone:"bad"}] ],  // chip tone: good|bad|flat
  sum: "Trending up ~70% MoM. At 55% of the plan target."  // one-line read (string, or {d,w,m} per grain)
}
```

Nothing about the layout is client-specific — only this data is. Add a client by producing one object.

---

## 4. Choosing each client's main KPI (the important judgement)

Map every client to **the metric its objective is judged on**, and bucket it:

| Objective | `group` | Headline KPI (`mlbl`/`val`) | Target? |
|---|---|---|---|
| Sales / e-commerce | `sales` | **ROAS** (revenue ÷ ad spend) | target ROAS if set |
| Lead generation | `lead` | **Leads** (accepted / MQL+HQL / signups / enquiries) | plan lead target |
| Awareness / brand | `reach` | **Impressions / reach** | plan impressions |
| Traffic / consideration | `reach` | **Clicks / sessions** | usually none → trend-only |

Rules of thumb: show the client's **actual** main KPI from its own data (the same number its dashboard
headlines), not a proxy. Where the plan has a target, pace against it; otherwise judge on trend. Put the
1–2 most telling secondary numbers in `sec` (e.g. acceptance rate, CPL, paying customers) **with a
comparison** so they mean something on their own.

---

## 5. The verdict — deliberately LENIENT (do not cry wolf)

Colour + label per cell. **Why lenient:** the audience over-alarms; if Report flags too much it gets
ignored. Wide green band; red only for a real, sustained problem.

```js
function verdict(pace, delta) {            // delta = trend % at the selected grain; higher is better
  let lvl = delta >= -8 ? 0 : delta >= -20 ? 1 : delta >= -35 ? 2 : 3;   // trend is primary
  if (pace != null && pace < 0.5 && delta < 0) lvl = Math.min(3, lvl+1); // target: only nudge if BOTH behind AND slipping
  return ["ok","watch","behind","risk"][lvl];
}
// then: awareness/reach clients are capped at "watch" — impression delivery varies with flight phase,
// it is never a "fire":  if (group==='reach' && (v==='behind'||v==='risk')) v = 'watch';
```

Key point: **targets are full-flight**, so a low pace *early* in a campaign is normal — pace never flags
on its own; the **trend** is the signal. (Cloudflare at 5% of a Q3 target reads *On track* because Q3
just started and the trend is flat.)

---

## 6. The trend + sparkline (rolling windows — the non-obvious bit)

Compute `gd` (delta %) over **rolling equal-length day windows** anchored at the latest date:
Daily = last 3 days vs prior 3, Weekly = last 7 vs prior 7, Monthly = last 30 vs prior 30. **Do NOT**
compare calendar buckets (this-month vs last-month), because the current month is incomplete and every
client looks like it just crashed (−90%). Rolling windows fix that and work for weekly-grained series too.

- Guard: if the recent window is ~0 (flight ended/dormant), report 0, not a scary −100%.
- Clamp the **displayed** delta (e.g. `>200 → "200+"`) — tiny denominators produce absurd % on the daily view.
- `sk` = the last 12 buckets (day/week/month) for the sparkline. `noDaily` clients fall back Daily→Weekly.

The Reading toggle matters: a client can look rough weekly but be a normal monthly hiccup, or hide a
slow monthly bleed behind good-looking weeks.

---

## 7. Where the numbers come from (data pipeline)

Each client's KPI should be the **same number its own dashboard shows** — so read from the same source
(in this repo: each client's `data.json` in GCS, itself built from BigQuery). Reference builder
`scripts/build_exec_kpis.py` reads every client's source and emits the §3 array. Then, three layers,
same shape:

1. **live endpoint** `GET /api/exec` (cache) + `POST /api/exec/sync` (force refresh, what **Sync now**
   calls) — the server runs the builder on demand;
2. a **build-time snapshot** file as fallback;
3. a **baked preview** array as last resort (offline).

**Refresh:** on-demand via the Sync button, plus a scheduled refresh (e.g. every 10 min). On Cloud Run,
background work needs CPU-always-allocated (`--no-cpu-throttling --min-instances=1`) **or** a Cloud
Scheduler `*/10` ping to `POST …/sync` (request-scoped = full CPU). For bidbrain, use whatever refresh
mechanism it already has for its client metrics.

---

## 8. Porting into bidbrain's Report tab — checklist

The exec view is **one self-contained, framework-free module** (`executive-dashboard-demo.html` is the
entire thing: a `<style>` of `.ex-*` classes + the `EXC` data + ~15 small JS functions). To integrate:

1. **Render** the exec view into the Report tab's container (in vanilla, call `renderExec()`; in
   React/Vue, port the `exCard`/`renderExec` string-builders to components — keep the logic identical).
2. **Supply `EXC`** from bidbrain's own client-metrics source, mapped to §3–§4 (this is the real work —
   the design is done).
3. **Wire the cell click** (`data-dash` / the click handler) to bidbrain's **per-client dashboard route**
   (e.g. `/dashboard/<client>` or however bidbrain deep-links a client). In the demo it opens each
   client's dashboard URL; swap that for bidbrain's routing.
4. **Theme** by swapping the CSS custom properties (`--bg`, `--panel`, `--ink`, `--brand`, …) for
   bidbrain's brand + dark/light. Verdict colours are semantic (fixed), not brand.
5. **Access:** it exposes cross-client performance, so gate it to the agency/admin (and, if a single
   client ever views their own Report, filter `EXC` to that client).

**What must transfer intact:** the DATA CONTRACT (§3), the KPI-choice mapping (§4), the LENIENT verdict
(§5), and the rolling-window trend (§6). Those encode the idea; the HTML/CSS is just presentation.

---

## 9. Gotchas (paid for already — keep these)

- **Rolling windows, not calendar buckets** for the trend (§6) — else false −90% crashes.
- **Clamp the displayed delta** (daily windows with tiny denominators → "15000%").
- **Awareness clients capped at Watch** — impression swings are flight phase, not a crisis.
- **Targets are full-flight** → don't flag low early pace; trend is primary (§5).
- **Pick the metric its dashboard actually headlines** (e.g. VMCH = ad-attributed conversions, NOT the
  all-time GA4 enquiry count which includes an old, non-comparable taxonomy).
- **Cloud Run CPU throttling** kills background refresh unless CPU-always or a Scheduler ping (§7).
- **No em-dashes** in any client-facing copy (house style) — use "-".

---

*Reference files:* `grid-core/the-grid.html` (`renderExec`, `#exec-css`), `grid-core/server.js`
(`/api/exec`), `grid-core/scripts/build_exec_kpis.py`, and `executive-dashboard-demo.html` (standalone).
