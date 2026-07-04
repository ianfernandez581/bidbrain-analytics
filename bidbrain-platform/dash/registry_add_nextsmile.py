"""Add the Next Smile Australia placeholder to a DOWNLOADED platform.json (coming_soon + note +
preview url, attached to 100% Digital right after Caltex). Edits a local file only, so the upload
can be done with gcloud as ian@ (the Python GCS client would use the venv's charles@ ADC).

Run between a gcloud download + upload (PowerShell, after `gcloud auth login` as ian@):

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"; $reg="$env:TEMP\ns.json"
    gcloud storage cp gs://bidbrain-analytics-platform-dash/platform.json $reg --project bidbrain-analytics
    .\.venv\Scripts\python.exe bidbrain-platform\dash\registry_add_nextsmile.py $reg
    gcloud storage cp $reg gs://bidbrain-analytics-platform-dash/platform.json `
        --cache-control="no-store" --content-type="application/json" --project bidbrain-analytics
"""
import json, sys

p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
clients = d.setdefault("clients", {})
ex = clients.get("nextsmile", {})
order = ex.get("order", max([c.get("order", 0) for c in clients.values()], default=-1) + 1)
clients["nextsmile"] = {
    "key": "nextsmile", "name": "Next Smile Australia", "slug": "next-smile",
    "status": "coming_soon",
    "url": "https://nextsmile-dash-516554645957.australia-southeast1.run.app/",
    "note": "Dashboard isn't live yet - the structure is ready.",
    "password_hash": ex.get("password_hash", ""),
    "campaigns": [{"name": "Consult Bookings", "path": "/all-on-4", "status": "coming_soon"}],
    "order": order,
}
a = next(a for a in d["agencies"] if a["slug"] == "x100-digital")
ks = a.setdefault("client_keys", [])
if "nextsmile" not in ks:
    ks.insert(ks.index("caltex") + 1 if "caltex" in ks else len(ks), "nextsmile")
json.dump(d, open(p, "w", encoding="utf-8"), separators=(",", ":"))
print("OK nextsmile:", clients["nextsmile"]["status"], "| in x100-digital:", "nextsmile" in a["client_keys"])
