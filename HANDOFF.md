# StreetStat — Handoff Documentation

*Written 2026-07-12 for the organization inheriting this project. Everything here was verified
against the actual code and data on this date; where a fact could not be verified from the repo,
it is marked as such.*

---

## 1. What StreetStat is

StreetStat turns Tennessee's public crash records into a Memphis-specific accounting of pedestrian
and non-motorist crashes **by road design and road ownership** — City of Memphis versus the
Tennessee Department of Transportation (TDOT). It exists to give journalists and advocates a
citable, verifiable alternative to "the pedestrian made a mistake" framing: every number on the
site is a share, count, or distance computed from public data, reconciled against fixed totals
(currently **1,294 crashes / 175 deaths**, Jan 1 2023 – May 26 2026), and stated descriptively —
the site never claims a road *caused* a death. It ships as one self-contained web page (map,
search, location reports, methodology) plus the reproducible Python pipeline that builds it.

## 2. Architecture

### The four-part site (one page, four views)

| View | What it does |
|---|---|
| **Home** (`#/`) | Hero with computed stat cards + the findings dashboard (ownership split, charts, 25 deadliest corridors) |
| **Explore** (`#/explore`) | The citywide map. One analytic "lens" at a time (Road ownership / Sidewalk inventory / Crash density); crash dots always visible and clickable; signals and sidewalk segments clickable |
| **Investigate** (`#/investigate`) | The location microscope: address or coordinates in → full facts card (road, owner, sidewalk status, ±300 m crash count, time breakdown, nearest intersection/crossing) + hard-zoomed corridor view |
| **Methodology** (`#/methodology`) | Plain-language source → rule → limitations documentation of every pipeline stage |

The page is **self-contained** (crash data and search index embedded, ~5.3 MB) so corridor and
intersection search work even from a local file. Two Vercel serverless functions supplement it:
`api/geocode.js` (address → coordinates via the US Census geocoder; needed because Census sends no
CORS header) and `api/incident-context.js` (the AI drafting layer — **not enabled in the public
build**; see Open Items).

### Which script generates what, and the build order

