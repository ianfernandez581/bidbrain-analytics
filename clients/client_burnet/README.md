# client_burnet - Burnet Institute (PREVIEW, no data)

Melbourne medical research institute and registered charity (burnet.edu.au). The dashboard reports
**paid media and fundraising**: spend and delivery across Meta, Google Ads, The Trade Desk and
LinkedIn, against donations, donation revenue, gift sizes and the appeal themes people gave to.
Agency: **100% Digital** (not Transmission, not Extra Black).

**Status: PREVIEW.** No feed is connected. There is deliberately **no `sql/`, no `job/`, no
BigQuery dataset and no scheduler** - the dashboard serves a baked-in sample payload behind a
preview notice, exactly like `client_geyervalmont` and `client_lacevo`. Every figure on screen is
placeholder data and the page says so in five places: the topbar chip, the notice bar, a chip on
every card that renders a figure, the KPI band captions and the `PREVIEW_` export filename prefix.

The login is **real**, not a mock gate: a password in Secret Manager, a Burnet-only session secret,
and the platform SSO path scoped to this client key.

Live preview URL, once deployed: `https://burnet-dash-516554645957.australia-southeast1.run.app/`
Through the front door: `dashboards.bidbrain.ai` -> 100% Digital portal -> Burnet Institute ->
**Open preview ->**.

---

## File map

| Path | What it is |
|---|---|
| `dash/dashboard.html` | The whole UI. Four tabs: Overview, Paid Media, Fundraising, Internal Notes. Renders entirely from `/data.json`. |
| `dash/main.py` | Flask gate: login, platform SSO, `/data.json`, `/internal/notes.json`, `/logo.svg`, `/icon.png`, `/healthz`. |
| `dash/placeholder.json` | The sample payload. **Generated - do not hand-edit.** |
| `dash/internal_notes.json` | Staff-only content for the Internal Notes tab. Kept OUT of `data.json` on purpose. |
| `dash/platform_sso.py` | Vendored verbatim from the platform. Byte-identical to all 21 copies; never edit one. |
| `dash/logo.svg` | The lockup, served at `/logo.svg` for the login card. Generated. |
| `dash/icon.png` | The mark alone, rasterised, for the browser tab. Generated. |
| `creatives/burnet-lockup.svg` | The supplied artwork. Every variant derives from this. |
| `creatives/burnet-mark.svg` | The glyph alone, no wordmark. |
| `dash/Dockerfile`, `requirements.txt`, `cloudbuild.yaml` | Container. No trigger is wired; deploys are laptop/ship driven. |
| `dash/deploy_dash_burnet.ps1` | Redeploy the service after editing anything under `dash/`. |
| `deploy_burnet.ps1` | One-shot idempotent standup (APIs, bucket, SA, secrets, service). |
| `gen_placeholder.py` | Builds `dash/placeholder.json` and asserts it reconciles. |
| `gen_brand_assets.py` | Derives both served assets from the master and injects the inline lockup. |

Platform side (outside this folder):
- `bidbrain-platform/dash/config.py` - the `burnet` CLIENTS entry + membership of the 100% Digital agency.
- `bidbrain-platform/dash/set_burnet_tile.py` - surgical live-registry upsert for the portal tile.
- `scripts/apply_motion_kit.py` / `apply_login_kit.py` - the two palette entries (see "Branding").
- `scripts/enable_platform_sso.ps1` - `burnet` is in its `$ALL` list.

---

## Branding

This is the one place Burnet departs from the house look. Cloudflare's dashboard is dark because
**Cloudflare's brand** is dark; Burnet is a medical research NGO whose own site is white on a pale
peach ground, so this runs **light**. The COMPONENTS are the house set - the sticky control bar
holding the tab rail, KPI cards with a lit bar on the bottom edge, filter chips carrying their
series colour, the orange-ruled callout, the vs-plan table, pacing bars with a dashed on-pace
marker. Only the palette changes.

