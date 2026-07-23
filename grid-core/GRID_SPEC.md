# GRID_SPEC.md — The Grid: canonical specification

**Status: the single source of truth for the Grid, from 2026-07-23.** For day-to-day work this
document supersedes `GRID_BUILD_PLAYBOOK.md`; the playbook, `GRID_INVENTORY.md` and the
`PHASE*_REPORT.md` files at repo root remain as history and audit trail (keep them forever).
When this spec and an older document disagree, this spec wins. Keep it current: updating it is
part of finishing a change, not an afterthought.

Runtime in one line: a single static app (`the-grid.html`, hash-routed) served by plain-node
`server.js` (local `:8787`; Cloud Run service `central-grid`, proxied at
`dashboards.bidbrain.ai/d/central/`, super-admin only). Data = SQLite + BigQuery (below).

---

## 1. Purpose

The Grid replaces the agencies' manual Central Sheet ("Live Campaigns" in `central.xlsx`) with a
live, correct, single-source cockpit above the client dashboards. Two agencies — **100% Digital**
and **Transmission** — and ~14 advertisers ride one spine.

The product owner's core requirements, in their own priority order:

1. **Data must be CORRECT and in unison across every tab.** Clients' income depends on
   pace-correct spend; owners make calls off these numbers. Pulse, Central and Executive must
   agree to the digit because they read the same spine — parity by construction, never by
   coincidence.
2. **One-glance answers.** Each tab answers a different question off the same data spine — nobody
   should have to open every dashboard daily to know who needs attention.
3. **Media buyers stop hand-typing metrics; owners stop being blindsided.** Synced actuals
   replace transcription; loud staleness and error states replace silent rot.

The trust contract (binding): every number is **CONFIG** (typed/approved), **API** (synced from
platform truth) or **DERIVED** (computed fresh by the one engine). Never a stale hardcoded cell.

## 2. The tabs and the question each answers

| Tab | Question it answers | What it shows |
|---|---|---|
| **Pulse** | Which campaigns are on pace, and where is profit at risk? | Budget-pacing scatter (x = % flight elapsed, y = % budget spent, green on-pace wedge, bubble size = budget remaining); the "What needs attention" queue sorted by money at risk; "Wrapping up soon" (14-day window); by-advertiser roll-ups. Profit-at-risk uses the per-channel effective margin — **TTD/DV360 carry Platform Margin** (§3 money rules). Rows under 15% flight elapsed render `Early` and are deliberately not judged. |
| **Central** (merged with Register) | What is the full state of every campaign? | The automated Central Sheet: every client, per-client tick/untick accordions, CONFIG/API/DERIVED column tagging, LIVE/SHEET markers, inline CONFIG editing, column-group filters (Core / Pacing / Budget / Margin / Performance / Links) responding across the whole table, Group: advertiser vs Flat, search, Manager filter, CSV export, the media-plan reader dropzone, and the Map-client reconcile entry point. **Register as a separate tab is retired** (Phase 2); its filtering lives here. |
| **Brain** | What should we do about it? | Marketing-expert-grade optimization recommendations: quality over quantity, grounded in the account's own historical data (the V3 historical-ingestion pipeline exists precisely so the engine learns from past wins/mistakes), and **never platform-self-serving defaults** — the Google-PMax trap: a platform's own recommendations serve the platform. Keeps the Optimization Log. The Site Quality Index card is REMOVED (Phase 4; real site-quality scoring is blocked on TTD seat access). Recommendations are still mock (V1) — the real engine is roadmap (§5). |
| **Executive** | Is any client quietly failing? | One card per client: objective + headline KPI at a glance (KPI, trend delta, sparkline, target meter where a target exists, supporting metrics with context chips), Daily/Weekly/Monthly reading toggle, click-through to that client's dashboard. Replaces the old Dashboards tab. Verdicts are deliberately **LENIENT** (On track / Watch / Behind / At risk) — an at-a-glance view that cries wolf gets ignored. |

## 3. Data architecture (as actually built)

### The spine

- **SQLite** `data/brain-historical.db`, table `campaigns` — the operational store (config,
  provenance, approvals). Seeded ONCE on boot from `config/central-import.json` (idempotent; a
  one-time import, not a pipeline). Rows carry a stable `id`, `sourceOfRecord`
  (`sheet-import | manual | plan`), `metricsSource` (`sheet-import | bq`), `spendBasis`
  (`billed | sheet`), `archivedAt` (soft delete only).
- **One formula engine:** `src/central/calc.js` (`derive.js`, the inline engine and the baked
  `const DATA` are retired — Phase 1). Every tab fetches `GET /api/central/campaigns` and computes
  derived fields fresh via `CentralCalc.computeRow()`, anchored to the DB's newest `lastSyncedAt`.
  DERIVED fields are never writable (`db.js` whitelists reject them at every route).
