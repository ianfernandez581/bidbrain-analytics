# Greenlight - what it does, what is broken, what to fix

Analysis of `grid-core/expected/` + `grid-core/src/greenlight/`, read against the code on
**2026-08-06**. Replaces the 2026-08-05 draft, which predates the Kimi switch, the `/rebuild`
path and the flight-window ladder.

**Status: the S1 correctness findings were fixed on 2026-08-06.** F1, F2, F3, F8, F10, F13 and
F16 are closed, F15 has a first suite (114 tests, ~2s, no key), and the daily/cumulative
inconsistency found while testing is fixed. There is now also a **free preflight** (`POST
/analyses/:id/preflight`) that previews a run before it costs anything: every file tagged read
or not read with the reason, plus a self-calibrating token estimate, shown as a modal that
becomes the live progress view. Section 3 marks each row. The run-engine findings (F4-F7) are
open and are still the next package. Fix detail lives in `expected/README.md`, not here - this
file stays the analysis.

Verified here: `npm run test:greenlight` 114/114 green, plus live smoke runs of every changed
route on the dev harness (upload, skip-record, simulated partial restore, 409 refusal, size
guards, preflight, calibration loop). **Not** verified: live Cloud Run settings (gcloud auth is
stale on this box), so deployment facts come from `deploy_grid.ps1` and `Dockerfile`, not from
the running service.

---

## In one minute

**What it is.** Every other Grid tab measures what *did* happen. Greenlight measures what
*should* happen: you drop a campaign's paperwork in, it reads the media plan, and it produces
the daily spend/impression targets the campaign is supposed to hit, plus a list of everything
missing or contradictory in the paperwork.

**Is it working?** Yes. The pipeline is well built and the core design is right.

**What is wrong.** Three things, all the same shape: **Greenlight sometimes runs on less than
you gave it, and never says so.**

1. Files you upload are **not restored** when the server restarts. The analysis comes back
   showing zero files, and a re-run quietly analyzes whatever is left.
2. Greenlight **only reads spreadsheets and CSVs**. PDFs, Word docs, decks and legacy `.xls`
   files are never opened - and it does not tell you.
3. Files over 15MB are **silently dropped**, and the warning that says so disappears from the
   screen a second after it appears.

In all three cases you get a clean, confident, fully-cited baseline built from part of the
paperwork. That is worse than an error, because nothing looks wrong.

**What to do first.** Two fixes, both contained: restore uploaded files from cloud storage
(W1), and make Greenlight read more file types and complain about the ones it cannot (W4.3).
Everything else can queue behind them.

---

## 1. What it does

You give it: a media plan, a brief, platform setup sheets, creative sheets, trackers, the
creative files themselves.

You get back:

| Output | Plain English |
|---|---|
| `daily_kpi.xlsx` / `.json` | the daily target: how much each campaign should spend and deliver, every day of the flight |
| `findings.json` / `report.md` | everything wrong or missing in the paperwork, ranked |
| `flowchart.html` | a six-stage readiness view; red means a blocker sits in that stage |
| `pacing.html` | the plan lines in a table, with the hook for joining real delivery later |
| `chase_messages.md` | drafted chase emails, one per person, for a human to review and send |
| `plan.json` | the raw extraction, where every single value cites the file, sheet and row it came from |

Nothing in the code knows about any specific client. Every number comes out of the documents at
run time. The only file with real client numbers in it is the regression test, on purpose.

## 2. How it works

```
your files -> preprocess -> extract -> validate -> build
              (code)        (AI)       (code)      (code)
```

**Preprocess** (`preprocess.js`) - no AI. Converts spreadsheets to numbered text rows so the AI
can cite "row 8" and you can go check it. Measures images, video length and PDF page counts in
code. Hashes every file so identical copies are only processed once.

**Extract** (`extract.js`) - one AI call, the only one. Reads the converted documents and pulls
out the plan: client, budget, flight dates, campaign lines, URLs, approvals. Rules it is held
to: cite everything, never guess, list conflicts instead of picking a winner, **do no
arithmetic**, and never mix two clients together.

**Validate** (`validate.js` + `rulebook.json`) - no AI. All the maths: do the budgets add up,
do impressions match budget and CPM, does the stated duration match the actual dates, are the
UTMs consistent, are approvals blank, are there orphan or duplicate files.

**Build** (`build_expected.js`) - no AI. Spreads each budget evenly across its flight and writes
every output file. Days are counted inclusively so the last day lands exactly on the goal.

### The one design idea worth protecting

**The AI is only allowed to do two things: read documents and exercise judgement. Every number
is calculated in code.**