Tokens taken from burnet.edu.au and used exactly:

| Token | Value | Where |
|---|---|---|
| brand orange | `#F76E3B` | **fills and rules only** - the KPI stripe, bar fills, active chips, the tab underline |
| logo mark | `#ED6E3B` | the artwork's own orange |
| deep | `#BD572F` | **any orange that has to be READ** - labels, links, the submit button fill |
| lit | `#F9A85C` | the lighter end of every orange gradient |
| peach ground | `#FDF0EA` | the page wash, the login card, the callout |
| hairline | `#F9D4C4` | every border and grid line |
| ink | `#27272A` | body text, the dashed pace marker |
| channels | `#9BBAE5` `#F99D46` `#CC9EDE` `#A1D487` | Meta / Google Ads / The Trade Desk / LinkedIn |

**THE ONE RULE THAT MATTERS: brand orange is a FILL and a RULE, never TEXT.** `#F76E3B` on white is
**2.9:1** - it fails AA at every size, so an orange label, an orange link or an orange number is
unreadable however right it looks in a swatch. And white ON `#F76E3B` is the same 2.9:1 the other
way. So:

- anything orange that must be read is the **deep `#BD572F`** (4.6:1 on white, 4.2:1 on the peach);
- anything sitting **on** an orange fill takes near-black ink (`--on-accent: #2A1408`), not white;
- the submit button is filled with the deep, not the bright.

That is the same "which shade depends on what it sits on" rule `client_lacevo` carries for its clay,
and getting it backwards in either direction turns a brand colour into an invisible border. It is
also why the two kits take **different accents**: `apply_motion_kit.py` gets the bright `#F76E3B`
(it only ever paints an outline, a hover border, the scroll rail and a row's inset edge), while
`apply_login_kit.py` gets the deep `#BD572F` (that kit paints its show/hide control and its Caps
Lock hint IN the accent colour, so the bright one would ship an unreadable control).

### Typefaces

**Burnet's own faces are not available to us.** The site uses **Degular** and **Adelle Mono**
through Adobe Fonts, domain-locked to burnet.edu.au, so serving them from
`dashboards.bidbrain.ai` would be a licence breach and would simply not load. The dashboard uses
**Inter**, which is the estate's own face (`client_cloudflare` and `client_sophiie` load it, and it
heads the fallback stack everywhere else). Small caps labels are Inter uppercase at 11px with
`.06em` tracking - the house `.kpi .label` treatment - not a mono face.

Ask whether `dashboards.bidbrain.ai` can be added to Burnet's Adobe web project. It is question 6
on the Internal Notes tab. If it can, the change is the two `<link>` tags and the `--sans` stack.

**THE LOGIN AND THE DASHBOARD ARE CURRENTLY IN DIFFERENT TYPEFACES, and that is a loose end, not a
decision.** The login design supplied on 2026-09-18 is set in **Figtree** with **IBM Plex Mono** for
its small-caps labels - the pairing the original reference preview used, and a closer stand-in for
Degular + Adelle Mono than Inter is. The dashboard behind it is still Inter. One click apart, that
is visible. Whichever way it resolves it is a one-line change at each end: point the login's
`--sans`/`--mono` at Inter, or add the Figtree + Plex Mono `<link>` to `dashboard.html` and swap its
font stack. Do not leave it split once someone has an opinion.

### The login page

The login is **not** the plain centred card the rest of the estate uses. It is a two-column stage:
the card on the right, and on the left an animated SVG of **clonal selection** - an antigen arrives,
the one lymphocyte whose receptor matches it is selected while the others fade back, and that cell
alone divides into a clone. That is **Burnet's own theory**: Frank Macfarlane Burnet took the 1960
Nobel Prize for it, and it is the single idea the institute is named for. Five shape chips under the
illustration re-run it with a different antigen; it also cycles on its own every 7.5s, and stops
dead under `prefers-reduced-motion`.

