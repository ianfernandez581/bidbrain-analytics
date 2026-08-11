# Platform health assessment - dashboards.bidbrain.ai

Read-only pass, 2026-08-09. Nothing was edited, deployed, staged, synced or written.
`POST /sync-all` was NOT called. No brute-force probe was run against `/extrablack`.

**Updated 2026-08-09 (second pass).** `gcloud` auth was restored, so sections 1 (freshness),
2 (reconciliation), 6 (Cloud Run) and 7 (Scheduler) are now **verified** and carry findings
F13-F17. F3 (default passwords) is **RESOLVED**. Section 4 (browser render) remains unverified.
Two files carry uncommitted changes authored outside this session - left untouched, see
"Uncommitted work in the tree".

## Summary

- **16 findings**: 3 live-and-dangerous, 4 latent, 6 silent-wrong, 3 cosmetic.
  (F3 resolved and closed; F13-F17 added by the second pass.)
- **Worst**: any single-dashboard client login can `POST /sync-all` and force-rebuild every
  Snowflake client's export job. The tier check at `main.py:1473` admits `"client"`.
- **Same-day attention**: F1 only, and it is a one-line tier fix. F13 (Trade Desk ingest failing
  every morning for 9+ days) is the runner-up and is losing nothing yet, because the evening run
  covers for it.
- **No user-visible outage.** All 13 pipelines report healthy, 129 of 131 accuracy checks match,
  all 23 scheduler jobs are enabled and last-attempt green, and no service has code drift.
- The Extrablack external-tenant hardening audits well. The gap is the **client tier**, which that
  pass did not touch.

---

## Coverage - what I could and could not verify

Stating this up front because several requested sections are unanswered, and an unanswered
section must not read as a passing one.

| Section | Status | Why |
|---|---|---|
| 1. Data freshness (all clients) | **DONE** (2nd pass) | Live `status.json`, 13 clients, 38 source watermarks. |
| 2. Reconciliation "X/Y match" chips | **DONE** (2nd pass) | 131 checks read from live `status.json`. |
| 3. Buttons and endpoints | **DONE** | Route table + decorators + live unauth probes. |
| 4. Dashboards render | **STILL NOT VERIFIED** | No browser automation and no dashboard passwords. Static JS gate only. |
| 5. Auth boundaries | **MOSTLY DONE** | Code-level + live unauth probes. |
| 6. Cloud Run services/revisions | **DONE** (2nd pass) | 22 services, revision counts, deploy-vs-source drift. |
| 7. Cloud Scheduler / jobs | **DONE** (2nd pass) | 23 jobs + 300 recent executions. |
| 8. Registry integrity | **PARTIAL** | Live registry blob not read; code-level only. |
| 9. Secrets in git | **DONE** | Clean. |
| 10. Dependencies / dead paths | **DONE** | |
| 11. Known outstanding items | **5 of 6 DONE** | 11a still needs the registry blob. |

The only remaining gap is **section 4**: rendering every dashboard in a real browser needs
browser automation (absent) and the per-dashboard passwords (not supplied). The `A$0` /
zero-height-bar / `undefined` class of defect is therefore **unassessed**, not clean. Section 8
needs one read of the private registry blob, and 11a falls out of the same read.

**Verified good** (worth recording, so a later pass does not re-litigate): every privileged route
correctly 403s or redirects when unauthenticated (16 probed); no secrets committed in the
Extrablack range; no hardcoded `run.app` URLs in live code; the external deny-by-default
allow-list is keyed on Flask **endpoint names**, so a future route is closed to external tenants
by construction; external payload prep fails **closed** (502, never pass-through).

---

# Tier 1 - live in production now

No user-facing outage was confirmed. These are defects that are true in production right now and
carry real consequence.

### F1. Any client-dashboard login can force-rebuild every client's pipeline

**What.** `POST /sync-all` fires `FORCE_REBUILD=1` on six `<c>-export` jobs plus `status-export`.
Its only tier gate is:

```python
_EDIT_ROLES = ("agency", "client", "admin", "superadmin")   # main.py:1165
...
if session.get("kind") not in _EDIT_ROLES:                  # main.py:1473
    abort(403)
```

`"client"` is in that tuple. A client session is what the platform issues when someone logs in
with a single dashboard's own password (`_establish_session`, `main.py:386-390`) - a password
that is handed to clients and revealed in the god-mode console.

The second gate does not help. `_ext_setting("show_sync")` resolves through
`_session_agency()`, which returns `None` for any non-agency session (`main.py:306-310`), and
`agency_setting(None, ...)` falls to `INTERNAL_DEFAULTS` = permissive (`store.py:97-103`).

