# Memphis Pedestrian Safety — Crash Data Project

**Started: 2026-05-29**

## What this project is

Memphis has one of the worst pedestrian fatality rates in the United States.
Local news often frames each crash as the victim's fault ("jaywalking,"
"stepped into traffic"). The goal of this project is to produce a
Memphis-specific breakdown of crashes by **who owns the road** they happened on
— City of Memphis vs. the Tennessee Department of Transportation (TDOT) —
because pedestrian crashes are widely believed to concentrate on state-owned
arterial roads, but no one has published a Memphis-specific number for this.

The eventual deliverable is a **map + short brief** that journalists can cite.

> Session/agent working rules (venv usage, the inspect-then-ask rule, file
> protections, methodology constants, sanity-check anchors) live in `CLAUDE.md`
> at the project root and are loaded automatically each session.

## Phases completed

- **Phase 1 + 2 — project setup + crash data download (2026-05-29).** Pulled
  the Shelby County non-motorist crash data (pedestrians + other non-motorists,
  pedalcyclists excluded) from the TDOT SAFETY MapServer and saved person-row
  and one-row-per-crash CSVs. *(script 01)*
- **Phase 3 + 4 — road download + jurisdictional classification (2026-05-29/30).**
  Downloaded the City of Memphis state-route and city-boundary layers,
  filtered crashes to inside the city, and classified each in-Memphis crash as
  on a **TDOT** state route or a **City of Memphis** road by nearest-road
  distance. Produces `shelby_crashes_classified.csv`, plus a static prototype
  sanity map. *(scripts 02, 03, 04)*
- **Phase 5 — street network + deadliest-streets ranking (2026-05-30).**
  Downloaded the full Shelby street centerline, matched every in-Memphis crash
  to its nearest named street, and built the project's first **deadliest-streets
  ranking** (529 streets). Produces `shelby_crashes_named.csv` and
  `deadliest_streets.csv`. *(scripts 05, 06)*
- **Statistics resource — verified "novel statistics" (2026-06-01).** Computed
  and verified every headline figure straight from the data, captured them in a
  rubric (`novel_statistics.md`) + a living Word document (`novel_statistics.docx`).
  *(scripts 07, 08)*
- **v1 interactive map (2026-06-01).** Built a self-contained Leaflet web map
  (`outputs/interactive_map/index.html`) that opens by double-click — fatal
  crashes emphasized, non-fatal clustered, top-25 deadliest corridors, by road
  owner. *(script 09)*
- **Lighting stat + map dashboard (2026-06-04).** Computed the lighting finding
  (76.6% of in-Memphis pedestrian deaths after dark; 14.3% on dark unlit roads)
  and appended a stats/findings dashboard (hero cards, Chart.js charts, top-25
  table) below the map, making it one map-plus-dashboard page. *(script 10)*

## Data source

**Crashes:** Tennessee SAFETY MapServer, **Layer 8 (Non-Motorist Crashes)**,
maintained by TDOT. Public ArcGIS REST endpoint, no login.
Filter: Shelby County, excluding pedalcyclists. One report number
(`MstrRecNbrTxt`) can appear on multiple rows — one row per person.

**Roads + boundary:** City of Memphis Public Works `PW_Support_Layers`
MapServer. **Layer 17** = state routes (TDOT-owned roads inside Memphis, every
segment tagged `State_Route="Yes"`, `Funding_Source="TDOT"`). **Layer 15** =
the City of Memphis municipal boundary. Public ArcGIS REST endpoints, no login.

## Data files

In `data/raw/` (raw downloads — never hand-edit):

- `shelby_crashes_page_001.json` — raw crash API response page(s).
- `shelby_crashes_all_persons.csv` — **one row per person** (1,467 rows).
  Primary file for "people affected" counts.
- `state_routes_page_001.json` — raw state-route API response page(s).
- `state_routes.geojson` — the **1,652 state-route segments** as lines, in
  lat/long (EPSG:4326). 0 segments were dropped for missing geometry.
- `memphis_boundary.json` — raw boundary API response.
- `memphis_boundary.geojson` — the City of Memphis outline as one polygon, in
  lat/long (EPSG:4326).
- `memphis_streets_page_XXX.json` — raw street-network API response pages.
- `memphis_streets.geojson` — the **full street network for Shelby County**
  (**55,141 line segments**, 39,652 of them inside the City of Memphis), in
  lat/long (EPSG:4326). All 62 source attributes kept, including the full-name
  field `LABEL` and components `PREDIR/NAME/TYPE/SUFDIR/SUBNAME/ALTNAME_1`.
  Used to attach a street name to every crash and to draw streets on the
  eventual interactive map. (~96 MB.)

In `data/processed/`:

- `shelby_crashes_dedup.csv` — **one row per crash** (1,390 rows), deduplicated
  by report number, with the worst injury severity preserved and a
  `VictimsInCrash` count. This is the input to the spatial join.
- `shelby_crashes_classified.csv` — the dedup file (1,390 rows) plus the
  classification columns: `InMemphis`, `Jurisdiction`
  (`TDOT` / `City of Memphis` / `Suburban-Shelby` / `Excluded-BadGeo`),
  the matched `StateRoute_*` attributes (populated only for TDOT crashes), and
  `DistToStateRoute_m`. (0 crashes were excluded for bad location.)
- `shelby_crashes_named.csv` — the **1,294 in-Memphis crashes** (TDOT + City of
  Memphis) with each matched to its nearest street. Adds `Street_Name`,
  `DistToStreet_m`, `Street_SPDLIMIT`, `Street_LANES`, `Street_ONEWAY`,
  `Street_CITY_L`, `Street_COUNTY_L` (existing `StateRoute_*` columns are kept).
- `deadliest_streets.csv` — the deadliest-streets ranking: **529 streets** with
  `Total_Crashes`, `Fatal_Crashes`, `Serious_Injuries` (Suspected Serious
  Injury), `Dominant_Jurisdiction`, `Mixed_Jurisdiction` (true if no single
  jurisdiction is ≥90%), and the street's modal `SPDLIMIT` / `LANES`. Sorted by
  total crashes. Crash counts sum to the 1,294 input crashes.
- `novel_statistics.md` — the **rubric/template** for the statistics document:
  what each section must contain, the fixed definitions and denominator rules,
  and how each figure is verified. It is *instructions*, not the filled-in
  numbers.
- `novel_statistics.docx` — the **living statistics document** (the filled-in,
  verified content the `.md` rubric specifies): scope, jurisdiction split,
  deadliest streets, road-character/design-problem stats, concentration of
  deaths, where victims were killed, year-by-year, plus external/cited context
  and the to-compute backlog. This is the file that gets added to and updated;
  Section A numbers are reproducible via `scripts/07_compute_novel_stats.py`.

In `outputs/` (deliverables and review extracts):

- `interactive_map/index.html` — the **v1 interactive map** (open by
  double-click; needs internet for the Leaflet CDN + OSM tiles). *(script 09)*
- `interactive_map/deadliest_corridors.geojson` — the extracted top-25 corridor
  geometry (merged per street, clipped to Memphis) used by the map. *(script 09)*
- `prototype_crash_map.png` — the static 300-dpi prototype sanity map. *(script 04)*
- `state_routes_master_list.csv` — the 46 distinct TDOT state-route names (the
  full universe of state routes), with SR number and functional class.
- `crashes_by_state_route.csv` — the 36 state routes that had ≥1 in-Memphis
  crash, with crash / fatal / people counts.

## Scripts

Run each from the project folder in PowerShell. They run in order; script 03
depends on the files script 02 produces.

- `scripts/01_download_crashes.py` — downloads the Shelby County non-motorist
  crash data and writes the person-row and dedup CSVs.
  Run: `.\.venv\Scripts\python.exe scripts\01_download_crashes.py`
- `scripts/02_download_roads.py` — downloads the state-route layer (17) and the
  city-boundary layer (15) and writes `state_routes.geojson` and
  `memphis_boundary.geojson`.
  Run: `.\.venv\Scripts\python.exe scripts\02_download_roads.py`
- `scripts/03_spatial_join.py` — filters crashes to inside Memphis, classifies
  each as TDOT vs City by nearest state route, writes
  `shelby_crashes_classified.csv`, and prints the headline summary.
  Run: `.\.venv\Scripts\python.exe scripts\03_spatial_join.py`
- `scripts/04_prototype_map.py` — draws a single high-resolution prototype map
  (a visual sanity check, **not** the final deliverable). **Reads**
  `data/processed/shelby_crashes_classified.csv`, `data/raw/state_routes.geojson`,
  and `data/raw/memphis_boundary.geojson`. Plots every in-Memphis crash (TDOT +
  City of Memphis only; Suburban-Shelby and Excluded-BadGeo are dropped) on an
  OpenStreetMap basemap, colored by jurisdiction (teal = City, red = TDOT), with
  fatal crashes drawn larger and outlined, plus the state routes, city boundary,
  title, legend, scale bar, north arrow, and a stats box computed live from the
  data. If basemap tiles can't download, it falls back to a plain white
  background. **Produces** `outputs/prototype_crash_map.png` (300 dpi) and prints
  the headline stats and the number of rows dropped for bad coordinates.
  Requires `matplotlib` and `contextily` (`py -m pip install matplotlib contextily`).
  Run: `.\.venv\Scripts\python.exe scripts\04_prototype_map.py`
