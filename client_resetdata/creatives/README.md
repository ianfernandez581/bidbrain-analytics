# client_resetdata/creatives/ — drop branding assets here

Put the ResetData branding assets in this folder and I'll wire them into the
dashboard (topbar logo chip + login page) and extract the palette from them:

- **ResetData logo** — preferred as `.svg` (inline, sharp at any size). A raster
  `.png` / `.jpg` is fine too — it'll be embedded as a base64 `<img>`.
- **Agency logo** — goes top-left where STT shows `TRANSMISSION`.
- **Website screenshot** — used only to extract the palette (cool / technical:
  deep blue / teal / slate / near-black for a sovereign-AI / data-centre brand).

Until assets land here, the dashboard ships with a clearly-labeled **placeholder
logo block** and the fallback cool/technical palette (see the README note about
"final logos + palette pending"). Swapping is a single contiguous block edit in
`dash/dashboard.html` (and the `LOGIN_HTML` block in `dash/main.py`).

Suggested filenames (any of these will be picked up):
`resetdata-logo.svg` · `resetdata-logo.png` · `agency-logo.svg` · `website.png`
