# Timesheet — June 2026 (reconstructed from git history)

**Person:** Ian (`ian@100.digital`)
**Repo logged:** `bidbrain-analytics` only (all other repos excluded per instruction)
**Window:** 1–30 June 2026
**Generated:** 2026-06-30 — read-only reconstruction from actual commits. No fabricated hours.

## Method & assumptions
- **Source of truth:** `git log` over `bidbrain-analytics`, all branches, scoped to Ian's three
  authoring identities found in this repo — `Ian <ian@100.digital>`,
  `IanFernandezCTM <IanFernandezCTM@gmail.com>`, and `Agora Data Driven <info@agoradatadriven.com>`.
  All three commit interleaved on the same dashboard work (STT, MongoDB, Cloudflare, Schneider, Geocon,
  platform front-door) and are the *only* June contributors to this repo — so all three are treated as
  Ian. (The `agoradatadriven.com` identity is flagged below for your confirmation.)
- **Weekdays only.** Saturdays and Sundays are left blank. Work committed on weekends is **credited to
  weekdays**, but **no weekday exceeds 8h**.
- **8h cap.** Realistic raw effort most weeks exceeded 22 weekdays × 8h. Where a weekday's own commits
  plus credited weekend/overflow work exceed 8h, it is capped at 8h (raw estimate noted in parentheses).
- **Clustering:** a burst of commits close in time is treated as one continuous session, not additive
  per-commit time. Design, EDA, testing and debugging around each commit are included but kept grounded.
- **Billable:** every row is `bidbrain-analytics` client-dashboard delivery → **billable**. A handful of
  days are platform/internal tooling (front-door, feedback, status, repo refactor) rather than a single
  client dashboard — tagged `Platform` so you can re-bucket them if you bill those differently.

---

## Daily timesheet

