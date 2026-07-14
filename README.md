# Memphis Pedestrian Safety — *by who owns the road*

**An interactive map + data analysis showing that Memphis's pedestrian deaths concentrate on a small set of wide, fast arterials — reframing them as a systemic infrastructure problem, not individual error, and pinning down who owns those roads.**

![The interactive crash map, with crashes colored by road owner and a findings dashboard](docs/hero.png)

> 🔗 **Live site: [streetstat.org](https://streetstat.org/)** — explore the map, search any street / intersection / address, or look up any location (address / coordinates) in the Investigate tab for a road-attributed crash report. (Also runs locally in ~2 min → [**Run it locally**](#-run-it-locally).)

---

## The problem

Memphis has one of the worst pedestrian fatality rates in the United States, and local coverage often frames each death as the victim's mistake — "jaywalking," "stepped into traffic." This project tests a different hypothesis with public data: that these deaths cluster on roads **engineered for speed and throughput**, and that the responsibility is therefore a *design* question. The first thing nobody had published a Memphis-specific number for: **who owns the deadly roads** — the City of Memphis, or the Tennessee Department of Transportation (TDOT)?

## Key findings

*All figures are computed from the data and reconcile to fixed totals — 1,337 pedestrian/non-motorist crashes inside Memphis, 179 fatal (2023-01-01 → 2026-07-11; the window advances as the data refreshes — the live site's "data current through" label is authoritative).*

- **~75–80% of crashes (and ~69–72% of deaths) are on City-of-Memphis roads; ~20–25% of crashes (28–31% of deaths) on TDOT state routes.** State arterials are over-represented in *deaths* relative to their crash share — i.e. deadlier per crash. Interstates and other limited-access roads add **35 more crashes (14 fatal)**, reported separately.
- **76.5% of pedestrian deaths happen after dark**; 14.0% on dark, *unlit* roads.
- The design signature: **63.1% of deaths are on roads with 4+ lanes** and **60.3% on roads posted ≥40 mph.** Just over half (50.3%) are on roads that are *both* — wide *and* fast (for exposure context, 4+ lane roads are only ~11% of surface-street mileage).
- Deaths concentrate on a handful of corridors: **Poplar (46 crashes / 9 fatal), Union (37 / 8), Lamar (33 / 7), Winchester (28 / 5)** lead the ranking of 545 streets.
- **Proof of concept on Union Ave (preliminary):** ~**1 in 5** crossing-related crashes happened **more than 250 ft from the nearest safe crossing**, and one **2,921 ft stretch (~9.7× the FHWA ~300 ft best-practice spacing)** has no crossing at all. *These crossing-distance figures are Union-only and provisional pending imagery ground-truthing of the OSM crosswalk layer.*

> The rigor is the point: every number is recomputed from raw data, reconciled to the fixed totals, and stated **descriptively** — the project never claims a road "causes" a death or that one road is "N× deadlier."

## What it does

- **Interactive map** — every crash as an individual dot, colored by road owner (City / TDOT state route / limited-access), deaths emphasized; layer toggles, a fatal-only filter, a "hotspots" intensity view, and a TDOT signalized-crossing layer.
- **Jurisdiction analysis** — a documented, rulebook-driven classifier tags every road segment by owner and attributes each crash to it, with per-crash provenance.
- **Signal & crossing layers** — the TDOT pedestrian-signal inventory plus OpenStreetMap crosswalks, with an along-corridor distance-to-crossing analysis.
- **Sidewalk presence** — the City of Memphis sidewalk inventory (46,875 lines) is checked per road location; results read *"Sidewalk present in city inventory"* or *"No sidewalk found in city inventory (absence may reflect incomplete records)"* — never a flat "no sidewalk."
- **Search** — type-ahead lookup of any corridor or any of the **25,533 street junctions citywide** (built from true geometric centerline intersection, with divided-arterial carriageways consolidated to one node), each with a clean stat card and map highlight; a junction with no recorded crashes returns an honest *"0 incidents reported here,"* never a blank. Address search is wired but pending a backend — see [roadmap](#-status--roadmap).
- **Findings dashboard** — charts and the deadliest-corridor table, all computed from the data.

## 📸 Screenshots

<!-- ============================================================================
     SCREENSHOTS BLOCK — easy to refresh after a big change.
     To update: drop new PNGs into  docs/screenshots/  using the EXACT filenames
     below (overwrite the old ones). Nothing else to edit. Recommended width ~1400px.
       01-map-overview.png    — the full interactive map
       02-search-count-a.png  — a search/click result card (road + owner + Count A)
       03-city-vs-state.png   — the "See City vs State segments" corridor view
       04-dashboard.png       — the findings dashboard + deadliest-corridors table
     ============================================================================ -->

| The map — crashes by who owns the road | Road-attributed search (Count A) |
|---|---|
| ![Interactive map with crashes colored by road owner](docs/screenshots/01-map-overview.png) | ![Search result card: snapped road, owner, and crashes on the ±300 m stretch](docs/screenshots/02-search-count-a.png) |
| City vs State segment breakdown | Findings dashboard |
| ![A corridor colored by owner: teal = City of Memphis, crimson = TDOT/State](docs/screenshots/03-city-vs-state.png) | ![Findings dashboard and the 25 deadliest corridors](docs/screenshots/04-dashboard.png) |

<!-- SCREENSHOTS BLOCK END -->

## Methodology — how the data works

This is the real differentiator. Sources and provenance:

| Layer | Source (exact origin) |
|---|---|
| Pedestrian/non-motorist crashes | Tennessee **SAFETY MapServer** (TDOT), Layer 8 — `https://tnmap.tn.gov/arcgis/rest/services/SAFETY/MapForDashboards/MapServer/8/query` (public, no key). Query scope: `County='Shelby' AND PersonType<>'Pedalcyclists'` — pedestrians + other non-motorists in Shelby County; pedalcyclists excluded by design. Coverage window at this writing: **Jan 1, 2023 – Jul 11, 2026** (the state's rolling ~3-year file; advances on every refresh — the site's "data current through" label is authoritative). Full endpoint reference: `outputs/data_source.md` |
| State routes, city boundary, street centerlines | **City of Memphis Public Works GIS** — ArcGIS REST services (state-route, city-boundary, and street-centerline layers, retrieved by `scripts/02_download_roads.py` and `scripts/05_download_streets.py`); the road-ownership rulebook is derived from these by `scripts/17_classifier.py` |
| Pedestrian signals | **TDOT "ADA Asset Data"** FeatureServer — geodata.tn.gov Hub item `69511fa73a584e2bb37acfa85b177fa5`, layer 1 (Pedestrian Signal), Shelby County extract (`scripts/19_acquire_ped_signals.py`) |
| Crosswalks | **OpenStreetMap** via Overpass — © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/). Used for the **Union Ave corridor analysis only** so far (citywide use pending imagery ground-truthing) |
| Sidewalks | **City of Memphis (Engineering)** sidewalk inventory — received June 2026 as a file-geodatabase export (`Memphis_Sidewalks_V2`; zip dated April 2026, internal timestamps January 2025). **Survey vintage unknown.** Redistribution permission granted (recorded July 2026); the reprojected working file is committed in `data/processed/` |
| Address geocoding | **US Census Bureau** onelineaddress geocoder (proxied by `api/geocode.js`; public, no key) |

Credibility principles baked into the pipeline:

- **Computed, never hardcoded** — every displayed figure is derived from the data files at build time.
- **Reconciled** — all jurisdiction/severity splits sum back to **1,294 crashes / 175 deaths**.
- **Correct geometry** — all distance math in **EPSG:32136** (NAD83 / Tennessee, meters); never Web Mercator (which stretches distance ~22% at this latitude).
- **Descriptive, not causal** — shares and distances only; no inflated "deadlier" claims.
- **Honest about coverage** — where signal/crossing data is incomplete, fields read **"not yet analyzed,"** never a fabricated number.

The jurisdiction classifier (`scripts/17_classifier.py`) tags each centerline segment by an **ordered rulebook** (interstate → ramp → limited-access override → state-route geometric overlap → completeness override → city residual) and records **which rule fired**, so every crash's classification is auditable.

> **Attribution caveat (point search).** Incidents are matched to roads by the nearest point to the true road centerline. Near intersections, a point may attribute to a cross street rather than the main road. Points on roads with no recorded pedestrian crashes snap to the nearest road that has them — so always check the road name and snap distance shown on each result.

---

## 🛠 Tech stack

- **Analysis:** Python · GeoPandas · Shapely · pyproj · pandas · NumPy
- **Front end:** Leaflet.js · Chart.js (self-contained HTML — the map embeds its own data)
- **Data/IO:** ArcGIS REST APIs · OpenStreetMap Overpass · US Census geocoder · python-docx
- **Tooling:** headless Chrome (render & verify) · Python venv

## 📁 Repo structure

```
scripts/         # numbered, reproducible pipeline (01–25): download → classify → analyze → build
data/
  raw/           # API downloads (geojson/csv); the 91 MB street network + page-dumps are .gitignored
  processed/     # deduped + classified crashes, the road-ownership rulebook, audit outputs
outputs/
  interactive_map/   # index.html (the app) + slim ownership geojson + search_index.json
  *.md               # audit & methodology reports (final numbers, completeness, OSM eval, Union POC)
docs/            # README assets
README.md · CLAUDE.md · requirements.txt
```

**Pipeline flow:** download crashes + roads → filter to the Memphis boundary → classify each crash by road owner (rulebook) → match to nearest named street + rank corridors → add signals/crossings → build the map, dashboard, and search.

## ▶ Run it locally

```bash
# 1. set up the environment
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. (optional) regenerate the large gitignored street network (~91 MB)
.\.venv\Scripts\python.exe scripts\05_download_streets.py

# 3. run the pipeline (scripts run in numeric order, 01 → 25); the key build steps:
.\.venv\Scripts\python.exe scripts\17_classifier.py          # classify crashes by road owner
.\.venv\Scripts\python.exe scripts\18_build_public_map.py    # build the map + dashboard
.\.venv\Scripts\python.exe scripts\25_rebuild_junctions.py   # rebuild every junction (true intersection)
.\.venv\Scripts\python.exe scripts\24_build_search.py        # add the search index + UI

# 4. view it — serve over http so EVERY feature works
.\.venv\Scripts\python.exe -m http.server 8000 --directory outputs\interactive_map
#    then open http://localhost:8000/index.html
```

> Serve it over `http://` (step 4), not by double-clicking the file — browsers block some features (like address search) on `file://`.
> `data/raw/memphis_streets.geojson` is gitignored to keep the repo light; script 05 regenerates it from the source API (so totals may shift slightly as the rolling ~3-year crash window advances).

## 🚦 Status & roadmap

- **Done:** jurisdiction classifier · interactive map + findings dashboard · corridor/intersection search · road-attributed point lookup (address / coordinates, in the Investigate tab) · signalized-crossing analysis · Union Ave distance-to-crossing proof of concept (preliminary) · **City-of-Memphis sidewalk-presence layer**.
- **In progress:** Vercel deployment (a live URL).
- **Next:** live auto-refresh from the crash API · extend the crossing-distance analysis citywide (after OSM ground-truthing).

### Serverless functions (Vercel)

Two small functions supplement the static page; **neither needs any secret or environment variable**:

| Function | Purpose | Secrets |
|---|---|---|
| `api/geocode.js` | US Census address → coordinates (Census sends no CORS header, so the browser can't call it directly) | none |
| `api/locate.js` | full-network street / intersection search over a preprocessed ~2.9 MB lookup | none |

For local development, `scripts/dev_server.py` serves the built page plus a local `/api/geocode`
(and proxies `/api/locate` to `node scripts/locate_dev_server.js` when that's running), so address
search works on localhost exactly as deployed.

> An AI drafting layer ("Report a New Incident") was prototyped during development and **removed
> before launch** — the code remains retrievable from git history. Any future AI feature must use
> its own API key and must never commit credentials.

---

## Data sources, attribution & license

- **Crashes:** Tennessee SAFETY MapServer (TDOT), layer 8 (`tnmap.tn.gov/.../SAFETY/MapForDashboards/MapServer/8`) — public, no login; Shelby County pedestrian/non-motorist scope; rolling window (Jan 1, 2023 – Jul 11, 2026 at this writing — the site's "data current through" label is authoritative).
- **Roads / boundary / streets:** City of Memphis Public Works GIS (ArcGIS REST).
- **Pedestrian signals:** TDOT "ADA Asset Data" (geodata.tn.gov Hub item `69511fa73a584e2bb37acfa85b177fa5`, layer 1).
- **Sidewalks:** City of Memphis (Engineering) sidewalk inventory — received June 2026; survey vintage unknown; redistribution permission granted (July 2026).
- **Crosswalks:** © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/) — Union Ave corridor analysis only.
- **Geocoding:** US Census Bureau geocoder.
- Developed in support of pedestrian-safety advocacy with **Street Fair Memphis** and **Innovate Memphis**.

> **Data provenance.** All statistics on StreetStat are computed by its own open-source pipeline from
> public data sources. They are not official figures published by TDOT or the City of Memphis and may
> differ from official counts due to methodology. Exact attribution and counting methods are documented
> on the [Methodology page](https://streetstat.org/#/methodology).

- **License:** [MIT](LICENSE) for the code. Source data remains under its respective providers' terms.

## About

Built by **Samarth Desai**.

> I built this because Memphis's pedestrian deaths are too often written off as individual mistakes, when the data points to roads engineered in ways that make those deaths predictable. I wanted a tool that lets journalists and advocates *see* — and cite — where the responsibility actually sits.

- **Email:** [sdesai25@unc.edu](mailto:sdesai25@unc.edu)
- **LinkedIn:** [linkedin.com/in/samarthdesai06](https://www.linkedin.com/in/samarthdesai06)
- **GitHub:** [@sdesai25unc](https://github.com/sdesai25unc)

---

## 🎨 Changelog

*(Historical notes — figures cited in each dated entry below reflect that date's data window, not the
current totals; the live site is always authoritative.)*

### StreetStat UI/UX redesign (2026-07-11)

The public page was rebranded **StreetStat** and restructured into a four-view product, with the
underlying data, methodology, and every computed number **unchanged** (regression-verified: 1,294 / 175;
Poplar 44/8 · Union 36/8 · Lamar 30/6 · Winchester 28/5; all 25 deadliest corridors; `Count-A` facts
byte-identical at the verification anchors). Presentation-layer work only, in the existing generators:

- **`scripts/18_build_public_map.py`** — now emits the StreetStat shell: Geist / Geist Mono type
  (fontsource CDN, graceful system-font fallback on `file://`), a neutral design-token system
  (near-white surface, ink text, indigo accent for interaction only; the semantic data colors —
  teal = City, crimson = TDOT, charcoal = limited-access, blue/amber = sidewalk — are unchanged),
  a sticky top nav, and four hash-routed views on the single self-contained page:
  - **`#/` Home** — hero (name, honest subtitle, thesis) + four computed stat cards + the full
    findings dashboard (all previous cards/charts/tables, restyled).
  - **`#/explore`** — the citywide map with a **one-lens-at-a-time** control
    (Road ownership / Sidewalk inventory / Crash density) replacing the checkbox stack; crash dots
    stay visible in every lens; *Fatal only* and *Signalized crossings (TDOT)* remain independent
    toggles; owner rows in the legend click to filter dots; legend shows only the active lens.
  - **`#/investigate`** — the location microscope: address / coordinates / map-click in, full facts
    card out (road, owner, snap distance, sidewalk status, ±300 m network-distance count, whole-road
    totals, always-expanded time table, nearest intersection, nearest safe crossing where analyzed),
    with the map hard-zoomed to the corridor showing ownership glow + sidewalk-status coloring +
    the ±300 m window bars + intersection ring at once. Same `snapBest`/`netCount` pipeline as the
    Explore card, so the numbers are provably identical.
  - **`#/methodology`** — plain-language, source → rule → limitations documentation of all seven
    pipeline stages (crash data, road attribution, ownership rulebook, corridors & along-road
    counting, intersection index, sidewalk presence, safe-crossing PoC), with thresholds stated and
    per-section script links; counts (junctions, sidewalk lines, crossings, Union PoC figures) are
    read from the data files at build time.
- **`scripts/24_build_search.py`** — search/injection bundle restyled onto the design tokens; the
  sidewalk layer registers as the Explore *Sidewalks* lens; adds the Investigate wiring; and fixes a
  pre-existing bug where clicking the "Search address:" dropdown row threw a swallowed TypeError
  (`pick()` now routes address rows to `openAddress` directly).
- **Not in this build:** the AI "Report a New Incident" prototype (never injected into the public
  page, and later removed from the project entirely on 2026-07-13 — retrievable from git history).
  `api/geocode.js` is unchanged and still powers address search when deployed.

Build order is unchanged (`18` → `24`); `data/processed/search_index.json` re-emits byte-identical.
A 40-check headless regression (Playwright + installed Chrome, incl. an emulated `/api/geocode` to
test address search end-to-end, plus a `file://` degradation pass) passed 40/40 on this build.

### Interaction-model update (2026-07-12 — local, not committed)

- **Click-to-locate removed.** Empty-map clicks no longer run a Count-A lookup; the Investigate tab
  (address / coordinates) is the only path to a full location report. The popup-timing conflict
  handler and empty-click marker logic this required were deleted with it.
- **Features are directly clickable instead.** Crash dots (top click priority), TDOT signal markers
  (location + inventory provenance), and — with the Sidewalks lens on — sidewalk segments (honest
  status wording, street name, inventory width where recorded; `sww` width arrays added to the
  search index). All vectors share one canvas and the lens renderer re-raises signals then dots
  after every change, so a dot click is never swallowed by a line beneath it (verified with real
  mouse-click tests on a dot lying directly over a sidewalk line).
- **Lanes statistic got exposure context.** The findings card now adds a computed caption:
  roads with 4+ lanes account for **11.3% of surface-street mileage** in the network (lengths in
  EPSG:32136; LANES joined from the raw city centerline file onto the rulebook network by OBJECTID;
  lane data covers 100.0% of network mileage). The 62.9%-of-deaths statistic itself is unchanged.

### Search overhaul (2026-07-12 — local, not committed)

Street/intersection search now works to a navigation-tool standard: casual queries
(case/suffix/directional-blind, "and"/"&"/"@", 1–2-character typos, state-route aliases built
from the data, e.g. "us 51" → Elvis Presley Blvd) resolve against the embedded index, and a new
**`/api/locate`** serverless endpoint (backed by a preprocessed ~2.9 MB lookup built by
`scripts/27_build_locate_index.py`) makes **every named Memphis street (16,719) and every mapped
junction findable** — including zero-crash residential streets, which return an honest minimal
card ("0 pedestrian incidents recorded here", owner from the rulebook, "not analyzed" for fields
we didn't compute). Ambiguous queries (N vs S variants) list candidates and never silent-pick.
Verified: casual-query hit rate 81% → **100%** on a 186-query test set; all existing features and
headline stats unchanged (1,294/175 reconciliation printed at build).