**Evidence.** `bidbrain-platform/dash/main.py:1165`, `:1473-1482`; `store.py:97-103`.
The in-code comment at `main.py:1475-1478` reasons only about *external agencies* - correct as far
as it goes, and it is why this was missed: the Extrablack hardening pass secured the agency tier
and the client tier was never in scope.

**How bad.** This is the exact endpoint the brief flags as having previously rebuilt the pipeline
by accident. Any of ~13 client passwords reaches it. Cost and cross-client blast radius: one
client can trigger *every other client's* export job.

**Fixing would touch.** `_EDIT_ROLES`, or a local tier check in `sync_all`. Note `_EDIT_ROLES` is
shared with `api_status` and `_can_edit`, so narrowing the tuple changes three call sites - F2 is
the same root cause and would be fixed by the same edit.

---

### F2. Client sessions can stage and deploy accuracy-check definitions

**What.** Same root cause. `_can_edit` (`main.py:1207-1216`) is
`session.get("kind") in _EDIT_ROLES and _may_open(client) and _ext_setting("edit_definitions")`.
For a client session that is `True and True and True`. So a client can:

- `POST /definitions/<own-client>` - write an arbitrary staged definitions doc to the status
  bucket (`main.py:1407`), and
- `POST /deploy/<own-client>` - which calls `_run_status_deploy` and executes the privileged
  `status-deploy` Cloud Run job (`main.py:1441-1459`, `:1219-1229`).

`/deploy` requires a staged doc first, which the same session can create.

**Evidence.** `main.py:1207-1216`, `:1396-1459`. The `_can_edit` docstring already flags internal
*agency* access as a deliberate open question - it does not mention the client tier, which
suggests the client tier was not considered here either.

**How bad.** A client can run a production job that reseeds and promotes accuracy definitions and
rebuilds dashboards. Bounded to their own client key by `_may_open`, which is the saving grace.

**Fixing would touch.** The same `_EDIT_ROLES` decision as F1.

---

### F3. ~~Committed default passwords are the registry seed values~~ - **RESOLVED**

> **RESOLVED 2026-08-09**, confirmed by the platform owner. The seeded passwords have been
> rotated, so the literals below are dead credentials and no longer grant access. No action
> outstanding on the live system.
>
> The one piece worth carrying forward as **cleanup, not risk**: the literals are still present in
> `config.py:26,34,35` and the platform deploy script still sets no env override, so a future
> re-seed of a fresh registry would reintroduce them. Moving those three to the Secret Manager
> pattern `enable_super_admin.ps1` already uses for `SUPER_ADMIN_PW` would close that door.
> Tracked as cleanup below; not a live exposure.

Original finding, retained for the record:

**What.** `config.py` ships real literals:

```python
ADMIN_PW               = os.environ.get("ADMIN_PW", "bidbrain-admin-2026")   # :26
AGENCY_100D_PW         = os.environ.get("AGENCY_100D_PW", "100d2026")        # :34
AGENCY_TRANSMISSION_PW = os.environ.get("AGENCY_TRANSMISSION_PW", "transmission2026")  # :35
```

`store._seed_doc()` hashes these into the registry at seed time (`store.py:166`), and
`bidbrain-platform/dash/deploy_dash_platform.ps1` sets **no** `--set-env-vars` and **no**
`--set-secrets` at all. `deploy_platform.ps1:122` even prints a warning that the default is
`bidbrain-admin-2026` and should be overridden before seeding.

`SUPER_ADMIN_PW` and `AGENCY_EXTRABLACK_PW` correctly default to `""` and fail closed
(`config.py:29-39`), which shows the pattern is understood - these three are the ones that
predate it.

`resolve_password` checks the **registry hash** for admin and agency, with no live env fallback
(`store.py:352-356`) - which is why rotation in the god-mode console was sufficient to close this,
with no code change or redeploy needed.

**Residual (cleanup only).** Removing the three literals from `config.py` so a future fresh seed
cannot reintroduce them.

---

### F4. `/definitions` and `/deploy` are live privileged endpoints with no UI anywhere

**What.** Grepping every template and every proxy-injected widget for callers finds **zero**
references to `/definitions/<client>` or `/deploy/<client>`. `templates/` contains no occurrence
of the string `definit` at all.

`md/AGENTS.md` describes this feature as shipped - "editable from the platform Data Accuracy tab
('Make this live')" - and `deploy_definitions`' own docstring is `"'Make this live'"`. The button
does not exist in `_status_merge.html` or any other template.

