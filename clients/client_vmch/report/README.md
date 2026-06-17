# VMCH → Google Slides (prototype)

On-demand generator that turns the live VMCH dashboard data into a branded
**Google Slides** deck in your own Google Drive. Proof-of-concept for one client;
the pattern generalises to the other nine (per-client config + chart builders).

```
report.py     orchestrator — load data → render charts → build deck → print URL
charts.py     Chart.js configs + headless-Chromium render to PNG (charts.py BUILDERS)
chart_page.html  the render surface Playwright screenshots (Chart.js, VMCH palette)
deck.py       Slides + Drive API: create deck, KPI slide, one slide per chart
```

## How it works

1. **Data** — reads `gs://bidbrain-analytics-vmch-dash/vmch.json` (the same JSON the
   dashboard serves), or a local file with `--local`. No new data plumbing — it
   rides the existing export job's output.
2. **Charts** — the PNGs are *real Chart.js* output (same library + `#EB3300`/`#4C2736`
   palette as `dash/dashboard.html`), rendered by headless Chromium screenshotting a
   canvas. So slides look like the dashboard, not a matplotlib clone. Chart.js is
   vendored to `chart.umd.min.js` on first run (gitignored).
3. **Deck** — creates the presentation in **your** Drive via the Slides API: a title
   slide, a KPI-at-a-glance slide, then one slide per chart. Chart PNGs are uploaded
   to Drive, made link-readable just long enough for Slides to copy the bytes, then
   the temp files are deleted.

## One-time setup

APIs are already enabled on the project (`slides`, `drive`). Deps:

```powershell
.\.venv\Scripts\python.exe -m pip install -r clients\client_vmch\report\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Auth uses your gcloud **Application Default Credentials**, which need Drive + Slides
scopes on top of cloud-platform. Run once (re-run if you ever reset ADC):

```powershell
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/presentations
```

The deck is owned by whoever runs this (you), and lands in your Drive root unless you
pass `--folder <DriveFolderId>`.

## Run

```powershell
.\.venv\Scripts\python.exe clients\client_vmch\report\report.py
# options:
#   --local <path>   use a local vmch.json instead of GCS
#   --folder <id>    create the deck inside a Drive folder
#   --title "..."    override the deck title
```

It prints the deck URL when done.

## Charts included

| key | slide |
|-----|-------|
| `spend_sessions`     | TTD spend (bars) vs website sessions (line), monthly |
| `spend_by_campaign`  | TTD spend doughnut across the 4 service-line campaigns |
| `enquiries_by_type`  | GA4 key-event enquiries by type |
| `imps_sessions`      | Impressions vs sessions, monthly |

Add a chart: write a builder in `charts.py`, append it to `BUILDERS`. Change KPIs:
edit `build_kpis()` in `report.py`.

## Notes / next steps (prototype scope)

- **On-demand only** — no scheduler. To productionise: wrap as a Cloud Run job with a
  service account (share a Drive folder with the SA) and trigger from Scheduler or
  off the freshness watermark, mirroring the export jobs.
- **Owned by your user account** via ADC — simplest for a prototype. A service-account
  variant (for unattended runs) would create decks in the SA's Drive and share them out.
- Charts/KPIs are a starter set; extend per the table above to match the deck a client
  actually wants.
