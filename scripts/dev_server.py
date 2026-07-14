r"""
dev_server.py — minimal LOCAL development server (no secrets, no AI, laptop only).

Serves the built map plus local stand-ins for the two Vercel functions, so every
feature — including ADDRESS SEARCH and the full-network street search — works on
localhost exactly as deployed:

  static files                    -> outputs/interactive_map/  (index.html etc.)
  GET /api/geocode?address=...    -> proxies the US Census geocoder server-side
                                     (same response shape as api/geocode.js; the
                                     browser can't call Census directly: no CORS)
  GET /api/locate?q=...           -> proxied to the node dev server if running
                                     (start it first: node scripts\locate_dev_server.js)

Run:
    .\.venv\Scripts\python.exe scripts\dev_server.py          (port 8000)
    node scripts\locate_dev_server.js                          (optional, for /api/locate)
Then open http://localhost:8000/index.html
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBROOT = ROOT / "outputs" / "interactive_map"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
LOCATE_UPSTREAM = "http://127.0.0.1:8130"   # scripts/locate_dev_server.js default port
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEBROOT), **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/geocode":
            return self._geocode()
        if path == "/api/locate":
            return self._locate()
        return super().do_GET()

    def _geocode(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        address = (q.get("address", [""])[0] or "").strip()
        if not address:
            return self._json(400, {"error": "missing_address"})
        low = address.lower()
        if "memphis" not in low and " tn" not in low:
            address += ", Memphis, TN"
        url = (CENSUS_URL + "?" + urllib.parse.urlencode(
            {"address": address, "benchmark": "Public_AR_Current", "format": "json"}))
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
            match = (data.get("result", {}).get("addressMatches") or [None])[0]
            if not match:
                return self._json(404, {"error": "not_found"})
            return self._json(200, {"matchedAddress": match.get("matchedAddress", address),
                                    "lat": match["coordinates"]["y"],
                                    "lon": match["coordinates"]["x"]})
        except Exception:
            return self._json(502, {"error": "geocoder_unavailable"})

    def _locate(self):
        try:
            with urllib.request.urlopen(LOCATE_UPSTREAM + self.path, timeout=15) as r:
                body = r.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            return self._json(502, {"error": "locate_dev_server_not_running",
                                    "hint": "start it with: node scripts\\locate_dev_server.js"})


if __name__ == "__main__":
    print(f"dev server: http://localhost:{PORT}/index.html  (webroot: {WEBROOT})")
    print("  /api/geocode -> US Census (live)   /api/locate -> node dev server if running")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
