# client_resetdata/creatives/ — branding source assets (wired in)

Source artwork for the ResetData dashboard's branding. As of 2026-06-08 the real
branding **is wired in** — the topbar and login page render the inlined base64 logos,
not a placeholder. These files are the originals the base64 was made from / the palette
was sampled from:

- **`resetdate_wordmark.webp`** — the ResetData wordmark, embedded as a base64 `<img>`
  in the topbar of [`../dash/dashboard.html`](../dash/dashboard.html) and on the login
  page (`LOGIN_HTML`) in [`../dash/main.py`](../dash/main.py), next to the **100% Digital**
  agency mark and a divider.
- **`Screenshot 2026-06-08 133943.png`** — ResetData website screenshot, used to sample
  the brand palette: the crimson-pink accent **`#E84A6F`** on a deep-navy ground.

To **re-skin** later, swap the base64 in two places — the `.logo` block in
`../dash/dashboard.html` and the `LOGIN_HTML` block in `../dash/main.py` — and adjust the
`:root` palette in `dashboard.html`. (A leftover placeholder `.logo .mark` CSS rule still
sits in `dashboard.html`; it is unused — the markup uses the wordmark `<img>`.) The agency
slug carried in the data is `100-digital`.

A `.svg` wordmark would render sharper at any size than the current `.webp` raster — drop
one here if/when ResetData provides it and re-embed.