**Evidence.** `grep -rni "definit" bidbrain-platform/dash/templates/` returns nothing.
Route handlers at `main.py:1396`, `:1407`, `:1441`.

**How bad.** Either the editor regressed out of the UI and nobody noticed the feature is gone, or
it never shipped and the docs are wrong. Either way there is a reachable, job-triggering endpoint
that no button guards and no one is watching. It also means the Cloudflare `definitions.json`
workflow described in AGENTS.md is currently a manual/BQ-side process, not a UI one.

**Fixing would touch.** Either `templates/_status_merge.html` (restore the editor) or the three
route handlers (remove them). Deciding which needs a human who knows the intent. Also
`md/AGENTS.md`, whichever way it goes.

---

### F13. `windsor-tradedesk-ingest` fails every morning and has for at least 9 days

**What.** The job is scheduled twice daily (`35 1,21 * * *`). The **21:35 run succeeds; the 01:35
run fails**, every day, and has done since at least 2026-07-31.

```
windsor-tradedesk-ingest-sk9xp   FAILED    2026-08-09T03:05:16Z
windsor-tradedesk-ingest-bnmmz   ok        2026-08-08T21:52:57Z
windsor-tradedesk-ingest-c559h   FAILED    2026-08-08T03:05:20Z
windsor-tradedesk-ingest-lpgcm   ok        2026-08-07T21:46:11Z
...
windsor-tradedesk-ingest-5lwbt   FAILED    2026-08-01T23:35:37Z
windsor-tradedesk-ingest-nw4pd   FAILED    2026-07-31T23:35:40Z
```

The two most recent failures both complete at **03:05:1x** after a 01:35 start - a flat ~90 minute
runtime landing on the same second twice, which is the signature of a task timeout, not a data
error. It is the only job in the project with a recurring failure.

**Evidence.** `gcloud run jobs executions list --job=windsor-tradedesk-ingest`. Trade Desk is a
shared loader: Caltex, VMCH, City Perfume, ResetData, TLM, MongoDB, Cloudflare, HireRight,
Schneider, SchneiderLQAI and PropTrack all read `raw_windsor.perf_the_trade_desk`.

**How bad.** **Nothing is being lost today** - the evening run lands the data, and every TTD source
watermark sits at 2026-08-07, normal reporting lag. So this is a failure with no current symptom.
It matters because it is a silent 50% failure rate on the loader that feeds eleven dashboards: the
day the 21:35 run also fails, TTD goes stale everywhere at once and the alerting that should have
caught this has been green throughout. It also burns ~90 minutes of job time daily for nothing.

Worth noting the platform has no failure alerting at all - I found this by listing executions, not
because anything surfaced it. That is the more general gap.

**Fixing would touch.** `ingest/windsor_data_pull/` Trade Desk loader and its job config
(timeout / date-window). Diagnosing why the early run times out while the late one does not is the
first step - the Caltex note in `md/AGENTS.md` that "TTD refuses same-day dates" and the loader
"walks back from yesterday" is a plausible lead, since the 01:35 UTC run sits at a different point
in the TTD reporting day than the 21:35 one.

---

# Tier 2 - would break the next time X happens

### F5. Admin "Edit client" silently strips dual agency membership

**What.** `store.upsert_client` re-homes a client to exactly one agency:

```python
if agency_slug:                                    # store.py:519-526
    for a in doc["agencies"]:
        keys = a.get("client_keys", [])
        if a["slug"] == agency_slug:
            if key not in keys: a["client_keys"] = keys + [key]
        elif key in keys:
            a["client_keys"] = [k for k in keys if k != key]     # <- strips every other agency
```

Geocon, ResetData and Geyer Valmont are deliberately dual-homed (`x100-digital` **and**
`extrablack`, per `enable_extrablack.py:8-10`, which calls this out as
"NEVER removed"). The next admin who opens one of those clients in the admin tree and clicks Save
- even changing only the display name - drops it from Extrablack's portal.

**Evidence.** `store.py:500-527`. Confirmed unchanged; this is known item 11d, and it is
**reproducible from code**. Nobody has touched it.

Note the contrast one function up: `upsert_agency` **does** preserve `external`,
`google_allowlist` and every `EXTERNAL_SAFE_DEFAULTS` key across an edit (`store.py:484-489`),
with a comment explaining exactly why. The same care was not applied to client membership.

**How bad.** Silent. Extrablack simply loses tiles; no error, no log. Recovery is re-running
`enable_extrablack.py`, which is why this has been survivable so far.

**Fixing would touch.** `store.upsert_client` - the strip-others branch. Needs a decision on how
the admin UI should *express* multi-homing, since the form currently sends a single `agency_slug`.

