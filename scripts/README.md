# scripts/ — onboarding & daily credential preflight (Windows)

> The "get this repo running on a fresh Windows laptop" helpers, plus a quick check
> you run at the start of each session so nothing surprises you mid-task.

**Plain English:** these are convenience scripts for the person operating the platform from a
Windows machine. One sets the laptop up the first time (installs Python + the Google Cloud
tools, logs you in). The other is a 10-second morning check that you're still logged in to
Google Cloud, so the data loaders don't fail halfway through. None of this is part of what
runs in the cloud — the cloud pieces build themselves from each unit's own files.

**Where this sits:** these scripts prepare your **local machine** to run the
[`windsor_data_pull/`](../windsor_data_pull/) and [`snowflake_data_pull/`](../snowflake_data_pull/)
loaders and the client export jobs. They don't touch production directly beyond logging you in.

---

## What's in here

| File | What it does | Run it… |
|---|---|---|
| [`setup.ps1`](setup.ps1) | **One-time machine setup.** Installs Python 3.12 and the Google Cloud SDK if missing (via `winget`), verifies the committed `requirements.txt` files are present, creates an isolated `.venv` and installs deps into it, then logs you in to gcloud (both CLI creds **and** application-default creds), and verifies it can read the Windsor secret + reach BigQuery. **Idempotent.** | once, right after cloning |
| [`start_day.ps1`](start_day.ps1) | **Per-session preflight.** Verifies both credential systems gcloud uses (CLI creds for `gcloud secrets`, and application-default creds for the Python client libraries), pins the project, confirms it can read `windsor-api-key`, and pings BigQuery (`raw_windsor`). Reauths in a browser if anything expired. | start of each work session |
| [`setup.cmd`](setup.cmd) | Double-clickable launcher for `setup.ps1` (runs it with `-ExecutionPolicy Bypass` so you don't fight Windows script policy). | instead of `setup.ps1` if you prefer double-click |
| [`start_day.cmd`](start_day.cmd) | Double-clickable launcher for `start_day.ps1`. | instead of `start_day.ps1` |

---

## How to use

```powershell
# First time on a new machine (from the repo root):
.\scripts\setup.ps1          # or double-click scripts\setup.cmd

# Every session after that:
.\scripts\start_day.ps1      # or double-click scripts\start_day.cmd

# Then run a loader with the venv's Python:
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py
```

---

## Why two credential systems are checked

gcloud keeps **two** independent logins, and the org enforces periodic reauth on both, so
either can expire without the other:

- **gcloud CLI credentials** — used by `gcloud …` commands, including the `gcloud secrets`
  call the loaders make to fetch the Windsor key.
- **Application Default Credentials (ADC)** — used by the Python client libraries
  (`google-cloud-bigquery`, `-storage`, `-secret-manager`). This is why the committed code is
  portable: it reads secrets via ADC, with **no machine-specific gcloud path** baked in.

`start_day.ps1` checks both up front so you never hit a surprise reauth prompt halfway through
a long loader run.

---

## Notes & gotchas

- **The committed source is portable as-is.** These scripts are a *convenience* — they never
  edit tracked files. On macOS/Linux you don't need them: `python -m venv`, `pip install -r
  requirements.txt`, and `gcloud auth application-default login` are enough (see the root
  [README Quickstart](../README.md#quickstart)).
- **The `.venv` is a dev-only superset.** `setup.ps1` installs both
  [`requirements.txt`](../requirements.txt) (loaders + setup scripts) and
  [`client_mongodb/job/requirements.txt`](../client_mongodb/job/requirements.txt) (the export
  job) into one venv — they pin compatible versions so they coexist. The **dash** web app is
  deliberately excluded (it pins an older `google-cloud-storage` that conflicts). Each Cloud
  Run unit still builds its own container from its own `requirements.txt`, so this local venv
  never affects image builds.
- **`Test-Probe` (in `setup.ps1`):** under `$ErrorActionPreference = "Stop"`, redirecting a
  native command's stderr (`2>$null`) turns expected probe failures into *terminating* errors
  that would abort the whole script. `Test-Probe` drops to `Continue` and judges success purely
  by exit code, so an "expected to fail" check (e.g. not-logged-in) falls through to the login
  step instead of killing the script.
- **Known dangling reference:** the closing hints in `setup.ps1` mention
  `.\scripts\run-export-job.ps1` (a local export-job runner). **That file isn't in the repo
  yet.** To run the MongoDB export job locally today, use the commands in
  [`client_mongodb/README.md`](../client_mongodb/README.md) instead.

## See also

- [Root README](../README.md) — the whole-platform map and the cross-platform Quickstart.
- [`windsor_data_pull/`](../windsor_data_pull/README.md) / [`snowflake_data_pull/`](../snowflake_data_pull/README.md) — what you run *after* setup.
