import os
from store import Store, hash_pw
CLIENTS = ["mongodb","cloudflare","stt","schneider","hireright","cityperfume","resetdata","proptrack","tlm","vmch"]
s = Store(); doc = s._load()
for c in CLIENTS:
    url = os.environ.get(f"{c.upper()}_URL","").rstrip("/")
    pw  = os.environ.get(f"{c.upper()}_PW","").strip()
    if c in doc.get("clients",{}) and url:
        doc["clients"][c]["url"] = url + "/"
        if pw: doc["clients"][c]["password_hash"] = hash_pw(pw)
        print(f"{c:12} url={url}  pw={'set' if pw else 'MISSING'}")
    else:
        print(f"{c:12} SKIPPED (in registry={c in doc.get('clients',{})}, url={'yes' if url else 'no'})")
s._save(doc)
print("registry updated")