---

### F6. MongoDB's dashboard permanently fails its own pre-deploy JS gate

**What.** `scripts/_validate_dash_js.py` reports
`inline <script> #0 FAILED to parse -> Line 171: Unexpected token .` for
`clients/client_mongodb/dash/dashboard.html`. The offending line is optional chaining:

```js
const lbl=(k.querySelector('.label')?.textContent||'').trim(), ...   // colorKpis()
```

That is valid ES2020 and every browser runs it. The validator's parser predates it.

**Evidence.** All 16 client dashboards run through the gate; MongoDB is the only failure, and it
is a false positive.

**How bad.** `md/AGENTS.md` warns about precisely this failure mode: "the file then permanently
fails the gate, masking real errors". MongoDB is the template client and its dashboard is the most
heavily edited in the repo. A genuine syntax error there is now invisible to the gate.

**Fixing would touch.** `scripts/_validate_dash_js.py` (newer parser), not the dashboard. Worth
re-running across all clients afterwards, since other files may be sitting on the same blind spot.

---

### F7. The `/extrablack` rate limiter is per-process and in-memory

**What.** 5 failures per IP per 15 min, 15 min lockout (`main.py:506-509`), stored in a plain dict
(`_login_fails`). The code documents its own limits honestly at `main.py:502-505`: effective limit
is `instances x 5`, and any restart or new revision clears it.

**Not tested against production.** Verifying it empirically means making failed logins against a
live tenant portal, which would lock out this egress IP for 15 minutes and, because the counter is
per-process, would not produce a trustworthy result anyway. Static read only.

**How bad.** Fine against casual guessing, thin against a distributed or patient attacker on a
public, tenant-named, guessable URL. The code names Cloudflare WAF as "the real control" - I could
not confirm from here whether that WAF rule actually exists.

**Fixing would touch.** Either a shared counter (the platform bucket, or Firestore) or an edge
rule. Confirming the Cloudflare WAF rule is the cheaper first step.

---

# Tier 3 - wrong but nobody has noticed

### F14. A finished campaign and a dead connector look identical, and both read "Healthy"

**What.** Four source watermarks are more than three weeks behind while their client's headline
verdict is `ok`:

| Lag | Client(s) | Source | data_through |
|---|---|---|---|
| 40d | cloudflare | Reddit Ads - APAC_ALL | 2026-06-30 |
| 39d | **stt, hireright, schneider** | DV360 - APAC | 2026-07-01 |
| 26d | vmch | raw_windsor.perf_ga4 | 2026-07-14 |

**These are almost certainly fine.** 2026-06-30 and 2026-07-01 are the Q2 boundary, so Reddit and
DV360 have the shape of **ended flights**, not broken feeds - and Cloudflare's dashboard already
auto-hides channels that did not run in the selected window. VMCH's stale Windsor GA4 is the
*fallback* leg; its DTS twin `raw_ga4.perf_ga4` is current at 2026-08-08, so the stale one is
correctly unused. I am deliberately not calling these incidents.

**The finding is the ambiguity, not the dates.** `_verdict`/`_verdict_bq`
(`status_dashboard/job/main.py:1732-1778`) decide health from *when our ingest last ran against
the source*, never from *how old the data in it is*. So a source that stopped producing rows 40
days ago is indistinguishable from one that finished its flight - both stay green. The frontend
does append a "· N sources behind" hint (`_status_merge.html:242`), but the chip still reads
"✓ Healthy", and the hint is the only signal.

**How bad.** Low today, and the DV360 case is the one to think about: **one source, three
clients**, which is exactly the fan-out that would make a genuine connector outage expensive.
The day a live campaign's feed dies, this is the mechanism that will let it sit unnoticed - which
is close to what already happened with the LinkedIn grant lapse.

**Fixing would touch.** `status_dashboard/job/main.py` verdict logic - it would need to know each
source's expected flight window to tell "ended" from "died", which is a real modelling question,
not a threshold tweak. A cheaper interim: surface source age on the chip rather than as a suffix.

---

### F15. The retired `status-dash` service is still deployed and publicly answering

**What.** `md/AGENTS.md` states "the standalone `status-dash` service is retired and its `dash/`
source deleted". The service is still live:

```
status-dash   https://status-dash-p32gk2wuia-ts.a.run.app   HTTP 200
              revision status-dash-00004-l4h, last deployed 2026-06-17
```

Its source is gone from the repo, so what it serves is a 2026-06-17 image nobody can rebuild,
review or patch - showing pipeline-health data from whatever it can still reach.