- **BigQuery is the actuals layer** (`raw_snowflake.*`, `raw_windsor.*`); the sync overlays
  `impressions`/`mediaSpend` onto mapped rows. SQLite stays a deliberate placeholder for the
  future Bidbrain-native operational store — designs must survive that move.
- **Staleness thresholds live in ONE place:** `src/central/staleness.js` (warn > 6h, red > 24h;
  never-synced is its own loud state; `mixed` = live + sheet rows in one client). Never add a
  local copy.

### Client specs — `config/central-clients.json`

One entry per client: `validated` (bool), `source` (`raw | none`), `tables[]`, `map[]`.

- **Mode B ONLY — per-channel raw-table rules.** Each table rule = dataset, table,
  advertiser/account column + exact `advertiserValue` (BQ spelling, quirks included: `"VMCH "`
  trailing space, `"PopTrack"` typo), campaign column (the GRAIN — see naming rules), impression
  column (COALESCE legacy variants where needed), cost column, date column. Map entries are
  per-row `{campaignId, channel, advertiserName, campaignMatch:{mode: exact|contains|rollup,
  value}}` — one row per campaign-per-channel.
- **Mode A (cross-platform aggregate views) is BANNED.** A program view (Schneider's old
  `pm_delivery`) aggregates ACROSS platforms and lands the blend on one arbitrary channel row —
  the PHASE3_CLOUDFLARE §9 corruption: 5 Schneider rows written with LinkedIn dollars on TTD rows,
  then re-multiplied by sheet spendMults. Do not resurrect Mode A for any client.
- `validated: true` is the sync gate AND the containment lever: flipping it false stops all
  writes to that client on the next sync, no restart needed.

### The reconcile flow (how a client becomes validated)

1. A prep session pulls the BQ name list and **stages** curated, evidence-based candidate pairs
   into `config/reconcile-staged/{Client}.json` (per pair: match rule, confidence, rationale, BQ
   spend preview; plus warnings, unmatchable rows, BQ orphans). Staging writes NOTHING.
   **Evidence beats fuzzy scores:** budget/spend agreement at the right grain is the real signal
   (matches provable to the dollar with zero name overlap exist — Coles Prog ← "HyperlocalGeo").
2. The human opens the **Map client** panel: staged pairs render first (unticked), then generic
   fuzzy suggestions with honest flags (`weak` / `ambiguous` / `no-platform-match`).
   **Platform consistency is a HARD rule at two layers:** candidates are filtered by the BQ
   name's platform token AND the source-table channel tag, and `/approve` rejects any
   cross-platform pair with a 400.
3. Human ticks + approves → `POST /api/central/reconcile/:client/approve` writes the pairs into
   `map[]` and flips `validated: true`. **The approve click arms the sync** — every prerequisite
   (spendMult basis, platformMargin, currency scoping, fresh campaignIds) must be resolved
   BEFORE approving.

### Sync semantics — `POST /api/central/sync`

- **No param = ALL validated clients.** `?client=<name>` scopes to ONE client (Phase 4 fix — the
  param is honored now; the fetcher runs `--client <name>` so other clients' BQ is never queried;
  unknown/unvalidated name → 400, nothing synced). `?includeEnded=1` adds Ended rows — the
  deliberate one-time backfill, never the default.
- Matching uses ONLY the explicit map (fuzzy is reconcile-only). Per matched row the sync writes
  `impressions`/`mediaSpend`, sets `metricsSource:'bq'` + `lastSyncedAt`, and:
  **spendMult set** → `clientSpend = mediaSpend × spendMult`, `spendBasis:'billed'`;
  **spendMult unset** → `clientSpend` UNTOUCHED (`spendBasis:'sheet'`, unbilled-basis badge).
  It never writes `clientSpend = mediaSpend` silently. CONFIG columns are never written by sync.
- **No FX.** The sync sums raw cost columns with no conversion — a spec must be scoped to ONE
  currency's account via `advertiserValue`. If in-scope campaigns genuinely span currencies:
  stop and flag; the sync cannot handle it. (This is why STT must not be validated as-is.)
- Map `campaignId`s go stale on a DB rebuild; the (client, name) fallback picks the FIRST
  same-named row regardless of channel — re-reconcile after any rebuild.

### Money rules (each of these has bitten us)

- **Cost basis per raw table** (verify with a date-bounded BQ sum vs BOTH sheet columns before
  any first sync): `raw_snowflake.tradedesk_apac_all.COSTS` = **CLIENT-BILLED**;
  `raw_snowflake.dv360_apac.REVENUE_ADV_CURRENCY` = **CLIENT-BILLED**. → **spendMult MUST be 1**
  on rows synced from those tables (a sheet-derived 2.5–3.5× mult double-counts the margin — the
  §9 corruption). LinkedIn/Reddit `COSTS` = media = billed (mult 1). `raw_windsor.*` = raw media
  (sheet mult stays, but re-verify per client). DV360 `MEDIA_COST_ADVERTISER_CURRENCY` (still in
  the STT/PropTrack/HireRight specs) is media-basis — each validation picks its basis
  deliberately.