- `scripts/05_download_streets.py` — downloads the **full street network** so
  every crash can be tagged with a street name and streets can be drawn on the
  later interactive map. **Source layer:** Basemaps/Common_Services_PROD
  MapServer **Layer 17 "Streets"** (the city's full centerline layer; chosen
  over PW_Support_Layers/8 "Road Centerline" because it has a ready-made `LABEL`
  name field and component fields matching our state-routes layer). Pulls
  `COUNTY_L='SHELBY'` (all of Memphis plus a margin), paginates at 2,000/request,
  saves raw pages, keeps all attributes, reprojects EPSG:2274 → EPSG:4326, and
  **produces** `data/raw/memphis_streets.geojson` (55,141 segments). Caches like
  the other download scripts (skips if the saved count matches the live count).
  Run: `.\.venv\Scripts\python.exe scripts\05_download_streets.py`
- `scripts/06_join_streets.py` — matches every in-Memphis crash to its nearest
  street and builds the first deadliest-streets ranking. **Reads**
  `data/processed/shelby_crashes_classified.csv` and `data/raw/memphis_streets.geojson`.
  Takes the in-Memphis crashes (TDOT + City of Memphis), reprojects crashes and
  streets to **EPSG:32136 (meters)**, finds each crash's nearest street via
  `sjoin_nearest`, and attaches a standardized `Street_Name`
  (`PREDIR+NAME+TYPE+SUFDIR`, uppercased, directionals kept) plus distance,
  speed, lanes, oneway, and city/county. **Produces**
  `data/processed/shelby_crashes_named.csv` (per-crash) and
  `data/processed/deadliest_streets.csv` (ranking), and prints the top-25 tables,
  a distance quality check, and a reconciliation. Does **not** overwrite
  `shelby_crashes_classified.csv`.
  Run: `.\.venv\Scripts\python.exe scripts\06_join_streets.py`
- `scripts/07_compute_novel_stats.py` — computes and prints every verified
  "novel statistic" (the numbers locked into `data/processed/novel_statistics.md`)
  straight from `shelby_crashes_named.csv` and `deadliest_streets.csv`. Reads
  only; writes no files. Re-run to re-verify/refresh the figures after the crash
  window advances.
  Run: `.\.venv\Scripts\python.exe scripts\07_compute_novel_stats.py`
- `scripts/08_md_to_docx.py` — converts a Markdown file to a formatted Word
  (.docx) document (headings, tables, bullets, bold/italic). Defaults to
  `data/processed/novel_statistics.md` → `data/processed/novel_statistics.docx`;
  optionally takes input/output paths. Requires `python-docx`.
  Run: `.\.venv\Scripts\python.exe scripts\08_md_to_docx.py`
- `scripts/09_build_interactive_map.py` — builds the **v1 interactive web map**
  (Leaflet.js) as a single self-contained HTML file that opens by
  double-clicking (no server). **Reads** `shelby_crashes_named.csv`,
  `deadliest_streets.csv`, `memphis_streets.geojson` (top-25 corridor geometry
  only, clipped to Memphis), `state_routes.geojson`, and `memphis_boundary.geojson`.
  All map data is **embedded** into the HTML as JS variables (browsers block
  `fetch()` on `file://`), so it works offline-of-a-server but needs internet for
  the Leaflet CDN + OpenStreetMap tiles. Fatal crashes are always-on emphasized
  markers; non-fatal crashes are clustered; the 25 deadliest corridors are bold
  lines weighted by crash count; state routes and the boundary are context.
  **Produces** `outputs/interactive_map/index.html` (~1.3 MB) and
  `outputs/interactive_map/deadliest_corridors.geojson`. Does **not** ship the
  96 MB full street network to the browser.
  Run: `.\.venv\Scripts\python.exe scripts\09_build_interactive_map.py`
