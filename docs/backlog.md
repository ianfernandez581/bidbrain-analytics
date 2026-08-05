# Greenlight backlog — all 28 issues

> Generated from `greenlight-issues.json` (backlog v2, revised 2026-08-05). This file is the human-readable
> mirror of the JSON; the JSON is what `create-greenlight-backlog.ps1` actually reads. If they disagree,
> the JSON wins — edit the workbook first, regenerate the JSON, then refresh this file.

Issue bodies below are exactly what lands in GitHub: description, acceptance criteria, notes, dependencies and suggested branch.

## Index

| ID | Title | Type | Priority | Milestone | Est | Owner | Status |
|----|-------|------|----------|-----------|-----|-------|--------|
| [GL-01](#gl-01--move-greenlight-extraction-to-a-background-job) | Move Greenlight extraction to a background job | refactor | P0 Critical | M1 | M | Ian | Backlog |
| [GL-02](#gl-02--purge-committed-client-raw-material-and-fix-the-ignore-policy) | Purge committed client raw material and fix the ignore policy | bug | P0 Critical | M1 | M | Ian | Backlog |
| [GL-03](#gl-03--enable-greenlight-on-the-live-grid-flag-secret-bucket-smoke-run) | Enable Greenlight on the live Grid (flag, secret, bucket, smoke run) | task | P1 High | M1 | S | Ian | Backlog |
| [GL-04](#gl-04--ci-workflow-run-the-test-suites-regression-gate-on-demand) | CI workflow: run the test suites; regression gate on demand | testing | P1 High | M1 | M | Jerome | Backlog |
| [GL-05](#gl-05--close-the-drift-inside-expected-readme-md) | Close the drift inside expected/README.md | documentation | P2 Medium | M1 | XS | Christian | Backlog |
| [GL-06](#gl-06--wire-dashboard-js-validation-into-the-sanity-gate) | Wire dashboard JS validation into the sanity gate | testing | P2 Medium | M1 | S | Juan | Backlog |
| [GL-07](#gl-07--surface-run-cost-and-duration-in-the-run-history) | Surface run cost and duration in the run history | enhancement | P3 Low | M1 | XS | Juan | Backlog |
| [GL-23](#gl-23--guard-the-hubspot-deals-truncate-against-an-empty-response) | Guard the HubSpot deals truncate against an empty response | bug | P1 High | M1 | XS | Juan | Backlog |
| [GL-27](#gl-27--fix-the-dead-clone-url-and-stale-client-list-in-onboarding-md) | Fix the dead clone URL and stale client list in ONBOARDING.md | documentation | P3 Low | M1 | XS | Christian | Backlog |
| [GL-28](#gl-28--finish-the-client-material-upload-path-byte-staging-into-the-analysis-dump) | Finish the client-material upload path (byte staging into the analysis dump) | feature | P1 High | M1 | M | Charles | In Progress |
| [GL-08](#gl-08--adr-actuals-data-contract-and-campaign-matching-for-the-pacing-join) | ADR: actuals data contract and campaign matching for the Pacing join | documentation | P1 High | M2 | M | Ian | Backlog |
| [GL-09](#gl-09--actuals-feed-daily-platform-actuals-endpoint-per-analysis) | Actuals feed: daily platform actuals endpoint per analysis | feature | P1 High | M2 | L | Jerome | Backlog |
| [GL-10](#gl-10--campaign-matching-plan-names-to-warehouse-names-unmatched-raises-a-finding) | Campaign matching: plan names to warehouse names, unmatched raises a finding | feature | P1 High | M2 | M | Ian | Backlog |
| [GL-11](#gl-11--join-actuals-into-pacing-html-and-persist-the-joined-snapshot) | Join actuals into pacing.html and persist the joined snapshot | feature | P1 High | M2 | M | Juan | Backlog |
| [GL-12](#gl-12--pacing-stage-verdict-in-the-flowchart) | Pacing stage verdict in the flowchart | feature | P1 High | M2 | M | Charles | Backlog |
| [GL-13](#gl-13--pacing-variance-findings-with-rulebook-tolerances) | Pacing variance findings with rulebook tolerances | feature | P2 Medium | M2 | S | Charles | Backlog |
| [GL-24](#gl-24--ingest-loaders-must-fail-the-run-when-bigquery-loads-fail) | Ingest loaders must fail the run when BigQuery loads fail | bug | P1 High | M2 | S | Christian | Backlog |
| [GL-25](#gl-25--derive-the-dts-backfill-end-date-instead-of-hardcoding-it) | Derive the DTS backfill end date instead of hardcoding it | bug | P2 Medium | M2 | XS | Christian | Backlog |
| [GL-14](#gl-14--conversations-receiver-transcripts-as-citable-sources) | Conversations receiver: transcripts as citable sources | feature | P1 High | M3 | L | Ian | Backlog |
| [GL-15](#gl-15--per-platform-required-vs-missing-asset-checklist) | Per-platform required-vs-missing asset checklist | feature | P1 High | M3 | L | Charles | Backlog |
| [GL-16](#gl-16--finding-to-source-deep-links-in-the-tab) | Finding-to-source deep links in the tab | enhancement | P1 High | M3 | M | Juan | Backlog |
| [GL-17](#gl-17--scope-utm-checks-to-ad-destinations) | Scope UTM checks to ad destinations | bug | P2 Medium | M3 | S | Jerome | Backlog |
| [GL-18](#gl-18--referenced-files-matching-kill-the-false-unreferenced-asset-flags) | Referenced-files matching: kill the false 'unreferenced asset' flags | bug | P2 Medium | M3 | S | Jerome | Backlog |
| [GL-26](#gl-26--add-guards-to-the-production-table-truncate-scripts) | Add guards to the production table truncate scripts | bug | P2 Medium | M3 | XS | Christian | Backlog |
| [GL-19](#gl-19--second-pilot-a-different-agency-s-format-end-to-end) | Second pilot: a different agency's format end to end | testing | P1 High | M4 | L | Charles | Backlog |
| [GL-20](#gl-20--backfill-analyses-for-in-flight-campaigns-and-triage-the-findings) | Backfill analyses for in-flight campaigns and triage the findings | task | P2 Medium | M4 | L | Charles | Backlog |
| [GL-21](#gl-21--greenlight-status-chip-on-central-rows) | Greenlight status chip on Central rows | enhancement | P3 Low | M4 | M | Juan | Backlog |
| [GL-22](#gl-22--docs-agents-md-grid-core-readme-md-and-expected-readme-md-reflect-the-shipped-feature) | Docs: AGENTS.md, grid-core/README.md and expected/README.md reflect the shipped feature | documentation | P2 Medium | M4 | S | Christian | Backlog |

---

## M1 Greenlight Hardening (due 2026-08-11)

### GL-01 — Move Greenlight extraction to a background job

`refactor` · `P0 Critical` · `area:grid-core` · `epic:greenlight-hardening` · est **M** · owner **Ian** · board status **Backlog**

The extraction run executes ~320s synchronously inside the HTTP request (grid-core/expected/routes.js:89, marked TODO(background-job)). The deploy works around it with --timeout 600 on Cloud Run, so a slow model call or a bigger dump kills the run at the timeout and the buyer sees a dead request. Runs must start, detach, and be pollable.

#### Acceptance criteria

- [ ] POST run returns immediately with a runId and status 'running'
- [ ] The UI polls run status and renders progress; a page reload re-attaches to the running run
- [ ] A run that dies (crash, restart) is marked failed, never left 'running' forever
- [ ] The --timeout 600 crutch note in expected/README.md is removed once landed
- [ ] Re-run guard (content-hash unchanged check) still works
- [ ] Regression gate still passes end to end

#### Notes

The GCS mirror in store.js already makes run artifacts durable, so the job can write progress there. Keep the no-Express convention: server.js is plain node:http.

**Suggested branch:** `feat/greenlight-background-run`

### GL-02 — Purge committed client raw material and fix the ignore policy

`bug` · `P0 Critical` · `area:ops-scripts` · `epic:greenlight-hardening` · est **M** · owner **Ian** · board status **Backlog**

61MB of Schneider NEL raw client material is now tracked under grid-core/files/ (38 files, including a 49MB campaign PPTX and a 10MB creative workbook) while expected/README.md calls that directory 'local-only' and it is dockerignored. Separately, .gitignore:21 implements 'raw client exports, never committed' as clients/*/data/* only, so clients/*/raw_files/ and 'raw files/' bypass it; clients/client_resetdata/data/resetdata_reddit_febmar26.csv is tracked despite being matched by the rule; clients/client_vmch/VMCH_Campaign_Analysis.html (266KB of real client data) is dead code.

#### Acceptance criteria

- [ ] grid-core/files/ is gitignored and its contents removed from tracking (git rm --cached); the regression dump stays on disk locally and in gs://bidbrain-campaign-dumps
- [ ] test_regression.js documents where a fresh clone obtains the NEL dump
- [ ] The ignore rule covers clients/*/raw_files/, clients/*/raw files/ and grid-core/files/
- [ ] Existing tracked raw exports are removed or given explicit !exceptions with a reason
- [ ] VMCH_Campaign_Analysis.html is deleted (its data was already ported into the dashboard)
- [ ] A decision is recorded on whether committing client media plans is ever acceptable

#### Notes

History is still shallow enough that removal is real: main history remains squash-merged WIP commits. Do this before the repo accumulates more; a 49MB PPTX in git also slows every clone.

**Suggested branch:** `fix/purge-client-raw-material`

### GL-03 — Enable Greenlight on the live Grid (flag, secret, bucket, smoke run)

`task` · `P1 High` · `area:grid-core` · `epic:greenlight-hardening` · est **S** · owner **Ian** · board status **Backlog**

Everything ships flag-off. Turning it on for real means: GREENLIGHT_ENABLED=true on central-grid, ANTHROPIC_API_KEY wired from Secret Manager (v2+ of the secret is the funded key; v1 is the old unfunded org key), GREENLIGHT_BUCKET pointed at gs://bidbrain-campaign-dumps, and a witnessed smoke run.

#### Acceptance criteria

- [ ] gcloud run services update central-grid applies the flag, the secret (anthropic-api-key:latest resolving to the funded key) and the bucket env
- [ ] The nav button appears at /d/central/ for super-admin and the /enabled probe answers true
- [ ] A full upload-run-review cycle on the NEL analysis completes on the live service
- [ ] The run library survives a forced cold start (GCS mirror proves itself in prod)
- [ ] Cost of the smoke run is noted (~USD 1 expected per run)

#### Notes

Blocked by GL-01 if the live run exceeds the request timeout; sequence after it or accept the --timeout 600 crutch for the first smoke.

**Depends on:** GL-01

**Suggested branch:** `task/greenlight-enable-prod`

### GL-04 — CI workflow: run the test suites; regression gate on demand

`testing` · `P1 High` · `area:grid-core` · `epic:greenlight-hardening` · est **M** · owner **Jerome** · board status **Backlog**

No CI exists (no .github/ anywhere). grid-core has 8 npm-test suites nothing runs, pacing/pacing.test.js (21 passing) is orphaned outside the chain, and Greenlight added test_regression.js which needs a running server plus a funded API key (~USD 1/run) so it cannot run on every push. Split accordingly: free deterministic suites on every push, the regression gate as a manually-triggered workflow with the key as a repo secret.

#### Acceptance criteria

- [ ] .github/workflows/ci.yml runs npm ci + npm test in grid-core on push and PR
- [ ] npm test passes from a clean checkout (better-sqlite3 native build included)
- [ ] pacing.test.js joins the npm test chain; a decision is recorded for src/_retired/derive.test.js
- [ ] A separate workflow_dispatch job runs test_regression.js with ANTHROPIC_API_KEY from repo secrets
- [ ] A deliberately broken assertion fails the push workflow, verified once then reverted

#### Notes

This changes nothing about how anyone pushes: workflows report, they do not block, unless later wired as required checks under branch protection (still parked).

**Suggested branch:** `ci/grid-core-workflows`

### GL-05 — Close the drift inside expected/README.md

`documentation` · `P2 Medium` · `area:docs` · `epic:greenlight-hardening` · est **XS** · owner **Christian** · board status **Backlog**

The README disagrees with itself: the top section says storage is ephemeral on /tmp with a TODO(GCS), while the Analyses section documents the GCS mirror as implemented (it is: store.js). Line 139 says the upload zone accepts metadata only, while the storage section documents per-file base64 staging at 15MB. Stale instructions are worse than none.

#### Acceptance criteria

- [ ] One pass over expected/README.md removes every statement contradicted by the code
- [ ] The TODO(GCS) block is deleted or rewritten to describe the shipped mirror
- [ ] The upload description matches routes.js reality
- [ ] Remaining genuine TODOs (background job until GL-01 lands) stay

**Suggested branch:** `docs/expected-readme-drift`

### GL-06 — Wire dashboard JS validation into the sanity gate

`testing` · `P2 Medium` · `area:ops-scripts` · `epic:greenlight-hardening` · est **S** · owner **Juan** · board status **Backlog**

Invoke-SanityGate (scripts/merge-branches.ps1:208) checks secret filenames, conflict markers, Python syntax and JSON validity but no JavaScript, though ~29 dashboard HTML files of inline Chart.js are most of the product surface. scripts/_validate_dash_js.py already exists, unwired. A dashboard syntax error lands and deploys today.

#### Acceptance criteria

- [ ] The gate runs _validate_dash_js.py on every changed clients/*/dash/*.html
- [ ] A deliberate syntax error fails the gate, verified then reverted
- [ ] scripts/README.md and the AGENTS.md gate description are updated in the same change

**Suggested branch:** `gate/validate-dash-js`

### GL-07 — Surface run cost and duration in the run history

`enhancement` · `P3 Low` · `area:grid-core` · `epic:greenlight-hardening` · est **XS** · owner **Juan** · board status **Backlog**

Each run costs about a dollar and takes 5-7 minutes. The re-run guard already prevents accidental identical re-runs; showing cost and duration per run in the analysis history keeps usage honest as more buyers get access.

#### Acceptance criteria

- [ ] Each run row shows wall-clock duration and token usage or estimated cost
- [ ] Totals per analysis are visible
- [ ] No figure is invented: if the API response lacks usage data, show duration only

**Suggested branch:** `feat/greenlight-run-cost`

### GL-23 — Guard the HubSpot deals truncate against an empty response

`bug` · `P1 High` · `area:ingest` · `epic:adjacent-debt` · est **XS** · owner **Juan** · board status **Backlog**

ingest/windsor_data_pull/hubspot/hubspot_loader.py loads deals with WRITE_TRUNCATE and no emptiness guard: contacts aborts on empty (:204) and owners is guarded (:218), but a transient Windsor response with zero deals truncates raw_windsor.hubspot_deals to nothing, silently breaking Reset Data's deal views until the next good run. One `if deals:` fixes it.

#### Acceptance criteria

- [ ] An empty deals response aborts with a non-zero exit instead of truncating
- [ ] The guard matches the contacts pattern already in the file
- [ ] A comment records why, mirroring the contacts guard's comment

**Suggested branch:** `fix/hubspot-deals-guard`

### GL-27 — Fix the dead clone URL and stale client list in ONBOARDING.md

`documentation` · `P3 Low` · `area:docs` · `epic:adjacent-debt` · est **XS** · owner **Christian** · board status **Backlog**

ONBOARDING.md:25 still tells a new developer to clone github.com/Bidbrain/bidbrain-analytics.git, which is dead (404); AGENTS.md records it as dead and start_day.ps1 removes the remote if found. The doc also lists 10 client keys against 15 client folders. A new hire fails at step one.

#### Acceptance criteria

- [ ] The clone URL points at the live remote
- [ ] The client-keys list is reconciled with the actual folders
- [ ] One pass for other stale facts in the same file

**Suggested branch:** `docs/fix-onboarding`

### GL-28 — Finish the client-material upload path (byte staging into the analysis dump)

`feature` · `P1 High` · `area:grid-core` · `epic:greenlight-hardening` · est **M** · owner **Charles** · board status **In Progress**

The deployed image has no prestage (grid-core/files is dockerignored), so upload is the ONLY way client material reaches a production analysis - this path gates everything else. It is mid-build on a dev branch now. Current shape: uploads stage per file as base64 JSON, capped at 15MB/file by the platform proxy (~16MB POST cap), bigger files skipped with a note. Finish and harden it: bytes for every accepted type land in the analysis's isolated dump, oversize files have a documented route, and uploads are mirrored to GCS so a cold start cannot lose a buyer's dump.

#### Acceptance criteria

- [ ] Every accepted file type uploads BYTES (not metadata only) into the analysis's isolated dump
- [ ] Files over the 15MB proxy cap are skipped with a visible note and a documented alternative route (e.g. a direct drop into the gs://bidbrain-campaign-dumps path)
- [ ] Per-file upload state (pending / done / failed) renders in the tab; a failed file is retryable without re-sending the rest
- [ ] Uploads mirror to GCS on write (store.js pattern) and survive a forced cold start
- [ ] Duplicate uploads dedupe by sha256, consistent with the preprocess manifest
- [ ] expected/README.md storage section matches the final behaviour (coordinate with GL-05)

#### Notes

IN PROGRESS as of 2026-08-05 - confirm the current state with Charles before scoping the remainder; this ticket captures the finish line, not a restart. The 49MB NEL campaign PPTX is a real oversize example: without the alternative route, big decks simply cannot reach a production analysis.

**Suggested branch:** `feat/greenlight-upload-staging`

---

## M2 Actual Side - Pacing vs API Data (due 2026-08-25)

### GL-08 — ADR: actuals data contract and campaign matching for the Pacing join

`documentation` · `P1 High` · `area:docs` · `epic:actual-side` · est **M** · owner **Ian** · board status **Backlog**

Before code: decide where daily actuals come from per platform (raw_windsor.*, raw_snowflake.*, raw_google_ads.* — sources differ per client), the join grain ({date, campaign, spend, impressions, clicks} per build_expected.js's documented hook), currency handling, and how plan campaign names match warehouse names. Record it as an ADR in the style of grid-core/docs/.

#### Acceptance criteria

- [ ] Names the source table per platform and per client family
- [ ] Defines the matching rule: brief-number prefixes stripped once, then the Central match.js semantics, never raw-name equality
- [ ] Defines currency treatment: plan currency vs source currency, and stop-on-mismatch like the sync
- [ ] Defines what happens to unmatched delivery and unmatched plan campaigns (findings, never silence)
- [ ] States whether the join is computed at run time or on a schedule

#### Notes

AGENTS.md rule that governs the whole design: campaign names are NOT stable keys — Transmission prefixes brief numbers onto names mid-flight, and fixed-offset or exact-name matching has silently dropped delivery twice.

**Suggested branch:** `docs/adr-actuals-contract`

### GL-09 — Actuals feed: daily platform actuals endpoint per analysis

`feature` · `P1 High` · `area:grid-core` · `epic:actual-side` · est **L** · owner **Jerome** · board status **Backlog**

GET /api/greenlight/:analysisId/actuals returning daily {date, campaign, spend, impressions, clicks} rows for the analysis's campaigns, read from BigQuery via the client library (central_sync.py pattern — there is no bq CLI in the image). This is the data the meeting wants compared against the pacing plan.

#### Acceptance criteria

- [ ] Endpoint returns daily rows across the plan's flight window per matched campaign
- [ ] BigQuery access uses the client library, never the bq CLI
- [ ] Source per platform follows the GL-08 ADR
- [ ] Currency is reported with the rows; a mismatch with the plan currency is an error, not a silent conversion
- [ ] A campaign with no delivery yet returns empty rows, distinguished from a match failure
- [ ] Response is cacheable; repeated polls do not re-scan BigQuery unbounded

**Depends on:** GL-08

**Suggested branch:** `feat/greenlight-actuals-feed`

### GL-10 — Campaign matching: plan names to warehouse names, unmatched raises a finding

`feature` · `P1 High` · `area:grid-core` · `epic:actual-side` · est **M** · owner **Ian** · board status **Backlog**

Match the extracted plan campaigns to warehouse campaign names using normalised forms (brief prefix stripped once) and the existing match.js semantics. Any delivery in the advertiser's account that matches no plan campaign — and any plan campaign that matches no delivery after go-live — becomes a finding. This is the meeting's tracking-gap problem ('live but missing from the dashboard') made structural.

#### Acceptance criteria

- [ ] Matching reuses src/central/match.js semantics; no second matcher is written
- [ ] Both name forms of a mid-flight renamed campaign fold to one match
- [ ] Unmatched warehouse delivery raises a finding naming the campaigns and their spend
- [ ] A plan campaign with no delivery after flight start raises a finding
- [ ] The check scopes on the advertiser/account total so a parse regression cannot hide (never circular)
- [ ] Unit-tested against renamed-campaign fixtures

#### Notes

The mongodb scope-pin check that just landed in status_dashboard/job/main.py is the same idea done right (non-circular by design) — crib its approach.

**Depends on:** GL-08

**Suggested branch:** `feat/greenlight-campaign-matching`

### GL-11 — Join actuals into pacing.html and persist the joined snapshot

`feature` · `P1 High` · `area:grid-core` · `epic:actual-side` · est **M** · owner **Juan** · board status **Backlog**

build_expected.js already ships the hook: window.BB_ACTUALS / joinActuals(rows), with actuals drawn as thicker lines per campaign. Wire the Grid tab to fetch the actuals feed and join it, and persist the joined snapshot into the run's artifacts so a report is reproducible after the fact.

#### Acceptance criteria

- [ ] Opening a run's pacing view joins live actuals via the existing hook, no rebuild of pacing.html required
- [ ] The joined snapshot is persisted with the run artifacts (and mirrored to GCS)
- [ ] Expected vs actual renders legibly for the NEL pilot's 4 campaigns
- [ ] A campaign with no actuals renders its expected line with an explicit 'no delivery yet' marker, never a fake zero line

#### Notes

Project rule: no figure on screen without a source; remove the element rather than render a placeholder.

**Depends on:** GL-09,GL-10

**Suggested branch:** `feat/greenlight-join-actuals`

### GL-12 — Pacing stage verdict in the flowchart

`feature` · `P1 High` · `area:grid-core` · `epic:actual-side` · est **M** · owner **Charles** · board status **Backlog**

The sixth stage (Pacing) currently reflects expected-side data only. With actuals joined, compute a real verdict per campaign: cumulative actual vs cumulative expected as of today, classified on/behind/ahead with the thresholds in rulebook.json, and roll it into the stage card.

#### Acceptance criteria

- [ ] Per-campaign pacing status: on-track / behind / ahead with the deviation shown
- [ ] Stage card aggregates worst-first and names the campaigns driving it
- [ ] Thresholds live in rulebook.json, not in code
- [ ] A campaign missing goals or dates stays an exception, never a fake verdict
- [ ] Verdicts carry the as-of date of the actuals they used

**Depends on:** GL-11

**Suggested branch:** `feat/greenlight-pacing-verdict`

### GL-13 — Pacing variance findings with rulebook tolerances

`feature` · `P2 Medium` · `area:grid-core` · `epic:actual-side` · est **S** · owner **Charles** · board status **Backlog**

When a campaign's pacing deviation crosses the rulebook tolerance, emit a finding (origin 'code') so it appears in report.md and can carry a chase draft — over/underspend becomes a flagged, citable event rather than a chart the buyer has to notice.

#### Acceptance criteria

- [ ] A tolerance breach emits a finding naming campaign, metric, expected, actual and deviation
- [ ] Tolerances configurable in rulebook.json
- [ ] Findings deduplicate across runs (same breach does not stack per run)
- [ ] Chase-draft generation picks pacing findings up like any other finding

**Depends on:** GL-12

**Suggested branch:** `feat/greenlight-pacing-findings`

### GL-24 — Ingest loaders must fail the run when BigQuery loads fail

`bug` · `P1 High` · `area:ingest` · `epic:adjacent-debt` · est **S** · owner **Christian** · board status **Backlog**

meta_loader.py:529-531 catches BigQuery load failures, logs, and continues — a scheduled run where every load failed still exits 0 and reports success, so the Pacing actuals would silently go stale. The same shape was copied into the sibling Windsor loaders.

#### Acceptance criteria

- [ ] A failed BQ load marks the run failed (non-zero exit) after the loop completes remaining chunks
- [ ] The same fix is applied to every sibling loader with the copied pattern
- [ ] Cloud Run job executions show red on load failure (verify once)
- [ ] Per-account skip behaviour (AccountUnavailableError) is unchanged

#### Notes

Matters more once Pacing depends on these tables: silent staleness under an actuals join is exactly the failure AGENTS.md warns about.

**Suggested branch:** `fix/loader-exit-codes`

### GL-25 — Derive the DTS backfill end date instead of hardcoding it

`bug` · `P2 Medium` · `area:ingest` · `epic:adjacent-debt` · est **XS** · owner **Christian** · board status **Backlog**

ingest/dts_data_pull/backfill.py:40 pins END_DATE = date(2026, 6, 5), so the GA4 backfill has covered nothing after 2026-06-04 for two months. Derive from date.today() (end-exclusive, DTS rejects today/future).

#### Acceptance criteria

- [ ] END_DATE derives from today
- [ ] The end-exclusive comment stays accurate
- [ ] A catch-up run is executed for the gap once merged

**Suggested branch:** `fix/dts-backfill-end-date`

---

## M3 Inputs and Checklist (due 2026-09-08)

### GL-14 — Conversations receiver: transcripts as citable sources

`feature` · `P1 High` · `area:grid-core` · `epic:inputs-checklist` · est **L** · owner **Ian** · board status **Backlog**

The meeting's receiver should accept 'all raw campaign files AND conversations (from Teams, Fathom, etc.)'. Today the pipeline is files-only. Accept transcript text (paste or file upload) into the analysis dump, and let the extractor treat it as a source with citations pointing at the transcript and its line/timestamp — so a decision made in a call ('client agreed to move flight end to Aug 22') can resolve a conflict with a recorded rationale.

#### Acceptance criteria

- [ ] A transcript (pasted text or .txt/.md/.vtt upload) lands in the analysis dump like any file
- [ ] preprocess.js inventories it; extract.js can cite it as file + line/timestamp
- [ ] A value resolved by a conversation carries that citation in plan.json
- [ ] Conflicting sources (sheet says X, call says Y) keep both candidates with the resolution rationale, per the existing null-never-guess rule
- [ ] The regression gate gains a transcript fixture exercising a conversation-resolved value

#### Notes

The extraction schema already carries candidates + resolution_rationale on date fields — extend the same shape rather than inventing a parallel one.

**Suggested branch:** `feat/greenlight-conversations`

### GL-15 — Per-platform required-vs-missing asset checklist

`feature` · `P1 High` · `area:grid-core` · `epic:inputs-checklist` · est **L** · owner **Charles** · board status **Backlog**

The meeting's UI concept: under the flowchart, one checklist per platform showing required vs present. Requirements live in rulebook.json per platform (LinkedIn: lead-gen form sheet, insight tag implementation, statics at 1200x1200; TTD: creative bulk-upload sheet, statics at 300x600 + 320x100 per geo; UTM sheet; approvals recorded), evaluated against the manifest's code-measured media metadata and the extraction.

#### Acceptance criteria

- [ ] Requirements are data in rulebook.json keyed by platform, not code
- [ ] Each platform on the plan renders required vs present vs missing, with the evidencing file linked
- [ ] Image dimensions come from the manifest's code-measured metadata, not from filenames
- [ ] A platform on the plan with zero materials renders as missing-everything, not absent
- [ ] Missing items feed findings so they surface in report.md and chase drafts
- [ ] The NEL dump renders a correct checklist for LinkedIn and TTD (known ground truth)

#### Notes

The PlatformChecklist sheet in the workbook is the starting requirements matrix — lift it into rulebook entries with the media team's corrections.

**Suggested branch:** `feat/greenlight-platform-checklist`

### GL-16 — Finding-to-source deep links in the tab

`enhancement` · `P1 High` · `area:grid-core` · `epic:inputs-checklist` · est **M** · owner **Juan** · board status **Backlog**

The meeting's key feature: 'each flag must link directly to its source file/conversation for context.' greenlight.js already renders each finding's source as text (line ~475). Make it a link: clicking opens the cited file from the analysis dump (download or inline preview) positioned at the cited sheet/row where feasible, and transcript citations jump to the line.

#### Acceptance criteria

- [ ] Every finding's citation is clickable
- [ ] Cited files open from the analysis dump (inline preview for images/PDF/text, download otherwise)
- [ ] Sheet/row citations are shown with the preview so the reader can locate the cell
- [ ] Transcript citations open the transcript at the cited line
- [ ] A citation whose file is missing from the dump says so rather than 404ing silently

**Depends on:** GL-14

**Suggested branch:** `feat/greenlight-source-links`

### GL-17 — Scope UTM checks to ad destinations

`bug` · `P2 Medium` · `area:grid-core` · `epic:inputs-checklist` · est **S** · owner **Jerome** · board status **Backlog**

Known tuning item from expected/README.md: the UTM required-param check fires on reference URLs (SharePoint links, privacy pages) where UTMs do not belong, producing noise findings that erode trust in the audit.

#### Acceptance criteria

- [ ] The rulebook check applies only to URLs classified as ad destinations
- [ ] Classification rule lives in rulebook.json and is explainable per URL
- [ ] The NEL dump produces zero UTM false positives while keeping the true ones
- [ ] Regression gate updated accordingly

**Suggested branch:** `fix/utm-scope`

### GL-18 — Referenced-files matching: kill the false 'unreferenced asset' flags

`bug` · `P2 Medium` · `area:grid-core` · `epic:inputs-checklist` · est **S** · owner **Jerome** · board status **Backlog**

Known tuning item: documents cite assets by internal names (e.g. DCFCREVL001EN.pdf) that do not match physical file names, so genuinely-used assets get flagged unreferenced. Add tolerant matching (normalised names, stems, sha-duplicate awareness) before flagging.

#### Acceptance criteria

- [ ] Cited-name vs physical-name matching tolerates renames, copies and case/underscore drift
- [ ] The extractor's own mismatch flag and the validator's unreferenced check agree
- [ ] The NEL dump's known false positives disappear; true orphans still flag
- [ ] Regression gate updated

**Suggested branch:** `fix/referenced-files-matching`

### GL-26 — Add guards to the production table truncate scripts

`bug` · `P2 Medium` · `area:ingest` · `epic:adjacent-debt` · est **XS** · owner **Christian** · board status **Backlog**

ingest/windsor_data_pull/{ga4,google_ads,linkedin,reddit}/truncate_*.py each TRUNCATE a production BigQuery table at import time with no confirmation, no --yes flag, no dry-run. One stray execution wipes a raw table.

#### Acceptance criteria

- [ ] Each script requires an explicit --yes (or equivalent) and prints the target table first
- [ ] Running without the flag performs nothing
- [ ] The guard pattern is identical across all four

**Suggested branch:** `fix/truncate-guards`

---

## M4 Rollout and Docs (due 2026-09-22)

### GL-19 — Second pilot: a different agency's format end to end

`testing` · `P1 High` · `area:grid-core` · `epic:rollout` · est **L** · owner **Charles** · board status **Backlog**

The regression gate proves Schneider NEL (Transmission's format). Client-agnosticism is the design claim — prove it on a second real campaign from a different agency/format family (e.g. a 100-Digital client like Reset Data, or Cloudflare's cover-sheet workbooks), fix what breaks, and extend the gate to two dumps.

#### Acceptance criteria

- [ ] A second real campaign dump runs end to end: extraction, findings, pacing plan, flowchart, chase drafts
- [ ] Format gaps found become rulebook/prompt fixes, not client-named code (grep proves no client names in expected/)
- [ ] test_regression.js gains the second dump with its own expected keys
- [ ] Both gates green in the same run

**Depends on:** GL-03

**Suggested branch:** `test/second-pilot`

### GL-20 — Backfill analyses for in-flight campaigns and triage the findings

`task` · `P2 Medium` · `area:grid-core` · `epic:rollout` · est **L** · owner **Charles** · board status **Backlog**

Run an analysis for each in-flight campaign where the file dump can be assembled, then triage: real issues become chase messages or fixes, false positives become rulebook tuning. This is the rollout moment where the tool starts paying rent — and where false greens must be treated as release blockers.

#### Acceptance criteria

- [ ] Every in-flight campaign with an assemblable dump has an analysis
- [ ] Findings triaged with the media team; each is actioned, chased or tuned
- [ ] Recurring false positives become rulebook changes with the reason recorded
- [ ] Campaigns whose dumps cannot be assembled are listed with what is missing
- [ ] A false green found in triage blocks wider rollout until fixed

**Depends on:** GL-19

**Suggested branch:** `task/greenlight-backfill`

### GL-21 — Greenlight status chip on Central rows

`enhancement` · `P3 Low` · `area:grid-core` · `epic:rollout` · est **M** · owner **Juan** · board status **Backlog**

Light linkage, not a bridge: tag an analysis with the Central campaign id(s) it covers, and show a small Greenlight readiness chip on the Central table row that deep-links to the analysis. No writes from Greenlight into Central — display only.

#### Acceptance criteria

- [ ] An analysis can be associated with Central campaign id(s)
- [ ] Central rows with an analysis show a readiness chip linking to the Greenlight tab
- [ ] No Greenlight code path writes to the campaigns table
- [ ] Unlinked analyses and unlinked campaigns are both fine (no forced pairing)

#### Notes

Committing extracted plan values into Central (the old plan-reader v2 basis-gate design) stays out of scope — revisit only after rollout proves the extraction trustworthy.

**Suggested branch:** `feat/greenlight-central-chip`

### GL-22 — Docs: AGENTS.md, grid-core/README.md and expected/README.md reflect the shipped feature

`documentation` · `P2 Medium` · `area:docs` · `epic:rollout` · est **S** · owner **Christian** · board status **Backlog**

The repo's definition-of-done rule: after any change, update whatever it made stale, in the same change. The Greenlight epic makes several docs stale at once, so it gets an explicit closing ticket.

#### Acceptance criteria

- [ ] AGENTS.md's grid-core section names the Greenlight tab, its flag and its deploy nuances
- [ ] grid-core/README.md documents the tab, the pipeline and the API surface
- [ ] expected/README.md matches the final state (post GL-01/GL-05)
- [ ] No narrative summary .md about the work itself is created, per the repo rule

**Depends on:** GL-20

**Suggested branch:** `docs/greenlight-docs`