- **Effective margin per channel:** TradeDesk/DV360 → **Platform Margin**; every other channel
  (Google, Meta, LinkedIn, Reddit, DOOH, LINE, …) → **Campaign Margin** (realized). Never one
  blended formula. A platform-margin channel missing its margin degrades LOUDLY
  (`platform-margin-missing` warning, est. fallback) — never silently. Billed-basis TTD rows
  legitimately show ~0% realized campaignMargin post-sync — cosmetic, not a money error.
  Sheet Platform-Margin cells are not trustworthy (two hand-typed stale literals survived import
  sanity checks) — eyeball TTD/DV360 margins against the 0.60–0.65 agency standard.
- **Budget basis:** media plans state the MEDIA budget; Central/Grid budgets are CLIENT-BILLED —
  **~2× apart on fee-loaded rows** (Cloudflare §10.2: seven of eight rows at 1.2–2.7×). Never
  write a plan budget into `totalBudget` without basis normalization (this is plan-reader v2's
  founding requirement — `docs/plan-reader-v2-design.md`).

### Naming and grain rules

- **Prefer `contains` rules on stable suffix tokens.** Mid-flight renames add numeric job-number
  prefixes (`2103_`, `2306_` …; Schneider renamed its whole portfolio in one day) — exact-name
  matches silently drop the renamed vintage. Verify the token set partitions cleanly: every BQ
  name claimed by exactly one rule.
- **Pick the grain where sheet and BQ totals agree** — it differs per platform: TTD = campaign
  name; **LinkedIn = campaign GROUP** (`CAMPAIGN_GROUP_NAME` — program membership exists nowhere
  else); **DV360 = INSERTION ORDER** (IOs split rows that share one campaign, to the dollar).
