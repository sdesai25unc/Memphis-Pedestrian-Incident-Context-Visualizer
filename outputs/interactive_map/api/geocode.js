// api/geocode.js  —  Vercel serverless function (Node.js runtime, default).
//
// WHY THIS EXISTS:
//   The interactive map's address search needs to turn "1960 Oliver Ave" into
//   coordinates. The free US Census geocoder does that, but it sends NO
//   Access-Control-Allow-Origin header, so a browser calling it directly is
//   blocked by CORS. The fix is a tiny server-side proxy: the browser calls
//   THIS function (same origin, no CORS problem), and this function calls the
//   Census geocoder server-to-server (where CORS does not apply) and relays
//   the result back with CORS explicitly allowed.
//
// WHY NODE (not Python / edge):
//   - It is Vercel's zero-config default for a .js file in /api — nothing to
//     install or configure.
//   - Node 18+ on Vercel has a built-in global `fetch`, so there are NO npm
//     dependencies (no package.json needed for this function).
//   - The work is one outbound HTTP call + a little string handling; a full
//     Node function is the least surprising, most portable choice.
//
// ENDPOINT (after deploy):  GET /api/geocode?address=<text>
// RETURNS (200):  { "matchedAddress": "...", "lat": 35.13, "lon": -90.05 }
// RETURNS (404):  { "error": "not_found" }     (no Census match)
// RETURNS (400):  { "error": "missing_address" }

// The US Census "one line address" geocoder. Public, no API key, no login.
const CENSUS_URL =
  "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress";

export default async function handler(req, res) {
  // --- CORS: allow the browser to read this response from any origin. ---
  // (The site and the function share an origin on Vercel, so "*" is harmless
  //  here and also lets you test from a local file:// page if you ever proxy it.)
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  // Browsers send a preflight OPTIONS request before some cross-origin calls;
  // answer it immediately with "no content".
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  // --- Read and validate the address the page is asking about. ---
  let address = (req.query.address || "").toString().trim();
  if (!address) {
    res.status(400).json({ error: "missing_address" });
    return;
  }

  // The Census geocoder needs a city/state to resolve a bare street address.
  // Every crash in this project is inside Memphis, so default the locality to
  // "Memphis, TN" — but only if the user did not already type a city/state,
  // so we don't double-append (e.g. "...Memphis, TN, Memphis, TN").
  const lower = address.toLowerCase();
  if (!lower.includes("memphis") && !/\btn\b/.test(lower)) {
    address = `${address}, Memphis, TN`;
  }

  // --- Call the Census geocoder server-side. ---
  const url =
    `${CENSUS_URL}?address=${encodeURIComponent(address)}` +
    `&benchmark=Public_AR_Current&format=json`;

  try {
    // Guard against a slow/hung upstream so the function doesn't hang for 10s+.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const upstream = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);

    if (!upstream.ok) {
      // Census itself errored (rare) — report it as an upstream failure.
      res.status(502).json({ error: "geocoder_unavailable" });
      return;
    }

    const data = await upstream.json();
    const match =
      data &&
      data.result &&
      data.result.addressMatches &&
      data.result.addressMatches[0];

    if (!match) {
      // Valid request, but the address could not be located.
      res.status(404).json({ error: "not_found" });
      return;
    }

    // Census returns coordinates as { x: longitude, y: latitude }.
    res.status(200).json({
      matchedAddress: match.matchedAddress || address,
      lat: match.coordinates.y,
      lon: match.coordinates.x,
    });
  } catch (err) {
    // Network error, timeout/abort, or bad JSON from upstream.
    res.status(502).json({ error: "geocoder_unavailable" });
  }
}
