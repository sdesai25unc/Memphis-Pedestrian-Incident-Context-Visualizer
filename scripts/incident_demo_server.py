r"""
incident_demo_server.py  --  LAPTOP DEMO ONLY (do NOT deploy; not production-safe).

Serves the interactive map plus two local endpoints so the "Report a New Incident"
demo tab works on your laptop:

  GET  /api/geocode?address=...   -> US Census geocoder (server-side; so address search works
                                     locally without the Vercel function)
  POST /api/incident-context      -> OpenAI phrasing/framing over a deterministic facts object.
                                     Reads your API key from a LOCAL FILE (see KEY_FILE below).

The AI ONLY phrases/frames; all facts come from the page (window.CountA.facts). If the key is
missing or OpenAI errors/times out, this returns an error and the page still shows the facts card.

Run:
    .\.venv\Scripts\python.exe scripts\incident_demo_server.py
Then open:
    http://localhost:8000/index.html   (the Report-a-New-Incident tab is built into it)
"""

import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBROOT = ROOT / "outputs" / "interactive_map"
KEY_FILE = ROOT / "openai_key.txt"          # <<< paste your OpenAI API key into this file (one line)
OPENAI_MODEL = "gpt-5.4-mini"               # <<< THE model string -- change ONLY here. If the API says
#     "model not found", the server prints your account's available model ids so you can copy the right one.
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODELS_URL = "https://api.openai.com/v1/models"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
PORT = 8000