Three things about it are load-bearing:

- **An element is positioned by EITHER its SVG `transform` attribute OR by CSS `transform`, never
  both** - CSS wins outright and discards the attribute. So every CSS-animated group is an empty
  wrapper and the coordinates live on an inner group the CSS never touches. Flatten those wrappers
  and the whole illustration collapses to the origin.
- **It is CSS transitions on ~20 nodes, not a rAF loop.** A login page should not run an animation
  frame loop (the `client_sophiie` rule); this one only toggles classes on a timer.
- **The show/hide control belongs to the LOGIN KIT, not to the design.** The supplied file carried
  its own `.show` button; it was removed, because the kit's toggle is the one that also warns about
  Caps Lock and blocks a double POST. The design's chip styling was kept by scoping `.card .bb-pw-t`
  above the kit's own rule - the kit block is injected LAST, so anything client-specific that has to
  beat it needs the extra specificity, not just to sit earlier in the file.

The card is a real `<form method="post" action="login">`. The supplied file was a mock - its button
only focused the field - so the form, the `name="password"`, the submit button and the `{{ error }}`
line are ours. `action` is **relative** on purpose.

Two corrections were made to the supplied design, both the same class as the colour rule above:
the footer note was `#8A8A85` on the peach card (**3.05:1**, fails AA) and is now `#6B6B66` (4.8:1);
and its one client-facing em-dash became a hyphen. The button gradient `#C05A2E`-`#B04E26` under
white is 4.4:1 at the top and 5.3:1 at the bottom - it passes as large bold text and was left alone.

### The logo

The supplied artwork is a **single-colour vector** - seven paths, one fill - which makes it much
easier to work with than a raster master: there is nothing to key out, and a recolour is one
attribute. `gen_brand_assets.py` is the only thing that should ever write the derived files:

| Output | What | Where |
|---|---|---|
| `dash/logo.svg` | the full lockup | served at `/logo.svg`, rendered on the login card |
| `dash/icon.png` | the MARK alone, rasterised 96px, brand orange on transparent | the browser tab |
| inside `dashboard.html` | the full lockup, INLINE | the topbar |

**The lockup ships twice, and the inline copy is injected rather than pasted.** Behind the platform
proxy the dashboard is served at `/d/burnet/`, where a root-relative `/logo.svg` resolves to the
PLATFORM's namespace and 404s - the same gotcha `client_geyervalmont` and `client_lacevo` carry. The
login page is served from the service root, so it CAN use the route. The difference here is that the
second copy sits between `<!-- BB-BURNET:lockup -->` markers and `gen_brand_assets.py` rewrites it,
so the two can never drift.

**The tab icon is the MARK, not the lockup**, because the wordmark is illegible at 16px - and it is
brand orange rather than the deep, because orange carries on both light and dark browser chrome.

**Rasterising needs a Chromium.** There is no SVG rasteriser in the repo venv (PIL cannot read SVG)
and adding `cairosvg` would drag the cairo DLLs onto every Windows box, so the generator drives
headless Chrome or Edge - already on every dev machine, and already how this estate renders
dashboards for verification. Set `CHROME_PATH` to override. If neither is found it says so and
leaves the existing `icon.png` alone rather than writing a broken one.

**Both brand URLs are content-hashed (`/logo.svg?v=<sha>`).** They are served `max-age=86400`, which
is right for artwork - but on the Lacevo standup it meant that when the real lockup replaced the
placeholder, every browser that had already opened the login served the OLD one for a full day and
the deploy looked like it had silently failed. The client saw it before we did.

---

## Preview mechanism

`meta.placeholder` is the single switch. `main.py` serves `dash/placeholder.json` at `/data.json`
whenever the bucket has no real `burnet.json`; that payload carries `placeholder: true`, and the
dashboard derives the notice bar, the topbar Preview chip, the per-card `placeholder` tag and the
`PREVIEW_` export prefix from it. The moment an export job writes a real object to the bucket, that
wins and every one of those disappears - **no code change and no redeploy.**

