# Segment-inheritance jurisdiction method — audit

*Read/compute only · all spatial math in EPSG:32136 · new files; originals untouched.*
  candidate centerline segments near state routes: 3692 of 55141

## Phase 1 — segment ownership tagging

| Ownership | segments | miles |
|---|---|---|
| Interstate (TDOT) | 577 | 136.4 |
| Interstate ramp | 997 | 132.1 |
| TDOT state route | 1695 | 167.9 |
| City of Memphis | 51872 | 5151.3 |

- Raw `state_routes.geojson` mileage: **168.4 mi**; tagged "TDOT state route" centerline mileage: **167.9 mi** (centerline can differ from the single state-route line where a divided road has two carriageways or alignments differ).

- Overlap-fraction (ov10) distribution among candidates:
```
  [0.0, 0.1): 1264
  [0.1, 0.3): 572
  [0.3, 0.6): 80
  [0.6, 0.85): 32
  [0.85, 1.01): 1744
```

- Spot checks (Ownership mix by name key):
    POPLAR     : {'City of Memphis': 263, 'TDOT state route': 108, 'Interstate ramp': 22}
    LAMAR      : {'TDOT state route': 162, 'Interstate ramp': 51, 'City of Memphis': 9}
    SUMMER     : {'TDOT state route': 83, 'City of Memphis': 50}
    UNION      : {'TDOT state route': 77, 'City of Memphis': 26, 'Interstate ramp': 23}
    WINCHESTER : {'City of Memphis': 229, 'Interstate ramp': 34, 'TDOT state route': 1}
    GETWELL    : {'TDOT state route': 64, 'City of Memphis': 39, 'Interstate ramp': 29}
    AIRWAYS    : {'City of Memphis': 65, 'TDOT state route': 19, 'Interstate ramp': 7}
    INTERSTATE : {'Interstate (TDOT)': 577}

- Ambiguous segments to review (30–60% overlap, or >=60% with name mismatch & <85% tight overlap): **143**
```
  N MCLEAN BLVD              ov10=1.00 name_match=False MTFCC=S1400
  E RAINES RD                ov10=1.00 name_match=False MTFCC=S1200
  INTERSTATE 55 W            ov10=1.00 name_match=False MTFCC=S1100
  MADISON AVE TO S DANNY THO ov10=1.00 name_match=False MTFCC=S1630
  EMERGENCY CROSSOVER        ov10=1.00 name_match=False MTFCC=S1740
  EMERGENCY CROSSOVER        ov10=1.00 name_match=False MTFCC=S1740
  E HOLMES RD                ov10=1.00 name_match=False MTFCC=S1400
  RIDGEWAY RD                ov10=1.00 name_match=False MTFCC=S1200
  WEST DR                    ov10=1.00 name_match=False MTFCC=S1400
  EMERGENCY CROSSOVER        ov10=1.00 name_match=False MTFCC=S1740
  E RAINES RD                ov10=1.00 name_match=False MTFCC=S1200
  WINCHESTER RD TO 385 W     ov10=1.00 name_match=False MTFCC=S1630
  CONCORDE RD                ov10=0.99 name_match=False MTFCC=S1400
  S CAMILLA ST               ov10=0.97 name_match=False MTFCC=S1400
  GAYOSO AVE                 ov10=0.97 name_match=False MTFCC=S1400
  MADISON AVE TO S DANNY THO ov10=0.97 name_match=False MTFCC=S1630
  E H CRUMP BLVD TO RIVERSID ov10=0.96 name_match=False MTFCC=S1630
  WINCHESTER RD              ov10=0.96 name_match=False MTFCC=S1200
  MADISON AVE TO S DANNY THO ov10=0.95 name_match=False MTFCC=S1630
  MONROE AVE                 ov10=0.94 name_match=False MTFCC=S1400
```

Wrote shelby_crashes_named_seg.csv, shelby_crashes_classified_seg.csv, deadliest_streets_seg.csv (529 streets).

## Phase 3 — old (distance) vs new (segment) split

**ALL crashes**

| method | City | TDOT | Interstate | Interstate ramp |
|---|---|---|---|---|
| OLD distance (n=1294) | 966 (74.7%) | 328 (25.3%) | (in City) | (in City) |
| NEW segment, surface (n=1263) | 1008 (79.8%) | 255 (20.2%) | 23 sep. | 8 sep. |

**FATAL crashes**

| method | City | TDOT | Interstate | Interstate ramp |
|---|---|---|---|---|
| OLD distance (n=175) | 123 (70.3%) | 52 (29.7%) | (in City) | (in City) |
| NEW segment, surface (n=163) | 119 (73.0%) | 44 (27.0%) | 10 sep. | 2 sep. |

**Crashes that changed label: 400 of 1294** (reconciles: sum still 1294; fatal 175).

```
  TDOT               -> TDOT state route   : 207
  TDOT               -> City of Memphis    : 114
  City of Memphis    -> TDOT state route   : 48
  City of Memphis    -> Interstate (TDOT)  : 20
  City of Memphis    -> Interstate ramp    : 4
  TDOT               -> Interstate ramp    : 4
  TDOT               -> Interstate (TDOT)  : 3
```