**How bad.** Low-to-moderate and easy to miss. It is an unmaintained public surface presenting
internal pipeline state, pinned to an image whose source no longer exists. Also worth confirming
what its login gate actually is, since the UI it duplicated now lives behind the platform login.

For contrast, the other two non-client services are both correct: `pacing-grid` returns **403**
(IAM-gated internal tool, as intended) and `adriatic-dash` returns **200** by design - it is the
open sample dashboard `md/AGENTS.md` explicitly flags as a no-auth pattern not to copy.

**Fixing would touch.** Deleting the service, or restoring its source if it is still wanted.

---

### F16. Two GA4 transfers documented as broken have quietly recovered

**What.** `md/AGENTS.md` records two GA4 outages as current:

- City Perfume's native GA4 transfer "stalled 2026-07-02" - live watermark is
  `raw_ga4.perf_ga4 = 2026-08-08`.
- VMCH's GA4 Data Transfer "failing on a permission error (frozen 2026-06-01)", with the Windsor
  loader as fallback - live watermark is `raw_ga4.perf_ga4 = 2026-08-08`.

Both are current. The DTS route recovered; nobody updated the docs.

**How bad.** Harmless to the data, actively misleading to an engineer. VMCH's staging views still
run the DTS-first-then-Windsor precedence logic built for the outage, and the City Perfume note
tells a reader that GA4 there is dead. Someone acting on either would waste a day, or "fix"
something that is working.

**Fixing would touch.** `md/AGENTS.md` (the vmch and cityperfume rows) and
`clients/client_vmch/README.md`. Whether to retire VMCH's Windsor fallback path now that DTS is
healthy is a separate call - it is currently 26 days stale and doing nothing.

---

### F8. `EXTRABLACK_EXPOSURE_2.md` is cited three times and has never existed

**What.** `main.py` points a reader at this document at `:2220`, `:2468` and `:2501` - including
from the comment justifying the payload scrub block-list as "a deliberate exception", and from the
one explaining the raw-vs-billed spend commercial decision.

The file is not in the working tree, and `git log --all -- "*EXTRABLACK_EXPOSURE*"` returns
nothing. It was **never committed**, so it is not recoverable from history. No `_1` exists either.

**Evidence.** `find . -iname "*EXPOSURE*"` empty; `git log --all` empty.

**How bad.** Two of the three citations sit on genuinely non-obvious security decisions
(block-list-instead-of-allow-list, and shipping grossed spend rather than raw). The reasoning
those comments defer to is lost. This is known item 11c - confirmed still dangling, and worse than
"dangling": there is nothing to link to.

**Fixing would touch.** Either write the doc, or inline the reasoning into the three comments and
delete the references.

---

### F9. The Grid's per-objective KPI is an unimplemented passthrough

**What.** `grid-core/src/central/calc.js:212-220`:

```js
/** KPI Performance - marked [DERIVED] but no formula is defined yet ...
 *  TODO: implement per-objective KPI computation once the rule is specified. */
function kpiPerformance(c) {
  return c.kpiPerformance === undefined || c.kpiPerformance === '' ? null : c.kpiPerformance;
}
```

**How bad.** Depends on whether anything renders it as a computed figure. The executive dashboard
work is described as carrying "per-objective metrics", so a column that looks derived may be
echoing input or blank. Worth a look before that dashboard is shown to anyone senior.

**Fixing would touch.** `calc.js` plus whatever the rule turns out to be - needs a definition
first, not code.

---

### F10. Contradictory docstrings on the spend-multiplier store

**What.** `clean_multipliers` says an explicit `1.0` is **KEPT**, with a careful paragraph on why
"no markup" and "nobody has decided yet" must be distinguishable (`store.py:43-51`). Twelve lines
of the same file later, `set_spend_multipliers` says the map is "sanitised + minimised (**1.0
dropped**)" (`store.py:596`). The code does the former; the second docstring is stale.

**How bad.** Small, but it sits on the exact distinction that decides whether an external tenant
sees a spend figure or has it suppressed (`main.py:2827-2832` treats "no multiplier" as
"suppress every money field"). Someone trusting the stale docstring could reintroduce the drop.

**Fixing would touch.** One docstring in `store.py`.

---

# Tier 4 - cosmetic and cleanup

### F17. Revision accumulation on the long-lived services

**What.** Every service keeps every revision ever deployed. Current counts:

```
platform-dash 126   cloudflare-dash 102   resetdata-dash 86   schneider-dash 84
mongodb-dash   70   geocon-dash      47   stt-dash       43   vmch-dash      36
tlm-dash       32   proptrack-dash   29   cityperfume-dash 28  central-grid  26
pacing-grid    26   caltex-dash      18   hireright-dash 18   ...
```

