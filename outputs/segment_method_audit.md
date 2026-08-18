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

Wrote shelby_crashes_named_seg.csv, shelby_crashes_classified_seg.csv, deadliest_streets_seg.csv (552 streets).

## Phase 3 — old (distance) vs new (segment) split

**ALL crashes**

| method | City | TDOT | Interstate | Interstate ramp |
|---|---|---|---|---|
| OLD distance (n=1373) | 1022 (74.4%) | 351 (25.6%) | (in City) | (in City) |
| NEW segment, surface (n=1340) | 1066 (79.6%) | 274 (20.4%) | 24 sep. | 9 sep. |

**FATAL crashes**

| method | City | TDOT | Interstate | Interstate ramp |
|---|---|---|---|---|
| OLD distance (n=182) | 126 (69.2%) | 56 (30.8%) | (in City) | (in City) |
| NEW segment, surface (n=170) | 122 (71.8%) | 48 (28.2%) | 10 sep. | 2 sep. |

**Crashes that changed label: 429 of 1373** (reconciles: sum still 1373; fatal 182).

```
  TDOT               -> TDOT state route   : 222
  TDOT               -> City of Memphis    : 122
  City of Memphis    -> TDOT state route   : 52
  City of Memphis    -> Interstate (TDOT)  : 21
  City of Memphis    -> Interstate ramp    : 5
  TDOT               -> Interstate ramp    : 4
  TDOT               -> Interstate (TDOT)  : 3
```

**Wide-arterial old-vs-new** (crash counts by jurisdiction):

| street | OLD City/TDOT | NEW City/TDOT/Int/Ramp |
|---|---|---|
| POPLAR | 29/19 | 28/20/0/0 |
| LAMAR | 3/31 | 0/34/0/0 |
| SUMMER | 6/14 | 1/19/0/0 |
| UNION | 6/33 | 2/37/0/0 |
| JACKSON | 3/17 | 1/19/0/0 |
| PARK | 28/3 | 31/0/0/0 |
| GETWELL | 15/4 | 11/8/0/0 |
| WINCHESTER | 32/0 | 31/0/0/1 |
| AIRWAYS | 8/9 | 12/5/0/0 |

**Join-quality watchlist** — 3 of the 122 TDOT→City crashes sit on a segment that overlaps a state route ≥30% yet was tagged City (possible under-tagged carriageway / name gap — eyeball these; the rest are genuine city cross-streets near intersections):
```
  300968447 E RAINES RD          ov10=1.00 oldDistToSR=3.5m  (35.03850,-89.91717)
  300981287 N BELLEVUE BLVD      ov10=0.90 oldDistToSR=10.5m  (35.15429,-90.01961)
  300953626 JACKSON AVE          ov10=0.39 oldDistToSR=2.8m  (35.17769,-89.93764)
```

**Reframe check:** new surface split City 79.6% vs TDOT 20.4% — City still owns the majority of surface crashes; fatal surface City 71.8% vs TDOT 28.2%.

## Phase 4 — display layer

Wrote `ownership_segments.geojson`: 2968 Memphis state-route/interstate segments (0.89 MB, simplified, EPSG:4326).