Scripts live in `scripts/`, numbered, and run in order. The full from-scratch order (verified by
reading each script's declared inputs/outputs):

| Step | Script | Produces |
|---|---|---|
| 1 | `01_download_crashes.py` | Raw crash pages (`data/raw/`), person-row CSV, deduplicated one-row-per-crash CSV |
| 2 | `02_download_roads.py` | `state_routes.geojson`, `memphis_boundary.geojson` |
| 3 | `03_spatial_join.py` | Memphis-filtered, first-pass-classified `shelby_crashes_classified.csv` |
| 4 | `05_download_streets.py` | `memphis_streets.geojson` — the full street network (~91 MB, gitignored; regenerate from the API) |
| 5 | `06_join_streets.py` | `shelby_crashes_named.csv` (nearest named street per crash), `deadliest_streets.csv` |
| 6 | `14_segment_jurisdiction.py` | Segment-level ownership (`shelby_crashes_named_seg.csv`, `ownership_segments.geojson`) |
| 7 | `17_classifier.py` | **The canonical classifier**: `shelby_crashes_final.csv`, `road_ownership_rulebook.geojson`, `ownership_segments_final.geojson`, `outputs/final_numbers.md` |
| 8 | `19` → `20` → `21` | TDOT pedestrian signals: raw → deduped crossings (one per intersection) → per-crash signal attributes + covered intersections |
| 9 | `22_osm_crossings_eval.py` | OSM crosswalk completeness report (read-only gate for step 10) |
| 10 | `23_union_poc.py` | Union Ave safe-crossing analysis: `union_safe_summary.json`, `union_poc.html`, report |
| 11 | *(manual step — no script)* | `data/processed/memphis_sidewalks_32136.geojson` from the sidewalk file-geodatabase (see §3) |
| 12 | `18_build_public_map.py` | `outputs/interactive_map/index.html` — the page shell, map, dashboard, methodology |
| 13 | `25_rebuild_junctions.py` | `intersection_nodes_all.geojson` (every junction citywide), `covered_corridors.json`, re-attributed `shelby_crashes_signals.csv` |
| 14 | `24_build_search.py` | `search_index.json` + injects search, Count-A, and the Investigate wiring **into** `index.html` |

Scripts `04`, `07`–`12`, `15`, `16` are one-off statistics/audit steps or superseded prototypes —
not needed for a rebuild. `26_build_incident_demo.py` injects the AI demo tab **locally only** and
is deliberately not part of the public build.

**Routine rebuild** (data refresh, no methodology change): `01 → 03 → 06 → 14 → 17 → 21 → 23 → 18
→ 25 → 24`. Scripts 18 and 24 print a reconciliation (totals, 25-corridor match) on every run —
**if it doesn't print OK, stop and investigate before deploying.** The current sanity anchors are
in `CLAUDE.md`; they shift slowly as the state's rolling window advances, so re-verify rather than
assume.

**View locally:** `.\.venv\Scripts\python.exe -m http.server 8000 --directory outputs\interactive_map`
then open `http://localhost:8000/index.html`. (Address search needs the deployed `/api` functions.)

## 3. Data sources — origin, refresh, caveats

| Source | Origin | Refresh | Caveats |
|---|---|---|---|
| **Crashes** | TDOT SAFETY MapServer, layer 8 (`tnmap.tn.gov/arcgis/rest/services/SAFETY/MapForDashboards/MapServer/8/query`) — public, no key. Full reference: `outputs/data_source.md` | Re-run `scripts/01_download_crashes.py` (it re-downloads when the upstream count changes), then the routine rebuild chain | One row per **person**, deduped to crashes; pedalcyclists excluded by design. **Rolling ~3-year window** — old records fall out as new ones arrive. **Freshness measured:** newest upstream record was 1 day old when probed 2026-07-12 (typically ~1–3 days), but recency ≠ completeness — police reports are finalized with a lag, so the last several weeks always undercount. As of this writing the local snapshot ends **2026-05-26** while the endpoint already holds July records — run a refresh before the next publication. |
| **Roads / boundary / street network** | City of Memphis Public Works GIS (ArcGIS REST) | `02` (routes/boundary), `05` (street network) | Network is the city's centerline file; `LANES`/`SPDLIMIT` attributes are the city's, taken as-is |
| **Sidewalk inventory** | City of Memphis (delivered as `Memphis_Sidewalks_DMC (1).zip` → a `Memphis_Sidewalks_V2` file-geodatabase; 46,875 lines with `STREET_NAME` and `WIDTH`) | No refresh endpoint — a new delivery would come from the city. To regenerate the working file: read the GDB layer with geopandas and write `data/processed/memphis_sidewalks_32136.geojson` in EPSG:32136 *(this conversion was a one-off manual step; there is no numbered script for it)* | **Vintage unknown** — the GDB carries no collection-date metadata (internal file timestamps are Jan 2025, which reflects export, not survey date). **Redistribution permission is pending** — do not republish the raw layer until the city confirms. This is why the site only ever says "in city inventory" / "none found in city inventory (absence may reflect incomplete records)" — never a flat "no sidewalk." |
| **Pedestrian signals** | TDOT "ADA Asset Data" FeatureServer (geodata.tn.gov Hub item `69511fa73a584e2bb37acfa85b177fa5`, layer 1) | Re-run `19 → 20 → 21`, then `25 → 24` | An asset inventory: it records where TDOT has inventoried signals, mostly along state routes. Off covered corridors the site says "not yet analyzed" — absence of inventory is not "no signal" |
| **OSM crosswalks** | OpenStreetMap via Overpass (ODbL) — `22` acquires and evaluates | Re-run `22`, review the report, then `23` | **Union Avenue only** so far. OSM completeness varies block to block; `outputs/osm_crossings_eval.md` recommends an imagery spot-check before extending citywide. ODbL attribution required |
| **Geocoding** | US Census Bureau geocoder via `api/geocode.js` | none needed | Free, no key; occasionally misses newer addresses |

## 4. Known open items (honest and complete)

1. **AI drafting layer is local-only.** The "Report a New Incident" tool (script `26` +
   `scripts/incident_demo_server.py` + `api/incident-context.js`) exists and works, but it is
   **not injected into the public build**. Why: it spends OpenAI credits per use (needs
   `OPENAI_API_KEY`, ideally `INCIDENT_ACCESS_CODE` and a hard spending limit before any public
   exposure), and the team chose to launch with the deterministic facts only. The public page
   carries an honest "AI-assisted drafting: in development (beta)" note. The deterministic facts
   API it relies on (`window.CountA.facts`) ships and is tested.
2. **Safe-crossing / longest-gap statistics are preliminary.** The Union Ave numbers (24 safe
   crossings, 22% of crossing-relevant crashes >250 ft, 2,921 ft longest gap) are a **proof of
   concept on one corridor**, pending imagery ground-truthing of the OSM crosswalk layer
   (`outputs/osm_crossings_eval.md` describes the recommended check). They are labeled
   "preliminary" in the README, the Union report, and on the site's Union card. Do not extend
   citywide before ground-truthing.
3. **Live-update pipeline: designed, NOT built.** See §5. Today the site updates only when someone
   re-runs the pipeline and redeploys.
4. **Sidewalk data vintage unknown; redistribution permission pending.** See §3.
5. **Name collision:** "streetStat" is also the name of a Massachusetts pharmaceutical consultancy
   (streetStat LLC). Known and accepted by the project owner; revisit only if the project seeks
   trademark or wide distribution. *(Not verifiable from the repo — recorded from the project
   owner.)*
6. **Superseded figure in the living stats document.** `novel_statistics.docx` contains an early
   "~50/50 signalized/unsignalized" intersection split; a dated correction appended 2026-07-12
   supersedes it with the current verified **39.9% signalized / 60.1% unsignalized** (298 covered
   at-intersection crashes). Cite the correction, not the original.
7. **Nothing else is TODO-flagged.** A code sweep found no other TODO/FIXME markers; the only
   "beta" wording is the AI note above.

## 5. Live-update pipeline — the build plan (not yet implemented)

Verified against the endpoint (details and tested queries in `outputs/data_source.md`): the crash
layer is a standard ArcGIS REST `/query` endpoint that supports **date filtering**
(`CollisionDate` is a true date field), **pagination** (`resultOffset`/`resultRecordCount=2000`),
and **cheap count-only probes**. A competent developer can implement:

- **Weekly incremental pull.** Query with the existing `where` clause **plus a CollisionDate
  floor**: `AND CollisionDate >= DATE '<local_dmax minus 30 days>'` (the 30-day overlap catches
  late-arriving reports for recent dates). Page through, dedupe person-rows to crashes, and merge
  into the local crash file **keyed on `MstrRecNbrTxt`** (replace matching ids, append new ones —
  never blind-append).
- **Monthly full refresh.** Re-run the unfiltered pull (script `01` already does this with a
  count-change check). This is **required, not optional**, for two things incremental pulls cannot
  see: **backfills/corrections** to older records, and the **trailing edge of the rolling ~3-year
  window** (old crashes silently drop out upstream; totals are only correct after a full pull).
- **After either pull:** run the routine rebuild chain (§2), require the printed reconciliation to
  pass (totals will legitimately drift as the window advances — the check is that surface +
  limited-access sums match the new dedup total, and the 25-corridor table matches the index),
  update the sanity anchors in `CLAUDE.md`, and redeploy. If reconciliation fails, do not deploy.
- **Scheduling:** GitHub Actions cron (or any weekly scheduler) is sufficient; total runtime is
  minutes. Keep the raw page dumps it writes out of git (`data/raw/` is already the convention).
- **Display:** the "Data current through …" labels on the site are computed from the data at build
  time, so they update automatically.

## 6. Operating costs and monthly maintenance

**Costs (as configured today):**
- **Hosting: $0.** A static page + two small serverless functions fit Vercel's free (Hobby) tier.
  No database, no paid APIs. The custom-work items (`OPENAI_API_KEY`) are only needed if the AI
  layer is ever enabled — set a hard spending limit on that key if so.
- **Data: $0.** All sources are public endpoints without keys.
- **Domain:** currently the free `*.vercel.app` URL; a custom domain would be the only recurring
  cost (~$10–20/yr).

**Monthly maintenance (~1–2 hours):**
1. Refresh the data (run `01`, then the routine rebuild chain) and confirm the printed
   reconciliation passes.
2. Update the sanity anchors in `CLAUDE.md` to the new totals; skim the findings page for anything
   that reads oddly against the new numbers.
3. Redeploy (push the rebuilt `outputs/interactive_map/` to Vercel) and spot-check: one corridor
   search, one intersection, one Investigate lookup, one address (exercises `/api/geocode`).
4. Once a quarter: re-pull signals (`19`–`21` → `25` → `24`) and re-check that the source
   endpoints haven't changed schema (script `01` will fail loudly if the crash API changes).

## 7. How to cite StreetStat

> StreetStat — pedestrian crash & infrastructure context for Memphis. Built by Samarth Desai, in
> support of pedestrian-safety advocacy with Street Fair Memphis and Innovate Memphis.
> https://memphis-pedestrian-incident-context.vercel.app/ (accessed *date*). Crash data: Tennessee
> SAFETY MapServer (TDOT), window Jan 1 2023 – May 26 2026 *(use the "data current through" date
> shown on the site at access time)*. Roads, boundary, and sidewalk inventory: City of Memphis
> Public Works. Pedestrian signals: TDOT ADA Asset Data. Crosswalks: © OpenStreetMap contributors
> (ODbL).

When citing a specific number, prefer the wording the site itself uses (shares of *surface-street*
crashes, deaths *on roads with* 4+ lanes, etc.) — the qualifiers are part of the finding. For the
methodology behind any figure, cite the site's Methodology page or `novel_statistics.docx`
(including its 2026-07-12 correction section).

---

*Code is MIT-licensed. Source data remains under its providers' terms. The pipeline's own rule,
worth keeping: compute every statistic from the data files — never hardcode a number into an
output.*

---

## Addendum (2026-07-12, same night): full-network search

The search overhaul added after this document was first written:

- **`scripts/27_build_locate_index.py`** (runs after 25, before 24) preprocesses the full street
  network into a compact lookup — `outputs/interactive_map/api/locate_data.json` (~2.9 MB: all
  16,719 named Memphis streets with bbox/length/owner/crash-count, the 25,533-junction index, and
  a 97-key state-route alias table derived from the data).
- **`api/locate.js`** — a third Vercel serverless function: `GET /api/locate?q=...` answers
  street and intersection queries over the full network with forgiving matching (case/suffix/
  directional-blind, "and"/"&"/"@", 1–2-char typos, aliases). Bundles the JSON via `require`;
  measured cold start ~0.3–0.4 s, warm queries under ~55 ms. Test it locally with
  `node scripts\locate_dev_server.js`.
- The page's own matcher gained the same forgiveness for the embedded index, and calls
  `/api/locate` only when the embedded index can't resolve a query. A street outside the
  529 crash corridors returns an honest minimal card (0 incidents recorded, owner from the
  rulebook, "not analyzed" for sidewalk/stretch fields — never fabricated analysis).

**Needs the deployed server (won't work on `file://`):** address search (`/api/geocode`) and
full-network street lookup (`/api/locate`). Everything else — map, lenses, feature popups,
corridor/intersection search including casual/typo/alias forms, coordinate lookups, Investigate
coordinates mode — is embedded and works offline. The page says so honestly when offline.