Roughly 700 revisions across 22 services.

**How bad.** Cosmetic. Idle revisions with `min-instances=0` cost **nothing** to keep - there is no
runaway bill here, and this is not the finding a cost review would want. The two real limits are
the 1,000-revisions-per-service quota (platform-dash at 126 is the closest, and nowhere near) and
the container images accumulating in Artifact Registry, which do carry storage cost. Listing the
revision console for `platform-dash` or `cloudflare-dash` is also just unpleasant.

**Fixing would touch.** An Artifact Registry cleanup policy, and optionally a revision-retention
setting. Not urgent; worth doing once.

---

### F11. Double "Log out" on two proxied dashboards

**Confirmed, and narrower than assumed.** The proxy injects a fixed-position logout pill into
*every* proxied dashboard (`_LOGOUT_BUTTON`, `main.py:1803-1819`, injected at `:2804`). Only two
client dashboards also ship their own logout control in their header:

- `clients/client_resetdata/dash/dashboard.html:346`
- `clients/client_tlm/dash/dashboard.html:202`

Both are `onclick="location='/logout'"`, which is root-relative on the platform origin and so
resolves correctly - the duplicate button works, it is just a duplicate. The other 14 dashboards
show one control. This is known item 11f.

**Fixing would touch.** Two lines in two dashboards (remove the in-page button), or a proxy-side
suppression. Removing the in-page one would break those dashboards' standalone `run.app` view,
which still needs its own logout - so the proxy-side option is the safer of the two.

---

### F12. ResetData Reddit `spend * 2` - unchanged, still deferred

**What.** `clients/client_resetdata/sql/04b_stg_reddit.sql:23`:
`ROUND(spend * 2, 2) AS spend_aud,    -- AUD billed rate`

**Status.** Present, commented, documented in `md/AGENTS.md` as an intentional agency billed-rate
markup. **No accidental migration** - no other client's SQL carries a bare spend multiplier, and
nothing in the recent range touched this file. Known item 11b: confirmed clean.

Worth noting the second-order effect the code already flags: `_status_entry_for_external` drops
the `note` field for external tenants specifically because ResetData's Reddit note states the x2
markup in plain English (`main.py:1261-1262`). That mitigation is in place and correct.

---

## Verified live state (second pass)

### 1. Freshness - all 13 pipelines healthy

`status.json` generated `2026-08-09T13:15:33Z`, tolerance 45 min. **All 13 clients: verdict `ok`.**
No client where Data Accuracy claims current but the watermark disagrees - the build watermark and
the verdict agree everywhere. The four materially old *source* watermarks are F14, and are
probably ended flights rather than faults.

**The Geocon / ResetData tile-age question (11e) is answered: it is ingest cadence, not a
threshold, and it is not fixable by tuning one.**

| Client | build_at | Age at snapshot | Only upstream |
|---|---|---|---|
| geocon | 2026-08-08T21:20 | **~16 h** | `raw_windsor.perf_meta` |
| caltex | 2026-08-08T22:00 | ~15 h | `raw_windsor.perf_the_trade_desk` |
| vmch | 2026-08-08T22:02 | ~15 h | Windsor TTD + GA4 |
| resetdata | 2026-08-09T09:21 | ~4 h | Google Ads DTS + Windsor |
| mongodb / cloudflare / stt / hireright / schneider / proptrack | 2026-08-09T13:11 | ~4 min | Snowflake (`*/10`) |

Geocon's only source is Windsor Meta, loaded once a day by `windsor-meta-ingest-daily` at 21:15.
The export job self-gates on upstream advancing (the freshness contract), so it correctly rebuilds
**once per day** and the tile age cycles 0 to 24 hours. ResetData sits at ~4 hours because its
Google Ads DTS leg advances more often. Snowflake clients rebuild every 10 minutes, which is why
they always look instant by comparison.

So the tiles are behaving exactly as designed; what is wrong is that "16 hrs ago" *reads* as
staleness next to a sibling tile saying "4 mins ago", when both are equally current with respect
to their own upstream. Any fix belongs in the wording (e.g. age relative to the source's own
cadence), not in the pipeline.

### 2. Reconciliation - 129 of 131 checks match

| | Count |
|---|---|
| Total checks across 13 clients | **131** |
| Match | **129** |
| Fail | **1** |
| n/a | **1** |

