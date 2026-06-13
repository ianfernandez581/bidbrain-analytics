# Building `dashboard.html` from your existing `index.html`

The Cloud Run service ([main.py](main.py)) serves a file named **`dashboard.html`**
that sits next to it in this folder, and proxies the private data at **`/data.json`**.
Your current dashboard (`index.html`, the "Core Demand Generation" page) already
contains every chart and tab — it just fetches **two public R2 files**
(`pacing.json` + `paid_media.json`). On this architecture there's **one private
payload** served at `/data.json`, shaped so the two halves are exactly the old
two files nested under `pacing` and `paid_media`:

```jsonc
{
  "last_updated": "...",
  "data_through": "...",                     // newest source LAST_ALTERED (added with the freshness gate)
  "paid_media": { "row_count": ..., "window": {...}, "all_markets": [...],
                  "rows": [...], "creatives": [...], "benchmarks": {...},
                  "benchmarks_market": {...}, "li_weekly": [...] },   // == the old paid_media.json (+ creatives)
  "pacing":     { "row_count": ..., "rows": [...] },  // == the old pacing.json
  "campaigns":  { "peyc": {...}, "cf1_india": {...}, "coles_hyper": {...} }  // single-campaign LinkedIn dashboards (added later)
}
```

Because of that, the original conversion was **three small edits** to the
`<script>` in `index.html` — no chart/render code changes. `adaptPayload()`
already expects the exact shape of `COMBINED.paid_media`, and `rawRows` already
expects `COMBINED.pacing.rows`.

> The shipped `dashboard.html` has since grown beyond this three-edit baseline:
> the freshness gate added `data_through`, the Paid Media tab gained "top & bottom
> creatives" tables (reading `paid_media.creatives`), and a top-bar dashboard
> selector renders three single-campaign LinkedIn dashboards from a new
> `campaigns` branch. Those keys are additive — the original `adaptPayload()` /
> `rawRows` contract below is unchanged.

> Save the edited file as **`clients/client_cloudflare/dash/dashboard.html`** (the
> Dockerfile copies it in by that name). Don't add the old client-side password
> gate from `ORIGINAL_DASH_STATIC_DATA.html` — the Flask service is the gate now,
> and the bucket is private.

---

## Edit 1 — one data URL instead of two R2 URLs

**Find** (top of the `<script>`, the CONFIG block):

```js
const DATA_URL        = 'https://pub-769f11776a0b4d90921d81044a9b44cf.r2.dev/pacing.json';
const PAID_MEDIA_URL  = 'https://pub-769f11776a0b4d90921d81044a9b44cf.r2.dev/paid_media.json';
```

**Replace with:**

```js
const JSON_URL = '/data.json';   // served by the gated Cloud Run service (clients/client_cloudflare/dash)
let   COMBINED = null;           // whole payload: { last_updated, paid_media:{...}, pacing:{...} }
```

---

## Edit 2 — `boot()` fetches `/data.json` once

**Find** the first two lines inside the `try` of `boot()`:

```js
    const res = await fetch(DATA_URL + '?t=' + Date.now());
    if (!res.ok) throw new Error('HTTP ' + res.status + ' from R2');
    const data = await res.json();
    rawRows = data.rows || [];
    setLiveBanner(data.last_updated, rawRows.length);
```

**Replace with:**

```js
    const res = await fetch(JSON_URL, {cache:'no-store'});
    if (!res.ok) throw new Error('HTTP ' + res.status + ' fetching data.json');
    COMBINED = await res.json();
    rawRows = (COMBINED.pacing && COMBINED.pacing.rows) || [];
    setLiveBanner(COMBINED.last_updated, rawRows.length);
```

Everything else in `boot()` (hiding the loader, `renderChips()`,
`populateRegionSelects()`, `renderAll()`, the `loadPaidMedia()` kick-off) stays
exactly as-is.

---

## Edit 3 — `loadPaidMedia()` reads from memory, no second fetch

The paid-media data now arrives in the same payload as pacing, so this function
stops hitting the network and reads `COMBINED.paid_media` instead.

**Find** these lines inside the `try` of `loadPaidMedia()`:

```js
    const res = await fetch(PAID_MEDIA_URL + '?t=' + Date.now());
    if (!res.ok) throw new Error('HTTP ' + res.status + ' from R2');
    const data = await res.json();
    PAYLOAD = adaptPayload(data);
    paidMediaLastUpdated = data.last_updated || null;
```

**Replace with:**

```js
    // Paid-media data is already in memory — it's the paid_media branch of the
    // single combined payload fetched in boot(). No second network request.
    const data = (COMBINED && COMBINED.paid_media) || {};
    PAYLOAD = adaptPayload(data);
    paidMediaLastUpdated = (COMBINED && COMBINED.last_updated) || null;
```

The rest of `loadPaidMedia()` — `adaptPayload`, the `paidMediaAllMarkets`
fallback, `setPaidFooter(data.row_count)`, `renderPaidMediaChips()`,
`renderPaidMediaAll()` — is unchanged. `data.all_markets`, `data.window`,
`data.row_count`, `data.benchmarks*`, `data.li_weekly` all still resolve because
`COMBINED.paid_media` carries those exact keys.

---

## That's it

No edits to `adaptPayload()`, `renderPaidMediaAll()`, the CS render path, the
chip logic, or any chart. After the three edits, save as `dashboard.html` in this
folder and build (`cloudbuild.yaml` copies `main.py dashboard.html` into the
image).

### Optional cleanups (not required)

- The shipped `dashboard.html` keeps the `?t=' + Date.now()` cache-buster on the
  `/data.json` fetch (a harmless belt-and-braces — the service already sends
  `Cache-Control: no-store`, so freshness is handled server-side either way).
- The two error panels (`#error`, `#paid-error`) still work — a failed
  `/data.json` fetch shows the main error box; the paid panel only renders after
  `COMBINED` is set, so its error path now effectively can't fire on its own.
- If TTD market tokens (`HKTW`, `SGMYID`, `IN`, …) ever change, that mapping
  lives in `normalizeMarket()` / `PM_MARKET_REMAP`, untouched by this patch.

If you'd rather not hand-edit, I can emit the full merged `dashboard.html` in one
shot — just ask.
