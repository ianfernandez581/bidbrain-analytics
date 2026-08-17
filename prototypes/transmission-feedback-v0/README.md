# Transmission Feedback Loop — v0 prototype

A single-file, offline registry of every report deck sent to a Transmission client and every
piece of feedback received on it — the submit → feedback → final loop, filterable and printable.
**Internal only; never client-facing.** It SHIPPED as the Feedback Loop tab in the Transmission
agency portal (`bidbrain-platform/`), where it runs on the live sheet. 100% Digital staff always
see it; the agency's own login sees it only while an admin has switched it on with the visibility
button in the pane toolbar (off by default — the content names what went wrong on whose report).
The button hides itself unless `window.BB_FBL_ADMIN` is set, so it never appears in a standalone
build of this file. This folder stays the canonical source of the page and of the sheet -> JSON
contract.

- `index.html` — the page, self-contained, opens by double-click (`file://`), zero network.
  The tracked copy is seeded with **sample data** (`meta.sample: true`, amber SAMPLE DATA pill).
- `sample_data.json` — the seed, identical to the block embedded in `index.html`.
- `sheet_to_json.py` — builds a hand-shareable **snapshot file** from the compilation sheet.
- `DISCOVERY.md` / `QA_NOTES.md` — Phase 0 findings and the executed QA suite.
- `review_report.txt` — pointer; the real one is generated per snapshot build (see below).

## The portal needs no refresh (since 2026-08-17)

The Feedback Loop tab in the agency portal **reads the sheet live** on every load
(`bidbrain-platform/dash/feedback_loop_data.py`, cached ~60s), so adding a row to the sheet is
the whole workflow — there is nothing to re-run and nothing to redeploy. The transform rules live
in that module now; this folder's script imports `build()` from it rather than keeping a second
copy that could drift.

## Snapshot procedure (a real-data file to hand someone)

1. From the repo root:

       .\.venv\Scripts\python.exe prototypes\transmission-feedback-v0\sheet_to_json.py

   It pulls the sheet's own CSV export. Pass a path instead to build from a
   **File → Download → CSV** export (needed only if link sharing is ever turned off). Expected
   columns: `Client | Campaign | Month | Link to submitted deck | Link to final deck | Client
   feedback` (the legacy header `Link to report deck` is accepted for the submitted column;
   `Sent on`, `Sent by`, `Notes`, `Sentiment`, `Type`, `Source`, `Author` and `Feedback date`
   are honoured when present, in the file AND in the portal).
   Output lands in **`staging/transmission-feedback-v0/`** (gitignored — client verbatims must
   never enter git history): `index.html` (the shareable build), `data.json`, `review_report.txt`.
3. **Verify the reconciliation counts** the script prints (source rows vs reports vs feedback
   entries vs flags) and read `review_report.txt` — every judgment call is listed with its row
   number. Fix flagged rows in the sheet and re-run rather than hand-editing output.
4. Open the staging `index.html` and **confirm the amber SAMPLE DATA pill is gone**, the window
   line reads "refreshed today", and the footer says the file is a snapshot (a live build says so
   instead — the page reads `meta.live`).
5. Share that file **via direct message only (e.g. a Slack DM), never a public link or channel** —
   it aggregates candid client feedback and an incident log.

Rows the script splits from a multi-item cell arrive untagged (`neutral / general / other`, full
raw cell in the Note line). Tagging sentiment/type/source is a manual pass in the sheet; the
script never infers. Reports with an unparseable month surface in the page under **Needs review**.
Rows sharing client+campaign+month — or the same submitted-deck URL for the same client — are
**merged into one report** with their feedback combined; every merge is logged in
`review_report.txt` (the same URL under two different clients is flagged, never merged).

## Live in the portal

This page IS the portal's Feedback Loop tab (Transmission only): `make_portal_template.py` scopes
it into the inline pane `bidbrain-platform/dash/templates/_feedback_loop_pane.html` (a `.bbpane`
sibling of the other tabs, not an iframe) plus `feedback_loop_sample.json` (this folder's
`sample_data.json`, now only the last-resort fallback). `main.py _fill_feedback_loop()` fills the
`__FEEDBACK_DATA_JSON__` sentinel with the LIVE sheet read at request time — see
`bidbrain-platform/README.md` -> "Feedback Loop tab" for the fallback chain and the sheet columns.
**After editing `index.html` or `sample_data.json`, re-vendor and redeploy:**

    .\.venv\Scripts\python.exe prototypes\transmission-feedback-v0\make_portal_template.py
    .\bidbrain-platform\dash\deploy_dash_platform.ps1

## Repo notes

The tracked `index.html` must always carry sample data; real-data builds exist only under
`staging/` (gitignored). The live portal path never writes a file into the repo at all.
