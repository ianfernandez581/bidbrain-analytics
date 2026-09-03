# BUILD_NOTES - Foodbank Australia pitch dashboard (built 2026-09-03)

## What was built

`clients/client_foodbank/` - a password-gated, Foodbank-branded, Think HQ-signed campaign dashboard
on deterministic sample data. Seven tabs (Overview · Channels · Audience and reach · Video and
creative · Website and actions · Pacing · Methodology), a working Last 7 / Last 28 / Full flight
date control and channel chips that re-filter every figure, a login portal ported from the
Cloudflare gate, Docker + deploy scripts prepared (not run), QA screenshots.

## Reference files copied from (per the brief's "port, don't re-invent")

- Auth mechanism: `clients/client_cloudflare/dash/main.py` -> `authed()`, `home()`, `login()`
  (`hmac.compare_digest`, `session["ok"]`, permanent 12h session), `logout()`, gated `/data.json`.
- Login behaviours (show/hide, Caps Lock, submit-once, shake-once): the BB login kit as ported into
  `clients/client_geyervalmont/dash/main.py` (`scripts/motion_kit/login_js.tpl`).
- Preview-mode wiring (baked-in sample payload, standup script that creates no pipeline):
  `clients/client_geyervalmont/` (`main.py`, `deploy_geyervalmont.ps1`, `dash/deploy_dash_geyervalmont.ps1`).
- Multi-channel chip + filter shape: `client_geocon` / `client_resetdata`; sortable-table engine and
  donut-centre plugin vendored from `clients/client_resetdata/dash/dashboard.html`.
- Awareness vocabulary (impressions, reach, clicks, sessions, engaged sessions, key events, no
  revenue/ROAS): `clients/client_vmch/`.
- `dash/platform_sso.py`: byte-for-byte the vendored copy every dashboard carries.

## Decisions and deviations from the brief

1. **Templates + static files instead of one big `dashboard.html`.** The brief's architecture asks
   for `templates/` and `static/css|js|img/`; the estate convention is one file with inlined logos.
   Followed the brief, kept the estate's lesson: every asset URL is relative so it resolves behind
   `/d/foodbank/` too. Putting the JS in a static file also keeps Jinja away from `{{` in JS.
2. **Think HQ assets.** The addendum says three transparent wordmarks were supplied; only one file
   arrived (`image (4).png`, black on white, 1024px). The cream / ink / white PNGs were derived from
   it (alpha = darkness, then filled). Spec says "do not recolour" - there was no coloured original
   to preserve, so this is the closest faithful option. Replace with the real files when they land.
3. **Foodbank logo.** The SVG at foodbank.org.au downloaded fine and is already the cream lockup
   (one path, `#f2f2e2`). The supplied `logo-foodbank.png` is the purple version for white surfaces.
4. **Contrast over spec literals.** Three login alphas from the measured spec fell under target
   (placeholder 35% -> 2.9:1, footer 45% -> 4.1:1) and were nudged (42%, 52%). In the dashboard the
   muted ink token went from 56% to 68% and the variance-chip text colours were darkened so every
   text pairing clears 4.5:1 (cream on card 14.9:1, ink on coral 7.5:1, eyebrow 9.8:1).
5. **Em-dash.** The repo rule is "no em-dashes in client copy"; the addendum specifies the browser
   title verbatim with one. The title uses it; all other copy uses hyphens.
6. **Budget card is whole-flight** (a budget is a flight-level fact); the five hero numbers and
   everything below follow the date window and channel chips. The scope line under the controls
   states the active window in words.
7. **Pacing under a partial window** compares delivered spend with the whole plan weeks the window
   overlaps. The presets are multiples of 7 and the flight is Mon-Sun aligned, so they line up.
8. **Reach for an arbitrary window** uses a small model shipped in the payload (`reach_model`):
   sum of daily reach x days^(-k) per channel, then an interpolated cross-channel overlap factor.
   The generator uses the same formula to draw the reach curve, so the two always agree. Stated on
   the Methodology tab as an estimate.
9. **Video views are per-platform units** (Meta ThruPlay / YouTube view / programmatic completed
   view) - summed for the headline, defined per channel in the payload and on the Methodology tab.
   Viewability is NULL for Meta/YouTube (not measured), never 0 - the repo-wide rule.
10. **Chart animation off; one entrance moment** (login card 200ms fade-up; tab panel 320ms). No
    count-ups, no per-section reveals.
11. **Agency portal (`/thinkhq`, optional Section F) - SKIPPED, deliberately.** The existing agency
    portal machinery lives in the platform registry (`bidbrain-platform/dash/config.py`), which the
    hard constraints forbid touching. A `/thinkhq` route inside this service would be exactly the
    second pattern the addendum warns against. The right move is a Think HQ agency entry in the
    platform registry when the pitch lands (step 3 of the flip).
