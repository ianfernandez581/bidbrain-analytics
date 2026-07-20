r"""Add the Schneider "Liquid AI Data Center" (schneiderlqai) dashboard to a DOWNLOADED platform.json
as an ACTIVE client under the Transmission agency. Edits a local file only, so the upload can be done
with gcloud as ian@ (the Python GCS client would use the venv's charles@ ADC).

The dashboard password (Secret Manager `schneiderlqai-dash-password`) is passed as argv[2] so the
registry keeps a recoverable `password_plain` + a matching pbkdf2 `password_hash` (super-admin reveal
reads the plain; the hash lets the single-dashboard password log in at the platform level). The proxy
itself logs into the upstream with the Secret-Manager secret, not this hash.

Run between a gcloud download + upload (PowerShell, as ian@100.digital):

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"; $reg="$env:TEMP\lqai.json"
    gcloud storage cp gs://bidbrain-analytics-platform-dash/platform.json $reg --project bidbrain-analytics
    .\.venv\Scripts\python.exe bidbrain-platform\dash\registry_add_schneiderlqai.py $reg "<dash-password>"
    gcloud storage cp $reg gs://bidbrain-analytics-platform-dash/platform.json `
        --cache-control="no-store" --content-type="application/json" --project bidbrain-analytics
"""
import json
import sys
import hashlib
import os

p = sys.argv[1]
password = sys.argv[2] if len(sys.argv) > 2 else ""


def hash_password(pw):
    # matches bidbrain-platform/dash/store.py _hash: pbkdf2_sha256$120000$<salt_hex>$<dk_hex>
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 120_000)
    return f"pbkdf2_sha256$120000${salt.hex()}${dk.hex()}"


d = json.load(open(p, encoding="utf-8"))
clients = d.setdefault("clients", {})
ex = clients.get("schneiderlqai", {})
order = ex.get("order", max([c.get("order", 0) for c in clients.values()], default=-1) + 1)
entry = {
    "key": "schneiderlqai", "name": "Schneider - Liquid AI Data Center", "slug": "schneider-liquid-ai",
    "status": "active",
    "url": "https://schneiderlqai-dash-516554645957.australia-southeast1.run.app/",
    "campaigns": [{"name": "AI & Liquid Cooling", "path": "/", "status": "active"}],
    "order": order,
}
if password:
    entry["password_hash"] = hash_password(password)
    entry["password_plain"] = password
else:
    entry["password_hash"] = ex.get("password_hash", "")
clients["schneiderlqai"] = entry

a = next(a for a in d["agencies"] if a["slug"] == "transmission")
ks = a.setdefault("client_keys", [])
if "schneiderlqai" not in ks:
    ks.insert(ks.index("schneider") + 1 if "schneider" in ks else len(ks), "schneiderlqai")

json.dump(d, open(p, "w", encoding="utf-8"), separators=(",", ":"))
print("OK schneiderlqai:", entry["status"], "| pw set:", bool(password),
      "| in transmission:", "schneiderlqai" in a["client_keys"])
