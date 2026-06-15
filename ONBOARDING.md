# Onboarding — Calvin (bidbrain-analytics)

Welcome. You now have **Owner** on the GCP project `bidbrain-analytics` (project #516554645957,
region `australia-southeast1`). That means full access to everything: BigQuery, Cloud Run
(jobs + services), Cloud Storage, Secret Manager, Cloud Scheduler, IAM, Artifact Registry, billing.

This repo is a monorepo of self-hosted client marketing dashboards. The day-to-day job is **editing
dashboards and deploying them** — and the fastest way to do that is to let **Claude Code** do the
reading, editing, and deploying for you. This guide gets you from a blank machine to "I just shipped
a dashboard change" — driving everything through Claude.

---

## 1. One-time machine setup (~15 min)

Do these once on your Windows machine. Use **PowerShell** for everything.

**a) Install Git** (needed to clone, and Claude Code uses it for its Bash tool):
- https://git-scm.com/downloads/win — accept defaults.

**b) Clone the repo and run the repo's own setup script.** It installs Python 3.12 + the gcloud
CLI if missing, creates the `.venv`, installs dependencies, and logs you into Google Cloud:

```powershell
git clone https://github.com/Bidbrain/bidbrain-analytics.git
cd bidbrain-analytics
.\scripts\setup.ps1
```

When the browser opens during `setup.ps1`, **log in as `calvin@100.digital`** (twice — once for the
gcloud CLI, once for application-default credentials). It finishes by verifying it can read a secret
and reach BigQuery — you want green `[OK]` lines.

**c) Install Claude Code** (native installer, auto-updates):

```powershell
irm https://claude.ai/install.ps1 | iex
```

Then verify:

```powershell
claude --version
claude doctor
```

