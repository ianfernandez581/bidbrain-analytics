# expected - Greenlight, The Grid's plan-side tab (the Expected side)

Turns a media buyer's campaign file dump into the expected-side baseline the
Actual side compares against. Client-agnostic: no client names, job numbers,
or plan figures live in code - everything comes from extraction at run time.

## Greenlight in The Grid (the production surface)

Greenlight is a nav tab in the-grid.html (after Executive, NEW badge), served
by grid-core/server.js which mounts routes.js at `/api/greenlight/*`. The UI
module is `src/greenlight/greenlight.js` (Brain-style classic script rendering
into #view-greenlight on the Grid's own theme vars; violet = AI-authored).

- **Feature flag:** `GREENLIGHT_ENABLED=true` exposes the API and reveals the
  nav button (the page probes `GET /api/greenlight/enabled`). Default OFF:
  the probe answers false, every other greenlight route 404s, no tab in the
  nav. Flip it on the live service only after review:
  `gcloud run services update central-grid --region australia-southeast1
  --update-env-vars GREENLIGHT_ENABLED=true --timeout 600`
  (--timeout 600: the extraction call runs ~320s synchronously in the request;
  the default 300s would cut it off. TODO: move to a background job.)
- **Auth:** the Grid's own model - platform proxy (super-admin) + Cloud Run
  IAM. Zero auth code in this unit, same as every other tab.
- **API key:** production reads ANTHROPIC_API_KEY from Secret Manager
  (`--update-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest`, wired in
  deploy_grid.ps1; v2+ of that secret is the funded key, v1 is the old
  unfunded org key). Local dev reads gitignored grid-core/.env. Never a .env
  in production.
- **Provider is switchable per wire format** (`GREENLIGHT_PROVIDER=groq|anthropic`,
  inferred from the base URL when unset). extract.js prefers
  `GREENLIGHT_API_KEY`/`GREENLIGHT_BASE_URL` over the `ANTHROPIC_*` pair, so THIS
  stage can bill a different provider while Brain/plan-reader keep the Anthropic
  key. The SYSTEM prompt and SCHEMA are shared verbatim by both paths.
  - `anthropic` - the Anthropic SDK. Also serves **Anthropic-compatible**
    endpoints: Kimi (`https://api.kimi.com/coding` + `EXPECTED_MODEL=kimi-for-coding`,
    verified 2026-08-05 to enforce `output_config` json_schema, accept the
    fallback-beta shape, and map claude-* model names).
  - `groq` - OpenAI-compatible `/chat/completions` over plain `fetch` (Node 18+,
    no SDK, no new dependency). **Groq exposes no Anthropic endpoint** (verified
    2026-08-06: `/anthropic/v1/messages` 404s), so this is a different call
    shape, not a base-URL swap.
- **Groq specifics (verified 2026-08-06).** Only `openai/gpt-oss-120b` accepts
  `response_format` json_schema - `llama-3.3-70b-versatile` and `qwen/qwen3.6-27b`
  reject it outright. Every model caps at 131,072 tokens of **context**
  (prompt + completion); a full NEL dump is ~41K prompt tokens, so it fits.
  Two behaviours differ from Anthropic and are handled in `callGroq`:
  - **`max_completion_tokens` counts against the per-minute token budget**, not
    just the context window - Groq bills the RESERVATION, so an unused one is
    not free. Default `GREENLIGHT_MAX_OUTPUT` is 12000 (measured records run
    1,500-2,600) rather than the 64000 the Anthropic path asks for.
    **On a 413 the reservation auto-refits**: the error carries
    `Limit N, Requested M`, and since M is prompt + reservation the prompt is
    recoverable by subtraction - so the reservation shrinks to what the tier
    leaves room for and the request is retried immediately (a rejected request
    consumes no budget). This is what lets a small dump run on a small tier.
    It gives up only when the PROMPT alone leaves less than 1200 tokens of
    headroom, and then says so in those terms rather than repeating the raw 413.
  - **json_schema is validated AFTER generation, not enforced by constrained
    decoding.** The model can emit a stray shape and the request 400s with
    "Generated JSON does not match the expected schema" - measured 2 failures in
    3 otherwise-identical attempts. Those 400s are retried as model flakes; all
    other 4xx still fail immediately.
- **BLOCKER on the free (`on_demand`) Groq tier: 8,000 tokens/minute.** The TPM
  budget is checked as prompt + `max_completion_tokens` against a **single**
  request, and an oversized request is rejected outright (413) rather than
  queued - so no backoff can get around it. A full dump needs ~73K; the media
  plan alone is ~8.3K, over the whole per-minute budget by itself. Greenlight
  therefore cannot run a real campaign on the free tier: it needs Groq Dev Tier,
  or the Kimi/Anthropic path above.
- extract.js re-resolves EXPECTED_MODEL after its .env load; check_key.js probes
  whatever .env points at, on either wire format.
- **Storage:** uploads stage per file (base64 JSON, 15MB/file - the platform
  proxy caps forwarded POSTs ~16MB) into the analysis's own `files/` dir under
  GREENLIGHT_DUMPS_DIR, and each run archives to
  `analyses/<id>/runs/<runId>/` (out + results.json). On Cloud Run those point
  at /tmp (Dockerfile), which is wiped on every instance restart - the GCS
  mirror below is the durable copy. See "Analyses" for the full model.
- **Local prestage:** with no uploads staged, a run analyzes grid-core/files
  (dev convenience; that directory is dockerignored so the deployed image has
  no prestage - upload is the only path in).

## Pipeline (per run)

```
files dump -> preprocess.js -> extract.js (ONE model call) -> validate.js -> build_expected.js
              deterministic     provider-switchable, strict     rulebook.json    outputs in out/
                                schema (see Provider above)
```

1. `preprocess.js` - deterministic: workbook sheets to row-numbered CSV, media
   measured in code (image dims, mp4 duration via ISO-BMFF parse, pdf pages),
   sha256 dedupe, manifest.
   **Types whose CONTENT is read:** `.xlsx/.xlsm/.xls/.xlsb` (SheetJS reads the
   legacy binary formats through the same call - a media plan saved as `.xls`
   used to classify as 'other' and never be opened), `.csv/.tsv`, `.txt/.md`.
   **Not read:** pdf, pptx, docx and anything else - these are inventoried,
   labelled `CONTENT NOT EXTRACTED` (and marked `unread` + `converted: false`
   on the manifest entry) so the model treats them as WITHHELD rather than
   absent, and `validate.js` raises a `missing` finding naming them.
   **Nothing is dropped silently.** Every omission is recorded on the manifest
   entry and summarised in `manifest.intake` (`unread`, `parse_errors`,
   `truncated_sheets`, `sampled_csvs`, `content_read`, `duplicates`), and each
   becomes a finding. A CSV at or under `CSV_FULL_ROW_MAX` (200) data rows is
   bundled WHOLE - only bigger ones are head-sampled, because a media plan
   exported to CSV is 30-60 rows and the old flat 15-row cap silently dropped
   its budget lines.
   **Prompt-cost trims (all lossless, ~4% of the NEL bundle):** trailing empty
   cells are dropped per row; a **header-only** sheet (columns, zero data rows -
   e.g. the 8 unused format tabs in a Trade Desk bulk-upload workbook) is
   emitted as its header plus a `[TEMPLATE TAB]` note; a **static enumeration**
   (long, <=2 columns, >=40 rows - that workbook's 496-row IANA time-zone tab,
   its 105-row publisher list) is emitted as 5 rows plus a
   `[STATIC REFERENCE LIST: N rows]` note. The sheet still appears and is
   still citable; only its bulk is withheld.
2. `extract.js` - one structured-output call (model `claude-opus-5`, override
   with `EXPECTED_MODEL`). Every value cites file | sheet, row. Missing = null.
   Conflicts carry all candidates; a value is resolved ONLY when the documents
   themselves resolve it (rationale recorded), else stays null. Judgement
   findings + chase drafts are model work, tagged origin "model". The schema
   avoids type unions and nesting (the structured-outputs grammar compiler
   rejects union-heavy schemas): "" sentinels + numeric strings + pipe-
   delimited list entries, normalized back to nulls/numbers in code.
3. `validate.js` + `rulebook.json` - generic deterministic checks, identical
   for every client: budget sums, claimed-total labels, date math, items in
   flight, LinkedIn daily minimums, UTM consistency, empty approval fields,
   unreferenced media, duplicates, **files referenced but never supplied
   (`NOT SUPPLIED`)** and **files supplied but never read (`NOT READ`)**,
   **plus the intake checks** (files not read, workbooks that would not parse,
   truncated sheets, head-sampled CSVs) and **duplicate campaign names**.
   Findings tagged origin "code".
4. `build_expected.js` - plain-code outputs from out/plan.json + findings.json:
   daily = goal / days, cumulative = elapsed / total x goal (inclusive days,
   final day exact). Campaigns missing budget/goals/dates become exceptions,
   never zero rows. **Flight-window ladder (2026-08-05):** when the plan-level
   flight is unresolved it falls back deterministically - (a) min/max of the
   campaign lines' own dates, then (b) an endpoint whose candidate list holds
   exactly ONE distinct parseable date adopts it - and the assumption is
   APPENDED to findings.json as a `gap` ("ASSUMED FLIGHT") so it is loud in the
   UI/report. Only when both rungs fail does it exit 3 (any window would be an
   invention). Background: extraction is non-deterministic on borderline date
   conflicts (EcoConsult 2279: the same dump resolved 2026-05-01..2027-02-28
   on one run, null on another - media plan header vs 'Start-June' activation
   phrasing), so the builder must not turn that coin-flip into a dead run.

**Preflight - see the run before paying for it (2026-08-06).** Stage 0 is
deterministic, offline and takes well under a second, so the whole run can be
previewed for free. `POST /analyses/:id/preflight` runs `preprocess` ONLY (the
same call the real run makes, so it cannot drift) and returns: every file
tagged read / not read with the reason, the `intake` summary, any uploads that
never arrived, whether the dump is short, and a **token estimate**. The tab
opens this as a modal on "Run Analysis" - Start or Cancel - and the modal then
becomes the live progress view, so the intake breakdown stays on screen while
the stages tick over.

`tokens.js` produces the estimate and **self-calibrates**: every successful run
records its real chars-per-token (`plan.extractor.usage` + `bundle_chars`,
folded in by `routes.js`), and later estimates use the measured mean over the
last 20 runs instead of the 2.5 seed. Implausible ratios are rejected so one
bad observation cannot poison it, and the payload says whether a figure is
measured or estimated, with a +/-10% band once calibrated and +/-25% before.
Row-numbered CSV tokenizes much denser than prose, which is why the seed is 2.5
rather than the usual ~4 - the first real run replaces it anyway.
**No dollar figures anywhere:** Greenlight bills a Kimi subscription with no
per-call price this code can read, and an invented number is worse than none -
the same rule the extractor follows for plan values. Runs report duration
always, and tokens only when the provider reported them.

**Run state is durable and self-healing (2026-08-06).** A run outlives the
request that started it (the child is spawned, the response returns at once)
and can outlive the INSTANCE, so run state is written to
`analyses/<id>/live_run.json` on every stage transition plus a 15s heartbeat:

- **Per-analysis lock, not global.** A run on campaign A no longer blocks
  campaign B. `activeRunFor(id)` checks memory first, then the durable record.
- **A dead run expires.** No heartbeat for 4 minutes and the run reads as
  `error: this run stopped reporting`, instead of holding the lock forever.
  This is what wedged production: an instance recycled mid-run left
  `anyRunning()` permanently true and every subsequent run answered
  `409 a run is already in progress`, with nothing able to see or clear it.
- **Cross-instance polls work.** `GET /runs/:id` falls back to the durable
  record (`store.findLiveRun`), so a poll answered by a different instance
  finds the run rather than reporting a live one dead.
- **409s explain themselves** - which run, how long it has been going, which
  stage it is on.
- **`GET /analyses/:id` returns `active_run`**, so a reload or a second tab
  re-attaches to a run in flight instead of showing a Run button that 409s.
- **Per-run work dir** (`_work/<runId>`, removed when the run settles). One
  shared `out/` let concurrent runs interleave artifacts and archive each
  other's output; it was only the global lock that hid this. The legacy flat
  `/out/:file` route now serves the last completed run's archived copy.

**Run log - the pipeline is visible (2026-08-06).** Child stdout/stderr used to
be accumulated into a string and shown only if the run failed, so a healthy run
printed NOTHING to Cloud Run logs and a stuck one was undiagnosable. Every line
now goes to both the container log (prefixed `[greenlight][run <id>]`) and the
run record (last 400 lines), and the tab renders it live under **Run log** in
the progress modal.

**Retry the failed step (2026-08-05):** after every successful extraction its
artifacts are saved to `analyses/<id>/last_extract/` (`store.saveExtract`, GCS-
mirrored). `POST /analyses/:id/rebuild` restores that slot and reruns ONLY
`build_expected.js` - no model call, no cost - refused (409) when the files
changed since the extraction (hash check) so a stale plan can never be built
against new files. The UI offers "Retry failed step" on the error card when
the failed stage was `outputs`.

## Run

```
node grid-core/expected/server.js        # UI at http://localhost:8791 (EXPECTED_PORT)
node grid-core/expected/extract.js       # headless: [--files <dir>], writes out/
node grid-core/expected/build_expected.js
node grid-core/expected/check_key.js     # 1-token key probe (never prints the key)
npm --prefix grid-core run test:greenlight  # free deterministic suites (~2s, no key)
node grid-core/expected/test_regression.js  # gate vs the Schneider NEL dump (server must run)
```

Requires a key (env or gitignored `grid-core/.env`): `GREENLIGHT_API_KEY`,
`GROQ_API_KEY` or `ANTHROPIC_API_KEY`, resolved in that order. On the Anthropic
path a run costs about a dollar (one opus call over ~200KB of sheets) and takes
5-7 minutes.

## Analyses - the per-campaign workspace model (store.js)

An ANALYSIS is a named workspace for one campaign: its own isolated file dump
(persists across runs, so a buyer's incremental sends accumulate) plus a run
history. New analysis = fresh empty container - different campaigns' files
never mix. Names are optional; an auto-named analysis adopts the extracted
"<client> <job>" after its first successful run. Analyses can be renamed,
archived (soft, reversible) or deleted (hard, removes files + runs).

- Layout: `dumps/analyses/<id>/{analysis.json, files/**, runs/<runId>/{out/**, results.json}}`.
  Legacy flat `dumps/<runId>/` dirs are migrated on boot.
- **Re-run guard:** each run records a content hash of the file set; running
  again with identical files answers `{unchanged:true}` and the UI asks
  "Run anyway?" before spending another model call (force:true overrides).
- **GCS mirror** (GREENLIGHT_BUCKET, prod = gs://bidbrain-campaign-dumps):
  every write mirrors up (file uploads are AWAITED - the mirror is the only
  durable copy, so returning 200 first would lose a file to a crash in that
  window); boot pulls the small metadata index; artifacts come down lazily on
  first read. Local FS stays the source of truth for the instance - a mirror
  failure logs loudly, never breaks a request.
  Locally the mirror is off (env unset) and everything stays on disk.
- **Dump rehydration (`store.ensureFiles`, awaited by the detail, analyze and
  rebuild routes):** /tmp does not survive an instance restart, so without this
  an analysis comes back listing ZERO files and a re-run analyses only whatever
  is uploaded next - returning a clean, fully-cited baseline built from a
  fraction of the paperwork, with nothing looking wrong. `ensureFiles` lists
  `analyses/<id>/files/` in the bucket and pulls back anything missing, 8 at a
  time. Belt and braces: `analysis.json` records `files_expected` on every
  stage/remove, and a run whose local count is short is **refused with a 409**
  naming how many files are missing rather than analysing a partial dump.
- **Skipped uploads are recorded server-side** (`analysis.json.skipped`, via
  `POST /analyses/:id/files/skipped`). They used to live only in page memory
  and were cleared the moment the upload batch finished, so an oversize or
  failed file vanished from the dump with no explanation. The tab now shows a
  persistent warning that survives a reload, and staging the same name again
  clears it.
- **Identity guard** (extract.js, deterministic): 4-digit job prefixes in file
  names partition a dump. More than one distinct job = never blend: a blocker
  finding lists which files belong to which job, plan.campaigns keeps only the
  majority job, and the UI renders a red banner.
- `dumps/` and `out/` are gitignored (generated state; out/ was untracked on
  2026-08-05 - artifacts rebuild from any run).

## Outputs (out/)

- `plan.json` - the cited extraction record (the eyeball surface)
- `findings.json` - code + model findings merged, each tagged `origin`
- `daily_kpi.xlsx` / `daily_kpi.json` - one row per campaign per day, daily +
  cumulative spend/impressions/clicks; Info sheet carries goals + citations
- `pacing.html` - self-contained baseline TABLE page (chart removed
  2026-08-05): one row per plan line with full campaign name + source
  citation, window, goals, spend/day, expected-to-date; actuals join hook for
  the Actual side: `window.BB_ACTUALS` or `joinActuals(rows)` with daily
  `{date, campaign, spend}` rows (adds Actual-to-date + vs-expected columns)
- `flowchart.html` - stage readiness computed from findings (blocker = red)
- `report.md` / `chase_messages.md` / `messages.json` - findings report and
  model-drafted chase messages (a person reviews and sends)
- `manifest.json` - the preprocess inventory with code-measured media metadata
- `run.log` - timestamped trace of the whole run (both child processes' stdout,
  token usage, the outcome, and any ACTION NEEDED lines), archived with the run
  so a SUCCESSFUL run can be inspected too, not just a failed one. Live copy is
  on the run state as `log[]`; served at `.../out/run.log`.

## Partial runs - an incomplete dump is not a failed run

`build_expected.js` exits **3** when it refuses to invent a baseline (no
resolvable flight window, or no campaign line carrying budget + goals + dates).
That is a statement about the DUMP, not a crash: extraction and every
deterministic check have already succeeded by then.

So exit 3 is not a failure. The run finishes with `status: "done"` and
`run.partial: true`, archives normally, and carries:

- `run.blocked_reason` - why no baseline could be built,
- `needs_upload[]` - the `NOT SUPPLIED` / `NOT READ` findings, i.e. exactly the
  files the buyer still owes,
- the full `findings[]` and chase drafts, which are the useful half of the audit.

This is the intended working pattern: run on whatever has arrived, read the
gaps, upload the named files, re-run. Every other non-zero exit code is still a
hard failure.

## Tests

Two tiers, deliberately split by what they cost.

**Free, deterministic, every push** - no key, no server, no network, ~2s total.
`npm run test:greenlight` (also inside `npm test`):

```
expected/tokens.test.js     the pre-run estimate: seeded vs measured, the
                            self-calibration loop, and that an implausible
                            observation is rejected rather than averaged in
expected/intake.test.js     preprocess: which types are read, and that every
                            omission (unread type, parse error, truncation,
                            head-sampled CSV, duplicate) is recorded
expected/validate.test.js   every rulebook check FIRES on a real discrepancy
                            and does NOT fire on figures that reconcile
expected/build.test.js      spawns the real build_expected.js against fixture
                            plans: inclusive day counts, exact final
                            cumulatives, daily column summing to the goal,
                            exceptions, all three flight-ladder rungs, exit 3
```

**Paid, end to end, on demand** - the regression gate below (needs a server,
the private dump and a funded key).

## Regression gate

`test_regression.js` is the ONLY place client numbers live: a cold run on the
Schneider NEL dump (grid-core/files, local-only) must extract job 2053, AUD
35,000 split 8,000 TradeDesk + 6,000/14,000/7,000 LinkedIn, flight 2026-06-01
to 2026-08-22 (83 days), and the CODE validator must re-catch the
35,000-vs-27,000 build-sheet label and the 82-vs-83 day discrepancy.
Last green: 2026-08-04, 13/13.

## Known tuning items

- UTM required-param checks fire on reference URLs (SharePoint links, privacy
  pages) where UTMs do not belong - scope the rulebook check to ad
  destinations. (GL-17)
- `referenced_files` uses the names documents cite (e.g. `DCFCREVL001EN.pdf`),
  which may not match physical file names, so genuinely-used assets can be
  flagged unreferenced; the extractor flags the mismatch itself. (GL-18)
- **PDF text is still not extracted.** PDFs are inventoried, labelled
  `CONTENT NOT EXTRACTED` and raised as a `missing` finding, so a PDF brief can
  no longer pass unnoticed - but reading it is real work still to do. Same for
  `.pptx`/`.docx`.
- **Files over 15MB still cannot reach an analysis** (the platform proxy caps
  forwarded POSTs ~16MB). They are now recorded and shown persistently instead
  of vanishing, but the fix is a direct-to-GCS signed upload. (GL-28)
- Runs are still not resumable: if the instance dies mid-run the work is lost
  (the run is correctly reported dead, but nothing picks it back up). GL-01
  covers this; note its premise needs correcting - the run was always detached
  from the request, so the remaining work is resumability, not backgrounding.