No pattern to group: no single broken source taking down a check family, no schema change
breaking a family, no cluster of long-standing ambers. Per client: mongodb 9/9, cloudflare 23/24,
stt 12/12, hireright 12/12, schneider 5/5 +1 n/a, schneiderlqai 4/4, proptrack 13/13,
cityperfume 10/10, resetdata 17/17, tlm 8/8, geocon 6/6, caltex 5/5, vmch 5/5.

**The one failure** - cloudflare, "CF1 CS · Rejected", group "Content Syndication · CF1 (Double
Touch)": source **17** vs dashboard **20**. The check's own note calls this out as expected:
Cloudflare CS is derived in BigQuery from the `raw_snowflake` mirror while Salesforce leads are
continuously added and re-statused, so a small delta against a live source query is mirror lag.
A 3-lead gap on a re-statusing lifecycle field is exactly that shape. Not worth chasing; worth
deciding whether a check that is expected to disagree should be allowed to show red at all.

**The one n/a** - schneider, "Global Rebrand Activation · CS leads": source `None`, dashboard `0`.
Also explained in-note: global_rebrand has `flight_start 2026-07-01` with no end seeded, and the
clamp yields 0 delivered leads because the programme is awareness-only with no CS lane. Correct
behaviour rendering as an n/a rather than a match.

### 6. Cloud Run - 22 services, no drift

All 22 services serve their latest ready revision at 100%. **No deployed-vs-repo drift**: I
compared each service's last deploy against the last commit touching its source directory, and
every service post-dates its source. The one apparent exception, `caltex-dash` (deployed
2026-08-07, source touched 2026-08-08), is commit `5f5b698` touching **`README.md` only** - and
doc-only changes deploy nothing by design.

Revision accumulation is F17; the orphaned `status-dash` service is F15.

### 7. Scheduler - 23 jobs, all enabled, one recurring failure

All 23 jobs are `ENABLED`, every one has a live target, and none is overdue against its cadence.
13 client `*-export` jobs on `*/10`, `status-export` on `*/15`, `snowflake-ingest` on `*/10`,
6 Windsor ingest jobs plus Neto nightly, and `pacing-snapshot-daily`.

The four clients with no export job - **bellshakespeare, nextsmile, geyervalmont, adriatic** - are
correct: all four are documented as preview/placeholder deployments with no pipeline.

Failures across the last 300 executions:

- **`windsor-tradedesk-ingest` - recurring, see F13.**
- `status-export` - a burst of ~25 consecutive failures on **2026-07-30, 16:47 to 22:34 UTC**
  (~7 hours). Self-recovered; nothing since. Worth one look at what happened, since during that
  window the Data Accuracy tab would have been serving a stale `status.json` while every dashboard
  carried on fine - the monitor was down, not the pipelines.
- `schneider-export` - one isolated failure, 2026-08-06T08:41. No recurrence.

Everything else is green.

## Known outstanding items - status

| # | Item | Status |
|---|---|---|
| 11a | Transmission `internal_notes: false` | **Write almost certainly LANDED** - strong indirect evidence, see below. Not confirmed against the registry blob (not read). Code path is sound: an explicit key wins (`store.py:100-101`) and `upsert_agency` preserves it across admin edits (`store.py:487-489`). |
| 11b | Reddit x2 in `04b_stg_reddit.sql` | **Confirmed unchanged**, line 23. No migration. See F12. |
| 11c | `EXTRABLACK_EXPOSURE_2.md` reference | **Still dangling, and never existed in git.** See F8. |
| 11d | Admin Edit single-homing | **Reproducible from code, untouched.** See F5. |
| 11e | Geocon/ResetData "6-7 hrs ago" freshness | **ANSWERED - not a defect.** Geocon ~16 h, ResetData ~4 h at snapshot; both correct for their ingest cadence. Structural, not a threshold. See section 1 above. |
| 11f | Double "Log out" | **Confirmed**, exactly 2 of 16 dashboards. See F11. |

---

## Uncommitted work in the tree (not mine, not assessed, not touched)

The working tree was clean when this assessment started and is not now. Two files carry
uncommitted changes that appeared **between the two passes**, authored outside this session:

```
 M bidbrain-platform/dash/main.py                (+20)
 M clients/client_cloudflare/dash/dashboard.html (+15)
```

They add `_internal_flag_script()` / `window.BB_INTERNAL` to the proxy and gate Cloudflare's
native "Internal Notes" card behind it. **I left both exactly as found** - not staged, not
reverted, not reviewed as part of this assessment.

Two things follow that matter here:

