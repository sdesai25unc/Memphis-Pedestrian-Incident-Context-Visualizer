// api/locate.js — Vercel serverless function (Node.js runtime, CommonJS).
//
// FULL-NETWORK street & intersection search. The interactive page embeds search data only for
// the 529 crash-bearing corridors + the citywide junction index; every OTHER named Memphis
// street is findable through this endpoint. It answers from a preprocessed compact lookup
// (locate_data.json, ~2.9 MB, built by scripts/27_build_locate_index.py from the road-ownership
// rulebook + junction index + state-route alias groups) — bundled into the function via
// require(), so there is no runtime download and no database.
//
// ENDPOINT:  GET /api/locate?q=<text>
//   "slash pine"            -> street candidates (name, bbox for zoom, length, owner, crashes)
//   "poplar and cleveland"  -> intersection candidates (name, point, crashes, deaths, signal)
//   "us 51"                 -> the alias group's member streets as candidates
// Always returns a candidate LIST (<= 8) — ambiguous queries are the caller's to present;
// this endpoint never silently picks one interpretation.
//
// MATCHING (mirrors the in-page matcher; keep the two in sync):
//   case-insensitive; suffix-blind (poplar == poplar ave); directional-blind (cleveland
//   matches N & S Cleveland — both returned); "and"/"&"/"@" split intersections; typo-tolerant
//   (edit distance 1 for short names, 2 for 6+ chars); alias-aware (state-route designations
//   from the data). Grade-separation rules are inherited from the node index (interstates and
//   ramps are not through-roads there).

const DATA = require("./locate_data.json");

// ---- shared normalization (MUST match scripts/24_build_search.py BASE() and script 27) ----
const SUFFIX_WORDS = new Set(["avenue","ave","street","st","road","rd","boulevard","blvd",
  "drive","dr","parkway","pkwy","highway","hwy","lane","ln","court","ct","place","pl",
  "circle","cir","pike","way","cove","cv","terrace","ter","ext","expressway","expy"]);
const DIRS = new Set(["n","s","e","w","north","south","east","west"]);

function baseForm(s) {
  let w = String(s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  let hadDir = false;
  if (w.length > 1 && DIRS.has(w[0])) { w = w.slice(1); hadDir = true; }
  if (w.length > 1 && SUFFIX_WORDS.has(w[w.length - 1])) w = w.slice(0, -1);
  return { base: w.join(" "), hadDir: hadDir };
}

function lev(a, b, max) {
  // classic DP with early-exit band; returns max+1 when distance exceeds max
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1,
                        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (cur[j] < rowMin) rowMin = cur[j];
    }
    if (rowMin > max) return max + 1;
    prev = cur;
  }
  return prev[b.length];
}

// ---- cold-start index build (once per container) ----
const streetByBase = new Map();       // base -> [street row index]
const streetByDisp = new Map();       // lowercased display -> street row index
DATA.streets.forEach((s, i) => {
  const b = s[1];
  if (!streetByBase.has(b)) streetByBase.set(b, []);
  streetByBase.get(b).push(i);
  streetByDisp.set(s[0].toLowerCase(), i);
});
const nodeParts = DATA.nodes.map(n => n[0].split(" & ").map(p => baseForm(p).base));
const nodeByBase = new Map();         // base -> [node row index]
nodeParts.forEach((parts, i) => parts.forEach(b => {
  if (!nodeByBase.has(b)) nodeByBase.set(b, []);
  nodeByBase.get(b).push(i);
}));
const VOCAB = Array.from(new Set([...streetByBase.keys(), ...nodeByBase.keys()]));

