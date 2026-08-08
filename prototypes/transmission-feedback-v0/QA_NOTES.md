# QA_NOTES.md — Transmission Feedback Loop v0

Run 2026-08-08 against the shipped `index.html` (sample data) and `sheet_to_json.py`.

**How it was tested.** The environment can render: every functional check ran in real headless Chrome over `file://` — six instrumented variants of the page (default, XSS, missing-data, stale, long-content, 50-card perf) with an in-page assertion harness, at 1280/1024/900px. **183/183 assertions pass.** Print was verified two ways: `--print-to-pdf` (text-extracted and checked) plus a screenshot with the print stylesheet force-applied. Contrast was measured, not eyeballed: a computed audit of 41 text/background pairings with translucent backgrounds alpha-composited down to the page bg. Screenshots were taken at each key state (default, inaccuracy filter, print, 900px) and compared to the reference design. Purely interactive feel (hover tooltips appearing, scroll smoothness by hand, a live devtools network tab) can't be exercised headless — those were verified statically as noted below; worth one manual desktop pass before the file goes to Calvin.

## The 19-item suite

1. **file:// / console / network — PASS.** Zero console errors on every variant (in-page `window.onerror` hook, including the 50-card perf run). Network: static audit — no `<link>`, `<img>`, `url()`, `fetch`, import, or webfont anywhere; the only `http` strings live inside the data block and render as user-clickable links. Nothing to request, so the network tab is empty by construction; re-confirm interactively on the manual pass.
2. **Reconciliation — PASS.** Metric cards equal rendered DOM counts at 8 checkpoints (default, all-time, each filter, combined, after clear). At All time the four cards equal the JSON array lengths exactly (10 / 18 / 3 / 1; sentiment 7·6·5). Note: the *default* view is the "Last 3 months" window (Jun–Aug), which correctly excludes the May 2026 PropTrack report — cards then read 9/16/2/1, matching what is rendered, per §4.3 "cards describe the currently visible set".
3. **Filter matrix — PASS.** Each filter alone, combined (client+type+sentiment+period+search), zero-result state, and "Clear filters"/"Filtered — clear all" restore every control and the unfiltered counts.
4. **XSS — PASS.** A variant carrying `<script>alert(1)</script>` (verbatim + author) and `<img src=x onerror=alert(1)>` (verbatim + context): both render as literal text everywhere including the Note line and search results; no `img`/`script` elements appear in the app DOM; a pre-hooked `alert` never fires. The payload lived only in the generated QA variant — the shipped file never contained it.
5. **Long content — PASS.** A 600-char verbatim wraps inside its card (element scrollWidth ≤ clientWidth) with no page h-scroll at 1280/1024/900; a 120-char campaign truncates with ellipsis and carries the full name in `title`.
6. **Missing data — PASS.** Null `deck_submitted_url` → no link (nothing broken); null `deck_final_url` → no element; empty author → "Unattributed"; `period: null` → amber **Needs review** chip under a "Needs review — period missing in the source sheet" note, still visible under any period filter (a null period can't be windowed — absence surfaces rather than vanishes); null `sheet_url` → the Log feedback button is removed entirely.
7. **Log feedback — PASS.** Intercepted `window.open`: exact sheet URL, `_blank`, `noopener`. Tooltip text matches the spec string exactly.
8. **Freshness — PASS.** `generated_at` = today → "refreshed today"; a variant back-dated 14 days → "refreshed 14 days ago — refresh before using in a meeting" in amber (same >7-day branch the spec's 10-day example exercises). Shipped file restored to today.
9. **Sentiment labels — PASS.** `/negative/i` appears nowhere in rendered UI text in any state; the JSON enum stays `negative`. (Kept the sample verbatims free of the word so the check stays trivially auditable.)
10. **Tooltips — PASS.** Every type badge's `title` equals its §4.4 definition verbatim.
11. **Context notes — PASS.** "Note: …" renders only when `context` is non-empty; no empty elements (2 notes at all-time, 1 in the default window).
12. **Legend — PASS.** Computed legend-dot colors === computed entry-rail border colors (both read the same CSS custom properties).
13. **Sort — PASS.** Reverse-chronological within sections (Jul→Jun; PropTrack Jun→May at all-time), not alphabetical.
14. **Sample pill — PASS.** Present on screen and in the print PDF text; on a `meta.sample: false` build the element is removed (verified on a scripted staging build).
15. **Print — PASS.** 4-page PDF: light theme, toolbar hidden, `*{box-shadow:none!important;text-shadow:none!important}`, deck URLs printed inline after each link, window line + sample pill present, `break-inside:avoid` on report cards / incident rows / metric cards. The print-emulated screenshot reads as a deliberate document.
16. **Glow calibration — PASS.** Contrast audit **with glows applied**: 41 pairings, all AA (minimum 4.87:1 — blue deck links on card; large-text pairs well over 3:1). No `filter:` anywhere (the sticky toolbar uses `backdrop-filter`, which is portal-idiomatic and not the banned paint-killer). Perf variant: 50 report cards render with zero errors and no layout breakage. 100% screenshot check: the ambient is the portal's own radial, so "portal at night" holds by construction.
17. **Pluralization — PASS.** "1 report", "1 feedback item", "1 inaccuracy", and "1 needs improvement" vs "n need improvement" all verified.
18. **Resize — PASS.** 1280/1024/900: no overlap, no horizontal scroll (toolbar and metric grid wrap; report-head wraps). Repo hygiene: `git status` shows changes only inside `prototypes/transmission-feedback-v0/`; no production file touched; no dependency added (QA's `pypdf` went into the session scratchpad, not the repo venv).
19. **Data hygiene — PASS.** Tracked `index.html` embeds exactly `sample_data.json` (verified equal by parse) with `meta.sample: true`; `sheet_to_json.py` writes real-data builds only under gitignored `staging/transmission-feedback-v0/`; the branch's git log contains sample data only.

**Ingest script QA** (synthetic CSV, scratchpad only): month forms "June 2026"/"06/2026"/"2026-06"/"Jun 2026"/bare "June" all normalize; "Q3" → `period: null` + flag + renders under Needs review; unknown client "Cloudfare" → excluded + "did you mean 'Cloudflare'?" flag; case-insensitive "mongodb"/"stt" → canonical; multi-line bullet cell → 3 entries with the full raw cell in `context`; final==submitted → null + flag (rule 6); duplicate row, missing-link and blank rows flagged/skipped; legacy `Link to report deck` header accepted; reconciliation counts printed and correct; injected staging page parses identical to its `data.json`.

## Fixed as a result of QA

- All fixes were in the QA harness itself, not the page: literal `</script>` inside harness strings terminated its script block (the page's own injector already escapes `</` in JSON — the harness now splits the literal); two assertion expectations were wrong (12 deck links, not 11; sentiment-rail counts asserted at the default window instead of all-time); month-label assertions made locale-tolerant. No app-code defects were found after the first complete run.

## Conflicts flagged (prompt vs reference vs portal — none resolved silently)

- **Ambient alphas.** The prompt says both "match the portal's own ambient radial exactly" and "alphas ≈ 0.05–0.06", but the portal's actual radial stack is `rgba(76,141,255,.18)` + `rgba(110,168,255,.10)` (portal.html body). Kept the portal's exact values — parity is the point of the section, and the calibration target ("portal at night") is satisfied by using the portal's own light. The reference file's extra bottom teal radial was dropped for the same reason (the portal has none).
- **`review_report.txt` deliverable vs "verbatims never enter git".** A real review report can quote sheet cells, so the script emits it next to the staging build (gitignored); the tracked `review_report.txt` is a pointer explaining that. Data hygiene won.
- **Token drift.** Per "repo tokens first", the reference's approximated values were replaced with the portal's real ones (green `#34D399` not `#2fd985`, card `#101726` not `#0f1622`, magenta `#e60b7f` not `#ff2e88`, etc. — full mapping in DISCOVERY.md §2). The build therefore differs very slightly in color from the preview file Calvin saw earlier.

## Decisions where the spec was silent

- `report.notes` exists in the contract but no UI element is specified for it → not rendered.
- "Last month" = the calendar month containing `window_end` (consistent with "Last 3 months" = that month + 2 prior). Early in a month this can legitimately show zero monthly reports (the sample data does) — the zero-state message + Clear filters is the escape hatch.
- Only `http(s)` URLs are rendered as deck links or opened by the Log feedback button — a poisoned cell like `javascript:…` renders no link at all.
- Incident rows render their `context` Note line too (incidents are feedback entries; §4.4 defines context rendering for entries).
- CSV carries no sent-on/sent-by/date/author columns → script emits `sent_on: null`, `sent_by: ""`, `date: null`, `author: ""`; the UI omits the "Sent …" line, shows "Unattributed", and skips the date separator. Noted once in the review report's NOTES, not per-row.
- Bare month names ("June") are in the spec's accepted list but carry no year → the run year is assumed **and** the row is flagged (assumption made visible, not silent).
- Duplicate client+campaign+month rows: both emitted, flagged (never merge silently). Non-canonical clients: excluded from the build but flagged loudly with the nearest canonical name (the UI can only render canonical sections, so "included" would mean silently invisible — worse).
- The portal's decorative cursor-follow glow was not ported (not in the spec's glow map; quieter option).
- A one-line `<noscript>` notice was added.
- Sample `generated_at` kept at the contract example (2026-08-08T14:00:00+08:00) so the demo opens on "refreshed today"; the script stamps real run time with the machine's UTC offset.
- Month labels come from `toLocaleDateString('en-AU')`: desktop Chrome renders "Jul 2026"; the headless test browser's ICU rendered "July 2026". Cosmetic, environment-dependent; assertions were made locale-tolerant.
- Search matches verbatim/author/client/campaign per §4.2; report cards with no entries also match on campaign/client/sender so a searched report doesn't vanish (reference behavior, kept).
- The repo's `scripts/_validate_dash_js.py` was run for parity with dashboard practice: it flags the JSON data block because it tries to parse *every* inline script as JS (pre-existing validator limitation, false positive); the app script itself parses clean under the same esprima engine.