- `scripts/10_build_stats_section.py` — computes a new **lighting statistic** and
  **appends a stats/findings dashboard** to the bottom of the existing map page
  (`outputs/interactive_map/index.html`), turning it into one map-plus-dashboard
  resource. **Reads** `shelby_crashes_named.csv` and `deadliest_streets.csv`;
  every displayed number is computed (nothing hardcoded). Adds a 5-card hero band
  (City-owned share, fatal-on-4+lanes-&-40+mph "design problem", death
  concentration, dark-unlit fatal share, and the external #1-nationally context),
  a reframe paragraph, three **Chart.js** charts (jurisdiction split, deaths by
  lane count, crashes by year), the click-to-sort top-25 deadliest-streets table,
  and a methodology/sources footer. Runs **after** script 09 and is **idempotent**
  (re-running replaces the appended section, never duplicates it); leaves the map
  intact. Also **appends** the lighting stat + a dated note to
  `data/processed/novel_statistics.docx`. Lighting headline: of 175 in-Memphis
  fatal crashes, **76.6% happened after dark** and **14.3% on a dark, unlit road**.
  Run: `.\.venv\Scripts\python.exe scripts\10_build_stats_section.py`
- `scripts/11_jurisdiction_audit.py` — **read-only audit** (diagnose, don't fix):
  confirms `state_routes.geojson` has no interstate geometry, so interstate crashes
  fall into the "City of Memphis" residual. Finds the streets layer carries an
  authoritative class field (`MTFCC`, with `S1100` = interstate), quantifies the
  23 mislabeled interstate crashes (10 fatal), snap-checks them, and prints the
  before/after City-vs-TDOT split under two fix options. Writes
  `outputs/jurisdiction_audit.md` with a recommendation. Changes **no** data files.
  Run: `.\.venv\Scripts\python.exe scripts\11_jurisdiction_audit.py`
- `scripts/12_reclassify_interstates.py` — interim fix: tags interstate-proximate
  crashes as a separate `Interstate (TDOT)` bucket (nearest road = `MTFCC` S1100
  within 30 m). Writes `*_with_interstate.csv`. **Superseded by script 14** (kept
  for history; the `_with_interstate` files can be retired).
- `scripts/14_segment_jurisdiction.py` — **major method change: segment
  inheritance.** Instead of the crash-point distance to a state-route line, it tags
  every centerline segment with an `Ownership` (`Interstate (TDOT)` / `Interstate
  ramp` / `TDOT state route` / `City of Memphis`) and each crash inherits the tag of
  the segment it sits on. **Reads** `memphis_streets.geojson`, `state_routes.geojson`,
  `shelby_crashes_named.csv`, `shelby_crashes_classified.csv`. All spatial math in
  EPSG:32136. State-route tag = a centerline segment whose length is ≥60% within a
  10 m buffer of a same-named state route, OR ≥85% within an 8 m buffer (name
  override for SR-385/US-64/etc.); interstates from `MTFCC` S1100, ramps S1630.
  **Produces** NEW files (originals untouched): `shelby_crashes_named_seg.csv`,
  `shelby_crashes_classified_seg.csv`, `deadliest_streets_seg.csv`,
  `outputs/interactive_map/ownership_segments.geojson` (slim Memphis state-route +
  interstate display layer), and `outputs/segment_method_audit.md` (Phase-1
  validation, old-vs-new split, per-street comparison, join-quality flags). Does
  **not** rebuild `index.html` or `novel_statistics.docx`.
  Run: `.\.venv\Scripts\python.exe scripts\14_segment_jurisdiction.py`
- `scripts/15_sensitivity_check.py` — **read-only** sensitivity note on the segment
  method: hand-verifies the watchlist arterials, characterizes the intersection-area
  TDOT→City moves, and computes the surface split as a RANGE (nearest-centerline vs.
  corner-crashes-credited-to-the-state-route). Appends to `outputs/segment_method_audit.md`.
  Run: `.\.venv\Scripts\python.exe scripts\15_sensitivity_check.py`
- `scripts/16_completeness_audit.py` — **read-only** completeness audit of the
  state-route tagging against an EXTERNAL list of known corridors (not the gappy
  layer alone). Re-tags segments, then per corridor reports the share of its
  layer-covered span tagged TDOT, lists **threshold under-tag** segments
  (`ov_same_name` = fraction of a City segment lying along a same-named state route),
  the crash impact, re-judges the 3 watchlist crashes, flags **layer-level gaps**
  (roads the layer lacks: Sam Cooper, Bill Morris) as a separate uncertainty band,
  and prints the corrected surface City/TDOT range. Writes
  `outputs/completeness_audit.md`. Changes **no** classification/map/docx/data files.
  Run: `.\.venv\Scripts\python.exe scripts\16_completeness_audit.py`
- `scripts/17_classifier.py` — the **canonical, reusable classifier** that
  consolidates the settled methodology (scripts 14–16). **Part A** tags every
  centerline segment by a documented, ordered **rulebook** (1 interstate `S1100`,
  2 ramp `S1630`, 3 limited-access override = a name list of TDOT limited-access
  roads absent from the layer, seeded with Sam Cooper, 4 state-route geometric
  overlap, 5 force-state-route override = the completeness rule `ov_same_name ≥
  0.20` + an explicit list seeded empty, 6 City residual), recording which rule
  fired, and saves `data/processed/road_ownership_rulebook.geojson`. **Part B** is
  a reusable function: any crash set inherits its nearest rulebook segment's
  Ownership, with provenance (`Seg_OBJECTID`, `DistToSeg_m`, `Classification_Basis`)
  and flags (`is_limited_access`, `is_corner_case`, `is_override`); runs unchanged
  on new crash data. **Part C** prints the final locked numbers. **Produces**
  `data/processed/shelby_crashes_final.csv`,
  `outputs/interactive_map/ownership_segments_final.geojson` (slim Memphis
  state-route + limited-access tint layer), and `outputs/final_numbers.md`. Two
  override lists are top-of-file config. Does **not** rebuild `index.html` or any
  docx. **Headline:** surface **City 75–80% / TDOT 20–25%** (≈79.7% / 20.3% point
  estimate), with **limited-access (Interstate + ramps + Sam Cooper) = 35 crashes
  (14 fatal)** reported separately.
  Run: `.\.venv\Scripts\python.exe scripts\17_classifier.py`
- `scripts/18_build_public_map.py` — **Pass 2: rebuilds the public map + findings
  dashboard** as one clean, self-contained `outputs/interactive_map/index.html`
  off the Pass-1 classifier output (**supersedes the scripts 09/10 page**).
  **Reads** `shelby_crashes_final.csv`, `ownership_segments_final.geojson` (slim
  tint layer only — never the 55k network), and `memphis_boundary.geojson`. The
  map defaults to individual crash **dots in three categories** (City / TDOT state
  route / Limited-access), fatal emphasized; the old thick weighted corridor lines
  and fat numbered cluster bubbles are **removed**. Non-fatal dots cluster lightly
  (minimal gray counts) and split on zoom-in; fatal dots are always individual.
  Controls: per-category toggles, a Fatal-only filter, and a default-OFF
  **Hotspots** intensity overlay. Road segments are subtly tinted by ownership
  (crimson = state route, charcoal = limited-access; City untinted). Popups are
  user-facing (date, severity, location, road owner) — no provenance. The
  dashboard shows hero cards (point estimate + range), the three-category
  jurisdiction breakdown with **Limited-access as its own line**, three Chart.js
  charts (jurisdiction, deaths-by-lanes, crashes-by-year), and the 25-deadliest
  corridor table. Every number is computed from the data (reconciles to 1,294 /
  175). Also **appends** a dated Pass-2 section to `novel_statistics.docx` (final
  range, limited-access line, methodology decision-tree, provenance note);
  `novel_statistics.md` is left untouched. **Headline:** surface **City 75.1–79.7%
  / TDOT 20.3–24.9%** (all), **City 68.9–72.0% / TDOT 28.0–31.1%** (fatal); plus
  limited-access **35 crashes (14 fatal)**, separate.
  Run: `.\.venv\Scripts\python.exe scripts\18_build_public_map.py`
- `scripts/19_acquire_ped_signals.py` — **Phase 3a / Phase 1 acquisition.**
  Downloads the TDOT "ADA Asset Data" **Pedestrian Signal** layer (and, once, the
  **Crosswalks** layer to confirm the interstate-only pattern) for Shelby County
  from the ArcGIS Feature Service resolved from geodata.tn.gov Hub item
  `69511fa73a584e2bb37acfa85b177fa5` (layer 1 = Pedestrian Signal, 2 = Crosswalks).
  **Produces** `data/raw/ped_signals.geojson` (**5,694 points = 2,979 'Pedestrian
  Signal' heads + 2,715 'Push Button'**, EPSG:4326, route-referenced via
  `ROUTE_NAME`) and `data/raw/crosswalks_shelby.geojson` (**247 polygons, all on
  interstates I-40/240/55 + SR-385** — zero surface arterials, so crosswalks are
  set aside). Prints the feature-type/route breakdown and a nearest-neighbour
  distribution.
  Run: `.\.venv\Scripts\python.exe scripts\19_acquire_ped_signals.py`
- `scripts/20_dedup_crossings.py` — **Phase 3a / Phase 1 dedup + coverage scope.**
  Single-linkage clusters the raw heads + push buttons into **one signalized
  pedestrian crossing per intersection** at the confirmed **30 m** radius, and
  sizes the signal-covered corridor scope (a street carrying **≥4** inventoried
  signals is "signal-covered," regardless of City/TDOT ownership). **Reads**
  `ped_signals.geojson` + `road_ownership_rulebook.geojson`. **Produces**
  `data/processed/signalized_crossings_dedup.geojson` (**1,008 crossings**) and
  `data/processed/signal_covered_corridors.csv` (**379 covered streets**, 97.4% of
  signals). **Key coverage finding:** the inventory is **not** state-routes-only —
  ~38.5% of signals sit on major *city* arterials (Winchester, Riverdale, Stage,
  Germantown, Houston Levee…), so coverage is defined by corridor, not ownership;
  intersections off every covered corridor are `no_signal_coverage` (absence of
  data ≠ "no signal"). Thresholds (signed off 2026-06-16): dedup 30 m; crash→node
  30 m; signal→node 30 m; intersections = junctions of 2+ named through-roads on
  covered corridors. Does **not** touch crashes/map/docx (Phase 2).
  Run: `.\.venv\Scripts\python.exe scripts\20_dedup_crossings.py`
- `scripts/21_signal_intersections.py` — **Phase 3a / Phase 2.** Builds intersection
  nodes, signalized flags, and per-crash signal attributes (descriptive, scoped to
  signal-covered corridors; no causal claims). **(1)** Covered corridors are decided by
  **route grouping** (signals grouped by TDOT `ROUTE_NUMBER`; each covered route → its
  dominant arterial + any ≥25% secondary), giving **53 covered corridors** — not
  corner-noisy nearest-segment snapping. **(2)** Nodes = junctions of 2+ distinct named
  through-roads (MTFCC S1200/S1400; driveways/alleys/ramps/dead-ends excluded), built
  citywide and tagged on/off covered corridor (**2,268** covered nodes, **304**
  signalized). **(3)** A node is signalized if a deduped crossing is within 30 m.
  **(4)** Crash `at_intersection` comes from the NonMotorist field (primary), corroborated
  by a 30 m node snap. **Writes** `data/processed/shelby_crashes_signals.csv` (adds
  `at_intersection`, `intersection_node_id`, `intersection_signalized`
  [`yes`/`no`/`no_signal_coverage`], `nearest_ped_signal_m`, `is_ambiguous_intersection`;
  jurisdiction columns untouched) and `data/processed/intersection_nodes_covered.geojson`.
  **Scoped finding:** of 599 field-intersection crashes, **177 within coverage** split
  **signalized 89 (50.3%) / unsignalized 88 (49.7%)** (fatal 9 vs 4); **422** are
  `no_signal_coverage` (off-corridor — NOT counted as unsignalized; absence of signal
  data ≠ "no signal"). Appends a dated Phase-3a section to `novel_statistics.docx`
  (idempotent). The map's crossings layer is added by re-running script 18. Reconciles to
  1,294 / 175.
  Run: `.\.venv\Scripts\python.exe scripts\21_signal_intersections.py`
- `scripts/22_osm_crossings_eval.py` — **read-only EVALUATION** of OSM pedestrian
  crossings (does not modify the map or crash data). Acquires OSM crossings for the
  Shelby **bbox** via Overpass (coordinate-bounded — avoids the `name="Memphis"`
  pollution from Memphis MO/MI/TX), caches to `data/raw/osm_crossings.geojson`, then
  splits MARKED (`crossing:markings`≠no/blank) vs SIGNALIZED, dedups (node+way @ 8 m;
  signalized one-per-intersection @ 30 m), **cross-references** the OSM
  pedestrian-signalized subset against the TDOT deduped signals (script 20) at 30 m &
  50 m both directions, and assesses **marked-crossing completeness** along the deadly
  corridors (in-Memphis, single-carriageway reference length + longest-gap). Writes
  `outputs/osm_crossings_eval.md`. **Findings:** marked ≈1,219 in-Memphis (deduped,
  matches the ~1,256 anchor); OSM↔TDOT signal agreement ~44–51% (TDOT→OSM) / ~55–56%
  (OSM→TDOT) — TDOT's 1,008 is the more complete signal inventory, OSM's 440 is partial.
  Union Ave is dense+continuous (usable now); Poplar/Winchester/Lamar/Summer are
  well-mapped in the core but have ~3–6 mi outer **coverage cliffs** (ground-truth
  before a corridor-wide crossing-distance stat).
  Run: `.\.venv\Scripts\python.exe scripts\22_osm_crossings_eval.py`
- `scripts/23_union_poc.py` — **Phase 3b: Union Ave distance-to-crossing PROOF OF
  CONCEPT (Union only).** Re-pulls Union-area OSM crossings **with line geometry**
  (`out geom`) to `data/raw/osm_union_crossings.geojson` (the citywide file stored
  points), builds the in-Memphis Union centerline (4.61 mi, single carriageway), and
  assembles a **combined safe-crossing inventory** = OSM marked crosswalk OR TDOT
  pedestrian signal within 30 m, deduped so a signalized intersection with a marked
  crosswalk = one crossing (**37 = 18 signalized + 19 marked-only**). Measures each
  **crossing-relevant** crash's (On Roadway / In Crosswalk; 36 of 41 Union crashes)
  **along-corridor** distance (linear referencing) to the nearest safe crossing, and
  the corridor's longest no-crossing gap vs the FHWA ~300 ft best-practice spacing.
  **Findings:** mean 126 ft / median 3 ft (many struck AT a crossing), **19% (7/36)
  struck >250 ft** from any safe crossing; longest gap **2,924 ft (~9.7× the 300 ft
  guidance)**. Writes a focused `outputs/interactive_map/union_poc.html` (crosswalk
  lines by type, TDOT signal points per-corner, crashes shaded by distance, longest
  gap highlighted) — the citywide map is **untouched** — plus
  `outputs/union_poc_report.md`, and appends a dated Union POC section to
  `novel_statistics.docx`. Signalized = TDOT only (more complete than OSM signals).
  Run: `.\.venv\Scripts\python.exe scripts\23_union_poc.py`
- `scripts/24_build_search.py` — **map SEARCH feature (additive).** Builds a
  precomputed `data/processed/search_index.json` and injects a type-ahead
  corridor / intersection / address search into `outputs/interactive_map/index.html`
  (embedded as a JS variable so it works on `file://`; idempotent, marker-delimited
  block — re-running replaces only the injected block and never touches the existing
  map/layers/toggles/charts). **Corridors:** every named street with ≥1 crash, counts
  computed with the SAME `Street_Name` grouping as the deadliest-corridor card (a
  printed reconciliation confirms all 25 deadliest match exactly and totals sum to
  1,294) — total/fatal, ownership split, deadliest rank, # signalized intersections
  (covered corridors only, else "not yet analyzed"), simplified centerline for
  highlight, and safe-crossing stats **only for Union** (from `union_safe_summary.json`).
  **Intersections:** the 436 covered nodes with ≥1 crash or that are signalized —
  crashes/deaths, signalized yes/no, nearest safe crossing (Union only). On result it
  pans/zooms, highlights (corridor line / intersection marker / address pin) and opens
  a stat card that labels any "not yet analyzed" field. **Address** queries dispatch to
  the free no-key **US Census** onelineaddress geocoder client-side (graceful failure;
  may be blocked from `file://` by browser CORS — works when served over http), then
  show nearest corridor + nearest intersection + crashes within 50 m. Index: **529
  corridors, 436 intersections.** Run AFTER script 18 (re-running 18 drops the
  injection; just re-run this).
  Run: `.\.venv\Scripts\python.exe scripts\24_build_search.py`

## How to run (Windows)

From the project folder, in PowerShell:

```powershell
# one-time setup
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# run the pipeline in order
.\.venv\Scripts\python.exe scripts\01_download_crashes.py
.\.venv\Scripts\python.exe scripts\02_download_roads.py
.\.venv\Scripts\python.exe scripts\03_spatial_join.py

# optional: draw the prototype sanity map (needs matplotlib + contextily)
.\.venv\Scripts\python.exe scripts\04_prototype_map.py

# download the full street network (for naming crashes / interactive map)
.\.venv\Scripts\python.exe scripts\05_download_streets.py

# match crashes to nearest street + build the deadliest-streets ranking
.\.venv\Scripts\python.exe scripts\06_join_streets.py

# verify the headline statistics (prints to terminal; writes no files)
.\.venv\Scripts\python.exe scripts\07_compute_novel_stats.py

# (optional) regenerate the Word stats doc from a markdown file
.\.venv\Scripts\python.exe scripts\08_md_to_docx.py

# build the v1 interactive web map (outputs/interactive_map/index.html)
.\.venv\Scripts\python.exe scripts\09_build_interactive_map.py

# append the stats/findings dashboard below the map (run after script 09)
.\.venv\Scripts\python.exe scripts\10_build_stats_section.py
```

Both download scripts cache their data: if the saved record count matches the
live API count, they skip the download and just reprocess.

## Methodology (spatial join)

- **Geographic definition of "Memphis":** the City of Memphis boundary
  (Public Works layer 15). Because the state-route layer only covers the city,
  crashes are filtered to inside this boundary **before** classification —
  otherwise suburban Shelby crashes (with no nearby city road) would be
  miscounted as "City." Crashes outside the boundary are labeled
  `Suburban-Shelby` and excluded from the city-vs-TDOT percentages.
- **Projected CRS for distance math:** **EPSG:32136 (NAD83 / Tennessee,
  meters)**. This is purpose-built for Tennessee with negligible distance
  distortion here. We deliberately did **not** use Web Mercator (EPSG:3857),
  which stretches distances by ~22% at Memphis's latitude and would quietly
  corrupt a tight threshold.
- **Classification rule:** for each in-Memphis crash, the distance to the
  nearest state-route segment is measured. If that distance is **≤ 30 m**
  (`DISTANCE_THRESHOLD_M`, a named constant at the top of script 03), the crash
  is classified `TDOT`; otherwise `City of Memphis`. A sensitivity table at
  10/20/30/50/100 m is printed for transparency; the official threshold is 30 m.
- **Bad/missing locations:** crashes with a blank, `(0,0)`, or out-of-Shelby
  lat/long are kept in the output (labeled `Excluded-BadGeo`) but excluded from
  the join and percentages, so row counts still reconcile to the input (1,390).
  In the current data, 0 crashes were excluded.
- **Ties:** if a crash is exactly equidistant from two segments, the first match
  is kept deterministically.
- **`DistToStateRoute_m`** is populated for all in-Memphis crashes (TDOT and
  City) for the sanity check; it is left blank for `Suburban-Shelby` (the city
  road layer doesn't apply there) and `Excluded-BadGeo` (no coordinate).

## Headline findings (as of 2026-05-29)

Of the 1,390 Shelby County pedestrian/non-motorist crashes since 2023-01-01,
**93.1% (1,294) fall inside the City of Memphis**; the rest are suburban.
Among the **1,294 in-Memphis crashes**:

- **TDOT state routes account for 25.3% of crashes (328); City of Memphis roads
  74.7% (966).**
- **For fatal crashes the TDOT share is higher: 29.7% (52 of 175) on TDOT state
  routes vs 70.3% (123) on City roads.**
- People-affected weighting (`VictimsInCrash`) gives a similar split:
  24.9% TDOT, 75.1% City.
- Sanity check: TDOT-classified crashes sit ~5 m from a state route on average;
  City crashes ~1,066 m away — a clean separation that supports the 30 m cutoff.
  The TDOT share moves only gradually across thresholds (21.6% at 10 m → 32.7%
  at 100 m), so the result is not fragile.
- **Deadliest streets** (from `deadliest_streets.csv`): the worst corridors are a
  mix of City and TDOT — Poplar Ave (44 crashes, 8 fatal), Union Ave (36, 8),
  Lamar Ave (30, 6), Winchester Rd (28, 5). The full verified set — road-character
  / design-problem stats, concentration of deaths, where victims were killed,
  year-by-year — lives in `data/processed/novel_statistics.docx`.

## Project one-pager (standalone flyer)

A single-page recruiting/partnership flyer in `Project one pager/`. It is a
**standalone design deliverable** — it does **not** use the crash-data pipeline
or any data files.

- `Project one pager/index.html` — a print-optimized US Letter (portrait) flyer:
  header, "The Dilemma," the three tracks (Data & Research, Better Media
  Coverage, Pedestrian Testimonials) with emphasized "Where we need help" asks,
  contact, and an organizations footer. Styled to the **Street Fair Memphis
  brand** (white background, dark teal-navy pinstripe hero, green accent, amber
  call-outs; fonts **Manrope** + **Poppins**). Fully **self-contained** — the
  fonts are embedded as base64 so it works offline and on `file://` with no CDN.
  **Open** by double-clicking; **print/PDF** via the browser's Print dialog (set
  to fit one page).
- `Project one pager/build_onepager.py` — regenerates `index.html`: embeds the
  two web fonts (downloaded once, cached in `.fonts_cache.css`), optimizes the
  hero photo + crash-map thumbnail into `images/`, and writes the styled markup.
  Style is a clean white page with dark teal-navy cards and a single green accent
  (no amber), a large full-width hero photo (headline overlaid), and a big panel
  of the project's own crash map.
  **Re-run after changing logos, the hero photo, or copy** —
  `.\.venv\Scripts\python.exe "Project one pager\build_onepager.py"`.
- `Project one pager/images/` — generated, optimized images used by the flyer
  (`pedestrian.jpg` hero photo, `map_thumb.jpg` crash-map crop). The hero source
  photo is read from `logos/pedestrian_image.*`; the map is cropped from
  `outputs/prototype_crash_map.png`. (Ensure you have rights to any photo before
  publishing.)
- `Project one pager/logos/` — transparent-PNG logos, named exactly (lowercase):
  `morehead_cain.png`, `innovate_memphis.png`, `street_fair.png`,
  `hyde_foundation.png` (all four currently present). If a file is missing, the
  flyer falls back to clean styled text automatically.

## Next steps

- **Phase 5 — the deliverable (in progress):** the **v1 interactive map** is
  built — `outputs/interactive_map/index.html` (open by double-click), produced
  by `scripts/09_build_interactive_map.py`. It shows every in-Memphis crash
  (fatal emphasized, non-fatal clustered) by road ownership, the top-25 deadliest
  corridors, and the state-route/boundary context.
- Remaining: a public deployment of the interactive map and the short written
  brief for journalists (drawing on `data/processed/novel_statistics.docx`).