**Wide-arterial old-vs-new** (crash counts by jurisdiction):

| street | OLD City/TDOT | NEW City/TDOT/Int/Ramp |
|---|---|---|
| POPLAR | 26/18 | 27/17/0/0 |
| LAMAR | 3/27 | 0/30/0/0 |
| SUMMER | 5/13 | 1/17/0/0 |
| UNION | 6/30 | 2/34/0/0 |
| JACKSON | 3/17 | 1/19/0/0 |
| PARK | 27/3 | 30/0/0/0 |
| GETWELL | 14/4 | 10/8/0/0 |
| WINCHESTER | 29/0 | 28/0/0/1 |
| AIRWAYS | 7/8 | 11/4/0/0 |

**Join-quality watchlist** — 3 of the 114 TDOT→City crashes sit on a segment that overlaps a state route ≥30% yet was tagged City (possible under-tagged carriageway / name gap — eyeball these; the rest are genuine city cross-streets near intersections):
```
  300968447 E RAINES RD          ov10=1.00 oldDistToSR=3.5m  (35.03850,-89.91717)
  300981287 N BELLEVUE BLVD      ov10=0.90 oldDistToSR=10.5m  (35.15429,-90.01961)
  300953626 JACKSON AVE          ov10=0.39 oldDistToSR=2.8m  (35.17769,-89.93764)
```

**Reframe check:** new surface split City 79.8% vs TDOT 20.2% — City still owns the majority of surface crashes; fatal surface City 73.0% vs TDOT 27.0%.

## Phase 4 — display layer

Wrote `ownership_segments.geojson`: 2968 Memphis state-route/interstate segments (0.89 MB, simplified, EPSG:4326).

## Sensitivity & watchlist verification (read-only — nothing reclassified)

*Appended by `scripts/15_sensitivity_check.py`. The per-crash labels and the map's three categories are unchanged; these are reporting-only numbers.*

### 1. Watchlist arterials — should each be a state route?

| crash | matched (city) road | nearest state route | route # | dist | verdict |
|---|---|---|---|---|---|
| 300968447 | E RAINES RD | LAMAR | 4 | 3.5 m | City correct (nearest state route is a DIFFERENT road / cross-street) |
| 300953626 | JACKSON AVE | JACKSON | 14 | 2.8 m | SHOULD be state route (same road, under-tagged) |
| 300981287 | N BELLEVUE BLVD | N PARKWAY | 1 | 10.5 m | City correct (nearest state route is a DIFFERENT road / cross-street) |

*Verdict logic: if the crash's own (matched) road appears in the state-route layer at <12 m, it is an under-tagged state route; otherwise the nearby state route is a different road the city street merely meets/parallels, and City is correct.*

### 2. The intersection-area TDOT→City moves (city cross-street crashes)

- TDOT→City moves total: **114**; on a city cross-street (not a state-route-named road): **95**; fatal among them: **10**.
- NonMotoristLocation: **61 Intersection-***, **34 Not-Intersection-***. Breakdown:
```
  Not Intersection-On Roadway Not In Crosswalk: 24
  Intersection-In Crosswalk: 24
  Intersection-On Roadway not in Crosswalk: 16
  Intersection-On Roadway Crosswalk availability Unknown: 9
  Intersection-Unknown: 6
  Intersection-On Roadway Crosswalk Not Available: 4
  Not Intersection-Outside Traffic: 4
  Not Intersection-Bike Path: 2
  Intersection-Not on Roadway: 2
  Not Intersection-On Roadway Crosswalk not Available: 2
  Not Intersection-Other Not On Roadway: 1
  Not Intersection-On Roadway Crosswalk Availability Unknown: 1
```
- Of the 61 intersection crashes, **58 are at a junction WITH a state route** (a state route within 10 m — the 'crossing a state route at the corner' cases; 5 fatal). Sensitivity: ≤5 m → 51, ≤15 m → 59.

### 3. Surface City/TDOT split — a RANGE (sensitivity to corner crashes)

Two bounds on the same 1263 surface crashes (163 fatal). Lower bound = current nearest-centerline (corner crash credited to the city cross-street, City-favorable). Upper bound = the 58 state-route-junction crashes credited to the STATE ROUTE instead (TDOT-favorable). The truth sits between.

| | City | TDOT |
|---|---|---|
| ALL — nearest-centerline (current) | 1008 (79.8%) | 255 (20.2%) |
| ALL — corner→state route (upper) | 950 (75.2%) | 313 (24.8%) |
| FATAL — nearest-centerline (current) | 119 (73.0%) | 44 (27.0%) |
| FATAL — corner→state route (upper) | 114 (69.9%) | 49 (30.1%) |

**Range to report:** surface TDOT share is **20.2%–24.8%** (all crashes) and **27.0%–30.1%** (fatal); City correspondingly **75.2%–79.8%** / **69.9%–73.0%**. City owns the majority of surface crashes under **both** bounds. (Interstate stays a separate 23 / 10 fatal; the map and per-crash labels are unchanged.)