# The AI is a copy assistant, NOT an analyst. These rules are enforced verbatim.
SYSTEM_PROMPT = """You are a careful newsroom copy assistant for pedestrian-safety reporting.
You receive a FACTS object (verified data from a mapping tool) and optionally a DESCRIPTION
(a journalist's draft snippet). Follow these rules exactly.

CORE RULES (never break any of these):
- Use ONLY the facts in the FACTS object. Never state, imply, or invent any number, street, owner,
  distance, or claim that is not present in it.
- Never characterize any number as high, low, dangerous, notable, rare, common, or safe -- you have
  NO baseline for comparison. Report numbers plainly and neutrally.
- Frame away from individual fault: prefer infrastructure-grounded, non-victim-blaming language, but
  ONLY using the given facts. Never assert that infrastructure caused an incident unless a fact says so.
- If a DESCRIPTION is provided, identify blame-loaded or victim-blaming LANGUAGE in it and suggest
  neutral reframes -- but never contradict, omit, or reinterpret the incident's stated facts.
- If something is asked or implied that the facts do not cover, do not answer it; state that the data
  does not cover it.

INTERPRETATION BOUNDARY (critical):
- You MAY organize, connect, sequence, and frame the given facts into readable prose -- for example,
  relating the crash count, the road owner, and the nearest-crossing distance to one another within
  the same passage.
- You MAY reframe or interpret LANGUAGE in the DESCRIPTION: identify victim-blaming phrasing, suggest
  neutral rewrites, and weave the described incident into the context.
- You MUST NOT draw conclusions, verdicts, or judgments about the FACTS. Never say or imply that any
  number or distance is adequate, inadequate, dangerous, safe, concerning, sufficient, insufficient,
  or a "pattern," and never suggest what the facts mean for safety or for infrastructure quality.
  Present the facts and their relationships; do not editorialize on what they imply.

THE "paragraph" OUTPUT:
- Write a LONGER, multi-paragraph background/context block in clean, neutral journalistic prose that a
  reporter could paste directly into a story. Separate paragraphs with a blank line (\\n\\n).
- Write as much as the available facts genuinely support, then STOP. Do not pad, do not add filler, and
  do not add sentences that carry no information. Running out of facts is the correct place to end.
- It should read as close to a paste-ready context section as the facts allow, while containing ZERO
  interpretation of what the facts imply about safety or infrastructure quality. State what is, connect
  what relates, reframe the description's language -- nothing more.

Respond with a JSON object of exactly this shape:
{"paragraph": "<a multi-paragraph, paste-ready context block using ONLY the facts; paragraphs separated by \\n\\n>",
 "reframes": [{"original": "<phrase from the description>", "suggested": "<neutral rewrite>",
               "why": "<short reason>"}]}
If no description is provided, return "reframes": []."""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEBROOT), **k)

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/geocode":
            return self._geocode()
        return super().do_GET()          # static files (index.html, geojson, ...)

    def do_POST(self):
        if self.path == "/api/incident-context":
            return self._incident()
        return self._send_json(404, {"error": "not_found"})

    # ---- GET /api/geocode : US Census, server-side (adds "Memphis, TN" if absent) ----
    def _geocode(self):
        try:
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            addr = (params.get("address", [""])[0] or "").strip()
            if not addr:
                return self._send_json(400, {"error": "missing_address"})
            low = addr.lower()
            if "memphis" not in low and " tn" not in low and not low.endswith("tn"):
                addr = addr + ", Memphis, TN"
            url = CENSUS_URL + "?" + urllib.parse.urlencode(
                {"address": addr, "benchmark": "Public_AR_Current", "format": "json"})
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.load(r)
            matches = (((data or {}).get("result") or {}).get("addressMatches") or [])
            if not matches:
                return self._send_json(404, {"error": "not_found"})
            m = matches[0]
            return self._send_json(200, {"matchedAddress": m.get("matchedAddress"),
                                         "lat": m["coordinates"]["y"], "lon": m["coordinates"]["x"]})
        except Exception:
            return self._send_json(502, {"error": "geocoder_unavailable"})

    # ---- POST /api/incident-context : OpenAI phrasing/framing over the facts ----
    def _incident(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send_json(400, {"error": "bad_request"})
        facts = body.get("facts")
        desc = (body.get("description") or "").strip()

        if not KEY_FILE.exists():
            return self._send_json(503, {"error": "no_key",
                                         "detail": f"Paste your OpenAI API key into {KEY_FILE.name}"})
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if not key:
            return self._send_json(503, {"error": "no_key", "detail": f"{KEY_FILE.name} is empty"})

        user = ("FACTS:\n" + json.dumps(facts, indent=2)
                + ("\n\nDESCRIPTION:\n" + desc if desc else "\n\n(No description provided.)"))
        payload = {"model": OPENAI_MODEL, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": user}]}
        try:
            req = urllib.request.Request(
                OPENAI_URL, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=45) as r:
                out = json.load(r)
            content = out["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return self._send_json(200, {"paragraph": parsed.get("paragraph", ""),
                                         "reframes": parsed.get("reframes", []),
                                         "model": OPENAI_MODEL})
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()
            except Exception:
                detail = ""
            print("\n" + "!" * 66)
            print(f"  OpenAI API error (HTTP {e.code}) for model '{OPENAI_MODEL}':")
            print("  " + (detail.strip() or "(no response body)"))
            resp = {"error": "openai_error", "status": e.code, "model": OPENAI_MODEL,
                    "detail": (detail.strip()[:500] or f"HTTP {e.code}")}
            # If it's a model problem, list the account's real model ids so you can copy the right string.
            if e.code in (400, 404) and "model" in detail.lower():
                models = self._list_models(key)
                if models:
                    print("\n  Your account's available model ids "
                          "(copy the right one into OPENAI_MODEL near the top of this file):")
                    for mid in models:
                        print("    " + mid)
                    resp["available_models"] = models
                else:
                    print("  (could not list models -- check that the API key is valid)")
            print("!" * 66 + "\n")
            return self._send_json(502, resp)
        except Exception as e:
            print(f"\n  OpenAI call failed for model '{OPENAI_MODEL}': {e}\n")
            return self._send_json(502, {"error": "openai_unavailable", "detail": str(e)[:200]})

    def _list_models(self, key):
        """GET /v1/models -> sorted model ids (gpt/o/chatgpt first). Used to show the real names
        when the configured OPENAI_MODEL string is wrong."""
        try:
            req = urllib.request.Request(MODELS_URL, headers={"Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
            ids = sorted(m.get("id", "") for m in (data.get("data") or []) if m.get("id"))
            chat = [i for i in ids if i.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))]
            return chat + [i for i in ids if i not in chat]
        except Exception as e:
            print(f"  (list-models request failed: {e})")
            return []

    def log_message(self, *a):
        pass   # keep the console quiet


if __name__ == "__main__":
    if not WEBROOT.exists():
        sys.exit(f"web root not found: {WEBROOT}")
    print("=" * 64)
    print("  Report-a-New-Incident DEMO server  (laptop only -- do not deploy)")
    print("=" * 64)
    print(f"  open:   http://localhost:{PORT}/index.html   (Report-a-New-Incident tab is built in)")
    print(f"  serving: {WEBROOT}")
    print(f"  OpenAI key file: {KEY_FILE}")
    print(f"     -> {'FOUND' if (KEY_FILE.exists() and KEY_FILE.read_text().strip()) else 'MISSING (AI disabled; facts card still works)'}")
    print(f"  model: {OPENAI_MODEL}")
    print("  Ctrl+C to stop")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
