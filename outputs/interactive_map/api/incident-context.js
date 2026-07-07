// api/incident-context.js  --  Vercel serverless function (Node.js runtime).
//
// Production version of the "Report a New Incident" AI layer. The browser sends a deterministic
// FACTS object (+ optional description); this function asks OpenAI to PHRASE/FRAME them and returns
// {paragraph, reframes}. The AI never supplies facts.
//
// SECURITY:
//   - The OpenAI key is read from the environment variable OPENAI_API_KEY -- it is NEVER in the repo.
//     Set it in the Vercel dashboard (Project -> Settings -> Environment Variables). Until it is set,
//     this endpoint returns 503 and the page shows "AI summary unavailable" (no spend, no risk).
//   - Optional abuse/cost gate: if the env var INCIDENT_ACCESS_CODE is set, callers must send a matching
//     code (header "x-access-code" or body.access_code) or they get 401. If it is unset, the endpoint is
//     open -- in that case, set a hard spending limit on the OpenAI key.
//   - Model is OPENAI_MODEL (env) or the default below; change it in the dashboard without redeploying.
//
// Keep SYSTEM_PROMPT in sync with scripts/incident_demo_server.py (the local-dev twin).

export const maxDuration = 60;   // OpenAI drafting can take a while; allow up to 60s (Vercel)

const OPENAI_URL = "https://api.openai.com/v1/chat/completions";

const SYSTEM_PROMPT = `You are a careful newsroom copy assistant for pedestrian-safety reporting.
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
If no description is provided, return "reframes": [].`;

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, x-access-code");
  if (req.method === "OPTIONS") { res.status(204).end(); return; }
  if (req.method !== "POST") { res.status(405).json({ error: "method_not_allowed" }); return; }

  const key = process.env.OPENAI_API_KEY;
  if (!key) {
    // dormant until the env var is set -> no spend, page still shows the facts card
    res.status(503).json({ error: "no_key", detail: "OPENAI_API_KEY is not set on the server yet." });
    return;
  }

  const body = (typeof req.body === "string") ? safeParse(req.body) : (req.body || {});

  // optional shared-code gate (only enforced if INCIDENT_ACCESS_CODE is set)
  const gate = process.env.INCIDENT_ACCESS_CODE;
  if (gate) {
    const provided = req.headers["x-access-code"] || body.access_code || "";
    if (provided !== gate) {
      res.status(401).json({ error: "unauthorized", detail: "A valid access code is required." });
      return;
    }
  }

  const model = process.env.OPENAI_MODEL || "gpt-5.4-mini";
  const facts = body.facts;
  const desc = (body.description || "").trim();
  const user = "FACTS:\n" + JSON.stringify(facts, null, 2) +
    (desc ? ("\n\nDESCRIPTION:\n" + desc) : "\n\n(No description provided.)");

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 55000);
    const r = await fetch(OPENAI_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + key },
      body: JSON.stringify({
        model,
        response_format: { type: "json_object" },
        messages: [{ role: "system", content: SYSTEM_PROMPT }, { role: "user", content: user }],
      }),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!r.ok) {
      const detail = await r.text();
      res.status(502).json({ error: "openai_error", status: r.status, model, detail: detail.slice(0, 600) });
      return;
    }
    const out = await r.json();
    const parsed = JSON.parse(out.choices[0].message.content);
    res.status(200).json({ paragraph: parsed.paragraph || "", reframes: parsed.reframes || [], model });
  } catch (e) {
    res.status(502).json({ error: "openai_unavailable", detail: String(e).slice(0, 200) });
  }
}

function safeParse(s) { try { return JSON.parse(s); } catch { return {}; } }