- **This is the evidence for 11a.** The new code comments state the empty-notes shell is "what
  Transmission saw once their agency was set `internal_notes:false`", and that the card "rendered a
  heading over an empty mount". That is a first-hand account of the flag being live in production,
  so the registry write did land - and it had a visible side effect nobody had anticipated: an
  empty card that reads as broken. Someone is already fixing it. I still did not read the registry
  blob, so this is inference from an in-flight change, not direct confirmation.
- **It is not deployed.** Live `platform-dash` is revision `00126-ld6` (2026-08-09T04:44 UTC),
  which predates these edits. So the empty-shell behaviour is still what Transmission sees right
  now, and the fix ships on the next `/ship` or platform deploy.

## Registry integrity - what code review alone can say

The live registry is a private GCS blob I could not read, so this is partial.

- **Route/registry correspondence is structurally safe.** There is no per-client route table;
  `/d/<client>/` is one generic route resolving through `store.get_client` and `_upstream_base`,
  returning 404 for an unknown key (`main.py:2775-2776`). So "a route with no registry entry"
  cannot occur by construction. The reverse - a registry entry whose `url` is dead - is possible
  and needs live checking.
- **`config.py` is only the seed**, not live state. It still lists Geocon as
  `status: "coming_soon"` with an empty `url` (`config.py:142-143`) while Geocon is live on the
  Extrablack portal, so the seed has drifted from the registry. That is expected, but it means
  nobody should read `config.py` as truth for tile state - worth knowing before the fix session
  reaches for it.
- **`coming_soon` with a live URL is intentional in several places**, not a defect: Caltex,
  Bell Shakespeare, Next Smile and Geyer Valmont all carry a deployed preview URL while hidden
  from clients, and `_may_open` gives superadmin god-mode access to exactly those
  (`main.py:2442-2446`). Do not "fix" these.
- **Multipliers**: cannot enumerate which clients have them without the registry. The fail-closed
  behaviour is correct and worth confirming holds in practice - a client with no multiplier has
  **every money-shaped field suppressed** for an external session, not passed through raw
  (`main.py:2827-2832`). That means a missing multiplier on Geocon, ResetData or Geyer Valmont
  shows Extrablack a dashboard with blank spend rather than wrong spend. Check these three first.

## Dependencies

`bidbrain-platform/dash/requirements.txt` is fully pinned and current enough: Flask 3.0.3,
gunicorn 23.0.0, google-auth 2.35.0, requests 2.32.3, PyJWT[crypto] 2.9.0. Nothing stale enough to
flag. No hardcoded `run.app` URLs in live code - the only construction is the deliberate
deterministic `_runapp()` helper in `config.py:92-93`.

## Secrets

Clean. Across `4476239..HEAD` (the Extrablack range) no `.env`, key, credential file or plaintext
secret was committed. The only pattern hits are Secret Manager **resource names**
(`anthropic-api-key`, `geyervalmont-dash-password`), which are identifiers, not values.
`grid-core/.env` exists in the working tree, is untracked, and is covered by
`grid-core/.gitignore:6`. The only `.env*` files in history are `.env.example` templates.

Note F3 separately: those plaintext passwords are in `config.py` and **predate** this range, so a
scan scoped to the Extrablack window does not surface them.

---

## Suggested order for the fix session

Not a plan, just the dependency order I would expect.

1. **F1 + F2 together** - one `_EDIT_ROLES` decision resolves both, and F1 is the only same-day
   item left now that F3 is closed.
2. **F13** - diagnose why the 01:35 Trade Desk ingest times out. Nothing is being lost yet, so
   this is urgent-ish rather than urgent, but it feeds eleven dashboards.
3. **F4** needs a human intent call (restore the definitions editor, or delete the routes) before
   anyone writes code.
4. **F5** needs a product decision on how the admin form should express multi-homing, not just a
   code change.
5. **Section 4 is still open** - rendering the dashboards in a browser needs credentials and a
   browser. That is the last real coverage gap; the `A$0`/`undefined` class of defect remains
   unassessed.
6. The rest (F6, F7, F8, F9, F10, F14, F15, F16, F17, and the F3 config cleanup) are independent
   and can go in any order.

## What changed between the two passes

| | First pass | Second pass |
|---|---|---|
| Findings | 12 | 16 (F3 resolved, F13-F17 added) |
| Sections verified | 5 of 11 | 10 of 11 |
| Same-day items | F1, F3 | F1 |

Nothing found in the second pass contradicts the first. The infrastructure is in better shape than
the code review suggested: pipelines healthy, checks matching, no drift, no overdue jobs. The
open items remain concentrated in the **client-tier auth boundary** (F1, F2) rather than anywhere
operational.