The bucket is created EMPTY by the standup script precisely so this path is exercised from day one
rather than on go-live day.

---

## Data contract - the shape the pipeline must emit

This is the last leg of the repo's three-stage contract, matched BY NAME:

    sql/*.sql view column  ->  job/main.py env dict key  ->  dashboard.html DATA.* key

There is no `sql/` or `job/` yet, so the contract below is what a future job MUST emit. Build to
this shape and the template does not change - that is the point of the preview.

| Key | Shape | Notes |
|---|---|---|
| `meta` | object | `placeholder`, `client`, `agency`, `currency_symbol`, `period_label`, `date_min`/`date_max`/`data_through`, `scopes[]`, `scope_default`, `feeds_connected`, `feeds_expected`, `sessions` |
| `targets` | object | `derived` (drives the `(derived)` label everywhere), `note` |
| `flight` | object | `start`, `end`, `days_total`, `days_elapsed`, `days_covered`, `pace_through`, `budget` |
| `daily[]` | `date, spend, impressions, clicks, donations, revenue` | the ONLY dated array |
| `channels[]` | `channel, colour, spend, impressions, clicks, donations, revenue, budget, plan_ctr, plan_cpm, plan_cpc, plan_cost_per_donation` | the paid GRAIN |
| `appeals[]` | `appeal, short, donations, revenue` | the health theme used in the creative |
| `gift_bands[]` | `band, gifts, revenue` | display order is array order |
| `fundraising` | object | `one_off`, `regular_giving`, `largest_gift`, `email_signups`, `revenue_basis` |

**Almost nothing is carried precomputed, and that is deliberate.** CTR, CPM, CPC, cost per donation,
return per $1, average gift, the donation rate, every share, expected-to-date and the gap to pace
are all DERIVED in the browser from the arrays above. A precomputed headline sitting beside a table
the reader can filter out from under it is how two panels on one page start disagreeing, and a
preview exists to build trust in the numbers.

`gen_placeholder.py` asserts the reconciliations the real job will also have to hold: daily
donations = channel donations = appeal donations = gift-band gifts = one-off + regular; daily
revenue = channel revenue = appeal revenue = gift-band revenue; daily spend / clicks / impressions =
the channel totals; channel budgets = `flight.budget`.

---

## Things that were decided here, not inherited

**The plan benchmarks are ours and the UI says so, on every delta.** No media plan has been signed.
`targets.derived` drives a literal `(derived)` in each of the four vs-plan column headers, in the
card title ("vs our working benchmarks"), in the notice bar and in the card footnote. An unlabelled
red delta accuses a campaign of missing a KPI nobody agreed to - the caltex rule. Drop the flag in
the same edit that replaces the `plan_*` values with the signed plan.

**The cost-per-donation verdict colour is withheld under 30 donations.** LinkedIn has 24: one gift
moves its cost per donation by more than 4%, so a confident green "-12% vs plan" is a claim the data
cannot support. The NUMBER still prints - only the colour is withheld, and the footnote names the
channel and the reason. Same guard `client_sophiie` added after its ad-group table rendered
"+1261% vs target" in green off five clicks.

**The total row compares against nothing.** Summing four channels' benchmarks would invent a blended
target nobody set, and its delta would then move with the channel MIX rather than with performance.
Those cells are dashes, deliberately.

**Pacing is drawn to the last day the DATA covers, not to today.** `flight.days_covered` and
`pace_through` are carried separately from `days_elapsed` for exactly this reason: every ad feed
lags, so an expectation drawn to today divides loaded spend by unloaded days and reports the
campaign as behind by construction - in the direction that makes the agency look like it is
underdelivering. The card names the date it is drawn to. Being over budget is not a win either: the
bar reads "ahead of pace" and only within 5% of the mark is green.

**Channel chips are on the Paid Media tab only.** Not an oversight. The Overview headline is blended
by definition and the daily series carries no channel column at all, so a chip there would either
visibly fail to move the figures beside it or, worse, silently move half the panel. Same rule
`client_schneider` applies to its platform chips and `client_lacevo` to its channel chips. The
**appeal** chips sit inside the appeals card for the same reason - appeal is not on the daily series
or the channel split, so it can only honestly scope that one panel, and the caption says so.

**The period control is a statement, not a picker.** `daily` is the only dated array; channels,
appeals and gift bands are whole-period aggregates. A date filter today would move the KPI band
while every table under it stayed put. It becomes a real picker the day those aggregates carry a
date column, and its `title` says so.

**The scope control is built from `meta.scopes`.** Two entries today - "Fundraising AU" live and
"Research profile" disabled as `- coming soon` - so it renders as a select. With one entry it
renders as a plain label instead, because a select holding one real option is a control that cannot
do anything (the `client_geocon` property-selector rule). A second live lane is a payload change.

**Every KPI stripe is the brand colour.** It briefly carried a channel colour on the blended tiles
(cost per donation in Trade Desk purple, regular givers in LinkedIn green), which reads as "this
figure is that channel's" when the figure is every channel's. On this page a colour means a channel;
a blended KPI has no channel, so it takes none. The one headline tile per band is set apart by a
surface (`.kpi.accent`), not a hue.

**`[hidden]` is forced to `display:none`.** The UA stylesheet's `[hidden]{display:none}` loses to ANY
author rule that sets `display`, so `.filter-row{display:flex}` silently defeated `el.hidden = true`
and the channel filter rendered as an empty labelled strip on the tabs that do not use it. One rule
at the top of the stylesheet, rather than remembering it at every toggle site.

**Nothing new had to be built for this client.** Fundraising is a metric set the estate has not
reported before - donations, gift-size bands, regular givers - but structurally they are counts,
money and share-of-total, which the existing KPI cards, bar rows and vs-plan table already cover.
The four-section shape with a staff-only Internal Notes tab already exists three times over
(`client_lacevo`, `client_schneidersecpwr`, `client_cloudflare`).

---

## Internal Notes - how it is protected, and how far that goes

Two mechanisms, following `client_schneidersecpwr`'s Reports tab and `client_lacevo`'s notes tab:

1. **The tab is not built** unless `window.BB_INTERNAL` is set. The platform proxy injects that in
   `<head>` only for superadmin / admin / owning-agency sessions - the same `_internal_allowed`
   predicate that decides whether the staff Internal Notes widget is injected. A client session, and
   any direct `*.run.app` URL, never receives it, so the tab is absent, its pane stays empty, and
   `#notes` in the URL falls back to Overview.
2. **The content is not in `data.json`.** It is fetched from `internal/notes.json` only when that
   tab opens, so hiding the tab is not the only thing standing between a client and it.

**The honest limit: that route authenticates but does not authorize by ROLE.** This service cannot
yet tell a staff session from a client one - the `bb_sso` cookie carries the allowed-CLIENT list,
not the role - so a logged-in client who guessed the path would be served it. Closing that means
putting the role in the SSO token in `platform_sso.py`, which is vendored into every dashboard in
the estate. **Until then, nothing genuinely sensitive goes in `internal_notes.json`** - today it
holds feed status and questions to ask, which is the right ceiling for it. The pane says as much on
its own face, so a staff screenshot carries the caveat with it.

The fetch URL is **relative** (`internal/notes.json`, no leading slash), like Lacevo's and unlike
secpwr's root-relative one, so it resolves under both origins: `/d/burnet/internal/notes.json`
behind the proxy and `/internal/notes.json` direct.

---

## Deploying

| You changed | Run |
|---|---|
| anything under `dash/` | `clients\client_burnet\dash\deploy_dash_burnet.ps1` (also what `/ship` runs) |
| `gen_placeholder.py` | `.\.venv\Scripts\python.exe clients\client_burnet\gen_placeholder.py` then the dash deploy |
| `creatives/*.svg` | `.\.venv\Scripts\python.exe clients\client_burnet\gen_brand_assets.py` then the dash deploy |
| `bidbrain-platform/dash/config.py` | `bidbrain-platform\dash\deploy_dash_platform.ps1` |
| first-ever standup | `clients\client_burnet\deploy_burnet.ps1`, then `set_burnet_tile.py --yes` |

Deploys need `ian@100.digital` (charles@ has no perms): `$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"`.

After the standup, run `scripts\enable_platform_sso.ps1 -Keys burnet` so the platform's `bb_sso`
cookie opens this dashboard without a second password. Without it the dashboard still works, on its
own password only.

---

## Not wired yet (deliberate)

- **No `/report` AI deck.** It needs `roles/aiplatform.user`, an `enable_report_burnet.ps1`, a
  vendored `bb_deck.js` and a client-specific prompt set. None of that is worth wiring while every
  number is a placeholder. `requirements.txt` is correspondingly shorter than the live tenants'
  (no `anthropic`, no `httpx`) - add them back alongside a real `report.py`.
- **No status-pipeline entry.** `status_dashboard/job/main.py`'s `BQ_CLIENTS` verifies a JSON against
  BigQuery; there is no dataset to verify against. The registry's `show_pending_row` flag gives it
  the greyed "awaiting connection" row on the Data Accuracy tab instead, which is the honest state.
  **When it goes live, adding it to `BQ_CLIENTS` ALSO requires adding it to the bucket-grant list in
  `status_dashboard/job/deploy_job_status.ps1`** - missing that 403s, and that 403 aborts the whole
  BigQuery accuracy section for EVERY client (it happened on the Sophiie standup).
- **No Extra Black visibility.** Burnet is attached to 100% Digital only. Dual visibility for an
  external agency is a per-client decision, never a default - and `external: True` would strip the
  staff Internal Notes tab, which is where this dashboard keeps its open questions.

---

## FLIPPING PREVIEW TO LIVE

In order:

1. **Answer the open questions first**, especially *what the campaign is actually for*, *what counts
   as a donation* and *which donation platform Burnet uses*. All three change the SHAPE of the views,
   not just their values, and the third decides the entire Fundraising tab.
2. **Get the feeds.** Meta partner access, Google Ads manager link (and a separate customer ID if a
   Google Ad Grant account exists - it must report as its own channel, never blended into paid
   spend), Trade Desk advertiser ID plus donation event tags, LinkedIn ad account, GA4 read access.
   The current asks are tracked on the Internal Notes tab.
3. **Get the signed media plan**, then replace the `plan_*` benchmarks and channel budgets and set
   `targets.derived` false. Until then every delta stays labelled.
4. **Build `sql/` + `job/`** to the data contract above, with `job/freshness.py` vendored in (the
   repo's freshness contract binds every export job: self-gating on a `*/10` tick, watermark in a
   `_freshness.json` sidecar, and never watermark a VIEW).
5. **Re-run `deploy_burnet.ps1`** - it will need a `-WithData` branch adding for the dataset, the job
   service account and the scheduler; copy it from `clients/client_sophiie/deploy_sophiie.ps1`.
6. **Set `meta.placeholder` false** in the job's output (not in the template).
7. **Flip the tile**: in `set_burnet_tile.py` set `STATUS = "active"`, `NOTE = ""` and the campaign
   tuple's status to `"active"`, then re-run with `--yes`. Mirror it in `config.py` and drop
   `show_pending_row`.
8. **Set the client password** in the super-admin console, or grant each named person's
   Google/Microsoft email to this dashboard there. **Do not hand out the 100% Digital agency
   password** - it opens every other 100% Digital client.
9. **Add to the status pipeline** (see the two-list warning above).