12. **`SHOW_PLATFORM_CREDIT = False`** keeps the 100% Digital seam without rendering it anywhere.

## Second pass (same day): "too zoomed in", "more cells", "too childish - make it premium"

- **Login scaled down** to a 400px card, 124px lockup, 21px heading, 46px input, 48px button. The
  deep plum field and card were already the direction the client liked; only the scale changed.
- **Dashboard restyled with restraint, inside the brand kit.** The bright brand-purple canvas read
  playful, so the field is now the login's deep plum family (`--plum-0/1/2`) and brand purple is the
  ACCENT: active-tab underline, primary series, dots. Pill tabs became an underline rail; the solid
  segmented control became a quiet outline; shadows became hairlines; card radius 20 -> 10, panel
  radius 48 -> 22; bar radius 3; Poppins survives only on titles, every figure is Inter with tabular
  numerals. Hero numbers sit in a hairline-divided stat row instead of floating at 48px.
- **More cells.** Overview gained an 8-cell efficiency strip (spend, CPM, clicks, CTR, CPC, view rate,
  CPV, cost per visit) so the hero stops repeating those figures in its captions; Audience 4 -> 6
  cells; Website 4 -> 8; Pacing 4 -> 8 (average week, weeks within 5% of plan, best and weakest week).
  KPI grids are `minmax(148px, 1fr)` so 8 fit across at 1360.
- Text-valued KPI cells (`Complete`, `NSW-ACT`) use a smaller face (`.kpi-val.txt`) so they never wrap
  against the numeric cells beside them.
- The premium-polish skill's "never re-skin" ceiling protects dashboards a client already reads
  weekly. This one had no client history, so restyling before first sight was the right call; from
  here on the ceiling applies.

## Third pass: the shared motion kit ("make the buttons react on hover, like Cloudflare")

- Applied the **BB motion kit** the estate way: a `foodbank` palette in `scripts/apply_motion_kit.py`
  (`CLIENTS`, light canvas / light surfaces, brand-purple accent, purple / lilac / coral wash) plus an
  `EXTRA_TARGETS` entry pointing at `dash/templates/dashboard.html`, because this client is a Jinja
  template rather than a single `dashboard.html`. One line in the script's target loop now skips a
  `CLIENTS` key that also appears in `EXTRA_TARGETS`. Re-apply with
  `.\.venv\Scripts\python.exe scripts\apply_motion_kit.py foodbank`; never hand-edit the blocks.
- Four adaptations so the kit lands cleanly: the tab PANEL sections were renamed `.tab` -> `.tabpanel`
  (the kit's `.tab:hover` lifts a clickable tab and would have lifted whole sections); `body` now
  carries the page colour and `.panel` / footer are transparent so the wash at z-index -1 shows
  between cards; KPI values carry the kit's `.value` hook and hero figures `.stat .v`, so both count
  up; `Chart.defaults.animation = false` was removed so the kit's 760ms entry animation and the
  scroll-to replay apply. A `<style>` host block was added to `<head>` for the kit's CSS.
- Tab-rail buttons and Sign out got the same lift / press vocabulary by class (the kit's selector
  list does not know `.tab-btn`). `switchTab` now swaps only its own `tab-*` body class so the kit's
  `bb-scrolled` state survives a tab change.
- Verified with the kit active: no console errors, no `NaN`/`undefined`, zero overflow, 65 surfaces
  tagged for reveal, hero figures still exact after the count-up writes the original strings back.

## Fourth pass: line chart + clickable metric cards

- The Overview's stacked area is now **one line per channel** (2.25px brand strokes over a faint
  8% fill so the pale coral and lilac lines stay anchored on white). No stacking.
- **Metric cards are selectors** (the VMCH clickable-card vocabulary: cursor, dot after the label,
  keyboard Enter/Space, `aria-pressed`, a 2px brand rule on the plotted card). On the Overview, the
  five hero figures and the eight efficiency cells all plot onto the daily chart: reach, impressions,
  frequency, video views, visits, spend, CPM, clicks, CTR, CPC, view rate, CPV, cost per visit. On
  Website, the eight cards switch the trend line (visits, engaged sessions, engagement time, cost per
  visit, downloads, sign-ups, donations, donated value) over the impression bars, at day or week grain.
- Rates are computed per bucket from summed parts (`OV_METRICS` / `SITE_METRICS` read one
  channel-day or period bucket); a day with no denominator is left as a gap, never drawn as zero, and
  the tooltip total only appears for additive metrics. The chosen metric survives range and channel
  changes (`state.ovMetric`, `state.siteMetric`).
- The active rule is a `::before` pseudo-element rather than a box-shadow so the motion kit's hover
  lift cannot replace it.