**d) First Claude login.** From inside the repo, run `claude`. A browser opens — log in with your
**Claude.ai account** (must be Pro/Max/Team/Enterprise; free tier can't use Claude Code). Credentials
persist after that; use `/login` inside a session to re-auth later.

```powershell
cd C:\path\to\bidbrain-analytics
claude
```

> The project's `CLAUDE.md` is loaded automatically every time you start Claude in this repo — it
> already knows the deploy commands, naming conventions, and guardrails. You don't have to teach it.

---

## 2. Each working session (~30 sec)

Google's session policy expires your credentials periodically, so start each day with the preflight,
then open Claude:

```powershell
cd C:\path\to\bidbrain-analytics
.\scripts\start_day.ps1     # refreshes gcloud + ADC creds; pings Secret Manager + BigQuery
claude                      # or: claude -c  to resume the last conversation in this folder
```

If `start_day.ps1` pops a browser, just finish the login — that's the expected reauth.

---

## 3. How to actually make edits with Claude

You don't edit files by hand and you don't memorize gcloud commands. You **describe the change in
plain English** and let Claude find the file, make the edit, and deploy it. Claude already knows this
repo's rules from `CLAUDE.md`.

### The 8 client keys
`mongodb`, `cloudflare`, `stt`, `schneider`, `hireright`, `cityperfume`, `resetdata`, `proptrack`
(plus a meta `status_dashboard`). Everything for a client `<c>` derives from its key: dataset
`client_<c>`, bucket `bidbrain-analytics-<c>-dash`, job `<c>-export`, service `<c>-dash`,
subdomain `<c>.bidbrain.ai`. Each lives in `clients/client_<c>/` with `sql/` `job/` `dash/`.

### Two kinds of edit — say which one you want

| You want to… | What changes | Just tell Claude |
|---|---|---|
| Change a colour / label / card / layout | only `clients/client_<c>/dash/dashboard.html` | "On the **proptrack** dashboard, change the impressions card title to 'Total Impressions' and make the accent colour green." |
| Add / fix a **number** on screen | a 3-stage chain (see below) | "Add **weekly conversions** to the **resetdata** hero chart." |

### The data contract (why a number is sometimes 3 edits, not 1)
A value on screen traces through three files, matched **by name**:

```
sql/*.sql view column  →  job/main.py (env={…} dict key)  →  dashboard.html (data.* key)
```

So "add metric X" usually means: surface it in a `sql/*.sql` view → expose it in `job/main.py` →
render it in `dashboard.html`. Editing only the HTML renders nothing. Claude knows this — but if you
ask for a new metric, expect it to touch all three files.

### Let Claude deploy it
Deploys are **manual** (build the image, deploy as yourself — there are no auto-triggers, and
`cloudbuild` from a laptop fails on `actAs`). Claude knows the right script for each edit:

- Edited `dashboard.html` / `dash/main.py` → `clients/client_<c>/dash/deploy_dash_<c>.ps1`
- Edited a `sql/*.sql` view → `clients/client_<c>/sql/deploy_views_<c>.ps1`
- Edited `job/main.py` (the JSON shape) → `clients/client_<c>/job/deploy_job_<c>.ps1`

Just say **"deploy it"** after a change and Claude will run the matching script (rebuild → update the
Cloud Run service/job, re-run the export job). The service serves with `Cache-Control: no-store`, so
a redeploy shows up immediately at the dashboard URL.

### A good prompt looks like
> "On the **cityperfume** dashboard, the Margin ROAS card is using the wrong colour — make it match
> the other KPI cards. Show me the diff, then deploy it."

Claude will: grep to the right element in `dashboard.html`, make the edit, show you the change, and
(on your OK) run `deploy_dash_cityperfume.ps1`. Ask it to **explain before deploying** if you want a
checkpoint.

---

## 4. Doing GCP work through Claude

Because you're Owner, Claude (running as you) can do any GCP operation when you ask. Examples:

- "Show me the last 20 log lines from the **schneider-export** job."
- "Force a rebuild of the **stt** dashboard data now." *(runs the export job with `FORCE_REBUILD=1`)*
- "List the Cloud Scheduler jobs and confirm each export is on `*/10`."
- "What's in the **mongodb** bucket, and when was `mongodb.json` last updated?"
- "Reapply the **resetdata** SQL views and re-run its export job."

You can also run gcloud yourself — your config is already set to project `bidbrain-analytics` and
region `australia-southeast1`. But for anything non-trivial, asking Claude is faster and it
double-checks against the repo's conventions.

---

## 5. Guardrails — don't break these (Owner = no safety net)

These are the project's hard rules; Claude follows them, and so should you:

- **Never commit secrets** — no `*.p8`, `*credentials*.json`, `.env`, or `*_key`. Secrets live in
  **Secret Manager** + a local, gitignored `bidbrain-vault/` (ask Ian if you need the local vault;
  most things read from Secret Manager via your credentials and need nothing local).
- **Never make the dashboard data JSON public.** The private bucket + the Flask password gate **is**
  the security model. Don't add public access or copy data to a public URL.
- **Never edit BigQuery views in the console.** `sql/*.sql` is the source of truth, or the views
  drift. Edit the file and redeploy the views.
- **Everything stays in `australia-southeast1`.** Never create a resource in another region.
- **One client = its own dataset, job, bucket, service, password, subdomain.** Keep clients isolated.

---

## 6. Smoke test (prove your setup end-to-end)

1. `.\scripts\start_day.ps1` → all `[OK]`.
2. `claude` → ask: *"List the Cloud Run services in this project and their URLs."* (confirms your
   GCP access works through Claude).
3. Make a tiny, reversible dashboard edit on any client (e.g. change a card subtitle), ask Claude to
   deploy it, open the dashboard URL, confirm the change, then revert + redeploy. Now you've done the
   whole loop.

---

## 7. Where to read more
- **`CLAUDE.md`** (repo root) — the canonical fast-path: fixed facts, the data contract, and every
  deploy command. This is what Claude reads automatically.
- **`README.md`** (repo root) — the full human map of the architecture and every folder.
- **`clients/client_<c>/README.md`** — per-client detail (what it reports, currency, gotchas).
- **`clients/client_mongodb/README.md`** — the canonical 3-stage pattern, end to end.

Anything unclear, ask Claude in-repo ("how does the freshness gate work?", "where does the resetdata
ROAS get computed?") — it can read the whole repo and explain.
