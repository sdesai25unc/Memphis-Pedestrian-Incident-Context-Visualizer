// locate_dev_server.js — run the REAL api/locate.js Vercel handler locally for testing.
// (Same role scripts/incident_demo_server.py plays for the AI demo.)
//   node scripts\locate_dev_server.js  [port]     (default 8130)
// The regression harness proxies /api/locate here so tests exercise the production code path.

const http = require("http");
const url = require("url");
const path = require("path");
const handler = require(path.join(__dirname, "..", "outputs", "interactive_map", "api", "locate.js"));

const PORT = Number(process.argv[2] || 8130);

http.createServer((req, res) => {
  const u = url.parse(req.url, true);
  if (!u.pathname.startsWith("/api/locate")) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
    return;
  }
  // minimal Vercel-style req/res adapters
  req.query = u.query;
  res.status = (code) => { res.statusCode = code; return res; };
  res.json = (obj) => {
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(obj));
  };
  handler(req, res);
}).listen(PORT, "127.0.0.1", () => {
  console.log(`locate dev server: http://127.0.0.1:${PORT}/api/locate?q=...`);
});