That is why the output is checkable. A wrong figure is either a citation you can go look up, or
an arithmetic bug you can write a test for. Findings are tagged `code` or `model` so you always
know which one you are reading. Keep this. Every fix below is written to preserve it.

### Some things it already does well

- Refuses rather than guesses: no API key exits 2, unresolvable flight dates exit 3 instead of
  inventing a window, a campaign missing data becomes a named exception rather than a row of
  zeros, two campaigns in one folder produce a blocker rather than a blend.
- If the flight dates have to be inferred, the assumption is written into the findings list as
  a visible gap. It is never applied quietly.
- The expensive AI call is saved after it succeeds, so if only the final build step fails you
  can retry it for free (`/rebuild`).
- Identical files re-uploaded? It asks "run anyway?" before spending another AI call.

---

## 3. What is broken

Severity: **S1** wrong output, **S2** breaks under load or restart, **S3** annoying or risky
over time, **S4** slow.

| # | Problem | What you would actually see | Sev | Status |
|---|---|---|---|---|
| F1 | **Uploaded files are not restored after a restart** | analysis shows 0 files; re-running analyzes only what you upload next | S1 | **FIXED** `store.ensureFiles` + 409 on a short dump |
| F16 | **Only spreadsheets and CSVs are read** - 9 ways a file gets skipped | a PDF brief or `.xls` plan is ignored with no warning | S1 | **FIXED** more types read, every omission is a finding |
| F2 | **No check for a cut-off AI response** | run fails with "Unexpected end of JSON input" after paying for the call | S1 | **FIXED** `max_tokens` guard + raw reply saved |
| F3 | **Two campaign lines with the same name double up** | daily rows duplicated; the JSON stops matching the spreadsheet | S1 | **FIXED** uniquified in `normalizePlan` + finding |
| F18 | **Daily column does not sum to the cumulative column** | pivoting daily spend gives 6,000.07 against a stated 6,000 | S2 | **FIXED** (found while testing) daily is now the diff of rounded cumulatives |
| F4 | **Run status is stored in memory on one server** | "Run failed - poll returned HTTP 404" while the run is actually still going | S2 | **FIXED** durable `live_run.json` + cross-instance fallback |
| F5 | **One run at a time, everywhere, and all runs share one output folder** | analysis B waits on analysis A; stale files swept into the wrong archive | S2 | **FIXED** per-analysis lock + per-run work dir |
| F6 | **A run killed mid-flight stays "running" forever** | the spinner never stops, and the lock never clears | S2 | **FIXED** 15s heartbeat, dead after 4min - this wedged prod 2026-08-06 |
| F7 | **Reloading the page mid-run loses the run** | Run button is live again; clicking it errors with 409 | S2 | **FIXED** `active_run` in detail, tab re-attaches |
| F19 | **The pipeline printed nothing to the logs** | a stuck run was undiagnosable from anywhere | S2 | **FIXED** (found in prod) child output to console + a Run log in the tab |
| F8 | **Uploads are slow, and the "skipped" warning erases itself** | fewer files in the list than you dragged in, no explanation | S3 | **PART FIXED** warning now persists; uploads still serial, 15MB cap stands |
| F9 | **No sense of what changed between runs** | cannot tell new findings from ones you already triaged | S3 | open - `extract.js:258-268` |
| F10 | **Cost and duration are logged then thrown away** | no idea what a run cost | S3 | **FIXED** usage + duration on every run, plus a free pre-run estimate |
| F11 | **Re-reads the whole dump to answer "did anything change"** | slow with big dumps | S4 | open - `store.js:264-273` |
| F12 | **Cloud backup is serial, and not awaited where it matters** | a crash right after upload loses the file silently | S4 | **PART FIXED** file uploads awaited; `writeAnalysis` still fire-and-forget |
| F13 | **Buffers 64MB before enforcing the 15MB limit** | wasted memory on rejected uploads | S2 | **FIXED** capped at 2x, and it now answers 413 instead of resetting the socket |
| F14 | **The two-campaign guard filters files, not campaign lines** | blocker fires, but the blend can still happen | S2 | open - `extract.js:239-243` |
| F15 | **The maths has no unit tests** | every bug above could have been caught for free | S3 | **FIXED** 92 tests, ~2s, no key (`npm run test:greenlight`) |
| F17 | **Docs contradict the code in four places** | next person builds the wrong thing | S2 | **FIXED** in `expected/README.md` |

### What the run-engine fixes were actually about (2026-08-06, from production)