## Fifth pass: the approved countdown login (design/login_reference.html)

- `design/login_reference.html` is the client-approved login and the single source of truth. It was
  split the repo way: markup -> `templates/login.html`, CSS -> the `login` block at the end of
  `static/css/dashboard.css` (login-only tokens joined the shared `:root`), JS -> `static/js/login.js`.
  Sync by overwriting. Port mapping, applied every time: the reference's `.field` wrapper is
  `.pw-field` (the dashboard owns `.field` for its masthead) and its `--line` is the shared
  `--cream-line` (same value); every login selector is scoped to `body.login-page` so nothing leaks
  into the dashboard, which shares the stylesheet.
- Wiring: the inert demo `attempt()` is gone. The card is a real `<form method="POST" action="login">`,
  so Enter and the button submit natively; a rejected password comes back server-rendered with
  `class="error on"` (visible without JS) and `login.js` shakes the card once. Error copy, show/hide,
  error-clears-on-input all kept. The placeholder inline SVG became the real cream Foodbank SVG at
  64px; the `<img class="thq">` line is uncommented and points at `thinkhq-logo-cream.png`.
- Unchanged, as instructed: the counter is the only thing in the left column (eyebrow, label,
  number, resolve line); `START = 3_500_000`, `DURATION = 8_000`, `LOOP = false`; the label stays
  `white-space:nowrap` above 1080px and wraps below with no max-width; the resolve line copy; the
  commented-out source line; palette, radii, coral button with ink text; the reduced-motion path.
- **Verification note - headless Edge cannot run requestAnimationFrame for 8 real seconds** (under
  `--virtual-time-budget` timers fast-forward but rAF advanced ~400ms; `--timeout` and
  `--deterministic-mode` did no better). The countdown was therefore proven with a fake-clock Node
  run of the shipped `login.js`: lands on 0 at exactly 8,000ms, `.zero` + resolve on the next frame,
  still 0 at 60s with no timer pending (LOOP=false), reduced-motion lands immediately. The
  `screens/00-login.png` capture uses `--force-prefers-reduced-motion`, which renders the identical
  landed state (0, glow, resolve line).
- Checked: 18/18 server-side checks (form posts, wrong password 401 with the error visible, direct
  dashboard URL and `data.json` bounce without a session), typeable from first paint (autofocus,
  input enabled), no console errors, label nowrap at 1440 / wraps at 390, both logos load at 64px and
  15px, no CSS in the login block that the template does not use.

## Bugs found and fixed during QA

- **Chart.js v4 plugin options are truthy proxies when unset.** The value-label plugin drew numbers
  on every chart (stacked area, reach curve, site trend). Every custom plugin now requires an
  explicit option (`mode` string / `label` string / `bands` array / `labels` array).
- **Negative zero.** Pacing printed `-0.0%` and `A$-0` at exact delivery; `fmt.money` / `fmt.delta`
  now clamp sub-precision values to 0 and place the sign before the currency prefix.
- **Cap-aware allocation in the generator.** Quartile counts for a Connected TV row could exceed the
  row's video impressions under noise; the allocator now water-fills against per-row caps so totals
  stay exact AND every bound holds.

## QA results (2026-09-03)

- `data/generate_sample.py`: **61/61** reconciliation assertions pass (daily -> channel -> grand
  totals exact; CPM/CTR/CPV identities; reach <= impressions; dedup reach < channel sum; splits sum
  to 100%; all 56 days deliver on all 3 channels; every row bounded).
- Login flow via the Flask test client: **43/43** - fail, succeed, refresh, logout, direct-URL bypass
  (401 on `/data.json`), password never in any page, zero occurrences of "100% Digital" /
  "Transmission" / "TODO" / "lorem" in rendered output, all assets 200.
- Headless Edge harness across 3 ranges x 7 tabs + channel toggles: no `NaN` / `undefined` /
  `Infinity` / `null` in rendered text, zero console errors, zero horizontal overflow, 16 live
  charts, no broken images, last channel chip cannot be unticked. Hero figures tie to the anchors
  exactly (5.1M reach, 24.9M impressions, 4.9x, 6.6M video views, 54.2K visits, CPM A$7.44).
- Screenshots: `screens/00-login.png` (+1280x800, +390x844 via a fixed-width iframe, since headless
  Edge enforces a minimum window width), `screens/01-overview.png` ... `07-methodology.png`.
- Contrast: every text pairing >= 4.5:1; cream on the login card 14.9:1; ink on coral 7.5:1.

## Preview -> live checklist

See README.md -> "Flipping preview -> live". In short: build the data path and job, flip
`DATA_MODE = "live"`, run `deploy/deploy_foodbank.ps1`, register the Think HQ agency + Foodbank tile
in the platform registry, add to status monitoring, update `md/AGENTS.md`.
