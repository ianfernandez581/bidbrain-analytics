# Autosync — design note (Phase 4 item 8. DESIGN ONLY — nothing here is enabled)

**Status: NOT BUILT, NOT SCHEDULED.** Implementation happens only after every
money-material client is validated (Mission 1 approvals done + their first manual
syncs verified). This note exists so the eventual build inherits tonight's lessons
instead of re-learning them. The dormant `CENTRAL_AUTOSYNC_MIN` interval hook in
`server.js` stays **off** (0/unset) until this design is implemented — a bare
interval without the failure-alerting below is exactly the silent-corruption /
silent-staleness pattern Phase 4 closed out.

## What already exists (build on it, don't duplicate)

- `performCentralSync()` — the ONE guarded sync core (concurrency guard, per-client
  filter honored since Phase 4 item 1, `CENTRAL_LAST_SYNC` tracking).
- `CENTRAL_AUTOSYNC_MIN` env — a simple interval tick through that same core.
  Currently unset everywhere. The tick logs errors to console only; that is NOT
  enough (see Failure alerting).
- `src/central/staleness.js` — the single threshold config (warn > 6h, red > 24h)
  every tab renders from. Autosync's cadence must be derived from these numbers,
  never a second copy.
- The repo-wide freshness contract (CLAUDE.md): client dashboards self-gate on a
  `*/10` tick and rebuild only when upstream advanced. Central's autosync should
  converge on the same philosophy eventually (gate on `__TABLES__.last_modified_time`),
  but v1 below is a plain interval — the BQ cost of the mapped queries is small.

## Cadence

- **Every 60 minutes**, aligned so a fresh sync always exists well inside the 6h
  warn threshold (one missed tick + one failed tick still leaves 4h of margin).
- NOT `*/10`: the sync queries every mapped raw table per validated client; unlike
  the dashboards' metadata probes these are real queries, and Central is a
  trading-desk tool, not a realtime dashboard. Hourly is fresh enough for pacing
  and profit-at-risk.
- Overnight backoff is NOT worth the complexity (the queries are cheap; skip).

## Which clients

- **Validated clients only** — autosync calls the same core as the manual route,
  which already skips `validated: false`. No per-client cadence in v1: one global
  sync of all validated clients per tick (the per-client `?client=` scope stays a
  manual/recovery tool).
- A client with unresolved carry-forwards must be kept `validated: false` — that
  containment rule (PHASE3 §9) is what makes "sync all validated" safe, and
  autosync leans on it completely. **The approve click arms autosync too** — this
  must be stated in the Map client panel warning once autosync ships.
- Ended rows: autosync NEVER passes `includeEnded` — backfills of Ended rows are
  deliberate one-time manual actions.

## Staleness interaction

- A successful tick keeps every synced client inside `fresh` (< 6h). Therefore,
  once autosync is on: **any amber (> 6h) chip means ≥ ~5 consecutive failed or
  skipped ticks** — amber stops meaning "nobody pressed the button" and starts
  meaning "the pipeline is broken". That reframing is the main UX consequence and
  should be added to the chip tooltips when autosync ships.
- `never`-state clients (sheet-import-only) are unaffected — autosync does not
  touch unvalidated clients, so their "NO SYNC" chips remain the honest signal
  that a human has work to do (Mission 1), not that a scheduler failed.
- The Executive cards' `GRID <age>` chips inherit the same reframing for free
  (they read the same staleness.js rollup).

## Failure alerting — the tonight lesson (loud, never `updated: 0` quietly)

Tonight's failure mode, reproduced during Phase 4 item 6: **gcloud/ADC reauth
expiry**. Two credential stores are in play and they fail INDEPENDENTLY:
`central_sync.py` shells the `bq` CLI (gcloud CLI credential store), while
`build_exec_kpis.py` uses the Python GCS client (**ADC** — expired tonight with
`RefreshError: Reauthentication is needed` while `bq` still worked). An expired
credential makes the fetcher return errors or nothing; a naive tick would log
`updated: 0` and the grid would silently go stale. Requirements:

1. **Classify auth errors explicitly.** The fetcher already captures per-client
   errors into the response `errors[]`. The autosync tick must inspect them:
   anything matching `reauth|credential|invalid_grant|Access Denied|401|403`
   is an AUTH failure, not a data hiccup.
2. **Surface loudly in the UI**: persist the last tick's error state into
   `CENTRAL_LAST_SYNC` (already carries `errors` count — add `authFailure: true`)
   and have `/api/central/sync/status` drive a RED banner on Central ("Autosync
   is failing: BigQuery auth expired — run `gcloud auth login` on the host"),
   not a console line. The staleness chips go amber eventually; the banner says
   WHY immediately.
3. **Escalate out-of-band after N consecutive failures** (N=3): the platform
   repo pattern is available (status-dash job → status.json → health badges);
   minimum viable = a Cloud Run log-based alert on a structured
   `[CENTRAL][AutoSync] AUTH-FAILURE` line. Choose at build time; do not ship
   autosync without at least the log-based alert.
4. **`updated: 0` with zero errors is ALSO a signal** when the previous tick
   updated > 0 rows and BQ tables advanced — but v1 keeps this out of scope
   (requires the last-modified probe). Record only: tick history (last 24 ticks,
   in-memory) exposed on `/api/central/sync/status` so a human can see the
   pattern.

## Kill switch

- **Env:** `CENTRAL_AUTOSYNC_MIN=0` (or unset) = off — already the behaviour of
  the dormant hook; keep it as THE master switch (restart required).
- **Runtime:** add `POST /api/central/autosync/pause` (and `/resume`) flipping an
  in-memory flag the tick checks — no restart needed when a bad sync is
  discovered mid-incident. Pause state must be visible in `/sync/status` and as
  a chip next to Central's "auto every Nm" note.
- **Per-client containment stays the existing lever:** flip the client to
  `validated: false` in `central-clients.json` (takes effect next tick, no
  restart). This is the §9-proven mechanism and needs no new code.

## Explicitly out of scope for v1

- Self-gating on BQ `last_modified_time` (the dashboards' freshness contract) —
  a cost optimization, not a correctness need, at Central's query sizes.
- Per-client cadences / priorities.
- Autosync of the Executive KPI cache (it has its own `EXEC_AUTOSYNC_MIN` loop
  and its own failure mode — ADC — which the auth alerting above must ALSO tag).
- Any scheduler in this phase. **Do not enable anything on the strength of this
  note alone.**
