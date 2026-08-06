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
  proxy caps forwarded POSTs ~16MB; bigger files are skipped with a note) into
  GREENLIGHT_DUMPS_DIR/_staging, and each run archives to
  GREENLIGHT_DUMPS_DIR/<runId>/ (files + out + results.json). On Cloud Run
  both point at /tmp (Dockerfile) - ephemeral by design for now.
  TODO(GCS): gs://bidbrain-campaign-dumps via the src/brain/persist.js
  pattern so the runs library survives cold starts.
- **Local prestage:** with no uploads staged, a run analyzes grid-core/files
  (dev convenience; that directory is dockerignored so the deployed image has
  no prestage - upload is the only path in).

## Pipeline (per run)

```
files dump -> preprocess.js -> extract.js (ONE model call) -> validate.js -> build_expected.js
              deterministic     provider-switchable, strict     rulebook.json    outputs in out/
                                schema (see Provider above)
```

1. `preprocess.js` - deterministic: xlsx sheets to row-numbered CSV, media
   measured in code (image dims, mp4 duration via ISO-BMFF parse, pdf pages),
   sha256 dedupe, manifest. **Prompt-cost trims (all lossless, ~4% of the NEL
   bundle):** trailing empty cells are dropped per row; a **header-only** sheet
   (columns, zero data rows - e.g. the 8 unused format tabs in a Trade Desk
   bulk-upload workbook) is emitted as its header plus a `[TEMPLATE TAB]` note;
   a **static enumeration** (long, <=2 columns, >=40 rows - that workbook's
   496-row IANA time-zone tab, its 105-row publisher list) is emitted as 5 rows
   plus a `[STATIC REFERENCE LIST: N rows]` note. The sheet still appears and is
   still citable; only its bulk is withheld. Files with no converter (`.docx`,
   `.pptx`) are marked `converted: false` on the manifest so validate.js can
   raise them rather than letting an unread file pass as considered.
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
   (`NOT SUPPLIED`)** and **files supplied but never read (`NOT READ`)**.
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
  every write mirrors up best-effort; boot pulls the small metadata index;
  files/artifacts come down lazily on first read. Local FS stays the source
  of truth for the instance - a mirror failure logs loudly, never breaks a
  request. This is what makes the library survive Cloud Run cold starts.
  Locally the mirror is off (env unset) and everything stays on disk.
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
  destinations.
- `referenced_files` uses the names documents cite (e.g. `DCFCREVL001EN.pdf`),
  which may not match physical file names, so genuinely-used assets can be
  flagged unreferenced; the extractor flags the mismatch itself.
- Upload zone accepts file metadata only; byte upload into a per-run staging
  dir is the next milestone.
