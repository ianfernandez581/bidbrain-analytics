"""Repro v2: robust server, capture pageerrors immediately after load."""
import http.server, socketserver, threading, json, time
from playwright.sync_api import sync_playwright

ROOT = "/tmp/geocon_repro"
PORT = 8766

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def log_message(self, *a): pass
    def end_headers(self):
        self.send_header("Cache-Control","no-store"); super().end_headers()

socketserver.ThreadingTCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"[serve] http://127.0.0.1:{PORT}")

# sanity: fetch data.json via the server
import urllib.request
try:
    d = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/data.json").read()
    print(f"[serve] data.json OK {len(d)} bytes")
except Exception as e:
    print("[serve] data.json FAILED", e)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errs, warns = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: warns.append(f"{m.type}: {m.text}") if m.type in ("error",) else None)
    pg.on("requestfailed", lambda r: warns.append(f"REQFAIL {r.url} {r.failure})"))

    pg.goto(f"http://127.0.0.1:{PORT}/dashboard.html", wait_until="networkidle")
    pg.wait_for_timeout(1500)

    print("\n=== PAGE ERRORS DURING LOAD ===", len(errs))
    for e in errs: print("  PAGEERROR:", e)
    print("=== CONSOLE ERRORS DURING LOAD ===", len(warns))
    for w in warns[:20]: print("  ", w)

    print("\n=== DEFINITION CHECK ===")
    defs = pg.evaluate("""() => ({
        DATA: typeof DATA, bindControls: typeof bindControls, load: typeof load,
        render: typeof render, exportThisTab: typeof exportThisTab,
        bbBuildDeck: typeof bbBuildDeck, Chart: typeof Chart, pptx: typeof PptxGenJS,
        dataMeta: (typeof DATA!=='undefined'&&DATA&&DATA.meta)?true:false,
        rows: (typeof DATA!=='undefined'&&DATA&&DATA.rows)?DATA.rows.length:null,
        appDisplay: document.getElementById('app')?getComputedStyle(document.getElementById('app')).display:null,
        errDisplay: document.getElementById('error')?getComputedStyle(document.getElementById('error')).display:null,
        errDetail: document.getElementById('errDetail')?document.getElementById('errDetail').textContent.slice(0,300):null,
        viewBtnsBound: (typeof jQuery==='function') // placeholder
    })""")
    print(json.dumps(defs, indent=2))

    # test a couple clicks only if load worked
    if defs.get("DATA") == "object" and defs.get("rows"):
        def click(label, sel):
            before=len(errs)
            try:
                pg.click(sel); pg.wait_for_timeout(300)
                ne=errs[before:]
                print(f"[click] {label}: {'OK' if not ne else 'NEW ERRORS: '+str(ne)}")
            except Exception as e:
                print(f"[click] {label}: EXCEPTION {e}")
        click("view buyer", '[data-view="buyer"]')
        click("view client", '[data-view="client"]')
        click("grain month", '#grainSeg [data-grain="month"]')
        click("export tab", '#expTabBtn')

    print("\n=== FINAL ALL PAGE ERRORS ===", len(errs))
    for e in errs: print("  ", e)
    b.close()
srv.shutdown()
