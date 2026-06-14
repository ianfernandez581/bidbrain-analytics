# VMCH Dashboard Brand Assets

Real assets are inlined and live. To refresh after dropping a new logo here, run:

    .\.venv\Scripts\python.exe clients\client_vmch\creatives\inject_logos.py

## Files
- `Logo.webp` — client-supplied orange-red ("VMCH") wordmark, transparent bg.
- `Screenshot 2026-06-14 181950.png` — vmch.org.au, the brand-palette reference.
- `inject_logos.py` — idempotent: crops the logo and sets the `src=` of the dashboard topbar
  (`<img class="brandlogo">`) and the login (`<img class="client">`). Both surfaces are light, so
  the logo is used at its true orange colour. Re-run any time; it rewrites the `src` in place.

## Palette (sampled from vmch.org.au)
- Logo / primary accent orange-red `#EB3300`, deep `#C22A00`
- Hero / secondary maroon `#4C2736` (lighter `#7A4154`)
- Page cream `#FBF6F1`, white cards `#FFFFFF`, warm ink `#2A1E20`, lines `#ECE3D9`
- Supporting chart hues: organic green `#2E8B72`, direct slate `#7A6A6E`, grey `#C9BEB8`

These values live in `dash/dashboard.html`'s `:root` (plus the JS `C{}` / `KE_PALETTE` chart
palette) and in `dash/main.py`'s LOGIN_HTML — edit them there, not here.

## 100% Digital agency mark
No official 100% Digital raster logo exists in this repo, so the agency mark in the topbar + login
is an inline **SVG wordmark** (`100% Digital`). To use an official asset, drop it here and extend
`inject_logos.py` to inline it the same way as the VMCH logo.