F4 to F7 were open findings until the first real run wedged the tab. An
instance was recycled mid-run, its in-memory `runs` Map died with it, and the
run it held stayed `status: running` forever. From then on every attempt
answered `409 a run is already in progress` - for **every** analysis, because
the lock was global - and nothing in the product could see or clear it. The
tab showed "Run failed - a run is already in progress" with no run anywhere in
the history.

Worse, it was undiagnosable: `routes.js` accumulated the child's stdout into a
string and only surfaced it on failure, so a healthy run printed **nothing** to
Cloud Run logs. A two-hour log search for the run returned three GCS boot-sync
lines and no pipeline output at all.

The fix is the heartbeat: a run writes `live_run.json` every 15s, and one that
stops writing for 4 minutes reads as dead rather than holding the lock. Add a
per-analysis lock (campaign A no longer blocks campaign B), a per-run work
directory (the shared `out/` was only safe *because* of the global lock), the
durable record as a cross-instance poll fallback, and every pipeline line going
to both the container log and a Run log panel in the tab.

### The three that matter most

**F1 - uploaded files vanish on restart.** Greenlight mirrors its data to cloud storage so
nothing is lost, but the mirror covers the *index* and the *results*, not the *files
themselves*. `bootSync` only pulls `analysis.json` and `results.json` (`store.js:89`), and
nothing ever downloads the `files/` folder. On Cloud Run the local copy lives in `/tmp`, which
is wiped when an instance restarts.

So after a deploy or a restart: the analysis is still in the dropdown with its name and history,
but it reports **0 files**. If someone then uploads the two new assets that just came in and
hits Run, they get a successful run over a two-file dump. The AI faithfully extracts a
"complete" plan from a fraction of the paperwork, few findings appear because there is little to
contradict, and the flowchart goes green. The "identical files" guard cannot help - the file set
genuinely did change.

`--min-instances=1` has probably hidden this so far. One deploy is enough to trigger it.

**F16 - most file types are never read.** Only `.xlsx`/`.xlsm` and `.csv`/`.tsv` have their
contents given to the AI. Everything else becomes a single inventory line:

| Skipped | Trigger | Does the AI know? | Do you? |
|---|---|---|---|
| PDF contents | any `.pdf` | **no** - no "not converted" label | no |
| Word / PowerPoint | `.docx`, `.pptx` | yes, labelled | no |
| Anything else | `.xls`, `.xlsb`, `.msg`, `.eml`, `.txt`, `.zip` | **no** | **no, nowhere** |
| CSV past row 15 | any `.csv` | labelled "head sample" | no |
| Sheet past 30,000 chars | long sheets | marker in the text | no |
| Corrupt / locked workbook | parse failure | file just absent | no |
| Empty sheet | blank after conversion | absent | no |
| File over 15MB | never uploaded | absent | chip that erases itself |
| Failed upload | network error | absent | same |

The two worst are a **brief delivered as a PDF** and a **media plan saved as legacy `.xls`**.
Both are completely normal agency artifacts. Both are invisible, with no signal to the AI that
content was withheld, so it does not report the plan as missing - it just extracts what it can
from whatever else is there. `.xls` is the cheapest fix in this whole document: SheetJS already
reads it, so it is one line in `classify()`.

**F8 - the skipped-file warning erases itself.** When a file is over 15MB or an upload fails,
the UI shows a `SKIPPED`/`FAILED` chip and a count. Then the upload batch finishes, calls
`openAnalysis()`, and the first thing that does is clear the list the chips were stored in
(`greenlight.js:247`). They disappear within a second or two, and after a reload there is no
trace at all. Nothing in the run, the report or the findings ever mentions the dropped file.

This is very likely the explanation when someone says files "sometimes don't get read": they
were never uploaded, and the notice saying so was wiped before anyone read it.

### The pattern behind all three

Everywhere Greenlight knows it is working with less than it was given - a truncated sheet, an
unreadable workbook, an unread PDF, a dropped 49MB deck, an empty folder after a restart - it
records the fact somewhere internal and **tells nobody**.

The system's own philosophy is that missing stays missing, and a confidently wrong number is
worse than a gap. That is enforced strictly on values the AI extracts, and not at all on files
the pipeline never opened. **The rule needs to extend from values to inputs:** anything it
could not read becomes a finding, and every run states how much of the dump it actually saw.

### One correction to an existing ticket

GL-01 says extraction "runs 320s synchronously inside the HTTP request" and needs to be moved
to a background job. **That is not what the code does.** `routes.js:270` starts the child
process and responds immediately - the request finishes in milliseconds and the work carries on
in the background. The `--timeout 600` workaround, the `TODO(background-job)` comment and the
README all describe a mechanism that is not there.

