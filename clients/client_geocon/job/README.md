# clients/client_geocon/job/ — the Export Job (stage 2: BigQuery views → `geocon.json`)

> A **Cloud Run Job** (`geocon-export`) that reads this client's BigQuery views, assembles one
> tidy JSON file, and uploads it to the private data bucket. It runs, finishes, and stops.

**Plain English:** this is the *kitchen*. On a frequent schedule (every 10 minutes — and whenever
we run it by hand) it checks whether any upstream data actually moved, and only if it did does it
pull the prepared numbers out, pack them into a single file the dashboard knows how to read
(`geocon.json`), and put that file in locked storage. It does **not** talk to any ad platform —
the shared Windsor connectors and the native Google Ads DTS transfer already mirrored the source
data, and this client's [`sql/`](../sql/README.md) views did the filtering and maths.

**Where this sits:** `raw_windsor.*` + `raw_google_ads.*` → [`../sql/`](../sql/README.md) views →
**[this job]** → `gs://bidbrain-analytics-geocon-dash/geocon.json` →
[`../dash/`](../dash/README.md) serves it.

> **This README was a stale copy of `client_mongodb/job/README.md`** until 2026-08-24 — it
> described Snowflake mirrors, Salesforce and TTD pixel feeds that have never existed here.

---

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The job. Runs the freshness gate, then (only if stale) reads the views, builds the `env = {…}` payload, caches Meta creative thumbnails, uploads `geocon.json`, and writes the watermark. |
| [`freshness.py`](freshness.py) | The shared self-gating helper, vendored per job folder (`probe_bq_last_modified`, `read_watermark` / `write_watermark`, `is_stale`). No heavy top-level imports so a no-op tick stays a light container. |
| [`Dockerfile`](Dockerfile) | `python:3.12-slim`, non-root `appuser`, `COPY main.py freshness.py`, `CMD python main.py`. |
| [`cloudbuild.yaml`](cloudbuild.yaml) | Build → push → deploy (for a future push-to-`main` trigger; deploys are manual today). |
| [`requirements.txt`](requirements.txt) | `google-cloud-bigquery` + `google-cloud-storage`. |

---

## The payload

One object. The parts that matter:

| Key | What it carries |
|---|---|
| `meta` | client, currency, `last_updated`, `data_through`, `date_min`/`date_max`, `row_count`, `default_property` |
| **`properties[]`** | **per development**: `key`, `label`, `status`, `flight`, `benchmarks`, `targets`, **`plan[]`** (the signed media plan, one entry per bought line) and `plan_channels` |
| `flight` / `benchmarks` / `targets` | **legacy top-level keys**, holding the DEFAULT development's values — see below |
| **`rows[]`** | the fact: one row per (date × **channel** × campaign × adset × ad), each carrying `property`, `channel` and the **`plan_line`** it was bought under |
| `breakdowns[]` | Meta-only audience (age × gender) + placement facts |

**The legacy top-level keys are deliberate.** The job and the dashboard deploy separately, so a job
deploy that lands first must not change what the live dashboard renders. `flight` / `benchmarks` /
`targets` therefore still carry the default development's values, exactly as before; the current
dashboard reads `properties[]` and ignores them.

**Ratios are never stored.** CTR/CPM/CPC/CPL are recomputed client-side from summed components, so
any date sub-range the user picks is exact.

**Google conversions are carried and labelled, never folded into `leads`.** A Google search
conversion and a Meta lead form can be the same person enquiring twice.

---

## Two guardrails in the job

**1. It refuses to publish an empty fact.** A transient upstream failure must not blank a live
dashboard by overwriting good JSON with nothing — the job raises and leaves the previous
`geocon.json` in place (the caltex / schneidersecpwr pattern).

**2. It ALARMS on out-of-scope delivery** rather than absorbing it. Two warnings, both printed with
the offending campaign names and the spend involved:

- **scope audit** — rows on a shared platform table that matched no development (`'Unmapped'`).
  They are excluded from every KPI by construction, so this has to be loud or an entire channel
  could go missing in silence. Fix: widen `targets/property_map.csv`, re-seed, `FORCE_REBUILD=1`.
- **plan audit** — non-Meta delivery that matched no media-plan line. It IS counted, but it paces
  against nothing. Fix: widen that line's `match_pattern` in `targets/media_plan.csv`.

---

## Self-gating freshness (every 10 min, rebuild only on real change)

This job is **self-gating** (see the repo CLAUDE.md "Freshness contract"). Cloud Scheduler ticks it
every 10 minutes UTC ([`../scheduler.ps1`](../scheduler.ps1)), but each tick first does a cheap
metadata probe and **exits 0 without rebuilding unless an upstream actually advanced**:

- **Gate source** = the four raw tables this job's views read, set in `GATING_TABLES`:
  `raw_windsor.perf_meta`, `raw_windsor.perf_linkedin`, `raw_windsor.perf_the_trade_desk` and
  `raw_google_ads.p_ads_CampaignBasicStats_3451896252`. It probes their
  `__TABLES__.last_modified_time` (metadata-only) and `data_through` is the newest of them.
- **The Google Ads probe points at the BASE `p_ads_` table, never at a DTS bridge view** — a
  bridge view's `last_modified` is frozen forever (the repo-wide DTS fact in CLAUDE.md).
- **The three non-Meta tables are shared with other clients**, so their delivery also trips this
  gate and geocon rebuilds more often than its own data strictly changes. That breadth is the
  point: gating on Meta alone would leave a new channel's first day invisible for up to 24h, which
  is the failure the contract exists to prevent. A no-op tick is a metadata read and costs nothing.
- **Watermark** = a tiny `_freshness.json` sidecar in this client's own bucket. Order matters:
  upload `geocon.json` **first**, write the watermark **second**, so a failed upload retries next
  tick.
- **Manual override**: `FORCE_REBUILD=1` bypasses the gate. **A seed or view change is invisible to
  the gate**, so always force the job after editing `targets/*.csv` or `sql/*.sql`.

---

## Deploy

```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/geocon-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients\client_geocon\job --tag $IMG --region australia-southeast1
gcloud run jobs update  geocon-export --image $IMG --region australia-southeast1
gcloud run jobs execute geocon-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```

Read the run log — the summary line prints rows / leads / spend **per development × channel**, and
any scope or plan warning appears above it.

## See also

- [`../README.md`](../README.md) — the client overview and the 3-stage pipeline.
- [`../sql/README.md`](../sql/README.md) — the views this job reads.
- [`../dash/README.md`](../dash/README.md) — serves the JSON this job writes.
