# Union Ave — distance-to-crossing proof of concept

*Union only. Distances along the centerline (EPSG:32136). Safe crossing = OSM marked crosswalk OR TDOT pedestrian signal within 30 m, deduped (co-located = one).*

## 1. Corridor
- In-Memphis Union Ave reference centerline: **4.61 mi** (7418 m), single carriageway.

*Union-crossing filter: dropped 46 parallel/side-street marked LINES, 1 off-Union marked points, and 2 side-street-only TDOT signals (kept only crossings that cross Union itself).*

## 2. Combined safe-crossing inventory (24 crossings)

- **Signalized (TDOT): 17** | **Marked-only (OSM): 7**  (after the Union-crossing filter: 29 Union-crossing marked locations + 17 Union signals, deduped; raw marked features near Union were 151).
- Spacing between consecutive safe crossings: median **804 ft (245 m)**, mean 1041 ft (317 m), max 2921 ft (890 m).

## 3. Union crashes (within 30 m of centerline)

- Total: **41** (8 fatal)  *(deadliest-list anchor ≈ 36/8; the 30 m buffer catches a few more than the nearest-street assignment)*.
- **Crossing-relevant (On Roadway / In Crosswalk): 36** (7 fatal) — the headline set.
- Non-crossing (Outside Traffic / Not on Roadway / Unknown): 5 (1 fatal) — reported, excluded from the distance stat.

## 4. Distance from a crossing-relevant crash to the nearest safe crossing (along-corridor)

- mean **152 ft (46 m)**, median **4 ft (1 m)**, max 864 ft (263 m).
- struck **> 100 ft** from the nearest safe crossing: **14/36 (39%)**; **> 250 ft**: **8/36 (22%)**.
- **Bimodal split:** **22 struck AT/near a Union crossing** (≤100 ft), **8 struck in a gap** (>250 ft), 6 in between — of 36 crossing-relevant.
- fatal crossing-relevant crashes' distances: 0 ft (0 m), 3 ft (1 m), 3 ft (1 m), 65 ft (20 m), 244 ft (74 m), 246 ft (75 m), 864 ft (263 m).

## 5. Longest gap vs FHWA best-practice spacing

- Longest stretch of Union with **no safe crossing: 2921 ft (890 m)** (from 3.25 to 3.80 mi along the corridor).
- Median safe-crossing spacing **804 ft (245 m)** vs the FHWA marked-crossing best-practice guidance of ~300 ft (91 m). The longest gap is **9.7×** the ~300 ft figure. *(FHWA ~300 ft is best-practice spacing guidance, not a legal standard.)*

## 6. Visualization
- Focused Union map written to `outputs\interactive_map\union_poc.html` (crosswalk lines by type, TDOT signal points per-corner, crashes shaded by distance, longest gap highlighted). The citywide map is untouched.

## Method judgment calls
- Distance is along-corridor (linear referencing on the single Union reference line), not straight-line — it reflects walking distance along the road.
- 'In Crosswalk' crashes (struck AT a marked crossing, distance ≈ 0) are kept in the crossing-relevant set; they pull the mean down but honestly show people are struck even at crossings.
- Signalized crossings are TDOT-only (more complete than OSM signals); marked crosswalks are OSM, which Phase 3a found dense and continuous on Union specifically.
- OSM was re-pulled with full line geometry for Union only (the citywide file stored points).