GL-01 is still needed, but for a different reason: run status lives in memory on a single
server (F4), so a status check answered by a *different* server reports a live run as dead. Do
not spend the budget detaching a process that is already detached.

---

## 4. Fix order

| # | Package | Fixes | Size |
|---|---|---|---|
| **W1** | **Restore uploaded files from cloud storage.** Download missing files on read; refuse to run if the count is short. | F1, F13 | S |
| **W4.3** | **Read more file types, complain about the rest.** Add `.xls`/`.xlsb`, extract PDF text, stop truncating small CSVs, raise a finding for every unread file, and print "38 uploaded, 21 parsed, 4 unreadable" on every run. | F16 | M |
| **W2** | **Make a run survivable.** Per-run output folder first (this ordering matters), then durable run status, a heartbeat so dead runs stop spinning, a per-analysis lock, and resume-on-reload. | F4-F7 | M |
| **W3** | **Make failures cheap and readable.** Three-line guard for a cut-off AI response, save the raw reply for diagnosis, record cost and duration. | F2, F10 | XS |
| **W4** | **Guard the maths and test it.** De-duplicate campaign names, state the guard's real limit, and add fixture tests for validate/build/preprocess - these run in under a second and cost nothing. | F3, F14, F15 | M |
| **W5** | **Fix uploads.** 3-4 at a time, one progress bar, and a direct-to-storage route so a 49MB deck can actually get in. | F8 | M |
| **W6** | **Make findings a living list.** Stable IDs, a new-vs-carried-vs-resolved diff between runs, and an "acknowledge" action. Then the known false positives (GL-17, GL-18). | F9 | M |
| **W7** | **Speed.** Cache the file index instead of re-hashing the dump; parallel and awaited cloud writes. | F11, F12 | S |
| **W8** | **Fix the docs.** | F17 | XS |

```
W1 -> W4.3 -> W2 -> W3 -> W4 -> W8
        \-> W5
                  W6 -> W7
```

**W4.3 is pulled up next to W1** because they are the same failure: running on less input than
you think you have. W1 is the restart half, W4.3 is the file-type half. Neither announces
itself, and one is already being reported from real use.

**Do W1 through W4 before the actuals join (M2 / GL-08 to GL-13).** Comparing real delivery
against a baseline that might have been built from half the paperwork produces a variance
number that looks authoritative and is not. The Actual side is worth exactly as much as the
Expected side is trustworthy.

---

## 5. Mapping to the existing backlog

`docs/backlog.md` has 28 issues. Most of the above is not in it.

| Finding | Existing issue | Action |
|---|---|---|
| F1 files not restored | **none** | **file new, P0** |
| F16 file types not read | **none** | **file new, P0** - reported from real use |
| F2 cut-off AI response | none | file new, P1 (3 lines) |
| F3 duplicate campaign names | none | file new, P1 |
| F4 run status in memory | GL-01 | **re-scope** - premise is wrong, ticket still needed |
| F5 global lock, shared folder | none | fold into GL-01, note the ordering |
| F6, F7 zombie runs, no resume | GL-01 | already in its criteria, keep |
| F8 upload path | GL-28 (in progress) | keep, add concurrency + the erasing warning |
| F9 findings diff and acknowledge | none (GL-16/17/18 cover noise only) | file new, P2 |
| F10 cost and duration | GL-07 | keep, cheaper than estimated |
| F11, F12 efficiency | none | file new, P3 |
| F13 body cap | none | fold into W1 |
| F14 guard limit | none | file new, P3 |
| F15 no unit tests | GL-04 (CI only) | **extend** - there are no tests for CI to run |
| F17 doc drift | GL-05, GL-22 | keep |

---

## Bottom line

The pipeline is the best-built unit in `grid-core`, and the AI-versus-code boundary is exactly
right. What was not right was everything around it: the assumptions that state lives in one
process, that a local folder persists, and that whatever you dropped into the browser is what
the AI read.

**Half of that is now closed.** W1 (dump rehydration) and W4.3 (intake) landed on 2026-08-06,
so the input side no longer lies: files come back after a restart, a run refuses rather than
analysing a partial dump, more file types are read, and anything still unread becomes a
finding. The rule the unit already applied to extracted values now applies to inputs too.

**The state side is still open.** F4 to F7 - run status in memory on one instance, a global
lock over a shared output folder, zombie runs, no resume on reload - are W2, and they are the
next package. They cost users trust and money (a run reported dead is a run paid for twice),
but unlike the input findings they fail loudly, which is why they queue second.

Still true: **do not start the actuals join (M2) until W2 lands.** And when W2 is scoped,
correct GL-01 first - the run is already detached from the request; the work is durable run
state and instance-independent polling.
