# Ray White Projects artwork

**Nothing here yet.** Drop the supplied files in as:

    raywhite-projects-lockup.svg    the horizontal lockup, for the topbar and the login
    raywhite-projects-mark.svg      the mark alone, for the browser tab

Then run:

    .\.venv\Scripts\python.exe clients\client_raywhiteprojects\gen_brand_assets.py

Ask for the **concrete** colourway, not the yellow one: Ray White Projects uses the concrete
lockup on Monair, and Ray White yellow (`#FFE512`) is ~1.3:1 on the bone field, so it can only ever
be a fill or a rule in this build, never a mark or text.

Vector is strongly preferred. A single-colour vector recolours with one attribute; a raster master
has to be luminance-keyed and then only works on one background.

Until the files land, the mark on both surfaces is a typographic stand-in written in markup, and
the favicon is an inline data URI. There is deliberately **no generated placeholder image** - see
the note at the top of `gen_brand_assets.py`.
