# Transmission Feedback Loop — v0 prototype

A single-file, offline registry of every report deck sent to a Transmission client and every
piece of feedback received on it — the submit → feedback → final loop, filterable and printable.
**Internal only; never client-facing.** Approval prototype for Calvin; if approved it becomes a
tab in the agency portal (`bidbrain-platform/`).

- `index.html` — the page, self-contained, opens by double-click (`file://`), zero network.
  The tracked copy is seeded with **sample data** (`meta.sample: true`, amber SAMPLE DATA pill).
- `sample_data.json` — the seed, identical to the block embedded in `index.html`.
- `sheet_to_json.py` — turns a CSV export of the compilation sheet into a **real-data build**.
- `DISCOVERY.md` / `QA_NOTES.md` — Phase 0 findings and the executed QA suite.
- `review_report.txt` — pointer; the real one is generated per refresh (see below).

## Refresh procedure (real data)

1. Open the compilation sheet (the ＋ Log feedback button in the page links to it) and
   **File → Download → CSV** the tab. Expected columns:
   `Client | Campaign | Month | Link to submitted deck | Link to final deck | Client feedback`
   (the legacy header `Link to report deck` is accepted for the submitted column).
2. From the repo root:

       .\.venv\Scripts\python.exe prototypes\transmission-feedback-v0\sheet_to_json.py <export.csv>

   Output lands in **`staging/transmission-feedback-v0/`** (gitignored — client verbatims must
   never enter git history): `index.html` (the shareable build), `data.json`, `review_report.txt`.
3. **Verify the reconciliation counts** the script prints (source rows vs reports vs feedback
   entries vs flags) and read `review_report.txt` — every judgment call is listed with its row
   number. Fix flagged rows in the sheet and re-run rather than hand-editing output.
4. Open the staging `index.html` and **confirm the amber SAMPLE DATA pill is gone** and the
   window line reads "refreshed today".
5. Share that file **via direct message only (e.g. a Slack DM), never a public link or channel** —
   it aggregates candid client feedback and an incident log.

Rows the script splits from a multi-item cell arrive untagged (`neutral / general / other`, full
raw cell in the Note line). Tagging sentiment/type/source is a manual pass in the sheet; the
script never infers. Reports with an unparseable month surface in the page under **Needs review**.

## Repo notes

Lives on its own branch; nothing is wired into the production app and no repo file outside this
folder is touched. Keep the branch local (or park it as `wip/…`) until Calvin signs off — a pushed
dev branch gets integrated onto main by the next `/ship`. The tracked `index.html` must always
carry sample data; real-data builds exist only under `staging/`.
