---
name: premium-polish
description: Make a Bidbrain surface feel more premium without re-skinning it - research-led UI/UX polish for the client dashboard estate, the platform front-door, or the bidbrainai-www marketing site. Use when asked to make something look or feel more premium, elevate, refine, polish, or "make it not look templated", and when reviewing a dashboard's visual/interaction quality. Encodes the estate's design system and the constraints that silently break it.
---

# Premium polish

Anthropic's `frontend-design` skill is the craft reference, but it is written to *reshape* UI:
"take one real aesthetic risk", "spend your boldness". On this estate that advice is wrong for
three of the four surfaces. This skill routes first, then applies the right ceiling.

## Step 0 - route by surface. Do not skip this.

| Surface | Where | Ceiling |
|---|---|---|
| **Client dashboard** | `clients/client_<c>/dash/dashboard.html` | **Subtle only.** Never a re-skin. |
| **Platform front-door** | `bidbrain-platform/dash/templates/` | Subtle only. Sibling layer, not the kit. |
| **The Grid** | `grid-core/` | Internal cockpit. Function over polish. |
| **Marketing site** | `bidbrainai-www` (`src/`) | **Bold is correct here.** Use `frontend-design` fully. |

Only the marketing site wants a distinctive point of view. Everything else is a working
instrument a client reads weekly, where a re-skin destroys familiarity and costs trust.

## The estate ceiling

**Polish is felt in motion, interaction and functionality - never in a re-skin. About 1% pixel
change at rest is the right order.** If a stakeholder can spot your change in a side-by-side
screenshot of the resting page, you went too far.

What counts as premium here, in priority order:

1. **Interaction quality** - hover/press/focus vocabulary, keyboard paths, a real Reset that knows
   what is filtered, `/` to focus search, Esc to clear.
2. **Honest states** - loading, empty, stale, withheld and error each say what is true and what to
   do next. A withheld figure is never rendered as `0`. A stale feed names itself.
3. **Typographic and spacing discipline** - tabular figures on numeric columns, consistent scale,
   nothing reflowing between renders.
4. **Motion that carries meaning** - a reveal that orients, not decorates.
5. **Colour and texture** - last, and smallest.

## Research phase - do this before proposing anything

1. **Read the client README first.** `clients/client_<c>/README.md` carries the client's approved
   look, what was built and removed on request, and why. A thing removed once must not come back
   as a "polish" idea. `md/AGENTS.md` carries the repo-wide rules.
2. **Render the current state and look at it.** See "Verify" below. Screenshot before you opine.
3. **Inventory the shared layer** - most polish belongs in `scripts/motion_kit/`, not in one file.
4. **Name what is actually weak.** Point at a component and say why it underperforms for the
   person reading it weekly. "Feels generic" is not a finding.
5. **Propose 3-6 changes with the ceiling attached**, cheapest and highest-confidence first, and
   say which are shared-layer versus single-client. Get agreement before building.

## Hard constraints - each of these has broken production

**The motion kit is INJECTED, not hand-written.** Canonical source `scripts/motion_kit/*.tpl`;
apply with `scripts/apply_motion_kit.py` (`--check`, `--revert`, or one client key), login twin
`apply_login_kit.py`. Editing the kit block inside a dashboard is wasted work - the next run
overwrites it. Client-specific CSS goes *above* the kit block in that client's own stylesheet.

**`cloudflare` and `sophiie` are excluded from the kit.** Cloudflare has its own richer
client-approved layer; Sophiie's aurora *is* its design. Do not unify either onto the kit.

**Never emit these strings** anywhere in injected content - the platform proxy string-replaces
them across the whole page, so even one inside a comment moves where it injects its widgets:
`</body>` `</head>` `</style>` `<body` `/data.json` `'/report'` `/creative-img/`.
The login kit additionally bans `{{` `{%` `{#` `"""` because `LOGIN_HTML` renders through Jinja.
Both lists are asserted in `FORBIDDEN` in the two scripts - keep it that way.

**Money must stay grossed correctly.** `bbApplySpendMult` runs right after `DATA` is parsed and
grosses raw spend per row by that row's OWN channel. Any new spend field or aggregate must be
grossed too (row spend stashes to `_rawSpend`); revenue/ROAS/MER stay on RAW spend. CSV exports
must filter `_`-prefixed keys or raw pre-markup spend leaks to the client. Moving where a money
field is read from counts as adding one - extend the shim in the same change.

**Chart.js v4: never put a function in `options.plugins.*`.** It is treated as a scriptable
option, auto-invoked, throws, and silently blanks the whole chart. Re-theme via global
`Chart.defaults` before any chart is built.

**Geometry uses `translate` / `scale`, never the `transform` shorthand** - several dashboards
already set a transform on a chip, caret or close button and the shorthand replaces it. Two
effects sharing one property compose through `@property` vars with `inherits:false`.

**`.dash-select` must stay SOLID.** Chrome paints the native `<option>` list from the select's
background; translucent means invisible options.

**Anything that hides content until an event fires needs an escape hatch.** `IntersectionObserver`
threshold must be `0` (a card taller than the viewport never reaches a fraction). Ship the
watchdog. `@media print` must un-hide everything. Losing an animation always beats losing a number.

**Respect `prefers-reduced-motion`** - CSS freezes, canvases `remove()` themselves so no rAF runs.

**No em-dashes in client-facing copy.** Use a hyphen. A stray em-dash reads as AI-written.

## Copy is design material

Name things by what people control, not how the system is built. Active voice; a control says what
happens ("Save changes", not "Submit"), and keeps that name through the whole flow. Errors explain
what went wrong and how to fix it, never apologise, never go vague. An empty screen is an
invitation to act. Sentence case, plain verbs, no filler.

## Verify - required before you call it done

```bash
# 1. Syntax gate (the repo's own). Sweeps the estate.
./.venv/Scripts/python.exe scripts/_validate_dash_js.py clients/*/dash/dashboard.html

# 2. Kit drift - confirms no hand-edit is about to be overwritten
./.venv/Scripts/python.exe scripts/apply_motion_kit.py --check

# 3. Render before/after with the SAME payload and diff the rendered TEXT.
#    Presentation-only changes must be byte-identical in text.
```

Render locally with puppeteer against either the real payload pulled from the client's GCS bucket
or a stub built from `job/main.py`'s keys. Probe both builds with the same data - a change that
alters a number is not a polish change.

Also confirm by hand: responsive to mobile, visible keyboard focus, reduced-motion honoured, no
horizontal body scroll, and every element id still present (grep the ids you touched).

## Deploy

Polish touches `dash/dashboard.html` and `dash/main.py` only, so
`clients/client_<c>/dash/deploy_dash_<c>.ps1` covers it - or `/ship`, which auto-deploys changed
services. No job, view or JSON change means **no forced job run needed**. If you edited
`scripts/motion_kit/`, re-apply to every client and deploy each affected dashboard.

## Definition of done

Update whatever the change made stale, in the same change: the client README for a single-client
gotcha, `md/AGENTS.md` for a repo-wide rule. One terse line. Never create a narrative summary file
about the work - the git log is the changelog.
