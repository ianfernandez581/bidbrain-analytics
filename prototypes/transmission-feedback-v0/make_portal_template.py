#!/usr/bin/env python3
"""Vendor the Feedback Loop prototype into the platform as the portal-tab template.

The portal's /feedback-loop route serves a copy of index.html whose embedded data
block is replaced by the __FEEDBACK_DATA_JSON__ sentinel (the route substitutes the
JSON at request time - sample file today, GCS on the real-data swap). This script
produces that copy plus the baked sample JSON. Both land in the platform templates
folder because the Dockerfile ships `COPY templates ./templates` - no Dockerfile edit.

RE-RUN THIS AFTER ANY EDIT to index.html or sample_data.json (vendored-copy rule,
same as bb_deck.js), then redeploy the platform:

    .\\.venv\\Scripts\\python.exe prototypes\\transmission-feedback-v0\\make_portal_template.py
    .\\bidbrain-platform\\dash\\deploy_dash_platform.ps1
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = HERE.parent.parent / "bidbrain-platform" / "dash" / "templates"

SENTINEL = "__FEEDBACK_DATA_JSON__"
BLOCK = re.compile(r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)

html = (HERE / "index.html").read_text(encoding="utf-8")
if not BLOCK.search(html):
    raise SystemExit("ERROR: data block not found in index.html")
out = BLOCK.sub(lambda m: m.group(1) + SENTINEL + m.group(3), html, count=1)
(DEST / "feedback_loop.html").write_text(out, encoding="utf-8")

sample = (HERE / "sample_data.json").read_text(encoding="utf-8")
json.loads(sample)  # refuse to vendor a broken sample
(DEST / "feedback_loop_sample.json").write_text(sample, encoding="utf-8")

print("vendored -> %s" % (DEST / "feedback_loop.html"))
print("vendored -> %s" % (DEST / "feedback_loop_sample.json"))
print("route substitutes %s at request time" % SENTINEL)
