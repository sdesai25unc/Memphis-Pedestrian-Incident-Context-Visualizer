# OSM pedestrian crossings — evaluation & cross-reference

*Evaluation only — no map or crash-data changes. Acquired from OSM via Overpass (Shelby bbox (34.99, -90.31, 35.42, -89.61)); distances in EPSG:32136.*

## 1. Raw counts (Shelby-wide | in-Memphis)

- Total OSM crossing/traffic-signal elements fetched: **8229** (6413 in Memphis).
- **MARKED** (crossing:markings ≠ no/blank): **2932** | 2288  *(≈1,256 expected)*
- **SIGNALIZED, full** (crossing=traffic_signals / crossing:signals=yes / highway=traffic_signals): **2225** | 1776  *(≈755 expected)*
  - pedestrian-specific subset (crossing=traffic_signals / crossing:signals=yes): **1351** | 1110
  - bare highway=traffic_signals only (vehicular signal nodes, not ped-tagged): 874 | 666
- markings value mix: {'zebra': 1100, 'lines': 868, 'yes': 838, 'ladder': 106, 'ladder:skewed': 20}

*Note: the MARKED deduped-in-Memphis count (§2) lands near the ~1,256 anchor, validating the marked pipeline. SIGNALIZED runs well above the ~755 anchor — driven by the broad highway=traffic_signals tag (vehicular signal nodes, not pedestrian-specific) and by growth in OSM crossing mapping since the earlier snapshot. The pedestrian-specific deduped count is the clean signalized figure used for the cross-reference.*

## 2. Deduped (raw → deduped)

- MARKED, node+way merged @ 8 m: 2932 → **1595** (1219 in Memphis).
- SIGNALIZED ped, one-per-intersection @ 30 m: 1351 → **440** (355 in Memphis).
- SIGNALIZED full, @ 30 m: 2225 → **976**.

## 3. Cross-reference — OSM ped-signalized (440) vs TDOT deduped signals (1008), Shelby-wide

| match radius | TDOT with an OSM match | OSM with a TDOT match |
|---|---|---|
| 30 m | 439/1008 (43.6%) | 241/440 (54.8%) |
| 50 m | 512/1008 (50.8%) | 248/440 (56.4%) |

- **Disagreement:** 496 TDOT signals have NO OSM ped-signal within 50 m (TDOT-only); 192 OSM ped-signals have NO TDOT signal within 50 m (OSM-only).
- *Interpretation:* TDOT inventories pedestrian signal heads/buttons on its route system; OSM `crossing=traffic_signals` is mapper-contributed and may tag the intersection node or omit legs. Mismatch ≠ error in either source — it reflects different definitions and OSM coverage gaps.

## 4. Completeness — marked-crossing coverage

- Core vs suburb: 1219 marked crossings inside Memphis vs 376 in the Shelby suburbs (outside the city). Memphis holds 76.4% of marked crossings.

**Marked crossings along the deadly corridors — scoped to the in-Memphis stretch** (where the crashes are). Length = the in-Memphis single-carriageway reference (longest merged run); count = deduped in-Memphis marked crossings within 25 m; max gap = longest in-Memphis stretch with NO marked crossing.

| corridor | in-Memphis length (mi) | marked crossings | per mile | longest gap (mi) |
|---|---|---|---|---|
| Poplar Ave | 10.6 | 71 | 6.7 | 5.87 |
| Winchester Rd | 12.2 | 47 | 3.9 | 5.72 |
| Lamar Ave | 8.3 | 50 | 6.0 | 3.41 |
| Union Ave | 4.6 | 76 | 16.5 | 0.93 |
| Jackson Ave | 6.2 | 39 | 6.3 | 1.59 |
| Summer Ave | 8.9 | 22 | 2.5 | 4.77 |

*A well-mapped urban arterial has a marked crossing roughly every signalized block (~4+/mi, gaps under ~0.5 mi). Low per-mile or a long gap flags where OSM coverage thins.*

## 5. Usability call

- Core marked coverage is dense (1219 crossings in Memphis, 76.4% of the metro total) — the OSM MARKED layer is usable in the urban core; the suburban fringe (376) is thinner.
- **Trustworthy enough for a distance-to-marked-crossing stat now** (≥~4/mi, no gap >~0.6 mi): **Union Ave**.
- **Ground-truth first** (lower density or a long gap): **Poplar Ave, Winchester Rd, Lamar Ave, Jackson Ave, Summer Ave**.
- **Coverage cliffs** (dense in the core, then a long unmapped stretch): Poplar Ave (~5.9 mi with no OSM marked crossing); Winchester Rd (~5.7 mi with no OSM marked crossing); Lamar Ave (~3.4 mi with no OSM marked crossing); Summer Ave (~4.8 mi with no OSM marked crossing). These corridors are usable for CORE-area crashes but not corridor-wide until the outer stretches are mapped/ground-truthed.
- **Recommended (not performed):** an aerial/satellite spot-check on **Poplar and Winchester** (highest-traffic corridors) — sample ~10 intersections each and confirm OSM marked crossings match painted crosswalks on imagery before publishing any crossing-distance stat.
- For SIGNALIZED crossings, TDOT (1,008 deduped) is the more complete inventory; OSM's pedestrian-signal layer (440) is partial, so prefer TDOT for signal-based stats and treat OSM signals as corroboration only.