- **Same-named rows differing by Objective are distinct rows — never archive as duplicates**
  (the three `Software First EcoStruxure · LinkedIn` rows are Awareness / Retargeting 1 /
  Consideration; Phase 2's "duplicate" read was wrong).

## 4. Operational runbook

**Onboard a client end-to-end** (one client at a time; prep is agent work, approval is yours):

1. **Currency/account audit first** (LinkedIn + DV360 especially): list the client's
   accounts/advertisers per table; if in-scope campaigns span currencies, stop — scope
   `advertiserValue` to one currency's account or don't onboard yet.
2. **Cost-basis check per table** (§3 money rules): date-bounded BQ sum vs the sheet's media AND
   billed columns. Billed feed → plan for `spendMult = 1` on those rows.
3. **Prerequisites BEFORE approval:** spendMult set right (inline-editable, Margin column
   group), platformMargin present + sane on every TTD/DV360 row, staged `campaignId`s verified
   to resolve (fresh after any DB rebuild), prep writes through the governed
   `db.updateCampaignField` path (provenance; ungoverned SQLite writes vanish on rebuild).
4. **Stage** the evidence-based pairs in `config/reconcile-staged/{Client}.json`; put the
   consequences in its `warnings[]` (the panel renders them).
5. **Approve in the Map client panel** — knowing the approve click validates the client and arms
   every future no-param sync.
6. **First sync scoped:** `POST /api/central/sync?client=<name>` (+`&includeEnded=1` only when an
   Ended backfill is intended — the Sync now button does not pass it).
7. **Verify:** LIVE/BQ badges on the mapped rows; spend vs BQ direct; correct margin type per
   channel; no lingering amber `N SHEET` chips except deliberately-unmapped rows; the client's
   Executive card vs its dashboard headline (resolve its `config/kpi-objects/<c>.json` stub).

**Run a sync safely.** Prefer `?client=` scope. Remember the no-param sync (and any approve
click) covers ALL validated clients — post-sync verification must too. After editing server
code, confirm the RUNNING process vintage (start time vs file mtime) — a stale `node server.js`
serves new files with old route code in memory; "I restarted it" is unverified until the old PID
is dead.

**Read staleness.** Pill/chips: `never` (NO SYNC — a human has work to do) / fresh / amber > 6h /
red > 24h; amber SHEET tags mark rows inside a synced client that the sync does not cover. Once
autosync ships, amber stops meaning "nobody pressed the button" and starts meaning "the pipeline
is broken" (`docs/autosync-design.md`).

**When numbers look wrong — the containment pattern (§9-proven):**

1. **Flip the client `validated: false`** in `central-clients.json` — stops the bleeding at the
   next sync, no restart, no code.
2. **Restore the affected rows from `config/central-import.json`** with a targeted,
   read-back-verified script (`scripts/schneider-containment-v2.js` is the template): restore
   mediaSpend/clientSpend/impressions, set `metricsSource:'sheet-import'`, `lastSyncedAt: NULL`.
   **Never file-swap or hand-edit the DB**; never touch rows you can't tie to the incident.
3. Diagnose (map grain? basis? stale ids?), fix the map/spec, re-stage, re-approve — the fix
   flows back through the same human gate it should have passed the first time.

## 5. Current state (2026-07-23) + roadmap

**Live — BQ-validated, synced, Mode B:**

- **Cloudflare** — 14 of 17 rows LIVE (LinkedIn group grain, TTD `COALESCE(IMPRESSIONS,
  IMPRESSION)`, Reddit; TTD spendMult=1 held). Unmatchable by design: Q2 Core DG · LINE (no LINE
  raw table) and Q3 Core DG · Google Ads (no Cloudflare account in `google_ads_apac`).
- **Schneider** — 18 of 25 rows LIVE (8 TTD + 8 LinkedIn approved 2026-07-23; the 2 EAE · DV360
  pairs approved + backfilled same day: billed $5,713.90/$2,649.17, spendMult=1,
  platformMargin=0.6). The 7 sheet-only rows are all explained: IA Services · LinkedIn
  (unapproved — BQ $8,226 vs sheet $4,955, does not reconcile), SF EcoStruxure Retargeting 1 +
  Consideration · LinkedIn (not launched), Heavy Industries ×2 (channel NULL in the sheet; real
  TTD delivery exists — set channel on ONE row, then map), AET · Google Ads (no Schneider account
  in `google_ads_apac`), DOOH (no source anywhere).
- **Closed anomalies:** the EAE sync gap (above) and the EBA / SF EcoStruxure TTD margin
  anomalies (hand-typed sheet literals 0.9729/0.843 → 0.60 via `scripts/margin-anomaly-fix.js
  --apply`, durable in `central-import.json`). Note: these post-Phase-4 config changes
  (`central-clients.json` EAE map entries + the reformatted `central-import.json`) are
  **uncommitted local state at the time of writing — commit them.**
- **Known residual landmines:** the EAE rows' spendMult/platformMargin in `central-import.json`
  are still null (a DB rebuild re-seeds them null — benign but re-prep before re-approving);
  `build_central_import.js` regeneration would also drop the Schneider spendMult=1 and margin
  patches — re-apply (or fix the source sheet) after any regeneration.

**Staged / spec'd, not yet validated** (specs in `central-clients.json`, `map: []` unless noted):
HireRight (pre-seeded map awaiting confirmation), **STT (danger case: spec spans SGD + USD
accounts on LinkedIn, Google Ads AND DV360 — MUST NOT be validated as-is; no FX in the sync)**,
PropTrack, MongoDB (real TTD delivery keyed on `tradedesk_apac_conversion` advertiser id
`9c1w83i`; NO cost column there — spend stays sheet-based), City Perfume, ResetData, VMCH,
The Little Marionette (main Google spend in un-audited `raw_google_ads` — coverage gap), QTopia,
Ad Assembly. STT/PropTrack/HireRight DV360 specs still carry the media-basis cost column — each
validation must pick its basis deliberately.

**Unmatchable by design** (`source: "none"` — no advertiser in `raw_snowflake`/`raw_windsor`):
Gateway, Caltex, Next Smile Australia, Bell Shakespeare. They stay sheet-valued; their `NO SYNC`
chips are honest.

**Roadmap, in order:**

1. **Remaining approvals** (Mission 1 batch validation): work down by money at stake; each run
   follows §4's onboarding steps. Resolve the 5 deferred Executive KPI stubs as each client
   validates.
2. **Autosync** — design done, nothing enabled (`docs/autosync-design.md`: hourly, validated
   clients only, never `includeEnded`, loud auth-failure alerting for BOTH credential stores,
   pause/resume kill switch). Build only after money-material clients are validated.
3. **Brain build-out** — the real recommendations engine (BQ + the V3/V3.5 history →
   scored recs; real ClickUp round-trip; replace `brain-mock-data.js`). Biggest data blocker:
   no per-placement/per-site ingest exists (Trade Desk stops at campaign×ad_group×creative);
   site-quality work additionally blocked on TTD seat access.
4. **Plan-reader v2** — `docs/plan-reader-v2-design.md`: basis-aware, Central-independent
   seeding for clients that never had a central sheet.
5. **Bidbrain integration** — a connection job, not a rescue job: map Grid clients onto
   Bidbrain's hierarchy, swap SQLite for the production operational store, feed the metrics
   catalogue.