// resolve one query part to a Map of candidate base -> match quality. ALL tiers are merged
// (a weak prefix match like "polar"->"polaris" must never shadow the correct fuzzy match
// "polar"->"poplar"): exact/alias 4, prefix 3, fuzzy 2, contains 1.
function matchPart(rawPart) {
  const { base: part } = baseForm(rawPart);
  const out = new Map();
  if (!part) return out;
  const aliasMembers = DATA.alias[rawPart.toLowerCase().replace(/\s+/g, " ").trim()] ||
                       DATA.alias[part] || null;
  if (aliasMembers) aliasMembers.forEach(m => out.set(baseForm(m).base, 4));
  if (streetByBase.has(part) || nodeByBase.has(part)) out.set(part, 4);
  let pre = 0, sub = 0;
  for (const v of VOCAB) {
    if (v === part) continue;
    if (v.startsWith(part)) {
      if (pre < 40 && (out.get(v) || 0) < 3) { out.set(v, 3); pre++; }
    } else if (part.length >= 5 && sub < 40 && v.includes(part)) {
      if (!out.has(v)) { out.set(v, 1); sub++; }
    }
  }
  if (part.length >= 4) {
    const tol = part.length < 6 ? 1 : 2;
    let best = tol + 1;
    const fz = [];
    for (const v of VOCAB) {
      const d = lev(part, v, tol);
      if (d < best) { best = d; fz.length = 0; fz.push(v); }
      else if (d === best && d <= tol) fz.push(v);
    }
    if (best <= tol) fz.slice(0, 25).forEach(v => { if ((out.get(v) || 0) < 2) out.set(v, 2); });
  }
  return out;
}

function streetCandidates(partMap) {
  const out = [];
  for (const [b, q] of partMap) {
    for (const i of (streetByBase.get(b) || [])) {
      const s = DATA.streets[i];
      out.push({ kind: "street", name: s[0], bbox: [s[2], s[3], s[4], s[5]],
                 length_m: s[6], owner: s[7], crashes: s[8], q: q });
    }
  }
  out.sort((a, b) => (b.q - a.q) || (b.crashes - a.crashes) || (b.length_m - a.length_m));
  return out;
}

function nodeCandidates(partMaps) {
  // nodes where EVERY query part matches a DISTINCT street of the node
  const pool = new Set();
  for (const b of partMaps[0].keys()) for (const i of (nodeByBase.get(b) || [])) pool.add(i);
  const out = [];
  for (const i of pool) {
    const parts = nodeParts[i];
    const used = new Set();
    let ok = true, qsum = 0;
    for (const pm of partMaps) {
      let found = -1, fq = 0;
      for (let k = 0; k < parts.length; k++) {
        if (!used.has(k) && pm.has(parts[k])) {
          const q = pm.get(parts[k]);
          if (q > fq) { fq = q; found = k; }
        }
      }
      if (found < 0) { ok = false; break; }
      used.add(found); qsum += fq;
    }
    if (ok) {
      const n = DATA.nodes[i];
      out.push({ kind: "intersection", name: n[0], lat: n[1], lon: n[2],
                 crashes: n[3], deaths: n[4], sig: n[5], q: qsum });
    }
  }
  out.sort((a, b) => (b.q - a.q) || (b.crashes - a.crashes));
  return out;
}

function locate(q) {
  q = String(q || "").trim();
  if (!q) return { error: "missing_query" };
  const parts = q.split(/\s*(?:\band\b|&|@)\s*/i).map(s => s.trim()).filter(Boolean);
  let candidates = [];
  if (parts.length >= 2) {
    const sets = parts.map(matchPart);
    if (sets.every(s => s.size)) candidates = nodeCandidates(sets);
  } else {
    const m = matchPart(q);
    candidates = streetCandidates(m);
    if (candidates.length === 0 && m.size) {
      // a street-form query that only exists as intersection streets: offer its junctions
      candidates = nodeCandidates([m]);
    }
  }
  return {
    query: q,
    intent: parts.length >= 2 ? "intersection" : "street",
    candidates: candidates.slice(0, 8),
    total_matches: candidates.length,
    coverage: "full Memphis street network (rulebook) + citywide junction index",
  };
}

function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "public, max-age=86400");   // static data -> cacheable
  if (req.method === "OPTIONS") { res.status(204).end(); return; }
  const q = (req.query && req.query.q) || "";
  const out = locate(q);
  res.status(out.error ? 400 : 200).json(out);
}

module.exports = handler;
module.exports.locate = locate;   // exported for the local dev server / tests