| Date | Day | Hours (raw) | Client / Project | Billable? | Evidence (commits — summary) |
|---|---|---|---|---|---|
| Jun 01 | Mon | **8** (≈5) | Cloudflare/MongoDB CS | Yes | 1 commit — exclude `LEAD_STATUS='New'` from the Salesforce lead pull; project kickoff + env setup feeding the Jun 2 ingest build. ⚠ lightest-evidence day |
| Jun 02 | Tue | **8** (≈13) | Shared ingest + MongoDB + Cloudflare | Yes | 15 commits — `snowflake_data_pull` shared raw mirror; migrate MongoDB onto `raw_snowflake`; TradeDesk loader (ad_group/creative grain); land Cloudflare raw sources in BQ; **add Cloudflare dashboard (1,701 lines)**; GA4 loader; full dual-purpose README sweep |
| Jun 03 | Wed | **8** (≈12) | STT (archetype) | Yes | 7 commits — **add client_STT** (GA4+LinkedIn+DV360, 33 files / 2,132 lines); Country filter (Global off by default); Google Ads paid-search lane + Platform filter; SGD conversion at staging; GA4 events loader (660 lines) |
| Jun 04 | Thu | **8** (≈14) | HireRight + Schneider + STT | Yes | 25 commits (busiest day) — **HireRight + Schneider scaffolds (80 files / 5,408 lines)**; STT Overview tab (AI commentary, key-events charts); per-stage redeploy scripts for every client (604 lines); SameSite=None cookie fix; Schneider plan-budget seeding; repo-wide docs sweep |
| Jun 05 | Fri | **8** (≈11) | Shared DTS ingest + Cloudflare | Yes | 12 commits — **native DTS ingestion (Google Ads + GA4 → BQ, 584 lines)**; regenerate `perf_ga4` across 13/20 properties (373 lines); GA4/Google-Ads history backfill (37-mo cap); Cloudflare creative-name decoding + CS clear buttons |
| Jun 06 | Sat | — | — | — | weekend, blank (work credited to the week: Windsor Google Ads loader 701 lines, Neto orders loader 1,112 lines, DTS bridges) |
| Jun 07 | Sun | — | — | — | weekend, blank |
| Jun 08 | Mon | **8** (≈12) | CityPerfume + ResetData | Yes | 2 commits — **client_cityperfume (5th, e-comm, 46 files / 2,697 lines)** + **client_resetdata (6th, B2B AU, 42 files / 2,188 lines)**; two full client builds in one day |
| Jun 09 | Tue | **8** (≈6) | Cloudflare + MongoDB | Yes | 4 commits — Cloudflare CS lead-status bucket redefinition; single-campaign LinkedIn view + dashboard selector; white Transmission logo SVG; MongoDB numeric header alignment |
| Jun 10 | Wed | **8** (≈8) | MongoDB + cross-client filter | Yes | 2 commits — MongoDB CS bucket redefinition + lead-quality card (449 lines); **Looker-style date-range filter rolled to all 7 dashboards (1,840 lines)** |
| Jun 11 | Thu | **8** (≈13) | PropTrack + freshness infra + STT | Yes | 5 commits — **PropTrack (7th) + cityperfume daily views + containerized ingest jobs (73 files / 3,672 lines)**; **self-gating freshness across the fleet (62 files / 3,549 lines)**; date-picker fix; STT GA4 Korea normalize |
| Jun 12 | Fri | **8** (≈10) | CityPerfume + ResetData + Reddit + PropTrack | Yes | 9 commits — CityPerfume Year-on-Year tab + sales-channel filter + Karla font; ResetData drill-down hero + grain/axis toggles; **Reddit Ads loader (1,317 lines)**; PropTrack creative assets |
| Jun 13 | Sat | — | — | — | weekend, blank (credited: **435-file refactor into clients/ + ingest/**, full repo doc sweep 1,061 lines) |
| Jun 14 | Sun | — | — | — | weekend, blank (credited: **TLM 9th client + VMCH 10th client — two full builds**, 2,214 + 2,945 lines) |
| Jun 15 | Mon | **8** (≈12) | All-10 dashboards (cross-client) | Yes | 2 commits — **Month/Week/Day + Relative/Absolute toggles across ALL 10 dashboards (120 files / 5,642 lines)** + workspace update (34 files / 2,016 lines). Absorbs the credited Jun 13–14 weekend client builds |
| Jun 16 | Tue | **8** (≈10) | CityPerfume + MongoDB | Yes | 3 commits — **CityPerfume 2nd dashboard (all-sales incl. in-store POS, 1,946 lines)**; **MongoDB KGA/IDC delivered-leads rule + complete CS market totals (38 files / 4,955 lines)** |
| Jun 17 | Wed | **8** (≈12) | MongoDB + Cloudflare + Meta/ResetData | Yes | 10 commits — **MongoDB Universal Pixel rebuilt from live Snowflake (1,165 lines)**; **Cloudflare ported to BQ-owns-the-model (28 files / 957 lines)** + CS set 8→12; Meta 'Signup Button' pixel → ResetData Meta leads 2→51; Meta 13-month-horizon fix |
| Jun 18 | Thu | **8** (≈7) | VMCH | Yes | 2 commits — **VMCH consolidated to single-page dashboard + spend-proportional (OLS) ad attribution** (238 ins / 861 del); workspace updates (451 lines) |
| Jun 19 | Fri | **8** (≈8) | Platform feedback + Cloudflare | Yes (Platform) | 5 commits — **text/voice feedback widget on every dashboard (323 lines)** + Gemini transcribe/AI-interpret + html2canvas screenshot (253 lines) + per-note triage; Cloudflare client-defined KR + RIG CS segments |
| Jun 20 | Sat | — | — | — | weekend, blank (credited to Mon Jun 22: **ResetData HubSpot CRM tab + shared Windsor hubspot/fields ingest**, 23 files / 1,207 lines) |
| Jun 21 | Sun | — | — | — | weekend, blank |
| Jun 22 | Mon | **8** (≈8) | ResetData HubSpot + Schneider/Cloudflare prep | Yes | **0 same-repo commits this date** — 8h is the credited Jun 20 HubSpot CRM build + lead-up to the large Jun 23 morning landing. ⚠ verify (only Jun 22 commit on this machine is in the excluded Riverdance repo) |
| Jun 23 | Tue | **8** (≈13) | Schneider + Cloudflare + Platform status | Yes (mixed) | 3 commits — **Schneider CS-clone restructure + Cloudflare CF1 syndication lane + status dash (30 files, 1,663 ins / 2,054 del)**; **merge Status dashboard into front-door + editable definitions (20 files / 1,325 lines)**; drop definitions editor |
| Jun 24 | Wed | **8** (≈6) | Cloudflare + Status + Platform feedback | Yes (mixed) | 4 commits — Cloudflare dashboard cleanup (remove pixel-caveat blocks + Unprocessed card); status verifier CS residual guard + raw 12-campaign counts; platform feedback fixes (AI summary + voice player, 195 lines) |
| Jun 25 | Thu | **8** (≈8) | Cloudflare markets/targets + docs | Yes | 3 commits — **Cloudflare 11 media-plan markets + no-Others + KR=all-Korea + committed-CSV→BQ targets standard (20 files / 612 lines)**; merge front-door + Sync-all-now; sync all .md docs (27 files) |
| Jun 26 | Fri | **8** (≈10) | Geocon (new client) | Yes | 3 commits — **Geocon new Meta paid-media client scaffold (40 files / 3,525 lines)** + dashboard assets + AI Download-report & trend toggles (2,039 lines) |
| Jun 27 | Sat | — | — | — | weekend, blank (Geocon build continues; credited to Jun 26 / Jun 29) |
| Jun 28 | Sun | — | — | — | weekend, blank |
| Jun 29 | Mon | **8** (≈9) | Geocon | Yes | 3 commits (overnight 04:11–07:58) — **Geocon ground-up rebuild to STT/MongoDB grade** (11 files, 874 ins / 1,892 del); denser restyle; integrate spec gaps (KPI deltas, volume warnings, hero band) |
| Jun 30 | Tue | **8** (≈10) | Schneider + Platform + STT | Yes (mixed) | 9 commits — Schneider rebrand APAC→Pacific + label rename; **platform native Google sign-in (17 files / 624 lines)**; feedback reporter-name/deadline + hand-editable tracker + filter dropdowns; Bid Brain favicon; STT date filter drives KPI cards |

---

## Totals (June 2026)

- **Total billable hours:** **176.0 h** (22 weekdays × 8h, all `bidbrain-analytics`)
- **Total internal hours:** **0.0 h** (only `bidbrain-analytics` logged per instruction; other repos excluded)
- **Weekend days:** 8 (Jun 6, 7, 13, 14, 20, 21, 27, 28) — blank; their work credited into weekdays at the 8h cap.

> Of the 176h, roughly **150h is client-facing dashboard delivery** and **~26h is platform/internal
> tooling** (the `Platform`-tagged portions of Jun 19, 23, 24, 30 — feedback system, front-door, status
> merge, Google sign-in). Re-bucket these if you bill platform work differently from client work.

---

## Days to manually verify

1. **Mon Jun 22 — biggest flag.** No `bidbrain-analytics` commit is dated this day; the only commit on
   this machine for Jun 22 is in the **Riverdance** repo (excluded). The 8h here is *credited* work —
   the Jun 20 (Sat) HubSpot CRM build + prep for the large Jun 23 07–08:00 landing. Confirm Jun 22 was
   actually spent on analytics and not mostly on Riverdance.
2. **Mon Jun 01 — lightest evidence.** One 3-line commit at 18:19. The 8h assumes project kickoff,
   environment setup and EDA flowing into the Jun 2 ingest build. Confirm this was a full day.
3. **`Agora Data Driven <info@agoradatadriven.com>` identity.** I counted these as your commits (they
   continue the exact same dashboards in the same repo, interleaved with your other two identities).
   Confirm this is you and not a separate contributor — it affects Jun 26–30 (Geocon, platform,
   feedback) and parts of Jun 30.
4. **Heavy weekend work now uncounted (you may want to redistribute within policy).** Real, substantial
   work fell on weekends and is only credited up to the 8h weekday cap, so some is effectively unbilled:
   **Jun 14 (Sun) — TLM + VMCH, two full client builds**; **Jun 13 (Sat) — 435-file refactor + docs**;
   **Jun 20 (Sat) — HubSpot CRM**; **Jun 6 (Sat) — Windsor + Neto loaders**. If your billing allows
   crediting weekend work to a later week, these are the hours that overflow past the cap.
5. **Platform/internal vs client split.** Jun 19, 23, 24, 30 mix client dashboards with platform
   tooling (feedback, front-door, status, Google sign-in). Tagged `Platform` above — split out if needed.
